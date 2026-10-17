"""Regression tests for issue #333.

A multi-token EVALUATE WHEN selector -- arithmetic (``WS-N + 1``), a
reference modification (``WS-BASE (1:2)``) or a subscript (``WS-TE (2)``) --
was stored as ``{"type": "Literal", "value": "WS-N + 1"}`` with no marker,
and gen-fixtures solved against that text as if it were a literal (and
counted WHEN OTHER as targeted against it).
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramLayoutIndex

_HEAD = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. SEL.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-F ASSIGN TO INDD.
DATA DIVISION.
FILE SECTION.
FD IN-F.
01 IN-REC.
   05 IN-QTY PIC S9(3).
   05 IN-CD  PIC X(2).
WORKING-STORAGE SECTION.
01 WS-BASE PIC X(4) VALUE 'ABCD'.
01 WS-N    PIC 9(3) VALUE 5.
01 WS-T.
   05 WS-TE PIC X(2) OCCURS 3.
PROCEDURE DIVISION.
    OPEN INPUT IN-F
    READ IN-F
"""


def _parse(body: str):
    result = parse_cobol(
        _HEAD + body + "    CLOSE IN-F\n    GOBACK.\n",
        free_form=True,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert not result.errors
    return result.ast


def _evaluate(subject: str, selector: str):
    return _parse(
        f"    EVALUATE {subject}\n"
        f"       WHEN {selector} DISPLAY 'A'\n"
        "       WHEN OTHER DISPLAY 'O'\n"
        "    END-EVALUATE\n"
    )


def _selectors(ast) -> list:
    (stmt,) = ast.find_all_by_type("EvaluateStatement")
    return stmt.to_dict()["when_clauses"][0]["selectors"]


@pytest.mark.parametrize(
    ("subject", "selector", "value"),
    [
        ("IN-QTY", "WS-N + 1", "WS-N + 1"),
        ("IN-QTY", "1 + WS-N", "1 + WS-N"),
        ("IN-CD", "WS-BASE (1:2)", "WS-BASE ( 1 : 2 )"),
        ("IN-CD", "WS-TE (2)", "WS-TE ( 2 )"),
        ("IN-CD", "FUNCTION UPPER-CASE (WS-BASE)", "FUNCTION UPPER-CASE ( WS-BASE )"),
    ],
)
def test_computed_selector_is_marked(subject: str, selector: str, value: str) -> None:
    assert _selectors(_evaluate(subject, selector)) == [
        {"type": "Literal", "value": value, "expression": True}
    ]


@pytest.mark.parametrize(
    ("subject", "selector", "expected"),
    [
        ("IN-QTY", "-5", {"type": "Literal", "value": "- 5"}),
        ("IN-QTY", "5", {"type": "Literal", "value": "5"}),
        ("IN-CD", "'AB'", {"type": "Literal", "value": "AB", "quoted": True}),
        (
            "IN-CD",
            "WS-BASE",
            {"type": "Literal", "value": "WS-BASE", "identifier": True},
        ),
    ],
)
def test_literal_selectors_are_unchanged(subject: str, selector: str, expected) -> None:
    assert _selectors(_evaluate(subject, selector)) == [expected]


def test_also_selector_is_marked() -> None:
    ast = _parse(
        "    EVALUATE IN-CD ALSO IN-QTY\n"
        "       WHEN 'AB' ALSO WS-N + 1 DISPLAY 'C'\n"
        "    END-EVALUATE\n"
    )
    assert _selectors(ast)[1] == {
        "type": "Literal",
        "value": "WS-N + 1",
        "expression": True,
    }


def _report(ast):
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ConstraintExtractor().extract(ast, index, boundaries)


@pytest.mark.parametrize(
    ("subject", "selector"),
    [("IN-QTY", "WS-N + 1"), ("IN-CD", "WS-BASE (1:2)"), ("IN-CD", "WS-TE (2)")],
)
def test_constraints_do_not_fabricate_a_literal(subject: str, selector: str) -> None:
    report = _report(_evaluate(subject, selector))
    (branch,) = report.branches
    # Neither the WHEN nor the WHEN OTHER arm gets a constraint built from
    # the selector text.
    for constraints in branch.arms.values():
        assert constraints == []
    text = str(report.to_dict())
    assert "computed operand rather than a literal" in text


def test_range_with_a_computed_bound_is_unsupported() -> None:
    report = _report(_evaluate("IN-QTY", "1 THRU WS-N + 1"))
    assert "range bound is a computed operand" in str(report.to_dict())


def test_signed_numeric_selector_still_solves() -> None:
    report = _report(_evaluate("IN-QTY", "-5"))
    (branch,) = report.branches
    when = next(iter(branch.arms.values()))
    assert when[0].values == ("-5",)


def test_business_rules_render_the_expression_unquoted() -> None:
    text = BusinessRuleExtractor().analyze(_evaluate("IN-QTY", "WS-N + 1")).to_text()
    assert "IN-QTY = WS-N + 1" in text
    assert "'WS-N + 1'" not in text
