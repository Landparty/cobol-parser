"""Tests for arithmetic statement SIZE ERROR clause coverage.

Targets uncovered lines in parsers/statements/arithmetic_parsers.py (79.32%):
  - ON SIZE ERROR and NOT ON SIZE ERROR nested statement blocks
  - ROUNDED phrase handling
  - GIVING clause across MULTIPLY/DIVIDE/COMPUTE
  - _skip_to_period error handling
"""

from cobolparser import parse_cobol


class TestAddSizeError:
    """Cover ADD statement ON SIZE ERROR clauses."""

    def test_add_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 1.
       01  WS-ERR PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B
               ON SIZE ERROR
                   MOVE 'Y' TO WS-ERR
           END-ADD.
           STOP RUN.
        """)
        assert result.ast is not None
        adds = result.ast.find_statements("ADD")
        assert len(adds) >= 1

    def test_add_not_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 1.
       01  WS-B PIC 9(3) VALUE 2.
       01  WS-OK PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B
               NOT ON SIZE ERROR
                   MOVE 'Y' TO WS-OK
           END-ADD.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_add_both_size_error_clauses(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 1.
       01  WS-FLAG PIC X.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B
               ON SIZE ERROR
                   MOVE 'E' TO WS-FLAG
               NOT ON SIZE ERROR
                   MOVE 'S' TO WS-FLAG
           END-ADD.
           STOP RUN.
        """)
        assert result.ast is not None


class TestSubtractSizeError:
    """Cover SUBTRACT statement SIZE ERROR."""

    def test_subtract_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
           SUBTRACT WS-A FROM WS-B
               ON SIZE ERROR
                   DISPLAY 'OVERFLOW'
           END-SUBTRACT.
           STOP RUN.
        """)
        assert result.ast is not None


class TestMultiplySizeError:
    """Cover MULTIPLY statement SIZE ERROR and GIVING clause."""

    def test_multiply_giving_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           MULTIPLY WS-A BY WS-B GIVING WS-C
               ON SIZE ERROR
                   DISPLAY 'OVERFLOW'
           END-MULTIPLY.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_multiply_basic(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 5.
       01  WS-B PIC 9(3) VALUE 10.
       PROCEDURE DIVISION.
           MULTIPLY WS-A BY WS-B.
           STOP RUN.
        """)
        assert result.ast is not None


class TestDivideSizeError:
    """Cover DIVIDE statement SIZE ERROR and GIVING/REMAINDER clauses."""

    def test_divide_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           DIVIDE WS-A INTO WS-B GIVING WS-C
               ON SIZE ERROR
                   DISPLAY 'OVERFLOW'
           END-DIVIDE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_divide_by_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 100.
       01  WS-B PIC 9(3) VALUE 3.
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           DIVIDE WS-A BY WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None


class TestComputeSizeError:
    """Cover COMPUTE statement SIZE ERROR and expression parsing."""

    def test_compute_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-C = WS-A * WS-B
               ON SIZE ERROR
                   DISPLAY 'OVERFLOW'
           END-COMPUTE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_not_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-C = WS-A + WS-B
               NOT ON SIZE ERROR
                   DISPLAY 'OK'
           END-COMPUTE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_rounded(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3)V99.
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
           COMPUTE WS-B ROUNDED = WS-A / 3.
           STOP RUN.
        """)
        assert result.ast is not None


class TestAddGiving:
    """Cover ADD ... GIVING clause."""

    def test_add_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 10.
       01  WS-B PIC 9(3) VALUE 20.
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
           ADD WS-A WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None
