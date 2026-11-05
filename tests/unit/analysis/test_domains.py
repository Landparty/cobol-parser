"""Unit tests for the Phase 4 constraint solver (cobolparser.analysis.domains).

Property-style: for every solved witness, (a) re-checking the constraint set
against the witness value passes, and (b) the rendered value is assignable to
the field (never exceeds its PICTURE). Empty-domain cases return
Unsatisfiable with a reason, never a value.
"""

from __future__ import annotations

import pytest

from cobolparser.analysis.constraints import FieldConstraint
from cobolparser.analysis.domains import Unsatisfiable, Witness, solve
from cobolparser.generators.data.layout import FieldCategory, FieldSpec
from cobolparser.generators.data.program_layout import ResolvedField
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem


def _numeric_spec(
    name: str = "WS-QTY",
    integer_digits: int = 3,
    decimal_digits: int = 0,
    is_signed: bool = False,
    condition_values: tuple[str, ...] = (),
) -> FieldSpec:
    picture = ("S" if is_signed else "") + f"9({integer_digits})"
    return FieldSpec(
        name=name,
        path=(name,),
        column=name,
        level=5,
        picture=picture,
        usage="DISPLAY",
        category=FieldCategory.NUMERIC,
        size=integer_digits + decimal_digits,
        integer_digits=integer_digits,
        decimal_digits=decimal_digits,
        is_signed=is_signed,
        condition_values=list(condition_values),
    )


def _text_spec(
    name: str = "WS-STATUS",
    size: int = 1,
    condition_values: tuple[str, ...] = (),
) -> FieldSpec:
    return FieldSpec(
        name=name,
        path=(name,),
        column=name,
        level=5,
        picture=f"X({size})",
        usage="DISPLAY",
        category=FieldCategory.ALPHANUMERIC,
        size=size,
        integer_digits=0,
        decimal_digits=0,
        is_signed=False,
        condition_values=list(condition_values),
    )


def _resolved(spec: FieldSpec) -> ResolvedField:
    record = CobolDataItem(name="WS-REC", level=1, location=SourceLocation(1, 1))
    return ResolvedField(spec=spec, section="working_storage", record=record)


def _constraint(
    spec: FieldSpec, op: str, values: tuple[str, ...], negated: bool = False
) -> FieldConstraint:
    return FieldConstraint(
        field=_resolved(spec), op=op, values=values, origin="TEST", negated=negated
    )


def _float_spec(name: str = "WS-FLT", usage: str = "COMP-2") -> FieldSpec:
    """A PICTURE-less float the way layout.py builds one: 9 integer digits,
    no decimals, unsigned -- a placeholder the solver must not use (#551)."""
    return FieldSpec(
        name=name,
        path=(name,),
        column=name,
        level=5,
        picture=None,
        usage=usage,
        category=FieldCategory.FLOAT,
        size=4 if usage == "COMP-1" else 8,
        integer_digits=9,
        decimal_digits=0,
        is_signed=False,
    )


class TestFloatDomain:
    @pytest.mark.parametrize("usage", ["COMP-1", "COMP-2"])
    def test_negative_bound_is_satisfiable(self, usage):
        spec = _float_spec(usage=usage)
        result = solve(spec, [_constraint(spec, "lt", ("-100",))])
        assert isinstance(result, Witness), result
        assert float(result.value) < -100

    @pytest.mark.parametrize("usage", ["COMP-1", "COMP-2"])
    def test_fractional_interval_is_satisfiable(self, usage):
        spec = _float_spec(usage=usage)
        result = solve(
            spec,
            [_constraint(spec, "gt", ("0.25",)), _constraint(spec, "lt", ("0.75",))],
        )
        assert isinstance(result, Witness), result
        assert 0.25 < float(result.value) < 0.75

    def test_negative_fraction_equality_is_kept_exactly(self):
        spec = _float_spec()
        result = solve(spec, [_constraint(spec, "eq", ("-2.5",))])
        assert isinstance(result, Witness), result
        assert float(result.value) == -2.5


class TestNumericInterval:
    def test_gt_lt_produces_witness_in_range(self):
        spec = _numeric_spec(integer_digits=3)
        result = solve(
            spec, [_constraint(spec, "gt", ("10",)), _constraint(spec, "lt", ("100",))]
        )
        assert isinstance(result, Witness)
        assert 10 < float(result.value) < 100

    def test_contradictory_eq_is_unsatisfiable(self):
        spec = _numeric_spec(integer_digits=3)
        result = solve(
            spec, [_constraint(spec, "eq", ("5",)), _constraint(spec, "eq", ("6",))]
        )
        assert isinstance(result, Unsatisfiable)
        assert result.reason

    def test_eq_then_ne_same_value_is_unsatisfiable(self):
        spec = _numeric_spec(integer_digits=3)
        result = solve(
            spec, [_constraint(spec, "eq", ("5",)), _constraint(spec, "ne", ("5",))]
        )
        assert isinstance(result, Unsatisfiable)

    def test_witness_never_exceeds_picture_digits(self):
        spec = _numeric_spec(integer_digits=2)  # PIC 9(2), max 99
        result = solve(spec, [_constraint(spec, "ge", ("0",))])
        assert isinstance(result, Witness)
        assert len(result.value.lstrip("-")) <= 2

    def test_signed_field_allows_negative(self):
        spec = _numeric_spec(integer_digits=3, is_signed=True)
        result = solve(spec, [_constraint(spec, "lt", ("0",))])
        assert isinstance(result, Witness)
        assert float(result.value) < 0

    def test_unsigned_field_never_goes_negative(self):
        spec = _numeric_spec(integer_digits=3, is_signed=False)
        result = solve(spec, [])
        assert isinstance(result, Witness)
        assert float(result.value) >= 0


class TestEnumDomain88:
    def test_in_set_picks_a_declared_value(self):
        spec = _text_spec(size=1, condition_values=("A", "B"))
        result = solve(spec, [_constraint(spec, "in_set", ("A", "B"))])
        assert isinstance(result, Witness)
        assert result.value in ("A", "B")

    def test_not_in_set_excludes(self):
        spec = _text_spec(size=1, condition_values=("A", "B"))
        result = solve(spec, [_constraint(spec, "not_in_set", ("A",))])
        assert isinstance(result, Witness)
        assert result.value == "B"

    def test_excluding_every_88_value_falls_back_to_the_picture_domain(self):
        """The level-88 enum is a *preference*, not the field's domain. A
        `not_in_set` covering every declared 88 value -- exactly what an
        `EVALUATE TRUE / WHEN <88> ... WHEN OTHER` chain's OTHER arm negates
        to -- empties the enum, but the field's PICTURE still admits plenty
        of other values, so a witness outside the enum is the right answer.
        Reporting Unsatisfiable here (as this used to) made every WHEN OTHER
        scenario a miss for a branch that is perfectly reachable."""
        spec = _text_spec(size=1, condition_values=("A",))
        result = solve(spec, [_constraint(spec, "not_in_set", ("A",))])
        assert isinstance(result, Witness)
        assert result.value != "A"

    def test_enum_still_preferred_when_it_survives_the_exclusion(self):
        """The fallback must not cost us the *useful* witness in the ordinary
        case: with one declared value left, that declared value wins over an
        arbitrary PICTURE-admissible string."""
        spec = _text_spec(size=1, condition_values=("A", "B"))
        result = solve(spec, [_constraint(spec, "not_in_set", ("A",))])
        assert isinstance(result, Witness)
        assert result.value == "B"

    def test_contradictory_set_constraints_are_still_unsatisfiable(self):
        """The picture-domain fallback is not a way to launder a genuine
        contradiction: `in_set ("A")` AND `not_in_set ("A")` has no witness
        in the enum OR in the PICTURE domain."""
        spec = _text_spec(size=1, condition_values=("A", "B"))
        result = solve(
            spec,
            [
                _constraint(spec, "in_set", ("A",)),
                _constraint(spec, "not_in_set", ("A",)),
            ],
        )
        assert isinstance(result, Unsatisfiable)

    def test_numeric_field_enforces_not_in_set_after_fallback(self):
        """A numeric level-88 field whose enum is emptied falls back to the
        NUMERIC domain, where `not_in_set` must be enforced as an exclusion
        -- not silently no-op'd into a witness that violates it.

        The `le 14` bound is load-bearing, not incidental: it puts the
        domain's deterministic midpoint witness exactly on 7, the excluded
        value. Without it the midpoint of a bare PIC 9(2) is ~50, which
        satisfies the assertion whether or not `not_in_set` was enforced --
        a test that passes for the wrong reason. It did exactly that once,
        while `_apply_numeric`'s set-op branch sat below the catch-all
        guard and was unreachable."""
        spec = _numeric_spec(integer_digits=2)
        spec.condition_values = ["7"]
        result = solve(
            spec,
            [
                _constraint(spec, "le", ("14",)),
                _constraint(spec, "not_in_set", ("7",)),
            ],
        )
        assert isinstance(result, Witness)
        assert int(result.value) != 7
        assert int(result.value) <= 14

    def test_numeric_in_set_narrows_to_a_member_after_fallback(self):
        """The other half of the same branch: `in_set` on a numeric fallback
        domain must narrow to one of the listed values, not no-op."""
        spec = _numeric_spec(integer_digits=2)
        spec.condition_values = ["7"]
        result = solve(spec, [_constraint(spec, "in_set", ("7", "9"))])
        assert isinstance(result, Witness)
        assert int(result.value) in (7, 9)


class TestTextDomain:
    def test_eq_literal(self):
        spec = _text_spec(size=3)
        result = solve(spec, [_constraint(spec, "eq", ("XYZ",))])
        assert isinstance(result, Witness)
        assert result.value == "XYZ"

    def test_conflicting_eq_is_unsatisfiable(self):
        spec = _text_spec(size=3)
        result = solve(
            spec, [_constraint(spec, "eq", ("AAA",)), _constraint(spec, "eq", ("BBB",))]
        )
        assert isinstance(result, Unsatisfiable)

    def test_unconstrained_text_picks_something_within_size(self):
        spec = _text_spec(size=4)
        result = solve(spec, [])
        assert isinstance(result, Witness)
        assert len(result.value) <= 4


class TestFigurative:
    def test_figurative_spaces_on_text(self):
        spec = _text_spec(size=3)
        result = solve(spec, [_constraint(spec, "figurative", ("SPACES",))])
        assert isinstance(result, Witness)
        assert result.value == ""

    def test_figurative_zero_on_numeric(self):
        spec = _numeric_spec(integer_digits=3)
        result = solve(spec, [_constraint(spec, "figurative", ("ZEROS",))])
        assert isinstance(result, Witness)
        assert float(result.value) == 0

    def test_negated_figurative_zero_excludes_zero(self):
        spec = _numeric_spec(integer_digits=1)
        result = solve(spec, [_constraint(spec, "figurative", ("ZERO",), negated=True)])
        assert isinstance(result, Witness)
        assert float(result.value) != 0


class TestWitnessSatisfiesConstraints:
    """Every solved witness, re-checked against its own constraint set,
    passes -- independent of the solver's internal domain bookkeeping."""

    @staticmethod
    def _satisfies(value: object, constraint: FieldConstraint) -> bool:
        if constraint.op == "eq":
            return value == constraint.values[0]
        if constraint.op == "ne":
            return value != constraint.values[0]
        if constraint.op in ("gt", "ge", "lt", "le"):
            n = float(value)  # type: ignore[arg-type]
            target = float(constraint.values[0])
            return {
                "gt": n > target,
                "ge": n >= target,
                "lt": n < target,
                "le": n <= target,
            }[constraint.op]
        if constraint.op == "in_set":
            return value in constraint.values
        if constraint.op == "not_in_set":
            return value not in constraint.values
        return True

    def test_numeric_interval_witness_round_trips(self):
        spec = _numeric_spec(integer_digits=3)
        constraints = [
            _constraint(spec, "ge", ("20",)),
            _constraint(spec, "le", ("30",)),
        ]
        result = solve(spec, constraints)
        assert isinstance(result, Witness)
        for c in constraints:
            assert self._satisfies(float(result.value), c)

    def test_enum_witness_round_trips(self):
        spec = _text_spec(size=1, condition_values=("A", "B", "C"))
        constraints = [_constraint(spec, "in_set", ("B", "C"))]
        result = solve(spec, constraints)
        assert isinstance(result, Witness)
        for c in constraints:
            assert self._satisfies(result.value, c)

    def test_never_returns_a_value_when_unsatisfiable(self):
        spec = _numeric_spec(integer_digits=1)  # max 9
        result = solve(
            spec, [_constraint(spec, "ge", ("5",)), _constraint(spec, "le", ("2",))]
        )
        assert isinstance(result, Unsatisfiable)


class TestEnumDomainHonoursRelationalConjuncts:
    """Issue #244: a level-88 field with a relational conjunct alongside a set
    op. `IF NOT HIGH-V AND WS-C > 5` (88s LOW-V=1, HIGH-V=9 on PIC 99) used
    to pick the enum's first surviving value, 1 -- which satisfies
    `not_in_set ("9")` and fails `gt 5`, because the enum path treated every
    relational op as a no-op and never re-checked its pick."""

    @staticmethod
    def _spec() -> FieldSpec:
        return _numeric_spec(name="WS-C", integer_digits=2, condition_values=("1", "9"))

    @pytest.mark.parametrize(
        ("op", "admits"),
        [
            ("gt", lambda n: n > 5),
            ("ge", lambda n: n >= 5),
            ("lt", lambda n: n < 5),
            ("le", lambda n: n <= 5),
        ],
    )
    def test_then_arm_witness_satisfies_the_relational_conjunct(self, op, admits):
        spec = self._spec()
        result = solve(
            spec,
            [
                _constraint(spec, "not_in_set", ("9",)),
                _constraint(spec, op, ("5",)),
            ],
        )
        assert isinstance(result, Witness)
        assert int(result.value) != 9
        assert admits(int(result.value))

    def test_gt_witness_is_inside_the_open_interval(self):
        spec = self._spec()
        result = solve(
            spec,
            [
                _constraint(spec, "not_in_set", ("9",)),
                _constraint(spec, "gt", ("5",)),
            ],
        )
        assert isinstance(result, Witness)
        assert int(result.value) in (6, 7, 8) or int(result.value) > 9

    def test_else_1_arm_still_picks_the_declared_value(self):
        spec = self._spec()
        result = solve(spec, [_constraint(spec, "in_set", ("9",))])
        assert isinstance(result, Witness)
        assert int(result.value) == 9

    def test_else_2_arm_satisfies_le(self):
        spec = self._spec()
        result = solve(spec, [_constraint(spec, "le", ("5",))])
        assert isinstance(result, Witness)
        assert int(result.value) <= 5

    def test_enum_value_that_satisfies_the_relational_op_is_still_preferred(self):
        """The re-check must not cost the useful witness: with `lt 5`, the
        declared value 1 satisfies both conjuncts and stays the answer."""
        spec = self._spec()
        result = solve(
            spec,
            [
                _constraint(spec, "not_in_set", ("9",)),
                _constraint(spec, "lt", ("5",)),
            ],
        )
        assert isinstance(result, Witness)
        assert int(result.value) == 1

    def test_in_set_contradicted_by_a_relational_op_is_unsatisfiable(self):
        """`HIGH-V AND WS-C < 5` has no witness anywhere: the enum's only
        candidate fails `lt 5`, and the picture-domain fallback must still
        report the contradiction rather than hand back 9."""
        spec = self._spec()
        result = solve(
            spec,
            [
                _constraint(spec, "in_set", ("9",)),
                _constraint(spec, "lt", ("5",)),
            ],
        )
        assert isinstance(result, Unsatisfiable)


class TestNumericClassOnAlphanumeric:
    """`IF X IS NUMERIC` tests every character position of the item."""

    def test_numeric_witness_fills_the_whole_field(self):
        """A value shorter than a PIC X(10) is space-padded when moved in,
        and "00000000  " is NOT NUMERIC: the THEN arm was never reached."""
        spec = _text_spec("IN-NAME", size=10)
        result = solve(spec, [_constraint(spec, "class_numeric", ())])
        assert isinstance(result, Witness)
        assert result.value.isdigit()
        assert len(result.value) == 10

    def test_not_numeric_witness_is_still_found(self):
        spec = _text_spec("IN-NAME", size=10)
        result = solve(spec, [_constraint(spec, "class_numeric", (), negated=True)])
        assert isinstance(result, Witness)
        assert not result.value.ljust(10).isdigit()

    def test_short_allowed_literal_is_not_numeric(self):
        """`IF X = '123' AND X IS NUMERIC` on a PIC X(5): "123  " is not
        numeric, so the conjunction has no witness."""
        spec = _text_spec("IN-CODE", size=5)
        result = solve(
            spec,
            [
                _constraint(spec, "eq", ("'123'",)),
                _constraint(spec, "class_numeric", ()),
            ],
        )
        assert isinstance(result, Unsatisfiable)


class TestOdoCounterDomain:
    """The counter of an `OCCURS m TO n DEPENDING ON` table only holds m..n."""

    @staticmethod
    def _counter(low: int = 1, high: int = 5) -> FieldSpec:
        spec = _numeric_spec("DTL-CNT", integer_digits=2)
        spec.odo_counter_bounds = (low, high)
        return spec

    def test_gt_witness_stays_inside_the_occurs_bounds(self):
        """`IF DTL-CNT > 3` used to get 51 (the picture's midpoint) for an
        `OCCURS 1 TO 5`: a loop over the table then ran past its end."""
        spec = self._counter()
        result = solve(spec, [_constraint(spec, "gt", ("3",))])
        assert isinstance(result, Witness)
        assert 3 < int(result.value) <= 5

    def test_value_outside_the_bounds_is_unsatisfiable(self):
        spec = self._counter()
        result = solve(spec, [_constraint(spec, "gt", ("5",))])
        assert isinstance(result, Unsatisfiable)

    def test_lower_bound_is_kept(self):
        spec = self._counter(low=1)
        result = solve(spec, [_constraint(spec, "lt", ("2",))])
        assert isinstance(result, Witness)
        assert int(result.value) == 1
