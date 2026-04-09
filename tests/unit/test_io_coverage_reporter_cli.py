"""Tests for io_coverage_reporter.py CLI and artifact validation.

Targets uncovered lines in analysis/io_coverage_reporter.py (73.16%):
  - _extract_io_variation from test IDs (lines 253-257)
  - validate_artifact structure checks (lines 355-356, 386-409)
  - main() CLI entry point (lines 464-520)
"""

import json
import os
import tempfile
from unittest.mock import patch

from cobolparser.analysis.io_coverage_reporter import (
    CoverageStatus,
    IOCoverageReporter,
    IoCoverageArtifact,
    IoVariationCoverage,
    main,
)


class TestExtractIoVariation:
    """Cover _extract_io_variation from test IDs (lines 252-257)."""

    def test_extract_from_pattern(self):
        reporter = IOCoverageReporter()
        result = reporter._extract_io_variation(
            "tests/io/test_READ-SEQUENTIAL-NEXT::test_basic"
        )
        assert result == "READ-SEQUENTIAL-NEXT"

    def test_extract_from_variation_list(self):
        reporter = IOCoverageReporter()
        reporter.variations = [
            IoVariationCoverage(
                variation_id="OPEN-INPUT-SEQ",
                verb="OPEN",
                organization="SEQUENTIAL",
                access_mode="INPUT",
                qualifiers="",
                status="covered",
                requires_fd=True,
                ibm_reference="",
            )
        ]
        result = reporter._extract_io_variation(
            "tests/unit/test_something::TestOpenInputSeq::test_OPEN-INPUT-SEQ_basic"
        )
        assert result == "OPEN-INPUT-SEQ"

    def test_no_match(self):
        reporter = IOCoverageReporter()
        result = reporter._extract_io_variation("tests/unit/test_lexer::test_basic")
        assert result is None


class TestValidateArtifact:
    """Cover validate_artifact structure checks (lines 373-418)."""

    def test_valid_artifact(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=2,
            covered_variations=1,
            coverage_percent=50.0,
            variations=[
                {"id": "READ-SEQ", "verb": "READ", "status": "covered"},
                {"id": "WRITE-SEQ", "verb": "WRITE", "status": "gap"},
            ],
            summary={"READ": 1, "WRITE": 1},
        )
        errors = reporter.validate_artifact(artifact)
        assert len(errors) == 0

    def test_generated_at_not_utc(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00+05:00",
            total_variations=0,
            coverage_percent=0.0,
            summary={},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("generated_at" in e for e in errors)

    def test_negative_total_variations(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=-1,
            coverage_percent=0.0,
            summary={},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("negative" in e for e in errors)

    def test_coverage_percent_out_of_range(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=0,
            coverage_percent=150.0,
            summary={},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("coverage_percent" in e for e in errors)

    def test_variation_missing_id(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=1,
            coverage_percent=0.0,
            variations=[{"id": "", "verb": "READ", "status": "gap"}],
            summary={"READ": 1},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("missing required 'id'" in e for e in errors)

    def test_variation_missing_verb(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=1,
            coverage_percent=0.0,
            variations=[{"id": "READ-SEQ", "verb": "", "status": "gap"}],
            summary={"READ": 1},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("missing 'verb'" in e for e in errors)

    def test_variation_invalid_status(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=1,
            coverage_percent=0.0,
            variations=[{"id": "READ-SEQ", "verb": "READ", "status": "INVALID"}],
            summary={"READ": 1},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("invalid status" in e for e in errors)

    def test_summary_count_mismatch(self):
        reporter = IOCoverageReporter()
        artifact = IoCoverageArtifact(
            generated_at="2024-01-01T00:00:00Z",
            total_variations=5,
            coverage_percent=0.0,
            variations=[],
            summary={"READ": 2},
        )
        errors = reporter.validate_artifact(artifact)
        assert any("Summary count" in e for e in errors)


class TestMainCli:
    """Cover main() CLI entry point (lines 462-520)."""

    def test_main_validate_only_file_not_found(self):
        """--validate-only with missing file returns 1."""
        with patch(
            "sys.argv",
            ["prog", "--pytest-results", "x.json", "--output", "/tmp/nonexistent_artifact.json", "--validate-only"],
        ):
            result = main()
        assert result == 1

    def test_main_validate_only_valid_artifact(self):
        """--validate-only with a valid artifact returns 0."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-01T00:00:00Z",
            "parser_version": "1.0.0",
            "total_variations": 0,
            "covered_variations": 0,
            "partial_variations": 0,
            "gap_variations": 0,
            "unsupported_variations": 0,
            "coverage_percent": 0.0,
            "variations": [],
            "summary": {},
            "metadata": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(artifact, f)
            tmppath = f.name
        try:
            with patch(
                "sys.argv",
                ["prog", "--pytest-results", "x.json", "--output", tmppath, "--validate-only"],
            ):
                result = main()
            assert result == 0
        finally:
            os.unlink(tmppath)

    def test_main_validate_only_invalid_artifact(self):
        """--validate-only with invalid artifact returns 1."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-01T00:00:00+05:00",
            "parser_version": "1.0.0",
            "total_variations": -1,
            "covered_variations": 0,
            "partial_variations": 0,
            "gap_variations": 0,
            "unsupported_variations": 0,
            "coverage_percent": 200.0,
            "variations": [],
            "summary": {},
            "metadata": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(artifact, f)
            tmppath = f.name
        try:
            with patch(
                "sys.argv",
                ["prog", "--pytest-results", "x.json", "--output", tmppath, "--validate-only"],
            ):
                result = main()
            assert result == 1
        finally:
            os.unlink(tmppath)

    def test_main_generate_report_success(self):
        """Full report generation succeeds."""
        # Create a minimal catalog CSV
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as cat_f:
            cat_f.write("id,verb,file_organization,access_mode,qualifiers,status,requires_fd_clauses,ibm_reference,notes\n")
            cat_f.write("READ-SEQ,READ,SEQUENTIAL,SEQUENTIAL,,PENDING,true,,test\n")
            catalog_path = cat_f.name

        # Create minimal pytest results JSON
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as res_f:
            json.dump({"tests": []}, res_f)
            results_path = res_f.name

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        ) as out_f:
            output_path = out_f.name

        try:
            with patch(
                "sys.argv",
                [
                    "prog",
                    "--pytest-results", results_path,
                    "--output", output_path,
                    "--catalog", catalog_path,
                ],
            ):
                result = main()
            assert result == 0
            # Verify output file was created
            assert os.path.exists(output_path)
            with open(output_path) as f:
                data = json.load(f)
            assert "variations" in data
        finally:
            os.unlink(catalog_path)
            os.unlink(results_path)
            os.unlink(output_path)
