"""field-impact and widen-check say when copybooks were not expanded.

On GenApp, ``field-impact CA-CUSTOMER-NUM`` reported 2 programs with
``problems: []`` while 21 use the field: the other 19 reach it through
``COPY LGCMAREA``, which did not resolve, and nothing said so. The MCP
``impact_of_change`` tool already carried an ``unresolved-copybook`` caveat
for the same question; the CLI now does too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main
from cobolparser.scan import FileScan

DECLARES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OWNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CA-AREA.
           05 CA-NUM PIC X(10).
       01  OUT-NUM PIC X(10).
       PROCEDURE DIVISION.
           MOVE CA-NUM TO OUT-NUM.
           GOBACK.
"""

COPIES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USER1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CAREA.
       01  OTHER-NUM PIC X(10).
       PROCEDURE DIVISION.
           MOVE CA-NUM TO OTHER-NUM.
           GOBACK.
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "owner.cbl").write_text(DECLARES)
    (tmp_path / "user1.cbl").write_text(COPIES)
    (tmp_path / "cpy").mkdir()
    return tmp_path


def _run(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    monkeypatch.setattr(
        sys, "argv", ["cobol-parser", "--no-config", *argv, "--workers", "1"]
    )
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_field_impact_names_the_files_with_unexpanded_copybooks(
    tree: Path, monkeypatch, capsys
) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        "field-impact",
        "CA-NUM",
        str(tree),
        "--copybook-path",
        str(tree / "cpy"),
    )
    assert code == 0
    caveats = json.loads(out)["caveats"]
    assert caveats[0].startswith(
        "copybooks not expanded in 1 program file(s): user1.cbl"
    )
    assert "members: CAREA" in caveats[0]


def test_widen_check_carries_the_same_caveat(tree: Path, monkeypatch, capsys) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        "widen-check",
        "CA-NUM",
        str(tree),
        "--to",
        "X(12)",
        "--copybook-path",
        str(tree / "cpy"),
    )
    assert code == 0
    assert json.loads(out)["caveats"][0].startswith("copybooks not expanded in 1")


def test_no_caveat_when_every_copybook_expands(tree: Path, monkeypatch, capsys) -> None:
    (tree / "cpy" / "CAREA.cpy").write_text(
        "       01  CA-AREA.\n           05 CA-NUM PIC X(10).\n"
    )
    code, out, _ = _run(
        monkeypatch,
        capsys,
        "field-impact",
        "CA-NUM",
        str(tree),
        "--copybook-path",
        str(tree / "cpy"),
    )
    assert code == 0
    report = json.loads(out)
    assert not any(c.startswith("copybooks not expanded") for c in report["caveats"])
    assert set(report["programs"]) == {"OWNER", "USER1"}


def test_a_field_found_nowhere_points_at_the_unexpanded_copybooks(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    (tmp_path / "user1.cbl").write_text(COPIES)
    code, _, err = _run(monkeypatch, capsys, "field-impact", "CA-NUM", str(tmp_path))
    assert code == 1
    assert "no such field in any report; it may be declared in a copybook" in err
    assert "user1.cbl" in err


def test_file_scan_round_trips_the_unexpanded_members() -> None:
    scan = FileScan(path="p.cbl", unexpanded_copybooks=["A", "B"])
    assert FileScan.from_dict(scan.to_dict()).unexpanded_copybooks == ["A", "B"]
    assert "unexpanded_copybooks" not in FileScan(path="p.cbl").to_dict()
