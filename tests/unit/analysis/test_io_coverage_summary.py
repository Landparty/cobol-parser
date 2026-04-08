"""Unit tests for IO coverage summary renderer.

Tests the render_markdown.py script for correct output
generation from coverage artifacts.
"""

import json

import pytest

from tools.io_coverage.render_markdown import CoverageRenderer


class TestCoverageRenderer:
    """Test cases for CoverageRenderer class."""

    @pytest.fixture
    def sample_artifact(self):
        """Create sample IO coverage artifact."""
        return {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "parser_version": "1.0.0",
            "total_variations": 10,
            "covered_variations": 6,
            "partial_variations": 2,
            "gap_variations": 2,
            "coverage_percent": 60.0,
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
                            "test_id": "tests/contracts/io/test_open_input.py::test_open_input_sequential",
                            "test_type": "contract",
                            "status": "passed",
                            "duration": 0.015,
                        }
                    ],
                    "last_tested": "2024-01-15T10:00:00Z",
                    "notes": "Basic sequential file open",
                },
                {
                    "id": "OPEN-OUTPUT-SEQUENTIAL",
                    "verb": "OPEN",
                    "organization": "SEQUENTIAL",
                    "access_mode": "OUTPUT",
                    "qualifiers": "",
                    "status": "covered",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_open.py::test_open_output",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.010,
                        }
                    ],
                    "last_tested": "2024-01-15T09:30:00Z",
                    "notes": "Create or truncate sequential file",
                },
                {
                    "id": "CLOSE-SIMPLE",
                    "verb": "CLOSE",
                    "organization": "N/A",
                    "access_mode": "N/A",
                    "qualifiers": "",
                    "status": "partial",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_close.py::test_close_simple",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.005,
                        },
                        {
                            "test_id": "tests/integration/io/test_close.py::test_close_integration",
                            "test_type": "integration",
                            "status": "failed",
                            "duration": 0.020,
                        },
                    ],
                    "notes": "Basic file close",
                },
                {
                    "id": "CLOSE-NO-REWIND",
                    "verb": "CLOSE",
                    "organization": "SEQUENTIAL",
                    "access_mode": "N/A",
                    "qualifiers": "NO REWIND",
                    "status": "gap",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [],
                    "notes": "Close without tape rewind",
                },
                {
                    "id": "READ-NEXT-AT-END",
                    "verb": "READ",
                    "organization": "SEQUENTIAL",
                    "access_mode": "SEQUENTIAL",
                    "qualifiers": "AT END",
                    "status": "covered",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_read.py::test_read_at_end",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.012,
                        }
                    ],
                    "notes": "Sequential read with end-of-file check",
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
                {
                    "id": "DISPLAY-TO-CONSOLE",
                    "verb": "DISPLAY",
                    "organization": "N/A",
                    "access_mode": "N/A",
                    "qualifiers": "",
                    "status": "covered",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_display.py::test_display_console",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.003,
                        }
                    ],
                    "notes": "Display output to console",
                },
                {
                    "id": "START-KEY-EQUAL",
                    "verb": "START",
                    "organization": "INDEXED",
                    "access_mode": "RANDOM",
                    "qualifiers": "KEY IS EQUAL",
                    "status": "covered",
                    "requires_fd": True,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_start.py::test_start_key_equal",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.018,
                        }
                    ],
                    "notes": "Position to equal key",
                },
                {
                    "id": "DELETE-INDEXED-INVALID-KEY",
                    "verb": "DELETE",
                    "organization": "INDEXED",
                    "access_mode": "I-O",
                    "qualifiers": "INVALID KEY",
                    "status": "partial",
                    "requires_fd": True,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [
                        {
                            "test_id": "tests/unit/io/test_delete.py::test_delete_invalid",
                            "test_type": "unit",
                            "status": "passed",
                            "duration": 0.025,
                        }
                    ],
                    "notes": "Delete indexed record with error handling",
                },
                {
                    "id": "UNLOCK-INDEXED",
                    "verb": "UNLOCK",
                    "organization": "INDEXED",
                    "access_mode": "I-O",
                    "qualifiers": "",
                    "status": "gap",
                    "requires_fd": False,
                    "ibm_reference": "SC27-8949-30",
                    "tests": [],
                    "notes": "Unlock indexed record",
                },
            ],
            "summary": {
                "OPEN": 2,
                "CLOSE": 2,
                "READ": 1,
                "WRITE": 1,
                "DISPLAY": 1,
                "START": 1,
                "DELETE": 1,
                "UNLOCK": 1,
            },
            "metadata": {
                "source": "pytest-results.json",
                "generator": "io_coverage_reporter",
            },
        }

    @pytest.fixture
    def artifact_file(self, sample_artifact, tmp_path):
        """Create sample artifact file."""
        file_path = tmp_path / "io-coverage.json"
        with open(file_path, "w") as f:
            json.dump(sample_artifact, f)
        return str(file_path)

    def test_render_markdown(self, artifact_file):
        """Test rendering coverage as Markdown."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for key sections
        assert "# IO Coverage Report" in output
        assert "**Coverage:** 60.0%" in output
        assert "| **Total** | 10 |" in output

    def test_render_markdown_summary_table(self, artifact_file):
        """Test that summary table is rendered correctly."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for summary table
        assert "## Summary by Verb" in output
        assert "| Verb |" in output
        assert "| OPEN | 2 |" in output
        assert "| CLOSE | 2 |" in output

    def test_render_markdown_detailed_table(self, artifact_file):
        """Test that detailed variation table is rendered."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for detailed table
        assert "## Detailed Variation Coverage" in output
        assert "OPEN-INPUT-SEQUENTIAL" in output
        assert "CLOSE-NO-REWIND" in output

    def test_render_markdown_status_badges(self, artifact_file):
        """Test that status badges are rendered correctly."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for status badges
        assert "✅ covered" in output  # OPEN-INPUT-SEQUENTIAL
        assert "❌ gap" in output  # CLOSE-NO-REWIND
        assert "⚠️ partial" in output  # CLOSE-SIMPLE

    def test_render_markdown_test_references(self, artifact_file):
        """Test that test references are included."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for test references
        assert "## Test References" in output
        assert "OPEN" in output
        assert "tests/contracts/io/test_open_input.py" in output

    def test_render_markdown_status_legend(self, artifact_file):
        """Test that status legend is included."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Check for legend
        assert "## Status Legend" in output
        assert "**covered**" in output
        assert "**partial**" in output
        assert "**gap**" in output

    def test_render_csv(self, artifact_file):
        """Test rendering coverage as CSV."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_csv()

        # Check for CSV header
        assert "id,verb,organization" in output
        assert "OPEN-INPUT-SEQUENTIAL" in output
        assert "CLOSE-NO-REWIND" in output

    def test_render_csv_fields(self, artifact_file):
        """Test that all expected CSV fields are present."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_csv()

        # Parse CSV
        import csv
        import io

        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)

        assert len(rows) == 10

        # Check first row has all expected fields
        first_row = rows[0]
        assert "id" in first_row
        assert "verb" in first_row
        assert "organization" in first_row
        assert "access_mode" in first_row
        assert "status" in first_row
        assert "test_count" in first_row

    def test_render_summary(self, artifact_file):
        """Test rendering brief summary for CLI."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_summary()

        # Check for summary content
        assert "IO Coverage Summary" in output
        assert "60.0%" in output
        assert "OPEN: 2/2 covered" in output

    def test_status_badge(self, artifact_file):
        """Test status badge generation."""
        renderer = CoverageRenderer(artifact_file)

        assert renderer._status_badge("covered") == "✅ covered"
        assert renderer._status_badge("partial") == "⚠️ partial"
        assert renderer._status_badge("gap") == "❌ gap"
        assert renderer._status_badge("unsupported") == "🚫 unsupported"

    def test_sorted_variations(self, artifact_file):
        """Test that variations are sorted by verb and ID."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Find the detailed table section
        lines = output.split("\n")
        table_start = None
        for i, line in enumerate(lines):
            if "## Detailed Variation Coverage" in line:
                table_start = i + 3  # Skip header lines
                break

        assert table_start is not None

        # Extract variation IDs from table
        variation_ids = []
        for line in lines[table_start:]:
            if line.startswith("|") and "---" not in line:
                parts = line.split("|")
                if len(parts) > 1:
                    var_id = parts[1].strip()
                    if var_id and var_id != "id":
                        variation_ids.append(var_id)

        # Check sorting (by verb then by ID)
        sorted_ids = sorted(variation_ids, key=lambda x: (x.split("-")[0], x))
        assert variation_ids == sorted_ids

    def test_truncated_notes(self, artifact_file):
        """Test that long notes are truncated."""
        renderer = CoverageRenderer(artifact_file)
        output = renderer.render_markdown()

        # Notes should be truncated to 50 chars + "..."
        lines = output.split("\n")
        for line in lines:
            if line.startswith("|") and "..." in line:
                # Find the notes column
                parts = line.split("|")
                for part in parts:
                    if "..." in part:
                        assert len(part.strip()) <= 53  # 50 + "..."


class TestCoverageRendererEdgeCases:
    """Test edge cases for CoverageRenderer."""

    def test_empty_variations(self, tmp_path):
        """Test rendering with no variations."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "parser_version": "1.0.0",
            "total_variations": 0,
            "covered_variations": 0,
            "partial_variations": 0,
            "gap_variations": 0,
            "coverage_percent": 0.0,
            "variations": [],
            "summary": {},
        }

        file_path = tmp_path / "empty.json"
        with open(file_path, "w") as f:
            json.dump(artifact, f)

        renderer = CoverageRenderer(str(file_path))
        output = renderer.render_markdown()

        assert "0.0%" in output
        assert len(output) > 0

    def test_missing_optional_fields(self, tmp_path):
        """Test rendering artifact with missing optional fields."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "total_variations": 1,
            "covered_variations": 1,
            "coverage_percent": 100.0,
            "variations": [
                {
                    "id": "TEST-VARIATION",
                    "verb": "TEST",
                    "status": "covered",
                    "tests": [],
                }
            ],
            "summary": {"TEST": 1},
        }

        file_path = tmp_path / "minimal.json"
        with open(file_path, "w") as f:
            json.dump(artifact, f)

        renderer = CoverageRenderer(str(file_path))
        output = renderer.render_markdown()

        assert "TEST-VARIATION" in output
        assert "100.0%" in output

    def test_variation_without_notes(self, tmp_path):
        """Test rendering variation without notes field."""
        artifact = {
            "version": "1.0.0",
            "generated_at": "2024-01-15T10:30:00Z",
            "total_variations": 1,
            "covered_variations": 1,
            "coverage_percent": 100.0,
            "variations": [
                {
                    "id": "TEST-VARIATION",
                    "verb": "TEST",
                    "status": "covered",
                    "notes": None,
                    "tests": [],
                }
            ],
            "summary": {"TEST": 1},
        }

        file_path = tmp_path / "no-notes.json"
        with open(file_path, "w") as f:
            json.dump(artifact, f)

        renderer = CoverageRenderer(str(file_path))
        output = renderer.render_markdown()

        # Should not crash on None notes
        assert "TEST-VARIATION" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
