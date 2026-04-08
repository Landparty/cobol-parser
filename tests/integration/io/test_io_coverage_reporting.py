"""Integration tests for IO coverage reporting.

These tests verify that the IO coverage reporting pipeline works end-to-end.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


class TestIOCoverageReportingIntegration:
    """Integration tests for IO coverage reporting pipeline."""

    @pytest.fixture
    def sample_artifact(self, tmp_path):
        """Create sample IO coverage artifact."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "parser_version": "1.0.0",
            "total_variations": 3,
            "covered_variations": 2,
            "partial_variations": 1,
            "gap_variations": 0,
            "coverage_percent": 66.67,
            "variations": [
                {
                    "id": "OPEN-INPUT-SEQUENTIAL",
                    "verb": "OPEN",
                    "organization": "SEQUENTIAL",
                    "access_mode": "INPUT",
                    "qualifiers": "",
                    "status": "covered",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/contracts/io/test_open.py::test_open_input_sequential",
                            "test_type": "contract",
                            "status": "passed",
                            "duration": 0.015,
                        }
                    ],
                    "notes": "Basic sequential file open",
                },
                {
                    "id": "CLOSE-NO-REWIND",
                    "verb": "CLOSE",
                    "organization": "SEQUENTIAL",
                    "access_mode": "N/A",
                    "qualifiers": "NO REWIND",
                    "status": "partial",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_close.py::test_close_no_rewind",
                            "test_type": "unit",
                            "status": "failed",
                            "duration": 0.005,
                        }
                    ],
                    "notes": "Close without tape rewind",
                },
                {
                    "id": "WRITE-ADVANCING",
                    "verb": "WRITE",
                    "organization": "SEQUENTIAL",
                    "access_mode": "OUTPUT",
                    "qualifiers": "ADVANCING",
                    "status": "covered",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_write.py::test_write_advancing",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.008,
                        }
                    ],
                    "notes": "Write with page/line advancing",
                },
            ],
            "summary": {"OPEN": 1, "CLOSE": 1, "WRITE": 1},
            "metadata": {
                "source": "pytest-results.json",
                "generator": "io_coverage_reporter",
            },
        }

        file_path = tmp_path / "io-coverage.json"
        with open(file_path, "w") as f:
            json.dump(artifact, f)
        return str(file_path)

    def test_cli_validate_artifact(self, sample_artifact):
        """Test the CLI validation tool."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        script_path = repo_root / "scripts" / "validate_io_coverage.py"

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--artifact",
                sample_artifact,
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

    def test_cli_render_markdown(self, sample_artifact, tmp_path):
        """Test the markdown rendering CLI tool."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        tool_path = repo_root / "tools" / "io_coverage" / "render_markdown.py"
        output_file = tmp_path / "io-coverage.md"

        result = subprocess.run(
            [
                sys.executable,
                str(tool_path),
                "--input",
                sample_artifact,
                "--output",
                str(output_file),
                "--format",
                "markdown",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.exists(), "CLI did not create output file"

        content = output_file.read_text(encoding="utf-8")
        assert "# IO Coverage Report" in content
        assert "OPEN-INPUT-SEQUENTIAL" in content

    def test_cli_render_csv(self, sample_artifact, tmp_path):
        """Test the CSV rendering CLI tool."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        tool_path = repo_root / "tools" / "io_coverage" / "render_markdown.py"
        output_file = tmp_path / "io-coverage.csv"

        result = subprocess.run(
            [
                sys.executable,
                str(tool_path),
                "--input",
                sample_artifact,
                "--output",
                str(output_file),
                "--format",
                "csv",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.exists(), "CLI did not create output file"

        content = output_file.read_text()
        assert "id,verb,organization" in content
        assert "OPEN-INPUT-SEQUENTIAL" in content

    def test_cli_render_summary(self, sample_artifact, tmp_path):
        """Test the summary rendering CLI tool."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        tool_path = repo_root / "tools" / "io_coverage" / "render_markdown.py"
        output_file = tmp_path / "summary.txt"

        result = subprocess.run(
            [
                sys.executable,
                str(tool_path),
                "--input",
                sample_artifact,
                "--output",
                str(output_file),
                "--format",
                "summary",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.exists(), "CLI did not create output file"

        content = output_file.read_text()
        assert "IO Coverage Summary" in content
        assert "OPEN: 1/1 covered" in content


class TestIOCoverageSchemaCompliance:
    """Tests for schema compliance."""

    def test_variation_status_values(self):
        """Test that all variation status values are valid."""
        from cobolparser.analysis.io_coverage_reporter import CoverageStatus

        valid_statuses = {"covered", "partial", "gap", "unsupported"}

        for status in CoverageStatus:
            assert status.value in valid_statuses

    def test_variation_id_format(self):
        """Test that variation IDs follow expected format."""
        import re

        pattern = re.compile(
            r"^(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|ACCEPT|DISPLAY|UNLOCK)-[A-Z]+(?:-[A-Z]+)*$"
        )

        valid_ids = [
            "OPEN-INPUT-SEQUENTIAL",
            "CLOSE-NO-REWIND",
            "READ-NEXT-AT-END",
            "WRITE-ADVANCING",
        ]

        for var_id in valid_ids:
            assert pattern.match(var_id), f"Invalid variation ID format: {var_id}"

    def test_artifact_required_fields(self, tmp_path):
        """Test that artifact has all required fields."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "variations": [],
        }

        file_path = tmp_path / "minimal.json"
        with open(file_path, "w") as f:
            json.dump(artifact, f)

        repo_root = Path(__file__).parent.parent.parent
        script_path = repo_root / "scripts" / "validate_io_coverage.py"

        result = subprocess.run(
            [sys.executable, str(script_path), "--artifact", str(file_path)],
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode != 0
        ), "Should fail validation - missing required fields"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
