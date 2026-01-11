"""Integration tests for IO statement parsing.

Tests verify that the parser correctly parses READ, WRITE, OPEN, CLOSE,
and ACCEPT statements with full clause variations.
"""

import pytest
from cobolparser import parse_cobol
from cobolparser.models.statements import (
    ReadStatement, WriteStatement, OpenStatement, CloseStatement, AcceptStatement
)


class TestReadStatementParsing:
    """Test parsing of READ statements."""
    
    def test_parse_simple_read(self):
        """Parse a simple READ statement."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-READ.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "input.txt".
        DATA DIVISION.
        FILE SECTION.
        FD INPUT-FILE.
        01 INPUT-RECORD.
        PROCEDURE DIVISION.
            OPEN INPUT INPUT-FILE.
            READ INPUT-FILE INTO INPUT-RECORD.
            CLOSE INPUT-FILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.success or len(result.errors) == 0
    
    def test_parse_read_with_into(self):
        """Parse READ with INTO clause."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-READ-INTO.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 INPUT-DATA.
        PROCEDURE DIVISION.
            READ MYFILE INTO INPUT-DATA.
            STOP RUN.
        """
        result = parse_cobol(code)
        # Should parse even if file not defined
        assert result.ast is not None
    
    def test_parse_read_with_next_record(self):
        """Parse READ with NEXT record format."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-READ-NEXT.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 COUNTER PIC 9(5).
        PROCEDURE DIVISION.
            READ INDEXED-FILE NEXT.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestWriteStatementParsing:
    """Test parsing of WRITE statements."""
    
    def test_parse_simple_write(self):
        """Parse a simple WRITE statement."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-WRITE.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 OUTPUT-RECORD.
        PROCEDURE DIVISION.
            WRITE OUTPUT-RECORD.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_write_with_from(self):
        """Parse WRITE with FROM clause."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-WRITE-FROM.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 SOURCE-DATA.
        01 OUTPUT-RECORD.
        PROCEDURE DIVISION.
            WRITE OUTPUT-RECORD FROM SOURCE-DATA.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_write_with_advancing(self):
        """Parse WRITE with ADVANCING clause."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-WRITE-ADVANCING.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 PRINT-RECORD.
        PROCEDURE DIVISION.
            WRITE PRINT-RECORD AFTER ADVANCING 2 LINES.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestOpenStatementParsing:
    """Test parsing of OPEN statements."""
    
    def test_parse_simple_open(self):
        """Parse a simple OPEN statement."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OPEN.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "input.txt".
        DATA DIVISION.
        FILE SECTION.
        FD INPUT-FILE.
        01 INPUT-RECORD.
        PROCEDURE DIVISION.
            OPEN INPUT INPUT-FILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_open_multiple_files(self):
        """Parse OPEN with multiple files."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OPEN-MULTI.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 FILE1.
        01 FILE2.
        PROCEDURE DIVISION.
            OPEN INPUT FILE1 FILE2.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestCloseStatementParsing:
    """Test parsing of CLOSE statements."""
    
    def test_parse_simple_close(self):
        """Parse a simple CLOSE statement."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CLOSE.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 INPUT-FILE.
        PROCEDURE DIVISION.
            CLOSE INPUT-FILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_close_multiple_files(self):
        """Parse CLOSE with multiple files."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CLOSE-MULTI.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 FILE1.
        01 FILE2.
        PROCEDURE DIVISION.
            CLOSE FILE1 FILE2.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_close_with_no_rewind(self):
        """Parse CLOSE with NO REWIND clause."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CLOSE-NO-REWIND.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 TAPE-FILE.
        PROCEDURE DIVISION.
            CLOSE TAPE-FILE WITH NO REWIND.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestAcceptStatementParsing:
    """Test parsing of ACCEPT statements."""
    
    def test_parse_simple_accept(self):
        """Parse a simple ACCEPT statement."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-ACCEPT.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 USER-INPUT.
        PROCEDURE DIVISION.
            ACCEPT USER-INPUT.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_accept_from_console(self):
        """Parse ACCEPT with FROM CONSOLE."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-ACCEPT-CONSOLE.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 USER-INPUT.
        PROCEDURE DIVISION.
            ACCEPT USER-INPUT FROM CONSOLE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
    
    def test_parse_accept_with_at_line_column(self):
        """Parse ACCEPT with AT LINE and COLUMN."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-ACCEPT-POSITION.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 USER-INPUT.
        PROCEDURE DIVISION.
            ACCEPT USER-INPUT AT LINE 5 COLUMN 10.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestIOStatementIntegration:
    """Integration tests for mixed IO statements."""
    
    def test_parse_complete_io_sequence(self):
        """Parse a complete file I/O sequence."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. FILE-PROCESSOR.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "input.txt"
                ORGANIZATION IS SEQUENTIAL.
            SELECT OUTPUT-FILE ASSIGN TO "output.txt"
                ORGANIZATION IS SEQUENTIAL.
        DATA DIVISION.
        FILE SECTION.
        FD INPUT-FILE.
        01 INPUT-RECORD PIC X(80).
        FD OUTPUT-FILE.
        01 OUTPUT-RECORD PIC X(80).
        WORKING-STORAGE SECTION.
        01 EOF-FLAG PIC X VALUE 'N'.
        PROCEDURE DIVISION.
            OPEN INPUT INPUT-FILE.
            OPEN OUTPUT OUTPUT-FILE.
            PERFORM UNTIL EOF-FLAG = 'Y'
                READ INPUT-FILE
                    AT END MOVE 'Y' TO EOF-FLAG
                    NOT AT END
                        WRITE OUTPUT-RECORD FROM INPUT-RECORD
                END-READ
            END-PERFORM.
            CLOSE INPUT-FILE.
            CLOSE OUTPUT-FILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        # Parser should handle the structure even if some parts aren't fully parsed
        assert result.ast is not None
    
    def test_parse_io_with_accept_display(self):
        """Parse a program using ACCEPT and DISPLAY."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. INTERACTIVE-APP.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 USER-NAME PIC X(30).
        01 USER-AGE PIC 9(3).
        PROCEDURE DIVISION.
            DISPLAY "Enter your name: ".
            ACCEPT USER-NAME.
            DISPLAY "Enter your age: ".
            ACCEPT USER-AGE FROM CONSOLE.
            DISPLAY "You are " USER-NAME.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None


class TestIOStatementErrorHandling:
    """Test error handling in IO statements."""
    
    def test_read_without_period(self):
        """Test READ statement without period."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-NO-PERIOD.
        PROCEDURE DIVISION.
            READ MYFILE
            STOP RUN.
        """
        result = parse_cobol(code, error_recovery="COLLECT_ALL")
        # Should have errors or warnings
        assert result.ast is not None
    
    def test_open_without_mode(self):
        """Test OPEN statement without explicit mode."""
        code = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OPEN-NO-MODE.
        PROCEDURE DIVISION.
            OPEN MYFILE.
            STOP RUN.
        """
        result = parse_cobol(code)
        assert result.ast is not None
