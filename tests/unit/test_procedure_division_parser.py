"""Tests for the Procedure Division parser.

Targets coverage gaps in parsers/divisions/procedure.py (87.56%, 24 missing branches).
No dedicated unit test file existed previously.
"""

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol


def _parse(src):
    return parse_cobol(src)


def _parse_with_recovery(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


class TestEmptyProcedureDivision:
    """Minimal procedure division."""

    def test_procedure_with_stop_run_only(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        proc = result.ast.procedure_division
        assert proc is not None


class TestSingleParagraph:
    """Single paragraph with statements."""

    def test_single_paragraph(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           DISPLAY 'HELLO'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        proc = result.ast.procedure_division
        assert len(proc.paragraphs) >= 1


class TestMultipleParagraphs:
    """Multiple paragraphs in procedure division."""

    def test_multiple_paragraphs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           PERFORM SUB-LOGIC.\n"
            "           STOP RUN.\n"
            "       SUB-LOGIC.\n"
            "           DISPLAY 'SUB'.\n"
        )
        result = _parse(src)
        assert result.success
        proc = result.ast.procedure_division
        assert len(proc.paragraphs) >= 2

    def test_three_paragraphs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       PARA-1.\n"
            "           DISPLAY 'ONE'.\n"
            "       PARA-2.\n"
            "           DISPLAY 'TWO'.\n"
            "       PARA-3.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        proc = result.ast.procedure_division
        assert len(proc.paragraphs) >= 3


class TestSections:
    """Sections containing paragraphs."""

    def test_section_with_paragraphs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-SECTION SECTION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY 'HELLO'.\n"
            "       SUB-PARA.\n"
            "           DISPLAY 'SUB'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_multiple_sections(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       SECTION-A SECTION.\n"
            "       PARA-A.\n"
            "           DISPLAY 'A'.\n"
            "       SECTION-B SECTION.\n"
            "       PARA-B.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success


class TestMixedStatements:
    """Mixed statement types in procedure division."""

    def test_mixed_statements(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9(4) VALUE 5.\n"
            "       01 WS-Y PIC 9(4) VALUE 10.\n"
            "       01 WS-Z PIC 9(4) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           MOVE WS-X TO WS-Z.\n"
            "           ADD WS-X TO WS-Y.\n"
            "           COMPUTE WS-Z = WS-X * WS-Y.\n"
            "           IF WS-Z > 50\n"
            "               DISPLAY 'BIG'\n"
            "           ELSE\n"
            "               DISPLAY 'SMALL'\n"
            "           END-IF.\n"
            "           PERFORM SUB-LOGIC.\n"
            "           STOP RUN.\n"
            "       SUB-LOGIC.\n"
            "           DISPLAY WS-Z.\n"
        )
        result = _parse(src)
        assert result.success
        stmts = result.ast.get_all_statements()
        types = [s.statement_type for s in stmts]
        assert "MOVE" in types
        assert "ADD" in types
        assert "COMPUTE" in types
        assert "IF" in types
        assert "DISPLAY" in types


class TestErrorRecovery:
    """Error recovery in procedure division."""

    def test_unknown_statement_verb(self):
        """Unknown verb should not crash with COLLECT_ALL mode."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           XYZZY 'FOO'.\n"
            "           DISPLAY 'HELLO'.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None
        stmts = result.ast.get_all_statements()
        display_stmts = [s for s in stmts if s.statement_type == "DISPLAY"]
        assert len(display_stmts) >= 1

    def test_missing_period(self):
        """Missing period terminator."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           DISPLAY 'HELLO'\n"
            "           DISPLAY 'WORLD'.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None


class TestDeclaratives:
    """DECLARATIVES section parsing."""

    def test_declaratives_section(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       DECLARATIVES.\n"
            "       ERROR-SECTION SECTION.\n"
            "           USE AFTER STANDARD ERROR PROCEDURE ON INPUT.\n"
            "       ERROR-PARA.\n"
            "           DISPLAY 'ERROR'.\n"
            "       END DECLARATIVES.\n"
            "       MAIN-LOGIC.\n"
            "           DISPLAY 'HELLO'.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None


class TestNestedStatements:
    """Nested IF/EVALUATE in procedure division."""

    def test_nested_if_evaluate(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9(4) VALUE 5.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-X > 3\n"
            "               EVALUATE WS-X\n"
            "                   WHEN 4\n"
            "                       DISPLAY 'FOUR'\n"
            "                   WHEN 5\n"
            "                       DISPLAY 'FIVE'\n"
            "                   WHEN OTHER\n"
            "                       DISPLAY 'OTHER'\n"
            "               END-EVALUATE\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        stmts = result.ast.get_all_statements()
        types = [s.statement_type for s in stmts]
        assert "IF" in types
        assert "EVALUATE" in types


class TestParagraphWithNoStatements:
    """Paragraph that's just a label."""

    def test_empty_paragraph_before_another(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "       EMPTY-PARA.\n"
            "       MAIN-LOGIC.\n"
            "           DISPLAY 'HELLO'.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None
