"""Regression tests: witnesses for negated conditions and awkward level-88s.

Each case below used to hand back a witness that did not satisfy the arm it
was solved for (or no model at all for a perfectly ordinary condition):

* ``IF NOT <88>`` / ``IF NOT (A AND B)`` -- the parser's unary ``NOT``
  wrapper was rejected as an "unsupported logical operator", so both arms of
  the commonest negated-88 idiom went unmodeled.
* ``NOT <88>`` over ``VALUE 1 THRU 999999`` -- modeled as ``not_in_set`` over
  the first 65 expanded values, so the solver's midpoint (499999) landed
  inside the range the arm excludes. Same for a non-integer range (only its
  endpoints listed), a range over a field with decimals, and the ``WHEN
  OTHER`` of an ``EVALUATE TRUE`` whose prior ``WHEN`` is such a name.
* ``88 BLANK VALUE SPACES`` -- the figurative word was read as a literal and
  rendered ``"SPA"`` into a ``PIC X(3)``.
* ``IF X = ZEROS`` on a ``PIC X(3)`` -- witnessed as ``"0"``, which a record
  pads to ``"0  "``, not the ``"000"`` the comparison needs.
"""

from __future__ import annotations

from decimal import Decimal

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Witness, solve
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.data.layout import condition_values_exhaustive

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEGTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
"""
_MID = """\
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
"""


def _branches(fields: str, body: str):
    result = parse_cobol(_HEAD + fields + _MID + body, filename="t.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == []
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    report = ConstraintExtractor().extract(result.ast, index, boundaries)
    return report


def _solve(constraints) -> str:
    witness = solve(constraints[0].field.spec, constraints)
    assert isinstance(witness, Witness), witness
    return witness.value


class TestUnaryNot:
    def test_not_condition_name_models_both_arms(self):
        report = _branches(
            "           05  F1-STATUS  PIC X.\n"
            "               88  F1-VALID  VALUE 'A' 'B'.\n",
            "           IF NOT F1-VALID\n"
            "               DISPLAY 'BAD'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert branch.unsupported == []
        then, else_ = branch.arms["THEN"], branch.arms["ELSE"]
        assert [(c.op, c.values) for c in then] == [("not_in_set", ("A", "B"))]
        assert [(c.op, c.values) for c in else_] == [("in_set", ("A", "B"))]
        assert _solve(then) not in ("A", "B")
        assert _solve(else_) in ("A", "B")

    def test_not_of_a_conjunction_is_de_morgan(self):
        report = _branches(
            "           05  F1-QTY     PIC 9(3).\n"
            "           05  F1-CODE    PIC X.\n",
            "           IF NOT (F1-QTY > 5 AND F1-CODE = 'X')\n"
            "               DISPLAY 'NO'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert branch.unsupported == []
        # NOT (A AND B) == NOT A OR NOT B: two THEN variants, one ELSE. Each
        # variant also negates the other disjunct, so it alone selects the
        # arm (#834).
        assert [(c.op, c.values) for c in branch.arms["THEN#1"]] == [
            ("le", ("5",)),
            ("eq", ("X",)),
        ]
        assert [(c.op, c.values) for c in branch.arms["THEN#2"]] == [
            ("ne", ("X",)),
            ("gt", ("5",)),
        ]
        assert sorted((c.op, c.values) for c in branch.arms["ELSE"]) == [
            ("eq", ("X",)),
            ("gt", ("5",)),
        ]


class TestNegatedRangeConditionNames:
    def test_not_of_a_wide_thru_range_is_reported_not_mis_solved(self):
        report = _branches(
            "           05  F1-CODE    PIC 9(6).\n"
            "               88  F1-BIG   VALUE 1 THRU 999999.\n",
            "           IF NOT F1-BIG\n"
            "               DISPLAY 'ZERO'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        # The positive arm is still modeled: any listed value is in range.
        assert 1 <= Decimal(_solve(branch.arms["ELSE"])) <= 999999
        # The negated arm must not be a not_in_set over a 65-value sample,
        # whose midpoint witness sat inside the excluded range.
        assert "THEN" not in branch.arms
        assert any("NOT F1-BIG" in reason for reason in branch.unsupported)

    def test_not_of_an_alphabetic_range_is_reported(self):
        report = _branches(
            "           05  F1-C       PIC X.\n"
            "               88  F1-LETTER  VALUE 'A' THRU 'Z'.\n",
            "           IF NOT F1-LETTER\n"
            "               DISPLAY 'OTHER'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert "THEN" not in branch.arms
        assert any("NOT F1-LETTER" in reason for reason in branch.unsupported)

    def test_not_of_a_range_over_a_decimal_field_is_reported(self):
        # VALUE 1 THRU 2 on PIC 9V9 also admits 1.5, which no listing of
        # "1", "2" can exclude.
        report = _branches(
            "           05  F1-R       PIC 9V9.\n"
            "               88  F1-MID    VALUE 1 THRU 2.\n",
            "           IF NOT F1-MID\n"
            "               DISPLAY 'OUT'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert "THEN" not in branch.arms

    def test_a_small_integer_range_still_negates_exactly(self):
        report = _branches(
            "           05  F1-N       PIC 9.\n"
            "               88  F1-LOW    VALUE 1 THRU 4.\n",
            "           IF NOT F1-LOW\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert branch.unsupported == []
        witness = Decimal(_solve(branch.arms["THEN"]))
        assert not 1 <= witness <= 4

    def test_when_other_after_a_wide_range_is_not_a_sampled_not_in_set(self):
        report = _branches(
            "           05  F1-CODE    PIC 9(4).\n"
            "               88  F1-LOWC   VALUE 1 THRU 9000.\n"
            "               88  F1-HIGHC  VALUE 9500.\n",
            "           EVALUATE TRUE\n"
            "             WHEN F1-LOWC  DISPLAY 'L'\n"
            "             WHEN F1-HIGHC DISPLAY 'H'\n"
            "             WHEN OTHER    DISPLAY 'O'\n"
            "           END-EVALUATE.\n",
        )
        (branch,) = report.branches
        assert branch.arms["WHEN_OTHER"] == []
        assert any("WHEN_OTHER" in reason for reason in branch.unsupported)


class TestFigurativeConditionValues:
    def test_88_value_spaces_is_a_figurative_constraint(self):
        report = _branches(
            "           05  F1-NAME    PIC X(3).\n"
            "               88  F1-BLANK  VALUE SPACES.\n"
            "               88  F1-ZZZ    VALUE 'ZZZ'.\n",
            "           IF F1-BLANK\n"
            "               DISPLAY 'EMPTY'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        (then,) = branch.arms["THEN"]
        assert (then.op, then.values, then.negated) == (
            "figurative",
            ("SPACES",),
            False,
        )
        assert _solve(branch.arms["THEN"]).strip() == ""
        else_value = _solve(branch.arms["ELSE"])
        assert else_value.strip() != ""
        assert else_value != "SPA"

    def test_zeros_on_an_alphanumeric_field_fills_the_width(self):
        report = _branches(
            "           05  F1-Z       PIC X(3).\n",
            "           IF F1-Z = ZEROS\n"
            "               DISPLAY 'Z'\n"
            "           END-IF.\n",
        )
        (branch,) = report.branches
        assert _solve(branch.arms["THEN"]) == "000"


class TestExhaustivenessHelper:
    def test_cases(self):
        assert condition_values_exhaustive(["A", "B"], 0)
        assert condition_values_exhaustive(["1", "THROUGH:5"], 0)
        assert not condition_values_exhaustive(["1", "THROUGH:5"], 1)
        assert not condition_values_exhaustive(["1", "THROUGH:999"], 0)
        assert not condition_values_exhaustive(["A", "THROUGH:Z"], 0)
        assert not condition_values_exhaustive(["SPACES"], 0)
        assert not condition_values_exhaustive(["ALL", "X"], 0)
