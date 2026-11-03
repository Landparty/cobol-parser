"""Regression tests for issue #817: an abend CALL is a way out of a loop.

``CALL 'CEE3ABD'`` and ``CALL 'ILBOABN0'`` never return, so a GO TO loop
whose only exit is such a CALL is escapable (MEDIUM), like the same loop with
STOP RUN -- not an unconditional trap (HIGH).
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer


def _source(exit_stmt: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC 9(4) VALUE 0.
       01 PGM PIC X(8) VALUE 'CEE3ABD'.
       PROCEDURE DIVISION.
       P1.
           ADD 1 TO X
           IF X > 5 {exit_stmt} END-IF
           GO TO P1.
"""


def _grades(exit_stmt: str) -> list[tuple[str, str]]:
    result = parse_cobol(_source(exit_stmt), filename="lp.cbl")
    assert result.ast is not None
    report = RecursionRiskAnalyzer().analyze(result.ast)
    return [(r.mechanism, r.severity) for r in report.risks]


@pytest.mark.parametrize(
    "exit_stmt", ["CALL 'CEE3ABD'", 'CALL "ILBOABN0"', "STOP RUN", "GOBACK"]
)
def test_terminating_exit_grades_medium(exit_stmt: str) -> None:
    assert _grades(exit_stmt) == [("GOTO", "MEDIUM")]


@pytest.mark.parametrize("exit_stmt", ["CALL PGM", "CALL 'SUBPGM'"])
def test_other_calls_are_no_exit(exit_stmt: str) -> None:
    assert _grades(exit_stmt) == [("GOTO", "HIGH")]


def test_abend_call_is_an_exit_point() -> None:
    result = parse_cobol(_source("CALL 'CEE3ABD'"), filename="lp.cbl")
    assert result.ast is not None
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    node = next(n for n in flow.nodes if n.name == "P1")
    assert node.has_abend_call
    assert node.exit_statement_kind == "CALL 'CEE3ABD'"
