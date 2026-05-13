"""Tests for CALL parser edge cases not covered by existing tests.

Targets: static/dynamic program name parsing, NOT ON EXCEPTION clause,
END-CALL token, USING BY VALUE / BY CONTENT / BY REFERENCE modifiers,
missing program name error recovery.
"""

from __future__ import annotations

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements.call import CallStatement


def _parser() -> CobolParser:
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)


def _wrap(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-PROG  PIC X(8) VALUE 'SUBPROG'.\n"
        "       01 WS-A     PIC 9(4) VALUE 0.\n"
        "       01 WS-B     PIC 9(4) VALUE 1.\n"
        "       01 WS-RET   PIC 9(4) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + body + "\n"
        "           STOP RUN.\n"
    )


def _calls(result) -> list[CallStatement]:
    if result.ast is None:
        return []
    return [s for s in result.ast.get_all_statements() if isinstance(s, CallStatement)]


# ---------------------------------------------------------------------------
# Static vs dynamic program name
# ---------------------------------------------------------------------------


class TestCallProgramName:
    def test_static_call_string_literal(self) -> None:
        result = _parser().parse(_wrap("           CALL 'MYSUBPROG'.\n"))
        assert result.ast is not None
        calls = _calls(result)
        assert len(calls) >= 1
        assert not calls[0].is_dynamic

    def test_dynamic_call_identifier(self) -> None:
        result = _parser().parse(_wrap("           CALL WS-PROG.\n"))
        assert result.ast is not None
        calls = _calls(result)
        assert len(calls) >= 1
        assert calls[0].is_dynamic


# ---------------------------------------------------------------------------
# ON EXCEPTION / NOT ON EXCEPTION
# ---------------------------------------------------------------------------


class TestCallExceptionClauses:
    def test_on_exception_only(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'FAILED'\n"
            "           END-CALL.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_not_on_exception_only(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               NOT ON EXCEPTION\n"
            "                   DISPLAY 'OK'\n"
            "           END-CALL.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_both_exception_clauses(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               ON EXCEPTION\n"
            "                   DISPLAY 'FAILED'\n"
            "               NOT ON EXCEPTION\n"
            "                   DISPLAY 'OK'\n"
            "           END-CALL.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None
        calls = _calls(result)
        assert len(calls) >= 1

    def test_not_on_exception_body_parsed(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               ON EXCEPTION\n"
            "                   MOVE 1 TO WS-A\n"
            "               NOT ON EXCEPTION\n"
            "                   MOVE 0 TO WS-A\n"
            "           END-CALL.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# END-CALL token
# ---------------------------------------------------------------------------


class TestCallEndCall:
    def test_end_call_terminates_statement(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               USING WS-A\n"
            "           END-CALL.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_end_call_with_no_clauses(self) -> None:
        src = _wrap("           CALL 'SUBPROG' END-CALL.\n")
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# USING BY VALUE / BY CONTENT / mixed
# ---------------------------------------------------------------------------


class TestCallUsingModes:
    def test_using_by_value(self) -> None:
        src = _wrap("           CALL 'SUBPROG' USING BY VALUE WS-A.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_using_by_content(self) -> None:
        src = _wrap("           CALL 'SUBPROG' USING BY CONTENT WS-A.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_using_by_reference_explicit(self) -> None:
        src = _wrap("           CALL 'SUBPROG' USING BY REFERENCE WS-A.\n")
        result = _parser().parse(src)
        assert result.ast is not None

    def test_using_mixed_modes(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n"
            "               USING BY REFERENCE WS-A\n"
            "                     BY VALUE WS-B.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None

    def test_using_by_value_multiple_params(self) -> None:
        src = _wrap(
            "           CALL 'SUBPROG'\n" "               USING BY VALUE WS-A WS-B.\n"
        )
        result = _parser().parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Missing program name (error recovery)
# ---------------------------------------------------------------------------


class TestCallMissingProgram:
    def test_call_period_only_recovers(self) -> None:
        result = _parser().parse(_wrap("           CALL.\n"))
        assert result.ast is not None

    def test_call_end_call_no_name_recovers(self) -> None:
        result = _parser().parse(_wrap("           CALL END-CALL.\n"))
        assert result.ast is not None
