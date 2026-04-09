"""Tests targeting uncovered lines in arithmetic_parsers.py.

Covers:
- _skip_to_period utility in each parser class
- NOT ON SIZE ERROR clause parsing paths
- SUBTRACT/MULTIPLY/DIVIDE GIVING variants
- COMPUTE expression edge cases
- matches() returning False on empty/wrong token
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.parser import CobolParser
from cobolparser.parsers.statements.arithmetic_parsers import (
    ComputeStatementParser,
    DivideStatementParser,
    MultiplyStatementParser,
)


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-ARITH.\n"
        "       PROCEDURE DIVISION.\n"
        f"{code}\n"
    )
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements, result
    return [], result


def _find_stmt(stmts, stmt_type):
    """Find and return the first statement of a given type, or fail."""
    for s in stmts:
        if isinstance(s, stmt_type):
            return s
    pytest.fail(f"No {stmt_type.__name__} found in {stmts}")


class TestSubtractGiving:
    """Tests for SUBTRACT ... GIVING path (lines 346-351)."""

    def test_subtract_giving(self):
        stmts, _ = parse_procedure("           SUBTRACT A FROM B GIVING C.")
        _find_stmt(stmts, SubtractStatement)

    def test_subtract_multiple_operands(self):
        stmts, _ = parse_procedure("           SUBTRACT A B FROM C GIVING D.")
        stmt = _find_stmt(stmts, SubtractStatement)
        assert len(stmt.operands) >= 2

    def test_subtract_with_trailing_tokens_triggers_skip_to_period(self):
        """SUBTRACT with ROUNDED after target exercises _skip_to_period."""
        stmts, _ = parse_procedure("           SUBTRACT A FROM B ROUNDED.")
        _find_stmt(stmts, SubtractStatement)


class TestMultiplyGiving:
    """Tests for MULTIPLY ... GIVING path (lines 416-421)."""

    def test_multiply_giving_sets_giving_target(self):
        stmts, _ = parse_procedure("           MULTIPLY A BY B GIVING C.")
        stmt = _find_stmt(stmts, MultiplyStatement)
        d = stmt.to_dict()
        assert d["giving"] == "C"


class TestDivideGiving:
    """Tests for DIVIDE ... BY/INTO ... GIVING path (lines 476-493)."""

    def test_divide_by_giving(self):
        stmts, _ = parse_procedure("           DIVIDE A BY B GIVING C.")
        stmt = _find_stmt(stmts, DivideStatement)
        d = stmt.to_dict()
        assert d["giving"] == "C"

    def test_divide_into(self):
        stmts, _ = parse_procedure("           DIVIDE A INTO B.")
        stmt = _find_stmt(stmts, DivideStatement)
        assert len(stmt.operands) >= 2


class TestComputeExpressions:
    """Tests for COMPUTE expression parsing (lines 530-595)."""

    def test_compute_with_parenthesized_expression(self):
        stmts, _ = parse_procedure("           COMPUTE A = (B + C) * (D - E).")
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.expression is not None
        assert "B" in compute.expression and "D" in compute.expression

    def test_compute_with_end_compute(self):
        stmts, _ = parse_procedure(
            "           COMPUTE A = B + C\n               END-COMPUTE."
        )
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.expression is not None

    def test_compute_with_on_size_error(self):
        stmts, _ = parse_procedure(
            "           COMPUTE A = B / C\n"
            "               ON SIZE ERROR\n"
            '                   DISPLAY "Overflow".'
        )
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.on_size_error is not None
        assert len(compute.on_size_error) >= 1

    def test_compute_with_not_on_size_error(self):
        stmts, _ = parse_procedure(
            "           COMPUTE A = B + 1\n"
            "               NOT ON SIZE ERROR\n"
            '                   DISPLAY "OK".'
        )
        compute = _find_stmt(stmts, ComputeStatement)
        assert compute.not_on_size_error is not None
        assert len(compute.not_on_size_error) >= 1

    def test_compute_rounded(self):
        stmts, _ = parse_procedure("           COMPUTE A ROUNDED = B + C.")
        compute = _find_stmt(stmts, ComputeStatement)
        assert "A" in compute.targets


class TestAddSizeErrorNested:
    """Tests for nested DISPLAY/MOVE within ON SIZE ERROR (lines 201-290)."""

    def test_add_on_size_error_with_move(self):
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               ON SIZE ERROR\n"
            "                   MOVE 0 TO C."
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.on_size_error is not None
        assert any(s.statement_type == "MOVE" for s in add_stmt.on_size_error)

    def test_add_not_on_size_error_with_display_and_move(self):
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               NOT ON SIZE ERROR\n"
            '                   DISPLAY "OK"\n'
            "                   MOVE 1 TO C."
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.not_on_size_error is not None
        types = [s.statement_type for s in add_stmt.not_on_size_error]
        assert "DISPLAY" in types
        assert "MOVE" in types

    def test_add_both_size_error_clauses(self):
        stmts, _ = parse_procedure(
            "           ADD A TO B\n"
            "               ON SIZE ERROR\n"
            '                   DISPLAY "Error"\n'
            "               NOT ON SIZE ERROR\n"
            '                   DISPLAY "OK".'
        )
        add_stmt = _find_stmt(stmts, AddStatement)
        assert add_stmt.on_size_error is not None


@pytest.mark.parametrize(
    "parser_cls",
    [MultiplyStatementParser, DivideStatementParser, ComputeStatementParser],
    ids=["multiply", "divide", "compute"],
)
class TestMatchesFalse:
    """matches() returns False on empty stream or wrong token type."""

    def test_matches_empty_stream(self, parser_cls):
        assert parser_cls().matches(TokenStream([])) is False

    def test_matches_wrong_token(self, parser_cls):
        tok = Token(TokenType.IDENTIFIER, "FOO", SourceLocation(1, 1))
        assert parser_cls().matches(TokenStream([tok])) is False
