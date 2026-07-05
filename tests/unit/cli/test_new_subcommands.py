"""Tests for the new CLI subcommands added to cobolparser.cli.parse:
io-sequence, move-type-check, linkage-check, language-env, ims-dli,
plus --output/-o flag and --glob flag for batch, and --version flag.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser import __version__
from cobolparser.cli.parse import (
    _build_parser,
    _cmd_ims_dli,
    _cmd_io_sequence,
    _cmd_language_env,
    _cmd_linkage_check,
    _cmd_move_type_check,
    _json_out,
    main,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SAMPLES = Path(__file__).parents[2] / "samples"

_SIMPLE = str(SAMPLES / "simple_calculation.cbl")
_FILE_OPS = str(SAMPLES / "file_operations.cbl")
_IBM = str(SAMPLES / "ibm_extensions.cbl")
_DYNAMIC = str(SAMPLES / "call_dynamic_programs.cbl")


def _make_args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": False,
        "free_form": False,
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "define": [],
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# _json_out with output_path
# ---------------------------------------------------------------------------


class TestJsonOut:
    def test_writes_to_stdout_by_default(self, capsys):
        _json_out({"key": "val"}, compact=False)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data == {"key": "val"}

    def test_writes_compact(self, capsys):
        _json_out({"a": 1}, compact=True)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        assert json.loads(out) == {"a": 1}

    def test_writes_to_file(self, tmp_path):
        out_file = str(tmp_path / "out.json")
        _json_out({"x": 42}, compact=False, output_path=out_file)
        content = Path(out_file).read_text()
        assert json.loads(content) == {"x": 42}

    def test_file_write_oserror_exits(self, tmp_path):
        bad_path = str(tmp_path / "no_dir" / "out.json")
        with pytest.raises(SystemExit):
            _json_out({"x": 1}, compact=False, output_path=bad_path)


# ---------------------------------------------------------------------------
# --version flag
# ---------------------------------------------------------------------------


class TestVersionFlag:
    def test_version_flag_exits(self, capsys):
        with patch("sys.argv", ["cobol-parser", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_version_flag_output_contains_version(self, capsys):
        with patch("sys.argv", ["cobol-parser", "--version"]):
            with pytest.raises(SystemExit):
                main()
        # argparse writes --version to stdout
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "cobol-parser" in output
        assert __version__ in output


# ---------------------------------------------------------------------------
# Subcommand: io-sequence
# ---------------------------------------------------------------------------


class TestCmdIoSequence:
    def test_outputs_report_dict(self, capsys):
        args = _make_args(_FILE_OPS)
        _cmd_io_sequence(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "has_violations" in data
        assert "violations" in data
        assert isinstance(data["violations"], list)

    def test_simple_file_no_io_statements(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_io_sequence(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "violations" in data

    def test_compact_output(self, capsys):
        args = _make_args(_SIMPLE, compact=True)
        _cmd_io_sequence(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)

    def test_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "io_seq.json")
        args = _make_args(_SIMPLE, output=out_file)
        _cmd_io_sequence(args)
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "has_violations" in data

    def test_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_io_sequence(args)

    def test_violation_count_in_output(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_io_sequence(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "violation_count" in data
        assert isinstance(data["violation_count"], int)


# ---------------------------------------------------------------------------
# Subcommand: move-type-check
# ---------------------------------------------------------------------------


class TestCmdMoveTypeCheck:
    def test_outputs_report_dict(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_move_type_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error_count" in data
        assert "warning_count" in data
        assert "violations" in data
        assert isinstance(data["violations"], list)

    def test_compact_output(self, capsys):
        args = _make_args(_SIMPLE, compact=True)
        _cmd_move_type_check(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)

    def test_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "move.json")
        args = _make_args(_SIMPLE, output=out_file)
        _cmd_move_type_check(args)
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "error_count" in data

    def test_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_move_type_check(args)

    def test_counts_are_non_negative(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_move_type_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["error_count"] >= 0
        assert data["warning_count"] >= 0


# ---------------------------------------------------------------------------
# Subcommand: linkage-check
# ---------------------------------------------------------------------------


class TestCmdLinkageCheck:
    def test_outputs_report_dict(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_linkage_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "has_violations" in data
        assert "violations" in data
        assert "entry_interfaces" in data
        assert "linkage_items" in data

    def test_compact_output(self, capsys):
        args = _make_args(_SIMPLE, compact=True)
        _cmd_linkage_check(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)

    def test_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "linkage.json")
        args = _make_args(_SIMPLE, output=out_file)
        _cmd_linkage_check(args)
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "has_violations" in data

    def test_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_linkage_check(args)

    def test_violation_count_field(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_linkage_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "violation_count" in data


# ---------------------------------------------------------------------------
# Subcommand: language-env
# ---------------------------------------------------------------------------


class TestCmdLanguageEnv:
    def test_outputs_report_dict(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_language_env(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "uses_intrinsic_functions" in data
        assert "uses_language_environment" in data
        assert "unique_functions" in data
        assert "unique_services" in data
        assert "intrinsic_usages" in data
        assert "le_service_calls" in data

    def test_compact_output(self, capsys):
        args = _make_args(_SIMPLE, compact=True)
        _cmd_language_env(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)

    def test_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "le.json")
        args = _make_args(_SIMPLE, output=out_file)
        _cmd_language_env(args)
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "uses_intrinsic_functions" in data

    def test_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_language_env(args)

    def test_ibm_extensions_file(self, capsys):
        args = _make_args(_IBM)
        _cmd_language_env(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        # IBM extensions file may use intrinsic functions
        assert isinstance(data["unique_functions"], list)
        assert isinstance(data["unique_services"], list)


# ---------------------------------------------------------------------------
# Subcommand: ims-dli
# ---------------------------------------------------------------------------


class TestCmdImsDli:
    def test_outputs_report_dict(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_ims_dli(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "dli_call_count" in data
        assert "all_segments" in data
        assert "dli_calls" in data
        assert isinstance(data["dli_calls"], list)
        assert isinstance(data["all_segments"], list)

    def test_simple_file_no_dli_calls(self, capsys):
        args = _make_args(_SIMPLE)
        _cmd_ims_dli(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["dli_call_count"] == 0
        assert data["all_segments"] == []

    def test_compact_output(self, capsys):
        args = _make_args(_SIMPLE, compact=True)
        _cmd_ims_dli(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)

    def test_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "ims.json")
        args = _make_args(_SIMPLE, output=out_file)
        _cmd_ims_dli(args)
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "dli_call_count" in data

    def test_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_ims_dli(args)


# ---------------------------------------------------------------------------
# --output/-o flag via main() entry point
# ---------------------------------------------------------------------------


class TestOutputFlag:
    def test_parse_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "ast.json")
        with patch("sys.argv", ["cobol-parser", "parse", _SIMPLE, "-o", out_file]):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "node_type" in data or "program_name" in data
        # nothing on stdout
        assert capsys.readouterr().out == ""

    def test_tokenize_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "tokens.json")
        with patch("sys.argv", ["cobol-parser", "tokenize", _SIMPLE, "-o", out_file]):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert data["source_file"] == _SIMPLE
        assert isinstance(data["tokens"], list)
        assert len(data["tokens"]) > 0

    def test_dead_code_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "dead.json")
        with patch("sys.argv", ["cobol-parser", "dead-code", _SIMPLE, "-o", out_file]):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, dict)

    def test_program_flow_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "flow.json")
        with patch(
            "sys.argv",
            ["cobol-parser", "program-flow", _SIMPLE, "-o", out_file],
        ):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, dict)

    def test_analyze_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "analyze.json")
        with patch("sys.argv", ["cobol-parser", "analyze", _DYNAMIC, "-o", out_file]):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert "calls" in data


# ---------------------------------------------------------------------------
# --glob flag for batch
# ---------------------------------------------------------------------------


class TestBatchGlob:
    def test_glob_expands_files(self, tmp_path, capsys):
        # Create two minimal COBOL files in a temp dir
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        (tmp_path / "a.cbl").write_text(cobol)
        (tmp_path / "b.cbl").write_text(cobol)
        pattern = str(tmp_path / "*.cbl")
        with patch("sys.argv", ["cobol-parser", "batch", "--glob", pattern]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_glob_no_match_warns_and_fails(self, tmp_path, capsys):
        pattern = str(tmp_path / "*.cbl")  # empty dir
        with patch("sys.argv", ["cobol-parser", "batch", "--glob", pattern]):
            with pytest.raises(SystemExit):
                main()
        err = capsys.readouterr().err
        assert "matched no files" in err or "No input files" in err

    def test_glob_and_explicit_files_combined(self, tmp_path, capsys):
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        (tmp_path / "a.cbl").write_text(cobol)
        (tmp_path / "b.cbl").write_text(cobol)
        explicit = str(tmp_path / "a.cbl")
        pattern = str(tmp_path / "*.cbl")
        # a.cbl appears both explicitly and via glob; dedup should give 2 files
        with patch(
            "sys.argv",
            ["cobol-parser", "batch", explicit, "--glob", pattern],
        ):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2  # deduplicated

    def test_dedup_resolves_relative_vs_absolute(self, tmp_path, capsys):
        """Same file given as absolute and via glob (which may return absolute)
        should only appear once in the output."""
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        f = tmp_path / "only.cbl"
        f.write_text(cobol)
        abs_path = str(f.resolve())
        pattern = str(tmp_path / "*.cbl")
        # Pass absolute path explicitly AND expand it via glob – should deduplicate
        with patch(
            "sys.argv",
            ["cobol-parser", "batch", abs_path, "--glob", pattern],
        ):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1  # only.cbl counted once

    def test_glob_output_is_sorted(self, tmp_path, capsys):
        """Files matched by --glob should appear in sorted (deterministic) order."""
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        for name in ("c.cbl", "a.cbl", "b.cbl"):
            (tmp_path / name).write_text(cobol)
        pattern = str(tmp_path / "*.cbl")
        with patch("sys.argv", ["cobol-parser", "batch", "--glob", pattern]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        paths = [entry["path"] for entry in data]
        assert paths == sorted(paths)

    def test_batch_no_files_fails(self, capsys):
        with patch("sys.argv", ["cobol-parser", "batch"]):
            with pytest.raises(SystemExit):
                main()


# ---------------------------------------------------------------------------
# New subcommands registered in parser
# ---------------------------------------------------------------------------


class TestNewSubcommandsRegistered:
    @pytest.mark.parametrize(
        "subcmd",
        [
            "io-sequence",
            "move-type-check",
            "linkage-check",
            "language-env",
            "ims-dli",
        ],
    )
    def test_subcommand_in_parser(self, subcmd):
        parser = _build_parser()
        # Parsing --help for a valid subcommand should not raise (except SystemExit from help)
        with pytest.raises(SystemExit):
            parser.parse_args([subcmd, "--help"])

    @pytest.mark.parametrize(
        "subcmd",
        [
            "io-sequence",
            "move-type-check",
            "linkage-check",
            "language-env",
            "ims-dli",
        ],
    )
    def test_subcommand_via_main(self, subcmd, capsys):
        with patch("sys.argv", ["cobol-parser", subcmd, _SIMPLE]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# _json_out: compact + file output together (previously untested combination)
# ---------------------------------------------------------------------------


class TestJsonOutCompactFile:
    def test_compact_and_file_combined(self, tmp_path):
        out_file = str(tmp_path / "compact.json")
        _json_out({"a": [1, 2]}, compact=True, output_path=out_file)
        content = Path(out_file).read_text()
        # compact means no interior newlines (trailing newline from write is ok)
        lines = content.splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"a": [1, 2]}

    def test_compact_false_file_is_pretty(self, tmp_path):
        out_file = str(tmp_path / "pretty.json")
        _json_out({"a": [1, 2]}, compact=False, output_path=out_file)
        content = Path(out_file).read_text()
        # pretty-printed: multiple lines
        assert content.count("\n") > 1
        assert json.loads(content) == {"a": [1, 2]}


# ---------------------------------------------------------------------------
# expand --output flag (was missing from original implementation)
# ---------------------------------------------------------------------------


class TestExpandOutput:
    def test_expand_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "expand.json")
        with patch("sys.argv", ["cobol-parser", "expand", _SIMPLE, "-o", out_file]):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, dict)
        # stdout is empty when writing to file
        assert capsys.readouterr().out == ""

    def test_expand_output_to_stdout_by_default(self, capsys):
        with patch("sys.argv", ["cobol-parser", "expand", _SIMPLE]):
            main()
        out = capsys.readouterr().out
        assert json.loads(out)  # valid JSON on stdout


# ---------------------------------------------------------------------------
# batch --output flag
# ---------------------------------------------------------------------------


class TestBatchOutput:
    def test_batch_output_to_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "batch.json")
        with patch(
            "sys.argv",
            ["cobol-parser", "batch", _SIMPLE, _DYNAMIC, "-o", out_file],
        ):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, list)
        assert len(data) == 2
        # nothing on stdout
        assert capsys.readouterr().out == ""

    def test_batch_glob_output_to_file(self, tmp_path, capsys):
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        (tmp_path / "x.cbl").write_text(cobol)
        out_file = str(tmp_path / "batch_glob.json")
        pattern = str(tmp_path / "*.cbl")
        with patch(
            "sys.argv",
            ["cobol-parser", "batch", "--glob", pattern, "-o", out_file],
        ):
            main()
        assert Path(out_file).exists()
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, list)
        assert len(data) == 1


# ---------------------------------------------------------------------------
# batch --glob recursive pattern
# ---------------------------------------------------------------------------


class TestBatchGlobRecursive:
    def test_recursive_glob(self, tmp_path, capsys):
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.cbl").write_text(cobol)
        (sub / "nested.cbl").write_text(cobol)
        pattern = str(tmp_path / "**" / "*.cbl")
        with patch("sys.argv", ["cobol-parser", "batch", "--glob", pattern]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2  # root.cbl + sub/nested.cbl

    def test_multiple_glob_patterns(self, tmp_path, capsys):
        cobol = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        (tmp_path / "a.cbl").write_text(cobol)
        (tmp_path / "b.cob").write_text(cobol)
        pat_cbl = str(tmp_path / "*.cbl")
        pat_cob = str(tmp_path / "*.cob")
        with patch(
            "sys.argv",
            ["cobol-parser", "batch", "--glob", pat_cbl, "--glob", pat_cob],
        ):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2


# ---------------------------------------------------------------------------
# New subcommands via main: stdout is silent when --output is used
# ---------------------------------------------------------------------------


class TestNewSubcommandsOutputSilent:
    @pytest.mark.parametrize(
        "subcmd",
        ["io-sequence", "move-type-check", "linkage-check", "language-env", "ims-dli"],
    )
    def test_stdout_silent_when_output_flag_used(self, subcmd, tmp_path, capsys):
        out_file = str(tmp_path / f"{subcmd}.json")
        with patch("sys.argv", ["cobol-parser", subcmd, _SIMPLE, "-o", out_file]):
            main()
        assert capsys.readouterr().out == ""
        assert Path(out_file).exists()
        json.loads(Path(out_file).read_text())  # valid JSON written


# ---------------------------------------------------------------------------
# Positive-case tests: subcommands with sources that trigger findings
# ---------------------------------------------------------------------------

# Minimal COBOL that triggers an io-sequence violation (READ before OPEN)
_IO_VIOLATION_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOBAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MY-FILE ASSIGN TO 'FILE.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD MY-FILE.
       01 MY-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           READ MY-FILE INTO MY-REC
               AT END MOVE 'Y' TO WS-EOF
           END-READ
           STOP RUN.
"""

# Minimal COBOL with an illegal MOVE (NUMERIC → ALPHABETIC)
_MOVE_VIOLATION_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEBAD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM    PIC 9(5).
       01 WS-ALPHA  PIC A(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-NUM TO WS-ALPHA
           STOP RUN.
"""

# Minimal COBOL with a LINKAGE SECTION and ENTRY
_LINKAGE_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LNKPROG.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-PARAM-A PIC X(10).
       01 LK-PARAM-B PIC 9(5).
       PROCEDURE DIVISION USING LK-PARAM-A LK-PARAM-B.
       MAIN-LOGIC.
           STOP RUN.
"""


class TestPositiveCaseFindings:
    def test_io_sequence_detects_read_before_open(self, tmp_path, capsys):
        src = tmp_path / "bad_io.cbl"
        src.write_text(_IO_VIOLATION_SRC)
        args = _make_args(str(src))
        _cmd_io_sequence(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["has_violations"] is True
        assert data["violation_count"] > 0
        kinds = [v["kind"] for v in data["violations"]]
        assert any("BEFORE_OPEN" in k or "LEFT_OPEN" in k for k in kinds)

    def test_move_type_check_detects_illegal_move(self, tmp_path, capsys):
        src = tmp_path / "bad_move.cbl"
        src.write_text(_MOVE_VIOLATION_SRC)
        args = _make_args(str(src))
        _cmd_move_type_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        # The illegal NUMERIC→ALPHABETIC move should be an ERROR
        assert data["error_count"] > 0
        assert any(
            v["kind"] == "ERROR"
            and "WS-NUM" in v["source"]
            and "WS-ALPHA" in v["target"]
            for v in data["violations"]
        )

    def test_linkage_check_reports_linkage_items(self, tmp_path, capsys):
        src = tmp_path / "linkage.cbl"
        src.write_text(_LINKAGE_SRC)
        args = _make_args(str(src))
        _cmd_linkage_check(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        # Should list the two 01-level LINKAGE items
        assert "LK-PARAM-A" in data["linkage_items"] or len(data["linkage_items"]) > 0

    def test_language_env_detects_intrinsic_functions(self, capsys):
        # ibm_extensions.cbl uses FUNCTION LENGTH, UPPER-CASE, etc.
        args = _make_args(_IBM)
        _cmd_language_env(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["uses_intrinsic_functions"] is True
        assert len(data["unique_functions"]) > 0
        # LENGTH is used in ibm_extensions.cbl
        assert "LENGTH" in data["unique_functions"]

    def test_ims_dli_detects_dli_calls(self, capsys):
        # ims_banking_accounts.cbl has CBLTDLI calls
        ims_file = str(SAMPLES / "ims_banking_accounts.cbl")
        args = _make_args(ims_file)
        _cmd_ims_dli(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["dli_call_count"] > 0
        assert len(data["all_segments"]) > 0
        # Each call should have interface, function_code fields
        for call in data["dli_calls"]:
            assert "interface" in call
            assert "segment_names" in call

    def test_ims_dli_call_structure(self, capsys):
        ims_file = str(SAMPLES / "ims_banking_accounts.cbl")
        args = _make_args(ims_file)
        _cmd_ims_dli(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        required_fields = {
            "interface",
            "function_code",
            "function_code_var",
            "pcb_name",
            "io_area_name",
            "ssa_names",
            "segment_names",
            "primary_segment",
            "location",
        }
        for call in data["dli_calls"]:
            assert required_fields.issubset(call.keys())


# ---------------------------------------------------------------------------
# --version via _build_parser() directly
# ---------------------------------------------------------------------------


class TestVersionViaParser:
    def test_version_action_on_parser(self, capsys):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert __version__ in output
