"""A missing period before a paragraph header no longer loses the paragraph
when the statement before it ends in a condition, an argument list or a
clause body.

The operand loops of MOVE, ADD, DISPLAY, STRING and others already stopped at
a header written without the period before it (H9). These did not:

* ``PERFORM P UNTIL c`` / ``PERFORM P VARYING ... UNTIL c`` and ``IF c``
  read the header into the condition text;
* ``CALL 'X' USING A`` took it as one more argument;
* ``INITIALIZE A`` took it as one more target;
* ``EVALUATE ... WHEN OTHER s`` and ``READ ... AT END s`` stopped the inner
  statement there (with the warning) and then consumed the header in the
  clause-body loop anyway.

The paragraph vanished from the AST, and lint reported a PERFORM of it as an
undefined name. Found by the 2026-11-10 bug hunt.
"""

from __future__ import annotations

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.analysis.lint import LintAnalyzer

_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPRD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO FDD.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 F-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 A PIC 9.
       01 B PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM P1
{statement}
       P1.
           DISPLAY 'IN P1'.
       P2.
           STOP RUN.
"""

_STATEMENTS = [
    "           PERFORM P2 UNTIL A > 5",
    "           PERFORM P2 VARYING A FROM 1 BY 1 UNTIL A > 5",
    "           IF A > B",
    "           CALL 'X' USING A",
    "           INITIALIZE A",
    "           EVALUATE A WHEN 1 CONTINUE WHEN OTHER MOVE 1 TO B",
    "           READ F AT END MOVE 1 TO B",
]


def _parse(statement: str):
    source = _TEMPLATE.format(statement=statement)
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)


@pytest.mark.parametrize("statement", _STATEMENTS)
def test_paragraph_after_missing_period_is_kept(statement: str) -> None:
    result = _parse(statement)

    names = [p.paragraph_name for p in result.ast.procedure_division.paragraphs]
    assert names == ["MAIN-PARA", "P1", "P2"]
    p1 = result.ast.procedure_division.paragraphs[1]
    assert [type(s).__name__ for s in p1.statements] == ["DisplayStatement"]
    missing = [w for w in result.warnings if "missing its terminating period" in w]
    assert len(missing) == 1, result.warnings
    assert "'P1'" in missing[0]
    assert not result.errors


def test_header_stays_out_of_the_statement() -> None:
    perform = _parse(_STATEMENTS[0]).ast.procedure_division.paragraphs[0]
    until = perform.statements[1].until_condition
    assert "P1" not in " ".join(until.operands)

    call = _parse(_STATEMENTS[3]).ast.procedure_division.paragraphs[0]
    assert [p.name for p in call.statements[1].using_parameters] == ["A"]

    initialize = _parse(_STATEMENTS[4]).ast.procedure_division.paragraphs[0]
    assert initialize.statements[1].targets == ["A"]


def test_lint_reports_no_undefined_paragraph() -> None:
    result = _parse("           PERFORM P1 UNTIL A > 5")
    findings = LintAnalyzer().analyze(result.ast).findings
    assert not [f for f in findings if f.rule == "undefined-name"]


def test_continuation_operand_is_not_a_header() -> None:
    """A wrapped operand deeper than the verb is still an operand."""
    source = _TEMPLATE.format(
        statement="           CALL 'X' USING A\n                B."
    ).replace("       P1.\n           DISPLAY 'IN P1'.\n", "")
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)
    call = result.ast.procedure_division.paragraphs[0].statements[1]
    assert [p.name for p in call.using_parameters] == ["A", "B"]
