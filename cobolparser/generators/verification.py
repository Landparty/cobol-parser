"""Self-verification: does a scenario's own generated data actually satisfy
the branch it is named for?

Phase 5/6 plan a scenario and pin witnesses into the generated rows, but
nothing checked afterwards that the data that came out still satisfies the
conditions that motivated it. The only way to find out was to run the suite
under a tracer, per scenario -- which makes every scenario name a claim the
bundle itself cannot support.

This module closes that: it re-reads each scenario's OWN emitted fixture
data and re-checks every planned conjunct against it, so the bundle carries
a verdict instead of a label. The check is deliberately independent of the
solver -- it evaluates constraints against concrete rendered strings, the
same strings a mock will actually move into the program -- so a solver bug,
a rendering bug, or a witness that never reached any fixture all surface as
a finding rather than as a green label.

Deliberately conservative: a conjunct this module cannot decide from a
rendered string is `"unknown"`, never silently "satisfied". "I could not
check this" and "this is fine" are different answers and the bundle says
which one it means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ..analysis.constraints import FieldConstraint
from .data.bundle import BoundaryFixture, Scenario
from .scenarios import PlannedScenario

#: Figurative constants a rendered value can be compared against. Mirrors
#: `domains.py`'s own table (a small, stable data table re-derived locally,
#: the same call this phase's other modules make).
_FIGURATIVE_TESTS: dict[str, str] = {
    "SPACE": "space",
    "SPACES": "space",
    "ZERO": "zero",
    "ZEROS": "zero",
    "ZEROES": "zero",
    "LOW-VALUE": "low",
    "LOW-VALUES": "low",
    "HIGH-VALUE": "high",
    "HIGH-VALUES": "high",
    "QUOTE": "quote",
    "QUOTES": "quote",
}


@dataclass(frozen=True)
class FieldVerdict:
    """What the generated data says about one constrained field."""

    field: str
    #: "satisfied" -- at least one generated row meets every conjunct;
    #: "violated" -- the field is present and no row meets them;
    #: "absent" -- no fixture this scenario emits carries the field at all,
    #:   so nothing pins the branch;
    #: "unknown" -- present, but a conjunct could not be decided from the
    #:   rendered value.
    status: str
    detail: str
    rows: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "status": self.status,
            "detail": self.detail,
            "rows": list(self.rows),
        }


@dataclass
class ScenarioVerification:
    """The verdict for one scenario, as carried in the bundle."""

    status: str  # "verified" | "unverified"
    fields: list[FieldVerdict] = field(default_factory=list)
    #: Reasons this scenario cannot promise it reaches its arm even when
    #: every field verdict is "satisfied" -- an enclosing branch on its path
    #: whose own condition was never modeled (`PlannedScenario.path_gaps`).
    gaps: list[str] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """Every reason this scenario is `unverified`, ready to print."""
        return [
            f"{verdict.field}: {verdict.detail}"
            for verdict in self.fields
            if verdict.status != "satisfied"
        ] + list(self.gaps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fields": [verdict.to_dict() for verdict in self.fields],
            "gaps": list(self.gaps),
        }


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _relational(op: str, value: str, target: str) -> bool | None:
    """Evaluate a relational conjunct against a rendered value.

    Numeric comparison when both sides parse as numbers; alphanumeric
    comparison when neither does (COBOL pads the shorter operand with
    spaces, so comparing the trailing-space-stripped forms gives the same
    answer for every value this generator can produce, without reading a
    PICTURE's padding as a difference).

    An ORDERING comparison with one numeric and one non-numeric side is
    `None`, not a lexical guess: `'XXXX' > 0` has no well-defined answer to
    report (IBM COBOL only allows an alphanumeric-to-numeric comparison when
    the alphanumeric operand is integer-like), and answering it lexically
    would let a scenario be stamped "verified" on a comparison nobody can
    actually evaluate. Equality survives the mixed case: a value that is not
    a number cannot equal a numeric literal, whichever way it is read.
    """
    left_num, right_num = _decimal(value), _decimal(target)
    if left_num is not None and right_num is not None:
        return _compare(op, left_num, right_num)
    if (left_num is None) != (right_num is None) and op in ("lt", "le", "gt", "ge"):
        return None
    return _compare(op, value.rstrip(), target.rstrip())


def _compare(op: str, left: Decimal | str, right: Decimal | str) -> bool | None:
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right  # type: ignore[operator]
    if op == "le":
        return left <= right  # type: ignore[operator]
    if op == "gt":
        return left > right  # type: ignore[operator]
    if op == "ge":
        return left >= right  # type: ignore[operator]
    return None


def satisfies(constraint: FieldConstraint, value: str) -> bool | None:
    """Does `value` satisfy `constraint`? `None` when undecidable.

    `None` is a real answer here, not a failure: a class test on a
    non-DISPLAY rendering, or an op this table does not model, must not be
    reported as either passing or failing.
    """
    op = constraint.op
    if op in ("eq", "ne", "lt", "le", "gt", "ge"):
        if len(constraint.values) != 1:
            return None
        return _relational(op, value, constraint.values[0])
    if op in ("in_set", "not_in_set"):
        member = any(
            _relational("eq", value, candidate) for candidate in constraint.values
        )
        return member if op == "in_set" else not member
    if op == "class_numeric":
        result = _decimal(value) is not None
        return not result if constraint.negated else result
    if op == "class_alphabetic":
        stripped = value.strip()
        result = bool(stripped) and all(c.isalpha() or c == " " for c in stripped)
        return not result if constraint.negated else result
    if op == "figurative":
        if len(constraint.values) != 1:
            return None
        kind = _FIGURATIVE_TESTS.get(constraint.values[0].upper())
        if kind == "space":
            result = value.strip() == ""
        elif kind == "zero" and _is_numeric_field(constraint):
            parsed = _decimal(value)
            result = parsed is not None and parsed == 0
        elif kind == "zero":
            # Compared with a non-numeric field a figurative constant is its
            # character repeated to the field's whole width: `IF X = ZEROS`
            # on PIC X(3) is true only for "000", never for "0  ".
            result = _fills(value, "0", constraint)
        elif kind == "quote":
            result = _fills(value, '"', constraint)
        else:
            return None  # LOW-VALUE/HIGH-VALUE: not representable as text here
        return not result if constraint.negated else result
    return None


def _is_numeric_field(constraint: FieldConstraint) -> bool:
    """Whether the constrained field is numeric (a constraint built with
    no field at all is read the numeric way, as before)."""
    field_ = getattr(constraint, "field", None)
    if field_ is None:
        return True
    # The same split `domains._picture_domain` makes.
    return field_.spec.category.value in ("numeric", "numeric-edited", "float")


def _fills(value: str, char: str, constraint: FieldConstraint) -> bool:
    """Whether *value* is *char* in every position of the field (of the
    value itself when the constraint carries no field)."""
    field_ = getattr(constraint, "field", None)
    size = field_.spec.character_positions if field_ is not None else 0
    width = size if size > 0 else len(value)
    return bool(value) and value == char * width


def _values_for(field_name: str, fixtures: list[BoundaryFixture]) -> list[str]:
    """Every generated value of `field_name` across a scenario's fixtures,
    in row order. Empty when no fixture carries the field at all -- which is
    itself the finding, not a missing input.

    `field_name` is a qualified name (`PlannedScenario.field_constraints` is
    keyed by `spec.qualified_name`), so a qualified match is the answer
    whenever one exists. The bare-name fallback below exists for layouts
    whose specs carry no qualification, but it is only taken when the bare
    name is unambiguous across the whole scenario: two boundaries with a
    same-named field in different records would otherwise let an unrelated
    record's value satisfy this field's conjuncts, and a false "satisfied"
    is the one verdict this module must never produce. An ambiguous name
    yields no values, which reads as "absent" -- unverified, the safe way to
    be wrong.
    """
    qualified = [
        (fixture, spec.column)
        for fixture in fixtures
        for spec in fixture.layout
        if spec.qualified_name == field_name
    ]
    matches = qualified
    if not matches:
        bare = [
            (fixture, spec.column)
            for fixture in fixtures
            for spec in fixture.layout
            if spec.name == field_name
        ]
        if len({column for _, column in bare}) != 1 or len(bare) != 1:
            return []
        matches = bare

    values: list[str] = []
    for fixture, column in matches:
        for row in fixture.sequence:
            if column in row:
                values.append(row[column])
    return values


def _verdict_for(
    field_name: str, constraints: list[FieldConstraint], values: list[str]
) -> FieldVerdict:
    if not values:
        return FieldVerdict(
            field=field_name,
            status="absent",
            detail=(
                "no fixture in this scenario generates this field, so nothing "
                "in the generated data pins the branch it guards"
            ),
        )
    satisfying: list[int] = []
    undecidable: list[str] = []
    for index, value in enumerate(values):
        results = [satisfies(c, value) for c in constraints]
        if any(result is None for result in results):
            undecidable.extend(
                f"{c.op} {c.values!r}"
                for c, result in zip(constraints, results, strict=True)
                if result is None
            )
            continue
        if all(results):
            satisfying.append(index)
    if satisfying:
        return FieldVerdict(
            field=field_name,
            status="satisfied",
            detail=f"row(s) {', '.join(str(i) for i in satisfying)} meet every conjunct",
            rows=tuple(satisfying),
        )
    if undecidable:
        return FieldVerdict(
            field=field_name,
            status="unknown",
            detail=(
                "could not be decided from the generated value(s): "
                + "; ".join(sorted(set(undecidable)))
            ),
        )
    return FieldVerdict(
        field=field_name,
        status="violated",
        detail=(
            f"none of the {len(values)} generated value(s) satisfy this "
            f"field's conjuncts (first: {values[0]!r})"
        ),
    )


def verify_scenario(
    planned: PlannedScenario, scenario: Scenario
) -> ScenarioVerification:
    """Check `scenario`'s emitted data against `planned`'s own constraints."""
    verdicts = [
        _verdict_for(
            field_name, constraints, _values_for(field_name, scenario.fixtures)
        )
        for field_name, constraints in sorted(planned.field_constraints.items())
    ]
    status = (
        "verified"
        if not planned.path_gaps
        and all(verdict.status == "satisfied" for verdict in verdicts)
        else "unverified"
    )
    return ScenarioVerification(
        status=status, fields=verdicts, gaps=list(planned.path_gaps)
    )
