"""Tests targeting uncovered lines in perform_parser.py.

Covers:
- PERFORM VARYING FROM/BY/UNTIL (lines 290-367)
- PERFORM WITH TEST BEFORE/AFTER (lines 96-112)
- PERFORM paragraph UNTIL condition (lines 262-267)
- PERFORM paragraph WITH TEST UNTIL (lines 243-257)
- PERFORM n TIMES inline (lines 119-149)
- PERFORM paragraph n TIMES (lines 193-238)
- END-PERFORM handling (lines 274-282)
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import PerformStatement
from cobolparser.parser import CobolParser
from cobolparser.parsers.statements.perform_parser import PerformStatementParser


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PERFORM.\n"
        "       PROCEDURE DIVISION.\n"
        f"{code}\n"
    )
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements, result
    return [], result


def _find_perform(stmts):
    for s in stmts:
        if isinstance(s, PerformStatement):
            return s
    pytest.fail(f"No PerformStatement found in {stmts}")


class TestPerformVarying:
    """PERFORM VARYING ... FROM ... BY ... UNTIL (lines 286-367)."""

    def test_perform_varying_basic(self):
        stmts, _ = parse_procedure(
            "           PERFORM VARYING WS-IDX FROM 1 BY 1\n"
            "               UNTIL WS-IDX > 10\n"
            "               DISPLAY WS-IDX\n"
            "           END-PERFORM."
        )
        _find_perform(stmts)

    @pytest.mark.parametrize("timing", ["BEFORE", "AFTER"])
    def test_perform_varying_with_test(self, timing):
        stmts, _ = parse_procedure(
            f"           PERFORM VARYING WS-I FROM 1 BY 1\n"
            f"               WITH TEST {timing}\n"
            f"               UNTIL WS-I > 5\n"
            f"               DISPLAY WS-I\n"
            f"           END-PERFORM."
        )
        _find_perform(stmts)


class TestPerformWithTestTiming:
    """PERFORM WITH TEST BEFORE/AFTER UNTIL (lines 96-112)."""

    @pytest.mark.parametrize("timing", ["BEFORE", "AFTER"])
    def test_perform_with_test_until(self, timing):
        stmts, _ = parse_procedure(
            f"           PERFORM WITH TEST {timing}\n"
            f"               UNTIL WS-FLAG = 'Y'\n"
            f'               DISPLAY "LOOP"\n'
            f"           END-PERFORM."
        )
        _find_perform(stmts)


class TestPerformParagraphUntil:
    """PERFORM paragraph UNTIL condition (lines 262-267)."""

    def test_perform_paragraph_until(self):
        stmts, _ = parse_procedure(
            "           PERFORM PROCESS-RECORDS UNTIL EOF-FLAG = 'Y'."
        )
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-RECORDS"

    def test_perform_paragraph_until_end_perform(self):
        stmts, _ = parse_procedure(
            "           PERFORM PROCESS-RECORDS\n"
            "               UNTIL WS-EOF = 'Y'\n"
            "           END-PERFORM."
        )
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-RECORDS"


class TestPerformParagraphWithTestUntil:
    """PERFORM paragraph WITH TEST ... UNTIL ... (lines 243-267)."""

    @pytest.mark.parametrize("timing", ["BEFORE", "AFTER"])
    def test_perform_paragraph_with_test_until(self, timing):
        stmts, _ = parse_procedure(
            f"           PERFORM PROCESS-PARA\n"
            f"               WITH TEST {timing}\n"
            f"               UNTIL DONE-FLAG = 'Y'."
        )
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-PARA"


class TestPerformNTimes:
    """PERFORM n TIMES inline (lines 119-149)."""

    def test_perform_n_times_inline(self):
        stmts, _ = parse_procedure(
            "           PERFORM 5 TIMES\n"
            '               DISPLAY "HELLO"\n'
            "           END-PERFORM."
        )
        _find_perform(stmts)

    def test_perform_1_time(self):
        stmts, _ = parse_procedure(
            "           PERFORM 1 TIME\n"
            '               DISPLAY "ONCE"\n'
            "           END-PERFORM."
        )
        _find_perform(stmts)


class TestPerformParagraphNTimes:
    """PERFORM paragraph n TIMES (lines 193-238)."""

    def test_perform_paragraph_n_times_numeric(self):
        stmts, _ = parse_procedure("           PERFORM PROCESS-PARA 5 TIMES.")
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-PARA"

    def test_perform_paragraph_variable_times(self):
        stmts, _ = parse_procedure("           PERFORM PROCESS-PARA WS-COUNT TIMES.")
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-PARA"


class TestPerformEndPerform:
    """END-PERFORM handling (lines 274-282)."""

    def test_perform_until_end_perform(self):
        stmts, _ = parse_procedure(
            "           PERFORM UNTIL WS-EOF = 'Y'\n"
            '               DISPLAY "PROCESSING"\n'
            "           END-PERFORM."
        )
        _find_perform(stmts)

    def test_perform_paragraph_end_perform(self):
        stmts, _ = parse_procedure(
            "           PERFORM PROCESS-PARA\n           END-PERFORM."
        )
        stmt = _find_perform(stmts)
        assert stmt.target_paragraph == "PROCESS-PARA"


class TestPerformMatchesFalse:
    """matches() returns False on empty stream or wrong token."""

    def test_matches_empty_stream(self):
        assert PerformStatementParser().matches(TokenStream([])) is False

    def test_matches_wrong_token(self):
        tok = Token(TokenType.IDENTIFIER, "FOO", SourceLocation(1, 1))
        assert PerformStatementParser().matches(TokenStream([tok])) is False
