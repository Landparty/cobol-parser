"""Tests for WRITE and CLOSE statement parser coverage.

Targets uncovered branches in:
  - write_parser.py: FROM clause, BEFORE/AFTER ADVANCING
  - close_parser.py: REEL, UNIT, WITH NO REWIND, WITH LOCK, multiple files

Notes on test strategy
----------------------
The lexer emits dedicated TokenType values for FROM, BEFORE, AFTER, WITH, and UNIT, but the
parser's FROM/ADVANCING/UNIT/WITH branches check for TokenType.IDENTIFIER.  Those branches are
therefore unreachable through a full parse_cobol() round-trip.  The tests for those specific
branches use direct parser invocation with hand-crafted Token objects (IDENTIFIER type, matching
value) so the branch coverage is exercised as proper parser-level unit tests.
"""

from cobolparser import parse_cobol
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.close_parser import CloseStatementParser
from cobolparser.parsers.statements.write_parser import WriteStatementParser

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
       01  WS-DATA   PIC X(80).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestWriteParserCoverage:
    """Cover uncovered branches in write_parser.py."""

    def test_write_minimal(self):
        """WRITE with record name only — baseline."""
        result = parse_cobol(_prog("           WRITE OUT-REC."))
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].record_name == "OUT-REC"

    def test_write_from_clause(self):
        """WRITE rec FROM src hits the FROM branch (lines 56-67).

        Direct parser test: lexer emits FROM as TokenType.FROM, but write_parser checks
        TokenType.IDENTIFIER, so we feed IDENTIFIER 'FROM' to exercise that branch.
        """
        stream = _stream(
            (TokenType.WRITE, "WRITE"),
            (TokenType.IDENTIFIER, "OUT-REC"),
            (TokenType.IDENTIFIER, "FROM"),
            (TokenType.IDENTIFIER, "WS-DATA"),
            (TokenType.PERIOD, "."),
        )
        stmt = WriteStatementParser().parse(stream)
        assert stmt.from_clause == "WS-DATA"
        assert stmt.record_name == "OUT-REC"

    def test_write_from_string_literal(self):
        """WRITE rec FROM 'literal text' -- an IBM/GnuCOBOL extension seen
        in production batch programs (e.g. legacy-application/cobol/
        GLRECON.cbl's `WRITE GLEXCPT-RECORD FROM 'GENERAL LEDGER OUT OF
        BALANCE...'`). Before the fix, a literal FROM source wasn't
        consumed at all -- the token type check only accepted IDENTIFIER --
        leaving the literal dangling and triggering a PARSE_WARNING
        ("Unparsed tokens...") on the next statement boundary."""
        result = parse_cobol(
            _prog("           WRITE OUT-REC FROM 'SOME MESSAGE TEXT'.")
        )
        assert not result.warnings
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) == 1
        assert stmts[0].from_clause == '"SOME MESSAGE TEXT"'
        assert stmts[0].record_name == "OUT-REC"

    def test_write_before_advancing(self):
        """WRITE rec BEFORE ADVANCING hits advancing branch (lines 69-87)."""
        stream = _stream(
            (TokenType.WRITE, "WRITE"),
            (TokenType.IDENTIFIER, "PRINT-REC"),
            (TokenType.IDENTIFIER, "BEFORE"),
            (TokenType.IDENTIFIER, "ADVANCING"),
            (TokenType.PERIOD, "."),
        )
        stmt = WriteStatementParser().parse(stream)
        assert stmt.advancing_mode == "BEFORE"

    def test_write_after_advancing(self):
        """WRITE rec AFTER ADVANCING hits the AFTER branch."""
        stream = _stream(
            (TokenType.WRITE, "WRITE"),
            (TokenType.IDENTIFIER, "PRINT-REC"),
            (TokenType.IDENTIFIER, "AFTER"),
            (TokenType.IDENTIFIER, "ADVANCING"),
            (TokenType.PERIOD, "."),
        )
        stmt = WriteStatementParser().parse(stream)
        assert stmt.advancing_mode == "AFTER"

    def test_write_from_and_before_advancing(self):
        """WRITE rec FROM src BEFORE ADVANCING covers combined path."""
        stream = _stream(
            (TokenType.WRITE, "WRITE"),
            (TokenType.IDENTIFIER, "PRINT-REC"),
            (TokenType.IDENTIFIER, "FROM"),
            (TokenType.IDENTIFIER, "WS-DATA"),
            (TokenType.IDENTIFIER, "BEFORE"),
            (TokenType.IDENTIFIER, "ADVANCING"),
            (TokenType.PERIOD, "."),
        )
        stmt = WriteStatementParser().parse(stream)
        assert stmt.from_clause == "WS-DATA"
        assert stmt.advancing_mode == "BEFORE"

    def test_write_from_and_after_advancing(self):
        """WRITE rec FROM src AFTER ADVANCING covers combined path."""
        stream = _stream(
            (TokenType.WRITE, "WRITE"),
            (TokenType.IDENTIFIER, "PRINT-REC"),
            (TokenType.IDENTIFIER, "FROM"),
            (TokenType.IDENTIFIER, "WS-DATA"),
            (TokenType.IDENTIFIER, "AFTER"),
            (TokenType.IDENTIFIER, "ADVANCING"),
            (TokenType.PERIOD, "."),
        )
        stmt = WriteStatementParser().parse(stream)
        assert stmt.from_clause == "WS-DATA"
        assert stmt.advancing_mode == "AFTER"


class TestCloseParserCoverage:
    """Cover uncovered branches in close_parser.py."""

    def test_close_minimal(self):
        """CLOSE file — baseline."""
        result = parse_cobol(_prog("           CLOSE SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        assert "SEQ-FILE" in stmts[0].file_names

    def test_close_reel(self):
        """CLOSE file REEL hits the REEL token branch (lines 62-65)."""
        result = parse_cobol(_prog("           CLOSE TAPE-FILE REEL."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert "TAPE-FILE" in stmt.file_names
        assert stmt.close_options["TAPE-FILE"]["reel"] is True

    def test_close_unit(self):
        """CLOSE file UNIT hits UNIT identifier branch (lines 68-71).

        Direct parser test: lexer emits UNIT as TokenType.UNIT, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TAPE-FILE"),
            (TokenType.IDENTIFIER, "UNIT"),
            (TokenType.PERIOD, "."),
        )
        stmt = CloseStatementParser().parse(stream)
        assert stmt.close_options["TAPE-FILE"]["unit"] is True

    def test_close_with_no_rewind(self):
        """CLOSE file WITH NO REWIND hits no_rewind branch (lines 73-85).

        Direct parser test: lexer emits WITH as TokenType.WITH, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "TAPE-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "NO"),
            (TokenType.IDENTIFIER, "REWIND"),
            (TokenType.PERIOD, "."),
        )
        stmt = CloseStatementParser().parse(stream)
        assert stmt.close_options["TAPE-FILE"]["no_rewind"] is True

    def test_close_with_lock(self):
        """CLOSE file WITH LOCK hits with_lock identifier path (lines 86-89).

        Direct parser test: lexer emits WITH as TokenType.WITH, not IDENTIFIER.
        """
        stream = _stream(
            (TokenType.CLOSE, "CLOSE"),
            (TokenType.IDENTIFIER, "IDX-FILE"),
            (TokenType.IDENTIFIER, "WITH"),
            (TokenType.IDENTIFIER, "LOCK"),
            (TokenType.PERIOD, "."),
        )
        stmt = CloseStatementParser().parse(stream)
        assert stmt.close_options["IDX-FILE"]["with_lock"] is True

    def test_close_multiple_files(self):
        """CLOSE with multiple file names iterates the while loop."""
        result = parse_cobol(_prog("           CLOSE FILE-A FILE-B FILE-C."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        assert len(stmts[0].file_names) >= 3
