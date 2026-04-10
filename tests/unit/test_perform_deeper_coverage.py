"""Deeper coverage tests for perform_parser.py targeting remaining uncovered paths.

Targets lines 39-40, 70-72, 75-80, 109-110, 161-162, 187-188, 237-238,
248-259, 256-257, 266-267, 280-282, 297, 313, 328, 339-350, 347-348,
359->exit, 366-367, 381, 383, 393, 410-411, 429-430, 438-441, 448,
457-458, 464->exit, 470-471, 486, 511-512, 520-521.
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import PerformStatement
from cobolparser.parsers.statements.perform_parser import PerformStatementParser


def _make_source(procedure_body: str, extra_data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-I PIC 9(4) VALUE 0.\n"
        "       01 WS-J PIC 9(4) VALUE 0.\n"
        "       01 WS-END PIC 9(4) VALUE 10.\n"
        "       01 WS-COUNT PIC 9(4) VALUE 5.\n"
        f"{extra_data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
        "       SUB-PARA.\n"
        '           DISPLAY "SUB".\n'
        "       END-PARA.\n"
        '           DISPLAY "END".\n'
    )


def _parse(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


def _find_perform(result):
    proc = result.ast.procedure_division
    for p in proc.paragraphs:
        for s in p.statements:
            if isinstance(s, PerformStatement):
                return s
    if proc.sections:
        for sec in proc.sections:
            for p in sec.paragraphs:
                for s in p.statements:
                    if isinstance(s, PerformStatement):
                        return s
    return None


def _tok(tt, value=None, line=0, col=0):
    """Create a Token for direct parser testing."""
    return Token(type=tt, value=value or tt.name, location=SourceLocation(line, col))


# ---------------------------------------------------------------------------
# matches() exception path (lines 39-40)
# ---------------------------------------------------------------------------


class TestPerformMatchesException:
    def test_matches_returns_false_on_broken_stream(self):
        """matches() catches exception and returns False (lines 39-40)."""

        class BrokenStream:
            def peek(self, offset=0):
                raise RuntimeError("broken")

            @property
            def context(self):
                return None

        parser = PerformStatementParser()
        assert parser.matches(BrokenStream()) is False

    def test_matches_returns_false_on_empty_stream(self):
        parser = PerformStatementParser()
        assert parser.matches(TokenStream([])) is False


# ---------------------------------------------------------------------------
# PERFORM at end of stream (lines 70-72)
# ---------------------------------------------------------------------------


class TestPerformEndOfStream:
    def test_perform_at_end_of_stream(self):
        """PERFORM with nothing after it (lines 70-72)."""
        tokens = [_tok(TokenType.PERFORM, "PERFORM")]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)


# ---------------------------------------------------------------------------
# PERFORM followed by period (lines 75-80)
# ---------------------------------------------------------------------------


class TestPerformFollowedByPeriod:
    def test_perform_period(self):
        """PERFORM. should report error and return (lines 75-80)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)


# ---------------------------------------------------------------------------
# PERFORM WITH TEST error (lines 109-110)
# ---------------------------------------------------------------------------


class TestPerformWithTestError:
    def test_perform_with_non_test_token(self):
        """PERFORM WITH <non-TEST> - error recovery (lines 109-110)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.WITH, "WITH"),
            _tok(TokenType.IDENTIFIER, "SOMETHING"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_perform_with_test_non_before_after(self):
        """PERFORM WITH TEST <non-BEFORE/AFTER> (lines 248->259)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.WITH, "WITH"),
            _tok(TokenType.TEST, "TEST"),
            _tok(TokenType.IDENTIFIER, "UNKNOWN"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)


# ---------------------------------------------------------------------------
# PERFORM paragraph with THRU (exception path lines 161-162, 187-188)
# ---------------------------------------------------------------------------


class TestPerformThruExceptions:
    def test_perform_paragraph_thru_paragraph(self):
        """PERFORM SUB-PARA THRU END-PARA via round-trip."""
        src = _make_source("           PERFORM SUB-PARA THRU END-PARA.\n")
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.target_paragraph == "SUB-PARA"
        assert stmt.thru_paragraph == "END-PARA"


# ---------------------------------------------------------------------------
# PERFORM paragraph n TIMES (lines 237-238, numeric after paragraph)
# ---------------------------------------------------------------------------


class TestPerformParagraphTimes:
    def test_perform_paragraph_numeric_times(self):
        """PERFORM SUB-PARA 5 TIMES."""
        src = _make_source("           PERFORM SUB-PARA 5 TIMES.\n")
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.times_count == 5

    def test_perform_paragraph_variable_times(self):
        """PERFORM SUB-PARA WS-COUNT TIMES (variable name for TIMES)."""
        src = _make_source("           PERFORM SUB-PARA WS-COUNT TIMES.\n")
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        # Variable name kept as string
        assert stmt.times_count == "WS-COUNT"


# ---------------------------------------------------------------------------
# PERFORM paragraph WITH TEST BEFORE/AFTER UNTIL (lines 248-259, 266-267)
# ---------------------------------------------------------------------------


class TestPerformParagraphWithTestUntil:
    def test_perform_paragraph_with_test_before_until(self):
        """PERFORM SUB-PARA WITH TEST BEFORE UNTIL WS-I = WS-END."""
        src = _make_source(
            "           PERFORM SUB-PARA WITH TEST BEFORE\n"
            "               UNTIL WS-I = WS-END.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.target_paragraph == "SUB-PARA"

    def test_perform_paragraph_with_test_after_until(self):
        """PERFORM SUB-PARA WITH TEST AFTER UNTIL WS-I = WS-END."""
        src = _make_source(
            "           PERFORM SUB-PARA WITH TEST AFTER\n"
            "               UNTIL WS-I = WS-END.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_perform_paragraph_until_simple(self):
        """PERFORM SUB-PARA UNTIL WS-I = WS-END."""
        src = _make_source("           PERFORM SUB-PARA UNTIL WS-I = WS-END.\n")
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.target_paragraph == "SUB-PARA"
        assert stmt.until_condition is not None


# ---------------------------------------------------------------------------
# PERFORM paragraph END-PERFORM (lines 280-282)
# ---------------------------------------------------------------------------


class TestPerformEndPerformCleanup:
    def test_perform_paragraph_end_perform(self):
        """PERFORM SUB-PARA END-PERFORM (cleanup path lines 280-282)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.IDENTIFIER, "SUB-PARA"),
            _tok(TokenType.IDENTIFIER, "END-PERFORM"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)
        assert stmt.target_paragraph == "SUB-PARA"


# ---------------------------------------------------------------------------
# PERFORM VARYING edge cases (lines 297, 313, 328, 339-350, 359, 366-367)
# ---------------------------------------------------------------------------


class TestPerformVaryingEdgeCases:
    def test_varying_no_identifier(self):
        """PERFORM VARYING <period> - no variable name (line 297)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.VARYING, "VARYING"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_varying_no_from(self):
        """PERFORM VARYING X <period> - no FROM (line 313 via early return)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.VARYING, "VARYING"),
            _tok(TokenType.IDENTIFIER, "WS-I"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_varying_no_by(self):
        """PERFORM VARYING X FROM 1 <period> - no BY (line 328 via early return)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.VARYING, "VARYING"),
            _tok(TokenType.IDENTIFIER, "WS-I"),
            _tok(TokenType.IDENTIFIER, "FROM"),
            _tok(TokenType.NUMERIC_LITERAL, "1"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_varying_no_by_value(self):
        """PERFORM VARYING X FROM 1 BY <eos> - no BY value (line 328)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.VARYING, "VARYING"),
            _tok(TokenType.IDENTIFIER, "WS-I"),
            _tok(TokenType.IDENTIFIER, "FROM"),
            _tok(TokenType.NUMERIC_LITERAL, "1"),
            _tok(TokenType.IDENTIFIER, "BY"),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_varying_with_test_before_until(self):
        """PERFORM VARYING X FROM 1 BY 1 WITH TEST BEFORE UNTIL (lines 339-350)."""
        src = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-I > WS-END\n"
            '               DISPLAY "LOOP"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_varying_with_test_after_until(self):
        """PERFORM VARYING X FROM 1 BY 1 WITH TEST AFTER UNTIL."""
        src = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST AFTER\n"
            "               UNTIL WS-I > WS-END\n"
            '               DISPLAY "LOOP"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_varying_without_until(self):
        """PERFORM VARYING X FROM 1 BY 1 <inline> - no UNTIL (line 359->exit)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.VARYING, "VARYING"),
            _tok(TokenType.IDENTIFIER, "WS-I"),
            _tok(TokenType.IDENTIFIER, "FROM"),
            _tok(TokenType.NUMERIC_LITERAL, "1"),
            _tok(TokenType.IDENTIFIER, "BY"),
            _tok(TokenType.NUMERIC_LITERAL, "1"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)

    def test_varying_full_round_trip(self):
        """PERFORM VARYING full syntax round trip."""
        src = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > WS-END\n"
            '               DISPLAY "LOOP"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None


# ---------------------------------------------------------------------------
# _collect_until_condition_tokens (lines 381, 383, 393)
# ---------------------------------------------------------------------------


class TestCollectUntilConditionTokens:
    def test_until_condition_with_period(self):
        """UNTIL condition stopping at period (line 383)."""
        src = _make_source(
            "           PERFORM UNTIL WS-I = WS-END\n"
            '               DISPLAY "DONE"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.until_condition is not None


# ---------------------------------------------------------------------------
# _parse_until_condition_only (lines 438-441, 448, 457-458, 464->exit, 470-471)
# ---------------------------------------------------------------------------


class TestParseUntilConditionOnly:
    def test_paragraph_until_with_end_perform(self):
        """PERFORM SUB-PARA UNTIL WS-I = 10 END-PERFORM (line 457-458)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.IDENTIFIER, "SUB-PARA"),
            _tok(TokenType.UNTIL, "UNTIL"),
            _tok(TokenType.IDENTIFIER, "WS-I"),
            _tok(TokenType.ASSIGN, "="),
            _tok(TokenType.NUMERIC_LITERAL, "10"),
            _tok(TokenType.IDENTIFIER, "END-PERFORM"),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)
        assert stmt.target_paragraph == "SUB-PARA"
        assert stmt.until_condition is not None

    def test_paragraph_until_empty_condition(self):
        """PERFORM SUB-PARA UNTIL . - empty condition (line 464->exit)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.IDENTIFIER, "SUB-PARA"),
            _tok(TokenType.UNTIL, "UNTIL"),
            _tok(TokenType.PERIOD, "."),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)
        assert stmt.target_paragraph == "SUB-PARA"

    def test_paragraph_until_end_of_stream(self):
        """PERFORM SUB-PARA UNTIL <eos> - end of stream (line 448)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.IDENTIFIER, "SUB-PARA"),
            _tok(TokenType.UNTIL, "UNTIL"),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)


# ---------------------------------------------------------------------------
# _parse_inline_statements (lines 486, 511-512)
# ---------------------------------------------------------------------------


class TestParseInlineStatements:
    def test_inline_perform_with_display(self):
        """Inline PERFORM with DISPLAY ... END-PERFORM."""
        src = _make_source(
            "           PERFORM UNTIL WS-I = WS-END\n"
            '               DISPLAY "HELLO"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.until_condition is not None
        assert len(stmt.inline_statements) >= 1

    def test_inline_perform_empty_body(self):
        """Inline PERFORM with empty body (END-PERFORM immediately)."""
        src = _make_source(
            "           PERFORM UNTIL WS-I = WS-END\n" "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_inline_perform_period_terminated(self):
        """Inline PERFORM terminated by period (no END-PERFORM)."""
        src = _make_source(
            "           PERFORM UNTIL WS-I = WS-END\n"
            '               DISPLAY "HELLO".\n'
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None


# ---------------------------------------------------------------------------
# _try_consume_period (lines 520-521)
# ---------------------------------------------------------------------------


class TestTryConsumePeriod:
    def test_end_perform_with_period(self):
        """END-PERFORM followed by period."""
        src = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > WS-END\n"
            '               DISPLAY "X"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_end_perform_without_period(self):
        """END-PERFORM without period (line 520-521 exception path)."""
        tokens = [
            _tok(TokenType.PERFORM, "PERFORM"),
            _tok(TokenType.UNTIL, "UNTIL"),
            _tok(TokenType.IDENTIFIER, "WS-DONE"),
            _tok(TokenType.ASSIGN, "="),
            _tok(TokenType.STRING_LITERAL, "Y"),
            _tok(TokenType.END_PERFORM, "END-PERFORM"),
        ]
        ts = TokenStream(tokens)
        parser = PerformStatementParser()
        stmt = parser.parse(ts)
        assert isinstance(stmt, PerformStatement)


# ---------------------------------------------------------------------------
# Round-trip integration tests
# ---------------------------------------------------------------------------


class TestPerformRoundTrip:
    def test_perform_varying_full(self):
        """Full PERFORM VARYING round trip."""
        src = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > 10\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        assert result.ast is not None
        stmt = _find_perform(result)
        assert stmt is not None

    def test_perform_times_inline(self):
        """PERFORM n TIMES with inline statements."""
        src = _make_source(
            "           PERFORM 3 TIMES\n"
            '               DISPLAY "HELLO"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.times_count == 3

    def test_perform_until_inline(self):
        """PERFORM UNTIL condition with inline body."""
        src = _make_source(
            "           PERFORM UNTIL WS-I > 10\n"
            "               DISPLAY WS-I\n"
            "               ADD 1 TO WS-I\n"
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.until_condition is not None

    def test_perform_simple_paragraph(self):
        """PERFORM paragraph-name."""
        src = _make_source("           PERFORM SUB-PARA.\n")
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
        assert stmt.target_paragraph == "SUB-PARA"

    def test_perform_with_test_before(self):
        """PERFORM WITH TEST BEFORE UNTIL condition."""
        src = _make_source(
            "           PERFORM WITH TEST BEFORE\n"
            "               UNTIL WS-I > 10\n"
            '               DISPLAY "LOOP"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None

    def test_perform_with_test_after(self):
        """PERFORM WITH TEST AFTER UNTIL condition."""
        src = _make_source(
            "           PERFORM WITH TEST AFTER\n"
            "               UNTIL WS-I > 10\n"
            '               DISPLAY "LOOP"\n'
            "           END-PERFORM.\n"
        )
        result = _parse(src)
        stmt = _find_perform(result)
        assert stmt is not None
