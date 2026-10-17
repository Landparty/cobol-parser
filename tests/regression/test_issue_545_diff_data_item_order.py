"""diff reports a reorder of a group's subordinate items (#545).

``ProgramDiffer`` compared each data item's own attributes but never their
order, so swapping two fields of a record -- which moves every byte offset
after them -- diffed as "No structural changes".
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer


def _program(*record: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. RO.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 CUST-REC.",
        *record,
        "PROCEDURE DIVISION.",
        "MAIN.",
        "    STOP RUN.",
    )
    return "".join(f"       {line}\n" for line in lines)


ID = "   05 CUST-ID    PIC 9(6)."
NAME = "   05 CUST-NAME  PIC X(20)."
BAL = "   05 CUST-BAL   PIC S9(7)V99 COMP-3."


def _diff(old: str, new: str):
    return ProgramDiffer().diff(parse_cobol(old).ast, parse_cobol(new).ast)


def test_swapped_fields_are_reported_with_their_offsets():
    report = _diff(_program(ID, NAME, BAL), _program(NAME, ID, BAL))
    moved = [c for c in report.changes if c.kind == "data-item-moved"]
    assert len(moved) == 1
    (change,) = moved
    assert change.symbol == "CUST-REC.CUST-NAME"
    assert change.old == "position 2, offset 6"
    assert change.new == "position 1, offset 0"
    assert "byte offset 6 -> 0" in change.detail
    assert change.sign == "~"
    assert "No structural changes" not in report.to_text()


def test_an_inserted_field_moves_nothing():
    report = _diff(
        _program(ID, NAME, BAL), _program("   05 CUST-NEW PIC X.", ID, NAME, BAL)
    )
    assert [c.kind for c in report.changes] == ["data-item-added"]


def test_a_removed_field_moves_nothing():
    report = _diff(_program(ID, NAME, BAL), _program(ID, BAL))
    assert [c.kind for c in report.changes] == ["data-item-removed"]


def test_a_nested_group_reorder_is_reported_in_its_group():
    old = _program(
        ID, "   05 CUST-ADDR.", "      10 STREET PIC X(10).", "      10 CITY PIC X(5)."
    )
    new = _program(
        ID, "   05 CUST-ADDR.", "      10 CITY PIC X(5).", "      10 STREET PIC X(10)."
    )
    (change,) = _diff(old, new).changes
    assert change.kind == "data-item-moved"
    assert change.symbol == "CUST-REC.CUST-ADDR.CITY"
    assert "in CUST-REC.CUST-ADDR" in change.detail
    assert "byte offset 16 -> 6" in change.detail


def test_reordered_level_88s_are_not_a_move():
    old = _program(
        "   05 CUST-TYPE PIC X.", "      88 T-A VALUE 'A'.", "      88 T-B VALUE 'B'."
    )
    new = _program(
        "   05 CUST-TYPE PIC X.", "      88 T-B VALUE 'B'.", "      88 T-A VALUE 'A'."
    )
    assert _diff(old, new).changes == []
