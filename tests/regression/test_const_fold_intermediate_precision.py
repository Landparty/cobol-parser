"""ConstantFolder must honour IBM's fixed-point intermediate precision.

IBM Enterprise COBOL carries a division's intermediate quotient to only
``max(d1 - d2, dmax)`` decimal places and truncates the rest, before the
rest of the COMPUTE expression sees it ("Intermediate results and
arithmetic precision"). ``COMPUTE N = 7 / 2 * 2`` into ``PIC 99`` stores 6,
and ``COMPUTE PCT = A / B * 100`` stores 0 whenever A < B. The folder used
to divide exactly and emit ``field_equals N="7"`` / ``PCT="25"`` -- a wrong
value, not an absent one. A quotient needing more decimal places than
``dmax`` now poisons; one that fits (truncation a no-op) still folds.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.layout.program import ProgramLayoutIndex


def _fold(data: str, *body: str) -> dict[str, str]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PRECTEST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + "".join(f"       {line}\n" for line in data.splitlines())
        + "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + "".join(f"           {line}\n" for line in body)
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    return ConstantFolder().fold(result.ast, index).known


@pytest.mark.parametrize(
    ("data", "compute"),
    [
        # 7 / 2 truncates to 3 at dmax 0: IBM stores 6.
        ("01 N PIC 99.", "COMPUTE N = 7 / 2 * 2."),
        # 1 / 4 truncates to 0: IBM stores 0.
        ("01 N PIC 999.", "COMPUTE N = 1 / 4 * 100."),
        # Negative exponent = 1 / (2 ** 1) under the division rules: 0.
        ("01 N PIC 9(4).", "COMPUTE N = 100 * 2 ** -1."),
        # Integral data-name exponent: only dmax (1) decimal places carried,
        # so 1.5 ** 2 = 2.25 is truncated to 2.2 and IBM stores 8.8.
        ("01 E PIC 9 VALUE 2.\n01 N PIC 99V9.", "COMPUTE N = 1.5 ** E * 4."),
        # An exponent with decimal places is evaluated in floating point.
        ("01 N PIC 9V99.", "COMPUTE N = 0.7 ** 2.0."),
    ],
)
def test_truncating_intermediate_is_poisoned(data: str, compute: str) -> None:
    body = [compute, "DISPLAY N."]
    if "E PIC" in data:
        body.insert(0, "MOVE 2 TO E.")
    assert _fold(data, *body) == {}


def test_division_with_field_operands_is_poisoned() -> None:
    assert (
        _fold(
            "01 A PIC 9.\n01 B PIC 9.\n01 N PIC 999.",
            "MOVE 1 TO A.",
            "MOVE 4 TO B.",
            "COMPUTE N = A / B * 100.",
            "DISPLAY N.",
        )
        == {}
    )


@pytest.mark.parametrize(
    ("data", "compute", "expected"),
    [
        # dmax 1 (the result field): 3.5 is carried whole.
        ("01 N PIC 99V9.", "COMPUTE N = 7 / 2 * 2.", "7.0"),
        # dmax 1 (the literal 0.5 is a non-divisor operand).
        ("01 N PIC 99.", "COMPUTE N = 7 / 2 + 0.5.", "4"),
        # An exact integral quotient is untouched by truncation.
        ("01 N PIC S99.", "COMPUTE N = 8 / 4 * 2.", "4"),
        ("01 N PIC S9(4)V9.", "COMPUTE N = 100 * 2 ** -1.", "50.0"),
        # A literal exponent carries d1 * n places: exact.
        ("01 N PIC 99V99.", "COMPUTE N = 1.5 ** 2.", "2.25"),
    ],
)
def test_truncation_free_intermediate_still_folds(
    data: str, compute: str, expected: str
) -> None:
    assert _fold(data, compute, "DISPLAY N.") == {"N": expected}


def test_dividend_field_decimals_raise_dmax() -> None:
    # A PIC 9V99 dividend puts dmax at 2: 1.00 / 4 = 0.25 is carried whole.
    assert _fold(
        "01 A PIC 9V99.\n01 B PIC 9.\n01 N PIC 999.",
        "MOVE 1 TO A.",
        "MOVE 4 TO B.",
        "COMPUTE N = A / B * 100.",
        "DISPLAY N.",
    ) == {"N": "25"}
