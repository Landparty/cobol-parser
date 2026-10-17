"""An exhaustive IF / EVALUATE whose every arm terminates ends its paragraph (#586).

Both ``DeadCodeAnalyzer`` and ``ProgramFlowAnalyzer`` counted only a
top-level statement as a terminator, so a paragraph ending in
``IF c GO TO A ELSE GO TO B END-IF`` (or an EVALUATE ... WHEN OTHER whose
every arm stops) was treated as falling through, and the paragraph after it
was reported live. A branch that is not exhaustive (no ELSE, no WHEN OTHER)
or has one arm that does not terminate still falls through.
"""

from __future__ import annotations

import pytest

from cobolparser import DeadCodeAnalyzer, ProgramFlowAnalyzer, parse_cobol


def _program(*body: str) -> str:
    head = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PF3.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-X PIC 9 VALUE 0.",
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
    )
    tail = (
        "ORPHAN-PARA.",
        "    DISPLAY 'NEVER RUNS'.",
        "PARA-A.",
        "    DISPLAY 'A'",
        "    STOP RUN.",
        "PARA-B.",
        "    DISPLAY 'B'",
        "    STOP RUN.",
    )
    return "".join(f"       {line}\n" for line in (*head, *body, *tail))


TERMINATING = {
    "go-to-dispatch": (
        "    IF WS-X = 1",
        "       GO TO PARA-A",
        "    ELSE",
        "       GO TO PARA-B",
        "    END-IF.",
    ),
    "goback-both-arms": (
        "    IF WS-X = 1",
        "       DISPLAY 'ONE'",
        "       GOBACK",
        "    ELSE",
        "       GOBACK",
        "    END-IF.",
    ),
    "evaluate-when-other": (
        "    EVALUATE WS-X",
        "       WHEN 1 STOP RUN",
        "       WHEN OTHER GOBACK",
        "    END-EVALUATE.",
    ),
    "stacked-when": (
        "    EVALUATE WS-X",
        "       WHEN 1",
        "       WHEN 2 GO TO PARA-A",
        "       WHEN OTHER GO TO PARA-B",
        "    END-EVALUATE.",
    ),
    "nested": (
        "    IF WS-X = 1",
        "       IF WS-X = 2 GOBACK ELSE STOP RUN END-IF",
        "    ELSE",
        "       EXIT PROGRAM",
        "    END-IF.",
    ),
}

FALLING_THROUGH = {
    "if-without-else": (
        "    IF WS-X = 1",
        "       GO TO PARA-A",
        "    END-IF.",
    ),
    "one-arm-continues": (
        "    IF WS-X = 1",
        "       GO TO PARA-A",
        "    ELSE",
        "       DISPLAY 'B'",
        "    END-IF.",
    ),
    "evaluate-without-other": (
        "    EVALUATE WS-X",
        "       WHEN 1 GO TO PARA-A",
        "       WHEN 2 GO TO PARA-B",
        "    END-EVALUATE.",
    ),
    "evaluate-other-continues": (
        "    EVALUATE WS-X",
        "       WHEN 1 GO TO PARA-A",
        "       WHEN OTHER CONTINUE",
        "    END-EVALUATE.",
    ),
}


def _ast(body: tuple[str, ...]):
    result = parse_cobol(_program(*body))
    assert result.success, result.errors
    return result.ast


def _fall_through(ast) -> set[tuple[str, str]]:
    report = ProgramFlowAnalyzer().analyze(ast)
    return {
        (e.source, e.target) for e in report.edges if e.edge_type.name == "FALL_THROUGH"
    }


def _dead(ast) -> set[str]:
    return {item.name for item in DeadCodeAnalyzer().analyze(ast).dead_items}


@pytest.mark.parametrize("body", TERMINATING.values(), ids=TERMINATING.keys())
def test_exhaustive_terminating_branch_ends_the_paragraph(body):
    ast = _ast(body)
    assert "ORPHAN-PARA" in _dead(ast)
    assert ("MAIN-PARA", "ORPHAN-PARA") not in _fall_through(ast)
    assert "ORPHAN-PARA" in ProgramFlowAnalyzer().analyze(ast).unreachable_nodes


@pytest.mark.parametrize("body", FALLING_THROUGH.values(), ids=FALLING_THROUGH.keys())
def test_non_exhaustive_branch_still_falls_through(body):
    ast = _ast(body)
    assert "ORPHAN-PARA" not in _dead(ast)
    assert ("MAIN-PARA", "ORPHAN-PARA") in _fall_through(ast)
    assert "ORPHAN-PARA" not in ProgramFlowAnalyzer().analyze(ast).unreachable_nodes
