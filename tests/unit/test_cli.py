"""Unit tests for the CLI interface."""

import json
import os
import tempfile
from io import StringIO
from unittest.mock import patch

import pytest

from cobolparser.cli import main

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")
SAMPLE_FILE = os.path.join(SAMPLE_DIR, "simple_calculation.cbl")
DECLARATIVES_FILE = os.path.join(SAMPLE_DIR, "declaratives_section.cbl")
CONTROL_FLOW_FILE = os.path.join(SAMPLE_DIR, "control_flow.cbl")


def _run_cli(*args: str) -> str:
    """Run CLI with given args and return stdout."""
    with patch("sys.argv", ["cobol-parser", *args]):
        buf = StringIO()
        with patch("sys.stdout", buf):
            main()
    return buf.getvalue()


def _run_cli_json(*args: str) -> dict | list:
    """Run CLI and parse JSON output."""
    return json.loads(_run_cli(*args))


def _run_cli_expect_fail(*args: str) -> int:
    """Run CLI expecting SystemExit, return exit code."""
    with patch("sys.argv", ["cobol-parser", *args]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code


class TestCLIFullParse:
    """Test parsing a full COBOL file via CLI."""

    def test_full_parse_outputs_valid_json(self):
        output = _run_cli_json(SAMPLE_FILE)
        assert output["node_type"] == "Program"
        assert output["program_name"] == "CALC-DEMO"

    def test_compact_flag(self):
        raw = _run_cli(SAMPLE_FILE, "--compact").strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert output["node_type"] == "Program"

    def test_free_form_flag(self):
        # Should not crash; free-form flag is passed through to parser
        output = _run_cli_json(SAMPLE_FILE, "--free-form")
        assert output["node_type"] == "Program"


class TestCLIPathResolution:
    """Test dot-path navigation into the AST."""

    def test_division_path(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure")
        assert output["node_type"] == "Division"
        assert output["division_name"] == "PROCEDURE"

    def test_division_case_insensitive(self):
        output = _run_cli_json(SAMPLE_FILE, "PROCEDURE")
        assert output["division_name"] == "PROCEDURE"

    def test_division_mixed_case(self):
        output = _run_cli_json(SAMPLE_FILE, "Procedure")
        assert output["division_name"] == "PROCEDURE"

    def test_paragraph_path(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure.MAIN-LOGIC")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_paragraph_case_insensitive(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure.main-logic")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_statement_type_filter(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure.MAIN-LOGIC.display")
        assert isinstance(output, list)
        assert len(output) > 0
        for stmt in output:
            assert stmt["statement_type"] == "DISPLAY"

    def test_statement_type_case_insensitive(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure.MAIN-LOGIC.DISPLAY")
        assert isinstance(output, list)
        assert len(output) > 0

    def test_data_division_path(self):
        output = _run_cli_json(SAMPLE_FILE, "data")
        assert output["division_name"] == "DATA"

    def test_data_division_section(self):
        output = _run_cli_json(SAMPLE_FILE, "data.WORKING-STORAGE")
        assert output["node_type"] == "Section"
        assert output["section_name"] == "WORKING-STORAGE"

    def test_identification_division(self):
        output = _run_cli_json(SAMPLE_FILE, "identification")
        assert output["division_name"] == "IDENTIFICATION"


class TestCLIPathEdgeCases:
    """Test edge cases in path resolution."""

    def test_empty_path_string(self):
        # Empty string is falsy, should output full AST
        output = _run_cli_json(SAMPLE_FILE, "")
        assert output["node_type"] == "Program"

    def test_trailing_dot(self):
        # "procedure." → ["procedure", ""] → empty filtered out → ["procedure"]
        output = _run_cli_json(SAMPLE_FILE, "procedure.")
        assert output["division_name"] == "PROCEDURE"

    def test_leading_dot(self):
        # ".procedure" → ["", "procedure"] → empty filtered out → ["procedure"]
        output = _run_cli_json(SAMPLE_FILE, ".procedure")
        assert output["division_name"] == "PROCEDURE"

    def test_multiple_dots(self):
        # "procedure..MAIN-LOGIC" → empty components filtered → ["procedure", "MAIN-LOGIC"]
        output = _run_cli_json(SAMPLE_FILE, "procedure..MAIN-LOGIC")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_only_dots(self):
        # "..." → all empty → empty path
        assert _run_cli_expect_fail(SAMPLE_FILE, "...") == 1

    def test_path_too_deep(self):
        assert _run_cli_expect_fail(SAMPLE_FILE, "a.b.c.d") == 1

    def test_path_with_whitespace(self):
        # Whitespace around components is stripped
        output = _run_cli_json(SAMPLE_FILE, " procedure . MAIN-LOGIC ")
        assert output["paragraph_name"] == "MAIN-LOGIC"


class TestCLIErrorHandling:
    """Test error cases."""

    def test_file_not_found(self):
        assert _run_cli_expect_fail("/nonexistent/file.cbl") == 1

    def test_non_utf8_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", delete=False) as f:
            f.write(b"\x80\x81\x82\xff\xfe")
            f.flush()
            try:
                assert _run_cli_expect_fail(f.name) == 1
            finally:
                os.unlink(f.name)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write("")
            f.flush()
            try:
                # Empty file parses to a minimal program — should not crash
                output = _run_cli_json(f.name)
                assert output["node_type"] == "Program"
            finally:
                os.unlink(f.name)

    def test_invalid_division(self):
        assert _run_cli_expect_fail(SAMPLE_FILE, "BOGUS") == 1

    def test_invalid_paragraph(self):
        assert _run_cli_expect_fail(SAMPLE_FILE, "procedure.NONEXISTENT") == 1

    def test_invalid_statement_type(self):
        assert _run_cli_expect_fail(SAMPLE_FILE, "procedure.MAIN-LOGIC.BOGUS") == 1

    def test_paragraph_with_no_matching_statement(self):
        # MAIN-LOGIC has no CALL statements
        assert _run_cli_expect_fail(SAMPLE_FILE, "procedure.MAIN-LOGIC.CALL") == 1

    def test_division_with_no_sections_or_paragraphs(self):
        # IDENTIFICATION division typically has no navigable children
        assert _run_cli_expect_fail(SAMPLE_FILE, "identification.SOMETHING") == 1


class TestCLIFlags:
    """Test --errors and --stats flags."""

    def test_errors_flag(self):
        output = _run_cli_json(SAMPLE_FILE, "--errors")
        assert "ast" in output
        assert "errors" in output
        assert "warnings" in output
        assert isinstance(output["errors"], list)
        assert isinstance(output["warnings"], list)

    def test_stats_flag(self):
        output = _run_cli_json(SAMPLE_FILE, "--stats")
        assert "ast" in output
        assert "statistics" in output
        assert "lines_processed" in output["statistics"]
        assert "tokens_processed" in output["statistics"]
        assert "parse_time_seconds" in output["statistics"]
        assert "memory_peak_mb" in output["statistics"]

    def test_errors_and_stats_combined(self):
        output = _run_cli_json(SAMPLE_FILE, "--errors", "--stats")
        assert "ast" in output
        assert "errors" in output
        assert "statistics" in output

    def test_errors_flag_with_path(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure", "--errors")
        assert "ast" in output
        assert output["ast"]["division_name"] == "PROCEDURE"
        assert "errors" in output

    def test_stats_flag_with_path(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure", "--stats")
        assert "ast" in output
        assert output["ast"]["division_name"] == "PROCEDURE"
        assert "statistics" in output

    def test_compact_with_errors(self):
        raw = _run_cli(SAMPLE_FILE, "--errors", "--compact").strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert "ast" in output
        assert "errors" in output


class TestCLISectionNavigation:
    """Test navigation into sections that contain paragraphs."""

    def test_section_in_procedure_division(self):
        output = _run_cli_json(DECLARATIVES_FILE, "procedure.MAIN-LOGIC")
        assert output["node_type"] == "Section"
        assert output["section_name"] == "MAIN-LOGIC"

    def test_multiple_paragraphs_different_file(self):
        # control_flow.cbl has many paragraphs, verify a few are reachable
        output = _run_cli_json(CONTROL_FLOW_FILE, "procedure.IF-TESTS")
        assert output["paragraph_name"] == "IF-TESTS"

    def test_statement_filter_on_paragraph(self):
        output = _run_cli_json(CONTROL_FLOW_FILE, "procedure.GOTO-TARGET.display")
        assert isinstance(output, list)
        assert len(output) > 0
        for stmt in output:
            assert stmt["statement_type"] == "DISPLAY"
