"""Tests for cobolparser.cli.parse subcommands: analyze, dead-code,
program-flow, and error paths in _read_source / _resolve_path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import (
    _cmd_analyze,
    _cmd_dead_code,
    _cmd_program_flow,
    _read_source,
    _resolve_path,
    main,
)
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SAMPLES = Path(__file__).parents[2] / "samples"

_SIMPLE = str(SAMPLES / "simple_calculation.cbl")
_DYNAMIC = str(SAMPLES / "call_dynamic_programs.cbl")
_SORT = str(SAMPLES / "sort_merge_operations.cbl")


def _make_analyze_args(filepath: str, **kwargs) -> argparse.Namespace:
    defaults = {
        "file": filepath,
        "compact": False,
        "free_form": False,
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "define": [],
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_dead_code_args(filepath: str, **kwargs) -> argparse.Namespace:
    return _make_analyze_args(filepath, **kwargs)


def _make_program_flow_args(filepath: str, **kwargs) -> argparse.Namespace:
    return _make_analyze_args(filepath, **kwargs)


# ---------------------------------------------------------------------------
# _read_source error paths
# ---------------------------------------------------------------------------


class TestReadSource:
    def test_file_not_found_exits(self, tmp_path):
        missing = str(tmp_path / "nope.cbl")
        with pytest.raises(SystemExit):
            _read_source(missing)

    def test_unknown_encoding_exits(self, tmp_path):
        # Non-UTF-8 bytes are decoded since #522 (detected, as a copybook's
        # are); naming an encoding that does not exist still exits.
        bad = tmp_path / "bad.cbl"
        bad.write_bytes(b"\xff\xfe binary garbage \x00\x01")
        with pytest.raises(SystemExit):
            _read_source(str(bad), "no-such-codec")

    def test_os_error_exits(self, tmp_path):
        """OSError (e.g. permission denied) causes SystemExit."""
        p = tmp_path / "perm.cbl"
        p.write_text("IDENTIFICATION DIVISION.")
        with patch("builtins.open", side_effect=OSError("permission denied")):
            with pytest.raises(SystemExit):
                _read_source(str(p))


# ---------------------------------------------------------------------------
# _resolve_path error paths
# ---------------------------------------------------------------------------


class TestResolvePath:
    @pytest.fixture
    def simple_ast(self):
        src = Path(_SIMPLE).read_text()
        result = parse_cobol(src)
        assert result.ast is not None
        return result.ast

    def test_missing_division_exits(self, simple_ast):
        with pytest.raises(SystemExit):
            _resolve_path(simple_ast, "NONEXISTENT")

    def test_missing_section_exits(self, simple_ast):
        # procedure division exists but NOPE paragraph/section doesn't
        with pytest.raises(SystemExit):
            _resolve_path(simple_ast, "procedure.NOPE-PARA")

    def test_missing_statement_type_exits(self, simple_ast):
        # MAIN-LOGIC paragraph exists but FOOSTATEMENT type does not
        with pytest.raises(SystemExit):
            _resolve_path(simple_ast, "procedure.MAIN-LOGIC.FOOSTATEMENT")

    def test_path_too_deep_exits(self, simple_ast):
        with pytest.raises(SystemExit):
            _resolve_path(simple_ast, "a.b.c.d")

    def test_empty_path_exits(self, simple_ast):
        with pytest.raises(SystemExit):
            _resolve_path(simple_ast, "")

    def test_division_resolved(self, simple_ast):
        result = _resolve_path(simple_ast, "procedure")
        assert isinstance(result, dict)

    def test_paragraph_resolved(self, simple_ast):
        result = _resolve_path(simple_ast, "procedure.MAIN-LOGIC")
        assert isinstance(result, dict)

    def test_statement_type_resolved(self, simple_ast):
        result = _resolve_path(simple_ast, "procedure.MAIN-LOGIC.display")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _cmd_analyze
# ---------------------------------------------------------------------------


class TestCmdAnalyze:
    def test_analyze_outputs_calls_json(self, capsys):
        args = _make_analyze_args(_DYNAMIC)
        _cmd_analyze(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "calls" in data
        assert isinstance(data["calls"], list)

    def test_analyze_compact(self, capsys):
        args = _make_analyze_args(_DYNAMIC, compact=True)
        _cmd_analyze(args)
        out = capsys.readouterr().out.strip()
        # compact JSON has no newlines in middle
        assert "\n" not in out
        data = json.loads(out)
        assert "calls" in data

    def test_analyze_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")  # invalid chars force ast=None in fail-fast
        args = _make_analyze_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_analyze(args)

    def test_analyze_static_call_not_dynamic(self, capsys):
        args = _make_analyze_args(_SIMPLE)
        # simple_calculation.cbl has no CALL statements
        _cmd_analyze(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["calls"] == []


# ---------------------------------------------------------------------------
# _cmd_dead_code
# ---------------------------------------------------------------------------


class TestCmdDeadCode:
    def test_dead_code_outputs_dict(self, capsys):
        args = _make_dead_code_args(_SIMPLE)
        _cmd_dead_code(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)

    def test_dead_code_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_dead_code_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_dead_code(args)

    def test_dead_code_compact(self, capsys):
        args = _make_dead_code_args(_SIMPLE, compact=True)
        _cmd_dead_code(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)  # valid JSON


# ---------------------------------------------------------------------------
# _cmd_program_flow
# ---------------------------------------------------------------------------


class TestCmdProgramFlow:
    def test_program_flow_outputs_dict(self, capsys):
        args = _make_program_flow_args(_SIMPLE)
        _cmd_program_flow(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)

    def test_program_flow_parse_failure_exits(self, tmp_path):
        bad = tmp_path / "bad.cbl"
        bad.write_text("@@@@ NOT COBOL")
        args = _make_program_flow_args(str(bad), error_recovery="fail-fast")
        with pytest.raises(SystemExit):
            _cmd_program_flow(args)

    def test_program_flow_compact(self, capsys):
        args = _make_program_flow_args(_SIMPLE, compact=True)
        _cmd_program_flow(args)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        json.loads(out)


# ---------------------------------------------------------------------------
# main() legacy syntax and no-subcommand branch
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    def test_legacy_syntax_prepends_parse(self, tmp_path, capsys):
        """Legacy invocation: cobol-parser <file> runs as 'parse <file>'."""
        with patch("sys.argv", ["cobol-parser", _SIMPLE]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "node_type" in data or "program_name" in data

    def test_no_args_prints_help_and_exits(self, capsys):
        with patch("sys.argv", ["cobol-parser"]):
            with pytest.raises(SystemExit):
                main()
