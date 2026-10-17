"""Field flattening: decompose record structures into generatable field specs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from ..._literals import typed_literal_content, unquote_literal
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
    #: ``DEPENDING ON CNT OF HDR``: the ``OF``/``IN`` qualifiers, upper-cased
    #: -- which of several same-named items is the counter.
    qualifiers: tuple[str, ...] = ()

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

    Only a range with ``DEPENDING ON`` varies inside one record layout.
    ``RECORD CONTAINS 47 TO 80`` (RECORD format 2) and ``RECORD VARYING``
    without ``DEPENDING ON`` declare a variable-length *file*, but each
    record's length is that of the 01 record description it was written
    from -- never a cut inside a field. Those ranges are kept (the file is
    still RECFM=V, and its LRECL is still the declared maximum) with
    :attr:`per_record` false, so no length is drawn per row. An explicit
    :attr:`~.options.DataGeneratorOptions.record_varying` remains the way
    to ask for arbitrary per-record lengths without a ``DEPENDING ON``.

    Attributes:
        minimum: Shortest record the FD permits, in bytes.
        maximum: Longest, already clamped to the bytes the record layout
            actually describes -- an FD promising more than its own 01 can
            hold is a mismatch, reported as a caveat rather than padded.
        depending_on: The ``DEPENDING ON`` data name, when the clause has
            one.  Usually a WORKING-STORAGE item rather than part of the
            record, which is why it is recorded but rarely writable.
        per_record: Whether each record's length is drawn from the range.
            False for an FD range without ``DEPENDING ON``, where the range
            bounds the file and every record keeps its own 01's length.
    """

    minimum: int
    maximum: int
    depending_on: str | None = None
    per_record: bool = True

    @classmethod
    def from_fd_clauses(
        cls,
        clauses: dict[str, Any] | None,
        *,
        record_size: int,
        caveats: list[str] | None = None,
    ) -> VaryingLength | None:
        """Read an FD's ``RECORD`` clause, or ``None`` if it declares no range.

        *record_size* clamps :attr:`maximum`; see its note above, and
        :meth:`build` for *caveats*.
        """
        block = (clauses or {}).get("record") or {}
        low, high = block.get("min"), block.get("max")
        if low is None or high is None or low == high:
            return None
        depending_on = block.get("depending_on")
        if not depending_on:
            return cls.file_range(
                int(low), int(high), record_size=record_size, caveats=caveats
            )
        return cls.build(
            int(low),
            int(high),
            depending_on,
            record_size,
            caveats=caveats,
            source="FD RECORD VARYING",
        )

    @classmethod
    def file_range(
        cls,
        minimum: int,
        maximum: int,
        *,
        record_size: int,
        caveats: list[str] | None = None,
    ) -> VaryingLength | None:
        """An FD range with no ``DEPENDING ON``: bounds the file, not the record.

        IBM COBOL writes such a record at the length of the 01 record named
        on the WRITE, so the range is not clamped to this one layout (a
        10-byte header under ``RECORD CONTAINS 10 TO 20`` is as valid as the
        20-byte detail beside it). A layout outside the range is a mismatch
        and appended to *caveats*; its records are still written whole.
        """
        low, high = sorted((max(0, minimum), max(0, maximum)))
        if high <= low:
            return None
        if record_size > 0 and not low <= record_size <= high and caveats is not None:
            caveats.append(
                f"FD RECORD FROM {low} TO {high} does not include the "
                f"{record_size}-byte record layout; every record is written "
                f"at the layout's full {record_size} bytes"
            )
        return cls(low, high, None, per_record=False)

    @classmethod
    def build(
        cls,
        minimum: int,
        maximum: int,
        depending_on: str | None,
        record_size: int,
        *,
        caveats: list[str] | None = None,
        source: str = "RECORD VARYING",
    ) -> VaryingLength | None:
        """A range clamped into what the layout can actually produce.

        Whenever the range is changed to fit -- a bound past the bytes the
        record layout describes is clamped to them, or nothing of the range
        is left and it is ignored (the record stays fixed-length) -- a
        sentence saying so is appended to *caveats*, so a caller that asked
        for ``FROM 40 TO 50`` on a 28-byte record is told it got neither.
        *source* names the range in that sentence.
        """
        stated = f"{source} FROM {minimum} TO {maximum}"
        low, high = sorted((max(0, minimum), max(0, maximum)))
        if record_size > 0:
            clamped_low, clamped_high = min(low, record_size), min(high, record_size)
            if (clamped_low, clamped_high) != (low, high) and caveats is not None:
                if clamped_high > clamped_low:
                    caveats.append(
                        f"{stated} exceeds the {record_size} bytes the record "
                        f"layout describes; clamped to FROM {clamped_low} TO "
                        f"{clamped_high}"
                    )
            low, high = clamped_low, clamped_high
        if high > low:
            return cls(low, high, depending_on)
        if caveats is not None:
            caveats.append(
                f"{stated} leaves no length range within the "
                f"{record_size}-byte record layout; ignored, every record is "
                f"written at the layout's full {record_size} bytes"
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the range (used by the CLI's ``--describe`` output)."""
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "depending_on": self.depending_on,
            "per_record": self.per_record,
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
        blank_when_zero: Whether the item carries ``BLANK WHEN ZERO``: a
            numeric DISPLAY / numeric-edited item holding zero is stored as
            all spaces, which the encoder writes and the decoder reads as 0.
        justified: Whether the item carries ``JUSTIFIED RIGHT``: a value
            shorter than the field is right-aligned with leading spaces, and
            one longer loses its *leftmost* characters -- the reverse of an
            ordinary alphanumeric MOVE.
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
    blank_when_zero: bool = False
    justified: bool = False
    occurs_depending_on: str | None = None
    odo_controls: tuple[OdoControl, ...] = ()
    odo_counter_bounds: tuple[int, int] | None = None
    # The canonical P-scaling facts, read directly off the item's own
    # `PictureClause` at construction time (see `_flatten_into`) rather than
    # re-derived from the raw picture string: `total_digits` is `None` for a
    # picture with no PICTURE clause at all standing in for "not this item's
    # concern", `scaling_leading` is `None` when the picture is not P-scaled.
    # `scaling_positions`/`stored_digits` below are computed from these, so
    # there is exactly one place a P run is ever counted --
    # `models.data_items.PictureClause._parse_scaled_pattern` -- matching
    # what `generators/data/layout_offsets.py` (the `data-items` CLI) already
    # does with the same `picture.total_digits`.
    total_digits: int | None = None
    scaling_leading: bool | None = None
    #: ``SPECIAL-NAMES. DECIMAL-POINT IS COMMA``: in :attr:`picture` ``,`` is
    #: the decimal point and ``.`` an insertion character, so an edited
    #: field displays ``1.234,56``. Read off the item's own ``PictureClause``.
    decimal_point_is_comma: bool = False
    #: The exact bytes each hex literal (``VALUE X'C1C2'``, a level-88 ``X'FF'``)
    #: declared for this field names, keyed by the text cell that stands for
    #: it (the bytes read as Latin-1, cut to the field's width).  A hex
    #: literal is bytes, not characters.  The encoder does not look a cell up
    #: here (text alone cannot tell ``X'4142'`` from ``'AB'``): it writes the
    #: bytes a :class:`LiteralCell` carries.  The decoder reads it the other
    #: way, so a record holding exactly these bytes decodes back to the cell
    #: it was generated from (:func:`.encoding.hex_literal_cell_for`).
    literal_bytes: dict[str, bytes] = field(default_factory=dict)
    #: Fixed character-length UTF-8 (``PIC U(n)``): the n characters a value
    #: holds, while :attr:`size` counts the 4 x n bytes reserved for them.
    #: ``None`` for every other field (``PIC U BYTE-LENGTH n`` included).
    utf8_characters: int | None = None
    #: ``SPECIAL-NAMES. CURRENCY SIGN`` symbols :attr:`picture` uses, each
    #: mapped to its currency string (``{"#": "#"}``, ``{"#": "EUR"}``), or
    #: to ``None`` when the program's declaration of it is not known.  Read
    #: off the item's own ``PictureClause``; empty for a ``$``-only picture.
    currency_signs: dict[str, str | None] = field(default_factory=dict)

    @property
    def scaling_positions(self) -> int:
        """Signed count of ``P`` scaling positions in the PICTURE.

        Positive for trailing ``P``s (``9(3)PPP``: the value is a multiple of
        ``10**3``), negative for leading ones (``SVPP9(3)``: the first two
        decimal places are always zero), zero for every other picture.  A
        ``P`` holds no byte, so :attr:`stored_digits` excludes them while
        :attr:`integer_digits`/:attr:`decimal_digits` -- which describe the
        *value* -- include them.
        """
        if self.scaling_leading is None or self.total_digits is None:
            return 0
        count = max(0, self.integer_digits + self.decimal_digits - self.total_digits)
        return -count if self.scaling_leading else count

    @property
    def stored_digits(self) -> int:
        """Digit positions the field actually stores: every ``9``, no ``P``."""
        if self.total_digits is not None:
            return max(0, self.total_digits)
        return max(0, self.integer_digits + self.decimal_digits)

    @property
    def character_positions(self) -> int:
        """Characters a text value of this field holds.

        :attr:`size` counts bytes for a national (``PIC N``) or DBCS
        (``PIC G`` / ``USAGE DISPLAY-1``) picture -- two per character -- so
        a ``PIC N(2)`` value is two characters long, not four; and for a
        fixed character-length UTF-8 picture -- four per character -- so a
        ``PIC U(4)`` value is four characters long, not sixteen.  Every other
        field holds :attr:`size` characters.
        """
        double_byte = self.category is FieldCategory.NATIONAL or (
            self.usage == "DISPLAY-1"
            and self.category
            not in (
                FieldCategory.NUMERIC,
                FieldCategory.NUMERIC_EDITED,
                FieldCategory.FLOAT,
            )
        )
        if double_byte and self.size > 1:
            return self.size // 2
        if self.utf8_characters is not None:
            # ``PIC U(n)``: n characters in 4 x n bytes.
            return self.utf8_characters
        return self.size

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
            total_digits=self.stored_digits,
            sign_clause=self.sign_clause,
            is_signed=self.is_signed,
            national_picture=self.category is FieldCategory.NATIONAL,
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
#: A ``VALUE ALL`` entry as the parser stores it, for a level-88 value and a
#: VALUE clause alike: ``ALL "X"`` (the literal as COBOL source) or
#: ``ALL SPACES`` (a figurative constant).
_ALL_OPERAND_RE = re.compile(r"^ALL\s+(\S.*)$", re.IGNORECASE | re.DOTALL)


def all_literal_operand(value: str) -> str | None:
    """The operand of a ``VALUE ALL`` entry, or ``None`` for any other value.

    ``ALL "X"`` gives ``"X"`` (still quoted) and ``ALL SPACES`` gives
    ``SPACES``. A bare ``ALL`` (nothing repeatable after it) is not one.
    """
    match = _ALL_OPERAND_RE.match(value.strip())
    return match.group(1).strip() if match else None


def fill_all_literal(value: str, width: int) -> str | None:
    """``ALL "AB"`` as the field of *width* characters it fills: ``ABABA``.

    ``None`` when *value* is not ``ALL`` followed by a quoted literal (a
    figurative operand is the figurative constant itself, not text), when
    the literal is empty, or when *width* is not positive.
    """
    operand = all_literal_operand(value)
    if operand is None or width <= 0 or operand[-1:] not in ("'", '"'):
        return None
    unit = _strip_literal_quotes(operand)
    if not unit:
        return None
    return (unit * (width // len(unit) + 1))[:width]


def _child_items(item: CobolDataItem) -> list[CobolDataItem]:
    return [c for c in item.children if isinstance(c, CobolDataItem)]


def owns_condition_name(item: CobolDataItem) -> bool:
    """Whether *item* has a level-88 condition name of its own."""
    return any(isinstance(child, ConditionNameItem) for child in item.children)


def layout_segment(item: CobolDataItem, parent: CobolDataItem | None) -> str:
    """The path segment *item* is laid out under, beneath *parent*.

    That is :attr:`CobolDataItem.layout_name`, except for a FILLER that owns
    a level-88 condition name (``05 FILLER PIC X. 88 FLAG-ON VALUE 'Y'.``,
    or the same with FILLER omitted). The program tests that FILLER through
    its 88, so a scenario pins a value on it, and a pin is keyed by the
    field's qualified name -- which plain ``FILLER`` shares with every other
    FILLER of the group. Such a FILLER is ``FILLER#<n>``, *n* its 1-based
    position among the FILLER items of *parent*: unique in the group, and
    the same in every walk of the record. Plain FILLERs keep ``FILLER``.
    """
    if parent is None or not item.is_filler or not owns_condition_name(item):
        return item.layout_name
    fillers = [c for c in _child_items(parent) if c.is_filler]
    position = next(n for n, c in enumerate(fillers, 1) if c is item)
    return f"FILLER#{position}"


def expand_condition_values(
    raw_values: list[str], width: int | None = None
) -> list[str]:
    """Expand one condition name's raw VALUE literals, THRU ranges included.

    The parser records ``VALUE 2 THRU 4`` as ``["2", "THROUGH:4"]`` -- the
    range end is marked rather than expanded. Numeric ranges are expanded
    here (bounded, so ``VALUE 1 THRU 999999`` cannot blow up memory); a
    non-numeric range contributes only its endpoints.

    ``VALUE ALL 'X'`` (recorded as ``ALL "X"``) denotes the literal repeated
    to the field's *width*: with a *width* it expands to that one value
    (``XXX``), and ``ALL SPACES`` to the figurative word ``SPACES``; without
    one it is kept as written (an entry whose width is unknown is dropped
    rather than guessed when a *width* of 0 or less is given).
    """
    values: list[str] = []
    previous: str | None = None
    for raw in raw_values:
        match = _THROUGH_RE.match(raw)
        if match is None:
            operand = all_literal_operand(raw)
            if operand is not None:
                previous = None
                if width is None:
                    values.append(raw.strip())
                elif operand.upper() in _FIGURATIVE_WORDS:
                    values.append(operand.upper())
                else:
                    filled = fill_all_literal(raw, width)
                    if filled is not None:
                        values.append(filled)
                continue
            cleaned = hex_literal_cell(raw, width) or _strip_literal_quotes(raw)
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
    return _dedup_values(values)


def condition_ranges(raw_values: list[str]) -> list[tuple[str, str]]:
    """Every ``THRU`` range of one condition name, as ``(from, to)`` written.

    The parser records ``VALUE 2 THRU 4`` as ``["2", "THROUGH:4"]``; this
    pairs each range end with the literal before it, quotes stripped and
    nothing expanded. A typed literal stays as written (``X'00'``, not a raw
    NUL byte). :func:`expand_condition_values` lists a range only in part (an
    integer range up to the expansion cap, any other range just its
    endpoints), so these pairs are the only full statement of what the
    condition admits.
    """
    ranges: list[tuple[str, str]] = []
    previous: str | None = None
    for raw in raw_values:
        match = _THROUGH_RE.match(raw)
        if match is None:
            previous = (
                None if all_literal_operand(raw) is not None else _range_endpoint(raw)
            )
            continue
        end = _range_endpoint(match.group(1))
        if previous is not None:
            ranges.append((previous, end))
        previous = end
    return ranges


def _range_endpoint(value: str) -> str:
    """A ``THRU`` endpoint for display: a typed literal (``X'3F'``) as
    written, any other literal with its quotes stripped."""
    if typed_literal_content(value) is not None:
        return value.strip()
    return _strip_literal_quotes(value)


def condition_values_exhaustive(raw_values: list[str], decimal_digits: int) -> bool:
    """Whether :func:`expand_condition_values` lists *every* value the
    condition name admits, for a field with *decimal_digits* decimals.

    A positive test (``IF COND``) only ever needs one member, so a partial
    list is still sound for it. A *negated* one (``IF NOT COND``, or the
    ``WHEN OTHER`` after ``WHEN COND``) is modelled as ``not_in_set`` over the
    listed values, which is only sound when nothing else satisfies ``COND``.
    That fails for a ``THRU`` range the expansion cannot enumerate: a
    non-integer range (only its endpoints are listed), one wider than the
    expansion cap, or any range over a field with decimal places (``VALUE 1
    THRU 2`` on ``PIC 9V9`` also admits 1.5). A figurative constant
    (``VALUE SPACES``) is not a literal value at all.
    """
    previous: str | None = None
    for raw in raw_values:
        match = _THROUGH_RE.match(raw)
        if match is None:
            operand = all_literal_operand(raw)
            if operand is not None:
                # ``ALL "X"`` is one exact value (the literal filled to the
                # field); ``ALL SPACES`` is a figurative constant.
                if operand.upper() in _FIGURATIVE_WORDS:
                    return False
                previous = None
                continue
            cleaned = _strip_literal_quotes(raw)
            if raw.strip().upper() in _FIGURATIVE_WORDS or raw.strip().upper() == "ALL":
                return False
            previous = cleaned
            continue
        end = _strip_literal_quotes(match.group(1))
        if (
            decimal_digits > 0
            or previous is None
            or not _INTEGER_LITERAL_RE.match(previous)
            or not _INTEGER_LITERAL_RE.match(end)
            or abs(int(end) - int(previous)) > _MAX_RANGE_EXPANSION
        ):
            return False
        previous = end
    return True


#: Figurative constants as they can appear in a level-88 VALUE clause.
_FIGURATIVE_WORDS = frozenset(
    {
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "LOW-VALUE",
        "LOW-VALUES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)


#: Field categories whose DISPLAY bytes are one character per byte, so a
#: slice of a group VALUE's text is exactly the field's own value.
_TEXT_SLICE_CATEGORIES = frozenset(
    {
        FieldCategory.ALPHANUMERIC,
        FieldCategory.ALPHABETIC,
        FieldCategory.ALPHANUMERIC_EDITED,
        FieldCategory.NUMERIC,
        FieldCategory.NUMERIC_EDITED,
    }
)
_GROUP_VALUE_ALL_RE = re.compile(r"ALL\s+(.+)$", re.IGNORECASE | re.DOTALL)


def _apply_group_value(clause: str, specs: list[FieldSpec]) -> None:
    """Give each field of a group the part of the group's VALUE it holds.

    A group VALUE is an alphanumeric literal laid over the group's bytes
    (``05 HDR VALUE 'HDR0001'`` puts ``HDR`` in a leading ``X(3)`` and
    ``0001`` in the ``9(4)`` after it), padded with spaces when shorter; a
    figurative constant, or ``ALL`` a literal, fills every byte.  Each field
    gets the matching slice as its own VALUE clause, so ``ValueFactory``
    honours it -- or not, under ``respect_values=False`` -- exactly as it
    does an elementary VALUE.  A field that already declares one keeps it.

    Only DISPLAY fields of one byte per character are given a text slice:
    the bytes a literal leaves in a COMP / COMP-3 / national field are not
    a value of its own type, so those keep being generated.  A figurative
    is the exception -- it names a value every type has.
    A numeric DISPLAY field takes its slice as digits at its own scale,
    and only when the slice is all digits.
    """
    raw = clause.strip()
    all_match = _GROUP_VALUE_ALL_RE.match(raw)
    unit = all_match.group(1).strip() if all_match else raw
    if unit.upper() in _FIGURATIVE_WORDS:
        for spec in specs:
            if spec.value_clause is None:
                spec.value_clause = unit
        return
    data = hex_literal_bytes(unit)
    text = data.decode("latin-1") if data is not None else _strip_literal_quotes(unit)
    if not text:
        return
    total = sum(spec.storage_size for spec in specs)
    if all_match:
        text = (text * (total // len(text) + 1))[:total]
    offset = 0
    for spec in specs:
        width = spec.storage_size
        piece = text[offset : offset + width]
        offset += width
        if (
            spec.value_clause is not None
            or spec.usage != "DISPLAY"
            or spec.category not in _TEXT_SLICE_CATEGORIES
            or width != spec.character_positions
        ):
            continue
        if spec.category is FieldCategory.NUMERIC:
            # A numeric DISPLAY field's slice is its digits, not its value:
            # ``'0001'`` over ``PIC 9(2)V99`` is 00.01, and taking it as the
            # literal 1 wrote ``0100``.  A slice that is not all digits (a
            # hex literal's bytes, text, the spaces past the literal's end)
            # or a P-scaled picture is no value the encoder can write back as
            # the same bytes, so that field keeps being generated.
            if (
                data is not None
                or len(piece) != width
                or not piece.isdigit()
                or spec.scaling_positions != 0
            ):
                continue
            scale = spec.decimal_digits
            spec.value_clause = (
                f"{piece[:-scale] or '0'}.{piece[-scale:]}" if scale else piece
            )
            continue
        if data is not None and piece:
            # A hex literal is bytes: its slice stays a hex literal, so the
            # encoder writes those bytes rather than their Latin-1 text.
            spec.value_clause = "X'" + piece.encode("latin-1").hex().upper() + "'"
            spec.literal_bytes.setdefault(piece, piece.encode("latin-1"))
        else:
            # Past the literal's end the group holds spaces (the encoder
            # pads a short value with them).
            spec.value_clause = "'" + (piece or " ").replace("'", "''") + "'"


def _currency_signs(picture: PictureClause | None) -> dict[str, str | None]:
    """*picture*'s declared currency symbols with their currency strings
    (see :attr:`FieldSpec.currency_signs`)."""
    if picture is None:
        return {}
    signs = getattr(picture, "currency_signs", {}) or {}
    return {symbol: signs.get(symbol) for symbol in picture.currency_symbols}


def _condition_values(item: CobolDataItem) -> list[str]:
    """Collect level-88 VALUEs under *item*, merged across all its
    level-88 children -- FieldSpec.condition_values needs "any value that
    could apply to this field", not one condition name's values in
    isolation. See ``expand_condition_values`` for the per-name expansion
    this delegates to.
    """
    values: list[str] = []
    picture = item.picture_clause
    width = picture.size if picture is not None and picture.size else 0
    for child in item.children:
        if not isinstance(child, ConditionNameItem):
            continue
        values.extend(expand_condition_values(child.values, width))
    # Preserve first-seen order while removing duplicates.
    return _dedup_values(values)


class LiteralCell(str):
    """A generated cell that stands for a hex literal (``VALUE X'C1C2'``, a
    level-88 ``X'FF'``), carrying the literal's own :attr:`data`.

    The text is those bytes read as Latin-1, so the cell still prints and
    compares like any other.  The bytes travel with the cell rather than
    being looked up by its text afterwards: an ordinary value with the same
    text (``VALUE SPACE`` next to ``88 VALUE X'20'``, ``'AB'`` next to
    ``X'4142'``, a random ``A`` next to ``X'41'``) is a different literal
    and must still be written in the record charset.
    :func:`.encoding.encode_field` writes :attr:`data` verbatim.
    """

    data: bytes

    def __new__(cls, data: bytes) -> LiteralCell:
        cell = super().__new__(cls, data.decode("latin-1"))
        cell.data = data
        return cell

    def __reduce__(self) -> tuple[type[LiteralCell], tuple[bytes]]:
        return (LiteralCell, (self.data,))


def hex_literal_cell(value: str, width: int | None = None) -> LiteralCell | None:
    """The cell a hex literal *value* is written as, its bytes cut to
    *width* when one is known; ``None`` for any other literal."""
    data = hex_literal_bytes(value)
    if not data:
        return None
    if width is not None and width > 0:
        data = data[:width]
    return LiteralCell(data)


def _dedup_values(values: list[str]) -> list[str]:
    """*values* without repeats, first-seen order kept.  A hex literal's cell
    is not a repeat of an ordinary value with the same text (``X'4142'``
    and ``'AB'``): they name different bytes in an EBCDIC record."""
    seen: dict[tuple[str, bytes | None], str] = {}
    for value in values:
        if value == "":
            continue
        key = (str(value), value.data if isinstance(value, LiteralCell) else None)
        seen.setdefault(key, value)
    return list(seen.values())


def hex_literal_bytes(value: str) -> bytes | None:
    """The bytes an ``X'..'`` literal names, or ``None`` for any other text
    (another typed literal, a quoted one, hex that does not decode)."""
    stripped = value.strip()
    if len(stripped) < 3 or stripped[0] not in "xX" or stripped[1] not in "\"'":
        return None
    try:
        return bytes.fromhex(unquote_literal(stripped[1:]))
    except ValueError:
        return None


def value_clause_hex_bytes(clause: str, width: int) -> bytes | None:
    """The bytes a VALUE *clause* writes when it is a hex literal: ``X'..'``
    as is, ``ALL X'..'`` repeated across the *width* of the field.  ``None``
    for any other clause."""
    stripped = clause.strip()
    if stripped[:3].upper() == "ALL" and stripped[3:4].isspace():
        unit = hex_literal_bytes(stripped[3:])
        if not unit:
            return None
        size = width if width > 0 else len(unit)
        return (unit * (size // len(unit) + 1))[:size]
    return hex_literal_bytes(stripped)


def _literal_bytes(item: CobolDataItem, width: int) -> dict[str, bytes]:
    """Every hex literal *item* declares -- its VALUE clause and its level-88
    values -- as ``{text cell: bytes}``; see :attr:`FieldSpec.literal_bytes`.

    The key is the literal's Latin-1 text cut to *width*, the same cut
    ``ValueFactory`` applies when it writes the literal into a cell, so the
    decoder gives back the cell that was generated.
    """
    found: dict[str, bytes] = {}
    if item.value_clause:
        # ``ALL X'FF'`` fills the field with the literal's bytes.
        data = value_clause_hex_bytes(item.value_clause, width)
        if data:
            data = data[:width] if width > 0 else data
            found.setdefault(data.decode("latin-1"), data)
    raws: list[str] = []
    for child in item.children:
        if isinstance(child, ConditionNameItem):
            raws.extend(str(value) for value in child.values)
    for raw in raws:
        data = hex_literal_bytes(raw)
        if not data:
            continue
        if width > 0:
            data = data[:width]
        found.setdefault(data.decode("latin-1"), data)
    return found


def _strip_literal_quotes(value: str) -> str:
    """A COBOL literal's content: delimiters removed and each doubled
    delimiter collapsed (``"A""B"`` is ``A"B``), see ``unquote_literal``.
    A typed literal is decoded (``X"4142"`` is ``AB``), see
    ``typed_literal_content``."""
    typed = typed_literal_content(value)
    return typed if typed is not None else unquote_literal(value)


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
    *,
    ignore_root_redefines: bool = False,
) -> list[FieldSpec]:
    """Flatten *record* into the ordered list of columns to generate.

    Walks the record depth-first, descending through group items and emitting
    one :class:`FieldSpec` per elementary item (per occurrence, for tables).

    *ignore_root_redefines* asks for the fields of a record that *itself*
    carries ``REDEFINES``.  Ordinarily such a record flattens to nothing --
    a redefinition aliases bytes another item already covers, so generating
    both would put two values in one place.  A caller that has deliberately
    chosen the redefinition as the layout to work through (the record
    *decoder*, which reads one set of bytes through one overlay at a time)
    wants those fields anyway.  Only the root's own clause is exempted:
    ``REDEFINES`` nested inside the subtree still excludes its fields, so
    the result stays a contiguous byte map whose widths sum to the
    subtree's footprint.
    """
    opts = options or DataGeneratorOptions()
    specs: list[FieldSpec] = []
    _flatten_into(
        record,
        (),
        (),
        None,
        (),
        opts,
        specs,
        redefines_label=record.redefines if ignore_root_redefines else None,
        ignore_own_redefines=ignore_root_redefines,
    )
    _link_odo_counters(specs)
    _assign_columns(specs, opts)
    return specs


@dataclass(frozen=True)
class HiddenCounter:
    """An ``OCCURS ... DEPENDING ON`` counter an overlay view covers up.

    When a ``REDEFINES`` overlay is swapped in for the item holding a
    table's counter, the counter is no longer one of the view's fields --
    but the table still takes its length from those bytes.  The decoder
    reads the counter from them anyway, so every field after the table
    stays where the record's own counter puts it.

    Attributes:
        index: Position in the view's specs where the overlay starts; the
            counter's bytes are read when the decoder reaches it.
        offset: Bytes from the overlay's start to the counter's first byte.
        spec: The counter itself, as the base layout declares it.
    """

    index: int
    offset: int
    spec: FieldSpec


@dataclass
class _OverlayWalk:
    """What a :func:`flatten_overlay_view` walk carries down the tree."""

    substitutions: Mapping[int, CobolDataItem]
    hidden: list[HiddenCounter] = field(default_factory=list)


def flatten_overlay_view(
    record: CobolDataItem,
    substitutions: Mapping[int, CobolDataItem],
    options: DataGeneratorOptions | None = None,
) -> tuple[list[FieldSpec], list[HiddenCounter]]:
    """Flatten *record* read through chosen ``REDEFINES`` overlays.

    *substitutions* maps ``id()`` of a redefined item to the item
    redefining it.  The walk emits the overlay's fields wherever the
    redefined item's would have gone -- once per occurrence when it sits
    inside a table.  An overlay shorter than what it redefines is padded
    with a FILLER so every field after it keeps its offset.  This is how
    :mod:`.views` builds an overlay view: the whole record with the overlay
    swapped in.

    Also returns the ``DEPENDING ON`` counters the overlays cover up (see
    :class:`HiddenCounter`), which the decoder still has to read.  Columns
    are left unassigned (each spec's bare name): a view names them to match
    its base view, which this walk cannot see.
    """
    opts = options or DataGeneratorOptions()
    specs: list[FieldSpec] = []
    walk = _OverlayWalk(substitutions)
    _flatten_into(
        record,
        (),
        (),
        None,
        (),
        opts,
        specs,
        redefines_label=record.redefines,
        ignore_own_redefines=True,
        overlays=walk,
    )
    # Link over the hidden counters too: they are counters of tables in
    # these very specs, and only linking finds out which ones are.
    _link_odo_counters([*specs, *(hidden.spec for hidden in walk.hidden)])
    return specs, [h for h in walk.hidden if h.spec.odo_counter_bounds is not None]


def _flatten_into(
    item: CobolDataItem,
    path: tuple[str, ...],
    subscripts: tuple[int, ...],
    redefines: str | None,
    odo_controls: tuple[OdoControl, ...],
    opts: DataGeneratorOptions,
    out: list[FieldSpec],
    *,
    redefines_label: str | None = None,
    ignore_own_redefines: bool = False,
    overlays: _OverlayWalk | None = None,
    segment: str | None = None,
) -> None:
    """Recursive worker for :func:`flatten_record`.

    *segment* is this item's path segment (see :func:`layout_segment`);
    ``None`` means its :attr:`~CobolDataItem.layout_name`.

    *ignore_own_redefines* drops *this* item's own ``REDEFINES`` from the
    exclusion test -- passed only for the root, under
    :func:`flatten_record`'s ``ignore_root_redefines``.  It is not inherited:
    the recursive calls below leave it at its default, so a redefinition
    nested inside the subtree is excluded as usual and the walk still
    describes a contiguous run of bytes.

    *redefines_label* is the clause that exemption skipped.  It reaches every
    spec's :attr:`FieldSpec.redefines`, so a field still says which
    redefinition it belongs to, without gating the walk.
    """
    # A REDEFINES anywhere up the chain taints every field beneath it.
    inherited_redefines = (
        redefines if ignore_own_redefines else redefines or item.redefines
    )
    if inherited_redefines and not opts.include_redefines:
        return
    if (
        item.is_filler
        and not opts.include_filler
        and not (opts.include_condition_filler and owns_condition_name(item))
    ):
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
                qualifiers=tuple(
                    q.upper() for q in getattr(occurs, "depending_on_qualifiers", ())
                ),
            ),
        )

    item_path = (*path, segment or item.layout_name)
    for index in indexes:
        occ = (*subscripts, index) if index is not None else subscripts
        children = _child_items(item)
        if children:
            start = len(out)
            for child in children:
                overlay = overlays.substitutions.get(id(child)) if overlays else None
                if overlay is not None and overlays is not None:
                    _flatten_overlay(
                        child,
                        overlay,
                        item_path,
                        occ,
                        inherited_redefines,
                        inherited_controls,
                        opts,
                        out,
                        overlays,
                    )
                    continue
                _flatten_into(
                    child,
                    item_path,
                    occ,
                    inherited_redefines,
                    inherited_controls,
                    opts,
                    out,
                    redefines_label=redefines_label,
                    overlays=overlays,
                    segment=layout_segment(child, item),
                )
            if item.value_clause:
                # A group VALUE initialises the group's bytes, not one field:
                # carry it down to the fields that make them up (#552).
                own = inherited_redefines or redefines_label
                _apply_group_value(
                    item.value_clause,
                    [spec for spec in out[start:] if spec.redefines == own],
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
                name=item.layout_name,
                path=item_path,
                column=item.layout_name,
                level=item.level,
                picture=picture.pattern if picture else None,
                usage=(item.usage or "DISPLAY").upper(),
                category=category,
                size=size,
                integer_digits=integer_digits,
                decimal_digits=decimal_digits,
                total_digits=picture.total_digits if picture else None,
                scaling_leading=picture.scaling_leading if picture else None,
                decimal_point_is_comma=bool(
                    picture is not None
                    and getattr(picture, "decimal_point_is_comma", False)
                ),
                is_signed=_is_signed(picture),
                value_clause=item.value_clause,
                condition_values=_condition_values(item),
                literal_bytes=_literal_bytes(item, size),
                subscripts=occ,
                redefines=inherited_redefines or redefines_label,
                is_filler=item.is_filler,
                sign_clause=item.sign_clause,
                synchronized=item.synchronized,
                blank_when_zero=item.blank_when_zero,
                justified=bool(getattr(item, "justified", False)),
                occurs_depending_on=(
                    inherited_controls[0].depending_on if inherited_controls else None
                ),
                odo_controls=inherited_controls,
                utf8_characters=(
                    picture.utf8_characters
                    if picture is not None and item.byte_length is None
                    else None
                ),
                currency_signs=_currency_signs(picture),
            )
        )


def _flatten_overlay(
    target: CobolDataItem,
    overlay: CobolDataItem,
    path: tuple[str, ...],
    subscripts: tuple[int, ...],
    redefines: str | None,
    odo_controls: tuple[OdoControl, ...],
    opts: DataGeneratorOptions,
    out: list[FieldSpec],
    overlays: _OverlayWalk,
) -> None:
    """Emit *overlay*'s fields in *target*'s place, padded to its width.

    The pad keeps the record's own geometry: a redefinition aliases bytes,
    it does not remove any, so the fields after it stay where the base
    layout puts them.  A *wider* overlay (non-conforming below level 01) is
    emitted whole and moves what follows, which is where a compiler that
    accepts it puts them too -- :mod:`.views` says so in its caveats.

    *target*'s own fields are flattened too, to measure it and to keep any
    ``DEPENDING ON`` counter among them as a :class:`HiddenCounter`.
    """
    start = len(out)
    _flatten_into(
        overlay,
        path,
        subscripts,
        redefines,
        odo_controls,
        opts,
        out,
        redefines_label=overlay.redefines,
        ignore_own_redefines=True,
        overlays=overlays,
    )
    own = sum(spec.storage_size for spec in out[start:])
    probe: list[FieldSpec] = []
    _flatten_into(target, path, subscripts, redefines, odo_controls, opts, probe)
    at = 0
    for spec in probe:
        overlays.hidden.append(HiddenCounter(index=start, offset=at, spec=spec))
        at += spec.storage_size
    gap = at - own
    if gap <= 0:
        return
    out.append(
        FieldSpec(
            name="FILLER",
            path=(*path, overlay.name, "FILLER"),
            column="FILLER",
            level=overlay.level,
            picture=f"X({gap})",
            usage="DISPLAY",
            category=FieldCategory.ALPHANUMERIC,
            size=gap,
            integer_digits=0,
            decimal_digits=0,
            is_signed=False,
            subscripts=subscripts,
            redefines=overlay.redefines,
            is_filler=True,
            occurs_depending_on=odo_controls[0].depending_on if odo_controls else None,
            odo_controls=odo_controls,
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
    occurrence in both.  When the two do not overlap -- one table holding
    1-3, another 5-8 -- the tightest *maximum* wins, not the largest
    minimum: a count below a table's minimum still addresses occurrences
    that exist, while one above its maximum names bytes the record does
    not have.
    """
    bounds: dict[tuple[str, tuple[str, ...]], tuple[int, int]] = {}
    for spec in specs:
        for control in spec.odo_controls:
            key = (control.depending_on.upper(), control.qualifiers)
            existing = bounds.get(key)
            if existing is None:
                bounds[key] = (control.min_times, control.max_times)
                continue
            low = max(existing[0], control.min_times)
            high = min(existing[1], control.max_times)
            if low > high:
                # Disjoint ranges (one table holds 1-3, another 5-8). Falling
                # back to the larger *minimum* would name occurrence 5 of a
                # 3-occurrence table -- the over-counting direction, which is
                # the one that describes bytes the record does not have.
                # Collapse to the tightest maximum instead: under-counting
                # still addresses occurrences that exist.
                low = high
            bounds[key] = (low, high)

    if not bounds:
        return
    for spec in specs:
        # ``DEPENDING ON CNT OF HDR`` names HDR's CNT only: a same-named item
        # elsewhere in the record (``TRL.CNT``) is ordinary data, and
        # stamping it too made the encoder and decoder size the table from
        # whichever CNT came last.
        name = spec.name.upper()
        ancestors = {part.upper() for part in spec.path[:-1]}
        found: tuple[int, int] | None = None
        for (counter, qualifiers), (low, high) in bounds.items():
            if counter != name or not set(qualifiers) <= ancestors:
                continue
            if found is not None:
                low, high = max(found[0], low), min(found[1], high)
                if low > high:
                    low = high
            found = (low, high)
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
