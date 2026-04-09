"""Tests for GO TO parser edge cases and DEPENDING ON clause.

Targets uncovered lines in parsers/statements/go_parser.py (73.33%):
  - Exception in matches() (line 40-41)
  - Missing TO keyword error (lines 72-75)
  - Missing target paragraph error (lines 88-98)
  - DEPENDING ON clause edge cases (lines 126-156)
"""

from unittest.mock import MagicMock

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.go_parser import GoStatementParser


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


class TestGoParserEdgeCases:
    """Cover uncovered edge cases in go_parser.py."""

    def test_matches_exception_returns_false(self):
        """matches() returns False when peek raises an exception (line 40-41)."""
        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = GoStatementParser()
        assert parser.matches(mock_stream) is False

    def test_matches_none_token_returns_false(self):
        """matches() returns False when stream is empty."""
        tokens = []
        stream = TokenStream(tokens)
        parser = GoStatementParser()
        assert parser.matches(stream) is False

    def test_matches_non_go_token(self):
        """matches() returns False for non-GO token."""
        tokens = [_make_token(TokenType.IDENTIFIER, "MOVE")]
        stream = TokenStream(tokens)
        parser = GoStatementParser()
        assert parser.matches(stream) is False

    def test_matches_null_value_token(self):
        """matches() returns False when token value is None."""
        tokens = [_make_token(TokenType.IDENTIFIER, "")]
        stream = TokenStream(tokens)
        parser = GoStatementParser()
        assert parser.matches(stream) is False

    def test_parse_go_missing_to_empty_stream(self):
        """GO followed by nothing — covers line 71-75 (empty stream after GO)."""
        tokens = [_make_token(TokenType.IDENTIFIER, "GO")]
        stream = TokenStream(tokens)
        # Attach a context so error reporting works
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.target_paragraph is None

    def test_parse_go_to_missing_target_empty(self):
        """GO TO followed by nothing — covers lines 87-91."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.target_paragraph is None

    def test_parse_go_to_with_null_value_target(self):
        """GO TO followed by token with empty value — covers lines 93-98."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, ""),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result is not None

    def test_parse_go_wrong_keyword_after_go(self):
        """GO followed by non-TO keyword — covers line 78-82."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "SOMEWHERE"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result is not None


class TestGoDependingOnEdgeCases:
    """Cover DEPENDING ON clause edge cases (lines 125-156)."""

    def test_depending_on_empty_after_target(self):
        """No DEPENDING keyword after target — returns normally (line 125)."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        assert result.depending_on_variable is None

    def test_depending_without_on(self):
        """DEPENDING not followed by ON — returns without variable (line 137)."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "DEPENDING"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"

    def test_depending_on_without_variable(self):
        """DEPENDING ON with empty stream after — covers line 146-147."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "DEPENDING"),
            _make_token(TokenType.IDENTIFIER, "ON"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        assert result.depending_on_variable is None

    def test_depending_on_with_period_as_variable(self):
        """DEPENDING ON followed by period — should not set variable (line 154)."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "DEPENDING"),
            _make_token(TokenType.IDENTIFIER, "ON"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        # period is consumed as variable name "." which is filtered by var_name != "."
        assert result.depending_on_variable is None

    def test_depending_on_with_variable(self):
        """DEPENDING ON with a valid variable name."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "DEPENDING"),
            _make_token(TokenType.IDENTIFIER, "ON"),
            _make_token(TokenType.IDENTIFIER, "WS-IDX"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        assert result.depending_on_variable == "WS-IDX"

    def test_depending_on_non_depending_keyword(self):
        """Token after target is not DEPENDING — returns without clause (line 129)."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "SOMETHING-ELSE"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        assert result.depending_on_variable is None

    def test_depending_on_wrong_word_after_depending(self):
        """DEPENDING followed by non-ON keyword — covers line 140-141."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "GO"),
            _make_token(TokenType.IDENTIFIER, "TO"),
            _make_token(TokenType.IDENTIFIER, "PARA-1"),
            _make_token(TokenType.IDENTIFIER, "DEPENDING"),
            _make_token(TokenType.IDENTIFIER, "WRONG"),
        ]
        stream = TokenStream(tokens)
        stream.context = None
        parser = GoStatementParser()
        result = parser.parse(stream)
        assert result.target_paragraph == "PARA-1"
        assert result.depending_on_variable is None


class TestGoFullProgramIntegration:
    """Integration tests for GO TO via parse_cobol."""

    def test_go_to_depending_on_full_program(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX  PIC 9 VALUE 1.
       PROCEDURE DIVISION.
           GO TO PARA-1 DEPENDING ON WS-IDX.
           STOP RUN.
        """)
        assert result.ast is not None
        stmts = result.ast.find_statements("GOTO")
        assert len(stmts) >= 1
        assert stmts[0].depending_on_variable == "WS-IDX"

    def test_go_missing_to_error_recovery(self):
        """GO without TO in error-recovery mode."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           GO PARA-1.
           STOP RUN.
        """)
        assert result is not None
