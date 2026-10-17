"""Regression (#512): >>IF / >>WHEN word-form relational operators and
compile-time arithmetic.

The condition evaluator accepted only ``= <> > < >= <=``. The word forms
(``IS [NOT] GREATER [THAN]``, ``LESS [THAN]``, ``EQUAL [TO]``, ``... OR
EQUAL [TO]``) and arithmetic operands (``X + 1 = 8``) were "unsupported ...
treated as FALSE", so the ``>>ELSE`` / a later ``>>WHEN`` was compiled
instead -- a program the compiler would never build. ``>>DEFINE ... AS
2 * 3`` already evaluated arithmetic; ``>>IF`` now agrees with it.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.preprocess import preprocess_conditional_compilation


def _run(condition: str, define: str = "7") -> tuple[bool, list[str]]:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(
        f">>DEFINE X AS {define}\n"
        f">>IF {condition}\n"
        "DISPLAY 'YES'.\n"
        ">>ELSE\n"
        "DISPLAY 'NO'.\n"
        ">>END-IF\n",
        None,
        warnings=warnings,
    )
    assert ("YES" in out) is not ("NO" in out)
    return "YES" in out, warnings


class TestWordFormOperators:
    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("X GREATER THAN 5", True),
            ("X GREATER 7", False),
            ("X IS GREATER THAN 7", False),
            ("X IS EQUAL TO 7", True),
            ("X EQUAL 6", False),
            ("X IS NOT EQUAL TO 6", True),
            ("X IS NOT LESS THAN 7", True),
            ("X LESS THAN 8", True),
            ("X GREATER OR EQUAL 7", True),
            ("X GREATER THAN OR EQUAL TO 8", False),
            ("X LESS THAN OR EQUAL TO 7", True),
            ("X IS NOT GREATER THAN OR EQUAL TO 8", True),
        ],
    )
    def test_word_forms(self, condition: str, expected: bool) -> None:
        assert _run(condition) == (expected, [])

    def test_boolean_or_after_word_operator_is_still_boolean(self) -> None:
        assert _run("X GREATER 9 OR X = 7") == (True, [])
        assert _run("X LESS 5 OR X EQUAL 1") == (False, [])

    def test_symbolic_operators_unchanged(self) -> None:
        assert _run("X <= 7") == (True, [])
        assert _run("X <> 6") == (True, [])
        assert _run("X = -7") == (False, [])


class TestArithmeticOperands:
    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("X + 1 = 8", True),
            ("X * 2 = 14", True),
            ("X = 3 + 4", True),
            ("X - 1 = 6", True),
            ("X -1 = 6", True),
            ("X+1 = 8", True),
            ("-X = -7", True),
            ("(X + 1) * 2 = 16", True),
            ("(X + 1) * 2 = 15", False),
            ("X * 2 GREATER THAN 13", True),
            ("(X) = 7", True),
            ("(X = 7) AND X + 1 = 8", True),
        ],
    )
    def test_arithmetic(self, condition: str, expected: bool) -> None:
        assert _run(condition) == (expected, [])

    def test_agrees_with_define_arithmetic(self) -> None:
        assert _run("X = 2 * 3 + 1", define="2 * 3 + 1") == (True, [])

    def test_inexact_division_still_warns(self) -> None:
        selected, warnings = _run("X / 2 = 3")
        assert selected is False
        assert len(warnings) == 1 and "exact integer" in warnings[0]

    def test_undefined_symbol_in_arithmetic_warns(self) -> None:
        selected, warnings = _run("Z + 1 = 2")
        assert selected is False
        assert len(warnings) == 1 and "undefined symbol 'Z'" in warnings[0]


def test_issue_repro_keeps_big_and_arith() -> None:
    source = (
        "       >>DEFINE X AS 7\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CC3.\n"
        "       PROCEDURE DIVISION.\n"
        "       >>IF X GREATER THAN 5\n"
        "           DISPLAY 'BIG'\n"
        "       >>ELSE\n"
        "           DISPLAY 'SMALL'\n"
        "       >>END-IF\n"
        "       >>EVALUATE TRUE\n"
        "       >>WHEN X + 1 = 8\n"
        "           DISPLAY 'ARITH'\n"
        "       >>END-EVALUATE\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source)
    assert result.success
    assert result.ast is not None
    shown = [
        str(item)
        for node in result.ast.find_all_by_type("DisplayStatement")
        for item in node.to_dict()["display_items"]
    ]
    text = " ".join(shown)
    assert "BIG" in text and "ARITH" in text
    assert "SMALL" not in text
    assert result.warnings == []
