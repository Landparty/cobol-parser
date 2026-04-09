"""Tests for EXEC CICS and EXEC SQL parser coverage.

Targets uncovered lines in parsers/statements/ibm_exec_statements.py (63.16%):
  - EXEC CICS parse loop (lines 164-192)
  - EXEC SQL host variable concatenation (lines 92-119)
  - Exception handling in matches() methods
"""

from unittest.mock import MagicMock

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatementParser,
    ExecSqlStatementParser,
)


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


class TestExecCicsParsing:
    """Cover EXEC CICS parse loop (lines 164-192)."""

    def test_exec_cics_simple(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSPROG.
       PROCEDURE DIVISION.
           EXEC CICS
               SEND MAP('MENUMAP')
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_receive(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSPROG.
       PROCEDURE DIVISION.
           EXEC CICS
               RECEIVE INTO(WS-BUFFER)
               LENGTH(WS-LEN)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_with_multiple_commands(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSPROG.
       PROCEDURE DIVISION.
           EXEC CICS
               SEND MAP('MAP1') MAPSET('MSET1')
               ERASE
           END-EXEC.
           EXEC CICS
               RETURN TRANSID('TRN1')
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_cics_parser_direct(self):
        """Exercise the ExecCicsStatementParser.parse() method directly."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.IDENTIFIER, "CICS"),
            _make_token(TokenType.IDENTIFIER, "SEND"),
            _make_token(TokenType.IDENTIFIER, "MAP"),
            _make_token(TokenType.IDENTIFIER, "END-EXEC"),
        ]
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        result = parser.parse(stream)
        assert result is not None
        assert result.node_type == "EXEC_CICS"

    def test_exec_cics_parser_empty_body(self):
        """EXEC CICS END-EXEC with no commands between."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.IDENTIFIER, "CICS"),
            _make_token(TokenType.IDENTIFIER, "END-EXEC"),
        ]
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        result = parser.parse(stream)
        assert result is not None

    def test_exec_cics_matches_with_exec_identifier(self):
        """matches() when EXEC is an IDENTIFIER token."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "EXEC"),
            _make_token(TokenType.IDENTIFIER, "CICS"),
        ]
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        assert parser.matches(stream) is True

    def test_exec_cics_matches_false_for_sql(self):
        """matches() should be False when second token is SQL."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.SQL, "SQL"),
        ]
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        assert parser.matches(stream) is False

    def test_exec_cics_matches_exception(self):
        """matches() returns False when exception is raised."""
        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = ExecCicsStatementParser()
        assert parser.matches(mock_stream) is False

    def test_exec_cics_matches_none_token(self):
        """matches() returns False when peek returns None."""
        tokens = []
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        assert parser.matches(stream) is False

    def test_exec_cics_matches_no_second_token(self):
        """matches() returns False when only one token exists."""
        tokens = [_make_token(TokenType.EXEC, "EXEC")]
        stream = TokenStream(tokens)
        parser = ExecCicsStatementParser()
        assert parser.matches(stream) is False


class TestExecSqlHostVariables:
    """Cover EXEC SQL host variable and punctuation handling (lines 92-119)."""

    def test_exec_sql_with_host_variable(self):
        """SQL with :HOST-VAR syntax exercises colon concatenation."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEE
               WHERE EMP-ID = :WS-ID
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_exec_sql_parser_direct_with_host_vars(self):
        """Direct parse with colon tokens to exercise colon concatenation."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.SQL, "SQL"),
            _make_token(TokenType.IDENTIFIER, "SELECT"),
            _make_token(TokenType.IDENTIFIER, "NAME"),
            _make_token(TokenType.IDENTIFIER, "INTO"),
            _make_token(TokenType.COLON, ":"),
            _make_token(TokenType.IDENTIFIER, "WS-NAME"),
            _make_token(TokenType.IDENTIFIER, "FROM"),
            _make_token(TokenType.IDENTIFIER, "EMPLOYEE"),
            _make_token(TokenType.END_EXEC, "END-EXEC"),
        ]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        result = parser.parse(stream)
        assert result is not None

    def test_exec_sql_with_comma_punctuation(self):
        """SQL with comma handling in column list."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.SQL, "SQL"),
            _make_token(TokenType.IDENTIFIER, "SELECT"),
            _make_token(TokenType.IDENTIFIER, "A"),
            _make_token(TokenType.COMMA, ","),
            _make_token(TokenType.IDENTIFIER, "B"),
            _make_token(TokenType.IDENTIFIER, "FROM"),
            _make_token(TokenType.IDENTIFIER, "TBL"),
            _make_token(TokenType.END_EXEC, "END-EXEC"),
        ]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        result = parser.parse(stream)
        assert result is not None

    def test_exec_sql_matches_exception(self):
        """matches() returns False when exception is raised."""
        mock_stream = MagicMock()
        mock_stream.peek = MagicMock(side_effect=RuntimeError("fail"))
        parser = ExecSqlStatementParser()
        assert parser.matches(mock_stream) is False

    def test_exec_sql_matches_none_token(self):
        """matches() returns False when peek returns None."""
        tokens = []
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        assert parser.matches(stream) is False

    def test_exec_sql_matches_no_second_token(self):
        """matches() returns False with only EXEC token."""
        tokens = [_make_token(TokenType.EXEC, "EXEC")]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        assert parser.matches(stream) is False

    def test_exec_sql_matches_identifier_exec(self):
        """matches() when EXEC is IDENTIFIER type."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "EXEC"),
            _make_token(TokenType.IDENTIFIER, "SQL"),
        ]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        assert parser.matches(stream) is True

    def test_exec_sql_matches_wrong_second_token(self):
        """matches() returns False when second token is not SQL."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.IDENTIFIER, "NOTQL"),
        ]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        assert parser.matches(stream) is False

    def test_exec_sql_end_exec_as_identifier(self):
        """Parse EXEC SQL...END-EXEC where END-EXEC is an IDENTIFIER."""
        tokens = [
            _make_token(TokenType.EXEC, "EXEC"),
            _make_token(TokenType.SQL, "SQL"),
            _make_token(TokenType.IDENTIFIER, "SELECT"),
            _make_token(TokenType.IDENTIFIER, "1"),
            _make_token(TokenType.IDENTIFIER, "END-EXEC"),
        ]
        stream = TokenStream(tokens)
        parser = ExecSqlStatementParser()
        result = parser.parse(stream)
        assert result is not None
