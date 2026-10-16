"""Regression: a sentence-ending period in an unnamed paragraph (#503).

Statements before the first paragraph header -- at the top of the PROCEDURE
DIVISION, or at the start of a SECTION -- are dispatched one at a time from
``ProcedureDivisionParser.parse_division``'s top loop. The EXEC SQL/CICS,
EVALUATE and CALL parsers leave the period after their scope terminator in
the stream, and so does a doubled period (``DISPLAY 'A'..``). The top loop
took that ``.`` for a paragraph name: a phantom paragraph named ``.`` held
the rest of the code, and the analyzers lost its PERFORMs, terminators and
decisions (dead code went unreported, a PERFORM became a FALL_THROUGH).
"""

from __future__ import annotations

import pytest

from cobolparser import (
    ComplexityAnalyzer,
    DeadCodeAnalyzer,
    ProgramFlowAnalyzer,
    parse_cobol,
)
from cobolparser.analysis.program_flow import FlowEdgeType

# Each first sentence ends in a period the verb's own parser leaves behind.
FIRST_SENTENCES = {
    "exec-sql": [
        "EXEC SQL",
        "  SELECT 1 INTO :WS-N FROM SYSIBM.SYSDUMMY1",
        "END-EXEC.",
    ],
    "exec-cics": ["EXEC CICS ASKTIME NOHANDLE END-EXEC."],
    "evaluate": [
        "EVALUATE WS-X",
        "  WHEN 'A' DISPLAY 'A'",
        "END-EVALUATE.",
    ],
    "call": ["CALL 'SUBPROG' END-CALL."],
    "doubled-period": ["DISPLAY 'A'.."],
}

_HEADER = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. P503.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01  WS-X PIC X.",
    "01  WS-N PIC S9(9) COMP.",
    "PROCEDURE DIVISION.",
]


def _fixed(lines_a: list[tuple[bool, str]]) -> str:
    """Lay out ``(area_a, text)`` lines in fixed format."""
    return "".join(
        ("       " if area_a else "           ") + text + "\n"
        for area_a, text in lines_a
    )


def _section_program(first: list[str]) -> str:
    lines = [(True, h) for h in _HEADER]
    lines.append((True, "MAIN SECTION."))
    lines += [(False, s) for s in first]
    lines += [(False, "PERFORM WORK-SEC."), (False, "STOP RUN.")]
    lines += [(True, "WORK-SEC SECTION."), (False, "DISPLAY 'WORK'.")]
    lines += [(True, "DEAD-SEC SECTION."), (False, "DISPLAY 'DEAD'.")]
    return _fixed(lines)


def _implicit_program(first: list[str]) -> str:
    lines = [(True, h) for h in _HEADER]
    lines += [(False, s) for s in first]
    lines += [
        (False, "PERFORM WORK-PARA."),
        (False, "MOVE 'A' TO WS-X."),
        (False, "GOBACK."),
    ]
    lines += [(True, "WORK-PARA."), (False, "DISPLAY 'WORK'.")]
    lines += [(True, "DEAD-PARA."), (False, "DISPLAY 'DEAD'.")]
    return _fixed(lines)


def _paragraph_names(paragraphs: list) -> list[str]:
    return [p.paragraph_name for p in paragraphs]


@pytest.mark.parametrize("verb", sorted(FIRST_SENTENCES))
def test_section_start_period_is_not_a_paragraph(verb: str) -> None:
    result = parse_cobol(_section_program(FIRST_SENTENCES[verb]))
    assert result.success, result.errors
    pd = result.ast.procedure_division
    main = next(s for s in pd.sections if s.section_name == "MAIN")

    assert _paragraph_names(main.paragraphs) == [""]
    kinds = [type(s).__name__ for s in main.paragraphs[0].statements]
    assert kinds[-2:] == ["PerformStatement", "StopStatement"]

    dead = [d.name for d in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    assert dead == ["DEAD-SEC"]

    edges = ProgramFlowAnalyzer().analyze(result.ast).edges
    main_to_work = [e for e in edges if (e.source, e.target) == ("MAIN", "WORK-SEC")]
    assert [e.edge_type for e in main_to_work] == [FlowEdgeType.PERFORM]


@pytest.mark.parametrize("verb", sorted(FIRST_SENTENCES))
def test_implicit_paragraph_period_is_not_a_paragraph(verb: str) -> None:
    result = parse_cobol(_implicit_program(FIRST_SENTENCES[verb]))
    assert result.success, result.errors
    pd = result.ast.procedure_division

    assert _paragraph_names(pd.paragraphs) == ["", "WORK-PARA", "DEAD-PARA"]
    kinds = [type(s).__name__ for s in pd.paragraphs[0].statements]
    assert kinds[-3:] == ["PerformStatement", "MoveStatement", "GobackStatement"]

    dead = [d.name for d in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    assert dead == ["DEAD-PARA"]


def test_issue_repro_complexity_counts_every_statement() -> None:
    result = parse_cobol(_section_program(FIRST_SENTENCES["evaluate"]))
    counts = {
        p.name: p.statement_count
        for p in ComplexityAnalyzer().analyze(result.ast).procedures
    }
    # EVALUATE + its WHEN's DISPLAY + PERFORM + STOP RUN, as in the issue.
    assert counts["MAIN"] == 4
