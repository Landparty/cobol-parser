"""DISPLAY of a subscripted item with a reference modification (2026-11-11, A13).

``DISPLAY X(I)(1:N)`` lost its ``(1:N)``: the subscript was folded into
the item, but the second parenthesized group was left behind, and the bare
LEFT_PAREN then ended the item list, so every item after it was lost too.
MOVE kept the reference modification all along.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol


def _display_items(statements: list[str]) -> list[list[str]]:
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. CSDIOMQI.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  T.",
        "           05  X  PIC X(10) OCCURS 5.",
        "       01  I  PIC 9.",
        "       01  N  PIC 9.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *[f"           {s}" for s in statements],
        "           GOBACK.",
    ]
    result = parse_cobol("\n".join(lines) + "\n")
    assert result.errors == []
    return [s.display_items for s in result.ast.find_all_by_type("DisplayStatement")]


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("DISPLAY X(I)(1:N)", ["X(I)(1:N)"]),
        ("DISPLAY X(I) (1:N) 'TAIL'", ["X(I)(1:N)", '"TAIL"']),
        ("DISPLAY X(1:N) N", ["X(1:N)", "N"]),
        ("DISPLAY X(I)(N:) I", ["X(I)(N:)", "I"]),
        ("DISPLAY X(I + 1)(1:N)", ["X(I + 1)(1:N)"]),
    ],
)
def test_reference_modification_is_kept(statement: str, expected: list[str]) -> None:
    assert _display_items([statement]) == [expected]


def test_plain_subscript_unchanged() -> None:
    assert _display_items(["DISPLAY X(I) N"]) == [["X(I)", "N"]]
