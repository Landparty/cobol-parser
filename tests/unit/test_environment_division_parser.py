"""Tests for the Environment Division parser.

Targets coverage gaps in parsers/divisions/environment.py (86.87%, 38 missing branches).
No dedicated unit test file existed previously.
"""

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol


def _parse(src):
    return parse_cobol(src)


def _parse_with_recovery(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


class TestEmptyEnvironmentDivision:
    """Empty environment division."""

    def test_empty_environment_division(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        env = result.ast.get_division("ENVIRONMENT")
        assert env is not None


class TestConfigurationSection:
    """Configuration Section parsing."""

    def test_source_computer(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SOURCE-COMPUTER. IBM-370.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_object_computer(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       OBJECT-COMPUTER. IBM-370.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_both_computers(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SOURCE-COMPUTER. IBM-370.\n"
            "       OBJECT-COMPUTER. IBM-370.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_special_names(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SPECIAL-NAMES.\n"
            "           DECIMAL-POINT IS COMMA.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success


class TestInputOutputSection:
    """Input-Output Section and File-Control parsing."""

    def test_select_sequential(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT INPUT-FILE ASSIGN TO 'INPUT.DAT'\n"
            "               ORGANIZATION IS SEQUENTIAL\n"
            "               ACCESS MODE IS SEQUENTIAL\n"
            "               FILE STATUS IS WS-STATUS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC XX.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_select_indexed(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT MASTER-FILE ASSIGN TO 'MASTER.DAT'\n"
            "               ORGANIZATION IS INDEXED\n"
            "               ACCESS MODE IS DYNAMIC\n"
            "               RECORD KEY IS MASTER-KEY\n"
            "               FILE STATUS IS WS-STATUS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC XX.\n"
            "       01 MASTER-KEY PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_select_relative(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT REL-FILE ASSIGN TO 'REL.DAT'\n"
            "               ORGANIZATION IS RELATIVE\n"
            "               ACCESS MODE IS RANDOM\n"
            "               RELATIVE KEY IS WS-REC-NUM\n"
            "               FILE STATUS IS WS-STATUS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC XX.\n"
            "       01 WS-REC-NUM PIC 9(4).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_multiple_select(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT FILE-A ASSIGN TO 'A.DAT'.\n"
            "           SELECT FILE-B ASSIGN TO 'B.DAT'.\n"
            "           SELECT FILE-C ASSIGN TO 'C.DAT'.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_select_with_alternate_key(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT IDX-FILE ASSIGN TO 'IDX.DAT'\n"
            "               ORGANIZATION IS INDEXED\n"
            "               ACCESS MODE IS DYNAMIC\n"
            "               RECORD KEY IS PRIMARY-KEY\n"
            "               ALTERNATE RECORD KEY IS ALT-KEY\n"
            "               FILE STATUS IS WS-STATUS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC XX.\n"
            "       01 PRIMARY-KEY PIC X(10).\n"
            "       01 ALT-KEY PIC X(5).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success


class TestEnvironmentDivisionBoundary:
    """Tests for division boundary detection."""

    def test_stops_at_data_division(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SOURCE-COMPUTER. IBM-370.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        assert result.ast.has_division("DATA")

    def test_stops_at_procedure_division(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SOURCE-COMPUTER. IBM-370.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        assert result.ast.has_division("PROCEDURE")


class TestEnvironmentWithRecovery:
    """Error recovery in environment division."""

    def test_malformed_select_recovers(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        # Should not crash even with malformed SELECT
        assert result.ast is not None

    def test_full_environment_with_all_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SOURCE-COMPUTER. IBM-370.\n"
            "       OBJECT-COMPUTER. IBM-370.\n"
            "       SPECIAL-NAMES.\n"
            "           DECIMAL-POINT IS COMMA.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT MAIN-FILE ASSIGN TO 'MAIN.DAT'\n"
            "               ORGANIZATION IS INDEXED\n"
            "               ACCESS MODE IS DYNAMIC\n"
            "               RECORD KEY IS MAIN-KEY\n"
            "               FILE STATUS IS WS-STATUS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC XX.\n"
            "       01 MAIN-KEY PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        assert result.ast.has_division("ENVIRONMENT")
