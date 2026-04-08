"""Tests for EVALUATE, IF, and SEARCH statement model coverage.

Targets uncovered lines in models/statements/control.py (72.43%):
  - EvaluateStatement: add_subject, add_when_clause, set_default_when, to_dict
  - IfStatement: set_condition, add_then_statement, add_else_statement, to_dict
  - SearchStatement: set_table_name, set_varying_variable, add_when_clause,
    set_at_end_clause, to_dict
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.base import CobolExpression, ConditionalExpression
from cobolparser.models.statements.control import (
    EvaluateStatement,
    IfStatement,
    SearchStatement,
    WhenClause,
)
from cobolparser.models.statements.data import DisplayStatement


class TestEvaluateStatementModel:
    """Cover EvaluateStatement setters and to_dict."""

    def test_add_subject_string(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        stmt.add_subject("WS-GRADE")
        assert stmt.subjects == ["WS-GRADE"]
        assert "WS-GRADE" in stmt.operands

    def test_add_subject_expression(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        expr = CobolExpression("CONDITION", SourceLocation(1, 10))
        stmt.add_subject(expr)
        assert len(stmt.subjects) == 1
        assert isinstance(stmt.subjects[0], CobolExpression)

    def test_add_when_clause(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        when = WhenClause([{"type": "Literal", "value": "1"}], SourceLocation(2, 1))
        display = DisplayStatement(SourceLocation(2, 10))
        display.add_display_item("FOUND")
        when.add_statement(display)
        stmt.add_when_clause(when)
        assert len(stmt.when_clauses) == 1
        assert len(stmt.when_clauses[0].statements) == 1

    def test_set_default_when(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        default = WhenClause([{"type": "Any"}], SourceLocation(3, 1))
        display = DisplayStatement(SourceLocation(3, 10))
        display.add_display_item("DEFAULT")
        default.add_statement(display)
        stmt.set_default_when(default)
        assert stmt.default_when is not None

    def test_to_dict_with_string_subjects(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        stmt.add_subject("WS-GRADE")
        when = WhenClause([{"type": "Literal", "value": "A"}], SourceLocation(2, 1))
        stmt.add_when_clause(when)

        d = stmt.to_dict()
        assert d["subjects"] == ["WS-GRADE"]
        assert len(d["when_clauses"]) == 1
        assert d["default_when"] is None

    def test_to_dict_with_expression_subjects(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        expr = CobolExpression("CONDITION", SourceLocation(1, 10))
        stmt.add_subject(expr)

        d = stmt.to_dict()
        assert len(d["subjects"]) == 1
        assert isinstance(d["subjects"][0], dict)

    def test_to_dict_with_default_when(self):
        stmt = EvaluateStatement(SourceLocation(1, 1))
        stmt.add_subject("WS-X")
        default = WhenClause([{"type": "Any"}], SourceLocation(3, 1))
        stmt.set_default_when(default)

        d = stmt.to_dict()
        assert d["default_when"] is not None
        assert d["default_when"]["selectors"] == [{"type": "Any"}]


class TestIfStatementModel:
    """Cover IfStatement setters and to_dict."""

    def test_set_condition(self):
        stmt = IfStatement(SourceLocation(1, 1))
        cond = ConditionalExpression(">", SourceLocation(1, 5))
        cond.set_left_operand("WS-A")
        cond.set_right_operand("10")
        stmt.set_condition(cond)
        assert stmt.condition is not None
        assert stmt.condition.operator == ">"

    def test_add_then_statement(self):
        stmt = IfStatement(SourceLocation(1, 1))
        display = DisplayStatement(SourceLocation(2, 1))
        display.add_display_item("YES")
        stmt.add_then_statement(display)
        assert len(stmt.then_statements) == 1

    def test_add_else_statement(self):
        stmt = IfStatement(SourceLocation(1, 1))
        display = DisplayStatement(SourceLocation(3, 1))
        display.add_display_item("NO")
        stmt.add_else_statement(display)
        assert len(stmt.else_statements) == 1

    def test_to_dict_with_branches(self):
        stmt = IfStatement(SourceLocation(1, 1))
        cond = ConditionalExpression("=", SourceLocation(1, 5))
        cond.set_left_operand("WS-FLAG")
        cond.set_right_operand("Y")
        stmt.set_condition(cond)

        then_stmt = DisplayStatement(SourceLocation(2, 1))
        then_stmt.add_display_item("TRUE-BRANCH")
        stmt.add_then_statement(then_stmt)

        else_stmt = DisplayStatement(SourceLocation(3, 1))
        else_stmt.add_display_item("FALSE-BRANCH")
        stmt.add_else_statement(else_stmt)

        d = stmt.to_dict()
        assert d["condition"] is not None
        assert len(d["then_statements"]) == 1
        assert len(d["else_statements"]) == 1

    def test_to_dict_no_condition(self):
        stmt = IfStatement(SourceLocation(1, 1))
        d = stmt.to_dict()
        assert d["condition"] is None
        assert d["then_statements"] == []
        assert d["else_statements"] == []


class TestSearchStatementModel:
    """Cover SearchStatement setters and to_dict."""

    def test_set_table_name(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        stmt.set_table_name("WS-TABLE")
        assert stmt.table_name == "WS-TABLE"

    def test_set_varying_variable(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        stmt.set_varying_variable("WS-IDX")
        assert stmt.varying_variable == "WS-IDX"

    def test_add_when_clause(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        display = DisplayStatement(SourceLocation(2, 1))
        display.add_display_item("FOUND")
        stmt.add_when_clause("WS-KEY(WS-IDX) = WS-SEARCH", [display])
        assert len(stmt.when_clauses) == 1
        assert stmt.when_clauses[0]["condition"] == "WS-KEY(WS-IDX) = WS-SEARCH"

    def test_set_at_end_clause(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        display = DisplayStatement(SourceLocation(3, 1))
        display.add_display_item("NOT FOUND")
        stmt.set_at_end_clause([display])
        assert stmt.at_end_clause is not None
        assert len(stmt.at_end_clause) == 1

    def test_to_dict_full(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        stmt.set_table_name("WS-TABLE")
        stmt.set_varying_variable("WS-IDX")

        display_found = DisplayStatement(SourceLocation(2, 1))
        display_found.add_display_item("FOUND")
        stmt.add_when_clause("WS-KEY(WS-IDX) = 'A'", [display_found])

        display_end = DisplayStatement(SourceLocation(3, 1))
        display_end.add_display_item("NOT FOUND")
        stmt.set_at_end_clause([display_end])

        d = stmt.to_dict()
        assert d["table_name"] == "WS-TABLE"
        assert d["varying_variable"] == "WS-IDX"
        assert len(d["when_clauses"]) == 1
        assert d["when_clauses"][0]["condition"] == "WS-KEY(WS-IDX) = 'A'"
        assert len(d["when_clauses"][0]["statements"]) == 1
        assert len(d["at_end_clause"]) == 1

    def test_to_dict_minimal(self):
        stmt = SearchStatement(SourceLocation(1, 1))
        d = stmt.to_dict()
        assert "table_name" not in d
        assert "varying_variable" not in d
        assert "when_clauses" not in d
        assert "at_end_clause" not in d
