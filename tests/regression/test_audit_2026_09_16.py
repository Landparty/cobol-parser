"""Regressions for the defects found by the 2026-09-16 repo audit.

Two of the three are the same defect wearing different clothes: an
"exactness" check in `analysis/const_fold.py` that was itself performed in
inexact decimal arithmetic, so the gate meant to keep a fabricated value out
of a generated fixture waved it through. The third is a YAML comment-stripper
that mis-tracked a backslash escape.

Each test names the thing that used to be silently wrong, so a reappearance
is legible from the failure alone rather than from a diff.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder, _exact_divide, _fits_exactly
from cobolparser.config._yaml import YamlError, parse_yaml
from cobolparser.layout.options import DataGeneratorOptions
from cobolparser.layout.program import ProgramLayoutIndex

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_COMPUTE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FOLDT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-T   PIC S9(9)V9(9).
       PROCEDURE DIVISION.
       0000-MAIN.
           COMPUTE WS-T = %s.
           DISPLAY WS-T.
"""


def _fold_compute(expression: str) -> Decimal | str | None:
    """Fold ``COMPUTE WS-T = <expression>`` and return what the walk claims
    to know about WS-T, or None when it (correctly) poisoned the field."""
    result = parse_cobol(_COMPUTE_PROGRAM % expression, filename="foldt.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    folded = ConstantFolder().fold(result.ast, index)
    for name, value in folded.known.items():
        if name.endswith("WS-T"):
            return value
    return None


def _spec(picture: str, integer_digits: int, decimal_digits: int):
    """The FieldSpec `_fits_exactly` would be handed for `picture`."""
    from cobolparser.generators.data.copybook import parse_copybook_records
    from cobolparser.layout.fields import flatten_record

    source = f"       01  R.\n           05  F PIC {picture}.\n"
    records = parse_copybook_records(source)
    specs = flatten_record(records[0], DataGeneratorOptions())
    spec = specs[0]
    assert spec.integer_digits == integer_digits
    assert spec.decimal_digits == decimal_digits
    return spec


# ---------------------------------------------------------------------------
# const_fold: the exactness gate must not be decided in inexact arithmetic
# ---------------------------------------------------------------------------


# Each quotient is just *under* a whole number, so COBOL (which truncates
# toward zero) stores 8.999999999 / 9.999999999 -- never the round number.
# At the default 28-digit decimal precision every one of them rounds up to
# the round number, and used to be recorded as such.
@pytest.mark.parametrize(
    "expression",
    [
        "3 / 0.3333333333333333333333333333334",
        "3 / 0.33333333333333333333333333333334",
        "1 / 0.1000000000000000000000000000001",
        "7 / 0.7000000000000000000000000000001",
        "2 / 0.2000000000000000000000000000001",
    ],
)
def test_compute_divide_never_folds_a_rounded_quotient(expression: str) -> None:
    """A COMPUTE quotient that only *looks* whole after context rounding is
    poisoned, not recorded as the whole number.

    These folded to exactly 9 / 10 while the value a COBOL program stores is
    8.999999999 / 9.999999999 -- a wrong integer digit, emitted as a
    `field_equals` expectation into a generated fixture bundle.
    """
    assert _fold_compute(expression) is None


def test_compute_divide_still_folds_a_genuinely_exact_quotient() -> None:
    """The fix poisons inexact quotients only -- an exact one still folds.

    `known` holds each value already rendered through the target's PICTURE,
    so WS-T (``PIC S9(9)V9(9)``) reads back with its nine decimal places.
    """
    assert _fold_compute("10 / 4") == "2.500000000"
    assert _fold_compute("9 / 3") == "3.000000000"


def test_exact_divide_rejects_what_a_decimal_multiply_back_cannot_see() -> None:
    """`_exact_divide`'s proof of exactness must not be performed in the same
    precision as the division.

    The rounding error is by construction too small for that precision to
    represent, so `quotient * divisor` rounded straight back to `dividend`
    and the check passed for every inexact quotient it existed to catch.
    """
    dividend = Decimal(3)
    divisor = Decimal("0.3333333333333333333333333333334")

    # The old check, reproduced: it passes, which is why it was no check.
    with localcontext() as ctx:
        ctx.prec = 80
        quotient = dividend / divisor
        assert quotient * divisor == dividend
    # ... while the quotient is not actually 3 / divisor.
    assert Fraction(quotient) * Fraction(divisor) != Fraction(dividend)

    assert _exact_divide(dividend, divisor) is None
    # An exactly-representable quotient is still returned.
    assert _exact_divide(Decimal(10), Decimal(4)) == Decimal("2.5")
    assert _exact_divide(Decimal(1), Decimal(0)) is None


def test_fits_exactly_is_not_fooled_by_ambient_context_rounding() -> None:
    """`_fits_exactly` is the last gate before a value is recorded; it must
    decide over exact arithmetic.

    It scaled with `Decimal` operators, which run in the ambient 28-digit
    context: a value carrying more precision than that was silently rounded
    by the very `abs()` and `*` used to test it, so 8.999...9982 arrived
    already rounded to 9 and passed as an exact fit for PIC S9(9)V9(9).
    """
    spec = _spec("S9(9)V9(9)", 9, 9)

    with localcontext() as ctx:
        ctx.prec = 80
        just_under_nine = Decimal(3) / Decimal("0.3333333333333333333333333333334")

    assert just_under_nine < 9
    assert _fits_exactly(just_under_nine, spec) is False

    # Values that really do fit are unaffected.
    assert _fits_exactly(Decimal("8.999999999"), spec) is True
    assert _fits_exactly(Decimal("2.5"), spec) is True
    # One digit too many on the right, and one too many on the left.
    assert _fits_exactly(Decimal("1.0000000001"), spec) is False
    assert _fits_exactly(Decimal("1000000000"), spec) is False


def test_fits_exactly_rejects_non_finite_values() -> None:
    """NaN/Infinity can reach the gate through a poisoned arithmetic path;
    `Fraction()` would raise on them, so they are refused up front."""
    spec = _spec("S9(9)V9(9)", 9, 9)
    assert _fits_exactly(Decimal("NaN"), spec) is False
    assert _fits_exactly(Decimal("Infinity"), spec) is False


# ---------------------------------------------------------------------------
# _yaml: a backslash escape consumes the character after it
# ---------------------------------------------------------------------------


def test_escaped_quote_does_not_end_a_double_quoted_scalar() -> None:
    """`\\"` inside a double-quoted value must not close the string.

    The comment stripper advanced one character past a backslash instead of
    two, so the escaped quote was read on its own and closed the string it
    sat inside. With an odd number of them a later `#` looked unquoted, the
    value lost its tail, and the file failed to parse at all.
    """
    assert parse_yaml('msg: "a \\" # b"') == {"msg": 'a " # b'}
    assert parse_yaml('msg: "say \\"hi\\" # not a comment"') == {
        "msg": 'say "hi" # not a comment'
    }


def test_comment_after_a_quoted_value_is_still_stripped() -> None:
    """The fix must not swallow real trailing comments."""
    assert parse_yaml('p: "C:\\\\dir" # real comment') == {"p": "C:\\dir"}
    assert parse_yaml('msg: "a # b"  # trailing') == {"msg": "a # b"}
    assert parse_yaml("copybook_path: ./copybooks  # where they live") == {
        "copybook_path": "./copybooks"
    }


def test_unterminated_quoted_string_still_reported() -> None:
    """A genuinely unterminated string remains an error naming the line."""
    with pytest.raises(YamlError, match="unterminated quoted string"):
        parse_yaml('msg: "a b')
