"""Edge case tests for the PERFORM statement parser.

Targets uncovered lines in cobolparser/parsers/statements/perform_parser.py:
- Lines 70-72: PERFORM at end of token stream (peek raises)
- Lines 75-80: PERFORM followed by None/PERIOD token
- Lines 109-110: Error in WITH TEST parsing
- Lines 161-162, 187-188: Edge cases in TIMES clause
- Lines 237-238, 256-257, 266-267, 280-282: VARYING clause missing clauses
- Lines 347-348, 365-367: Inline PERFORM with nested statement errors
- Lines 410-411, 429-430, 457-458, 470-471: _parse_varying_clause edge cases
- Lines 511-512, 520-521: Additional VARYING paths
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import PerformStatement


def _make_source(procedure_body: str) -> str:
    """Build a minimal fixed-format COBOL program with the given procedure body."""
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
    )


def _parse_collect_all(source: str):
    """Parse with COLLECT_ALL error recovery and return the ParseResult."""
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(source)


def _find_performs(result) -> list[PerformStatement]:
    """Extract all PerformStatement nodes from a parse result."""
    if result.ast is None:
        return []
    stmts = result.ast.find_statements("PERFORM")
    return [s for s in stmts if isinstance(s, PerformStatement)]


class TestPerformAtEndOfStream:
    """PERFORM as the very last token with nothing following it (lines 70-72)."""

    def test_perform_last_token_no_period(self):
        """PERFORM keyword with no target and no trailing period."""
        source = _make_source("           PERFORM")
        result = _parse_collect_all(source)
        # Should not crash; the parser recovers gracefully
        assert result.ast is not None

    def test_perform_at_end_after_other_statements(self):
        """PERFORM at end of stream after other valid statements."""
        source = _make_source("           DISPLAY 'HELLO'.\n" "           PERFORM")
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformFollowedByPeriod:
    """PERFORM immediately followed by a period — missing target (lines 75-80, 82-89)."""

    def test_perform_period_only(self):
        """PERFORM followed immediately by period should report an error."""
        source = _make_source("           PERFORM.\n" "           STOP RUN.")
        result = _parse_collect_all(source)
        assert result.ast is not None
        # The parser should produce an error about missing target
        assert len(result.errors) > 0

    def test_perform_period_among_other_statements(self):
        """PERFORM. embedded between valid statements."""
        source = _make_source(
            "           DISPLAY 'BEFORE'.\n"
            "           PERFORM.\n"
            "           DISPLAY 'AFTER'.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformWithNonTestToken:
    """PERFORM WITH followed by a non-TEST token (lines 109-110)."""

    def test_perform_with_no_test_keyword(self):
        """PERFORM WITH followed by something other than TEST."""
        source = _make_source(
            "           PERFORM WITH UNTIL WS-FLAG = 'Y'\n"
            "               DISPLAY 'LOOP'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_with_identifier_not_test(self):
        """PERFORM WITH followed by an identifier that is not TEST."""
        source = _make_source(
            "           PERFORM WITH BOGUS UNTIL WS-EOF = 'Y'\n"
            "               DISPLAY 'DATA'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformWithTestNonBeforeAfter:
    """PERFORM WITH TEST followed by a non-BEFORE/AFTER token (lines 104-110)."""

    def test_perform_with_test_unknown_timing(self):
        """PERFORM WITH TEST followed by an unexpected keyword."""
        source = _make_source(
            "           PERFORM WITH TEST UNTIL WS-X = 1\n"
            "               DISPLAY 'X'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_with_test_identifier(self):
        """PERFORM WITH TEST followed by a plain identifier."""
        source = _make_source(
            "           PERFORM WITH TEST MIDDLE\n"
            "               UNTIL WS-DONE = 'Y'\n"
            "               DISPLAY 'HI'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformTimesWithDataName:
    """PERFORM n TIMES where n is a data-name variable (lines 161-162, 187-188)."""

    def test_perform_variable_times_inline(self):
        """PERFORM with a variable name TIMES for inline perform."""
        source = _make_source(
            "           PERFORM WS-COUNT TIMES\n"
            "               DISPLAY 'ITERATE'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1

    def test_perform_paragraph_variable_times(self):
        """PERFORM paragraph-name WS-VAR TIMES."""
        source = _make_source(
            "           PERFORM PROCESS-PARA WS-REPEAT TIMES.\n"
            "           STOP RUN.\n"
            "       PROCESS-PARA.\n"
            "           DISPLAY 'PROCESS'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        # The times_count should be the variable name string
        stmt = performs[0]
        assert stmt.times_count == "WS-REPEAT"

    def test_perform_paragraph_numeric_literal_times(self):
        """PERFORM paragraph-name <numeric-literal> TIMES."""
        source = _make_source(
            "           PERFORM PROCESS-PARA 10 TIMES.\n"
            "           STOP RUN.\n"
            "       PROCESS-PARA.\n"
            "           DISPLAY 'RUN'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        stmt = performs[0]
        assert stmt.perform_type == "TIMES"
        assert stmt.times_count == 10


class TestPerformVaryingMissingFrom:
    """PERFORM VARYING without FROM clause (lines 303-306)."""

    def test_perform_varying_no_from(self):
        """PERFORM VARYING WS-I with no FROM clause — should recover."""
        source = _make_source(
            "           PERFORM VARYING WS-I\n"
            "               DISPLAY 'OOPS'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_varying_variable_then_period(self):
        """PERFORM VARYING WS-I followed immediately by period."""
        source = _make_source(
            "           PERFORM VARYING WS-I.\n" "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformVaryingMissingBy:
    """PERFORM VARYING X FROM 1 without BY clause (lines 318-320)."""

    def test_perform_varying_from_no_by(self):
        """PERFORM VARYING WS-I FROM 1 without BY — should recover."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1\n"
            "               DISPLAY 'MISSING-BY'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_varying_from_then_period(self):
        """PERFORM VARYING WS-I FROM 1 followed by period."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1.\n" "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformVaryingMissingUntil:
    """PERFORM VARYING X FROM 1 BY 1 without UNTIL clause (lines 353-367)."""

    def test_perform_varying_no_until(self):
        """PERFORM VARYING ... FROM ... BY ... with no UNTIL — should recover."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               DISPLAY 'NO-UNTIL'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_varying_from_by_then_period(self):
        """PERFORM VARYING WS-I FROM 1 BY 1 then period, no UNTIL."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1.\n" "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformInlineEmptyBody:
    """Inline PERFORM...END-PERFORM with empty body (lines 473-512)."""

    def test_perform_until_empty_body(self):
        """PERFORM UNTIL ... END-PERFORM with no statements inside."""
        source = _make_source(
            "           PERFORM UNTIL WS-FLAG = 'Y'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        stmt = performs[0]
        assert stmt.inline_statements == [] or stmt.inline_statements is not None

    def test_perform_times_empty_body(self):
        """PERFORM 3 TIMES END-PERFORM with no body statements."""
        source = _make_source(
            "           PERFORM 3 TIMES\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_varying_empty_body(self):
        """PERFORM VARYING ... END-PERFORM with no body."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > 5\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformUntilCompoundCondition:
    """PERFORM UNTIL with compound conditions using AND/OR (lines 369-396)."""

    def test_perform_until_with_and(self):
        """PERFORM UNTIL with AND compound condition."""
        source = _make_source(
            "           PERFORM UNTIL WS-A = 1 AND WS-B = 2\n"
            "               DISPLAY 'COMPOUND'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1

    def test_perform_until_with_or(self):
        """PERFORM UNTIL with OR compound condition."""
        source = _make_source(
            "           PERFORM UNTIL WS-EOF = 'Y' OR WS-ERR = 'Y'\n"
            "               DISPLAY 'CHECKING'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1

    def test_perform_until_complex_compound(self):
        """PERFORM UNTIL with a more complex compound condition."""
        source = _make_source(
            "           PERFORM UNTIL WS-A > 10 AND WS-B < 5\n"
            "               OR WS-DONE = 'Y'\n"
            "               DISPLAY 'COMPLEX'\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_paragraph_until_compound(self):
        """PERFORM paragraph UNTIL compound condition with AND."""
        source = _make_source(
            "           PERFORM PROCESS-PARA\n"
            "               UNTIL WS-A = 0 AND WS-B = 0.\n"
            "           STOP RUN.\n"
            "       PROCESS-PARA.\n"
            "           DISPLAY 'WORK'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        assert performs[0].target_paragraph == "PROCESS-PARA"


class TestPerformVaryingWithTestTiming:
    """PERFORM VARYING with WITH TEST BEFORE/AFTER (lines 334-348)."""

    def test_perform_varying_with_test_before(self):
        """PERFORM VARYING with WITH TEST BEFORE before UNTIL."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-I > 10\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1

    def test_perform_varying_with_test_after(self):
        """PERFORM VARYING with WITH TEST AFTER before UNTIL."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               WITH TEST AFTER\n"
            "               UNTIL WS-I > 10\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1


class TestPerformThruEdgeCases:
    """Edge cases in PERFORM ... THRU ... parsing (lines 174-188)."""

    def test_perform_thru_missing_end_paragraph(self):
        """PERFORM paragraph THRU with no ending paragraph name."""
        source = _make_source(
            "           PERFORM START-PARA THRU.\n"
            "           STOP RUN.\n"
            "       START-PARA.\n"
            "           DISPLAY 'START'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        # Should have an error about missing ending paragraph
        assert len(result.errors) > 0

    def test_perform_thru_with_times(self):
        """PERFORM paragraph THRU paragraph N TIMES."""
        source = _make_source(
            "           PERFORM START-PARA THRU END-PARA 3 TIMES.\n"
            "           STOP RUN.\n"
            "       START-PARA.\n"
            "           DISPLAY 'A'.\n"
            "       END-PARA.\n"
            "           DISPLAY 'B'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1


class TestPerformInlineNestedErrors:
    """Inline PERFORM with nested statement parsing difficulties (lines 347-348, 504-512)."""

    def test_perform_inline_with_unparseable_content(self):
        """PERFORM inline block with tokens that are not valid statements."""
        source = _make_source(
            "           PERFORM UNTIL WS-DONE = 'Y'\n"
            "               FOOBAR BAZQUX\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_inline_with_multiple_nested_statements(self):
        """PERFORM inline block with multiple valid nested statements."""
        source = _make_source(
            "           PERFORM UNTIL WS-DONE = 'Y'\n"
            "               DISPLAY 'A'\n"
            "               DISPLAY 'B'\n"
            "               MOVE 'Y' TO WS-DONE\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        stmt = performs[0]
        # Should have parsed nested statements
        assert len(stmt.inline_statements) >= 1

    def test_perform_varying_inline_no_until(self):
        """PERFORM VARYING with FROM/BY but no UNTIL, then inline body."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 1 BY 1\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformEndPerformEdgeCases:
    """END-PERFORM edge cases (lines 269-282)."""

    def test_perform_paragraph_with_end_perform(self):
        """PERFORM paragraph-name END-PERFORM (unusual but valid)."""
        source = _make_source(
            "           PERFORM SOME-PARA\n"
            "           END-PERFORM.\n"
            "           STOP RUN.\n"
            "       SOME-PARA.\n"
            "           DISPLAY 'DONE'."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None

    def test_perform_without_end_perform_or_period(self):
        """PERFORM followed by another statement (no explicit terminator)."""
        source = _make_source(
            "           PERFORM UNTIL WS-X = 1\n"
            "               DISPLAY 'LOOP'\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None


class TestPerformVaryingFromValue:
    """PERFORM VARYING edge cases for FROM value parsing (lines 310-315)."""

    def test_perform_varying_from_variable(self):
        """PERFORM VARYING with a variable as FROM value."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM WS-START BY 1\n"
            "               UNTIL WS-I > WS-END\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1

    def test_perform_varying_from_zero(self):
        """PERFORM VARYING starting FROM 0."""
        source = _make_source(
            "           PERFORM VARYING WS-I FROM 0 BY 1\n"
            "               UNTIL WS-I > 5\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM.\n"
            "           STOP RUN."
        )
        result = _parse_collect_all(source)
        assert result.ast is not None
        performs = _find_performs(result)
        assert len(performs) >= 1
        stmt = performs[0]
        if stmt.varying_clause:
            assert stmt.varying_clause["from_value"] in ("0", 0)
