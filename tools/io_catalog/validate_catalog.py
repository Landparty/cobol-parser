#!/usr/bin/env python3
"""
Validate IO variation catalog against IBM reference rules.

This script ensures the catalog entries match IBM Enterprise COBOL reference guidelines:
- All verbs are canonical IBM IO verbs
- File organizations match verb constraints
- Qualifiers follow syntactic rules
- Entries are consistently formatted

Usage:
    python validate_catalog.py --catalog <path-to-csv> [--output report.json] [--strict]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Valid verbs per IBM reference
VALID_VERBS = {
    "OPEN",
    "CLOSE",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "START",
    "ACCEPT",
    "DISPLAY",
    "UNLOCK",
}

# Valid file organizations
VALID_FILE_ORGS = {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM", "N/A"}

# Valid access modes
VALID_ACCESS_MODES = {
    "INPUT",
    "OUTPUT",
    "I-O",
    "EXTEND",
    "SEQUENTIAL",
    "RANDOM",
    "DYNAMIC",
    "N/A",
}

# Verb-to-org constraints (simplified)
VERB_ORG_RULES = {
    "OPEN": {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM"},
    "CLOSE": {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM", "N/A"},
    "READ": {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM"},
    "WRITE": {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM"},
    "REWRITE": {"SEQUENTIAL", "INDEXED", "RELATIVE", "VSAM"},
    "DELETE": {"INDEXED", "RELATIVE", "VSAM", "SEQUENTIAL"},
    "START": {"INDEXED", "RELATIVE", "VSAM"},
    "ACCEPT": {"N/A"},
    "DISPLAY": {"N/A"},
    "UNLOCK": {"INDEXED", "RELATIVE", "VSAM"},
}


def validate_row(row: dict[str, str], row_num: int, errors: list[str]) -> bool:
    """Validate a single catalog row. Returns True if valid."""
    valid = True

    # Check ID is non-empty
    if not row.get("id", "").strip():
        errors.append(f"Row {row_num}: Missing or empty 'id' field")
        valid = False

    # Check verb is valid
    verb = row.get("verb", "").strip().upper()
    if verb not in VALID_VERBS:
        errors.append(f"Row {row_num} ({row.get('id')}): Invalid verb '{verb}'")
        valid = False

    # Check file_organization is valid
    org = row.get("file_organization", "").strip().upper()
    if org not in VALID_FILE_ORGS:
        errors.append(
            f"Row {row_num} ({row.get('id')}): Invalid file_organization '{org}'"
        )
        valid = False

    # Check verb-org combination
    if verb in VERB_ORG_RULES:
        allowed_orgs = VERB_ORG_RULES[verb]
        if org not in allowed_orgs:
            errors.append(
                f"Row {row_num} ({row.get('id')}): Verb '{verb}' does not support organization '{org}' "
                f"(allowed: {allowed_orgs})"
            )
            valid = False

    # Check access_mode is valid
    access_mode = row.get("access_mode", "").strip().upper()
    if access_mode and access_mode not in VALID_ACCESS_MODES:
        errors.append(
            f"Row {row_num} ({row.get('id')}): Invalid access_mode '{access_mode}' "
            f"(allowed: {VALID_ACCESS_MODES})"
        )
        valid = False

    # Check IBM reference is populated
    if not row.get("ibm_reference", "").strip():
        errors.append(f"Row {row_num} ({row.get('id')}): Missing IBM reference")
        valid = False

    # Check status is one of allowed values
    status = row.get("status", "").strip().upper()
    allowed_statuses = {"PENDING", "COVERED", "GAP", "MISSING", "EXCLUDED"}
    if status not in allowed_statuses:
        errors.append(
            f"Row {row_num} ({row.get('id')}): Invalid status '{status}' "
            f"(allowed: {allowed_statuses})"
        )
        valid = False

    return valid


def validate_catalog(
    catalog_path: Path, strict: bool = False
) -> tuple[bool, list[str], dict[str, int]]:
    """
    Validate catalog CSV file.

    Returns:
        (all_valid, errors, stats) tuple
    """
    errors: list[str] = []
    stats = {
        "total_rows": 0,
        "valid_rows": 0,
        "invalid_rows": 0,
        "verbs": {},
        "orgs": {},
        "statuses": {},
    }

    if not catalog_path.exists():
        errors.append(f"Catalog file not found: {catalog_path}")
        return False, errors, stats

    try:
        with open(catalog_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                errors.append("Catalog file is empty or has no header")
                return False, errors, stats

            required_fields = {
                "id",
                "verb",
                "file_organization",
                "access_mode",
                "status",
                "ibm_reference",
            }
            if not required_fields.issubset(set(reader.fieldnames)):
                missing = required_fields - set(reader.fieldnames)
                errors.append(f"Missing required columns: {missing}")
                return False, errors, stats

            for row_num, row in enumerate(
                reader, start=2
            ):  # Start at 2 because of header
                stats["total_rows"] += 1

                is_valid = validate_row(row, row_num, errors)
                if is_valid:
                    stats["valid_rows"] += 1
                else:
                    stats["invalid_rows"] += 1

                # Collect statistics
                verb = row.get("verb", "").strip().upper()
                if verb:
                    stats["verbs"][verb] = stats["verbs"].get(verb, 0) + 1

                org = row.get("file_organization", "").strip().upper()
                if org:
                    stats["orgs"][org] = stats["orgs"].get(org, 0) + 1

                status = row.get("status", "").strip().upper()
                if status:
                    stats["statuses"][status] = stats["statuses"].get(status, 0) + 1

    except Exception as e:
        errors.append(f"Error reading catalog: {e}")
        return False, errors, stats

    all_valid = stats["invalid_rows"] == 0
    if not all_valid and strict:
        errors.insert(0, "Catalog validation failed in strict mode")

    return all_valid, errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, required=True, help="Path to IO variation catalog CSV"
    )
    parser.add_argument("--output", type=Path, help="Write report to JSON file")
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors"
    )

    args = parser.parse_args()

    all_valid, errors, stats = validate_catalog(args.catalog, strict=args.strict)

    # Build report
    report = {
        "catalog": str(args.catalog),
        "valid": all_valid,
        "errors": errors,
        "stats": stats,
    }

    # Output to stdout
    print(json.dumps(report, indent=2))

    # Write to file if requested
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
        print(f"\n✅ Report written to {args.output}")

    # Exit with appropriate code
    if not all_valid:
        print(f"\n❌ Catalog validation failed with {len(errors)} error(s)")
        return 1

    print(f"\n✅ Catalog validation passed ({stats['valid_rows']} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
