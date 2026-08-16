"""Tests for the `complexity` and `health` CLI subcommands.

Covers:
- Both subcommands are registered in the argparse parser (--help works)
- Both are in the legacy-syntax `_SUBCOMMANDS` set (regression: without this,
  `main()`'s backward-compatibility shim mistakes the subcommand name itself
  for a filename and prepends "parse", e.g. turning
  `cobol-parser health foo.cbl` into `cobol-parser parse health foo.cbl`)
- Both run end to end via `main()` and produce the expected JSON shape
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main

SAMPLES = Path(__file__).parents[2] / "samples"
_SIMPLE = str(SAMPLES / "simple_calculation.cbl")


@pytest.mark.parametrize("subcmd", ["complexity", "health"])
class TestSubcommandsRegistered:
    def test_subcommand_in_parser(self, subcmd: str) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([subcmd, "--help"])

    def test_subcommand_in_legacy_set(self, subcmd: str) -> None:
        assert subcmd in _SUBCOMMANDS

    def test_subcommand_via_main(self, subcmd: str, capsys) -> None:
        with patch("sys.argv", ["cobol-parser", subcmd, _SIMPLE]):
            main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)
        assert data["source_file"] == _SIMPLE


class TestComplexitySubcommand:
    def test_shape(self, capsys) -> None:
        with patch("sys.argv", ["cobol-parser", "complexity", _SIMPLE, "--compact"]):
            main()
        data = json.loads(capsys.readouterr().out)
        assert "procedures" in data
        assert "summary" in data
        assert "thresholds" in data


class TestHealthSubcommand:
    def test_shape(self, capsys) -> None:
        with patch("sys.argv", ["cobol-parser", "health", _SIMPLE, "--compact"]):
            main()
        data = json.loads(capsys.readouterr().out)
        assert "score" in data
        assert "grade" in data
        assert "components" in data
        assert "top_offenders" in data
        assert "complexity_summary" in data
        assert "redundancy_summary" in data
