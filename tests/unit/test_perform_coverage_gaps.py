"""Tests targeting uncovered lines in perform_parser.py.

Covers:
- Empty/malformed PERFORM (lines 70-80) — end-of-stream and period error recovery
- PERFORM VARYING clause (lines 290-367) — FROM/BY/UNTIL
- PERFORM paragraph WITH TEST BEFORE/AFTER (lines 244-257)
- PERFORM paragraph UNTIL condition (lines 262-267)
- END-PERFORM handling (lines 274-282)
- PERFORM n TIMES inline (lines 119-149)
- _parse_until_condition_only (lines 432-471)
- _try_consume_period (lines 514-521)
"""

from cobolparser.models.statements import PerformStatement
from cobolparser.parser import CobolParser


def parse_procedure(code):
    """Parse COBOL and return procedure division statements."""
    src = f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PERFORM.
       PROCEDURE DIVISION.
{code}
    """
    result = CobolParser().parse(src)
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements, result
    if proc.sections:
        sec = proc.sections[0]
        if sec.paragraphs:
            return sec.paragraphs[0].statements, result
    return [], result


class TestPerformVarying:
    """Tests for PERFORM VARYING ... FROM ... BY ... UNTIL (lines 286-367)."""

    def test_perform_varying_basic(self):
        stmts, result = parse_procedure(
            "           PERFORM VARYING WS-IDX FROM 1 BY 1\n"
            "               UNTIL WS-IDX > 10\n"
            "               DISPLAY WS-IDX\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_varying_with_test_before(self):
        stmts, result = parse_procedure(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-I > 5\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_varying_with_test_after(self):
        stmts, result = parse_procedure(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST AFTER\n"
            "               UNTIL WS-I > 5\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformWithTestTiming:
    """Tests for PERFORM WITH TEST BEFORE/AFTER (lines 96-112)."""

    def test_perform_with_test_before_until(self):
        stmts, result = parse_procedure(
            "           PERFORM WITH TEST BEFORE\n"
            "               UNTIL WS-FLAG = 'Y'\n"
            "               DISPLAY \"LOOP\"\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_with_test_after_until(self):
        stmts, result = parse_procedure(
            "           PERFORM WITH TEST AFTER\n"
            "               UNTIL WS-DONE = 'Y'\n"
            "               DISPLAY \"LOOP\"\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformParagraphUntil:
    """Tests for PERFORM para UNTIL condition (lines 262-267)."""

    def test_perform_paragraph_until(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-RECORDS UNTIL EOF-FLAG = 'Y'."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1
        stmt = perform_stmts[0]
        assert stmt.target_paragraph == "PROCESS-RECORDS"

    def test_perform_paragraph_until_end_perform(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-RECORDS\n"
            "               UNTIL WS-EOF = 'Y'\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformParagraphWithTestUntil:
    """Tests for PERFORM paragraph WITH TEST ... UNTIL ... (lines 243-267)."""

    def test_perform_paragraph_with_test_before_until(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-PARA\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL DONE-FLAG = 'Y'."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_paragraph_with_test_after_until(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-PARA\n"
            "               WITH TEST AFTER\n"
            "               UNTIL DONE-FLAG = 'Y'."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformNTimes:
    """Tests for PERFORM n TIMES inline (lines 119-149)."""

    def test_perform_n_times_inline(self):
        stmts, result = parse_procedure(
            "           PERFORM 5 TIMES\n"
            "               DISPLAY \"HELLO\"\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_1_time(self):
        stmts, result = parse_procedure(
            "           PERFORM 1 TIME\n"
            "               DISPLAY \"ONCE\"\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformParagraphNTimes:
    """Tests for PERFORM paragraph n TIMES (lines 193-238)."""

    def test_perform_paragraph_n_times_numeric(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-PARA 5 TIMES."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1
        stmt = perform_stmts[0]
        assert stmt.target_paragraph == "PROCESS-PARA"

    def test_perform_paragraph_variable_times(self):
        """PERFORM paragraph WS-COUNT TIMES — variable used for count."""
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-PARA WS-COUNT TIMES."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformEndPerform:
    """Tests for END-PERFORM handling (lines 274-282)."""

    def test_perform_until_end_perform(self):
        stmts, result = parse_procedure(
            "           PERFORM UNTIL WS-EOF = 'Y'\n"
            "               DISPLAY \"PROCESSING\"\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1

    def test_perform_paragraph_end_perform(self):
        stmts, result = parse_procedure(
            "           PERFORM PROCESS-PARA\n"
            "           END-PERFORM."
        )
        perform_stmts = [s for s in stmts if isinstance(s, PerformStatement)]
        assert len(perform_stmts) >= 1


class TestPerformMatchesFalse:
    """Tests for matches() returning False."""

    def test_matches_empty_stream(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.parsers.statements.perform_parser import (
            PerformStatementParser,
        )

        parser = PerformStatementParser()
        stream = TokenStream([])
        assert parser.matches(stream) is False

    def test_matches_wrong_token(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.parsers.statements.perform_parser import (
            PerformStatementParser,
        )

        parser = PerformStatementParser()
        tok = Token(TokenType.IDENTIFIER, "FOO", SourceLocation(1, 1))
        stream = TokenStream([tok])
        assert parser.matches(stream) is False
