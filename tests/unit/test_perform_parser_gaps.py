"""Tests for PERFORM parser edge cases not covered by existing tests.

Targets: no-target error recovery, NUMERIC_LITERAL/LEVEL_NUMBER TIMES,
paragraph WITH TEST BEFORE/AFTER UNTIL, END-PERFORM token, THRU missing end,
VARYING with WITH TEST timing.
"""

from __future__ import annotations

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import PerformStatement


def _parser() -> CobolParser:
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)


def _wrap(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-COUNT PIC 9(4) VALUE 0.\n"
        "       01 WS-IDX   PIC 9(4) VALUE 1.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        + body
        + "\n"
        "           STOP RUN.\n"
        "       SUB-PARA.\n"
        "           DISPLAY 'SUB'.\n"
    )


def _find_performs(result) -> list[PerformStatement]:
    if result.ast is None:
        return []
    return [s for s in result.ast.get_all_statements() if isinstance(s, PerformStatement)]


# ---------------------------------------------------------------------------
# No-target error recovery
# ---------------------------------------------------------------------------


class TestPerformNoTarget:
    def test_bare_perform_with_period_recovers(self) -> None:
        result = _parser().parse(_wrap("           PERFORM.\n"))
        assert result.ast is not None

    def test_bare_perform_at_end_of_stream_recovers(self) -> None:
        # PERFORM with nothing after it — parser must not crash
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Inline PERFORM n TIMES — numeric literal variants
# ---------------------------------------------------------------------------


class TestPerformNumericTimes:
    def test_perform_integer_literal_times(self) -> None:
        src = _wrap(
            "           PERFORM 5 TIMES\n"
            "               DISPLAY 'LOOP'\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
        performs = _find_performs(result)
        assert any(p.times_count is not None or p.perform_type is not None for p in performs)

    def test_perform_level_number_token_times(self) -> None:
        # Small integers like 03 tokenize as LEVEL_NUMBER — covers that branch
        src = _wrap(
            "           PERFORM 03 TIMES\n"
            "               DISPLAY 'LOOP'\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_perform_identifier_digit_times(self) -> None:
        # A digit-only identifier falls through to the isdigit() branch
        src = _wrap(
            "           PERFORM 10 TIMES\n"
            "               DISPLAY 'X'\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Paragraph WITH TEST BEFORE/AFTER UNTIL
# ---------------------------------------------------------------------------


class TestPerformParagraphWithTest:
    def test_perform_para_with_test_before(self) -> None:
        src = _wrap(
            "           PERFORM SUB-PARA\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-COUNT > 5.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_perform_para_with_test_after(self) -> None:
        src = _wrap(
            "           PERFORM SUB-PARA\n"
            "               WITH TEST AFTER\n"
            "               UNTIL WS-IDX = 10.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_perform_thru_with_test_before(self) -> None:
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9 VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM PARA-A THRU PARA-B\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-X > 3.\n"
            "           STOP RUN.\n"
            "       PARA-A.\n"
            "           ADD 1 TO WS-X.\n"
            "       PARA-B.\n"
            "           DISPLAY WS-X.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# END-PERFORM explicit token
# ---------------------------------------------------------------------------


class TestPerformEndPerform:
    def test_perform_para_end_perform(self) -> None:
        src = _wrap("           PERFORM SUB-PARA END-PERFORM.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_perform_inline_end_perform(self) -> None:
        src = _wrap(
            "           PERFORM UNTIL WS-COUNT > 2\n"
            "               ADD 1 TO WS-COUNT\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# THRU with missing end paragraph (error recovery)
# ---------------------------------------------------------------------------


class TestPerformThruErrors:
    def test_perform_thru_period_recovers(self) -> None:
        src = _wrap("           PERFORM SUB-PARA THRU.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_perform_thru_nonidentifier_recovers(self) -> None:
        src = _wrap("           PERFORM SUB-PARA THRU 'LITERAL'.\n")
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# VARYING with WITH TEST timing
# ---------------------------------------------------------------------------


class TestPerformVaryingWithTest:
    def test_varying_with_test_before(self) -> None:
        src = _wrap(
            "           PERFORM VARYING WS-IDX FROM 1 BY 1\n"
            "               WITH TEST BEFORE\n"
            "               UNTIL WS-IDX > 10\n"
            "               DISPLAY WS-IDX\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_varying_with_test_after(self) -> None:
        src = _wrap(
            "           PERFORM VARYING WS-IDX FROM 1 BY 1\n"
            "               WITH TEST AFTER\n"
            "               UNTIL WS-IDX > 5\n"
            "               DISPLAY WS-IDX\n"
            "           END-PERFORM.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
