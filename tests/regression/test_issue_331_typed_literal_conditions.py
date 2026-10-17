"""Regression tests for issue #331.

A typed literal (``X'00'``, ``Z'q'``) in a condition or an EVALUATE selector
lost its prefix: ``X'0000'`` was stored as the plain ``'0000'`` -- four
characters rather than two bytes -- so gen-fixtures reported a 2-byte
comparison against a ``PIC X(2)`` field as unsatisfiable.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Witness, solve
from cobolparser.generators import ProgramLayoutIndex

_HEAD = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. HEX.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-F ASSIGN TO INDD.
DATA DIVISION.
FILE SECTION.
FD IN-F.
01 IN-REC.
   05 IN-TYPE PIC X(2).
   05 IN-B    PIC X.
WORKING-STORAGE SECTION.
01 WS-A PIC X.
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


def _render(node) -> str:
    if getattr(node, "left_condition", None) is not None:
        return (
            f"({_render(node.left_condition)} {node.operator} "
            f"{_render(node.right_condition)})"
        )
    return f"{node.left_operand} {node.operator} {node.right_operand}"


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("IN-TYPE = X'0000'", "IN-TYPE EQUAL X'0000'"),
        ('IN-TYPE = X"0000"', "IN-TYPE EQUAL X'0000'"),
        ("IN-B = X'00' OR Z'q'", "(IN-B EQUAL X'00' OR IN-B EQUAL Z'q')"),
        ("IN-B = 'A' OR N'B'", "(IN-B EQUAL 'A' OR IN-B EQUAL N'B')"),
    ],
)
def test_if_condition_keeps_the_prefix(condition: str, expected: str) -> None:
    ast = _parse(f"    IF {condition} DISPLAY 'X' END-IF\n")
    (stmt,) = ast.find_all_by_type("IfStatement")
    assert _render(stmt.condition) == expected


def test_perform_until_keeps_the_prefix() -> None:
    ast = _parse(
        "    PERFORM UNTIL WS-A = HIGH-VALUES OR X'FF'\n"
        "       MOVE X'FF' TO WS-A\n    END-PERFORM\n"
    )
    (stmt,) = ast.find_all_by_type("PerformStatement")
    tree = stmt.until_condition.condition_tree
    assert _render(tree) == "(WS-A EQUAL HIGH-VALUES OR WS-A EQUAL X'FF')"


def test_evaluate_selector_keeps_the_prefix() -> None:
    ast = _parse(
        "    EVALUATE IN-B\n"
        "       WHEN X'00' DISPLAY 'Z'\n"
        "       WHEN X'01' THRU X'0F' DISPLAY 'R'\n"
        "       WHEN 'A' DISPLAY 'A'\n"
        "    END-EVALUATE\n"
    )
    (stmt,) = ast.find_all_by_type("EvaluateStatement")
    whens = stmt.to_dict()["when_clauses"]
    assert whens[0]["selectors"] == [
        {"type": "Literal", "value": "X'00'", "typed": True}
    ]
    assert whens[1]["selectors"] == [
        {"type": "Range", "start": "X'01'", "end": "X'0F'"}
    ]
    assert whens[2]["selectors"] == [{"type": "Literal", "value": "A", "quoted": True}]


def _constraints(body: str):
    ast = _parse(body)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ConstraintExtractor().extract(ast, index, boundaries)


def test_two_byte_hex_literal_fits_a_two_character_field() -> None:
    report = _constraints("    IF IN-TYPE = X'0000' DISPLAY 'N' END-IF\n")
    (branch,) = report.branches
    (constraint,) = branch.arms["THEN"]
    assert constraint.values == ("\x00\x00",)
    witness = solve(constraint.field.spec, branch.arms["THEN"])
    assert isinstance(witness, Witness)
    assert witness.value == "\x00\x00"


def test_one_byte_hex_evaluate_selector_is_one_character() -> None:
    report = _constraints(
        "    EVALUATE IN-B\n       WHEN X'41' DISPLAY 'A'\n"
        "       WHEN OTHER DISPLAY 'O'\n    END-EVALUATE\n"
    )
    (branch,) = report.branches
    constraints = next(iter(branch.arms.values()))
    assert constraints[0].values == ("A",)


def test_business_rules_render_the_typed_literal() -> None:
    ast = _parse("    EVALUATE IN-B\n       WHEN X'00' DISPLAY 'Z'\n    END-EVALUATE\n")
    text = BusinessRuleExtractor().analyze(ast).to_text()
    assert "IN-B = X'00'" in text
