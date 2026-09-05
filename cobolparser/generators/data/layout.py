"""Field flattening: decompose record structures into generatable field specs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from ...models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    PictureClause,
)
from .options import DataGeneratorOptions
from .storage import storage_size


class FieldCategory(StrEnum):
    """Data category of an elementary field, driving value generation."""

    ALPHANUMERIC = "alphanumeric"
    ALPHABETIC = "alphabetic"
    NATIONAL = "national"
    NUMERIC = "numeric"
    NUMERIC_EDITED = "numeric-edited"
    ALPHANUMERIC_EDITED = "alphanumeric-edited"
    FLOAT = "float"


@dataclass(frozen=True)
class OdoControl:
    """One ``OCCURS ... DEPENDING ON`` dimension a field sits inside.

    The layout is always flattened at the table's *maximum*, because a
    ``FieldSpec`` list has to describe every byte the record could occupy.
    Whether a given occurrence is actually *present* in a given record is a
    per-row question, answered at encoding time from the counter's own
    generated value -- which is what makes variable-length output possible
    without a second flattening pass.

    Attributes:
        depending_on: The counter data name from the ``DEPENDING ON`` phrase.
        subscript_index: Position in :attr:`FieldSpec.subscripts` of the
            dimension this counter controls.  A field is present in a record
            iff ``subscripts[subscript_index] <= counter`` for every control
            it carries -- nested ODO tables each contribute one.
        min_times: Lower bound from ``OCCURS min TO max``.
        max_times: Upper bound from ``OCCURS min TO max``, already clamped to
            the occurrences the layout actually expanded (``max_occurs`` and
            the hard cap can both cut a table short, and a counter naming an
            occurrence that was never flattened would describe bytes that do
            not exist).
    """

    depending_on: str
    subscript_index: int
    min_times: int
    max_times: int

    def to_dict(self) -> dict[str, Any]:
        """Serialise the control (used by the CLI's ``--describe`` output)."""
        return {
            "depending_on": self.depending_on,
            "subscript_index": self.subscript_index,
            "min_times": self.min_times,
            "max_times": self.max_times,
        }


@dataclass(frozen=True)
class VaryingLength:
    """An FD's declared record-length range: how long a record may be.

    The *other* way a COBOL record varies, and the one an ``OCCURS ...
    DEPENDING ON`` walk cannot see::

        FD  EMPFILE
            RECORD VARYING FROM 47 TO 80 CHARACTERS
                   DEPENDING ON EMPREC-LEN
            RECORDING MODE IS V.
        01  EMP-RECORD80.
            ...

    The record layout here is an ordinary fixed one -- no table, nothing
    subordinate to a counter.  What varies is how many of its bytes each
    record actually carries; the program sets ``EMPREC-LEN`` before a WRITE
    and reads it back after a READ, and the length itself travels in the
    RDW rather than anywhere in the record.  So the length has to be drawn
    per record at generation time (see
    :meth:`~.copybook.CopybookDataGenerator.generate_from_record`) and
    handed to the encoder, which is exactly what ``data_length`` on
    :func:`.encoding.encode_record` is for.

    ``RECORD CONTAINS 47 TO 80`` declares the same thing without the
    ``VARYING`` keyword and is treated identically.

    Attributes:
        minimum: Shortest record the FD permits, in bytes.
        maximum: Longest, already clamped to the bytes the record layout
            actually describes -- an FD promising more than its own 01 can
            hold is a mismatch, reported as a caveat rather than padded.
        depending_on: The ``DEPENDING ON`` data name, when the clause has
            one.  Usually a WORKING-STORAGE item rather than part of the
            record, which is why it is recorded but rarely writable.
    """

    minimum: int
    maximum: int
    depending_on: str | None = None

    @classmethod
    def from_fd_clauses(
        cls, clauses: dict[str, Any] | None, *, record_size: int
    ) -> VaryingLength | None:
        """Read an FD's ``RECORD`` clause, or ``None`` if it declares no range.

        *record_size* clamps :attr:`maximum`; see its note above.
        """
        block = (clauses or {}).get("record") or {}
        low, high = block.get("min"), block.get("max")
        if low is None or high is None or low == high:
            return None
        return cls.build(int(low), int(high), block.get("depending_on"), record_size)

    @classmethod
    def build(
        cls,
        minimum: int,
        maximum: int,
        depending_on: str | None,
        record_size: int,
    ) -> VaryingLength | None:
        """A range clamped into what the layout can actually produce."""
        low, high = sorted((max(0, minimum), max(0, maximum)))
        if record_size > 0:
            low, high = min(low, record_size), min(high, record_size)
        return cls(low, high, depending_on) if high > low else None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the range (used by the CLI's ``--describe`` output)."""
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "depending_on": self.depending_on,
        }


@dataclass
class FieldSpec:
    """One generated CSV column: an elementary field of the record.

    Attributes:
        name: The field's own COBOL data name.
        path: Ancestor names from the record root down to (and including)
            this field.
        column: Header used in the CSV -- unique across the record.
        level: COBOL level number.
        picture: PICTURE string, or ``None`` for pictureless items
            (``COMP-1``/``COMP-2``, ``INDEX``, ``POINTER``).
        usage: USAGE clause, defaulting to ``DISPLAY``.
        category: Data category driving value generation.
        size: Character positions the item occupies in DISPLAY form.
        integer_digits: Digit positions left of the decimal point.
        decimal_digits: Digit positions right of the decimal point.
        is_signed: Whether the field can hold a negative value.  True for an
            explicit ``S``, and also for a numeric-edited picture carrying a
            ``+``/``-`` insertion symbol or the ``CR``/``DB`` credit-debit
            symbols (``PIC -ZZ,ZZ9.99``) -- broader than
            :attr:`PictureClause.is_signed`, which reports only the ``S``.
        value_clause: Raw VALUE clause literal, if any.
        condition_values: Flattened level-88 values, ranges expanded.
        subscripts: OCCURS subscript path, empty for non-table fields.
        redefines: Name of the item this field's group redefines, if any.
        is_filler: Whether the item is FILLER.
        sign_clause: Raw ``SIGN IS`` clause (``"LEADING SEPARATE"``), if any.
            ``SEPARATE`` is the reason :attr:`storage_size` can exceed
            :attr:`size`: the sign gets a byte the PICTURE does not count.
        synchronized: Whether the item carries ``SYNCHRONIZED``.  Recorded
            rather than acted on -- see :func:`.encoding.encoding_caveats`.
        occurs_depending_on: The controlling data name when this field sits
            inside an ``OCCURS ... DEPENDING ON`` table (the outermost one,
            when several nest), else ``None``.  The table is always
            flattened at its maximum, so this marks where that assumption
            was made.
        odo_controls: Every ``OCCURS ... DEPENDING ON`` dimension this field
            sits inside, outermost first -- the machine-readable form of
            :attr:`occurs_depending_on`, and what
            :func:`.encoding.encode_record` consults to decide whether this
            occurrence belongs in a variable-length record.
        odo_counter_bounds: ``(min, max)`` occurrence counts this field
            *controls*, when it is itself the counter named by some table's
            ``DEPENDING ON`` phrase.  ``None`` for every other field.  Set on
            the counter rather than derived at generation time so
            :class:`~.values.ValueFactory` can draw a count the table can
            actually hold instead of any value the PICTURE permits.
    """

    name: str
    path: tuple[str, ...]
    column: str
    level: int
    picture: str | None
    usage: str
    category: FieldCategory
    size: int
    integer_digits: int
    decimal_digits: int
    is_signed: bool
    value_clause: str | None = None
    condition_values: list[str] = field(default_factory=list)
    subscripts: tuple[int, ...] = ()
    redefines: str | None = None
    is_filler: bool = False
    sign_clause: str | None = None
    synchronized: bool = False
    occurs_depending_on: str | None = None
    odo_controls: tuple[OdoControl, ...] = ()
    odo_counter_bounds: tuple[int, int] | None = None

    @property
    def storage_size(self) -> int:
        """Bytes one occurrence of this field really occupies.

        Distinct from :attr:`size`, which counts PICTURE *character
        positions*: a ``PIC S9(7)V99 COMP-3`` field has ``size == 9`` and
        ``storage_size == 5``.  Everything that lays out or encodes a record
        wants this one; only CSV-shaped output wants ``size``.
        """
        return storage_size(
            self.usage,
            picture_size=self.size,
            total_digits=self.integer_digits + self.decimal_digits,
            sign_clause=self.sign_clause,
            is_signed=self.is_signed,
        )

    @property
    def qualified_name(self) -> str:
        """Dotted path from the record root, e.g. ``CUST-REC.ADDRESS.CITY``."""
        return ".".join(self.path)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the field spec (used by the CLI's ``--describe`` output)."""
        return {
            "name": self.name,
            "column": self.column,
            "qualified_name": self.qualified_name,
            "level": self.level,
            "picture": self.picture,
            "usage": self.usage,
            "category": self.category.value,
            "size": self.size,
            "storage_size": self.storage_size,
            "integer_digits": self.integer_digits,
            "decimal_digits": self.decimal_digits,
            "is_signed": self.is_signed,
            "value_clause": self.value_clause,
            "condition_values": list(self.condition_values),
            "subscripts": list(self.subscripts),
            "redefines": self.redefines,
            "sign_clause": self.sign_clause,
            "synchronized": self.synchronized,
            "occurs_depending_on": self.occurs_depending_on,
            "odo_controls": [c.to_dict() for c in self.odo_controls],
            "odo_counter_bounds": (
                list(self.odo_counter_bounds) if self.odo_counter_bounds else None
            ),
        }


# Module-level constants
_MAX_RANGE_EXPANSION = 64
# Hard ceiling on OCCURS expansion, independent of ``max_occurs``. A copybook
# with a bogus or pathological ``OCCURS`` count (e.g. millions of times) would
# otherwise materialize one FieldSpec per occurrence per field, exhausting
# memory well before any caller-supplied cap kicks in.
_MAX_OCCURS_HARD_CAP = 10_000

_REPEAT_COUNT_RE = re.compile(r"\(\d+\)")
_THROUGH_RE = re.compile(r"^THROUGH:(.*)$", re.IGNORECASE)
# An optionally-signed integer literal, used to decide whether a level-88
# ``THRU`` range can be expanded. Both endpoints are tested the same way: the
# sign has to be accepted on either side, not just the first.
_INTEGER_LITERAL_RE = re.compile(r"^[+-]?\d+$")


def _child_items(item: CobolDataItem) -> list[CobolDataItem]:
    return [c for c in item.children if isinstance(c, CobolDataItem)]


def expand_condition_values(raw_values: list[str]) -> list[str]:
    """Expand one condition name's raw VALUE literals, THRU ranges included.

    The parser records ``VALUE 2 THRU 4`` as ``["2", "THROUGH:4"]`` -- the
    range end is marked rather than expanded. Numeric ranges are expanded
    here (bounded, so ``VALUE 1 THRU 999999`` cannot blow up memory); a
    non-numeric range contributes only its endpoints.
    """
    values: list[str] = []
    previous: str | None = None
    for raw in raw_values:
        match = _THROUGH_RE.match(raw)
        if match is None:
            cleaned = _strip_literal_quotes(raw)
            values.append(cleaned)
            previous = cleaned
            continue
        end = _strip_literal_quotes(match.group(1))
        start = previous
        if (
            start is not None
            and _INTEGER_LITERAL_RE.match(start)
            and _INTEGER_LITERAL_RE.match(end)
        ):
            low, high = int(start), int(end)
            if low > high:
                low, high = high, low
            # Cap the expansion: the point is a representative domain,
            # not an exhaustive enumeration of a six-digit range.
            high = min(high, low + _MAX_RANGE_EXPANSION)
            # Emit the closed interval, both endpoints included. Iterating
            # from ``low`` rather than from ``start`` is what makes a
            # descending ``VALUE 4 THRU 2`` yield 2 as well as 3 and 4;
            # the ``dict.fromkeys`` dedup below drops the repeated
            # endpoint that ``start`` already contributed.
            values.extend(str(value) for value in range(low, high + 1))
        elif end:
            values.append(end)
        previous = end
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(v for v in values if v != ""))


def _condition_values(item: CobolDataItem) -> list[str]:
    """Collect level-88 VALUEs under *item*, merged across all its
    level-88 children -- FieldSpec.condition_values needs "any value that
    could apply to this field", not one condition name's values in
    isolation. See ``expand_condition_values`` for the per-name expansion
    this delegates to.
    """
    values: list[str] = []
    for child in item.children:
        if not isinstance(child, ConditionNameItem):
            continue
        values.extend(expand_condition_values(child.values))
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(v for v in values if v != ""))


def _strip_literal_quotes(value: str) -> str:
    """Remove the surrounding quotes from a COBOL literal, if present."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _classify(item: CobolDataItem, picture: PictureClause | None) -> FieldCategory:
    """Determine the data category used to pick a value generator."""
    usage = (item.usage or "DISPLAY").upper()
    if usage in ("COMP-1", "COMPUTATIONAL-1", "COMP-2", "COMPUTATIONAL-2"):
        return FieldCategory.FLOAT
    if picture is None:
        # INDEX/POINTER and friends carry no picture; treat as small integers.
        return FieldCategory.NUMERIC
    if picture.is_numeric_edited:
        return FieldCategory.NUMERIC_EDITED
    if picture.is_alphanumeric_edited:
        return FieldCategory.ALPHANUMERIC_EDITED

    core = _REPEAT_COUNT_RE.sub("", picture.pattern.upper())
    symbols = set(core)
    if symbols and symbols <= {"A", "B"}:
        return FieldCategory.ALPHABETIC
    if "N" in symbols and not symbols & {"9", "X", "A"}:
        return FieldCategory.NATIONAL
    if "9" in symbols and not symbols & {"X", "A"}:
        return FieldCategory.NUMERIC
    return FieldCategory.ALPHANUMERIC


def _is_signed(picture: PictureClause | None) -> bool:
    """True when the picture can hold a negative value.

    ``PictureClause.is_signed`` only reports an explicit ``S``.  A
    numeric-edited item has no ``S`` but still holds a sign whenever it
    carries a ``+``/``-`` insertion symbol or the ``CR``/``DB`` credit-debit
    symbols -- ``PIC -ZZ,ZZ9.99`` is the canonical signed display field.
    """
    if picture is None:
        return False
    if picture.is_signed:
        return True
    if not picture.is_numeric_edited:
        return False
    core = _REPEAT_COUNT_RE.sub("", picture.pattern.upper())
    return any(symbol in core for symbol in ("-", "+", "CR", "DB"))


def _digit_counts(picture: PictureClause | None) -> tuple[int, int]:
    """Return ``(integer_digits, decimal_digits)`` with sane fallbacks."""
    if picture is None:
        return (9, 0)
    integer_digits = picture.integer_digits
    decimal_digits = picture.decimal_digits or 0
    if integer_digits is None:
        total = picture.total_digits
        integer_digits = (total - decimal_digits) if total else 0
    return (max(0, integer_digits), max(0, decimal_digits))


def flatten_record(
    record: CobolDataItem,
    options: DataGeneratorOptions | None = None,
) -> list[FieldSpec]:
    """Flatten *record* into the ordered list of columns to generate.

    Walks the record depth-first, descending through group items and emitting
    one :class:`FieldSpec` per elementary item (per occurrence, for tables).
    """
    opts = options or DataGeneratorOptions()
    specs: list[FieldSpec] = []
    _flatten_into(record, (), (), None, (), opts, specs)
    _link_odo_counters(specs)
    _assign_columns(specs, opts)
    return specs


def _flatten_into(
    item: CobolDataItem,
    path: tuple[str, ...],
    subscripts: tuple[int, ...],
    redefines: str | None,
    odo_controls: tuple[OdoControl, ...],
    opts: DataGeneratorOptions,
    out: list[FieldSpec],
) -> None:
    """Recursive worker for :func:`flatten_record`."""
    # A REDEFINES anywhere up the chain taints every field beneath it.
    inherited_redefines = redefines or item.redefines
    if inherited_redefines and not opts.include_redefines:
        return
    if item.is_filler and not opts.include_filler:
        return
    # Level-66 RENAMES and level-88 condition names are not storage of their
    # own; they are handled via their parent item.
    if item.level in (66, 88):
        return

    # An OCCURS ... DEPENDING ON anywhere up the chain marks everything
    # beneath it: the table is flattened at its maximum, and the field needs
    # to carry where that assumption came from -- and, for variable-length
    # output, which of its subscripts the counter governs.
    occurs = item.occurs_clause
    indexes = _occurrence_indexes(item, opts)
    inherited_controls = odo_controls
    if occurs is not None and occurs.depending_on:
        inherited_controls = (
            *odo_controls,
            OdoControl(
                depending_on=occurs.depending_on,
                # The dimension this table adds sits at the end of the
                # subscript tuple its children will carry, which is exactly
                # the current tuple's length.
                subscript_index=len(subscripts),
                min_times=max(
                    0,
                    min(
                        # `or 1` would read a declared `OCCURS 0 TO n` as 1.
                        1 if occurs.min_times is None else occurs.min_times,
                        len(indexes),
                    ),
                ),
                # Not occurs.max_times: max_occurs and the hard cap can both
                # stop the flattening short, and a counter allowed to name
                # occurrence 50 of a table flattened to 10 would describe
                # bytes no FieldSpec covers.
                max_times=len(indexes),
            ),
        )

    item_path = (*path, item.name)
    for index in indexes:
        occ = (*subscripts, index) if index is not None else subscripts
        children = _child_items(item)
        if children:
            for child in children:
                _flatten_into(
                    child,
                    item_path,
                    occ,
                    inherited_redefines,
                    inherited_controls,
                    opts,
                    out,
                )
            continue

        picture = item.picture_clause
        category = _classify(item, picture)
        integer_digits, decimal_digits = _digit_counts(picture)
        size = (picture.size if picture and picture.size else 0) or max(
            1, integer_digits + decimal_digits
        )
        out.append(
            FieldSpec(
                name=item.name,
                path=item_path,
                column=item.name,
                level=item.level,
                picture=picture.pattern if picture else None,
                usage=(item.usage or "DISPLAY").upper(),
                category=category,
                size=size,
                integer_digits=integer_digits,
                decimal_digits=decimal_digits,
                is_signed=_is_signed(picture),
                value_clause=item.value_clause,
                condition_values=_condition_values(item),
                subscripts=occ,
                redefines=inherited_redefines,
                is_filler=item.is_filler,
                sign_clause=item.sign_clause,
                synchronized=item.synchronized,
                occurs_depending_on=(
                    inherited_controls[0].depending_on if inherited_controls else None
                ),
                odo_controls=inherited_controls,
            )
        )


def _occurrence_indexes(
    item: CobolDataItem, opts: DataGeneratorOptions
) -> list[int | None]:
    """Return the subscripts to emit for *item* (``[None]`` when not a table)."""
    occurs = item.occurs_clause
    if occurs is None:
        return [None]
    times = occurs.max_times or occurs.min_times or 1
    if not opts.expand_occurs:
        times = 1
    else:
        if opts.max_occurs is not None:
            times = min(times, opts.max_occurs)
        times = min(times, _MAX_OCCURS_HARD_CAP)
    return list(range(1, max(1, times) + 1))


def _assign_columns(specs: list[FieldSpec], opts: DataGeneratorOptions) -> None:
    """Give every spec a unique CSV header.

    COBOL permits the same data name in different groups (disambiguated by
    ``OF``), so a short-name header can collide.  Collisions fall back to the
    qualified path, and any residual duplicate gets a numeric suffix -- a CSV
    header must be unique for consumers to address it.

    Repeats of the same name from a single OCCURS table are *not* a collision:
    the subscript suffix already tells them apart, so ``ITEM-CODE(1)`` stays
    short rather than becoming ``REC.TAB.ITEM-CODE(1)``.
    """
    paths_by_name: dict[str, set[str]] = {}
    for spec in specs:
        paths_by_name.setdefault(spec.name, set()).add(spec.qualified_name)

    used: set[str] = set()
    for spec in specs:
        ambiguous = len(paths_by_name[spec.name]) > 1
        if opts.header_style == "path" or ambiguous:
            base = spec.qualified_name
        else:
            base = spec.name
        if spec.subscripts:
            base += "(" + ",".join(str(s) for s in spec.subscripts) + ")"
        column = base
        suffix = 2
        while column in used:
            column = f"{base}_{suffix}"
            suffix += 1
        used.add(column)
        spec.column = column


# ---------------------------------------------------------------------------
# OCCURS DEPENDING ON: from a flattened layout to one row's real occurrences
# ---------------------------------------------------------------------------


def _link_odo_counters(specs: list[FieldSpec]) -> None:
    """Stamp :attr:`FieldSpec.odo_counter_bounds` onto each table's counter.

    Run once per flattening, over the finished list, because a counter is
    normally declared *before* the table that depends on it -- its spec
    already exists by the time the ``DEPENDING ON`` phrase is seen, so the
    bounds cannot be attached during the walk itself.

    A counter governing two tables at once (legal, if odd) gets the
    intersection of their bounds, so the one value it holds names a real
    occurrence in both.  When the two do not overlap the lower bound wins:
    a count below a table's minimum still addresses bytes that exist, while
    one above its maximum does not.
    """
    bounds: dict[str, tuple[int, int]] = {}
    for spec in specs:
        for control in spec.odo_controls:
            key = control.depending_on.upper()
            existing = bounds.get(key)
            if existing is None:
                bounds[key] = (control.min_times, control.max_times)
                continue
            low = max(existing[0], control.min_times)
            high = min(existing[1], control.max_times)
            bounds[key] = (low, max(low, high))

    if not bounds:
        return
    for spec in specs:
        found = bounds.get(spec.name.upper())
        if found is not None:
            spec.odo_counter_bounds = found


def odo_counter_cells(specs: list[FieldSpec], row: list[str]) -> dict[str, str]:
    """The raw generated cell of every field that controls an ODO table.

    Keyed by upper-cased data name, which is how a ``DEPENDING ON`` phrase
    names its counter.  A layout with no ODO table returns an empty dict, and
    every caller below short-circuits on that -- so a fixed-length copybook
    pays nothing for this machinery.

    A counter that is itself inside a table has one cell per occurrence and
    they collapse here; :func:`present_indexes` resolves those by position
    instead, and only falls back to this map.
    """
    return {
        spec.name.upper(): cell
        for spec, cell in zip(specs, row, strict=True)
        if spec.odo_counter_bounds is not None
    }


def occurrence_count(control: OdoControl, cells: dict[str, str]) -> int:
    """How many occurrences of *control*'s table one row actually holds.

    The counter's own generated value, clamped into the table's bounds.  A
    counter that is missing from the record (declared outside it, which COBOL
    permits), blank (``blank_rate``), or non-numeric falls back to the
    maximum: reserving the whole table is the one answer that never claims
    bytes the layout does not describe.
    """
    raw = (cells.get(control.depending_on.upper()) or "").strip()
    if not raw:
        return control.max_times
    try:
        count = int(Decimal(raw))
    except (InvalidOperation, ValueError):
        return control.max_times
    return max(control.min_times, min(control.max_times, count))


def _counter_positions(
    specs: list[FieldSpec],
) -> dict[tuple[str, tuple[int, ...]], int]:
    """Where each ODO counter sits in *specs*, keyed by name and subscripts.

    The subscripts matter for IBM's *complex ODO* -- a ``DEPENDING ON`` table
    nested inside an ordinary ``OCCURS``, where the counter is subscripted
    too and each outer occurrence carries its own count.  Keying by name
    alone would collapse those into one, and every outer occurrence would be
    trimmed to the last one's count.
    """
    return {
        (spec.name.upper(), spec.subscripts): index
        for index, spec in enumerate(specs)
        if spec.odo_counter_bounds is not None
    }


def present_indexes(specs: list[FieldSpec], row: list[str]) -> list[int]:
    """Positions in *specs* whose bytes a record built from *row* contains.

    Every field, in order, except the occurrences of an ``OCCURS ...
    DEPENDING ON`` table beyond the count that row's counter holds.  For a
    layout without ODO -- and for every row of one whose counters all sit at
    their maximum -- this is simply every position, which is why fixed-length
    output can share the same code path.

    Dropping a trailing occurrence and concatenating what remains is exactly
    what a real variable-length record looks like: anything declared *after*
    the table shifts up into the space the absent occurrences would have
    taken, which falls out of preserving order here.
    """
    if not any(spec.odo_controls for spec in specs):
        return list(range(len(specs)))
    cells = odo_counter_cells(specs, row)
    positions = _counter_positions(specs)
    counts: dict[tuple[str, tuple[int, ...]], int] = {}
    kept: list[int] = []
    for index, spec in enumerate(specs):
        present = True
        for control in spec.odo_controls:
            name = control.depending_on.upper()
            if control.subscript_index >= len(spec.subscripts):
                # Defensive: a control always names a dimension the field's
                # own subscripts carry, since both are built in the same walk.
                continue
            # The counter governing *this* occurrence shares the field's
            # enclosing subscripts -- () for the ordinary case, and the outer
            # table's index under complex ODO.
            outer = spec.subscripts[: control.subscript_index]
            key = (name, outer)
            if key not in counts:
                at = positions.get(key)
                counts[key] = occurrence_count(
                    control, {name: row[at]} if at is not None else cells
                )
            if spec.subscripts[control.subscript_index] > counts[key]:
                present = False
                break
        if present:
            kept.append(index)
    return kept


def unresolved_odo_counters(specs: list[FieldSpec]) -> list[str]:
    """Counter names a table depends on that the layout does not contain.

    A ``DEPENDING ON`` item may live outside the record it sizes -- in
    WORKING-STORAGE, or in a record this copybook does not define.  Nothing
    can be generated for it, so its table is written at full length; this
    reports which ones, so that is stated rather than assumed.
    """
    named = {
        control.depending_on.upper() for spec in specs for control in spec.odo_controls
    }
    present = {spec.name.upper() for spec in specs}
    return sorted(named - present)
