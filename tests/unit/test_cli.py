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
COPYBOOK_PROGRAM_FILE = os.path.abspath(
    os.path.join(SAMPLE_DIR, "copybook_programs", "basic_copy.cbl")
)
COPYBOOK_DIR = os.path.abspath(os.path.join(SAMPLE_DIR, "copybooks"))


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


def _run_cli_path(*args: str) -> dict | list:
    """Run CLI with a dot-path and return the identified extraction result."""
    output = _run_cli_json(*args)
    assert "source_file" in output
    assert "program_id" in output
    return output["result"]


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
        output = _run_cli_path(SAMPLE_FILE, "procedure")
        assert output["node_type"] == "Division"
        assert output["division_name"] == "PROCEDURE"

    def test_division_case_insensitive(self):
        output = _run_cli_path(SAMPLE_FILE, "PROCEDURE")
        assert output["division_name"] == "PROCEDURE"

    def test_division_mixed_case(self):
        output = _run_cli_path(SAMPLE_FILE, "Procedure")
        assert output["division_name"] == "PROCEDURE"

    def test_paragraph_path(self):
        output = _run_cli_path(SAMPLE_FILE, "procedure.MAIN-LOGIC")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_paragraph_case_insensitive(self):
        output = _run_cli_path(SAMPLE_FILE, "procedure.main-logic")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_statement_type_filter(self):
        output = _run_cli_path(SAMPLE_FILE, "procedure.MAIN-LOGIC.display")
        assert isinstance(output, list)
        assert len(output) > 0
        for stmt in output:
            assert stmt["statement_type"] == "DISPLAY"

    def test_statement_type_case_insensitive(self):
        output = _run_cli_path(SAMPLE_FILE, "procedure.MAIN-LOGIC.DISPLAY")
        assert isinstance(output, list)
        assert len(output) > 0

    def test_data_division_path(self):
        output = _run_cli_path(SAMPLE_FILE, "data")
        assert output["division_name"] == "DATA"

    def test_data_division_section(self):
        output = _run_cli_path(SAMPLE_FILE, "data.WORKING-STORAGE")
        assert output["node_type"] == "Section"
        assert output["section_name"] == "WORKING-STORAGE"

    def test_identification_division(self):
        output = _run_cli_path(SAMPLE_FILE, "identification")
        assert output["division_name"] == "IDENTIFICATION"


class TestCLIPathEdgeCases:
    """Test edge cases in path resolution."""

    def test_empty_path_string(self):
        # Empty string is falsy, should output full AST
        output = _run_cli_json(SAMPLE_FILE, "")
        assert output["node_type"] == "Program"

    def test_trailing_dot(self):
        # "procedure." → ["procedure", ""] → empty filtered out → ["procedure"]
        output = _run_cli_path(SAMPLE_FILE, "procedure.")
        assert output["division_name"] == "PROCEDURE"

    def test_leading_dot(self):
        # ".procedure" → ["", "procedure"] → empty filtered out → ["procedure"]
        output = _run_cli_path(SAMPLE_FILE, ".procedure")
        assert output["division_name"] == "PROCEDURE"

    def test_multiple_dots(self):
        # "procedure..MAIN-LOGIC" → empty components filtered → ["procedure", "MAIN-LOGIC"]
        output = _run_cli_path(SAMPLE_FILE, "procedure..MAIN-LOGIC")
        assert output["paragraph_name"] == "MAIN-LOGIC"

    def test_only_dots(self):
        # "..." → all empty → empty path
        assert _run_cli_expect_fail(SAMPLE_FILE, "...") == 1

    def test_path_too_deep(self):
        assert _run_cli_expect_fail(SAMPLE_FILE, "a.b.c.d") == 1

    def test_path_with_whitespace(self):
        # Whitespace around components is stripped
        output = _run_cli_path(SAMPLE_FILE, " procedure . MAIN-LOGIC ")
        assert output["paragraph_name"] == "MAIN-LOGIC"


class TestCLIErrorHandling:
    """Test error cases."""

    def test_file_not_found(self):
        assert _run_cli_expect_fail("/nonexistent/file.cbl") == 1

    def test_non_utf8_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", delete=False) as f:
            f.write(b"\x80\x81\x82\xff\xfe")
            fname = f.name
        try:
            # #522: a non-UTF-8 program is decoded (detected encoding), not
            # refused with exit 1. These bytes decode to no program at all,
            # so the parse collects errors and the CLI exits 2 -- still
            # non-zero, now for the right reason.
            with patch("sys.argv", ["cobol-parser", fname]):
                buf = StringIO()
                with patch("sys.stdout", buf):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
            assert exc_info.value.code == 2
            assert json.loads(buf.getvalue())["node_type"] == "Program"
        finally:
            os.unlink(fname)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write("")
            fname = f.name
        try:
            # Empty file parses to a minimal program — should not crash, but
            # the parse collects an error so the CLI must exit non-zero
            # (2026-07-07 audit C7: no more exit 0 on an errored parse).
            with patch("sys.argv", ["cobol-parser", fname]):
                buf = StringIO()
                with patch("sys.stdout", buf):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
            assert exc_info.value.code == 2
            output = json.loads(buf.getvalue())
            assert output["node_type"] == "Program"
        finally:
            os.unlink(fname)

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
        assert "result" in output
        assert output["result"]["division_name"] == "PROCEDURE"
        assert "errors" in output

    def test_stats_flag_with_path(self):
        output = _run_cli_json(SAMPLE_FILE, "procedure", "--stats")
        assert "result" in output
        assert output["result"]["division_name"] == "PROCEDURE"
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
        output = _run_cli_path(DECLARATIVES_FILE, "procedure.MAIN-LOGIC")
        assert output["node_type"] == "Section"
        assert output["section_name"] == "MAIN-LOGIC"

    def test_multiple_paragraphs_different_file(self):
        # control_flow.cbl has many paragraphs, verify a few are reachable
        output = _run_cli_path(CONTROL_FLOW_FILE, "procedure.IF-TESTS")
        assert output["paragraph_name"] == "IF-TESTS"

    def test_statement_filter_on_paragraph(self):
        output = _run_cli_path(CONTROL_FLOW_FILE, "procedure.GOTO-TARGET.display")
        assert isinstance(output, list)
        assert len(output) > 0
        for stmt in output:
            assert stmt["statement_type"] == "DISPLAY"


class TestCLISubcommandDispatch:
    """Test backward compatibility and explicit subcommand dispatch."""

    def test_implicit_parse_backward_compat(self):
        """No subcommand given → should still parse."""
        output = _run_cli_json(SAMPLE_FILE)
        assert output["node_type"] == "Program"

    def test_explicit_parse_subcommand(self):
        """Explicit 'parse' subcommand produces same output."""
        output = _run_cli_json("parse", SAMPLE_FILE)
        assert output["node_type"] == "Program"
        assert output["program_name"] == "CALC-DEMO"

    def test_explicit_parse_with_path(self):
        output = _run_cli_path("parse", SAMPLE_FILE, "procedure")
        assert output["division_name"] == "PROCEDURE"

    def test_explicit_parse_with_flags(self):
        output = _run_cli_json("parse", SAMPLE_FILE, "--errors", "--stats")
        assert "ast" in output
        assert "errors" in output
        assert "statistics" in output


class TestCLIParseNewFlags:
    """Test new flags on the parse subcommand."""

    def test_error_recovery_fail_fast(self):
        output = _run_cli_json(SAMPLE_FILE, "--error-recovery", "fail-fast")
        assert output["node_type"] == "Program"

    def test_error_recovery_collect_all(self):
        output = _run_cli_json(SAMPLE_FILE, "--error-recovery", "collect-all")
        assert output["node_type"] == "Program"

    def test_find_type_display(self):
        output = _run_cli_json(SAMPLE_FILE, "--find-type", "DisplayStatement")
        assert output["node_type"] == "DisplayStatement"
        assert isinstance(output["matches"], list)
        for node in output["matches"]:
            assert node["statement_type"] == "DISPLAY"

    def test_find_type_no_matches(self):
        output = _run_cli_json(SAMPLE_FILE, "--find-type", "NonexistentType")
        assert isinstance(output["matches"], list)
        assert len(output["matches"]) == 0

    def test_find_type_with_compact(self):
        raw = _run_cli(
            "parse", SAMPLE_FILE, "--find-type", "DisplayStatement", "--compact"
        ).strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert isinstance(output["matches"], list)

    def test_copybook_path_flag(self):
        output = _run_cli_json(
            "parse",
            COPYBOOK_PROGRAM_FILE,
            "--copybook-path",
            COPYBOOK_DIR,
        )
        assert output["node_type"] == "Program"

    def test_define_flag(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. TESTDEF.\n"
                "       PROCEDURE DIVISION.\n"
                "       MAIN-LOGIC.\n"
                ">>IF DEBUG IS DEFINED\n"
                "           DISPLAY 'DEBUG MODE'.\n"
                ">>END-IF\n"
                "           STOP RUN.\n"
            )
            fname = f.name
        try:
            output = _run_cli_json("parse", fname, "--define", "DEBUG")
            assert output["node_type"] == "Program"
        finally:
            os.unlink(fname)

    def test_define_with_value(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. TESTDEF.\n"
                "       PROCEDURE DIVISION.\n"
                "       MAIN-LOGIC.\n"
                "           STOP RUN.\n"
            )
            fname = f.name
        try:
            output = _run_cli_json("parse", fname, "--define", "ENV=PROD")
            assert output["node_type"] == "Program"
        finally:
            os.unlink(fname)


class TestCLIBatch:
    """Test the batch subcommand."""

    def test_batch_two_files(self):
        output = _run_cli_json("batch", SAMPLE_FILE, CONTROL_FLOW_FILE)
        assert isinstance(output, list)
        assert len(output) == 2
        assert output[0]["path"].endswith("simple_calculation.cbl")
        assert output[1]["path"].endswith("control_flow.cbl")
        assert output[0]["success"] is True
        assert output[1]["success"] is True

    def test_batch_with_ast(self):
        output = _run_cli_json("batch", SAMPLE_FILE)
        assert len(output) == 1
        assert "ast" in output[0]
        assert output[0]["ast"]["node_type"] == "Program"

    def test_batch_compact(self):
        raw = _run_cli("batch", SAMPLE_FILE, "--compact").strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert isinstance(output, list)

    def test_batch_with_errors_flag(self):
        output = _run_cli_json("batch", SAMPLE_FILE, "--errors")
        assert "errors" in output[0]
        assert "warnings" in output[0]

    def test_batch_with_stats_flag(self):
        output = _run_cli_json("batch", SAMPLE_FILE, "--stats")
        assert "statistics" in output[0]
        assert "lines_processed" in output[0]["statistics"]

    def test_batch_with_workers(self):
        output = _run_cli_json(
            "batch", SAMPLE_FILE, CONTROL_FLOW_FILE, "--workers", "1"
        )
        assert len(output) == 2

    def test_batch_nonexistent_file(self):
        # A failed file is reported in the JSON AND in the exit code
        # (2026-07-07 audit C7: batch no longer exits 0 when files fail).
        with patch("sys.argv", ["cobol-parser", "batch", "/nonexistent/file.cbl"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 2
        output = json.loads(buf.getvalue())
        assert len(output) == 1
        assert "read_error" in output[0]

    def test_batch_error_recovery_flag(self):
        output = _run_cli_json("batch", SAMPLE_FILE, "--error-recovery", "fail-fast")
        assert isinstance(output, list)


class TestCLITokenize:
    """Test the tokenize subcommand."""

    def test_tokenize_outputs_identified_tokens(self):
        output = _run_cli_json("tokenize", SAMPLE_FILE)
        assert output["source_file"] == SAMPLE_FILE
        assert isinstance(output["tokens"], list)
        assert len(output["tokens"]) > 0

    def test_tokenize_token_structure(self):
        output = _run_cli_json("tokenize", SAMPLE_FILE)
        token = output["tokens"][0]
        assert "type" in token
        assert "value" in token
        assert "line" in token
        assert "column" in token

    def test_tokenize_compact(self):
        raw = _run_cli("tokenize", SAMPLE_FILE, "--compact").strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert isinstance(output["tokens"], list)

    def test_tokenize_free_form(self):
        output = _run_cli_json("tokenize", SAMPLE_FILE, "--free-form")
        assert isinstance(output["tokens"], list)

    def test_tokenize_file_not_found(self):
        assert _run_cli_expect_fail("tokenize", "/nonexistent/file.cbl") == 1

    def test_tokenize_has_expected_types(self):
        output = _run_cli_json("tokenize", SAMPLE_FILE)
        types = {t["type"] for t in output["tokens"]}
        # Should have at least identifiers and periods
        assert "IDENTIFIER" in types or "PERIOD" in types


class TestCLIPreprocess:
    """Test the preprocess subcommand."""

    def test_preprocess_fixed_format(self):
        raw = _run_cli("preprocess", SAMPLE_FILE)
        assert "IDENTIFICATION DIVISION" in raw
        assert "PROGRAM-ID" in raw

    def test_preprocess_free_form_passthrough(self):
        raw = _run_cli("preprocess", SAMPLE_FILE, "--free-form")
        # With --free-form, no normalization is applied
        assert len(raw) > 0

    def test_preprocess_strip_directives(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                "       PROCESS APOST\n"
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. TESTPROG.\n"
            )
            fname = f.name
        try:
            raw = _run_cli("preprocess", fname, "--strip-directives")
            assert "PROCESS" not in raw
            assert "IDENTIFICATION" in raw
        finally:
            os.unlink(fname)

    def test_preprocess_with_define(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                ">>DEFINE TESTVAR\n"
                ">>IF TESTVAR IS DEFINED\n"
                "       IDENTIFICATION DIVISION.\n"
                ">>END-IF\n"
                "       PROGRAM-ID. CONDPROG.\n"
            )
            fname = f.name
        try:
            raw = _run_cli("preprocess", fname, "--free-form")
            assert "IDENTIFICATION" in raw
        finally:
            os.unlink(fname)

    def test_preprocess_with_external_define(self):
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                ">>IF MYVAR IS DEFINED\n"
                "       IDENTIFICATION DIVISION.\n"
                ">>END-IF\n"
                "       PROGRAM-ID. CONDPROG.\n"
            )
            fname = f.name
        try:
            raw = _run_cli("preprocess", fname, "--define", "MYVAR", "--free-form")
            assert "IDENTIFICATION" in raw
        finally:
            os.unlink(fname)

    def test_preprocess_file_not_found(self):
        assert _run_cli_expect_fail("preprocess", "/nonexistent/file.cbl") == 1


class TestCLIExpand:
    """Test the expand subcommand."""

    def test_expand_basic(self):
        output = _run_cli_json(
            "expand",
            COPYBOOK_PROGRAM_FILE,
            "--copybook-path",
            COPYBOOK_DIR,
        )
        assert "expanded_source" in output
        assert "included_copybooks" in output
        assert "statistics" in output

    def test_expand_includes_copybooks(self):
        output = _run_cli_json(
            "expand",
            COPYBOOK_PROGRAM_FILE,
            "--copybook-path",
            COPYBOOK_DIR,
        )
        assert len(output["included_copybooks"]) > 0

    def test_expand_compact(self):
        raw = _run_cli(
            "expand",
            COPYBOOK_PROGRAM_FILE,
            "--copybook-path",
            COPYBOOK_DIR,
            "--compact",
        ).strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert "expanded_source" in output

    def test_expand_max_depth(self):
        output = _run_cli_json(
            "expand",
            COPYBOOK_PROGRAM_FILE,
            "--copybook-path",
            COPYBOOK_DIR,
            "--max-depth",
            "50",
        )
        assert "expanded_source" in output

    def test_expand_no_copybook_path_on_file_without_copy(self):
        # Without --copybook-path, expand works on files without COPY statements
        output = _run_cli_json("expand", SAMPLE_FILE)
        assert "expanded_source" in output

    def test_expand_file_not_found(self):
        assert _run_cli_expect_fail("expand", "/nonexistent/file.cbl") == 1


class TestCLIAnalyze:
    """Test the analyze subcommand."""

    def test_analyze_basic(self):
        output = _run_cli_json("analyze", SAMPLE_FILE)
        assert "calls" in output
        assert isinstance(output["calls"], list)

    def test_analyze_compact(self):
        raw = _run_cli("analyze", SAMPLE_FILE, "--compact").strip()
        assert "\n" not in raw
        output = json.loads(raw)
        assert "calls" in output

    def test_analyze_with_call_statements(self):
        # Use control_flow.cbl which may have CALL statements
        output = _run_cli_json("analyze", CONTROL_FLOW_FILE)
        assert "calls" in output

    def test_analyze_file_not_found(self):
        assert _run_cli_expect_fail("analyze", "/nonexistent/file.cbl") == 1
