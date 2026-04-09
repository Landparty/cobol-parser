"""Tests for error recovery mode (COLLECT_ALL) with malformed COBOL.

Covers error-handling branches across multiple parser files:
- parser.py error recovery (lines 196-200, 291-296)
- divisions/procedure.py (lines 320-322, 428-430)
- divisions/data.py (lines 280-281, 569-571)
- divisions/environment.py (lines 103-107)
- divisions/identification.py (lines 218-220)
"""

from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode


def parse_with_recovery(source):
    """Parse with COLLECT_ALL error recovery mode."""
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(source)


class TestMalformedProcedureDivision:
    """Tests for error recovery in procedure division parsing."""

    def test_missing_procedure_division_header(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
           DISPLAY "HELLO".
           STOP RUN.
        """
        result = parse_with_recovery(src)
        # Should parse without crashing
        assert result.ast is not None

    def test_unterminated_if(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           IF A = B
               DISPLAY "YES"
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_unknown_statement_verb(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           XYZZY "HELLO".
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_empty_procedure_division(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None


class TestMalformedDataDivision:
    """Tests for error recovery in data division parsing."""

    def test_invalid_level_number(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       99 WS-BAD PIC X.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_missing_pic_clause(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GROUP.
          05 WS-FIELD.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_data_item_with_value_clause(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(5) VALUE 12345.
       01 WS-B PIC X(10) VALUE "HELLO".
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None
        assert len(result.errors) == 0


class TestMalformedEnvironmentDivision:
    """Tests for error recovery in environment division parsing."""

    def test_incomplete_select_clause(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_environment_with_special_names(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None


class TestMalformedIdentificationDivision:
    """Tests for error recovery in identification division."""

    def test_extra_identification_fields(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       AUTHOR. JOHN DOE.
       DATE-WRITTEN. 2024-01-01.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None

    def test_missing_program_id(self):
        src = """
       IDENTIFICATION DIVISION.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None


class TestParserEdgeCases:
    """Tests for parser.py edge cases (lines 144, 237, 306, 328-329)."""

    def test_multiple_divisions_parsing(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X.
       PROCEDURE DIVISION.
           DISPLAY WS-A.
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None
        assert result.ast.identification_division is not None
        assert result.ast.environment_division is not None
        assert result.ast.data_division is not None
        assert result.ast.procedure_division is not None

    def test_program_with_sections(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           DISPLAY "HELLO".
           STOP RUN.
        """
        result = parse_with_recovery(src)
        assert result.ast is not None
