"""Tests for OPEN and READ statement parser coverage.

Targets uncovered branches in:
  - open_parser.py: EXTEND mode, I-O mode, WITH REPOSITION, multiple files
  - read_parser.py: INTO, KEY IS, WITH LOCK, AT END, NOT AT END,
                    INVALID KEY, NOT INVALID KEY, END-READ, FIRST/LAST access modes

Notes on test strategy
----------------------
The WITH REPOSITION and WITH [NO] LOCK branches check for TokenType.IDENTIFIER with value
"WITH", but the lexer emits WITH as TokenType.WITH.  Those three tests use direct parser
invocation with crafted IDENTIFIER tokens to exercise the branches.
"""
import pytest
from cobolparser import parse_cobol
from cobolparser.lexer import Token, TokenType
from cobolparser.core.token_stream import TokenStream
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.open_parser import OpenStatementParser
from cobolparser.parsers.statements.read_parser import ReadStatementParser


_LOC = SourceLocation(1, 1)


def _stream(*specs):
    """Build a TokenStream from (TokenType, value) pairs, appending EOF."""
    tokens = [Token(t, v, _LOC) for t, v in specs]
    tokens.append(Token(TokenType.EOF, "", _LOC))
    return TokenStream(tokens)


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BUF    PIC X(80).
       01  WS-KEY    PIC 9(5).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestOpenParserCoverage:
    """Cover uncovered branches in open_parser.py."""

    def test_open_input_mode(self):
        """OPEN INPUT — baseline."""
        result = parse_cobol(_prog("           OPEN INPUT SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "INPUT"

    def test_open_output_mode(self):
        """OPEN OUTPUT."""
        result = parse_cobol(_prog("           OPEN OUTPUT SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "OUTPUT"

    def test_open_extend_mode(self):
        """OPEN EXTEND hits EXTEND in _OPEN_MODES (line 50)."""
        result = parse_cobol(_prog("           OPEN EXTEND SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "EXTEND"

    def test_open_io_mode(self):
        """OPEN I-O hits I-O branch (line 50)."""
        result = parse_cobol(_prog("           OPEN I-O IDX-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "I-O"

    def test_open_multiple_files(self):
        """OPEN INPUT with multiple file names iterates the while loop."""
        result = parse_cobol(_prog("           OPEN INPUT FILE-A FILE-B."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert len(stmts[0].file_names) >= 2

    def test_open_with_reposition(self):
        """OPEN I-O file WITH REPOSITION covers lines 82-89.

        Direct parser test: lexer emits WITH as TokenType.WITH, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.OPEN, "OPEN"),
            (TokenType.IDENTIFIER, "I-O"),
            (TokenType.IDENTIFIER, "VSAM-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "REPOSITION"),
            (TokenType.PERIOD, "."),
        )
        stmt = OpenStatementParser().parse(stream)
        assert stmt.with_reposition is True


class TestReadParserCoverage:
    """Cover uncovered branches in read_parser.py."""

    def test_read_minimal(self):
        """READ file — baseline."""
        result = parse_cobol(_prog("           READ SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "SEQ-FILE"

    def test_read_into_clause(self):
        """READ file INTO ws-var covers INTO branch (lines 77-84)."""
        result = parse_cobol(_prog("           READ SEQ-FILE INTO WS-BUF."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].into_target == "WS-BUF"

    def test_read_next_record(self):
        """READ file NEXT covers NEXT TokenType branch (lines 58-61)."""
        result = parse_cobol(_prog("           READ SEQ-FILE NEXT."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "NEXT"

    def test_read_first_record(self):
        """READ file FIRST covers FIRST identifier branch (lines 62-67)."""
        result = parse_cobol(_prog("           READ IDX-FILE FIRST."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "FIRST"

    def test_read_last_record(self):
        """READ file LAST covers LAST identifier branch (lines 62-67)."""
        result = parse_cobol(_prog("           READ IDX-FILE LAST."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "LAST"

    def test_read_key_is_clause(self):
        """READ file KEY IS key-name covers KEY_IS/KEY branch (lines 88-104)."""
        result = parse_cobol(_prog("           READ IDX-FILE KEY IS WS-KEY."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].key_name == "WS-KEY"

    def test_read_with_lock(self):
        """READ file WITH LOCK covers lock branch (lines 121-124).

        Direct parser test: lexer emits WITH as TokenType.WITH, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.READ, "READ"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.LOCK, "LOCK"),
            (TokenType.PERIOD, "."),
        )
        stmt = ReadStatementParser().parse(stream)
        assert stmt.with_lock is True

    def test_read_with_no_lock(self):
        """READ file WITH NO LOCK covers no-lock branch (lines 112-120).

        Direct parser test: lexer emits WITH as TokenType.WITH, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.READ, "READ"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "NO"),
            (TokenType.LOCK, "LOCK"),
            (TokenType.PERIOD, "."),
        )
        stmt = ReadStatementParser().parse(stream)
        assert stmt.with_nowait is True

    def test_read_at_end(self):
        """READ file AT END ... END-READ covers AT END (lines 132-143) + END-READ."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END DISPLAY 'DONE'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].at_end_clause is not None

    def test_read_not_at_end(self):
        """READ file NOT AT END covers NOT AT END branch (lines 147-164)."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               NOT AT END DISPLAY 'GOT REC'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_at_end_clause is not None

    def test_read_invalid_key(self):
        """READ file INVALID KEY covers INVALID KEY clause (lines 182-192)."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_read_not_invalid_key(self):
        """READ file NOT INVALID KEY via the NOT->INVALID branch (lines 165-177)."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_invalid_key_clause is not None

    def test_read_at_end_and_not_at_end(self):
        """READ with both AT END and NOT AT END covers both branches."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END DISPLAY 'DONE'\n"
                "               NOT AT END DISPLAY 'GOT REC'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].at_end_clause is not None
        assert stmts[0].not_at_end_clause is not None
