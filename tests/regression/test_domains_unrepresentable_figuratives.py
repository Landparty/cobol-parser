"""A witness for ``IF X = LOW-VALUES`` / ``HIGH-VALUES`` must not be blanks.

``domains._FIGURATIVE_VALUES`` (like ``ValueFactory``'s own table) maps
LOW-VALUES / HIGH-VALUES / NULL to "", so ``solve()`` handed back ``""`` as
the witness -- rendered space-padded, a field of blanks, never X'00' or
X'FF'. The scenario named for that arm could not reach it, while
``ScenarioCoverage`` counted it targeted. The same held for a numeric field
compared with SPACES / LOW-VALUES: the constraint was a no-op, so any number
came back as a "witness". Both are now ``Unsatisfiable`` (the arm is missed
with a reason); the negated tests narrow nothing, since every generated
value already differs.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Unsatisfiable, Witness, solve
from cobolparser.generators import ProgramLayoutIndex


def _arms(field: str, condition: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. FIGTEST.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT F1 ASSIGN TO 'F1.DAT'.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  F1.\n"
        "       01  F1-REC.\n"
        f"           05  F1-KEY  {field}.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           READ F1 END-READ\n"
        f"           IF {condition}\n"
        "               DISPLAY 'HIT'\n"
        "           ELSE\n"
        "               DISPLAY 'MISS'\n"
        "           END-IF.\n"
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    (branch,) = ConstraintExtractor().extract(result.ast, index, boundaries).branches
    return branch.arms


def _solve(constraints):
    return solve(constraints[0].field.spec, constraints)


@pytest.mark.parametrize(
    "figurative", ["LOW-VALUES", "HIGH-VALUES", "LOW-VALUE", "HIGH-VALUE"]
)
def test_positive_binary_figurative_is_unsatisfiable(figurative: str) -> None:
    arms = _arms("PIC X(4)", f"F1-KEY = {figurative}")
    assert isinstance(_solve(arms["THEN"]), Unsatisfiable)
    witness = _solve(arms["ELSE"])
    assert isinstance(witness, Witness) and witness.value.strip() != ""


def test_spaces_still_solves_to_blanks() -> None:
    arms = _arms("PIC X(4)", "F1-KEY = SPACES")
    witness = _solve(arms["THEN"])
    assert isinstance(witness, Witness) and witness.value.strip() == ""


@pytest.mark.parametrize("figurative", ["SPACES", "LOW-VALUES", "QUOTES"])
def test_numeric_field_never_equals_a_non_zero_figurative(figurative: str) -> None:
    arms = _arms("PIC 9(4)", f"F1-KEY = {figurative}")
    assert isinstance(_solve(arms["THEN"]), Unsatisfiable)
    assert isinstance(_solve(arms["ELSE"]), Witness)


def test_numeric_zero_figurative_still_solves() -> None:
    arms = _arms("PIC 9(4)", "F1-KEY = ZEROS")
    witness = _solve(arms["THEN"])
    assert isinstance(witness, Witness) and int(witness.value) == 0
