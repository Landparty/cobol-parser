"""Unit tests for the CLI interface."""

import json
import os
from io import StringIO
from unittest.mock import patch

import pytest

from cobolparser.cli import main

SAMPLE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "samples", "simple_calculation.cbl"
)


class TestCLIFullParse:
    """Test parsing a full COBOL file via CLI."""

    def test_full_parse_outputs_valid_json(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert output["node_type"] == "Program"
        assert output["program_name"] == "CALC-DEMO"

    def test_compact_flag(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "--compact"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        raw = buf.getvalue().strip()
        # Compact output should be a single line
        assert "\n" not in raw
        output = json.loads(raw)
        assert output["node_type"] == "Program"


class TestCLIPathResolution:
    """Test dot-path navigation into the AST."""

    def test_division_path(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "procedure"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert output["node_type"] == "Division"
        assert output["division_name"] == "PROCEDURE"

    def test_division_case_insensitive(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "PROCEDURE"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert output["division_name"] == "PROCEDURE"

    def test_paragraph_path(self):
        with patch(
            "sys.argv", ["cobol-parser", SAMPLE_FILE, "procedure.MAIN-LOGIC"]
        ):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_statement_type_filter(self):
        with patch(
            "sys.argv",
            ["cobol-parser", SAMPLE_FILE, "procedure.MAIN-LOGIC.display"],
        ):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert isinstance(output, list)
        assert len(output) > 0
        for stmt in output:
            assert stmt["statement_type"] == "DISPLAY"

    def test_data_division_path(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "data"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert output["division_name"] == "DATA"


class TestCLIErrorHandling:
    """Test error cases."""

    def test_file_not_found(self):
        with patch("sys.argv", ["cobol-parser", "/nonexistent/file.cbl"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_invalid_division(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "BOGUS"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_invalid_paragraph(self):
        with patch(
            "sys.argv", ["cobol-parser", SAMPLE_FILE, "procedure.NONEXISTENT"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_invalid_statement_type(self):
        with patch(
            "sys.argv",
            ["cobol-parser", SAMPLE_FILE, "procedure.MAIN-LOGIC.BOGUS"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_path_too_deep(self):
        with patch(
            "sys.argv",
            ["cobol-parser", SAMPLE_FILE, "a.b.c.d"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestCLIFlags:
    """Test --errors and --stats flags."""

    def test_errors_flag(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "--errors"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert "ast" in output
        assert "errors" in output
        assert "warnings" in output

    def test_stats_flag(self):
        with patch("sys.argv", ["cobol-parser", SAMPLE_FILE, "--stats"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert "ast" in output
        assert "statistics" in output
        assert "lines_processed" in output["statistics"]

    def test_errors_and_stats_combined(self):
        with patch(
            "sys.argv", ["cobol-parser", SAMPLE_FILE, "--errors", "--stats"]
        ):
            buf = StringIO()
            with patch("sys.stdout", buf):
                main()
        output = json.loads(buf.getvalue())
        assert "ast" in output
        assert "errors" in output
        assert "statistics" in output
