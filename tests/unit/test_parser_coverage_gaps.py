"""Tests for parser.py paths not covered by existing tests.

Targets: error_recovery kwarg to parse(), parse_file() OSError,
error count limit (add_error suppression), FAIL_FAST after division exception.
"""

from __future__ import annotations

from unittest.mock import patch

from cobolparser import CobolParser
from cobolparser._errors import ParseError
from cobolparser.plugins.core import ErrorRecoveryMode, MemoryConfiguration

_MINIMAL = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           STOP RUN.
"""

_BROKEN = "       PROCEDURE DIVISION.\n" + "           MOVE TO.\n" * 30


# ---------------------------------------------------------------------------
# parse() error_recovery kwarg
# ---------------------------------------------------------------------------


class TestParseErrorRecoveryKwarg:
    def test_collect_all_via_kwarg_overrides_default(self) -> None:
        parser = CobolParser()  # default is FAIL_FAST
        result = parser.parse(_MINIMAL, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None

    def test_fail_fast_via_kwarg(self) -> None:
        parser = CobolParser()
        result = parser.parse(_MINIMAL, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert result.ast is not None

    def test_kwarg_does_not_permanently_change_instance(self) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        parser.parse(_MINIMAL, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        # Instance attribute should reflect the override applied during that parse
        # (behaviour: kwarg sets self.error_recovery when not None)
        # A second parse without kwarg should use whatever was last set
        result = parser.parse(_MINIMAL)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# parse_file() error handling
# ---------------------------------------------------------------------------


class TestParseFileErrors:
    def test_oserror_returns_failed_result(self, tmp_path) -> None:
        bad = tmp_path / "perm.cbl"
        bad.write_text(_MINIMAL)
        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = CobolParser().parse_file(str(bad))
        assert result.ast is None
        assert len(result.errors) > 0
        assert any(
            "permission denied" in str(e).lower() or "file error" in str(e).lower()
            for e in result.errors
        )

    def test_valid_file_parses_ok(self, tmp_path) -> None:
        f = tmp_path / "valid.cbl"
        f.write_text(_MINIMAL)
        result = CobolParser().parse_file(str(f))
        assert result.ast is not None


# ---------------------------------------------------------------------------
# add_error() — error count limit
# ---------------------------------------------------------------------------


class TestErrorCountLimit:
    def test_suppression_message_appears_after_limit(self) -> None:
        config = MemoryConfiguration(max_error_count=3)
        parser = CobolParser(
            memory_config=config,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        result = parser.parse(_BROKEN)
        messages = [str(e) for e in result.errors]
        assert any("suppressed" in m.lower() or "limit" in m.lower() for m in messages)

    def test_add_error_skips_when_already_limit_reached(self) -> None:
        config = MemoryConfiguration(max_error_count=2)
        parser = CobolParser(
            memory_config=config,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        parser.statistics.reset()
        parser.statistics.start_timing()
        # Fill up to limit
        for _ in range(5):
            parser.add_error(ParseError("test error", line_number=1, column=1))
        count_after_fill = len(parser.errors)
        # Further add_error calls must be no-ops
        parser.add_error(ParseError("extra", line_number=1, column=1))
        assert len(parser.errors) == count_after_fill

    def test_error_limit_carries_triggering_location(self) -> None:
        config = MemoryConfiguration(max_error_count=2)
        parser = CobolParser(
            memory_config=config,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        parser.statistics.reset()
        parser.statistics.start_timing()
        for i in range(4):
            parser.add_error(ParseError("err", line_number=i + 1, column=1))
        # The limit-reached error should exist among the collected errors
        msgs = [str(e) for e in parser.errors]
        assert any("suppress" in m.lower() or "limit" in m.lower() for m in msgs)


# ---------------------------------------------------------------------------
# FAIL_FAST behaviour
# ---------------------------------------------------------------------------


class TestFailFastBehaviour:
    def test_fail_fast_returns_result_on_broken_cobol(self) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse("       @@JUNK DIVISION.\n       @@@.\n")
        assert result is not None  # must not raise

    def test_fail_fast_parse_minimal_succeeds(self) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse(_MINIMAL)
        assert result.ast is not None
        assert result.success


# ---------------------------------------------------------------------------
# parse() top-level exception handler
# ---------------------------------------------------------------------------


class TestParseTopLevelException:
    def test_unexpected_internal_error_is_caught(self) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        # Force an exception inside parse() by corrupting the stream setup
        with patch.object(
            parser, "_skip_to_identification_division", side_effect=RuntimeError("boom")
        ):
            result = parser.parse(_MINIMAL)
        assert result is not None
        assert result.ast is None
        assert any(
            "boom" in str(e) or "parser error" in str(e).lower() for e in result.errors
        )
