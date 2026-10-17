"""Regression (#567): ``>>DEFINE B AS A`` copies A's value.

IBM's ``>>DEFINE name AS arithmetic-expression`` accepts a lone compilation
variable as the expression. Only text containing an operator was evaluated,
so ``AS A + 1`` worked while ``AS A`` stored the word "A": every later
``>>IF B = 3`` compared against "A" and was silently FALSE.
"""

from __future__ import annotations

from cobolparser.preprocess import preprocess_conditional_compilation


def _run(*directives: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(
        "\n".join([*directives, "       DISPLAY 'GOOD'.", ">>END-IF"]),
        warnings=warnings,
    )
    return out.strip(), warnings


def test_define_as_a_numeric_variable_copies_its_value() -> None:
    out, warnings = _run(">>DEFINE A AS 3", ">>DEFINE B AS A", ">>IF B = 3")
    assert out == "DISPLAY 'GOOD'."
    assert warnings == []


def test_define_as_an_alphanumeric_variable_copies_its_value() -> None:
    out, warnings = _run(">>DEFINE A AS 'X'", ">>DEFINE B AS A", ">>IF B = 'X'")
    assert out == "DISPLAY 'GOOD'."
    assert warnings == []


def test_lowercase_directives_resolve_the_variable() -> None:
    out, _ = _run(">>define a as 3", ">>define b as a", ">>if b = 3")
    assert out == "DISPLAY 'GOOD'."


def test_the_copy_is_taken_at_define_time() -> None:
    out, _ = _run(">>DEFINE A AS 3", ">>DEFINE B AS A", ">>DEFINE A AS 9", ">>IF B = 3")
    assert out == "DISPLAY 'GOOD'."


def test_an_undefined_variable_warns() -> None:
    out, warnings = _run(">>DEFINE B AS Q", ">>IF B = 3")
    assert out == ""
    assert len(warnings) == 1
    assert "'Q' is not a defined compilation variable" in warnings[0]


def test_arithmetic_on_a_variable_still_evaluates() -> None:
    out, warnings = _run(">>DEFINE A AS 3", ">>DEFINE B AS A + 1", ">>IF B = 4")
    assert out == "DISPLAY 'GOOD'."
    assert warnings == []
