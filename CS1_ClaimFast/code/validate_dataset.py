import argparse
import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

REQUIRED_FIELDS = {
    "id",
    "message",
    "claim_type",
    "urgency",
    "policy_number",
    "incident_date",
    "location",
    "vehicle_reg_no",
    "estimated_amount_inr",
    "injury_reported",
    "police_report_filed",
    "notes",
}

CLAIM_TYPES = {
    "own_damage",
    "third_party_liability",
    "theft",
    "total_loss",
    "glass_only",
    "not_a_claim",
}

URGENCY_LEVELS = {"high", "medium", "low"}

EXPECTED_DISTRIBUTIONS = {
    "dev": {
        "total": 20,
        "classes": {
            "own_damage": 4,
            "third_party_liability": 4,
            "theft": 3,
            "total_loss": 2,
            "glass_only": 3,
            "not_a_claim": 4,
        },
    },
    "test": {
        "total": 60,
        "classes": {
            "own_damage": 14,
            "third_party_liability": 12,
            "theft": 9,
            "total_loss": 6,
            "glass_only": 9,
            "not_a_claim": 10,
        },
    },
}

VEHICLE_REG_PATTERN = re.compile(
    r"^(?:[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$"
)


def normalize_message(msg: str) -> str:
    """Normalize whitespace and lowercase for duplicate detection."""
    return " ".join(msg.strip().lower().split())


def validate_record(record, line_number, seen_ids, seen_messages=None):
    errors = []

    if not isinstance(record, dict):
        return ["Record must be a JSON object."]

    actual_keys = set(record.keys())
    missing = REQUIRED_FIELDS - actual_keys
    unexpected = actual_keys - REQUIRED_FIELDS

    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
    if unexpected:
        errors.append(f"Unexpected fields: {sorted(unexpected)}")

    if missing:
        return errors

    # ID validation
    record_id = record["id"]
    if not isinstance(record_id, str) or not record_id.strip():
        errors.append("id must be a non-empty string.")
    elif record_id in seen_ids:
        errors.append(f"Duplicate ID in file: '{record_id}'")
    else:
        seen_ids.add(record_id)

    # Message validation
    message = record["message"]
    if not isinstance(message, str) or not message.strip():
        errors.append("Message must be a non-empty string.")
    elif seen_messages is not None:
        norm_msg = normalize_message(message)
        if norm_msg in seen_messages:
            errors.append(
                f"Duplicate message detected (identical to record {seen_messages[norm_msg]})"
            )
        else:
            seen_messages[norm_msg] = record_id

    # Claim type validation
    if record["claim_type"] not in CLAIM_TYPES:
        errors.append(f"Invalid claim_type: '{record['claim_type']}' (allowed: {sorted(CLAIM_TYPES)})")

    # Urgency validation
    if record["urgency"] not in URGENCY_LEVELS:
        errors.append(f"Invalid urgency: '{record['urgency']}' (allowed: {sorted(URGENCY_LEVELS)})")

    # Incident date validation
    incident_date = record["incident_date"]
    if incident_date is not None:
        if not isinstance(incident_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", incident_date):
            errors.append(f"incident_date must use YYYY-MM-DD or null, got: '{incident_date}'")
        else:
            try:
                datetime.date.fromisoformat(incident_date)
            except ValueError:
                errors.append(f"incident_date '{incident_date}' is not a valid calendar date.")

    # Vehicle registration validation
    vehicle = record["vehicle_reg_no"]
    if vehicle is not None:
        if not isinstance(vehicle, str):
            errors.append("vehicle_reg_no must be a string or null.")
        elif " " in vehicle or vehicle != vehicle.upper():
            errors.append(f"vehicle_reg_no must be uppercase without spaces: '{vehicle}'")
        elif not VEHICLE_REG_PATTERN.match(vehicle):
            errors.append(f"vehicle_reg_no '{vehicle}' does not match standard registration format.")

    # Estimated amount validation
    amount = record["estimated_amount_inr"]
    if amount is not None:
        if type(amount) is not int or amount < 0:
            errors.append(f"estimated_amount_inr must be a non-negative integer or null, got: {amount}")

    # Nullable boolean validation
    for field in ("injury_reported", "police_report_filed"):
        val = record[field]
        if val is not None and type(val) is not bool:
            errors.append(f"{field} must be true, false or null, got: {val}")

    # String or null validation
    for field in ("policy_number", "location"):
        val = record[field]
        if val is not None and not isinstance(val, str):
            errors.append(f"{field} must be a string or null.")

    # Notes validation
    notes = record["notes"]
    if not isinstance(notes, str) or not notes.strip():
        errors.append("notes must be a non-empty string.")

    # Semantic cross-checks
    if record["injury_reported"] is True and record["urgency"] != "high":
        errors.append(f"Rule 3 violation: injury_reported is true, but urgency is '{record['urgency']}' (must be 'high').")

    return errors


def validate_file(
    file_path: Path,
    expected_split: str = None,
    shared_ids: set = None,
    shared_messages: dict = None,
):
    path = Path(file_path)
    seen_ids = set()
    seen_messages = {}
    class_counts = Counter()
    urgency_counts = Counter()
    total_physical_lines = 0
    non_empty_records = 0
    empty_lines = 0
    failed = 0
    all_errors = []

    print(f"\n==================================================")
    print(f"Validating file: {path}")
    print(f"==================================================")

    if not path.exists():
        print(f"ERROR: File does not exist: {path}")
        return False, 0, Counter()

    with open(path, "r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            total_physical_lines += 1
            line = raw_line.strip()

            # Empty lines check: The validator must fail if blank lines are present
            if not line:
                empty_lines += 1
                failed += 1
                msg = f"Line {line_number}: Unexpected blank line detected."
                print(msg)
                all_errors.append(msg)
                continue

            non_empty_records += 1

            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                failed += 1
                msg = f"Line {line_number}: Invalid JSON: {error}"
                print(msg)
                all_errors.append(msg)
                continue

            rec_id = record.get("id")

            # Check cross-dataset duplicate ID
            if shared_ids is not None and isinstance(rec_id, str):
                if rec_id in shared_ids:
                    msg = f"Line {line_number}: Duplicate ID across datasets: '{rec_id}'"
                    print(msg)
                    all_errors.append(msg)
                    failed += 1

            # Check cross-dataset duplicate message
            rec_msg = record.get("message")
            if shared_messages is not None and isinstance(rec_msg, str):
                norm = normalize_message(rec_msg)
                if norm in shared_messages:
                    msg = f"Line {line_number}: Duplicate message across datasets (matches {shared_messages[norm]}): '{rec_msg[:50]}...'"
                    print(msg)
                    all_errors.append(msg)
                    failed += 1

            errors = validate_record(record, line_number, seen_ids, seen_messages)

            if errors:
                failed += 1
                for error in errors:
                    msg = f"Line {line_number} (ID: {record.get('id', 'unknown')}): {error}"
                    print(msg)
                    all_errors.append(msg)
            else:
                class_counts[record["claim_type"]] += 1
                urgency_counts[record["urgency"]] += 1

            if shared_ids is not None and isinstance(rec_id, str):
                shared_ids.add(rec_id)
            if shared_messages is not None and isinstance(rec_msg, str):
                shared_messages[normalize_message(rec_msg)] = rec_id

    # Detect split if not explicitly provided
    detected_split = expected_split
    if detected_split is None:
        name_lower = path.name.lower()
        if "dev" in name_lower:
            detected_split = "dev"
        elif "test" in name_lower:
            detected_split = "test"

    distribution_passed = True
    if detected_split in EXPECTED_DISTRIBUTIONS:
        expected = EXPECTED_DISTRIBUTIONS[detected_split]
        print(f"\n--- Checking {detected_split.upper()} split requirements ---")
        expected_total = expected["total"]

        # Check physical record counts
        if total_physical_lines != expected_total:
            distribution_passed = False
            msg = f"Physical line count mismatch: Expected {expected_total}, got {total_physical_lines}"
            print(f"ERROR: {msg}")
            all_errors.append(msg)
        else:
            print(f"✓ Physical line count: {total_physical_lines} (matches expected {expected_total})")

        if non_empty_records != expected_total:
            distribution_passed = False
            msg = f"Non-empty record count mismatch: Expected {expected_total}, got {non_empty_records}"
            print(f"ERROR: {msg}")
            all_errors.append(msg)
        else:
            print(f"✓ Non-empty records:   {non_empty_records} (matches expected {expected_total})")

        print("\nClaim type distribution:")
        for c_type, exp_cnt in expected["classes"].items():
            act_cnt = class_counts.get(c_type, 0)
            status = "✓" if act_cnt == exp_cnt else "✗ MISMATCH"
            if act_cnt != exp_cnt:
                distribution_passed = False
                all_errors.append(f"Distribution mismatch for '{c_type}': expected {exp_cnt}, got {act_cnt}")
            print(f"  {status:10} {c_type:22} : actual {act_cnt:2} / expected {exp_cnt:2}")
    else:
        print(f"\nDistribution breakdown (no split target enforced):")
        for c_type, count in sorted(class_counts.items()):
            print(f"  {c_type:22}: {count:2}")

    print("\nUrgency distribution:")
    for urg, count in sorted(urgency_counts.items()):
        print(f"  {urg:10}: {count:2}")

    print("\n--- Summary ---")
    print(f"Physical lines:    {total_physical_lines}")
    print(f"Non-empty records: {non_empty_records}")
    print(f"Empty lines:       {empty_lines}")
    print(f"Valid records:     {non_empty_records - (failed - empty_lines)}")
    print(f"Failed items:      {failed}")

    overall_success = (failed == 0) and distribution_passed
    if overall_success:
        print("\nRESULT: PASSED")
    else:
        print(f"\nRESULT: FAILED ({len(all_errors)} errors detected)")

    return overall_success, non_empty_records, class_counts


def main():
    parser = argparse.ArgumentParser(description="Validate ClaimFast JSONL datasets.")
    parser.add_argument("files", nargs="*", type=Path, help="JSONL file(s) to validate.")
    parser.add_argument("--dev", type=Path, default=None, help="Path to dev.jsonl")
    parser.add_argument("--test", type=Path, default=None, help="Path to test.jsonl")
    args = parser.parse_args()

    files_to_validate = []

    if args.dev or args.test:
        if args.dev:
            files_to_validate.append((args.dev, "dev"))
        if args.test:
            files_to_validate.append((args.test, "test"))
    elif args.files:
        for f in args.files:
            name_lower = f.name.lower()
            split = "dev" if "dev" in name_lower else ("test" if "test" in name_lower else None)
            files_to_validate.append((f, split))
    else:
        base_data = Path(__file__).parent.parent / "data"
        dev_file = base_data / "dev.jsonl"
        test_file = base_data / "test.jsonl"
        if dev_file.exists():
            files_to_validate.append((dev_file, "dev"))
        if test_file.exists():
            files_to_validate.append((test_file, "test"))

    if not files_to_validate:
        parser.print_help()
        sys.exit(1)

    shared_ids = set()
    shared_messages = {}
    all_passed = True

    for file_path, split in files_to_validate:
        passed, _, _ = validate_file(
            file_path,
            expected_split=split,
            shared_ids=shared_ids,
            shared_messages=shared_messages,
        )
        if not passed:
            all_passed = False

    print("\n==================================================")
    if all_passed:
        print("OVERALL DATASET VALIDATION: PASSED")
    else:
        print("OVERALL DATASET VALIDATION: FAILED")
    print("==================================================")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
