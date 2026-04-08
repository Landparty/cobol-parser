"""Tests for ENTRY statement parser USING clause coverage.

Targets uncovered lines in parsers/statements/entry_parser.py (75.51%):
  - _parse_using_clause() parameter list parsing
  - Entry name extraction across different token types
"""

from cobolparser import parse_cobol


class TestEntryUsingClause:
    """Cover ENTRY statement USING clause parsing."""

    def test_entry_with_using_parameters(self):
        """ENTRY with USING clause covers _parse_using_clause (lines 102-155)."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  PARAM-A PIC X(10).
       01  PARAM-B PIC X(10).
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING PARAM-A PARAM-B.
           STOP RUN.
        """)
        assert result.ast is not None
        stmts = result.ast.find_statements("ENTRY")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.entry_name == "DLITCBL"
        assert len(stmt.using_parameters) >= 1

    def test_entry_without_using(self):
        """ENTRY without USING clause — just an entry name."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYTEST.
       PROCEDURE DIVISION.
           ENTRY 'MYENTRY'.
           STOP RUN.
        """)
        assert result.ast is not None
        stmts = result.ast.find_statements("ENTRY")
        assert len(stmts) >= 1
        assert stmts[0].entry_name == "MYENTRY"

    def test_entry_with_multiple_parameters(self):
        """ENTRY with many USING parameters."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  P1 PIC X(10).
       01  P2 PIC X(10).
       01  P3 PIC X(10).
       PROCEDURE DIVISION.
           ENTRY 'MULTI' USING P1 P2 P3.
           STOP RUN.
        """)
        assert result.ast is not None
        stmts = result.ast.find_statements("ENTRY")
        assert len(stmts) >= 1

    def test_entry_identifier_name(self):
        """ENTRY with identifier (not string literal) entry name."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ENTRY-NAME PIC X(8) VALUE 'MYENTRY'.
       PROCEDURE DIVISION.
           ENTRY ENTRY-NAME.
           STOP RUN.
        """)
        assert result.ast is not None
