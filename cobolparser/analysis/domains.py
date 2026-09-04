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
import random
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation, localcontext

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
    """Bounds/exclusions are ``Decimal`` throughout: a ``PIC 9(17)``/``9(18)``
    literal exceeds float64's 53-bit mantissa, and a bound silently rounded
    on the way in produced a witness that could never satisfy the original
    constraint (``eq 123456789012345678`` used to render
    ``123456789012345680``)."""

    lo: Decimal
    hi: Decimal
    decimals: int
    excluded: set[Decimal] = field(default_factory=set)

    def pick(self) -> str | None:
        """Deterministic witness on the field's own decimal grid.

        Every representable value of a ``PIC [S]9(m)[V9(d)]`` field is an
        integer multiple of ``10**-d``, so candidates are enumerated in
        integer grid units (never a raw midpoint, which for e.g.
        ``PIC 9`` with ``ne 4`` used to pick 4.5, dodge the equality
        exclusion check, and then RENDER back to the excluded "4").
        Exclusions are compared after quantizing to the same grid; an
        exclusion not on the grid can never equal a grid candidate and is
        ignored. All arithmetic is exact Decimal, so the returned string is
        exact and the PICTURE-rendering step downstream never rounds it.
        """
        if self.lo > self.hi:
            return None
        scale = 10**self.decimals
        # Wide precision so bound*scale stays exact even for the largest
        # PICTUREs (up to 31 integer + 31 decimal digits); the default
        # 28-digit context would silently round the product.
        with localcontext() as ctx:
            ctx.prec = 80
            lo_units = int((self.lo * scale).to_integral_value(rounding=ROUND_CEILING))
            hi_units = int((self.hi * scale).to_integral_value(rounding=ROUND_FLOOR))
            if lo_units > hi_units:
                return None
            excluded_units = set()
            for value in self.excluded:
                units = value * scale
                if units == units.to_integral_value():
                    excluded_units.add(int(units))
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
    # A field with level-88s gets the enumerated domain FIRST when any set-op
    # is in play: for `IF NOT TYPE-P-BAL-M` against 88s "05"/"09" the useful
    # witness is the other *declared* value, "09", not some arbitrary string
    # the PICTURE also admits. But the enum is only a preference, never the
    # field's real domain -- a `not_in_set` covering every declared 88 value
    # (exactly what an `EVALUATE TRUE / WHEN <88> ... WHEN OTHER` chain's
    # OTHER arm negates to) empties it, and the answer there is a value
    # outside the enum, which the PICTURE does admit. So an emptied enum
    # falls back to the picture-derived domain and re-applies the same
    # constraints, rather than reporting Unsatisfiable for a branch that is
    # perfectly satisfiable.
    enum_first = bool(spec.condition_values) and any(
        c.op in ("in_set", "not_in_set") for c in constraints
    )
    witness: str | None = None
    domain: Domain
    if enum_first:
        domain = EnumDomain(list(spec.condition_values))
        if all(_apply(domain, c) for c in constraints):
            witness = domain.pick()

    if witness is None:
        domain = _picture_domain(spec)
        for constraint in constraints:
            if not _apply(domain, constraint):
                return Unsatisfiable(
                    f"empty domain after applying {constraint.op} "
                    f"from {constraint.origin}"
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
        value = Decimal(rendered)
    except InvalidOperation:
        return True  # non-numeric rendering: nothing checkable here
    if value in domain.excluded:
        return False
    return domain.lo <= value <= domain.hi


def _picture_domain(spec: FieldSpec) -> Domain:
    """The field's real domain, from its PICTURE -- what it can actually hold,
    independent of any level-88 names declared on it."""
    if spec.category in (
        FieldCategory.NUMERIC,
        FieldCategory.NUMERIC_EDITED,
        FieldCategory.FLOAT,
    ):
        return _initial_numeric_domain(spec)
    return TextDomain(allowed=None, forbidden=set(), size=max(1, spec.size))


def _initial_numeric_domain(spec: FieldSpec) -> NumericDomain:
    digits = spec.integer_digits
    decimals = spec.decimal_digits
    ceiling = (
        Decimal(10**digits - 1)
        if decimals == 0
        else Decimal(10**digits) - Decimal(1).scaleb(-decimals)
    )
    lo = -ceiling if spec.is_signed else Decimal(0)
    return NumericDomain(lo=lo, hi=ceiling, decimals=decimals)


def _epsilon(decimals: int) -> Decimal:
    return Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)


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

    # Set ops reach a numeric domain only via the enum-domain fallback in
    # solve() (a level-88 field whose enum was emptied). They must be enforced
    # here, not no-op'd through the `return True` tail below: a witness that
    # silently violates `not_in_set` would be an "exact by construction"
    # promise the value does not keep.
    if c.op in ("in_set", "not_in_set"):
        parsed = []
        for raw in c.values:
            try:
                candidate = Decimal(raw)
            except InvalidOperation:
                continue
            if candidate.is_finite():
                parsed.append(candidate)
        if not parsed:
            return True
        if c.op == "not_in_set":
            domain.excluded.update(parsed)
            return domain.lo < domain.hi or domain.lo not in domain.excluded
        # in_set: an interval cannot express a discrete allow-set, so narrow
        # to the first admissible member -- sound (it satisfies the set) and
        # deterministic, at the cost of generality no caller depends on.
        for candidate in parsed:
            if domain.lo <= candidate <= domain.hi and candidate not in domain.excluded:
                domain.lo = domain.hi = candidate
                domain.excluded = set()
                return True
        return False

    try:
        value = Decimal(c.values[0]) if c.values else None
    except InvalidOperation:
        return True  # a non-numeric literal against a numeric field: ignore, don't fail solve()
    if value is None or not value.is_finite():
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
    # Same wide-precision reasoning as NumericDomain.pick(): a strict bound
    # nudged by one grid epsilon must stay exact for the widest PICTUREs.
    if c.op == "gt":
        with localcontext() as ctx:
            ctx.prec = 80
            domain.lo = max(domain.lo, value + _epsilon(domain.decimals))
        return domain.lo <= domain.hi
    if c.op == "ge":
        domain.lo = max(domain.lo, value)
        return domain.lo <= domain.hi
    if c.op == "lt":
        with localcontext() as ctx:
            ctx.prec = 80
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
