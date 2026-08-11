"""Unit tests for cobolparser.analysis.program_flow.condition_text."""

from __future__ import annotations

from cobolparser.analysis.program_flow.condition_text import render_condition_text
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.base import (
    CobolExpression,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)

LOC = SourceLocation(line=1, column=8)


def test_none_returns_empty_string() -> None:
    assert render_condition_text(None) == ""


def test_simple_equal_comparison() -> None:
    expr = ConditionalExpression("EQUAL", LOC)
    expr.set_left_operand("WS-EOF-SW")
    expr.set_right_operand("'Y'")
    assert render_condition_text(expr) == "WS-EOF-SW = 'Y'"


def test_greater_or_equal_comparison() -> None:
    expr = ConditionalExpression("GREATER_OR_EQUAL", LOC)
    expr.set_left_operand("WS-QTY")
    expr.set_right_operand("0")
    assert render_condition_text(expr) == "WS-QTY >= 0"


def test_not_equal_comparison() -> None:
    expr = ConditionalExpression("NOT_EQUAL", LOC)
    expr.set_left_operand("WS-STATUS")
    expr.set_right_operand("'A'")
    assert render_condition_text(expr) == "WS-STATUS <> 'A'"


def test_class_condition() -> None:
    expr = ConditionalExpression("IS NUMERIC", LOC)
    expr.set_left_operand("WS-AMOUNT")
    assert render_condition_text(expr) == "WS-AMOUNT IS NUMERIC"


def test_negated_class_condition() -> None:
    expr = ConditionalExpression("IS NOT POSITIVE", LOC)
    expr.set_left_operand("WS-BALANCE")
    assert render_condition_text(expr) == "WS-BALANCE IS NOT POSITIVE"


def test_condition_name() -> None:
    expr = ConditionalExpression("CONDITION_NAME", LOC)
    expr.set_left_operand("END-OF-FILE")
    assert render_condition_text(expr) == "END-OF-FILE"


def test_comparison_fallback_uses_raw_condition_metadata() -> None:
    expr = ConditionalExpression("COMPARISON", LOC)
    expr.set_metadata("raw_condition", "WS-A ( 1 )")
    assert render_condition_text(expr) == "WS-A ( 1 )"


def test_logical_and() -> None:
    left = ConditionalExpression("EQUAL", LOC)
    left.set_left_operand("WS-A")
    left.set_right_operand("1")
    right = ConditionalExpression("EQUAL", LOC)
    right.set_left_operand("WS-B")
    right.set_right_operand("2")
    logical = LogicalExpression("AND", LOC)
    logical.set_left_condition(left)
    logical.set_right_condition(right)
    assert render_condition_text(logical) == "WS-A = 1 AND WS-B = 2"


def test_logical_or_nested_under_and() -> None:
    # (A OR B) AND C
    a = ConditionalExpression("EQUAL", LOC)
    a.set_left_operand("A")
    a.set_right_operand("1")
    b = ConditionalExpression("EQUAL", LOC)
    b.set_left_operand("B")
    b.set_right_operand("2")
    or_expr = LogicalExpression("OR", LOC)
    or_expr.set_left_condition(a)
    or_expr.set_right_condition(b)
    c = ConditionalExpression("EQUAL", LOC)
    c.set_left_operand("C")
    c.set_right_operand("3")
    and_expr = LogicalExpression("AND", LOC)
    and_expr.set_left_condition(or_expr)
    and_expr.set_right_condition(c)
    assert render_condition_text(and_expr) == "A = 1 OR B = 2 AND C = 3"


def test_function_call_operand() -> None:
    func = FunctionCall("UPPER-CASE", LOC)
    func.add_argument("WS-NAME")
    expr = ConditionalExpression("EQUAL", LOC)
    expr.set_left_operand(func)
    expr.set_right_operand('"SMITH"')
    assert render_condition_text(expr) == 'UPPER-CASE(WS-NAME) = "SMITH"'


def test_perform_until_raw_wrapper_uses_operands() -> None:
    # PERFORM UNTIL's CobolExpression("CONDITION") wrapper: real text lives
    # in operands[0], not expression_type.
    expr = CobolExpression("CONDITION", LOC)
    expr.operands = ["WS-EOF-SW = 'Y'"]
    assert render_condition_text(expr) == "WS-EOF-SW = 'Y'"


def test_bare_expression_with_nothing_falls_back_to_expression_type() -> None:
    # Matches today's behavior for synthetic test doubles with no operands,
    # no metadata, and no structured left/right operand -- see
    # test_program_flow.py::TestBranchNodes::test_if_with_else_creates_one_branch_node,
    # which pins this exact fallback.
    expr = CobolExpression("COMPARISON", LOC)
    assert render_condition_text(expr) == "COMPARISON"


def test_conditional_expression_with_no_left_operand_falls_back() -> None:
    # A ConditionalExpression("COMPARISON", ...) with no operand set at all
    # (the _conditions.py catch-all wrapper before raw_condition metadata is
    # attached) falls back the same way.
    expr = ConditionalExpression("COMPARISON", LOC)
    assert render_condition_text(expr) == "COMPARISON"
