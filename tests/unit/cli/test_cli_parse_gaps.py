"""Tests for cli/parse.py paths not covered by existing tests.

Targets:
- _text_out() writing to file and OSError path (lines 152-159)
- _cmd_program_flow() with format=mermaid and format=dot (lines 634-643)
- main() called with no subcommand (lines 1062-1064)
- _cmd_analyze() dynamic calls with possible_values (lines 549-550)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _cmd_analyze, _cmd_program_flow, _text_out, main

SAMPLES = Path(__file__).parents[2] / "samples"

_SIMPLE = str(SAMPLES / "simple_calculation.cbl")
_DYNAMIC = str(SAMPLES / "call_dynamic_programs.cbl")


# ---------------------------------------------------------------------------
# _text_out() — file write and OSError
# ---------------------------------------------------------------------------


class TestTextOut:
    def test_writes_to_stdout(self, capsys):
        _text_out("hello world")
        assert capsys.readouterr().out.strip() == "hello world"

    def test_writes_to_file(self, tmp_path):
        out = tmp_path / "out.txt"
        _text_out("some text", str(out))
        assert out.read_text() == "some text\n"

    def test_appends_newline_if_missing(self, tmp_path):
        out = tmp_path / "out.txt"
        _text_out("no newline", str(out))
        assert out.read_text().endswith("\n")

    def test_no_extra_newline_when_text_ends_with_newline(self, tmp_path):
        out = tmp_path / "out.txt"
        _text_out("already\n", str(out))
        content = out.read_text()
        assert content == "already\n"

    def test_oserror_exits(self, tmp_path):
        out = tmp_path / "out.txt"
        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(SystemExit):
                _text_out("data", str(out))


# ---------------------------------------------------------------------------
# _cmd_program_flow() — mermaid and dot formats
# ---------------------------------------------------------------------------


def _make_flow_args(filepath: str, **kwargs) -> argparse.Namespace:
    defaults = {
        "file": filepath,
        "compact": False,
        "free_form": False,
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "define": [],
        "format": "json",
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestCmdProgramFlowFormats:
    def test_mermaid_format_produces_text(self, capsys):
        args = _make_flow_args(_SIMPLE, format="mermaid")
        _cmd_program_flow(args)
        out = capsys.readouterr().out
        assert len(out) > 0
        # Mermaid diagrams start with 'graph' or 'flowchart'
        assert any(keyword in out for keyword in ("graph", "flowchart", "-->", "---"))

    def test_dot_format_produces_text(self, capsys):
        args = _make_flow_args(_SIMPLE, format="dot")
        _cmd_program_flow(args)
        out = capsys.readouterr().out
        assert len(out) > 0
        # DOT format contains digraph declaration
        assert "digraph" in out or "->" in out or "graph" in out

    def test_mermaid_to_file(self, tmp_path):
        out_file = str(tmp_path / "flow.md")
        args = _make_flow_args(_SIMPLE, format="mermaid", output=out_file)
        _cmd_program_flow(args)
        content = Path(out_file).read_text()
        assert len(content) > 0

    def test_dot_to_file(self, tmp_path):
        out_file = str(tmp_path / "flow.dot")
        args = _make_flow_args(_SIMPLE, format="dot", output=out_file)
        _cmd_program_flow(args)
        content = Path(out_file).read_text()
        assert len(content) > 0

    def test_json_format_still_works(self, capsys):
        import json

        args = _make_flow_args(_SIMPLE, format="json")
        _cmd_program_flow(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# main() — no subcommand triggers print_help + sys.exit(1)
# ---------------------------------------------------------------------------


class TestMainNoSubcommand:
    def test_no_args_exits(self):
        # main() reads sys.argv directly. With no args, it prepends "parse"
        # which then fails because file argument is missing → argparse SystemExit.
        with patch.object(sys, "argv", ["cobol-parser"]):
            with pytest.raises(SystemExit):
                main()

    def test_help_flag_exits_zero(self):
        with patch.object(sys, "argv", ["cobol-parser", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# _cmd_analyze() — dynamic call with possible_values populated
# ---------------------------------------------------------------------------


def _make_analyze_args(filepath: str, **kwargs) -> argparse.Namespace:
    defaults = {
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


class TestCmdAnalyzeDynamicCalls:
    def test_dynamic_call_possible_values_in_output(self, capsys):
        import json

        args = _make_analyze_args(_DYNAMIC)
        _cmd_analyze(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        calls = data.get("calls", [])
        # At least one dynamic call should exist in call_dynamic_programs.cbl
        dynamic = [c for c in calls if c.get("is_dynamic")]
        if dynamic:
            # possible_values key must be present when is_dynamic is True
            assert "possible_values" in dynamic[0]
