"""One missing copybook no longer stops the analysis.

On the open-source corpus, 82 of 1,804 programs failed every single-file
analyzer with exit 1 and no output because one COPY member was not on the
``--copybook-path`` (21 CardDemo programs only for want of DFHAID/DFHBMSCA),
while the same command with no path at all succeeded. scan expanded nothing
for such a file, and codebase-graph listed DFHAID as unresolved 42 times.
lint already finished what it could; every subcommand now does the same,
with ``--strict-copybooks`` to fail instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.batch import parse_files_with_copybooks
from cobolparser.cli.parse import main
from cobolparser.scan import ScanOptions, scan_one

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY PRESENT.
       COPY ABSENT.
       COPY DFHAID.
       01  OUT-X PIC X(10).
       PROCEDURE DIVISION.
           MOVE PRESENT-X TO OUT-X.
           IF EIBAID = DFHENTER
               DISPLAY OUT-X
           END-IF.
           GOBACK.
"""

PRESENT = "       01  PRESENT-X PIC X(10).\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "MIXED.cbl").write_text(PROGRAM)
    (tmp_path / "cpy").mkdir()
    (tmp_path / "cpy" / "PRESENT.cpy").write_text(PRESENT)
    return tmp_path


def _run(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", "--no-config", *argv])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize("command", ["xref", "data-items", "parse"])
def test_analyzer_skips_only_the_missing_member(
    tree: Path, monkeypatch, capsys, command: str
) -> None:
    code, out, err = _run(
        monkeypatch,
        capsys,
        command,
        str(tree / "MIXED.cbl"),
        "--copybook-path",
        str(tree / "cpy"),
    )
    assert code == 0, err
    assert "copybook(s) not expanded (ABSENT)" in err
    assert "--strict-copybooks" in err
    assert "PRESENT-X" in out


def test_xref_resolves_present_and_stand_in_members(
    tree: Path, monkeypatch, capsys
) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        "xref",
        str(tree / "MIXED.cbl"),
        "--copybook-path",
        str(tree / "cpy"),
    )
    assert code == 0
    undefined = json.dumps(json.loads(out).get("undefined", []))
    assert "PRESENT-X" not in undefined
    assert "DFHENTER" not in undefined


def test_strict_copybooks_restores_exit_1(tree: Path, monkeypatch, capsys) -> None:
    code, out, err = _run(
        monkeypatch,
        capsys,
        "dead-code",
        str(tree / "MIXED.cbl"),
        "--copybook-path",
        str(tree / "cpy"),
        "--strict-copybooks",
    )
    assert code == 1
    assert out == ""
    # Strict means no stand-ins either: DFHAID is the first member missing.
    assert "Copybook expansion failed" in err and "not found" in err


def test_scan_keeps_every_other_member(tree: Path) -> None:
    scan = scan_one(
        str(tree / "MIXED.cbl"),
        ScanOptions(
            analyzers=("unused-variables",), copybook_paths=(str(tree / "cpy"),)
        ),
    )
    assert scan.error is None
    assert scan.copybook_error is None
    assert scan.unexpanded_copybooks == ["ABSENT"]
    unused = scan.units[0].reports["unused-variables"]["unused_variables"]
    # DFHAID expanded from the stand-in; PRESENT-X is declared and used.
    assert any(item["name"] == "DFHCLEAR" for item in unused)
    assert not any(item["name"] == "PRESENT-X" for item in unused)


def test_batch_skip_missing_copybooks(tree: Path) -> None:
    [strict] = parse_files_with_copybooks(
        [tree / "MIXED.cbl"], copybook_paths=[str(tree / "cpy")]
    )
    assert strict.copybook_error is not None
    [lenient] = parse_files_with_copybooks(
        [tree / "MIXED.cbl"],
        copybook_paths=[str(tree / "cpy")],
        skip_missing_copybooks=True,
    )
    assert lenient.copybook_error is None
    assert lenient.result is not None
    assert any("COPY ABSENT was not expanded" in w for w in lenient.result.warnings)
    assert not any("DFHAID" in w for w in lenient.result.warnings)


def test_codebase_graph_does_not_report_dfhaid(tree: Path) -> None:
    graph = CodebaseGraphBuilder(copybook_paths=[str(tree / "cpy")]).build(
        [str(tree / "MIXED.cbl")]
    )
    notes = "\n".join(graph.unresolved)
    assert "ABSENT" in notes
    assert "DFHAID" not in notes
