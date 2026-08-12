"""Domain-propagation constraint solver (Phase 4 of `gen-fixtures`).

No external dependency, matching the core library's zero-runtime-dependency
rule. Given a :class:`~.layout.FieldSpec` and the
:class:`~.constraints.FieldConstraint` conjuncts that apply to it, narrows a
small domain lattice (numeric interval, text allow/deny set, or an enumerated
level-88 domain) and picks a deterministic witness -- always rendered through
:meth:`~cobolparser.generators.data.values.ValueFactory.render` so a solved
value can never violate the field's PICTURE, the same invariant the copybook
generator's own value providers already guarantee.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from decimal import Decimal

from ..generators.data.layout import FieldCategory, FieldSpec
from ..generators.data.options import DataGeneratorOptions
from ..generators.data.values import ValueFactory
from .constraints import FieldConstraint

# Mirrors values.py's own _FIGURATIVE_CONSTANTS (re-derived locally rather
# than imported -- a small, stable data table, same call as elsewhere in this
# phase's modules).
_FIGURATIVE_VALUES: dict[str, str] = {
    "SPACE": "",
    "SPACES": "",
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
    "LOW-VALUE": "",
    "LOW-VALUES": "",
    "HIGH-VALUE": "",
    "HIGH-VALUES": "",
    "QUOTE": '"',
    "QUOTES": '"',
    "NULL": "",
    "NULLS": "",
}
_ZERO_FIGURATIVES = frozenset({"ZERO", "ZEROS", "ZEROES"})


@dataclass(frozen=True)
class Unsatisfiable:
    """No value can satisfy the constraint set as modeled."""

    reason: str


@dataclass(frozen=True)
class Witness:
    """A concrete value, already rendered through the field's PICTURE."""

    value: str


@dataclass
class NumericDomain:
    lo: float
    hi: float
    decimals: int
    excluded: set[float] = field(default_factory=set)

    def pick(self) -> str | None:
        """Deterministic witness on the field's own decimal grid.

        Every representable value of a ``PIC [S]9(m)[V9(d)]`` field is an
        integer multiple of ``10**-d``, so candidates are enumerated in
        integer grid units (never a raw float midpoint, which for e.g.
        ``PIC 9`` with ``ne 4`` used to pick 4.5, dodge the float-equality
        exclusion check, and then RENDER back to the excluded "4").
        Exclusions are compared after quantizing to the same grid; an
        exclusion not on the grid can never equal a grid candidate and is
        ignored. The returned string is exact (rendered via Decimal), so the
        PICTURE-rendering step downstream never rounds it.
        """
        if self.lo > self.hi:
            return None
        scale = 10**self.decimals
        # A tiny tolerance so float noise (0.1 + 0.01 = 0.11000000000000001)
        # does not shift a bound off its intended grid cell.
        lo_units = math.ceil(self.lo * scale - 1e-9)
        hi_units = math.floor(self.hi * scale + 1e-9)
        if lo_units > hi_units:
            return None
        excluded_units = set()
        for value in self.excluded:
            units = round(value * scale)
            if abs(value * scale - units) < 1e-6:
                excluded_units.add(units)
        mid_units = (lo_units + hi_units) // 2
        for units in itertools.chain(
            range(mid_units, hi_units + 1), range(lo_units, mid_units)
        ):
            if units not in excluded_units:
                return str(Decimal(units).scaleb(-self.decimals))
        return None


@dataclass
class TextDomain:
    allowed: set[str] | None  # None = "any value of size <= size"
    forbidden: set[str]
    size: int

    def pick(self) -> str | None:
        if self.allowed is not None:
            remaining = sorted(self.allowed - self.forbidden)
            return remaining[0] if remaining else None
        n = max(1, min(self.size, 8))
        for letter in "XYZABCDEFGH":
            candidate = letter * n
            if candidate not in self.forbidden:
                return candidate
        return None


@dataclass
class EnumDomain:
    values: list[str]  # remaining allowed values, in declared order

    def pick(self) -> str | None:
        return self.values[0] if self.values else None


Domain = NumericDomain | TextDomain | EnumDomain


def solve(
    spec: FieldSpec, constraints: list[FieldConstraint]
) -> Witness | Unsatisfiable:
    """Solve *constraints* against *spec*'s domain and pick a witness.

    Witness picking is deterministic: the grid value at the midpoint of a
    numeric interval (scanning forward past exclusions, wrapping to the low
    bound), the first allowed literal in sorted order for text, the first
    remaining enumerated value for a level-88 domain.
    """
    domain: Domain
    if any(c.op in ("in_set", "not_in_set") for c in constraints):
        domain = EnumDomain(list(spec.condition_values))
    elif spec.category in (
        FieldCategory.NUMERIC,
        FieldCategory.NUMERIC_EDITED,
        FieldCategory.FLOAT,
    ):
        domain = _initial_numeric_domain(spec)
    else:
        domain = TextDomain(allowed=None, forbidden=set(), size=max(1, spec.size))

    for constraint in constraints:
        if not _apply(domain, constraint):
            return Unsatisfiable(
                f"empty domain after applying {constraint.op} from {constraint.origin}"
            )

    witness = domain.pick()
    if witness is None:
        return Unsatisfiable("no witness available in domain")

    factory = ValueFactory(random.Random(0), DataGeneratorOptions())
    rendered = factory.render(spec, str(witness))
    if isinstance(domain, NumericDomain) and not _rendered_numeric_ok(rendered, domain):
        # Defensive: grid-based picking should make this unreachable, but a
        # witness whose RENDERED form violates the constraint set must never
        # escape (rendering used to round a fractional midpoint onto an
        # excluded value).
        return Unsatisfiable(
            f"rendered witness {rendered!r} violates the constraint set"
        )
    return Witness(rendered)


def _rendered_numeric_ok(rendered: str, domain: NumericDomain) -> bool:
    """True when the PICTURE-rendered witness still satisfies the domain."""
    try:
        value = float(rendered)
    except ValueError:
        return True  # non-numeric rendering: nothing checkable here
    if any(abs(value - excluded) < 1e-9 for excluded in domain.excluded):
        return False
    return domain.lo - 1e-9 <= value <= domain.hi + 1e-9


def _initial_numeric_domain(spec: FieldSpec) -> NumericDomain:
    digits = spec.integer_digits
    decimals = spec.decimal_digits
    ceiling = (
        float(10**digits - 1) if decimals == 0 else float(10**digits) - 10.0**-decimals
    )
    lo = -ceiling if spec.is_signed else 0.0
    return NumericDomain(lo=lo, hi=ceiling, decimals=decimals)


def _epsilon(decimals: int) -> float:
    return 10.0**-decimals if decimals > 0 else 1.0


def _apply(domain: Domain, c: FieldConstraint) -> bool:
    if isinstance(domain, EnumDomain):
        return _apply_enum(domain, c)
    if isinstance(domain, NumericDomain):
        return _apply_numeric(domain, c)
    return _apply_text(domain, c)


def _apply_enum(domain: EnumDomain, c: FieldConstraint) -> bool:
    if c.op in ("in_set", "eq"):
        allowed = {v.upper() for v in c.values}
        domain.values = [v for v in domain.values if v.upper() in allowed]
    elif c.op in ("not_in_set", "ne"):
        denied = {v.upper() for v in c.values}
        domain.values = [v for v in domain.values if v.upper() not in denied]
    # Other op kinds do not meaningfully narrow an enumerated domain in v1;
    # leave it unconstrained rather than fail.
    return bool(domain.values)


def _apply_numeric(domain: NumericDomain, c: FieldConstraint) -> bool:
    if c.op == "figurative":
        fig = c.values[0].upper() if c.values else ""
        if fig not in _ZERO_FIGURATIVES:
            return True  # SPACES/LOW-VALUES etc. don't narrow a numeric range
        return _apply_numeric(
            domain,
            FieldConstraint(c.field, "ne" if c.negated else "eq", ("0",), c.origin),
        )

    if c.op not in ("eq", "ne", "gt", "ge", "lt", "le"):
        return True  # class_numeric/class_alphabetic: no-op on a numeric domain in v1

    try:
        value = float(c.values[0]) if c.values else None
    except ValueError:
        return True  # a non-numeric literal against a numeric field: ignore, don't fail solve()
    if value is None:
        return True

    if c.op == "eq":
        if not (domain.lo <= value <= domain.hi) or value in domain.excluded:
            return False
        domain.lo = domain.hi = value
        domain.excluded = set()
        return True
    if c.op == "ne":
        domain.excluded.add(value)
        return domain.lo < domain.hi or domain.lo not in domain.excluded
    if c.op == "gt":
        domain.lo = max(domain.lo, value + _epsilon(domain.decimals))
        return domain.lo <= domain.hi
    if c.op == "ge":
        domain.lo = max(domain.lo, value)
        return domain.lo <= domain.hi
    if c.op == "lt":
        domain.hi = min(domain.hi, value - _epsilon(domain.decimals))
        return domain.lo <= domain.hi
    if c.op == "le":
        domain.hi = min(domain.hi, value)
        return domain.lo <= domain.hi
    return True


def _apply_text(domain: TextDomain, c: FieldConstraint) -> bool:
    if c.op in ("eq", "in_set") or (c.op == "figurative" and not c.negated):
        values = _text_values(c)
        domain.allowed = values if domain.allowed is None else (domain.allowed & values)
        return bool(domain.allowed)
    if c.op in ("ne", "not_in_set") or (c.op == "figurative" and c.negated):
        values = _text_values(c)
        domain.forbidden |= values
        if domain.allowed is not None:
            domain.allowed -= domain.forbidden
            return bool(domain.allowed)
        return True
    # class_numeric/class_alphabetic and relational ops on text: not
    # meaningfully enforceable on a bare allow/deny set in v1 -- no-op.
    return True


def _text_values(c: FieldConstraint) -> set[str]:
    if c.op == "figurative":
        return {_FIGURATIVE_VALUES.get(c.values[0].upper(), "")} if c.values else {""}
    return set(c.values)


__all__ = [
    "Unsatisfiable",
    "Witness",
    "NumericDomain",
    "TextDomain",
    "EnumDomain",
    "solve",
]
