"""Tests for error recovery mode (COLLECT_ALL) with malformed COBOL.

Exercises error-handling branches across:
- parser.py (lines 196-200, 291-296)
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
    """Error recovery in procedure division parsing."""

    def test_missing_procedure_division_header(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            '           DISPLAY "HELLO".\n'
            "           STOP RUN.\n"
        )
        assert result.ast is not None

    def test_unterminated_if_recovers(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
            "           IF A = B\n"
            '               DISPLAY "YES"\n'
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        assert result.ast.procedure_division is not None

    def test_unknown_statement_verb(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
            '           XYZZY "HELLO".\n'
            "           STOP RUN.\n"
        )
        assert result.ast is not None

    def test_empty_procedure_division(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
        )
        assert result.ast is not None
        assert result.ast.procedure_division is not None


class TestMalformedDataDivision:
    """Error recovery in data division parsing."""

    def test_missing_pic_clause_on_elementary_item(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-GROUP.\n"
            "          05 WS-FIELD.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None

    def test_valid_data_items_parse_cleanly(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9(5) VALUE 12345.\n"
            '       01 WS-B PIC X(10) VALUE "HELLO".\n'
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        assert result.ast.data_division is not None
        assert len(result.errors) == 0


class TestMalformedEnvironmentDivision:
    """Error recovery in environment division parsing."""

    def test_incomplete_select_clause(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT INPUT-FILE.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        assert result.ast.environment_division is not None

    def test_special_names_decimal_point(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SPECIAL-NAMES.\n"
            "           DECIMAL-POINT IS COMMA.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        assert result.ast.environment_division is not None


class TestMalformedIdentificationDivision:
    """Error recovery in identification division."""

    def test_extra_identification_fields(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       AUTHOR. JOHN DOE.\n"
            "       DATE-WRITTEN. 2024-01-01.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        assert result.ast.identification_division is not None

    def test_missing_program_id(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert result.ast is not None


class TestMultipleDivisions:
    """Full program with all four divisions (parser.py lines 237, 306, 328-329)."""

    def test_all_divisions_present(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
        )
        ast = result.ast
        assert ast.identification_division is not None
        assert ast.environment_division is not None
        assert ast.data_division is not None
        assert ast.procedure_division is not None

    def test_program_with_named_section(self):
        result = parse_with_recovery(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-SECTION SECTION.\n"
            "       MAIN-PARA.\n"
            '           DISPLAY "HELLO".\n'
            "           STOP RUN.\n"
        )
        assert result.ast is not None
        proc = result.ast.procedure_division
        assert proc is not None
