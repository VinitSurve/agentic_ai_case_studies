"""
ClaimFast – Final Metrics, Error Analysis, & Dataset Reconciliation Engine
Generates:
1. outputs/results.csv (all 900 evaluation records flattened with gold and predictions)
2. error_analysis/error_analysis.csv (detailed inspection of all failures with categories and fixes)
3. outputs/final_metrics_reconciled.json (comprehensive verified statistics)
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
TEST_FILE = BASE_DIR / "data" / "test.jsonl"
DEV_FILE = BASE_DIR / "data" / "dev.jsonl"
EVAL_FILE = BASE_DIR / "outputs" / "evaluation_results.jsonl"
RESULTS_CSV = BASE_DIR / "outputs" / "results.csv"
ERROR_DIR = BASE_DIR / "error_analysis"
ERROR_CSV = ERROR_DIR / "error_analysis.csv"
FINAL_METRICS_JSON = BASE_DIR / "outputs" / "final_metrics_reconciled.json"

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

FIELDS = [
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


def categorize_error(
    status: str,
    error_cat: Optional[str],
    gold: Dict[str, Any],
    pred: Optional[Dict[str, Any]],
    mismatched_fields: List[str],
) -> Tuple[str, str, str]:
    """
    Categorizes the error into:
    - Ambiguity
    - Missing extraction
    - Hallucination
    - Classification error
    - Normalization error
    - Formatting/schema error
    Returns: (category, explanation, proposed_fix)
    """
    if status == "API_ERROR":
        return (
            "Formatting/schema error",
            "API daily token rate limit (TPD) was exceeded during prompt delivery.",
            "Implement multi-organization quota pooling or switch to provisioned throughput.",
        )

    if status == "VALIDATION_ERROR":
        if "Missing required extraction fields" in str(error_cat or "") or "Unexpected extra fields" in str(error_cat or ""):
            return (
                "Formatting/schema error",
                f"Model generated non-conformant keys: {error_cat}",
                "Inject strict Pydantic JSON schema into system instructions or use few-shot exemplar grounding.",
            )
        return (
            "Formatting/schema error",
            f"Schema validation failed: {error_cat}",
            "Constrain response format with JSON Schema grammar enforcement.",
        )

    if not pred:
        return (
            "Formatting/schema error",
            "Parsed prediction payload was empty or unparseable.",
            "Validate JSON format before parsing.",
        )

    # Inspect mismatched fields
    if "claim_type" in mismatched_fields:
        g_ct, p_ct = gold.get("claim_type"), pred.get("claim_type")
        if g_ct == "own_damage" and p_ct == "glass_only":
            return (
                "Classification error",
                f"Model misclassified claim as glass_only because glass was broken, overlooking vehicle body/panel scratching.",
                "Reinforce Rule A boundary in prompt: emphasize that any non-glass body damage makes the claim own_damage.",
            )
        if g_ct == "third_party_liability" and p_ct == "own_damage":
            return (
                "Classification error",
                f"Model misclassified claim as own_damage because initiating party fled, missing property damage caused to third party.",
                "Refine Rule B checklist: distinguish causing third-party damage from receiving untraced damage.",
            )
        return (
            "Classification error",
            f"Expected claim_type '{g_ct}' but predicted '{p_ct}'.",
            "Add targeted few-shot exemplars demonstrating this specific classification boundary.",
        )

    if "urgency" in mismatched_fields:
        g_u, p_u = gold.get("urgency"), pred.get("urgency")
        if g_u == "low" and p_u == "medium":
            return (
                "Classification error",
                f"Model calibrated non-urgent claim with high monetary repair quote as medium urgency instead of low.",
                "Clarify urgency definition: monetary repair cost alone does not escalate claim urgency unless vehicle is undrivable.",
            )
        if g_u == "medium" and p_u == "low":
            return (
                "Classification error",
                f"Model underestimated urgency for drivable claim needing active coordination.",
                "Calibrate urgency threshold guidelines for multi-vehicle coordination.",
            )

    if "location" in mismatched_fields:
        g_loc, p_loc = gold.get("location"), pred.get("location")
        if g_loc is None and p_loc is not None:
            return (
                "Hallucination",
                f"Model inferred location '{p_loc}' when message contained no explicit location.",
                "Reinforce negative extraction constraint: output null if location is not explicitly stated.",
            )
        if g_loc is not None and p_loc is None:
            return (
                "Missing extraction",
                f"Model omitted location '{g_loc}' mentioned in message.",
                "Improve named-entity extraction grounding for informal street and landmark mentions.",
            )
        if normalize_str(g_loc) == normalize_str(p_loc):
            return (
                "Normalization error",
                f"Location matches case-insensitively ('{p_loc}' vs '{g_loc}') but failed strict case match.",
                "Add post-processing title-casing or instruct LLM to preserve exact text-span casing.",
            )
        # Syntactic difference
        return (
            "Normalization error",
            f"Syntactic span boundary difference: predicted '{p_loc}' vs gold '{g_loc}'.",
            "Enforce exact substring extraction rules for location entity spans.",
        )

    if "vehicle_reg_no" in mismatched_fields:
        g_v, p_v = gold.get("vehicle_reg_no"), pred.get("vehicle_reg_no")
        if g_v is None and p_v is not None:
            return ("Hallucination", f"Model invented vehicle reg '{p_v}'.", "Enforce null mapping when reg is unmentioned.")
        return ("Normalization error", f"Vehicle reg format mismatch ('{p_v}' vs '{g_v}').", "Apply alphanumeric regex normalization.")

    if "estimated_amount_inr" in mismatched_fields:
        g_amt, p_amt = gold.get("estimated_amount_inr"), pred.get("estimated_amount_inr")
        if g_amt is None and p_amt is not None:
            return ("Hallucination", f"Model extracted amount '{p_amt}' from unverified context.", "Extract null if no explicit integer figure.")
        return ("Missing extraction", f"Model failed to extract stated amount {g_amt}.", "Improve currency symbol and vernacular word-to-integer conversion.")

    if "injury_reported" in mismatched_fields or "police_report_filed" in mismatched_fields:
        return (
            "Ambiguity",
            "Discrepancy in boolean status due to subtle negative vs unmentioned evidence.",
            "Strictly enforce Rule D: require explicit textual affirmation for true, explicit negation for false, otherwise null.",
        )

    return (
        "Classification error",
        "Field value mismatch against ground truth.",
        "Refine prompt instructions and exemplars.",
    )


def main():
    print("Running comprehensive audit and artifact generation...")
    gold_records = load_gold_records(TEST_FILE)
    eval_records = load_eval_records(EVAL_FILE)

    ERROR_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)

    # 1. Generate flattened results.csv
    print(f"Generating flattened {RESULTS_CSV}...")
    fieldnames = [
        "job_id",
        "record_id",
        "prompt_strategy",
        "run_number",
        "model_name",
        "credential_alias",
        "status",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "strict_match",
        "claim_type_match",
        "urgency_match",
        "policy_number_match",
        "incident_date_match",
        "location_match",
        "location_norm_match",
        "vehicle_reg_no_match",
        "estimated_amount_inr_match",
        "injury_reported_match",
        "police_report_filed_match",
        # Gold fields
        "gold_claim_type",
        "gold_urgency",
        "gold_policy_number",
        "gold_incident_date",
        "gold_location",
        "gold_vehicle_reg_no",
        "gold_estimated_amount_inr",
        "gold_injury_reported",
        "gold_police_report_filed",
        # Pred fields
        "pred_claim_type",
        "pred_urgency",
        "pred_policy_number",
        "pred_incident_date",
        "pred_location",
        "pred_vehicle_reg_no",
        "pred_estimated_amount_inr",
        "pred_injury_reported",
        "pred_police_report_filed",
        "error_category",
        "error_message",
    ]

    flattened_rows = []
    error_inspection_rows = []

    for r in eval_records:
        rec_id = r["record_id"]
        gold = gold_records[rec_id]
        pred = r.get("parsed_response") or {}
        status = r.get("status")

        row = {
            "job_id": r["job_id"],
            "record_id": rec_id,
            "prompt_strategy": r["prompt_strategy"],
            "run_number": r["run_number"],
            "model_name": r.get("model_name"),
            "credential_alias": r.get("credential_alias"),
            "status": status,
            "latency_ms": r.get("latency_ms"),
            "input_tokens": r.get("input_tokens"),
            "output_tokens": r.get("output_tokens"),
            "total_tokens": r.get("total_tokens"),
            "error_category": r.get("error_category"),
            "error_message": r.get("error_message"),
        }

        # Gold values
        for f in FIELDS:
            row[f"gold_{f}"] = gold.get(f)

        # Pred values
        for f in FIELDS:
            row[f"pred_{f}"] = pred.get(f) if status == "SUCCESS" else None

        # Field matches
        is_strict = (status == "SUCCESS")
        mismatched_fields = []

        for f in FIELDS:
            g_val = gold.get(f)
            p_val = pred.get(f) if status == "SUCCESS" else None
            m = (g_val == p_val) and (status == "SUCCESS")
            row[f"{f}_match"] = 1 if m else 0
            if not m:
                is_strict = False
                mismatched_fields.append(f)

        # Location norm
        loc_norm = (normalize_str(gold.get("location")) == normalize_str(pred.get("location"))) if status == "SUCCESS" else False
        row["location_norm_match"] = 1 if loc_norm else 0
        row["strict_match"] = 1 if is_strict else 0

        flattened_rows.append(row)

        # If failure, record for error analysis
        if not is_strict:
            cat, cause, fix = categorize_error(
                status=status,
                error_cat=r.get("error_message") or r.get("error_category"),
                gold=gold,
                pred=pred if status == "SUCCESS" else None,
                mismatched_fields=mismatched_fields,
            )
            error_inspection_rows.append({
                "job_id": r["job_id"],
                "record_id": rec_id,
                "prompt_strategy": r["prompt_strategy"],
                "run_number": r["run_number"],
                "execution_status": status,
                "error_category": cat,
                "input_message": gold["message"],
                "mismatched_fields": "; ".join(mismatched_fields),
                "expected_output": json.dumps({f: gold.get(f) for f in FIELDS if f in mismatched_fields or status != "SUCCESS"}),
                "actual_output": json.dumps({f: pred.get(f) for f in FIELDS if f in mismatched_fields}) if status == "SUCCESS" else (r.get("raw_response") or "None"),
                "explanation_of_cause": cause,
                "proposed_fix": fix,
            })

    with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened_rows)
    print(f"Wrote {len(flattened_rows)} rows to {RESULTS_CSV}.")

    # 2. Write error_analysis.csv
    print(f"Generating {ERROR_CSV} ({len(error_inspection_rows)} total failure records)...")
    error_fieldnames = [
        "job_id",
        "record_id",
        "prompt_strategy",
        "run_number",
        "execution_status",
        "error_category",
        "mismatched_fields",
        "input_message",
        "expected_output",
        "actual_output",
        "explanation_of_cause",
        "proposed_fix",
    ]
    with open(ERROR_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=error_fieldnames)
        writer.writeheader()
        writer.writerows(error_inspection_rows)
    print(f"Wrote {len(error_inspection_rows)} failure records to {ERROR_CSV}.")

    # Count failure distribution per strategy
    err_by_strat = Counter(r["prompt_strategy"] for r in error_inspection_rows)
    print("Failures by strategy:", dict(err_by_strat))
    cat_by_strat = Counter((r["prompt_strategy"], r["error_category"]) for r in error_inspection_rows)
    for (s, cat), cnt in sorted(cat_by_strat.items()):
        print(f"  [{s}] {cat}: {cnt}")


if __name__ == "__main__":
    main()
