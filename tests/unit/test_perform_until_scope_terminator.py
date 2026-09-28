"""An out-of-line ``PERFORM p UNTIL c`` / ``VARYING ... UNTIL c`` nested in an
IF / EVALUATE / inline PERFORM must stop its condition at the enclosing
statement's scope terminator, not swallow it.

Swallowing ``END-IF`` into the condition text re-nested every statement up to
the next period into that IF arm, so a top-level ``STOP RUN`` read as
conditional and the control-flow analyzers invented a fall-through out of a
paragraph that always stops (hiding the dead paragraph after it).
"""

import pytest

from cobolparser import DeadCodeAnalyzer, parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    StopStatement,
)


def _program(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PSCOPE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 A PIC X(10).\n"
        "       01 B PIC 9.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n" + body + "       WORK.\n"
        "           DISPLAY 'W'.\n"
        "       DEAD-PARA.\n"
        "           DISPLAY 'D'.\n"
    )


def _main_statements(source: str) -> list:
    result = parse_cobol(source)
    assert result.ast is not None
    assert not result.errors, result.errors
    return result.ast.procedure_division.paragraphs[0].statements


def _until_text(stmt: PerformStatement) -> str:
    assert stmt.until_condition is not None
    return " ".join(str(op) for op in stmt.until_condition.operands)


@pytest.mark.parametrize(
    "perform",
    [
        "PERFORM WORK UNTIL B > 1",
        "PERFORM WORK WITH TEST AFTER UNTIL B > 1",
        "PERFORM WORK VARYING B FROM 1 BY 1 UNTIL B > 1",
    ],
)
def test_end_if_closes_the_if_not_the_condition(perform: str) -> None:
    source = _program(
        f"           IF A = 1 {perform}\n"
        "           END-IF\n"
        "           STOP RUN.\n"
    )
    stmts = _main_statements(source)
    assert [type(s) for s in stmts] == [IfStatement, StopStatement]
    (inner,) = stmts[0].then_statements
    assert isinstance(inner, PerformStatement)
    assert "END-IF" not in _until_text(inner)


def test_end_evaluate_closes_the_evaluate() -> None:
    source = _program(
        "           EVALUATE A\n"
        "             WHEN OTHER PERFORM WORK UNTIL B > 1\n"
        "           END-EVALUATE\n"
        "           STOP RUN.\n"
    )
    stmts = _main_statements(source)
    assert [type(s) for s in stmts] == [EvaluateStatement, StopStatement]
    (inner,) = stmts[0].default_when.statements
    assert _until_text(inner) == "B > 1"


def test_end_perform_belongs_to_the_enclosing_inline_perform() -> None:
    source = _program(
        "           PERFORM UNTIL B > 1\n"
        "              PERFORM WORK UNTIL A = 'X'\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n"
    )
    stmts = _main_statements(source)
    assert [type(s) for s in stmts] == [PerformStatement, StopStatement]
    (inner,) = stmts[0].inline_statements
    assert "END-PERFORM" not in _until_text(inner)


def test_paragraph_after_a_stopping_main_is_dead() -> None:
    source = _program(
        "           IF A = 1 PERFORM WORK UNTIL B > 1 END-IF\n" "           STOP RUN.\n"
    )
    result = parse_cobol(source)
    assert result.ast is not None
    dead = [i.name for i in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    assert dead == ["DEAD-PARA"]
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    assert not any(
        e.source == "MAIN" and e.edge_type.value == "FALL_THROUGH" for e in flow.edges
    )
