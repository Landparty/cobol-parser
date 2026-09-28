"""Regression: >>DEFINE / >>IF literal handling.

- A literal's contents are case-sensitive: ``>>DEFINE X AS 'abc'`` then
  ``>>IF X = 'ABC'`` is FALSE (the whole directive line used to be
  upper-cased, so it read as TRUE).
- A negative numeric literal (``-1``) and a literal with a doubled delimiter
  (``'O''BRIEN'``) are legal operands of both ``>>DEFINE`` and ``>>IF``;
  they used to make the condition unparseable (FALSE with a warning).
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.preprocess import preprocess_conditional_compilation


def _run(source: str, defined=None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(source, defined, warnings=warnings)
    return out, warnings


def _guarded(define: str, condition: str) -> str:
    return (
        f">>DEFINE X AS {define}\n"
        f">>IF {condition}\n"
        "DISPLAY 'YES'.\n"
        ">>ELSE\n"
        "DISPLAY 'NO'.\n"
        ">>END-IF\n"
    )


class TestLiteralCase:
    @pytest.mark.parametrize(
        ("define", "condition", "expected"),
        [
            ("'abc'", "X = 'ABC'", False),
            ("'abc'", "X = 'abc'", True),
            ("'abc'", "X <> 'ABC'", True),
            ('"Mixed"', 'X = "Mixed"', True),
            ('"Mixed"', 'X = "MIXED"', False),
        ],
    )
    def test_literal_contents_are_case_sensitive(self, define, condition, expected):
        out, warnings = _run(_guarded(define, condition))
        assert ("YES" in out) is expected
        assert ("NO" in out) is not expected
        assert warnings == []

    def test_keywords_and_names_stay_case_insensitive(self):
        out, warnings = _run(
            ">>define env as 'Prod'\n>>if Env = 'Prod' and env is defined\n"
            "DISPLAY 'YES'.\n>>end-if\n"
        )
        assert "YES" in out
        assert warnings == []

    def test_evaluate_when_literal_is_case_sensitive(self):
        out, warnings = _run(
            ">>DEFINE X AS 'abc'\n>>EVALUATE X\n>>WHEN 'ABC'\nDISPLAY 'UP'.\n"
            ">>WHEN 'abc'\nDISPLAY 'LOW'.\n>>END-EVALUATE\n"
        )
        assert "LOW" in out
        assert "UP" not in out
        assert warnings == []

    def test_quoted_caller_value_keeps_case(self):
        out, _ = _run(">>IF ENV = 'PROD'\nDISPLAY 'P'.\n>>END-IF\n", {"ENV": "'prod'"})
        assert "DISPLAY 'P'." not in out
        out, _ = _run(">>IF ENV = 'prod'\nDISPLAY 'P'.\n>>END-IF\n", {"ENV": "'prod'"})
        assert "DISPLAY 'P'." in out

    def test_full_parse_takes_else_branch(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       PROCEDURE DIVISION.\n"
            "       >>DEFINE X AS 'abc'\n"
            "       >>IF X = 'ABC'\n"
            '           DISPLAY "YES"\n'
            "       >>ELSE\n"
            '           DISPLAY "NO"\n'
            "       >>END-IF\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(source)
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert [d.display_items for d in displays] == [['"NO"']]
        assert result.warnings == []


class TestNegativeAndDoubledQuoteLiterals:
    @pytest.mark.parametrize(
        ("define", "condition", "expected"),
        [
            ("-1", "X = -1", True),
            ("-1", "X < 0", True),
            ("-1", "X = 1", False),
            ("5", "X > -3", True),
            ("+2", "X = 2", True),
            ("'O''BRIEN'", "X = 'O''BRIEN'", True),
            ("'O''BRIEN'", "X = 'OBRIEN'", False),
            ('"SAY ""HI"""', 'X = "SAY ""HI"""', True),
            ("'O''BRIEN'", 'X = "O\'BRIEN"', True),
        ],
    )
    def test_condition(self, define, condition, expected):
        out, warnings = _run(_guarded(define, condition))
        assert ("YES" in out) is expected
        assert ("NO" in out) is not expected
        assert warnings == []

    def test_doubled_quote_value_is_undoubled(self):
        # A comparison against the single-quoted form proves the stored
        # value is O'BRIEN, not O''BRIEN.
        out, warnings = _run(_guarded("'O''BRIEN'", 'X = "O\'BRIEN"'))
        assert "YES" in out
        assert warnings == []
