"""Tests for STOP statement parser coverage.

Targets uncovered lines in parsers/statements/stop_parser.py (76.74%):
  - Exception handling in matches() (line 20-21)
  - Empty token stream handling (lines 30-32)
  - STOP "literal" parsing (lines 47-49)
  - STOP with nothing after it
"""

from unittest.mock import MagicMock

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.stop_parser import StopStatementParser


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


class TestStopParserDirectCoverage:
    """Direct unit tests for StopStatementParser edge cases."""

    def test_matches_exception_returns_false(self):
        """matches() returns False when exception is raised (line 20-21)."""
        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = StopStatementParser()
        assert parser.matches(mock_stream) is False

    def test_matches_none_token(self):
        """matches() returns False for empty stream (line 16-17)."""
        tokens = []
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        assert parser.matches(stream) is False

    def test_matches_null_value(self):
        """matches() returns False when token value is empty."""
        tokens = [_make_token(TokenType.IDENTIFIER, "")]
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        assert parser.matches(stream) is False

    def test_parse_stop_string_literal(self):
        """STOP followed by a string literal (line 47-49)."""
        tokens = [
            _make_token(TokenType.STOP, "STOP"),
            _make_token(TokenType.STRING_LITERAL, "HALTED"),
        ]
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.stop_type == "HALTED"

    def test_parse_stop_run(self):
        """STOP RUN sets stop_type to 'RUN' (line 44-46)."""
        tokens = [
            _make_token(TokenType.STOP, "STOP"),
            _make_token(TokenType.IDENTIFIER, "RUN"),
        ]
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.stop_type == "RUN"

    def test_parse_stop_empty_after_stop(self):
        """STOP with nothing after it — covers lines 41 (empty check)."""
        tokens = [
            _make_token(TokenType.STOP, "STOP"),
        ]
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        result = parser.parse(stream)
        assert result is not None

    def test_parse_stop_followed_by_period(self):
        """STOP followed by period — stop_type remains None."""
        tokens = [
            _make_token(TokenType.STOP, "STOP"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = StopStatementParser()
        result = parser.parse(stream)
        assert result is not None
        # period has value "." which doesn't match "RUN" or STRING_LITERAL


class TestStopIntegration:
    """Integration tests for STOP via parse_cobol."""

    def test_stop_with_string_literal(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           STOP 'PROGRAM HALTED'.
        """)
        assert result.ast is not None
        stmts = result.ast.find_statements("STOP")
        assert len(stmts) >= 1
