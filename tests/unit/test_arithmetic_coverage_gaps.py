"""Tests targeting uncovered lines in arithmetic_parsers.py.

Covers:
- _skip_to_period utility in each parser class
- NOT ON SIZE ERROR clause parsing paths
- SUBTRACT/MULTIPLY/DIVIDE GIVING variants
- COMPUTE expression edge cases
- matches() returning False on empty/wrong token
"""

from cobolparser.models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.parser import CobolParser


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-ARITH.
       PROCEDURE DIVISION.
{code}
    """
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections:
        sec = proc.sections[0]
        if sec.paragraphs:
            return sec.paragraphs[0].statements, result
    return [], result


class TestSubtractGiving:
    """Tests for SUBTRACT ... GIVING path (line 346-351)."""

    def test_subtract_giving(self):
        stmts, result = parse_procedure(
            "           SUBTRACT A FROM B GIVING C."
        )
        assert any(isinstance(s, SubtractStatement) for s in stmts)

    def test_subtract_multiple_operands_giving(self):
        stmts, result = parse_procedure(
            "           SUBTRACT A B FROM C GIVING D."
        )
        assert any(isinstance(s, SubtractStatement) for s in stmts)


class TestMultiplyGiving:
    """Tests for MULTIPLY ... GIVING path (lines 416-421)."""

    def test_multiply_giving(self):
        stmts, result = parse_procedure(
            "           MULTIPLY A BY B GIVING C."
        )
        assert any(isinstance(s, MultiplyStatement) for s in stmts)

    def test_multiply_matches_false_empty(self):
        """matches() should return False on empty stream."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.parsers.statements.arithmetic_parsers import (
            MultiplyStatementParser,
        )

        parser = MultiplyStatementParser()
        stream = TokenStream([])
        assert parser.matches(stream) is False

    def test_multiply_matches_false_wrong_token(self):
        """matches() should return False for non-MULTIPLY token."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.parsers.statements.arithmetic_parsers import (
            MultiplyStatementParser,
        )

        parser = MultiplyStatementParser()
        tok = Token(TokenType.IDENTIFIER, "FOO", SourceLocation(1, 1))
        stream = TokenStream([tok])
        assert parser.matches(stream) is False


class TestDivideGiving:
    """Tests for DIVIDE ... BY ... GIVING path (lines 486-493)."""

    def test_divide_by_giving(self):
        stmts, result = parse_procedure(
            "           DIVIDE A BY B GIVING C."
        )
        assert any(isinstance(s, DivideStatement) for s in stmts)

    def test_divide_into(self):
        stmts, result = parse_procedure(
            "           DIVIDE A INTO B."
        )
        assert any(isinstance(s, DivideStatement) for s in stmts)

    def test_divide_matches_false_empty(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.parsers.statements.arithmetic_parsers import (
            DivideStatementParser,
        )

        parser = DivideStatementParser()
        stream = TokenStream([])
        assert parser.matches(stream) is False


class TestComputeExpressions:
    """Tests for COMPUTE expression parsing (lines 557-595)."""

    def test_compute_with_parenthesized_expression(self):
        stmts, result = parse_procedure(
            "           COMPUTE A = (B + C) * (D - E)."
        )
        assert any(isinstance(s, ComputeStatement) for s in stmts)
        compute = next(s for s in stmts if isinstance(s, ComputeStatement))
        assert compute.expression is not None

    def test_compute_with_end_compute(self):
        stmts, result = parse_procedure(
            "           COMPUTE A = B + C\n               END-COMPUTE."
        )
        assert any(isinstance(s, ComputeStatement) for s in stmts)

    def test_compute_with_on_size_error(self):
        stmts, result = parse_procedure(
            "           COMPUTE A = B / C\n"
            "               ON SIZE ERROR\n"
            "                   DISPLAY \"Overflow\"."
        )
        assert any(isinstance(s, ComputeStatement) for s in stmts)
        compute = next(s for s in stmts if isinstance(s, ComputeStatement))
        assert compute.on_size_error is not None

    def test_compute_with_not_on_size_error(self):
        stmts, result = parse_procedure(
            "           COMPUTE A = B + 1\n"
            "               NOT ON SIZE ERROR\n"
            "                   DISPLAY \"OK\"."
        )
        assert any(isinstance(s, ComputeStatement) for s in stmts)
        compute = next(s for s in stmts if isinstance(s, ComputeStatement))
        assert compute.not_on_size_error is not None

    def test_compute_matches_false(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.parsers.statements.arithmetic_parsers import (
            ComputeStatementParser,
        )

        parser = ComputeStatementParser()
        stream = TokenStream([])
        assert parser.matches(stream) is False

    def test_compute_rounded(self):
        stmts, result = parse_procedure(
            "           COMPUTE A ROUNDED = B + C."
        )
        assert any(isinstance(s, ComputeStatement) for s in stmts)


class TestAddSizeErrorNestedMove:
    """Tests for nested MOVE parsing within ON SIZE ERROR (lines 246-284)."""

    def test_add_on_size_error_with_move(self):
        stmts, result = parse_procedure(
            "           ADD A TO B\n"
            "               ON SIZE ERROR\n"
            "                   MOVE 0 TO C."
        )
        assert any(isinstance(s, AddStatement) for s in stmts)
        add_stmt = next(s for s in stmts if isinstance(s, AddStatement))
        assert add_stmt.on_size_error is not None
        assert len(add_stmt.on_size_error) >= 1

    def test_add_not_on_size_error_with_display_and_move(self):
        stmts, result = parse_procedure(
            "           ADD A TO B\n"
            "               NOT ON SIZE ERROR\n"
            "                   DISPLAY \"OK\"\n"
            "                   MOVE 1 TO C."
        )
        assert any(isinstance(s, AddStatement) for s in stmts)
        add_stmt = next(s for s in stmts if isinstance(s, AddStatement))
        assert add_stmt.not_on_size_error is not None

    def test_add_both_size_error_clauses(self):
        stmts, result = parse_procedure(
            "           ADD A TO B\n"
            "               ON SIZE ERROR\n"
            "                   DISPLAY \"Error\"\n"
            "               NOT ON SIZE ERROR\n"
            "                   DISPLAY \"OK\"."
        )
        assert any(isinstance(s, AddStatement) for s in stmts)
        add_stmt = next(s for s in stmts if isinstance(s, AddStatement))
        # The parser collects both DISPLAY statements — at minimum on_size_error is set
        assert add_stmt.on_size_error is not None


class TestSubtractSkipToPeriod:
    """Exercises _skip_to_period in SubtractStatementParser (lines 357-365)."""

    def test_subtract_with_trailing_tokens(self):
        """SUBTRACT with extra tokens before period triggers _skip_to_period."""
        stmts, result = parse_procedure(
            "           SUBTRACT A FROM B ROUNDED."
        )
        assert any(isinstance(s, SubtractStatement) for s in stmts)
