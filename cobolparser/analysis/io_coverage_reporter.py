"""IO Coverage Reporter for COBOL parser.

This module provides functionality to generate machine-readable IO coverage
artifacts that track which IBM Enterprise COBOL IO variations have been
tested and which are missing coverage.

Contract: contracts/io-coverage-schema.json
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum


class CoverageStatus(str, Enum):
    """IO variation coverage status."""

    COVERED = "covered"
    PARTIAL = "partial"
    GAP = "gap"
    UNSUPPORTED = "unsupported"


class TestType(str, Enum):
    """Type of test coverage."""

    UNIT = "unit"
    CONTRACT = "contract"
    INTEGRATION = "integration"


@dataclass
class TestReference:
    """Reference to a test file that covers a variation."""

    file_path: str
    test_name: str
    test_type: str
    line_number: Optional[int] = None


@dataclass
class IoVariationCoverage:
    """Coverage data for a single IO variation."""

    variation_id: str
    verb: str
    organization: str
    access_mode: str
    qualifiers: str
    status: str
    requires_fd: bool
    ibm_reference: str
    tests: List[Dict[str, Any]] = field(default_factory=list)
    last_tested: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class IoCoverageArtifact:
    """Complete IO coverage artifact."""

    version: str = "1.0.0"
    generated_at: str = ""
    parser_version: str = ""
    total_variations: int = 0
    covered_variations: int = 0
    partial_variations: int = 0
    gap_variations: int = 0
    unsupported_variations: int = 0
    coverage_percent: float = 0.0
    variations: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class IOCoverageReporter:
    """Generates IO coverage reports from pytest results.

    This reporter:
    1. Ingests pytest outputs (JSON or JUnit XML)
    2. Maps test results to IO variations from the catalog
    3. Produces machine-readable coverage artifacts
    4. Validates artifacts against the coverage schema
    """

    def __init__(
        self, catalog_path: Optional[str] = None, schema_path: Optional[str] = None
    ):
        """Initialize the IO coverage reporter.

        Args:
            catalog_path: Path to io-variation-catalog.csv
            schema_path: Path to io-coverage-schema.json
        """
        self.catalog_path = catalog_path or self._find_catalog_path()
        self.schema_path = schema_path or self._find_schema_path()
        self.variations: List[IoVariationCoverage] = []
        self.test_results: Dict[str, List[Dict[str, Any]]] = {}

    def _find_catalog_path(self) -> str:
        """Find the IO variation catalog path."""
        possible_paths = [
            "specs/001-io-variation-coverage/io-variation-catalog.csv",
            "specs/io-variation-coverage/io-variation-catalog.csv",
            "io-variation-catalog.csv",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError(
            f"Could not find IO variation catalog. Searched: {possible_paths}"
        )

    def _find_schema_path(self) -> str:
        """Find the coverage schema path."""
        possible_paths = [
            "contracts/io-coverage-schema.json",
            "specs/001-io-variation-coverage/contracts/io-coverage-schema.json",
            "io-coverage-schema.json",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError(
            f"Could not find coverage schema. Searched: {possible_paths}"
        )

    def load_catalog(self) -> None:
        """Load the IO variation catalog from CSV."""
        import csv

        if not os.path.exists(self.catalog_path):
            raise FileNotFoundError(f"Catalog not found: {self.catalog_path}")

        self.variations = []
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                variation = IoVariationCoverage(
                    variation_id=row.get("id", ""),
                    verb=row.get("verb", ""),
                    organization=row.get("file_organization", ""),
                    access_mode=row.get("access_mode", ""),
                    qualifiers=row.get("qualifiers", ""),
                    status=row.get("status", "PENDING"),
                    requires_fd=row.get("requires_fd_clauses", "").lower() == "true",
                    ibm_reference=row.get("ibm_reference", ""),
                    notes=row.get("notes", ""),
                )
                self.variations.append(variation)

    def load_pytest_results(self, results_path: str) -> None:
        """Load pytest results from JSON file.

        Args:
            results_path: Path to pytest results JSON file
        """
        if not os.path.exists(results_path):
            raise FileNotFoundError(f"Pytest results not found: {results_path}")

        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.test_results = {}
        for test in data.get("tests", []):
            test_id = test.get("id", test.get("nodeid", ""))
            test_type = self._determine_test_type(test_id)
            io_variation = self._extract_io_variation(test_id)

            if io_variation:
                if io_variation not in self.test_results:
                    self.test_results[io_variation] = []

                self.test_results[io_variation].append(
                    {
                        "test_id": test_id,
                        "test_type": test_type,
                        "status": test.get("status", "unknown"),
                        "duration": test.get("duration", 0),
                        "file_path": test.get("file", ""),
                        "line_number": test.get("line_number"),
                        "description": test.get("description", ""),
                    }
                )

    def _determine_test_type(self, test_id: str) -> str:
        """Determine the type of test from its ID."""
        test_id_lower = test_id.lower()
        # Check more specific paths first (longer prefixes)
        if "/contracts/" in test_id_lower or "/contracts\\" in test_id_lower:
            return TestType.CONTRACT.value
        elif "/integration/" in test_id_lower or "/integration\\" in test_id_lower:
            return TestType.INTEGRATION.value
        elif "/unit/" in test_id_lower or "/unit\\" in test_id_lower:
            return TestType.UNIT.value
        return TestType.UNIT.value

    def _extract_io_variation(self, test_id: str) -> Optional[str]:
        """Extract IO variation ID from test ID."""
        import re

        # Pattern to match IO variation IDs like OPEN-INPUT-SEQUENTIAL
        pattern = r"(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|ACCEPT|DISPLAY|UNLOCK)-[A-Z]+(?:-[A-Z]+)*"
        match = re.search(pattern, test_id, re.IGNORECASE)

        if match:
            return match.group(0).upper()

        # Try to extract from test name
        for variation in self.variations:
            if variation.variation_id in test_id.upper():
                return variation.variation_id

        return None

    def generate_artifact(self) -> IoCoverageArtifact:
        """Generate the complete IO coverage artifact.

        Returns:
            IoCoverageArtifact with coverage data
        """
        artifact = IoCoverageArtifact(
            generated_at=datetime.utcnow().isoformat() + "Z",
            parser_version=self._get_parser_version(),
            total_variations=len(self.variations),
        )

        # Build variation coverage data
        variation_data = []
        for variation in self.variations:
            tests = self.test_results.get(variation.variation_id, [])

            if tests:
                status = (
                    CoverageStatus.COVERED.value
                    if all(t.get("status") == "passed" for t in tests)
                    else CoverageStatus.PARTIAL.value
                )
                last_tested = datetime.utcnow().isoformat() + "Z"
            else:
                status = CoverageStatus.GAP.value
                last_tested = None

            coverage = IoVariationCoverage(
                variation_id=variation.variation_id,
                verb=variation.verb,
                organization=variation.organization,
                access_mode=variation.access_mode,
                qualifiers=variation.qualifiers,
                status=status,
                requires_fd=variation.requires_fd,
                ibm_reference=variation.ibm_reference,
                tests=tests,
                last_tested=last_tested,
                notes=variation.notes,
            )

            variation_dict = {
                "id": coverage.variation_id,
                "verb": coverage.verb,
                "organization": coverage.organization,
                "access_mode": coverage.access_mode,
                "qualifiers": coverage.qualifiers,
                "status": coverage.status,
                "requires_fd": coverage.requires_fd,
                "ibm_reference": coverage.ibm_reference,
                "tests": coverage.tests,
                "last_tested": coverage.last_tested,
                "notes": coverage.notes,
            }
            variation_data.append(variation_dict)

            # Update counts
            if status == CoverageStatus.COVERED.value:
                artifact.covered_variations += 1
            elif status == CoverageStatus.PARTIAL.value:
                artifact.partial_variations += 1
            elif status == CoverageStatus.GAP.value:
                artifact.gap_variations += 1
            else:
                artifact.unsupported_variations += 1

        artifact.variations = variation_data

        # Calculate coverage percent
        if artifact.total_variations > 0:
            artifact.coverage_percent = round(
                (artifact.covered_variations / artifact.total_variations) * 100, 2
            )

        # Build summary by verb
        for variation in self.variations:
            if variation.verb not in artifact.summary:
                artifact.summary[variation.verb] = 0
            artifact.summary[variation.verb] += 1

        # Add metadata
        artifact.metadata = {
            "catalog_path": self.catalog_path,
            "schema_path": self.schema_path,
            "generator": "IOCoverageReporter",
        }

        return artifact

    def _get_parser_version(self) -> str:
        """Get the parser version."""
        try:
            from cobolparser import __version__

            return __version__
        except ImportError:
            return "unknown"

    def save_artifact(self, artifact: IoCoverageArtifact, output_path: str) -> None:
        """Save the coverage artifact to a JSON file.

        Args:
            artifact: IoCoverageArtifact to save
            output_path: Path to output JSON file
        """
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        artifact_dict = asdict(artifact)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact_dict, f, indent=2)

    def validate_artifact(self, artifact: IoCoverageArtifact) -> List[str]:
        """Validate artifact against the coverage schema.

        Args:
            artifact: IoCoverageArtifact to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Basic structure validation
        if artifact.generated_at and not artifact.generated_at.endswith("Z"):
            errors.append("generated_at should end with 'Z' (ISO 8601 UTC)")

        if artifact.total_variations < 0:
            errors.append("total_variations cannot be negative")

        if artifact.coverage_percent < 0 or artifact.coverage_percent > 100:
            errors.append("coverage_percent must be between 0 and 100")

        # Variation validation
        for variation in artifact.variations:
            if not variation.get("id"):
                errors.append("Variation missing required 'id' field")

            if not variation.get("verb"):
                errors.append(
                    f"Variation {variation.get('id', 'unknown')} missing 'verb'"
                )

            valid_statuses = [s.value for s in CoverageStatus]
            if variation.get("status") not in valid_statuses:
                errors.append(
                    f"Variation {variation.get('id', 'unknown')} has invalid status: "
                    f"{variation.get('status')}. Must be one of: {valid_statuses}"
                )

        # Summary validation
        total_in_summary = sum(artifact.summary.values())
        if total_in_summary != artifact.total_variations:
            errors.append(
                f"Summary count ({total_in_summary}) does not match "
                f"total_variations ({artifact.total_variations})"
            )

        return errors

    def generate_report(
        self, pytest_results_path: str, output_path: str
    ) -> Dict[str, Any]:
        """Generate a complete IO coverage report.

        This is the main entry point for generating coverage reports.

        Args:
            pytest_results_path: Path to pytest results JSON
            output_path: Path for output artifact JSON

        Returns:
            Dictionary with report results and validation status
        """
        # Load catalog
        self.load_catalog()

        # Load pytest results
        self.load_pytest_results(pytest_results_path)

        # Generate artifact
        artifact = self.generate_artifact()

        # Validate
        validation_errors = self.validate_artifact(artifact)
        is_valid = len(validation_errors) == 0

        # Save artifact
        self.save_artifact(artifact, output_path)

        return {
            "success": is_valid,
            "output_path": output_path,
            "coverage_percent": artifact.coverage_percent,
            "covered_variations": artifact.covered_variations,
            "total_variations": artifact.total_variations,
            "gap_variations": artifact.gap_variations,
            "validation_errors": validation_errors,
        }


def main():
    """CLI entry point for IO coverage reporting."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate IO coverage reports for COBOL parser"
    )
    parser.add_argument(
        "--pytest-results", required=True, help="Path to pytest results JSON file"
    )
    parser.add_argument(
        "--output",
        default="io-coverage.json",
        help="Output path for coverage artifact (default: io-coverage.json)",
    )
    parser.add_argument("--catalog", help="Path to IO variation catalog CSV")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing artifact, do not generate",
    )

    args = parser.parse_args()

    reporter = IOCoverageReporter(catalog_path=args.catalog)

    if args.validate_only:
        if not os.path.exists(args.output):
            print(f"Error: Artifact not found: {args.output}")
            return 1

        with open(args.output, "r") as f:
            artifact_dict = json.load(f)
            artifact = IoCoverageArtifact(**artifact_dict)

        errors = reporter.validate_artifact(artifact)
        if errors:
            print(f"Validation errors ({len(errors)}):")
            for error in errors:
                print(f"  - {error}")
            return 1
        else:
            print("Artifact is valid!")
            return 0

    result = reporter.generate_report(args.pytest_results, args.output)

    if result["success"]:
        print(f"Coverage report generated: {result['output_path']}")
        print(f"Coverage: {result['coverage_percent']}%")
        print(f"  Covered: {result['covered_variations']}/{result['total_variations']}")
        print(f"  Gaps: {result['gap_variations']}")
    else:
        print(f"Report generation failed:")
        for error in result["validation_errors"]:
            print(f"  - {error}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
