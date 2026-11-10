"""Domain-propagation constraint solver (Phase 4 of `gen-fixtures`).

No external dependency, matching the core library's zero-runtime-dependency
rule. Given a :class:`~.layout.FieldSpec` and the
:class:`~.constraints.FieldConstraint` conjuncts that apply to it, narrows a
small domain lattice (numeric interval, text allow/deny set, or an enumerated
level-88 domain) and picks a deterministic witness -- always rendered through
:meth:`~cobolparser.layout.values.ValueFactory.render` so a solved
value can never violate the field's PICTURE, the same invariant the copybook
generator's own value providers already guarantee.
"""

from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation, localcontext

from .._vocabulary import ZERO_WORDS
from ..layout.fields import FieldCategory, FieldSpec
from ..layout.options import DataGeneratorOptions
from ..layout.values import ValueFactory
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
_ZERO_FIGURATIVES = ZERO_WORDS
#: Figurative constants whose value is a byte no generated field carries:
#: LOW-VALUE is X'00' and HIGH-VALUE X'FF' in every position, and NULL is
#: binary zeros. ``ValueFactory`` generates characters, and its own table
#: maps these words to "" -- which renders as *spaces*. A witness built that
#: way for ``IF X = LOW-VALUES`` is a field of blanks the branch never
#: takes, so the positive test is unsatisfiable here, not "satisfied".
_UNREPRESENTABLE_FIGURATIVES = frozenset(
    {"LOW-VALUE", "LOW-VALUES", "HIGH-VALUE", "HIGH-VALUES", "NULL", "NULLS"}
)
#: The domain a COMP-1/COMP-2 field is solved over: signed, +/-1E15 (the
#: largest magnitude a COMP-2 still holds to the unit), on a grid of
#: ``FLOAT_DECIMALS`` places -- the same quantisation ``values.py`` gives a
#: freely drawn float value.
FLOAT_LIMIT = Decimal("1E15")
FLOAT_DECIMALS = 4
#: A sign token detached from its digits by the lexer: ``- 5`` / ``+ 7``.
_SIGN_SPACE_RE = re.compile(r"^([+-])\s+")


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
    #: Class conditions narrowing what characters the value may be made of.
    #: ``None`` means the class was never tested; ``True``/``False`` mean the
    #: value must / must not be of that class.  An alphanumeric field can
    #: hold digits, so ``IF WS-TXT IS NUMERIC`` over a ``PIC X`` item is
    #: satisfiable and gets a digit string -- it used to get ``XXXXXXXX``,
    #: which satisfies neither arm while being reported as satisfying both.
    require_numeric: bool | None = None
    require_alphabetic: bool | None = None

    def _matches_classes(self, candidate: str) -> bool:
        stripped = candidate.strip()
        if self.require_numeric is not None:
            # NUMERIC tests every character position of the item: a value
            # shorter than the field is space-padded when moved in, and a
            # space is not a digit -- "00000000" in a PIC X(10) is NOT
            # NUMERIC. Only a value filling the whole width can be numeric.
            padded = candidate.ljust(self.size)
            is_numeric = padded.isascii() and padded.isdigit()
            if is_numeric is not self.require_numeric:
                return False
        if self.require_alphabetic is not None:
            is_alpha = bool(stripped) and all(
                ch.isalpha() or ch == " " for ch in stripped
            )
            if is_alpha is not self.require_alphabetic:
                return False
        return True

    def pick(self) -> str | None:
        if self.allowed is not None:
            for candidate in sorted(self.allowed - self.forbidden):
                if self._matches_classes(candidate):
                    return candidate
            return None
        n = max(1, min(self.size, 8))
        if self.require_numeric:
            # Short of the field's width the value is space-padded, which
            # no NUMERIC test accepts (see `_matches_classes`).
            n = max(1, self.size)
        # Digits first when the field must be numeric, letters otherwise --
        # then the other alphabet as a fallback, so a `forbidden` entry
        # covering every candidate of one shape can still be escaped.
        alphabets = "0123456789" if self.require_numeric else "XYZABCDEFGH"
        fallback = "XYZABCDEFGH" if self.require_numeric else "0123456789"
        for char in itertools.chain(alphabets, fallback):
            candidate = char * n
            if candidate not in self.forbidden and self._matches_classes(candidate):
                return candidate
        return None


@dataclass
class EnumDomain:
    values: list[str]  # remaining allowed values, in declared order

    def pick(self) -> str | None:
        return self.values[0] if self.values else None


Domain = NumericDomain | TextDomain | EnumDomain


#: The SQLCODEs tried first, in order, for the synthetic SQLCODE an EXEC SQL
#: leaves (``SQL@<line>.SQLCODE``, #840), so a witness reads like a real
#: outcome -- 0, 100 not found, -911 deadlock -- instead of an interval
#: midpoint. A FETCH's tries 100 before 0: a success witness on a looped
#: FETCH would not end the loop that reads it, and its rows already stand
#: for success.
SQLCODE_PREFERENCES = {
    "SQL": ("0", "100", "-911", "-805", "-803", "-811", "-904", "-180"),
    "FETCH": ("100", "-911", "-904", "-180", "0"),
}


def _preferred_values(spec: FieldSpec) -> tuple[str, ...]:
    """Values to try before the picture domain's own pick (#840)."""
    if spec.name != "SQLCODE" or len(spec.path) != 2:
        return ()
    kind, _, line = str(spec.path[0]).partition("@")
    if not line.isdigit():
        return ()
    return SQLCODE_PREFERENCES.get(kind, ())


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
        # A figurative word among the 88 VALUEs (`VALUE SPACES`) is not a
        # literal the field can hold as written: picked here it rendered as
        # "SPA" into a PIC X(3). Leave it out of the preference list.
        domain = EnumDomain(
            [v for v in spec.condition_values if v.upper() not in _FIGURATIVE_VALUES]
        )
        if all(_apply(domain, c) is None for c in constraints):
            # The enum narrows only by set ops; a relational conjunct
            # alongside one (`IF NOT HIGH-V AND WS-C > 5`) is a no-op there.
            # So each surviving declared value is re-checked against EVERY
            # conjunct in the field's real (picture) domain, and the first
            # that holds is the witness. None holding falls through to the
            # picture domain, which solves the relational part itself.
            for candidate in domain.values:
                pinned = _pinned_picture_domain(spec, candidate, constraints)
                if pinned is not None:
                    domain = pinned
                    witness = pinned.pick()
                    break

    if witness is None and constraints:
        for candidate in _preferred_values(spec):
            pinned = _pinned_picture_domain(spec, candidate, constraints)
            if pinned is not None:
                domain = pinned
                witness = pinned.pick()
                break

    if witness is None:
        domain = _picture_domain(spec)
        for constraint in constraints:
            reason = _apply(domain, constraint)
            if reason is not None:
                return Unsatisfiable(
                    f"{reason} after applying {constraint.op} "
                    f"from {constraint.origin}"
                )
        witness = domain.pick()

    if witness is None:
        return Unsatisfiable("no witness available in domain")

    factory = ValueFactory(random.Random(0), DataGeneratorOptions())
    rendered = factory.render(spec, str(witness))
    if (
        isinstance(domain, TextDomain)
        and domain.allowed is not None
        and rendered != str(witness)
    ):
        # Rendering truncates to the field's width: `IF WS-X = 'AB'` on a
        # PIC X field picked 'AB' and rendered 'A', which the branch can
        # never match. A literal the field cannot hold whole is a branch
        # this field's data cannot reach.
        return Unsatisfiable(
            f"literal {witness!r} does not fit the "
            f"{spec.character_positions}-character field "
            f"{spec.qualified_name} (rendered {rendered!r})"
        )
    if isinstance(domain, TextDomain) and not domain._matches_classes(rendered):
        # Same defensive role as the numeric check below: rendering pads and
        # justifies, and a witness whose RENDERED form no longer satisfies the
        # class test it was picked for must not escape as one that does.
        return Unsatisfiable(
            f"rendered witness {rendered!r} no longer satisfies the class test"
        )
    if isinstance(domain, NumericDomain) and not _rendered_numeric_ok(rendered, domain):
        # Defensive: grid-based picking should make this unreachable, but a
        # witness whose RENDERED form violates the constraint set must never
        # escape (rendering used to round a fractional midpoint onto an
        # excluded value).
        return Unsatisfiable(
            f"rendered witness {rendered!r} violates the constraint set"
        )
    return Witness(rendered)


def _pinned_picture_domain(
    spec: FieldSpec, candidate: str, constraints: list[FieldConstraint]
) -> Domain | None:
    """*spec*'s picture domain narrowed to *candidate* and then by every
    conjunct, or ``None`` when *candidate* violates any of them."""
    domain = _picture_domain(spec)
    pin = FieldConstraint(
        constraints[0].field, "eq", (candidate,), "level-88 candidate"
    )
    for constraint in (pin, *constraints):
        if _apply(domain, constraint) is not None:
            return None
    return domain


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
    if spec.category is FieldCategory.FLOAT:
        # COMP-1/COMP-2 have no PICTURE; the layout's 9-digit unsigned
        # integer shape is a placeholder that made `IF F < -100` or
        # `IF F > 0.25 AND F < 0.75` "unsatisfiable".
        return NumericDomain(lo=-FLOAT_LIMIT, hi=FLOAT_LIMIT, decimals=FLOAT_DECIMALS)
    if spec.category in (FieldCategory.NUMERIC, FieldCategory.NUMERIC_EDITED):
        return _initial_numeric_domain(spec)
    return TextDomain(
        allowed=None, forbidden=set(), size=max(1, spec.character_positions)
    )


def _initial_numeric_domain(spec: FieldSpec) -> NumericDomain:
    digits = spec.integer_digits
    decimals = spec.decimal_digits
    ceiling = (
        Decimal(10**digits - 1)
        if decimals == 0
        else Decimal(10**digits) - Decimal(1).scaleb(-decimals)
    )
    lo = -ceiling if spec.is_signed else Decimal(0)
    bounds = getattr(spec, "odo_counter_bounds", None)
    if bounds is not None:
        # The counter of an `OCCURS m TO n DEPENDING ON` table: any value
        # outside m..n is not a record the program can be handed (the
        # table would run past the record), and a loop over the table
        # driven by it runs off the end -- `PIC 99` at its picture's 99
        # with `OCCURS 0 TO 5` made a generated case loop forever.
        lo = max(lo, Decimal(bounds[0]))
        ceiling = min(ceiling, Decimal(bounds[1]))
    return NumericDomain(lo=lo, hi=ceiling, decimals=decimals)


def _epsilon(decimals: int) -> Decimal:
    return Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)


#: Why a domain rejected a constraint, when the reason is simply "nothing is
#: left that satisfies it". Distinguished from the text domain's own reasons,
#: which name an op the domain cannot model at all -- a different finding for
#: whoever reads it off `ScenarioCoverage`.
_EMPTY = "empty domain"


def _apply(domain: Domain, c: FieldConstraint) -> str | None:
    """Narrow *domain* by *c*. ``None`` on success, else why it failed."""
    if isinstance(domain, EnumDomain):
        return None if _apply_enum(domain, c) else _EMPTY
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


def _apply_numeric(domain: NumericDomain, c: FieldConstraint) -> str | None:
    """Narrow *domain* by *c*. ``None`` on success, else why it failed --
    the same contract as :func:`_apply_text`."""
    if c.op == "figurative":
        fig = c.values[0].upper() if c.values else ""
        if fig not in _ZERO_FIGURATIVES:
            if c.negated:
                return None  # no number is SPACES/LOW-VALUES: every one differs
            # A numeric witness can never *be* SPACES / LOW-VALUES / QUOTES:
            # the branch that needs one is not reachable with generated data.
            return f"a numeric field cannot be generated equal to {fig or 'it'}"
        return _apply_numeric(
            domain,
            FieldConstraint(c.field, "ne" if c.negated else "eq", ("0",), c.origin),
        )

    # Set ops reach a numeric domain only via the enum-domain fallback in
    # solve() (a level-88 field whose enum was emptied), and must be enforced
    # rather than no-op'd: a witness that silently violates `not_in_set` would
    # be an "exact by construction" promise the value does not keep.
    #
    # This block MUST stay above the catch-all guard below, which succeeds
    # for every op outside the relational set -- a set op placed after it is
    # dead code that no-ops silently. It shipped that way once and the numeric
    # test was too weak to notice (its midpoint witness happened to miss the
    # excluded value); `test_numeric_field_enforces_not_in_set_after_fallback`
    # now bounds the domain so the midpoint lands exactly on it.
    if c.op in ("in_set", "not_in_set"):
        parsed = []
        for raw in c.values:
            try:
                candidate = Decimal(_numeric_literal_text(raw))
            except InvalidOperation:
                continue
            if candidate.is_finite():
                parsed.append(candidate)
        if not parsed:
            return None
        if c.op == "not_in_set":
            domain.excluded.update(parsed)
            return (
                None
                if domain.lo < domain.hi or domain.lo not in domain.excluded
                else _EMPTY
            )
        # in_set: an interval cannot express a discrete allow-set, so narrow
        # to the first admissible member -- sound (it satisfies the set) and
        # deterministic, at the cost of generality no caller depends on.
        for candidate in parsed:
            if domain.lo <= candidate <= domain.hi and candidate not in domain.excluded:
                domain.lo = domain.hi = candidate
                domain.excluded = set()
                return None
        return _EMPTY

    if c.op not in ("eq", "ne", "gt", "ge", "lt", "le"):
        return None  # class_numeric/class_alphabetic: no-op on a numeric domain in v1

    if not c.values:
        return None
    try:
        value = Decimal(_numeric_literal_text(c.values[0]))
    except InvalidOperation:
        # A literal the numeric field cannot hold (`IF WS-CNT = 'X'`, or a
        # malformed number). Dropping the constraint used to hand back a
        # witness that satisfied the arm's OTHER conjuncts and let the arm
        # count as targeted; nothing generatable satisfies it, and saying so
        # is what lands the arm in ScenarioCoverage as missed with a reason.
        return (
            f"literal {c.values[0]!r} is not a number the numeric field "
            f"{c.field.spec.qualified_name} can hold"
        )
    if not value.is_finite():
        return f"literal {c.values[0]!r} is not a finite number"

    if c.op == "eq":
        if not (domain.lo <= value <= domain.hi) or value in domain.excluded:
            return _EMPTY
        domain.lo = domain.hi = value
        domain.excluded = set()
        return None
    if c.op == "ne":
        domain.excluded.add(value)
        return (
            None
            if domain.lo < domain.hi or domain.lo not in domain.excluded
            else _EMPTY
        )
    # Same wide-precision reasoning as NumericDomain.pick(): a strict bound
    # nudged by one grid epsilon must stay exact for the widest PICTUREs.
    if c.op == "gt":
        with localcontext() as ctx:
            ctx.prec = 80
            domain.lo = max(domain.lo, value + _epsilon(domain.decimals))
        return None if domain.lo <= domain.hi else _EMPTY
    if c.op == "ge":
        domain.lo = max(domain.lo, value)
        return None if domain.lo <= domain.hi else _EMPTY
    if c.op == "lt":
        with localcontext() as ctx:
            ctx.prec = 80
            domain.hi = min(domain.hi, value - _epsilon(domain.decimals))
        return None if domain.lo <= domain.hi else _EMPTY
    if c.op == "le":
        domain.hi = min(domain.hi, value)
        return None if domain.lo <= domain.hi else _EMPTY
    return None


def _numeric_literal_text(raw: str) -> str:
    """*raw* with the sign-then-space shape a detached sign token leaves
    (``- 5``) collapsed to ``-5``.  The extractor normalises this at the
    source; doing it again here costs nothing and protects a caller that
    builds a :class:`FieldConstraint` by hand."""
    return _SIGN_SPACE_RE.sub(r"\1", raw.strip())


def _apply_text(domain: TextDomain, c: FieldConstraint) -> str | None:
    if c.op == "figurative" and c.values:
        fig = c.values[0].upper()
        if fig in _UNREPRESENTABLE_FIGURATIVES:
            if c.negated:
                # Every generated (character) value differs from X'00' /
                # X'FF', so the negated test narrows nothing.
                return None
            return f"{fig} is a binary value generated character data never holds"
    if c.op in ("eq", "in_set") or (c.op == "figurative" and not c.negated):
        values = _text_values(c, domain.size)
        domain.allowed = values if domain.allowed is None else (domain.allowed & values)
        return None if domain.allowed else _EMPTY
    if c.op in ("ne", "not_in_set") or (c.op == "figurative" and c.negated):
        values = _text_values(c, domain.size)
        domain.forbidden |= values
        if domain.allowed is not None:
            domain.allowed -= domain.forbidden
            return None if domain.allowed else _EMPTY
        return None

    # Class conditions ARE enforceable here -- an alphanumeric field can hold
    # digits or letters, and which one it holds is exactly what the branch
    # turns on. Contradicting an earlier test of the same class empties the
    # domain rather than quietly overwriting it.
    if c.op in ("class_numeric", "class_alphabetic"):
        wanted = not c.negated
        attr = "require_numeric" if c.op == "class_numeric" else "require_alphabetic"
        current = getattr(domain, attr)
        if current is not None and current is not wanted:
            return _EMPTY
        setattr(domain, attr, wanted)
        # A field required to be both numeric and alphabetic is unsatisfiable
        # -- say so here rather than letting pick() fail with a vaguer reason.
        if domain.require_numeric and domain.require_alphabetic:
            return _EMPTY
        return None

    # Ordering over a text domain is the one thing a bare allow/deny set
    # genuinely cannot express. Reporting it as satisfied used to hand back a
    # witness that did not satisfy it -- and, for the negated arm of the same
    # branch, the identical witness. Unsatisfiable is the honest answer: the
    # arm lands in ScenarioCoverage as missed, carrying this reason.
    return f"{c.op} on an alphanumeric domain is not modeled in v1"


def _text_values(c: FieldConstraint, size: int) -> set[str]:
    if c.op == "figurative":
        if not c.values:
            return {""}
        unit = _FIGURATIVE_VALUES.get(c.values[0].upper(), "")
        # A figurative constant compared with an alphanumeric field stands
        # for its character repeated to the field's whole width: `IF X =
        # ZEROS` on a PIC X(3) is true only for "000". A bare "0" renders
        # (left-justified, space-padded) as "0  ", which the branch never
        # takes. SPACES stays "" -- the padding IS the repetition.
        return {unit * max(1, size)} if unit else {""}
    return set(c.values)


__all__ = [
    "Unsatisfiable",
    "Witness",
    "NumericDomain",
    "TextDomain",
    "EnumDomain",
    "solve",
]
