"""Unit tests for the Phase 4 constraint solver (cobolparser.analysis.domains).

Property-style: for every solved witness, (a) re-checking the constraint set
against the witness value passes, and (b) the rendered value is assignable to
the field (never exceeds its PICTURE). Empty-domain cases return
Unsatisfiable with a reason, never a value.
"""

from __future__ import annotations

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
        -- not silently no-op'd into a witness that violates it."""
        spec = _numeric_spec(integer_digits=2)
        spec.condition_values = ["7"]
        result = solve(spec, [_constraint(spec, "not_in_set", ("7",))])
        assert isinstance(result, Witness)
        assert int(result.value) != 7


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
