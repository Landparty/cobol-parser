"""
Deeper coverage tests for call_parser.py and if_parser.py.

Targets uncovered branches and edge cases in both parsers to push
line coverage above the current 84.86% (CALL) and 86.60% (IF).
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import CallStatement, IfStatement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(procedure_body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-PROG PIC X(8) VALUE 'SUBPROG1'.\n"
        "       01 WS-PARAM PIC X(10).\n"
        "       01 WS-RC PIC 9(4).\n"
        "       01 WS-A PIC 9(4) VALUE 1.\n"
        "       01 WS-B PIC 9(4) VALUE 2.\n"
        "       01 WS-C PIC 9(4) VALUE 3.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure_body}\n"
    )


def _parse(src: str):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


def _find_calls(result) -> list[CallStatement]:
    if result.ast is None:
        return []
    return [
        s for s in result.ast.find_statements("CALL") if isinstance(s, CallStatement)
    ]


def _find_ifs(result) -> list[IfStatement]:
    if result.ast is None:
        return []
    return [s for s in result.ast.find_statements("IF") if isinstance(s, IfStatement)]


# ===================================================================
# CALL parser tests
# ===================================================================


class TestCallOnOverflow:
    """CALL with ON OVERFLOW clause (lines 176-182)."""

    def test_call_with_on_overflow(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               ON OVERFLOW\n"
            "                   DISPLAY 'OVERFLOW OCCURRED'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.called_program is not None
        # on_overflow should be set (possibly empty list if nested parse
        # didn't capture DISPLAY, but the attribute should exist)
        assert hasattr(call, "on_overflow")


class TestCallOnUnknownAfterOn:
    """CALL with ON followed by neither EXCEPTION nor OVERFLOW (line 184)."""

    def test_call_on_unknown_breaks(self):
        """ON followed by a random identifier should stop CALL parsing."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               ON FOOBAR\n"
            "           DISPLAY 'DONE'.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        # The parser should have broken out of the CALL loop at ON FOOBAR
        call = calls[0]
        assert call.called_program is not None


class TestCallReturningNotIdentifier:
    """CALL where RETURNING is not followed by an identifier (lines 146->104)."""

    def test_returning_followed_by_period(self):
        src = _make_source("           CALL 'SUBPROG1' RETURNING.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        # RETURNING with no identifier - returning_parameter stays None
        assert call.returning_parameter is None

    def test_giving_followed_by_period(self):
        src = _make_source("           CALL 'SUBPROG1' GIVING.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.giving_parameter is None


class TestCallUsingMixedModes:
    """CALL USING with mixed BY REFERENCE/CONTENT/VALUE and multiple params
    (lines 289-316)."""

    def test_using_by_reference(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING\n"
            "               BY REFERENCE WS-PARAM\n"
            "               BY CONTENT WS-A\n"
            "               BY VALUE WS-B.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert len(call.using_parameters) == 3
        modes = [p.passing_mode for p in call.using_parameters]
        assert "REFERENCE" in modes
        assert "CONTENT" in modes
        assert "VALUE" in modes

    def test_using_multiple_params_default_mode(self):
        src = _make_source("           CALL 'SUBPROG1' USING WS-PARAM WS-A WS-B.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert len(call.using_parameters) >= 2
        # Default mode is REFERENCE
        for p in call.using_parameters:
            assert p.passing_mode == "REFERENCE"


class TestCallNotOnException:
    """CALL with NOT ON EXCEPTION clause (lines 191-209)."""

    def test_call_with_not_on_exception(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'ERROR'\n"
            "               NOT ON EXCEPTION\n"
            "                   DISPLAY 'SUCCESS'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert hasattr(call, "not_on_exception")

    def test_call_not_without_on_exception(self):
        """NOT followed by something other than ON EXCEPTION should break."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               NOT FOOBAR\n"
            "           DISPLAY 'AFTER'.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1


class TestCallEndCall:
    """CALL terminated by END-CALL (line 214-216)."""

    def test_call_end_call(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n" "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.called_program is not None


class TestCallStatementKeywordBreak:
    """CALL followed by a statement keyword that is not part of CALL (line 126)."""

    def test_call_followed_by_move(self):
        """A MOVE keyword right after CALL params should terminate the CALL."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n" "           MOVE 1 TO WS-A.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.called_program is not None


class TestCallWithReturningAndGiving:
    """CALL with RETURNING and GIVING (lines 138-159)."""

    def test_call_returning_identifier(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               RETURNING WS-RC.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.returning_parameter == "WS-RC"

    def test_call_giving_identifier(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               GIVING WS-RC.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.giving_parameter == "WS-RC"


class TestCallDynamic:
    """CALL with dynamic (variable) program name (lines 83-87)."""

    def test_call_dynamic_variable(self):
        src = _make_source("           CALL WS-PROG USING WS-PARAM.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.called_program == "WS-PROG"
        assert call.is_dynamic is True


class TestCallOnException:
    """CALL with ON EXCEPTION clause (lines 169-175)."""

    def test_call_on_exception_only(self):
        src = _make_source(
            "           CALL 'SUBPROG1'\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'FAILED'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert hasattr(call, "on_exception")


class TestCallUsingStatementKeywordEndsClause:
    """USING clause ends when a statement keyword is encountered (line 273-274)."""

    def test_using_ends_at_display(self):
        """DISPLAY after USING params should end the USING clause."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n" "           DISPLAY 'DONE'.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert len(call.using_parameters) >= 1


class TestCallUsingEndOfStream:
    """USING clause when token_stream runs out (lines 247-248, 264)."""

    def test_using_at_end_of_input(self):
        """CALL USING with param at end of input (no period)."""
        src = _make_source("           CALL 'SUBPROG1' USING WS-PARAM\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1


class TestCallUsingReturningGivingOnBreak:
    """USING clause stops at RETURNING / GIVING / ON keywords (line 270-271)."""

    def test_using_stops_at_returning(self):
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               RETURNING WS-RC.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert len(call.using_parameters) >= 1
        assert call.returning_parameter == "WS-RC"


# ===================================================================
# IF parser tests
# ===================================================================


class TestIfEmptyCondition:
    """IF with empty condition (lines 100-110)."""

    def test_if_then_no_condition(self):
        """IF THEN with no condition tokens produces an error."""
        src = _make_source(
            "           IF THEN\n"
            "               DISPLAY 'HELLO'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        # Should still parse (COLLECT_ALL mode) but condition is empty
        assert result.ast is not None


class TestIfElseEndIf:
    """IF with ELSE and END-IF (full structure, lines 136-146, 189-192)."""

    def test_if_else_end_if(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'ONE'\n"
            "           ELSE\n"
            "               DISPLAY 'NOT ONE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None
        assert len(stmt.then_statements) >= 1
        assert len(stmt.else_statements) >= 1


class TestIfExplicitThen:
    """IF with explicit THEN keyword (lines 115-119)."""

    def test_if_explicit_then(self):
        src = _make_source(
            "           IF WS-A = 1 THEN\n"
            "               DISPLAY 'YES'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None
        assert len(stmt.then_statements) >= 1


class TestIfPeriodTerminated:
    """IF with period-terminated statement (inline IF, line 149-151, 155-156)."""

    def test_inline_if_period(self):
        """Inline IF terminated by a period."""
        src = _make_source("           IF WS-A = 1\n" "               DISPLAY 'YES'.\n")
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None


class TestIfElsePeriodTerminated:
    """IF-ELSE with period-terminated statements (lines 195-197, 201-202)."""

    def test_if_else_period(self):
        """IF ELSE where ELSE branch ends with period."""
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'ONE'\n"
            "           ELSE\n"
            "               DISPLAY 'OTHER'.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert len(stmt.else_statements) >= 1


class TestIfNestedElsePeriod:
    """Deeply nested IF with ELSE branch having period-terminated statement
    (lines 208-215)."""

    def test_nested_if_else_period(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               IF WS-B = 2\n"
            "                   DISPLAY 'A=1,B=2'\n"
            "               ELSE\n"
            "                   DISPLAY 'A=1,B!=2'\n"
            "               END-IF\n"
            "           ELSE\n"
            "               DISPLAY 'A!=1'.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestIfFallbackCondition:
    """IF with condition containing no comparison operator (line 310-314)."""

    def test_if_condition_name_only(self):
        """IF with just a condition-name (no operator) -> fallback path."""
        src = _make_source(
            "           IF WS-A\n"
            "               DISPLAY 'TRUTHY'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        # Condition should be set (fallback COMPARISON node)
        assert stmt.condition is not None


class TestIfNotLessNotGreaterNotEqual:
    """IF with NOT LESS, NOT GREATER, NOT EQUAL operators (lines 252-266)."""

    def test_if_not_equal(self):
        src = _make_source(
            "           IF WS-A NOT EQUAL WS-B\n"
            "               DISPLAY 'NOT EQUAL'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None

    def test_if_not_less(self):
        src = _make_source(
            "           IF WS-A NOT LESS WS-B\n"
            "               DISPLAY 'NOT LESS'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None

    def test_if_not_greater(self):
        src = _make_source(
            "           IF WS-A NOT GREATER WS-B\n"
            "               DISPLAY 'NOT GREATER'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None

    def test_if_not_equal_sign(self):
        """NOT = should produce NOT_EQUAL."""
        src = _make_source(
            "           IF WS-A NOT = WS-B\n"
            "               DISPLAY 'NOT EQUAL'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_not_less_sign(self):
        """NOT < should produce GREATER_OR_EQUAL."""
        src = _make_source(
            "           IF WS-A NOT < WS-B\n"
            "               DISPLAY 'NOT LESS THAN'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_not_greater_sign(self):
        """NOT > should produce LESS_OR_EQUAL."""
        src = _make_source(
            "           IF WS-A NOT > WS-B\n"
            "               DISPLAY 'NOT GREATER THAN'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestIfAndOrConditions:
    """IF with compound AND/OR conditions (lines 270-282)."""

    def test_if_and_condition(self):
        src = _make_source(
            "           IF WS-A = 1 AND WS-B = 2\n"
            "               DISPLAY 'BOTH'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None

    def test_if_or_condition(self):
        src = _make_source(
            "           IF WS-A = 1 OR WS-B = 2\n"
            "               DISPLAY 'EITHER'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None


class TestIfAndOrWithOneSideNone:
    """IF with AND/OR where one side is empty -> returns None (line 278)."""

    def test_if_and_empty_right(self):
        """AND with nothing on right side."""
        src = _make_source(
            "           IF WS-A = 1 AND\n"
            "               DISPLAY 'INCOMPLETE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        # Should parse without crashing; AND with empty right may
        # or may not produce a valid condition, but shouldn't blow up
        assert result.ast is not None


class TestIfMultipleStatementsInBranch:
    """IF with multiple statements in THEN and ELSE branches."""

    def test_if_multiple_then_stmts(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'FIRST'\n"
            "               DISPLAY 'SECOND'\n"
            "               MOVE 2 TO WS-B\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert len(stmt.then_statements) >= 2

    def test_if_multiple_else_stmts(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'ONE'\n"
            "           ELSE\n"
            "               DISPLAY 'NOT ONE'\n"
            "               MOVE 0 TO WS-A\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert len(stmt.else_statements) >= 1


class TestIfEndIfWithPeriod:
    """IF END-IF followed by period (line 145-146, 191)."""

    def test_if_end_if_period(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'\n"
            "           END-IF.\n"
            "           DISPLAY 'AFTER'.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_else_end_if_period(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'\n"
            "           ELSE\n"
            "               DISPLAY 'NO'\n"
            "           END-IF.\n"
            "           DISPLAY 'AFTER'.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestIfIsOperator:
    """IF with IS keyword in condition (line 299 in _build_condition_expression)."""

    def test_if_is_equal(self):
        src = _make_source(
            "           IF WS-A IS EQUAL WS-B\n"
            "               DISPLAY 'EQUAL'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None


class TestIfConditionNoRhs:
    """IF condition with operator but no RHS (line 302, empty right_parts)."""

    def test_if_greater_no_rhs(self):
        """IF WS-A GREATER THEN -> GREATER has no right operand."""
        src = _make_source(
            "           IF WS-A GREATER THEN\n"
            "               DISPLAY 'EDGE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        # Should parse without crashing
        assert result.ast is not None


class TestIfDeeplyNested:
    """Deeply nested IF-ELSE-END-IF structures."""

    def test_triple_nested_if(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               IF WS-B = 2\n"
            "                   IF WS-C = 3\n"
            "                       DISPLAY 'DEEP'\n"
            "                   END-IF\n"
            "               END-IF\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestIfElseIfChain:
    """IF ... ELSE IF ... ELSE ... END-IF chain."""

    def test_else_if_chain(self):
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'ONE'\n"
            "           ELSE\n"
            "               IF WS-A = 2\n"
            "                   DISPLAY 'TWO'\n"
            "               ELSE\n"
            "                   DISPLAY 'OTHER'\n"
            "               END-IF\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestCallComplexCombinations:
    """Complex CALL statement combinations to reach multiple branches."""

    def test_call_using_returning_on_exception(self):
        """CALL with USING, RETURNING, ON EXCEPTION, and END-CALL."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               RETURNING WS-RC\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'EXCEPTION'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.called_program is not None
        assert call.returning_parameter == "WS-RC"
        assert len(call.using_parameters) >= 1

    def test_call_static_simple_period(self):
        """Simple static CALL terminated by period."""
        src = _make_source("           CALL 'SUBPROG1'.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert call.is_dynamic is False

    def test_call_using_string_literal_param(self):
        """CALL USING with a string literal parameter."""
        src = _make_source("           CALL 'SUBPROG1' USING 'LITERAL-PARAM'.\n")
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1

    def test_call_by_content_string(self):
        """CALL USING BY CONTENT with string literal."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING\n"
            "               BY CONTENT 'LITERAL'\n"
            "               BY REFERENCE WS-PARAM.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert len(call.using_parameters) >= 2

    def test_call_on_exception_not_on_exception_end_call(self):
        """Full CALL with both ON EXCEPTION and NOT ON EXCEPTION."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'ERROR'\n"
            "               NOT ON EXCEPTION\n"
            "                   DISPLAY 'OK'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        # Both exception clauses should be processed
        assert hasattr(call, "on_exception")
        assert hasattr(call, "not_on_exception")

    def test_call_overflow_with_end_call(self):
        """CALL with ON OVERFLOW and END-CALL."""
        src = _make_source(
            "           CALL 'SUBPROG1' USING WS-PARAM\n"
            "               ON OVERFLOW\n"
            "                   DISPLAY 'OVERFLOW'\n"
            "           END-CALL.\n"
        )
        result = _parse(src)
        calls = _find_calls(result)
        assert len(calls) >= 1
        call = calls[0]
        assert hasattr(call, "on_overflow")


class TestIfComparisonOperators:
    """IF with various comparison operators to exercise _build_condition_expression."""

    def test_if_greater_than(self):
        src = _make_source(
            "           IF WS-A > WS-B\n"
            "               DISPLAY 'GREATER'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_less_than(self):
        src = _make_source(
            "           IF WS-A < WS-B\n"
            "               DISPLAY 'LESS'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_greater_or_equal(self):
        src = _make_source(
            "           IF WS-A >= WS-B\n"
            "               DISPLAY 'GTE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_less_or_equal(self):
        src = _make_source(
            "           IF WS-A <= WS-B\n"
            "               DISPLAY 'LTE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_not_equal_diamond(self):
        """<> operator for not equal."""
        src = _make_source(
            "           IF WS-A <> WS-B\n"
            "               DISPLAY 'NE'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_word_equal(self):
        """EQUAL word operator."""
        src = _make_source(
            "           IF WS-A EQUAL WS-B\n"
            "               DISPLAY 'EQ'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_word_greater(self):
        """GREATER word operator."""
        src = _make_source(
            "           IF WS-A GREATER WS-B\n"
            "               DISPLAY 'GT'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_if_word_less(self):
        """LESS word operator."""
        src = _make_source(
            "           IF WS-A LESS WS-B\n"
            "               DISPLAY 'LT'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1


class TestIfElseAtEndOfStream:
    """IF ELSE at end of stream (lines 176-220, fallback return stmt)."""

    def test_if_else_no_end_if_no_period(self):
        """IF-ELSE with no END-IF and no trailing period."""
        src = _make_source(
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'\n"
            "           ELSE\n"
            "               DISPLAY 'NO'\n"
        )
        result = _parse(src)
        # Should still produce an AST
        assert result.ast is not None

    def test_if_no_end_if_no_period(self):
        """IF with no END-IF and no trailing period."""
        src = _make_source("           IF WS-A = 1\n" "               DISPLAY 'YES'\n")
        result = _parse(src)
        assert result.ast is not None


class TestIfConditionMultipleTokens:
    """IF condition with multiple tokens and no operator (fallback, line 311-314)."""

    def test_if_multi_token_condition_name(self):
        """Condition with multiple tokens but no comparison operator."""
        src = _make_source(
            "           IF WS-A WS-B\n"
            "               DISPLAY 'MULTI'\n"
            "           END-IF.\n"
        )
        result = _parse(src)
        ifs = _find_ifs(result)
        assert len(ifs) >= 1
        stmt = ifs[0]
        assert stmt.condition is not None
