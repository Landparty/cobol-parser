"""Tests for ENTRY statement USING clause parsing coverage.

Targets uncovered lines in parsers/statements/entry_parser.py (78.57%):
  - Exception handling in matches() (lines 32, 35-36)
  - Missing entry name errors (lines 67, 71, 88)
  - USING clause parameter list parsing (lines 113-155)
"""

from unittest.mock import MagicMock

import pytest

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.entry_parser import EntryStatementParser


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


class TestEntryParserMatchesEdgeCases:
    """Cover matches() edge cases."""

    def test_matches_exception_returns_false(self):
        """matches() returns False when exception raised (line 35-36)."""
        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = EntryStatementParser()
        assert parser.matches(mock_stream) is False

    def test_matches_none_token(self):
        """matches() returns False for empty stream (line 31-32)."""
        tokens = []
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        assert parser.matches(stream) is False

    def test_matches_empty_value(self):
        """matches() returns False when token value is empty."""
        tokens = [_make_token(TokenType.IDENTIFIER, "")]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        assert parser.matches(stream) is False

    def test_matches_true(self):
        """matches() returns True for ENTRY keyword."""
        tokens = [_make_token(TokenType.IDENTIFIER, "ENTRY")]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        assert parser.matches(stream) is True


class TestEntryParserMissingName:
    """Cover missing entry name error paths (lines 67, 71, 88)."""

    def test_parse_entry_empty_after_entry(self):
        """Empty stream after ENTRY raises ValueError (line 66-67)."""
        tokens = [_make_token(TokenType.IDENTIFIER, "ENTRY")]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        with pytest.raises(ValueError, match="ENTRY statement requires a name"):
            parser.parse(stream)

    def test_parse_entry_empty_value_raises(self):
        """Entry name with empty value raises ValueError (line 87-88)."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.IDENTIFIER, ""),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        with pytest.raises(ValueError, match="ENTRY statement requires a name"):
            parser.parse(stream)


class TestEntryParserUsingClause:
    """Cover USING clause parameter list parsing (lines 113-155)."""

    def test_parse_entry_with_using_parameters(self):
        """ENTRY with USING clause and multiple parameters."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.IDENTIFIER, "USING"),
            _make_token(TokenType.IDENTIFIER, "WS-PARAM1"),
            _make_token(TokenType.IDENTIFIER, "WS-PARAM2"),
            _make_token(TokenType.IDENTIFIER, "WS-PARAM3"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert len(result.using_parameters) == 3

    def test_parse_entry_using_with_newlines(self):
        """USING parameters separated by NEWLINE tokens — tests whitespace skip."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.IDENTIFIER, "USING"),
            _make_token(TokenType.NEWLINE, "\n"),
            _make_token(TokenType.IDENTIFIER, "PARAM-A"),
            _make_token(TokenType.NEWLINE, "\n"),
            _make_token(TokenType.IDENTIFIER, "PARAM-B"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert len(result.using_parameters) >= 2

    def test_parse_entry_using_stops_at_period(self):
        """USING parsing stops at period."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.IDENTIFIER, "USING"),
            _make_token(TokenType.IDENTIFIER, "PARAM-A"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert len(result.using_parameters) == 1

    def test_parse_entry_using_stops_at_by(self):
        """USING parsing stops at BY keyword."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.IDENTIFIER, "USING"),
            _make_token(TokenType.IDENTIFIER, "PARAM-A"),
            _make_token(TokenType.IDENTIFIER, "BY"),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert len(result.using_parameters) == 1

    def test_parse_entry_identifier_name(self):
        """Entry name as IDENTIFIER (not string literal) — line 79-81."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.IDENTIFIER, "SUBPROG"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.entry_name == "SUBPROG"

    def test_parse_entry_other_token_type_name(self):
        """Entry name from non-standard token type — line 83-85."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.NUMERIC_LITERAL, "12345"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.entry_name == "12345"

    def test_parse_entry_no_using(self):
        """ENTRY without USING clause."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert len(result.using_parameters) == 0

    def test_parse_entry_using_non_identifier_param(self):
        """USING with non-identifier token — line 153-155."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "ENTRY"),
            _make_token(TokenType.STRING_LITERAL, "'SUBPROG'"),
            _make_token(TokenType.IDENTIFIER, "USING"),
            _make_token(TokenType.NUMERIC_LITERAL, "100"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = EntryStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert "100" in result.using_parameters


class TestEntryIntegration:
    """Integration tests via parse_cobol."""

    def test_entry_with_using_in_program(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARAM PIC X(10).
       PROCEDURE DIVISION.
           ENTRY 'SUBENTRY' USING WS-PARAM.
           STOP RUN.
        """)
        assert result.ast is not None
