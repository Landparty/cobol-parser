"""Regression tests for #325 (owner decision: option (a), exit non-zero when
*any* file fails, like ``batch``): ``scan``, ``codebase-graph`` and
``copybook-impact`` exited 0 even when every input failed, and
``codebase-graph ./typo-dir/`` graphed the missing path as a phantom
``parse_failed`` program."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

GOOD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOOD.
       PROCEDURE DIVISION.
           GOBACK.
"""


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    with patch.object(sys, "argv", ["cobol-parser", "--no-config", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_scan_of_nothing_but_failures_exits_2(tmp_path: Path, capsys) -> None:
    code, out, err = _run(
        ["scan", str(tmp_path / "nope.cbl"), "--workers", "1", "--compact"], capsys
    )
    assert code == 2
    assert json.loads(out)["summary"]["failed_file_count"] == 1
    assert "1 of 1 file(s) could not be scanned" in err


def test_scan_with_one_failure_exits_2(tmp_path: Path, capsys) -> None:
    good = tmp_path / "GOOD.cbl"
    good.write_text(GOOD)
    code, _, _ = _run(
        ["scan", str(good), str(tmp_path / "nope.cbl"), "--workers", "1"], capsys
    )
    assert code == 2


def test_clean_scan_exits_0(tmp_path: Path, capsys) -> None:
    good = tmp_path / "GOOD.cbl"
    good.write_text(GOOD)
    code, _, err = _run(["scan", str(good), "--workers", "1"], capsys)
    assert code == 0
    assert "could not be scanned" not in err


@pytest.mark.parametrize("fmt", ["json", "dot", "mermaid"])
def test_codebase_graph_missing_path_is_not_a_program(
    tmp_path: Path, capsys, fmt: str
) -> None:
    typo = tmp_path / "typo-dir"
    code, out, err = _run(
        ["codebase-graph", str(typo), "--format", fmt, "--workers", "1"], capsys
    )
    assert code == 2
    assert f"no such file or directory: {typo}" in err
    assert "TYPO-DIR" not in out


def test_clean_codebase_graph_exits_0(tmp_path: Path, capsys) -> None:
    (tmp_path / "GOOD.cbl").write_text(GOOD)
    code, out, _ = _run(["codebase-graph", str(tmp_path), "--workers", "1"], capsys)
    assert code == 0
    assert json.loads(out)["errors"] == []


def test_copybook_impact_with_a_missing_file_exits_2(tmp_path: Path, capsys) -> None:
    code, out, _ = _run(
        ["copybook-impact", "X", str(tmp_path / "nope.cbl"), "--workers", "1"], capsys
    )
    assert code == 2
    assert json.loads(out)["member"] == "X"
