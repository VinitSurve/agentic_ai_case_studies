"""
ClaimFast – Evaluation Experiment Runner

Coordinates structured evaluation across:
- 5 prompt strategies (zero_shot, few_shot_k3, few_shot_k5, few_shot_k8, structured_reasoning)
- 60 held-out test records (TEST001–TEST060)
- 3 repeated stochastic runs
- Total: 900 distinct evaluation jobs

Features:
- Deterministic, unique job IDs: {strategy}_{record_id}_run{run_number}
- Atomic append-only progress persistence (immediate flush to JSONL)
- Complete resumability: skips already completed jobs on restart
- Dry-run validation and status reporting without making API requests
- Safe error recording without aborting the experiment
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_code_dir = str(Path(__file__).resolve().parent)
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

from groq_client import GenerationResult, GroqClient
from groq_config import GroqConfig
from groq_key_manager import GroqKeyManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ClaimFast.EvaluationRunner")

ALL_STRATEGIES: List[str] = [
    "zero_shot",
    "few_shot_k3",
    "few_shot_k5",
    "few_shot_k8",
    "structured_reasoning",
]


def load_test_records(test_path: Path) -> List[Dict[str, Any]]:
    """Load and parse test records from test.jsonl."""
    if not test_path.is_file():
        raise FileNotFoundError(f"Test dataset not found at: {test_path}")

    records: List[Dict[str, Any]] = []
    with open(test_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(data)
    return records


def load_prompt_templates(prompt_dir: Path) -> Dict[str, str]:
    """Load all prompt template text files into memory."""
    templates: Dict[str, str] = {}
    for strategy in ALL_STRATEGIES:
        tpl_path = prompt_dir / f"{strategy}.txt"
        if not tpl_path.is_file():
            raise FileNotFoundError(f"Prompt template missing for '{strategy}': {tpl_path}")
        with open(tpl_path, "r", encoding="utf-8") as f:
            templates[strategy] = f.read()
    return templates


def format_prompt(template: str, message: str) -> str:
    """Inject test record message into prompt template."""
    return template.replace("{{message}}", message)


def get_completed_job_ids(output_path: Path) -> Set[str]:
    """Inspect existing output file to find already executed job IDs."""
    completed: Set[str] = set()
    if not output_path.is_file():
        return completed

    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                job_id = record.get("job_id")
                if job_id:
                    completed.add(job_id)
            except Exception:
                continue
    return completed


def build_status_summary(output_path: Path, total_records: int, runs: int) -> Dict[str, Any]:
    """Generate detailed breakdown of completed jobs and API usage."""
    summary: Dict[str, Any] = {
        "total_jobs_target": len(ALL_STRATEGIES) * total_records * runs,
        "total_completed": 0,
        "by_strategy": {s: 0 for s in ALL_STRATEGIES},
        "by_status": {},
        "by_key": {},
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
    }

    if not output_path.is_file():
        return summary

    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                strat = rec.get("prompt_strategy")
                stat = rec.get("status", "UNKNOWN")
                alias = rec.get("credential_alias", "unknown")
                summary["total_completed"] += 1
                if strat in summary["by_strategy"]:
                    summary["by_strategy"][strat] += 1
                summary["by_status"][stat] = summary["by_status"].get(stat, 0) + 1
                summary["by_key"][alias] = summary["by_key"].get(alias, 0) + 1
                summary["total_input_tokens"] += rec.get("input_tokens") or 0
                summary["total_output_tokens"] += rec.get("output_tokens") or 0
                summary["total_tokens"] += rec.get("total_tokens") or 0
            except Exception:
                continue

    return summary


class EvaluationRunner:
    """
    Orchestrates the ClaimFast evaluation matrix across strategies, records, and runs.
    """

    def __init__(
        self,
        client: Optional[GroqClient] = None,
        prompt_dir: Optional[Path] = None,
        test_file: Optional[Path] = None,
        output_file: Optional[Path] = None,
        runs: int = 3,
        strategies: Optional[List[str]] = None,
        delay: Optional[float] = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent
        self.prompt_dir = prompt_dir or (base_dir / "prompts")
        self.test_file = test_file or (base_dir / "data" / "test.jsonl")
        self.output_file = output_file or (base_dir / "outputs" / "evaluation_results.jsonl")
        self.runs = runs
        self.strategies = strategies or ALL_STRATEGIES
        self.client = client

        if delay is not None:
            self.delay = max(0.0, float(delay))
        else:
            try:
                self.delay = max(0.0, float(os.getenv("GROQ_REQUEST_DELAY", "2.0")))
            except ValueError:
                self.delay = 2.0

    def get_client(self) -> GroqClient:
        if self.client is None:
            config = GroqConfig.from_env()
            key_mgr = GroqKeyManager(config)
            self.client = GroqClient(key_manager=key_mgr, config=config)
        return self.client

    def plan_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Compute the full list of evaluation jobs."""
        records = load_test_records(self.test_file)
        if limit is not None and limit > 0:
            records = records[:limit]

        jobs: List[Dict[str, Any]] = []
        for run_no in range(1, self.runs + 1):
            for strat in self.strategies:
                for rec in records:
                    record_id = rec["id"]
                    job_id = f"{strat}_{record_id}_run{run_no}"
                    jobs.append({
                        "job_id": job_id,
                        "record_id": record_id,
                        "prompt_strategy": strat,
                        "run_number": run_no,
                        "message": rec["message"],
                    })
        return jobs

    def run(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute planned jobs. Appends results directly to output JSONL.
        """
        templates = load_prompt_templates(self.prompt_dir)
        planned = self.plan_jobs(limit=limit)
        completed_ids = get_completed_job_ids(self.output_file)

        pending_jobs = [j for j in planned if j["job_id"] not in completed_ids]

        logger.info(
            "Evaluation Matrix Planned: %d total jobs | %d previously completed | %d pending execution",
            len(planned),
            len(completed_ids),
            len(pending_jobs),
        )

        if dry_run:
            logger.info("DRY-RUN enabled: no API calls will be executed.")
            return {
                "dry_run": True,
                "total_planned": len(planned),
                "previously_completed": len(completed_ids),
                "pending": len(pending_jobs),
                "sample_pending_jobs": [j["job_id"] for j in pending_jobs[:5]],
            }

        if not pending_jobs:
            logger.info("All planned jobs are already completed. Nothing to run.")
            return {
                "dry_run": False,
                "total_planned": len(planned),
                "executed": 0,
                "completed": len(completed_ids),
            }

        # Ensure output directory exists
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        client = self.get_client()

        executed_count = 0
        success_count = 0

        with open(self.output_file, "a", encoding="utf-8") as out_f:
            for job in pending_jobs:
                job_id = job["job_id"]
                strat = job["prompt_strategy"]
                record_id = job["record_id"]
                run_no = job["run_number"]
                message = job["message"]

                template = templates[strat]
                full_prompt = format_prompt(template, message)

                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

                gen_result: GenerationResult = client.generate(
                    prompt=full_prompt,
                    json_mode=True,
                    temperature=0.0,
                    record_id=record_id,
                    prompt_strategy=strat,
                )

                result_record = {
                    "job_id": job_id,
                    "record_id": record_id,
                    "prompt_strategy": strat,
                    "run_number": run_no,
                    "model_name": gen_result.model_name or client.config.model,
                    "credential_alias": gen_result.credential_alias,
                    "request_timestamp": timestamp,
                    "latency_ms": round(gen_result.latency_ms, 2),
                    "input_tokens": gen_result.input_tokens,
                    "output_tokens": gen_result.output_tokens,
                    "total_tokens": gen_result.total_tokens,
                    "raw_response": gen_result.raw_response,
                    "parsed_response": gen_result.parsed_json,
                    "status": gen_result.status,
                    "error_category": gen_result.error_category,
                    "error_message": gen_result.error_message,
                }

                out_f.write(json.dumps(result_record, ensure_ascii=False) + "\n")
                out_f.flush()

                executed_count += 1
                if gen_result.success:
                    success_count += 1

                total_now = len(completed_ids) + executed_count
                logger.info(
                    "[%d/%d this run | %d/900 total API calls] Completed %s | status=%s | alias=%s | latency=%.1fms",
                    executed_count,
                    len(pending_jobs),
                    total_now,
                    job_id,
                    gen_result.status,
                    gen_result.credential_alias,
                    gen_result.latency_ms,
                )

                # Pacing delay between requests to avoid rate limits
                if self.delay > 0 and executed_count < len(pending_jobs):
                    time.sleep(self.delay)

        total_completed_now = len(completed_ids) + executed_count
        return {
            "dry_run": False,
            "total_planned": len(planned),
            "executed": executed_count,
            "successes": success_count,
            "total_completed": total_completed_now,
            "api_calls_current_command": executed_count,
            "total_api_calls_till_now": total_completed_now,
            "remaining_target_calls": max(0, 900 - total_completed_now),
        }


def main():
    parser = argparse.ArgumentParser(description="ClaimFast Evaluation Experiment Runner")
    parser.add_argument("--dry-run", action="store_true", help="Plan evaluation without calling APIs")
    parser.add_argument("--strategy", type=str, choices=ALL_STRATEGIES, help="Run only specific strategy")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of test records")
    parser.add_argument("--runs", type=int, default=3, help="Number of repetitions per condition (default 3)")
    parser.add_argument("--status", action="store_true", help="Report status of completed jobs")
    parser.add_argument("--prompt-dir", type=str, default=None, help="Path to prompts directory")
    parser.add_argument("--test-file", type=str, default=None, help="Path to test.jsonl")
    parser.add_argument("--output-file", type=str, default=None, help="Path to outputs file")
    parser.add_argument("--delay", type=float, default=None, help="Pacing delay in seconds between calls (default: env GROQ_REQUEST_DELAY or 2.0s)")

    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    prompt_dir = Path(args.prompt_dir) if args.prompt_dir else base_dir / "prompts"
    test_file = Path(args.test_file) if args.test_file else base_dir / "data" / "test.jsonl"
    output_file = Path(args.output_file) if args.output_file else base_dir / "outputs" / "evaluation_results.jsonl"

    if args.status:
        try:
            records = load_test_records(test_file)
            summary = build_status_summary(output_file, len(records), args.runs)
            tot_target = summary["total_jobs_target"]
            tot_done = summary["total_completed"]
            pct = (tot_done / max(1, tot_target)) * 100
            rem = max(0, tot_target - tot_done)

            print("\n========================================================")
            print("         CLAIMFAST EVALUATION STATUS REPORT             ")
            print("========================================================")
            print(f"Target Total Jobs:              {tot_target}")
            print(f"Total API Calls Made Till Now:  {tot_done} / {tot_target} ({pct:.1f}%)")
            print(f"Remaining API Calls Needed:     {rem}")
            print("\nKey Allocation (From Start to Now):")
            for k, count in summary["by_key"].items():
                k_pct = (count / max(1, tot_done)) * 100
                print(f"  - {k:<28}: {count:3d} calls ({k_pct:.1f}%)")
            print("\nCumulative Token Usage:")
            print(f"  - Input Tokens:               {summary['total_input_tokens']:,}")
            print(f"  - Output Tokens:              {summary['total_output_tokens']:,}")
            print(f"  - Total Tokens:               {summary['total_tokens']:,}")
            print("\nBreakdown by Prompt Strategy:")
            for s, cnt in summary["by_strategy"].items():
                target_per_strat = len(records) * args.runs
                print(f"  - {s:<28}: {cnt:3d} / {target_per_strat:3d} ({cnt / max(1, target_per_strat) * 100:.1f}%)")
            print("\nBreakdown by Execution Status:")
            for stat, cnt in summary["by_status"].items():
                print(f"  - {stat:<28}: {cnt:3d}")
            print("========================================================\n")
        except Exception as e:
            print(f"Error checking status: {e}", file=sys.stderr)
            sys.exit(1)
        return

    selected_strategies = [args.strategy] if args.strategy else ALL_STRATEGIES

    runner = EvaluationRunner(
        prompt_dir=prompt_dir,
        test_file=test_file,
        output_file=output_file,
        runs=args.runs,
        strategies=selected_strategies,
        delay=args.delay,
    )

    res = runner.run(dry_run=args.dry_run, limit=args.limit)
    if not args.dry_run:
        print("\n========================================================")
        print("              EXECUTION BATCH SUMMARY                   ")
        print("========================================================")
        print(f"API Calls Made (This Command):     {res.get('api_calls_current_command', 0)}")
        print(f"Successful Extractions:            {res.get('successes', 0)}")
        print(f"Validation / Schema Errors:        {res.get('executed', 0) - res.get('successes', 0)}")
        print(f"Total API Calls Made Till Now:     {res.get('total_api_calls_till_now', 0)} / 900")
        print(f"Remaining Calls Needed:            {res.get('remaining_target_calls', 0)}")
        print("========================================================\n")
    else:
        print("\nDry Run Complete:")
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

