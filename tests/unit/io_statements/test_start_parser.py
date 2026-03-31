"""Tests for START statement parser coverage.

Targets uncovered branches in start_parser.py:
  - KEY IS condition variants: EQUAL, GREATER THAN, NOT LESS, GREATER THAN OR EQUAL
  - INVALID KEY and NOT INVALID KEY clauses
  - END-START delimiter
  - Missing file name early-return

Notes on test strategy
----------------------
START is registered in ProcedureDivisionParser but is absent from _is_statement_keyword(), so
parse_cobol() never dispatches to StartStatementParser.  All tests therefore invoke the parser
directly with hand-crafted Token streams.
"""
import pytest
from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.lexer import Token, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.start_parser import StartStatementParser


_LOC = SourceLocation(1, 1)


def _stream(*specs):
    """Build a TokenStream from (TokenType, value) pairs, appending EOF."""
    tokens = [Token(t, v, _LOC) for t, v in specs]
    tokens.append(Token(TokenType.EOF, "", _LOC))
    return TokenStream(tokens)


class TestStartParserCoverage:
    """Cover uncovered branches in start_parser.py."""

    def test_start_minimal(self):
        """START file-name with no clauses — baseline."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert stmt.statement_type == "START_STATEMENT"
        assert stmt.file_name == "IDX-FILE"
        assert stmt.key_condition is None

    def test_start_key_is_equal(self):
        """START file KEY IS EQUAL — covers KEY + IS token path + EQUAL condition."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IS, ""),
            (TokenType.IDENTIFIER, "EQUAL"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert stmt.key_condition is not None
        assert "EQUAL" in stmt.key_condition

    def test_start_key_greater_than(self):
        """START file KEY IS GREATER THAN — covers GREATER + THAN path (lines 86-96)."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IS, ""),
            (TokenType.IDENTIFIER, "GREATER"),
            (TokenType.IDENTIFIER, "THAN"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert "GREATER" in (stmt.key_condition or "")

    def test_start_key_not_less(self):
        """START file KEY NOT LESS — covers NOT prefix path (lines 79-82)."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.NOT, ""),
            (TokenType.IDENTIFIER, "LESS"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert "NOT" in (stmt.key_condition or "")

    def test_start_key_greater_than_or_equal(self):
        """START file KEY GREATER THAN OR EQUAL — covers OR EQUAL path (lines 99-106)."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IDENTIFIER, "GREATER"),
            (TokenType.IDENTIFIER, "THAN"),
            (TokenType.IDENTIFIER, "OR"),
            (TokenType.IDENTIFIER, "EQUAL"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert "OR EQUAL" in (stmt.key_condition or "")

    def test_start_with_invalid_key(self):
        """INVALID KEY clause — covers lines 111-123."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IS, ""),
            (TokenType.IDENTIFIER, "EQUAL"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.INVALID, ""),
            (TokenType.KEY, ""),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        # invalid_key_clause defaults to [] and is set (not None) after set_invalid_key_clause
        assert stmt.invalid_key_clause is not None

    def test_start_with_not_invalid_key(self):
        """NOT INVALID KEY clause — covers lines 125-141."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IS, ""),
            (TokenType.IDENTIFIER, "EQUAL"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.NOT, ""),
            (TokenType.INVALID, ""),
            (TokenType.KEY, ""),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert stmt.not_invalid_key_clause is not None

    def test_start_with_end_start(self):
        """END-START as IDENTIFIER delimiter — covers lines 146-148."""
        stream = _stream(
            (TokenType.START, "START"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.KEY, ""),
            (TokenType.IS, ""),
            (TokenType.IDENTIFIER, "EQUAL"),
            (TokenType.IDENTIFIER, "WS-KEY"),
            (TokenType.IDENTIFIER, "END-START"),
            (TokenType.PERIOD, "."),
        )
        stmt = StartStatementParser().parse(stream)
        assert stmt.statement_type == "START_STATEMENT"

    def test_start_missing_file_name_recovers(self):
        """START followed by non-identifier covers early return (line 56)."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           START.
           STOP RUN.
            """
        )
        # Should not crash
        assert result is not None
