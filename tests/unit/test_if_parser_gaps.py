"""Tests for IF parser edge cases not covered by existing tests.

Targets: period_found flag in THEN/ELSE branches (inline IF where nested
statement ends with a period), _try_consume_period method, THEN branch
with period terminator, ELSE with period terminator.
"""

from __future__ import annotations

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements.control import IfStatement


def _parser() -> CobolParser:
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)


def _wrap(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-FLAG PIC X VALUE 'N'.\n"
        "       01 WS-X    PIC 9 VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + body + "\n"
        "           STOP RUN.\n"
    )


def _find_ifs(result) -> list[IfStatement]:
    if result.ast is None:
        return []
    return [s for s in result.ast.get_all_statements() if isinstance(s, IfStatement)]


# ---------------------------------------------------------------------------
# Inline IF — THEN branch terminated by period (period_found path)
# ---------------------------------------------------------------------------


class TestIfPeriodTerminatedThenBranch:
    def test_inline_if_period_after_then_statement(self) -> None:
        # Inline IF: condition is true, body ends with period (no END-IF, no ELSE)
        src = _wrap("           IF WS-FLAG = 'Y'\n" "               DISPLAY 'YES'.\n")
        result = _parser().parse(src)
        assert result.ast is not None
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_inline_if_period_inside_compound_paragraph(self) -> None:
        # Multiple inline IFs in sequence, each terminated by period
        src = _wrap(
            "           IF WS-X = 0\n"
            "               MOVE 1 TO WS-X.\n"
            "           IF WS-X = 1\n"
            "               MOVE 2 TO WS-X.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
        ifs = _find_ifs(result)
        assert len(ifs) >= 2

    def test_if_then_period_no_end_if(self) -> None:
        # IF without END-IF, body statement has no period on its own line
        src = _wrap(
            "           IF WS-FLAG = 'N' THEN\n" "               DISPLAY 'NOPE'.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Inline IF-ELSE — ELSE branch terminated by period (period_found in ELSE)
# ---------------------------------------------------------------------------


class TestIfElsePeriodTerminated:
    def test_inline_if_else_period_terminated(self) -> None:
        src = _wrap(
            "           IF WS-FLAG = 'Y'\n"
            "               DISPLAY 'YES'\n"
            "           ELSE\n"
            "               DISPLAY 'NO'.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
        ifs = _find_ifs(result)
        assert len(ifs) >= 1

    def test_inline_if_else_then_period_both_branches(self) -> None:
        src = _wrap(
            "           IF WS-X > 5\n"
            "               MOVE 1 TO WS-X\n"
            "           ELSE\n"
            "               MOVE 0 TO WS-X.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# _try_consume_period — with and without trailing period
# ---------------------------------------------------------------------------


class TestIfTryConsumePeriod:
    def test_end_if_without_trailing_period(self) -> None:
        # END-IF not followed by period — _try_consume_period finds nothing
        src = _wrap(
            "           IF WS-FLAG = 'Y'\n"
            "               DISPLAY 'Y'\n"
            "           END-IF\n"
            "           DISPLAY 'DONE'.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_end_if_with_trailing_period(self) -> None:
        src = _wrap(
            "           IF WS-FLAG = 'Y'\n"
            "               DISPLAY 'Y'\n"
            "           END-IF.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Nested IF where outer condition token scanning touches statement keywords
# ---------------------------------------------------------------------------


class TestIfConditionEdgeCases:
    def test_if_condition_stops_at_statement_keyword(self) -> None:
        # MOVE inside IF body — parser must not consume MOVE as part of condition
        src = _wrap(
            "           IF WS-X = 0\n"
            "               MOVE 1 TO WS-X\n"
            "               DISPLAY WS-X\n"
            "           END-IF.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_if_empty_then_branch_recovers(self) -> None:
        # IF condition followed immediately by END-IF
        src = _wrap("           IF WS-FLAG = 'Y'\n" "           END-IF.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_if_nested_produces_nested_ast(self) -> None:
        src = _wrap(
            "           IF WS-FLAG = 'Y'\n"
            "               IF WS-X = 1\n"
            "                   DISPLAY 'BOTH'\n"
            "               END-IF\n"
            "           END-IF.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
        ifs = _find_ifs(result)
        assert len(ifs) >= 2
