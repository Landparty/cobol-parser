"""Tests for START statement parser coverage.

Targets uncovered lines in parsers/statements/start_parser.py (77.70%):
  - Complex KEY conditions (GREATER THAN, NOT LESS THAN, etc.)
  - INVALID KEY and NOT INVALID KEY clauses
  - Missing file name handling
  - END-START and period consumption
"""

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.start_parser import StartStatementParser


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO 'CUST.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-RECORD.
           05  CUST-KEY    PIC X(10).
           05  CUST-NAME   PIC X(30).
       WORKING-STORAGE SECTION.
       01  WS-STATUS PIC XX.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestStartKeyConditions:
    """Cover KEY condition parsing (lines 76-137)."""

    def test_start_key_equal(self):
        result = parse_cobol(
            _prog("           START CUST-FILE KEY IS EQUAL TO CUST-KEY.")
        )
        assert result.ast is not None

    def test_start_key_greater_than(self):
        result = parse_cobol(
            _prog("           START CUST-FILE KEY IS GREATER THAN CUST-KEY.")
        )
        assert result.ast is not None

    def test_start_key_not_less_than(self):
        result = parse_cobol(
            _prog("           START CUST-FILE KEY IS NOT LESS THAN CUST-KEY.")
        )
        assert result.ast is not None

    def test_start_key_greater_than_or_equal(self):
        result = parse_cobol(
            _prog("           START CUST-FILE KEY IS GREATER THAN OR EQUAL CUST-KEY.")
        )
        assert result.ast is not None

    def test_start_key_less(self):
        result = parse_cobol(_prog("           START CUST-FILE KEY IS LESS CUST-KEY."))
        assert result.ast is not None

    def test_start_key_equals(self):
        """EQUALS (with S) variant."""
        result = parse_cobol(
            _prog("           START CUST-FILE KEY IS EQUALS CUST-KEY.")
        )
        assert result.ast is not None

    def test_start_basic_no_key(self):
        result = parse_cobol(_prog("           START CUST-FILE."))
        assert result.ast is not None


class TestStartInvalidKey:
    """Cover INVALID KEY / NOT INVALID KEY clauses (lines 140-166)."""

    def test_start_invalid_key(self):
        result = parse_cobol(
            _prog(
                "           START CUST-FILE KEY IS EQUAL TO CUST-KEY\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'."
            )
        )
        assert result.ast is not None

    def test_start_not_invalid_key(self):
        result = parse_cobol(
            _prog(
                "           START CUST-FILE KEY IS EQUAL TO CUST-KEY\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'."
            )
        )
        assert result.ast is not None

    def test_start_both_invalid_key_clauses(self):
        result = parse_cobol(
            _prog(
                "           START CUST-FILE KEY IS EQUAL TO CUST-KEY\n"
                "               INVALID KEY DISPLAY 'ERR'\n"
                "               NOT INVALID KEY DISPLAY 'OK'."
            )
        )
        assert result.ast is not None


class TestStartEndStart:
    """Cover END-START and period consumption (lines 168-182)."""

    def test_start_with_end_start(self):
        result = parse_cobol(
            _prog(
                "           START CUST-FILE KEY IS EQUAL TO CUST-KEY\n"
                "           END-START."
            )
        )
        assert result.ast is not None


class TestStartParserDirect:
    """Direct unit tests for StartStatementParser edge cases."""

    def test_matches_exception(self):
        """matches() returns False on exception."""
        from unittest.mock import MagicMock

        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = StartStatementParser()
        assert parser.matches(mock_stream) is False

    def test_matches_none_token(self):
        """matches() returns False for empty stream."""
        tokens = []
        stream = TokenStream(tokens)
        parser = StartStatementParser()
        assert parser.matches(stream) is False

    def test_parse_missing_file_name(self):
        """parse() returns early when file name is missing (line 65)."""
        tokens = [
            _make_token(TokenType.START, "START"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        parser = StartStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.file_name is None
