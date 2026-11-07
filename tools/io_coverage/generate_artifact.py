#!/usr/bin/env python
"""
Generate IO coverage artifact from pytest results.

This script reads pytest JSON results, maps tests to IO variations
from the catalog, and produces a machine-readable coverage artifact.

Usage:
    python tools/io_coverage/generate_artifact.py --pytest-results results.json --output io-coverage.json

Output Format:
    The artifact is a JSON file following contracts/io-coverage-schema.json
    with the following structure:
    {
        "version": "1.0.0",
        "generated_at": "2024-01-01T00:00:00Z",
        "parser_version": "1.0.0",
        "total_variations": 64,
        "covered_variations": 40,
        "partial_variations": 5,
        "gap_variations": 19,
        "coverage_percent": 62.5,
        "variations": [
            {
                "id": "OPEN-INPUT-SEQUENTIAL",
                "verb": "OPEN",
                "organization": "SEQUENTIAL",
                "access_mode": "INPUT",
                "qualifiers": "",
                "status": "covered",
                "requires_fd": false,
                "ibm_reference": "SC27-8949-30",
                "tests": [
                    {
                        "test_id": "tests/unit/io_statements/test_io_clause_variations.py::...",
                        "test_type": "unit",
                        "status": "passed",
                        "duration": 0.01
                    }
                ],
                "last_tested": "2024-01-01T00:00:00Z",
                "notes": "Basic sequential file open"
            }
        ],
        "summary": {
            "OPEN": 7,
            "CLOSE": 5,
            "READ": 8,
            ...
        }
    }
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def find_catalog() -> Path | None:
    """Find the IO variation catalog CSV file."""
    search_paths = [
        Path(__file__).parent.parent
        / "specs"
        / "001-io-variation-coverage"
        / "io-variation-catalog.csv",
        Path(__file__).parent.parent / "specs" / "io-variation-catalog.csv",
        Path("specs/001-io-variation-coverage/io-variation-catalog.csv"),
        Path("io-variation-catalog.csv"),
    ]

    for path in search_paths:
        if path.exists():
            return path

    return None


def parse_catalog(catalog_path: Path) -> dict[str, dict[str, str]]:
    """Parse the IO variation catalog CSV.

    Returns a dictionary mapping variation_id -> variation_data
    """
    variations = {}

    if not catalog_path.exists():
        print(f"Warning: Catalog not found at {catalog_path}")
        return variations

    import csv

    with open(catalog_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            var_id = row.get("id", "")
            variations[var_id] = {
                "verb": row.get("verb", ""),
                "organization": row.get("file_organization", ""),
                "access_mode": row.get("access_mode", ""),
                "qualifiers": row.get("qualifiers", ""),
                "ibm_reference": row.get("ibm_reference", ""),
                "notes": row.get("notes", ""),
                "requires_fd": row.get("requires_fd_clauses", "").lower() == "true",
            }

    return variations


def extract_variation_id(
    test_id: str, catalog_variations: dict[str, dict]
) -> str | None:
    """Extract IO variation ID from a test ID or name."""
    import re

    # Pattern to match IO variation IDs like OPEN-INPUT-SEQUENTIAL
    pattern = r"^(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|ACCEPT|DISPLAY|UNLOCK)-[A-Z]+(?:-[A-Z]+)*"
    match = re.search(pattern, test_id, re.IGNORECASE)

    if match:
        return match.group(0).upper()

    # Also check catalog keys against test name
    for var_id in catalog_variations:
        if var_id in test_id.upper():
            return var_id

    return None


def determine_test_type(test_id: str) -> str:
    """Determine the type of test from its ID."""
    test_id_lower = test_id.lower()
    if "/unit/" in test_id_lower or "\\unit\\" in test_id_lower:
        return "unit"
    elif "/contract/" in test_id_lower or "\\contract\\" in test_id_lower:
        return "contract"
    elif "/integration/" in test_id_lower or "\\integration\\" in test_id_lower:
        return "integration"
    return "unit"


def load_pytest_results(results_path: str) -> dict[str, Any]:
    """Load pytest results from JSON file."""
    if not os.path.exists(results_path):
        print(f"Error: Pytest results not found: {results_path}")
        sys.exit(1)

    with open(results_path, encoding="utf-8") as f:
        return json.load(f)


def generate_coverage_artifact(
    pytest_results: dict[str, Any],
    catalog_variations: dict[str, dict[str, str]],
    parser_version: str = "unknown",
) -> dict[str, Any]:
    """Generate the IO coverage artifact from pytest results."""

    # Track which variations have tests
    variation_tests: dict[str, list[dict[str, Any]]] = {}

    for test in pytest_results.get("tests", []):
        test_id = test.get("id", test.get("nodeid", ""))
        var_id = extract_variation_id(test_id, catalog_variations)

        if var_id:
            if var_id not in variation_tests:
                variation_tests[var_id] = []

            variation_tests[var_id].append(
                {
                    "test_id": test_id,
                    "test_type": determine_test_type(test_id),
                    "status": test.get("status", "unknown"),
                    "duration": test.get("duration", 0),
                    "file_path": test.get("file", ""),
                    "line_number": test.get("line_number"),
                }
            )

    # Build the artifact
    artifact = {
        "version": "1.0.0",
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        "parser_version": parser_version,
        "total_variations": len(catalog_variations),
        "covered_variations": 0,
        "partial_variations": 0,
        "gap_variations": 0,
        "coverage_percent": 0.0,
        "variations": [],
        "summary": {},
        "metadata": {
            "source": "pytest-results.json",
            "generator": "io_coverage_reporter",
        },
    }

    # Build variation entries
    covered_count = 0
    partial_count = 0
    gap_count = 0

    for var_id, var_data in catalog_variations.items():
        tests = variation_tests.get(var_id, [])

        if tests:
            all_passed = all(t["status"] == "passed" for t in tests)
            status = "covered" if all_passed else "partial"

            if status == "covered":
                covered_count += 1
            else:
                partial_count += 1
        else:
            status = "gap"
            gap_count += 1

        variation_entry = {
            "id": var_id,
            "verb": var_data["verb"],
            "organization": var_data["organization"],
            "access_mode": var_data["access_mode"],
            "qualifiers": var_data["qualifiers"],
            "status": status,
            "requires_fd": var_data["requires_fd"],
            "ibm_reference": var_data["ibm_reference"],
            "tests": tests,
            "notes": var_data["notes"],
        }

        artifact["variations"].append(variation_entry)

        # Update summary
        verb = var_data["verb"]
        artifact["summary"][verb] = artifact["summary"].get(verb, 0) + 1

    artifact["covered_variations"] = covered_count
    artifact["partial_variations"] = partial_count
    artifact["gap_variations"] = gap_count

    # Calculate coverage percentage
    total = artifact["total_variations"]
    if total > 0:
        artifact["coverage_percent"] = round((covered_count / total) * 100, 2)

    return artifact


def validate_artifact(artifact: dict[str, Any]) -> list[str]:
    """Validate the artifact against the coverage schema."""
    errors = []

    # Required fields
    if "version" not in artifact:
        errors.append("Missing required field: version")
    if "generated_at" not in artifact:
        errors.append("Missing required field: generated_at")
    if "variations" not in artifact:
        errors.append("Missing required field: variations")

    # Type validation
    if not isinstance(artifact.get("variations", []), list):
        errors.append("variations must be an array")
        return errors

    # Validate each variation
    valid_statuses = {"covered", "partial", "gap", "unsupported"}
    for variation in artifact["variations"]:
        if "id" not in variation:
            errors.append("Variation missing required field: id")
        if "status" not in variation:
            errors.append(f"Variation {variation.get('id', 'unknown')} missing status")
        elif variation["status"] not in valid_statuses:
            errors.append(
                f"Variation {variation['id']} has invalid status: {variation['status']}"
            )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Generate IO coverage artifact from pytest results"
    )
    parser.add_argument(
        "--pytest-results", "-r", required=True, help="Path to pytest results JSON file"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="io-coverage.json",
        help="Output path for coverage artifact (default: io-coverage.json)",
    )
    parser.add_argument("--catalog", "-c", help="Path to IO variation catalog CSV")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing artifact instead of generating",
    )
    parser.add_argument(
        "--parser-version",
        default="1.0.0",
        help="Parser version string for the artifact",
    )

    args = parser.parse_args()

    if args.validate:
        if not os.path.exists(args.output):
            print(f"Error: Artifact not found: {args.output}")
            return 1

        with open(args.output) as f:
            artifact = json.load(f)

        errors = validate_artifact(artifact)
        if errors:
            print(f"Validation errors ({len(errors)}):")
            for error in errors:
                print(f"  - {error}")
            return 1
        else:
            print("Artifact is valid!")
            print(f"  Coverage: {artifact.get('coverage_percent', 0)}%")
            print(
                f"  Variations: {artifact.get('covered_variations', 0)}/{artifact.get('total_variations', 0)}"
            )
        return 0

    # Find catalog
    catalog_path = args.catalog
    if not catalog_path:
        catalog_path = find_catalog()
        if catalog_path:
            catalog_path = str(catalog_path)

    if not catalog_path or not os.path.exists(catalog_path):
        print("Error: Catalog not found. Please specify with --catalog")
        return 1

    print(f"Using catalog: {catalog_path}")

    # Load catalog
    catalog = parse_catalog(Path(catalog_path))
    print(f"Loaded {len(catalog)} variations from catalog")

    # Load pytest results
    results = load_pytest_results(args.pytest_results)
    print(f"Loaded {len(results.get('tests', []))} tests from pytest results")

    # Generate artifact
    artifact = generate_coverage_artifact(
        results, catalog, parser_version=args.parser_version
    )

    # Validate before saving
    errors = validate_artifact(artifact)
    if errors:
        print(f"\nValidation errors ({len(errors)}):")
        for error in errors:
            print(f"  - {error}")
        print("\nArtifact not saved due to validation errors.")
        return 1

    # Save artifact
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    print(f"\nCoverage artifact saved to: {args.output}")
    print(f"Coverage: {artifact['coverage_percent']}%")
    print(f"  Covered: {artifact['covered_variations']}")
    print(f"  Partial: {artifact['partial_variations']}")
    print(f"  Gaps: {artifact['gap_variations']}")
    print(f"  Total: {artifact['total_variations']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
