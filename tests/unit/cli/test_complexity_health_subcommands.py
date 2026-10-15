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


class TestHealthWithParseErrors:
    """Issue #397: a file that mostly failed to parse graded "A" (score 0.0,
    exit 0) with nothing in its JSON to say so. The grade is now withheld
    and the JSON carries the error count and a caveat."""

    JUNK = "THIS IS NOT COBOL AT ALL\nfoo bar baz.\n"

    @pytest.fixture
    def junk(self, tmp_path: Path) -> str:
        path = tmp_path / "junk.cbl"
        path.write_text(self.JUNK, encoding="utf-8")
        return str(path)

    def _run(self, path: str, capsys) -> dict:
        with patch("sys.argv", ["cobol-parser", "health", path, "--compact"]):
            main()
        return json.loads(capsys.readouterr().out)

    def test_grade_is_withheld(self, junk: str, capsys) -> None:
        data = self._run(junk, capsys)
        assert data["grade"] is None
        assert data["parse_error_count"] >= 1
        assert any("parsed with" in c for c in data["caveats"])

    def test_score_is_still_reported(self, junk: str, capsys) -> None:
        # Option (a) of #397: the number stays, labelled; no hard exit.
        data = self._run(junk, capsys)
        assert isinstance(data["score"], float)

    def test_clean_program_keeps_its_grade(self, capsys) -> None:
        data = self._run(_SIMPLE, capsys)
        assert data["grade"] in {"A", "B", "C", "D", "F"}
        assert data["parse_error_count"] == 0
        assert data["caveats"] == []
