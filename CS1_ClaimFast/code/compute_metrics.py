"""
ClaimFast – Comprehensive Metrics & Evaluation Analysis Engine

Reads:
- Gold labels: data/test.jsonl (60 records)
- Model predictions: outputs/evaluation_results.jsonl (900 records)

Computes:
1. Full dataset and execution integrity audit (job IDs, missing, duplicate, model, temperature, keys).
2. Diagnostic audit of non-SUCCESS results (validation errors, API errors, raw output analysis).
3. Overall strict exact match (all 9 fields identical to gold).
4. Field-by-field accuracy across all 9 target fields.
5. Multi-class classification metrics (Precision, Recall, Macro-F1) for claim_type and urgency.
6. Confusion matrices for claim_type and urgency.
7. System performance & latency statistics (mean, median, p95, p99, min, max).
8. Token usage (input, output, total) and cost estimation per 1,000 queries.
9. Run-to-run consistency & stability analysis (unanimous 3-run agreement, pairwise agreement).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


BASE_DIR = Path(__file__).resolve().parent.parent
TEST_FILE = BASE_DIR / "data" / "test.jsonl"
EVAL_FILE = BASE_DIR / "outputs" / "evaluation_results.jsonl"

STRATEGIES = [
    "zero_shot",
    "few_shot_k3",
    "few_shot_k5",
    "few_shot_k8",
    "structured_reasoning",
]

CLAIM_TYPES = [
    "own_damage",
    "third_party_liability",
    "theft",
    "total_loss",
    "glass_only",
    "not_a_claim",
]

URGENCY_LEVELS = ["high", "medium", "low"]

EXTRACTION_FIELDS = [
    "claim_type",
    "urgency",
    "policy_number",
    "incident_date",
    "location",
    "vehicle_reg_no",
    "estimated_amount_inr",
    "injury_reported",
    "police_report_filed",
]


def normalize_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s.lower() if s else None


def normalize_reg(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = re.sub(r"\s+", "", str(val)).upper()
    return s if s else None


def load_gold_records(path: Path) -> Dict[str, Dict[str, Any]]:
    records = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            records[d["id"]] = d
    return records


def load_eval_records(path: Path) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def compute_f1_scores(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


def main():
    print("=" * 80)
    print("CLAIMFAST COMPREHENSIVE EVALUATION ANALYSIS")
    print("=" * 80)

    gold_records = load_gold_records(TEST_FILE)
    eval_records = load_eval_records(EVAL_FILE)

    print(f"Total Gold Test Records Loaded:     {len(gold_records)}")
    print(f"Total Evaluation Results Loaded:    {len(eval_records)}")

    # 1. Integrity Verification
    expected_jobs = set()
    for strat in STRATEGIES:
        for rec_id in gold_records.keys():
            for r in [1, 2, 3]:
                expected_jobs.add(f"{strat}_{rec_id}_run{r}")

    actual_jobs = [r["job_id"] for r in eval_records]
    actual_job_set = set(actual_jobs)

    print("\n--- Integrity Audit ---")
    print(f"Expected Unique Job IDs:            {len(expected_jobs)}")
    print(f"Actual Unique Job IDs in Log:       {len(actual_job_set)}")
    print(f"Total Records in File:              {len(actual_jobs)}")
    
    missing_jobs = expected_jobs - actual_job_set
    extra_jobs = actual_job_set - expected_jobs
    duplicates = [j for j, count in Counter(actual_jobs).items() if count > 1]

    print(f"Missing Jobs:                       {len(missing_jobs)} {list(missing_jobs)[:3] if missing_jobs else ''}")
    print(f"Extra Jobs:                         {len(extra_jobs)} {list(extra_jobs)[:3] if extra_jobs else ''}")
    print(f"Duplicate Jobs:                     {len(duplicates)} {duplicates[:3] if duplicates else ''}")

    # Model and configuration audit
    models = Counter(r.get("model_name") for r in eval_records)
    print(f"Models Utilized:                    {dict(models)}")
    keys_used = Counter(r.get("credential_alias") for r in eval_records)
    print(f"Credential Allocation:              {dict(keys_used)}")

    # Execution status breakdown
    statuses = Counter(r.get("status") for r in eval_records)
    print(f"Status Breakdown:                   {dict(statuses)}")

    # 2. Detailed Non-Success Audit
    failed_records = [r for r in eval_records if r.get("status") != "SUCCESS"]
    print(f"\n--- Diagnostic Audit of Failures & Validation Errors ({len(failed_records)} records) ---")
    for idx, fr in enumerate(failed_records, 1):
        print(f"\n[{idx}] Job ID: {fr['job_id']}")
        print(f"    Strategy: {fr['prompt_strategy']} | Record: {fr['record_id']} | Run: {fr['run_number']}")
        print(f"    Status: {fr['status']} | Error Category: {fr['error_category']}")
        print(f"    Error Message: {fr['error_message']}")
        print(f"    Raw Output: {fr.get('raw_response', '')[:160]}...")
        if fr.get("parsed_response"):
            print(f"    Parsed Keys: {list(fr['parsed_response'].keys())}")
        gold = gold_records.get(fr["record_id"], {})
        print(f"    Gold Label: claim_type='{gold.get('claim_type')}', urgency='{gold.get('urgency')}', amt={gold.get('estimated_amount_inr')}, inj={gold.get('injury_reported')}, pol={gold.get('police_report_filed')}")

    # 3. Comprehensive Evaluation Metrics
    # We evaluate overall and by prompt strategy
    groups = {s: [] for s in STRATEGIES}
    for r in eval_records:
        groups[r["prompt_strategy"]].append(r)

    print("\n" + "=" * 80)
    print("PERFORMANCE & ACCURACY MATRIX BY PROMPT STRATEGY")
    print("=" * 80)

    # Header
    print(f"{'Metric':<32} | {'Zero-Shot':<10} | {'FewShot-k3':<10} | {'FewShot-k5':<10} | {'FewShot-k8':<10} | {'StructReason':<12} | {'Overall':<10}")
    print("-" * 105)

    def evaluate_subset(recs: List[Dict[str, Any]]):
        n = len(recs)
        if n == 0:
            return {}

        valid_schema_count = sum(1 for r in recs if r.get("status") == "SUCCESS")
        
        field_matches = {f: 0 for f in EXTRACTION_FIELDS}
        field_matches_normalized_loc = 0
        field_matches_normalized_reg = 0
        strict_exact_matches = 0

        # Classification tallies
        ct_gold_counts = Counter()
        ct_pred_counts = Counter()
        ct_tp = Counter()
        ct_fp = Counter()
        ct_fn = Counter()

        urg_gold_counts = Counter()
        urg_pred_counts = Counter()
        urg_tp = Counter()
        urg_fp = Counter()
        urg_fn = Counter()

        latencies = []
        in_tokens = []
        out_tokens = []
        tot_tokens = []

        for r in recs:
            rec_id = r["record_id"]
            gold = gold_records[rec_id]
            pred = r.get("parsed_response") or {}
            status = r.get("status")

            if r.get("latency_ms") and r["latency_ms"] > 0:
                latencies.append(r["latency_ms"])
            if r.get("input_tokens") is not None:
                in_tokens.append(r["input_tokens"])
            if r.get("output_tokens") is not None:
                out_tokens.append(r["output_tokens"])
            if r.get("total_tokens") is not None:
                tot_tokens.append(r["total_tokens"])

            # Strict check
            record_strict_match = (status == "SUCCESS")

            for f in EXTRACTION_FIELDS:
                g_val = gold.get(f)
                p_val = pred.get(f)

                # Special field checks
                if f == "location":
                    exact_m = (p_val == g_val)
                    norm_m = (normalize_str(p_val) == normalize_str(g_val))
                    if exact_m:
                        field_matches[f] += 1
                    if norm_m:
                        field_matches_normalized_loc += 1
                    if not exact_m:
                        record_strict_match = False
                elif f == "vehicle_reg_no":
                    exact_m = (p_val == g_val)
                    norm_m = (normalize_reg(p_val) == normalize_reg(g_val))
                    if exact_m:
                        field_matches[f] += 1
                    if norm_m:
                        field_matches_normalized_reg += 1
                    if not exact_m:
                        record_strict_match = False
                elif f == "estimated_amount_inr":
                    if p_val == g_val:
                        field_matches[f] += 1
                    else:
                        record_strict_match = False
                else:
                    if p_val == g_val:
                        field_matches[f] += 1
                    else:
                        record_strict_match = False

            if record_strict_match:
                strict_exact_matches += 1

            # Claim type confusion tallies
            g_ct = gold.get("claim_type")
            p_ct = pred.get("claim_type")
            ct_gold_counts[g_ct] += 1
            if p_ct:
                ct_pred_counts[p_ct] += 1
            if p_ct == g_ct:
                ct_tp[g_ct] += 1
            else:
                ct_fn[g_ct] += 1
                if p_ct in CLAIM_TYPES:
                    ct_fp[p_ct] += 1

            # Urgency confusion tallies
            g_urg = gold.get("urgency")
            p_urg = pred.get("urgency")
            urg_gold_counts[g_urg] += 1
            if p_urg:
                urg_pred_counts[p_urg] += 1
            if p_urg == g_urg:
                urg_tp[g_urg] += 1
            else:
                urg_fn[g_urg] += 1
                if p_urg in URGENCY_LEVELS:
                    urg_fp[p_urg] += 1

        # Macro-F1 for claim_type
        ct_precs, ct_recs, ct_f1s = [], [], []
        for c in CLAIM_TYPES:
            tp = ct_tp[c]
            fp = ct_fp[c]
            fn = ct_fn[c]
            p, rc, f1 = compute_f1_scores(tp, fp, fn)
            ct_precs.append(p)
            ct_recs.append(rc)
            ct_f1s.append(f1)
        ct_macro_p = sum(ct_precs) / len(ct_precs)
        ct_macro_r = sum(ct_recs) / len(ct_recs)
        ct_macro_f1 = sum(ct_f1s) / len(ct_f1s)

        # Macro-F1 for urgency
        urg_precs, urg_recs, urg_f1s = [], [], []
        for u in URGENCY_LEVELS:
            tp = urg_tp[u]
            fp = urg_fp[u]
            fn = urg_fn[u]
            p, rc, f1 = compute_f1_scores(tp, fp, fn)
            urg_precs.append(p)
            urg_recs.append(rc)
            urg_f1s.append(f1)
        urg_macro_p = sum(urg_precs) / len(urg_precs)
        urg_macro_r = sum(urg_recs) / len(urg_recs)
        urg_macro_f1 = sum(urg_f1s) / len(urg_f1s)

        return {
            "n": n,
            "valid_schema_rate": valid_schema_count / n,
            "strict_exact_match": strict_exact_matches / n,
            "claim_type_acc": field_matches["claim_type"] / n,
            "claim_type_macro_f1": ct_macro_f1,
            "claim_type_macro_p": ct_macro_p,
            "claim_type_macro_r": ct_macro_r,
            "urgency_acc": field_matches["urgency"] / n,
            "urgency_macro_f1": urg_macro_f1,
            "urgency_macro_p": urg_macro_p,
            "urgency_macro_r": urg_macro_r,
            "policy_number_acc": field_matches["policy_number"] / n,
            "incident_date_acc": field_matches["incident_date"] / n,
            "location_acc": field_matches["location"] / n,
            "location_norm_acc": field_matches_normalized_loc / n,
            "vehicle_reg_acc": field_matches["vehicle_reg_no"] / n,
            "vehicle_reg_norm_acc": field_matches_normalized_reg / n,
            "estimated_amount_acc": field_matches["estimated_amount_inr"] / n,
            "injury_reported_acc": field_matches["injury_reported"] / n,
            "police_report_acc": field_matches["police_report_filed"] / n,
            "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "median_latency_ms": sorted(latencies)[len(latencies)//2] if latencies else 0.0,
            "p95_latency_ms": sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0.0,
            "mean_in_tokens": sum(in_tokens) / len(in_tokens) if in_tokens else 0.0,
            "mean_out_tokens": sum(out_tokens) / len(out_tokens) if out_tokens else 0.0,
            "mean_tot_tokens": sum(tot_tokens) / len(tot_tokens) if tot_tokens else 0.0,
            "total_tokens_sum": sum(tot_tokens),
            "raw_field_matches": field_matches,
            "raw_strict": strict_exact_matches,
            "ct_per_class": {c: compute_f1_scores(ct_tp[c], ct_fp[c], ct_fn[c]) for c in CLAIM_TYPES},
            "urg_per_class": {u: compute_f1_scores(urg_tp[u], urg_fp[u], urg_fn[u]) for u in URGENCY_LEVELS},
        }

    strat_metrics = {s: evaluate_subset(groups[s]) for s in STRATEGIES}
    overall_metrics = evaluate_subset(eval_records)

    def row_fmt(label: str, key: str, is_pct: bool = True, decimals: int = 1):
        vals = []
        for s in STRATEGIES:
            v = strat_metrics[s].get(key, 0.0)
            if is_pct:
                vals.append(f"{v*100:.{decimals}f}%")
            else:
                vals.append(f"{v:.{decimals}f}")
        ov = overall_metrics.get(key, 0.0)
        if is_pct:
            ov_str = f"{ov*100:.{decimals}f}%"
        else:
            ov_str = f"{ov:.{decimals}f}"
        print(f"{label:<32} | {vals[0]:<10} | {vals[1]:<10} | {vals[2]:<10} | {vals[3]:<10} | {vals[4]:<12} | {ov_str:<10}")

    row_fmt("Evaluated Jobs Count (N)", "n", is_pct=False, decimals=0)
    row_fmt("Valid Schema / JSON Rate", "valid_schema_rate")
    row_fmt("Strict Exact Match (9 Fields)", "strict_exact_match")
    print("-" * 105)
    row_fmt("Claim Type Accuracy", "claim_type_acc")
    row_fmt("Claim Type Macro-F1", "claim_type_macro_f1")
    row_fmt("Urgency Accuracy", "urgency_acc")
    row_fmt("Urgency Macro-F1", "urgency_macro_f1")
    print("-" * 105)
    row_fmt("Policy Number Accuracy", "policy_number_acc")
    row_fmt("Incident Date Accuracy", "incident_date_acc")
    row_fmt("Location (Strict)", "location_acc")
    row_fmt("Location (Normalized)", "location_norm_acc")
    row_fmt("Vehicle Reg No (Strict)", "vehicle_reg_acc")
    row_fmt("Estimated Amount (INR) Acc", "estimated_amount_acc")
    row_fmt("Injury Reported Acc", "injury_reported_acc")
    row_fmt("Police Report Filed Acc", "police_report_acc")
    print("-" * 105)
    row_fmt("Mean Latency (ms)", "mean_latency_ms", is_pct=False, decimals=1)
    row_fmt("Median Latency (ms)", "median_latency_ms", is_pct=False, decimals=1)
    row_fmt("P95 Latency (ms)", "p95_latency_ms", is_pct=False, decimals=1)
    row_fmt("Mean Input Tokens", "mean_in_tokens", is_pct=False, decimals=0)
    row_fmt("Mean Output Tokens", "mean_out_tokens", is_pct=False, decimals=0)
    row_fmt("Mean Total Tokens", "mean_tot_tokens", is_pct=False, decimals=0)
    print("=" * 105)

    # 4. Detailed Cost Analysis
    # Groq pricing for qwen/qwen3.8-27b: $0.20 per 1M input tokens, $0.20 per 1M output tokens
    print("\n--- Estimated Cost per 1,000 Queries (Groq: $0.20/1M In, $0.20/1M Out) ---")
    for s in STRATEGIES:
        m = strat_metrics[s]
        in_cost_1k = (m["mean_in_tokens"] * 1000 / 1_000_000) * 0.20
        out_cost_1k = (m["mean_out_tokens"] * 1000 / 1_000_000) * 0.20
        tot_cost_1k = in_cost_1k + out_cost_1k
        print(f"  {s:<22}: ${tot_cost_1k:.5f} per 1k requests (Input: ${in_cost_1k:.5f}, Output: ${out_cost_1k:.5f})")

    # 5. Run-to-Run Consistency Analysis
    print("\n" + "=" * 80)
    print("RUN-TO-RUN CONSISTENCY & VARIANCE ANALYSIS (Across 3 Runs, 60 Test Messages)")
    print("=" * 80)
    print(f"{'Strategy':<22} | {'Unanimous Strict Match':<24} | {'Unanimous Claim Type':<22} | {'Unanimous Urgency':<20} | {'Pairwise Agreement (Strict)'}")
    print("-" * 115)

    # Group predictions by (strategy, record_id) -> list of 3 runs
    grid: Dict[Tuple[str, str], Dict[int, Dict[str, Any]]] = defaultdict(dict)
    for r in eval_records:
        grid[(r["prompt_strategy"], r["record_id"])][r["run_number"]] = r

    for s in STRATEGIES:
        unanimous_strict = 0
        unanimous_ct = 0
        unanimous_urg = 0
        pairwise_matches = 0
        pairwise_total = 0

        for rec_id in gold_records.keys():
            runs_dict = grid[(s, rec_id)]
            r1 = runs_dict.get(1, {})
            r2 = runs_dict.get(2, {})
            r3 = runs_dict.get(3, {})

            p1 = r1.get("parsed_response") or {}
            p2 = r2.get("parsed_response") or {}
            p3 = r3.get("parsed_response") or {}

            # Strict comparison helper
            def is_same_output(a, b):
                if not a or not b:
                    return a == b
                return all(a.get(f) == b.get(f) for f in EXTRACTION_FIELDS)

            s12 = is_same_output(p1, p2)
            s23 = is_same_output(p2, p3)
            s13 = is_same_output(p1, p3)

            pairwise_matches += (int(s12) + int(s23) + int(s13))
            pairwise_total += 3

            if s12 and s23 and s13:
                unanimous_strict += 1

            # Claim type unanimity
            if p1.get("claim_type") == p2.get("claim_type") == p3.get("claim_type") and p1.get("claim_type") is not None:
                unanimous_ct += 1

            # Urgency unanimity
            if p1.get("urgency") == p2.get("urgency") == p3.get("urgency") and p1.get("urgency") is not None:
                unanimous_urg += 1

        unanimous_strict_pct = (unanimous_strict / 60) * 100
        unanimous_ct_pct = (unanimous_ct / 60) * 100
        unanimous_urg_pct = (unanimous_urg / 60) * 100
        pairwise_pct = (pairwise_matches / pairwise_total) * 100

        print(f"{s:<22} | {unanimous_strict:>2}/60 ({unanimous_strict_pct:5.1f}%)         | {unanimous_ct:>2}/60 ({unanimous_ct_pct:5.1f}%)       | {unanimous_urg:>2}/60 ({unanimous_urg_pct:5.1f}%)     | {pairwise_pct:5.1f}%")

    print("-" * 115)

    # 6. Per-Class Precision, Recall, F1 Breakdown
    print("\n" + "=" * 80)
    print("CLAIM_TYPE PER-CLASS BREAKDOWN (OVERALL 900 JOBS)")
    print("=" * 80)
    print(f"{'Class':<25} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}")
    print("-" * 65)
    for c in CLAIM_TYPES:
        p, r, f1 = overall_metrics["ct_per_class"][c]
        print(f"{c:<25} | {p*100:6.1f}%    | {r*100:6.1f}%    | {f1*100:6.1f}%")

    print("\n" + "=" * 80)
    print("URGENCY PER-CLASS BREAKDOWN (OVERALL 900 JOBS)")
    print("=" * 80)
    print(f"{'Class':<25} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}")
    print("-" * 65)
    for u in URGENCY_LEVELS:
        p, r, f1 = overall_metrics["urg_per_class"][u]
        print(f"{u:<25} | {p*100:6.1f}%    | {r*100:6.1f}%    | {f1*100:6.1f}%")

    # Save summary dictionary to outputs/metrics_summary.json
    summary_path = BASE_DIR / "outputs" / "metrics_summary.json"
    summary_data = {
        "integrity": {
            "total_eval_jobs": len(eval_records),
            "expected_unique_jobs": len(expected_jobs),
            "actual_unique_jobs": len(actual_job_set),
            "missing_jobs_count": len(missing_jobs),
            "duplicate_jobs_count": len(duplicates),
            "models": dict(models),
            "credentials": dict(keys_used),
            "status_breakdown": dict(statuses),
        },
        "overall": {k: v for k, v in overall_metrics.items() if not k.startswith("raw_") and not k.endswith("_class")},
        "by_strategy": {s: {k: v for k, v in strat_metrics[s].items() if not k.startswith("raw_") and not k.endswith("_class")} for s in STRATEGIES},
        "failed_records": [
            {
                "job_id": fr["job_id"],
                "record_id": fr["record_id"],
                "strategy": fr["prompt_strategy"],
                "run": fr["run_number"],
                "status": fr["status"],
                "error_category": fr.get("error_category"),
                "error_message": fr.get("error_message"),
            }
            for fr in failed_records
        ],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\nWrote metrics summary to: {summary_path}")


if __name__ == "__main__":
    main()
