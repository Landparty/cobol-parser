"""Tests for WRITE ADVANCING clause parsing.

Targets uncovered lines in models/statements/io.py:
  - IOWriteStatement.set_advancing() with BEFORE/AFTER, lines, page
  - Integration tests for WRITE ... ADVANCING via parse_cobol
"""

from cobolparser import parse_cobol


class TestWriteAdvancingIntegration:
    """Cover WRITE ... ADVANCING via full program parsing."""

    def test_write_after_advancing_lines(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO 'PRINT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-LINE PIC X(80) VALUE 'HELLO WORLD'.
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE.
           WRITE PRINT-RECORD FROM WS-LINE
               AFTER ADVANCING 2 LINES.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_write_before_advancing_page(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO 'PRINT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-LINE PIC X(80) VALUE 'HELLO'.
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE.
           WRITE PRINT-RECORD FROM WS-LINE
               BEFORE ADVANCING PAGE.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_write_after_advancing_1_line(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO 'PRINT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-LINE PIC X(80) VALUE 'HELLO'.
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE.
           WRITE PRINT-RECORD FROM WS-LINE
               AFTER ADVANCING 1.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_write_from_without_advancing(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-DATA PIC X(80) VALUE 'TEST DATA'.
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE.
           WRITE OUT-RECORD FROM WS-DATA.
           CLOSE OUT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
