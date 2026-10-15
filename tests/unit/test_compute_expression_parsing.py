"""Tests for COMPUTE expression parsing coverage.

Targets uncovered lines in parsers/statements/arithmetic_parsers.py:
  - COMPUTE expression parsing with parentheses, operators, and terminators
  - ROUNDED phrase handling
  - ON SIZE ERROR / NOT ON SIZE ERROR with nested DISPLAY and MOVE
  - _skip_to_period for COMPUTE
"""

from cobolparser import parse_cobol


class TestComputeExpressionParsing:
    """Cover COMPUTE expression engine (lines 540-595 in arithmetic_parsers.py)."""

    def test_compute_simple_addition(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 10.
       01  WS-B PIC 9(3) VALUE 20.
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
           COMPUTE WS-C = WS-A + WS-B.
           STOP RUN.
        """)
        assert result.ast is not None
        computes = result.ast.find_statements("COMPUTE")
        assert len(computes) >= 1

    def test_compute_parenthesized_expression(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 5.
       01  WS-B PIC 9(3) VALUE 3.
       01  WS-C PIC 9(3) VALUE 2.
       01  WS-R PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-R = (WS-A + WS-B) * WS-C.
           STOP RUN.
        """)
        assert result.ast is not None
        computes = result.ast.find_statements("COMPUTE")
        assert len(computes) >= 1

    def test_compute_nested_parentheses(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 1.
       01  WS-B PIC 9(3) VALUE 2.
       01  WS-C PIC 9(3) VALUE 3.
       01  WS-D PIC 9(3) VALUE 4.
       01  WS-R PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-R = ((WS-A + WS-B) * (WS-C - WS-D)).
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_division_and_subtraction(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 100.
       01  WS-B PIC 9(3) VALUE 5.
       01  WS-C PIC 9(3) VALUE 10.
       01  WS-R PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-R = WS-A / WS-B - WS-C.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_with_numeric_literal(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 10.
       01  WS-R PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-R = WS-A * 100 + 50.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_rounded_with_expression(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3)V99 VALUE 10.50.
       01  WS-R PIC 9(3).
       PROCEDURE DIVISION.
           COMPUTE WS-R ROUNDED = WS-A / 3.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_complex_expression_with_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 999.
       01  WS-R PIC 9(3).
       01  WS-FLAG PIC X.
       PROCEDURE DIVISION.
           COMPUTE WS-R = (WS-A * WS-B) + 1
               ON SIZE ERROR
                   DISPLAY "OVERFLOW"
               NOT ON SIZE ERROR
                   DISPLAY "OK"
           END-COMPUTE.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_expression_with_exponentiation(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 2.
       01  WS-R PIC 9(6).
       PROCEDURE DIVISION.
           COMPUTE WS-R = WS-A ** 3.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_no_equals_sign(self):
        """COMPUTE without = should still parse."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 10.
       01  WS-R PIC 9(3).
       PROCEDURE DIVISION.
           COMPUTE WS-R WS-A + 1.
           STOP RUN.
        """)
        assert result.ast is not None


class TestArithmeticSizeErrorNestedStatements:
    """Cover nested DISPLAY and MOVE within ON SIZE ERROR clauses."""

    def test_add_size_error_with_display(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 1.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B
               ON SIZE ERROR
                   DISPLAY "ERROR OCCURRED".
           STOP RUN.
        """)
        assert result.ast is not None

    def test_add_size_error_with_move(self):
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
                   MOVE "Y" TO WS-FLAG.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_add_not_on_size_error_with_display(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 1.
       01  WS-B PIC 9(3) VALUE 2.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B
               NOT ON SIZE ERROR
                   DISPLAY "SUCCESS".
           STOP RUN.
        """)
        assert result.ast is not None

    def test_add_both_clauses_with_nested_stmts(self):
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
                   DISPLAY "ERROR"
                   MOVE "E" TO WS-FLAG
               NOT ON SIZE ERROR
                   DISPLAY "OK"
                   MOVE "S" TO WS-FLAG.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_compute_size_error_with_nested_display_and_move(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 999.
       01  WS-R PIC 9(3).
       01  WS-FLAG PIC X.
       PROCEDURE DIVISION.
           COMPUTE WS-R = WS-A * WS-B
               ON SIZE ERROR
                   DISPLAY "OVERFLOW"
                   MOVE "E" TO WS-FLAG
               NOT ON SIZE ERROR
                   DISPLAY "OK"
                   MOVE "S" TO WS-FLAG.
           STOP RUN.
        """)
        assert result.ast is not None


class TestMultiplyGiving:
    """Cover MULTIPLY...GIVING (lines 414-421 in arithmetic_parsers.py)."""

    def test_multiply_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 5.
       01  WS-B PIC 9(3) VALUE 10.
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           MULTIPLY WS-A BY WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None
        multiplies = result.ast.find_statements("MULTIPLY")
        assert len(multiplies) >= 1

    def test_multiply_giving_on_size_error(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 999.
       01  WS-B PIC 9(3) VALUE 999.
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
           MULTIPLY WS-A BY WS-B GIVING WS-C
               ON SIZE ERROR
                   DISPLAY "OVERFLOW".
           STOP RUN.
        """)
        assert result.ast is not None


class TestDivideByInto:
    """Cover DIVIDE BY/INTO distinction (lines 472-484)."""

    def test_divide_by(self):
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
        divides = result.ast.find_statements("DIVIDE")
        assert len(divides) >= 1

    def test_divide_into(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 100.
       01  WS-B PIC 9(3) VALUE 3.
       01  WS-C PIC 9(6).
       PROCEDURE DIVISION.
           DIVIDE WS-A INTO WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None

    def test_divide_into_no_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 100.
       01  WS-B PIC 9(3) VALUE 3.
       PROCEDURE DIVISION.
           DIVIDE WS-A INTO WS-B.
           STOP RUN.
        """)
        assert result.ast is not None


class TestSubtractGiving:
    """Cover SUBTRACT...GIVING (lines 346-351)."""

    def test_subtract_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 50.
       01  WS-B PIC 9(3) VALUE 20.
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
           SUBTRACT WS-A FROM WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None
        subtracts = result.ast.find_statements("SUBTRACT")
        assert len(subtracts) >= 1


class TestAddToGiving:
    """Cover ADD...TO...GIVING (lines 77-89)."""

    def test_add_to_giving(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3) VALUE 10.
       01  WS-B PIC 9(3) VALUE 20.
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
           ADD WS-A TO WS-B GIVING WS-C.
           STOP RUN.
        """)
        assert result.ast is not None
        adds = result.ast.find_statements("ADD")
        assert len(adds) >= 1


class TestComputeExpressionLayout:
    """#391: a line break inside the expression is layout, not text."""

    def test_line_break_does_not_appear_in_expression(self):
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
           COMPUTE WS-A = WS-B
               + 1
               * 2
           STOP RUN.
        """)
        assert result.ast is not None
        (compute,) = result.ast.find_statements("COMPUTE")
        assert compute.to_dict()["expression"] == "WS-B + 1 * 2"
