"""Regression tests for issue #329.

IBM defines ``NOT a = b OR c`` as ``(NOT (a = b)) OR (a = c)``: a leading NOT
negates only its own relation. The builder folded the NOT into the
relation's operator in place and then repeated that already-negated
operator in the abbreviated leg, building ``a <> b OR a <> c`` -- always
true.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.business_rules import BusinessRuleExtractor

_HEAD = (
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. T.\n"
    "DATA DIVISION.\n"
    "WORKING-STORAGE SECTION.\n"
    "01 WS-CODE PIC X.\n"
    "01 A PIC 9.\n"
    "PROCEDURE DIVISION.\n"
    "MAIN-PARA.\n"
)


def _parse(statement: str):
    result = parse_cobol(
        _HEAD + f"    {statement}\n    STOP RUN.\n",
        free_form=True,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert not result.errors
    return result.ast


def _render(node) -> str:
    if getattr(node, "left_condition", None) is not None:
        if node.right_condition is None:
            return f"({node.operator} {_render(node.left_condition)})"
        return (
            f"({_render(node.left_condition)} {node.operator} "
            f"{_render(node.right_condition)})"
        )
    return f"{node.left_operand} {node.operator} {node.right_operand}"


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (
            "NOT WS-CODE = 'A' OR 'B'",
            "(WS-CODE NOT_EQUAL 'A' OR WS-CODE EQUAL 'B')",
        ),
        ("NOT A = 1 OR 2", "(A NOT_EQUAL 1 OR A EQUAL 2)"),
        ("NOT A > 1 AND 5", "(A LESS_OR_EQUAL 1 AND A GREATER 5)"),
        ("NOT A = 1 OR 2 OR 3", "((A NOT_EQUAL 1 OR A EQUAL 2) OR A EQUAL 3)"),
        ("NOT A = 1 OR NOT 2", "(A NOT_EQUAL 1 OR A NOT_EQUAL 2)"),
        # NOT inside the operator is part of it and carries to the leg.
        ("A NOT = 1 OR 2", "(A NOT_EQUAL 1 OR A NOT_EQUAL 2)"),
        # Unchanged IBM examples without a leading NOT on the subject.
        (
            "A > 1 AND NOT < 3 OR 5",
            "((A GREATER 1 AND A GREATER_OR_EQUAL 3) OR A GREATER_OR_EQUAL 5)",
        ),
    ],
)
def test_if_leading_not_negates_only_its_relation(
    condition: str, expected: str
) -> None:
    (stmt,) = _parse(f"IF {condition} DISPLAY 'X' END-IF").find_all_by_type(
        "IfStatement"
    )
    assert _render(stmt.condition) == expected


def test_perform_until_leading_not() -> None:
    ast = _parse("PERFORM UNTIL NOT A = 1 OR 2\n  ADD 1 TO A\nEND-PERFORM")
    (stmt,) = ast.find_all_by_type("PerformStatement")
    tree = stmt.until_condition.condition_tree
    assert _render(tree) == "(A NOT_EQUAL 1 OR A EQUAL 2)"


def test_business_rules_text() -> None:
    ast = _parse("IF NOT WS-CODE = 'A' OR 'B' DISPLAY 'X' END-IF")
    text = BusinessRuleExtractor().analyze(ast).to_text()
    assert "WS-CODE <> 'A' OR WS-CODE = 'B'" in text
