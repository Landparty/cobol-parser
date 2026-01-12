#!/usr/bin/env python
"""
Validate IO coverage artifact against the schema.

This script validates that an io-coverage.json artifact follows
the contracts/io-coverage-schema.json specification.

Usage:
    python scripts/validate_io_coverage.py [--artifact io-coverage.json]

Exit codes:
    0 - Artifact is valid
    1 - Artifact is invalid
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class CoverageSchemaValidator:
    """Validates IO coverage artifacts against the schema."""

    # Schema definition (simplified version of contracts/io-coverage-schema.json)
    SCHEMA = {
        "type": "object",
        "required": ["version", "generated_at", "variations"],
        "properties": {
            "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
            "generated_at": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            },
            "parser_version": {"type": "string"},
            "total_variations": {"type": "integer", "minimum": 0},
            "covered_variations": {"type": "integer", "minimum": 0},
            "partial_variations": {"type": "integer", "minimum": 0},
            "gap_variations": {"type": "integer", "minimum": 0},
            "unsupported_variations": {"type": "integer", "minimum": 0},
            "coverage_percent": {"type": "number", "minimum": 0, "maximum": 100},
            "variations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "verb", "status"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": r"^(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|ACCEPT|DISPLAY|UNLOCK)-[A-Z]+(?:-[A-Z]+)*$",
                        },
                        "verb": {
                            "type": "string",
                            "enum": [
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
                            ],
                        },
                        "organization": {"type": "string"},
                        "access_mode": {"type": "string"},
                        "qualifiers": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["covered", "partial", "gap", "unsupported"],
                        },
                        "requires_fd": {"type": "boolean"},
                        "ibm_reference": {"type": "string"},
                        "tests": {"type": "array"},
                        "last_tested": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "object"},
            "metadata": {"type": "object"},
        },
    }

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
    VALID_STATUSES = {"covered", "partial", "gap", "unsupported"}

    def __init__(self, artifact_path: str):
        """Initialize validator with artifact path."""
        self.artifact_path = Path(artifact_path)
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(self) -> bool:
        """Run full validation and return success status."""
        # Load artifact
        if not self.artifact_path.exists():
            self.errors.append(f"Artifact not found: {self.artifact_path}")
            return False

        try:
            with open(self.artifact_path, "r", encoding="utf-8") as f:
                self.artifact = json.load(f)
        except json.JSONDecodeError as e:
            self.errors.append(f"Invalid JSON: {e}")
            return False

        # Run validations
        self._validate_root_structure()
        self._validate_variations()
        self._validate_counts()
        self._validate_summary()

        return len(self.errors) == 0

    def _validate_root_structure(self) -> None:
        """Validate root-level structure."""
        required_fields = ["version", "generated_at", "variations"]
        for field in required_fields:
            if field not in self.artifact:
                self.errors.append(f"Missing required field: {field}")

        # Version format
        version = self.artifact.get("version", "")
        if version and not self._matches_pattern(version, r"^\d+\.\d+\.\d+$"):
            self.errors.append(f"Invalid version format: {version}")

        # Generated at format
        generated_at = self.artifact.get("generated_at", "")
        if generated_at and not self._matches_pattern(
            generated_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        ):
            self.errors.append(f"Invalid generated_at format: {generated_at}")

    def _validate_variations(self) -> None:
        """Validate each variation entry."""
        variations = self.artifact.get("variations", [])

        if not isinstance(variations, list):
            self.errors.append("variations must be an array")
            return

        seen_ids = set()
        for i, variation in enumerate(variations):
            var_id = f"[{i}]"

            # Required fields
            if "id" not in variation:
                self.errors.append(f"{var_id}: Missing required field: id")
                continue

            variation_id = variation["id"]
            var_id = f"[{variation_id}]"

            # Check for duplicate IDs
            if variation_id in seen_ids:
                self.warnings.append(f"{var_id}: Duplicate variation ID")
            seen_ids.add(variation_id)

            # Verb validation
            verb = variation.get("verb", "")
            if verb and verb not in self.VALID_VERBS:
                self.errors.append(f"{var_id}: Invalid verb: {verb}")
            elif not verb:
                self.errors.append(f"{var_id}: Missing verb")

            # Status validation
            status = variation.get("status", "")
            if status and status not in self.VALID_STATUSES:
                self.errors.append(f"{var_id}: Invalid status: {status}")
            elif not status:
                self.errors.append(f"{var_id}: Missing status")

            # ID format validation
            if variation_id and not self._matches_pattern(
                variation_id,
                r"^(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|ACCEPT|DISPLAY|UNLOCK)-[A-Z]+(?:-[A-Z]+)*$",
            ):
                self.warnings.append(f"{var_id}: Non-standard variation ID format")

    def _validate_counts(self) -> None:
        """Validate count fields are consistent."""
        total = self.artifact.get("total_variations", 0)
        covered = self.artifact.get("covered_variations", 0)
        partial = self.artifact.get("partial_variations", 0)
        gap = self.artifact.get("gap_variations", 0)
        unsupported = self.artifact.get("unsupported_variations", 0)

        calculated_total = covered + partial + gap + unsupported
        if total != calculated_total:
            self.errors.append(
                f"Inconsistent counts: total_variations={total} but "
                f"covered+partial+gap+unsupported={calculated_total}"
            )

        # Coverage percent
        coverage = self.artifact.get("coverage_percent", 0)
        if coverage < 0 or coverage > 100:
            self.errors.append(f"coverage_percent must be 0-100, got: {coverage}")

    def _validate_summary(self) -> None:
        """Validate summary counts match variations."""
        summary = self.artifact.get("summary", {})
        variations = self.artifact.get("variations", [])

        # Count by verb
        verb_counts = {}
        for variation in variations:
            verb = variation.get("verb", "")
            verb_counts[verb] = verb_counts.get(verb, 0) + 1

        # Compare with summary
        for verb, count in verb_counts.items():
            summary_count = summary.get(verb, 0)
            if summary_count != count:
                self.errors.append(
                    f"Summary mismatch for {verb}: summary={summary_count}, variations={count}"
                )

    def _matches_pattern(self, value: str, pattern: str) -> bool:
        """Check if value matches regex pattern."""
        import re

        return bool(re.match(pattern, value))

    def print_report(self) -> None:
        """Print validation report."""
        print("=" * 60)
        print("IO Coverage Artifact Validation Report")
        print("=" * 60)
        print(f"Artifact: {self.artifact_path}")
        print()

        if self.errors:
            print(f"ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  - {error}")
            print()
        else:
            print("No errors found.")

        if self.warnings:
            print(f"WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  - {warning}")
            print()

        # Summary
        if self.artifact:
            print("Artifact Summary:")
            print(f"  Version: {self.artifact.get('version', 'N/A')}")
            print(f"  Generated: {self.artifact.get('generated_at', 'N/A')}")
            print(f"  Coverage: {self.artifact.get('coverage_percent', 0)}%")
            print(
                f"  Variations: {self.artifact.get('covered_variations', 0)}/{self.artifact.get('total_variations', 0)} covered"
            )
            print(f"  Gaps: {self.artifact.get('gap_variations', 0)}")

        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Validate IO coverage artifact against schema"
    )
    parser.add_argument(
        "--artifact",
        "-a",
        default="io-coverage.json",
        help="Path to IO coverage artifact JSON (default: io-coverage.json)",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Only output pass/fail status"
    )

    args = parser.parse_args()

    # Check if artifact exists
    if not os.path.exists(args.artifact):
        if not args.quiet:
            print(f"ERROR: Artifact not found: {args.artifact}")
        return 1

    # Run validation
    validator = CoverageSchemaValidator(args.artifact)
    is_valid = validator.validate()

    if not args.quiet:
        validator.print_report()

    if is_valid:
        if not args.quiet:
            print("VALIDATION PASSED")
        return 0
    else:
        if not args.quiet:
            print("VALIDATION FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
