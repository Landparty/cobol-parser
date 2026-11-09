"""Regression tests for the 2026-08-12 bug-review findings.

Pins the fixes for:

1. Decimal precision through the witness pipeline -- ``domains.solve()``
   and ``ValueFactory.render()`` used float64 internally, so any literal
   past ~16 significant digits (PIC 9(17)/9(18)) was silently rounded and
   the generated fixture could never reach the branch its scenario claimed
   to target (``eq 123456789012345678`` rendered ``123456789012345680``
   while ScenarioCoverage still reported the arm as targeted).
2. ``COMPUTE ... ** ...`` serialized its expression text as ``* *``.
3. ``DivideStatement`` dropped the BY/INTO distinction, making every
   DIVIDE unevaluable from the AST (const_fold poisoned all of them).
4. Statement-text fidelity: typed literals (``X"41"``) lost their prefix
   in MOVE/DISPLAY text, and reference modification gained spaces
   (``WS-X(2 : 3)``).
"""

import json
import random

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.analysis.domains import Witness, solve
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.scenarios import _picture_ceiling
from cobolparser.layout.fields import FieldCategory, FieldSpec
from cobolparser.layout.options import DataGeneratorOptions
from cobolparser.layout.program import ResolvedField
from cobolparser.layout.values import ValueFactory
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem

WIDE_LITERAL = "123456789012345678"  # 18 digits: exceeds float64's mantissa

BIG_ID_PROGRAM = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIGNUM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO 'ACCT'
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-FILE.
       01  ACCT-REC.
           05  ACCT-ID      PIC 9(18).
           05  ACCT-NAME    PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-STATUS        PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCT-FILE.
           READ ACCT-FILE
               AT END MOVE 'Y' TO WS-STATUS
           END-READ.
           IF ACCT-ID = {WIDE_LITERAL}
               DISPLAY 'MATCH'
           ELSE
               DISPLAY 'NO MATCH'
           END-IF.
           CLOSE ACCT-FILE.
           STOP RUN.
"""

FOLD_HEADER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-R PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _numeric_spec(integer_digits, decimal_digits=0, is_signed=False):
    return FieldSpec(
        name="WS-N",
        path=("WS-REC", "WS-N"),
        column="WS-N",
        level=5,
        picture=f"9({integer_digits})",
        usage="DISPLAY",
        category=FieldCategory.NUMERIC,
        size=integer_digits + decimal_digits,
        integer_digits=integer_digits,
        decimal_digits=decimal_digits,
        is_signed=is_signed,
    )


def _constraint(spec, op, values):
    record = CobolDataItem(name="WS-REC", level=1, location=SourceLocation(1, 1))
    return FieldConstraint(
        field=ResolvedField(spec=spec, section="working_storage", record=record),
        op=op,
        values=values,
        origin="TEST",
    )


class TestWideNumericPrecision:
    """Finding 1: float64 in the witness pipeline corrupted wide literals."""

    def test_render_preserves_18_digit_literal(self):
        factory = ValueFactory(random.Random(0), DataGeneratorOptions())
        spec = _numeric_spec(18)
        assert factory.render(spec, WIDE_LITERAL) == WIDE_LITERAL

    def test_render_preserves_signed_17_digit_literal(self):
        factory = ValueFactory(random.Random(0), DataGeneratorOptions())
        spec = _numeric_spec(17, is_signed=True)
        assert factory.render(spec, "-12345678901234567") == "-12345678901234567"

    def test_render_preserves_wide_decimal_literal(self):
        factory = ValueFactory(random.Random(0), DataGeneratorOptions())
        spec = _numeric_spec(15, decimal_digits=2)
        assert factory.render(spec, "123456789012345.67") == "123456789012345.67"

    def test_render_still_clamps_overflow(self):
        factory = ValueFactory(random.Random(0), DataGeneratorOptions())
        assert factory.render(_numeric_spec(3), "12345") == "999"

    def test_render_still_strips_sign_for_unsigned(self):
        factory = ValueFactory(random.Random(0), DataGeneratorOptions())
        assert factory.render(_numeric_spec(4), "-25") == "25"

    def test_solve_eq_wide_literal_is_exact(self):
        spec = _numeric_spec(18)
        result = solve(spec, [_constraint(spec, "eq", (WIDE_LITERAL,))])
        assert isinstance(result, Witness)
        assert result.value == WIDE_LITERAL

    def test_solve_gt_at_picture_ceiling_is_exact(self):
        spec = _numeric_spec(18)
        result = solve(spec, [_constraint(spec, "gt", ("999999999999999998",))])
        assert isinstance(result, Witness)
        assert result.value == "999999999999999999"

    def test_picture_ceiling_never_scientific_notation(self):
        # str(float(10**18 - 1)) is '1e+18': wrong value AND a notation the
        # solver mis-parses.
        assert _picture_ceiling(_numeric_spec(18)) == "999999999999999999"
        assert _picture_ceiling(_numeric_spec(2, decimal_digits=2)) == "99.99"

    def test_generated_fixture_actually_reaches_the_targeted_arm(self):
        """End-to-end: the THEN scenario's READ rows carry the literal
        exactly, so the fixture can actually take the branch that
        ScenarioCoverage reports as targeted."""
        result = parse_cobol(BIG_ID_PROGRAM)
        assert result.errors == []
        index = ProgramLayoutIndex.build(result.ast)
        boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        bundle = ProgramFixtureGenerator().generate_with_scenarios(
            result.ast, index, boundary_report, mode="branches", seed=7
        )
        data = json.loads(bundle.to_json())
        then_scenarios = [s for s in data["scenarios"] if "THEN" in s["name"]]
        assert then_scenarios, [s["name"] for s in data["scenarios"]]
        read_fixtures = [
            f for f in then_scenarios[0]["fixtures"] if f["category"] == "READ"
        ]
        assert read_fixtures
        for row in read_fixtures[0]["sequence"]:
            assert row["ACCT-ID"] == WIDE_LITERAL


class TestComputePowerSerialization:
    """Finding 2: `**` used to serialize as `* *`."""

    def test_power_operator_round_trips(self):
        source = FOLD_HEADER + "           COMPUTE WS-A = 2 ** 3 + 1.\n"
        result = parse_cobol(source)
        assert result.errors == []
        compute = result.ast.find_all_by_type("ComputeStatement")[0]
        assert compute.expression == "2 ** 3 + 1"
        assert "* *" not in compute.to_dict()["expression"]

    def test_plain_multiply_unchanged(self):
        source = FOLD_HEADER + "           COMPUTE WS-A = WS-B * 2.\n"
        result = parse_cobol(source)
        compute = result.ast.find_all_by_type("ComputeStatement")[0]
        assert compute.expression == "WS-B * 2"


class TestDivideMode:
    """Finding 3: DivideStatement dropped the BY/INTO distinction."""

    @pytest.mark.parametrize(
        ("statement", "mode"),
        [
            ("DIVIDE WS-A BY 3 GIVING WS-B.", "BY"),
            ("DIVIDE 3 INTO WS-A GIVING WS-B.", "INTO"),
            ("DIVIDE 3 INTO WS-A.", "INTO"),
        ],
    )
    def test_division_mode_recorded_and_serialized(self, statement, mode):
        result = parse_cobol(FOLD_HEADER + f"           {statement}\n")
        assert result.errors == []
        divide = result.ast.find_all_by_type("DivideStatement")[0]
        assert divide.division_mode == mode
        assert divide.to_dict()["division_mode"] == mode

    def _fold(self, body):
        source = FOLD_HEADER + body + "           DISPLAY WS-A WS-B WS-R.\n"
        result = parse_cobol(source)
        assert result.errors == []
        index = ProgramLayoutIndex.build(result.ast)
        return ConstantFolder().fold(result.ast, index).known

    def test_fold_divide_by_giving(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n" "           DIVIDE WS-A BY 3 GIVING WS-B.\n"
        )
        assert known == {"WS-A": "12", "WS-B": "4"}

    def test_fold_divide_into_giving(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n"
            "           DIVIDE 3 INTO WS-A GIVING WS-B.\n"
        )
        assert known == {"WS-A": "12", "WS-B": "4"}

    def test_fold_divide_into_in_place(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n           DIVIDE 3 INTO WS-A.\n"
        )
        assert known == {"WS-A": "4"}

    def test_fold_poisons_inexact_quotient(self):
        known = self._fold(
            "           MOVE 10 TO WS-A.\n" "           DIVIDE WS-A BY 3 GIVING WS-B.\n"
        )
        assert known == {"WS-A": "10"}

    def test_fold_poisons_divide_by_zero(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n" "           DIVIDE WS-A BY 0 GIVING WS-B.\n"
        )
        assert known == {"WS-A": "12"}

    def test_fold_poisons_rounded(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n"
            "           DIVIDE WS-A BY 3 GIVING WS-B ROUNDED.\n"
        )
        assert known == {"WS-A": "12"}

    def test_fold_remainder_target_poisoned_giving_still_folds(self):
        known = self._fold(
            "           MOVE 12 TO WS-A.\n"
            "           DIVIDE WS-A BY 3 GIVING WS-B REMAINDER WS-R.\n"
        )
        assert known == {"WS-A": "12", "WS-B": "4"}
        assert "WS-R" not in known


class TestStatementTextFidelity:
    """Finding 4: typed-literal prefixes and ref-mod spacing."""

    def _move_sources(self, *statements):
        body = "".join(f"           {s}\n" for s in statements)
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC X(10).\n"
            "       01 WS-Y PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n" + body
        )
        result = parse_cobol(source)
        assert result.errors == []
        return [m.source for m in result.ast.find_all_by_type("MoveStatement")]

    def test_hex_literal_keeps_its_prefix_in_move(self):
        assert self._move_sources('MOVE X"41" TO WS-X.') == ['X"41"']

    def test_plain_string_literal_unchanged(self):
        assert self._move_sources("MOVE 'HI' TO WS-X.") == ['"HI"']

    def test_reference_modification_joins_tight(self):
        assert self._move_sources("MOVE WS-X(2:3) TO WS-Y.") == ["WS-X(2:3)"]

    def test_negative_subscript_still_joins_tight(self):
        # The P-B1 fix this extends: no reintroduction.
        assert self._move_sources("MOVE WS-X(-1) TO WS-Y.") == ["WS-X(-1)"]

    def test_hex_literal_keeps_its_prefix_in_display(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY X\"41\" 'HI'.\n"
        )
        result = parse_cobol(source)
        assert result.errors == []
        display = result.ast.find_all_by_type("DisplayStatement")[0]
        assert display.display_items == ['X"41"', '"HI"']


class TestConstraintPipelineWideLiteral:
    """The constraint extractor + solver end of finding 1."""

    def test_branch_witnesses_are_exact(self):
        result = parse_cobol(BIG_ID_PROGRAM)
        assert result.errors == []
        index = ProgramLayoutIndex.build(result.ast)
        boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        constraint_report = ConstraintExtractor().extract(
            result.ast, index, boundary_report
        )
        eq_witnesses = []
        for branch in constraint_report.branches:
            for constraints in branch.arms.values():
                for constraint in constraints:
                    if constraint.op == "eq":
                        witness = solve(constraint.field.spec, [constraint])
                        assert isinstance(witness, Witness)
                        eq_witnesses.append(witness.value)
        assert eq_witnesses == [WIDE_LITERAL]
