"""Regression tests for issue #495: MULTIPLY / DIVIDE ... GIVING operands.

``operands`` dedupes, so ``MULTIPLY A BY B GIVING B`` left ``[A, B]`` and,
once the GIVING name was filtered out, one operand: business-rules printed
``compute MULTIPLY A GIVING B``. The parser now records both sending
operands of the GIVING form in ``source_operands``. And program-flow's
statement text rendered the GIVING form as ``DIVIDE A B C``, so ``diff``
reported an INTO -> BY change as ``DIVIDE A B C -> DIVIDE A B C``.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.program_flow.statement_text import summarize_statement
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.generators import ProgramLayoutIndex

_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BR3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A PIC 9(5).
       01  B PIC 9(5).
       01  C PIC 9(5).
       01  R PIC 9(5).
       PROCEDURE DIVISION.
       MAIN.
{body}           STOP RUN.
"""


def _ast(body: str):  # type: ignore[no-untyped-def]
    result = parse_cobol(_TEMPLATE.format(body=body), filename="br3.cbl")
    assert result.ast is not None and not result.errors
    return result.ast


def _formulas(body: str) -> list[str]:
    report = BusinessRuleExtractor().analyze(_ast(body))
    return [r.formula for r in report.rules if r.kind == "calculation"]


def test_giving_target_that_is_also_an_operand_keeps_both_operands() -> None:
    body = (
        "           MULTIPLY A BY B GIVING B\n"
        "           DIVIDE B INTO A GIVING A\n"
        "           DIVIDE A BY B GIVING A\n"
    )
    assert _formulas(body) == ["B = A * B", "A = A / B", "A = A / B"]


def test_same_operand_twice() -> None:
    assert _formulas("           MULTIPLY A BY A GIVING C\n") == ["C = A * A"]


def test_statement_text_shows_into_and_by() -> None:
    body = (
        "           DIVIDE A INTO B GIVING C\n"
        "           DIVIDE A BY B GIVING C REMAINDER R\n"
        "           MULTIPLY A BY B GIVING C ROUNDED\n"
    )
    stmts = _ast(body).get_all_statements()
    assert [summarize_statement(s) for s in stmts[:3]] == [
        "DIVIDE A INTO B GIVING C",
        "DIVIDE A BY B GIVING C REMAINDER R",
        "MULTIPLY A BY B GIVING C ROUNDED",
    ]


def test_diff_shows_into_to_by() -> None:
    old = _ast("           DIVIDE A INTO B GIVING C\n")
    new = _ast("           DIVIDE A BY B GIVING C\n")
    report = ProgramDiffer().diff(old, new)
    messages = [c.detail for c in report.changes]
    assert any(
        "DIVIDE A INTO B GIVING C -> DIVIDE A BY B GIVING C" in m for m in messages
    ), messages


def test_xref_does_not_read_the_giving_target() -> None:
    report = XrefAnalyzer().analyze(_ast("           MULTIPLY A BY A GIVING C\n"))
    roles = {e.name: {r.role for r in e.references} for e in report.entries}
    assert roles["C"] == {"write"}
    assert "read" in roles["A"]


def test_const_fold_uses_both_operands() -> None:
    ast = _ast(
        "           MOVE 3 TO A\n"
        "           MULTIPLY A BY A GIVING C\n"
        "           DISPLAY C\n"
    )
    fold = ConstantFolder().fold(ast, ProgramLayoutIndex.build(ast))
    assert fold.known.get("C") == "9"
