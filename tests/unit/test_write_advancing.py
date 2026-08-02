"""Tests for WRITE ADVANCING clause parsing.

Targets uncovered lines in models/statements/io.py:
  - IOWriteStatement.set_advancing() with BEFORE/AFTER, lines, page
  - Integration tests for WRITE ... ADVANCING via parse_cobol
"""

from cobolparser import parse_cobol


def _advancing_program(clause: str) -> str:
    """Return a minimal program writing PRINT-RECORD with *clause* appended."""
    return f"""
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
               {clause}.
           CLOSE PRINT-FILE.
           STOP RUN.
        """


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

    def test_write_after_1_without_advancing_keyword(self):
        """ADVANCING is optional: WRITE ... AFTER 1 must keep the clause."""
        result = parse_cobol(_advancing_program("AFTER 1"))
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_mode == "AFTER"
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": 1,
            "unit": "LINES",
        }

    def test_write_after_1_line_without_advancing_keyword(self):
        result = parse_cobol(_advancing_program("AFTER 1 LINE"))
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": 1,
            "unit": "LINES",
        }

    def test_write_after_2_lines_without_advancing_keyword(self):
        result = parse_cobol(_advancing_program("AFTER 2 LINES"))
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": 2,
            "unit": "LINES",
        }

    def test_write_before_page_without_advancing_keyword(self):
        result = parse_cobol(_advancing_program("BEFORE PAGE"))
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_mode == "BEFORE"
        assert write.advancing_clause == {
            "type": "BEFORE",
            "value": "PAGE",
            "unit": "CHANNEL",
        }

    def test_write_after_advancing_still_parses_with_keyword(self):
        """The explicit-ADVANCING form must be unaffected by the optional path."""
        result = parse_cobol(_advancing_program("AFTER ADVANCING 2 LINES"))
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": 2,
            "unit": "LINES",
        }

    def test_write_after_advancing_mnemonic_name(self):
        """A SPECIAL-NAMES mnemonic-name (e.g. a printer channel) is a valid
        ADVANCING target and must not be misread as a line count / new
        paragraph header (`WRITE ... AFTER ADVANCING TOP-OF-PAGE.` used to
        leave "TOP-OF-PAGE." dangling, which the PROCEDURE DIVISION scanner
        then mis-parsed as a paragraph header)."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           C01 IS TOP-OF-PAGE.
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
               AFTER ADVANCING TOP-OF-PAGE.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        assert result.warnings == []
        writes = result.ast.find_all_by_type("IOWriteStatement")
        assert len(writes) == 1
        assert writes[0].advancing_clause == {
            "type": "AFTER",
            "value": "TOP-OF-PAGE",
            "unit": "MNEMONIC",
        }
        # No bogus "TOP-OF-PAGE" paragraph should have been created out of
        # the dangling mnemonic-name token.
        procedure = next(
            d
            for d in result.ast.children
            if getattr(d, "division_name", None) == "PROCEDURE"
        )
        paragraph_names = [p.paragraph_name for p in procedure.paragraphs]
        assert "TOP-OF-PAGE" not in paragraph_names

    def test_write_after_mnemonic_name_without_advancing_keyword(self):
        """ADVANCING is optional, including before a mnemonic-name."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           C01 IS TOP-OF-PAGE.
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
               AFTER TOP-OF-PAGE.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": "TOP-OF-PAGE",
            "unit": "MNEMONIC",
        }

    def test_write_before_advancing_identifier_lines(self):
        """A data-name holding a line count (followed by LINES) is captured
        as the ADVANCING identifier target, not dropped."""
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
       01  WS-LINE-COUNT PIC 9(2) VALUE 3.
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE.
           WRITE PRINT-RECORD FROM WS-LINE
               BEFORE ADVANCING WS-LINE-COUNT LINES.
           CLOSE PRINT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        assert result.warnings == []
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause == {
            "type": "BEFORE",
            "value": "WS-LINE-COUNT",
            "unit": "LINES",
        }

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
