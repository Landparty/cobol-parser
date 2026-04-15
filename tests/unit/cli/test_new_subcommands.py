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
        assert "1.0.0" in output


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
        tokens = json.loads(Path(out_file).read_text())
        assert isinstance(tokens, list)
        assert len(tokens) > 0

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
