"""Field flattening: decompose record structures into generatable field specs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ...models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    PictureClause,
)
from .options import DataGeneratorOptions


class FieldCategory(StrEnum):
    """Data category of an elementary field, driving value generation."""

    ALPHANUMERIC = "alphanumeric"
    ALPHABETIC = "alphabetic"
    NATIONAL = "national"
    NUMERIC = "numeric"
    NUMERIC_EDITED = "numeric-edited"
    ALPHANUMERIC_EDITED = "alphanumeric-edited"
    FLOAT = "float"


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
            "integer_digits": self.integer_digits,
            "decimal_digits": self.decimal_digits,
            "is_signed": self.is_signed,
            "value_clause": self.value_clause,
            "condition_values": list(self.condition_values),
            "subscripts": list(self.subscripts),
            "redefines": self.redefines,
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


def _condition_values(item: CobolDataItem) -> list[str]:
    """Collect level-88 VALUEs under *item*, expanding ``THRU`` ranges.

    The parser records ``VALUE 2 THRU 4`` as ``["2", "THROUGH:4"]`` -- the
    range end is marked rather than expanded.  Numeric ranges are expanded
    here (bounded, so ``VALUE 1 THRU 999999`` cannot blow up memory); a
    non-numeric range contributes only its endpoints.
    """
    values: list[str] = []
    for child in item.children:
        if not isinstance(child, ConditionNameItem):
            continue
        previous: str | None = None
        for raw in child.values:
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
    _flatten_into(record, (), (), None, opts, specs)
    _assign_columns(specs, opts)
    return specs


def _flatten_into(
    item: CobolDataItem,
    path: tuple[str, ...],
    subscripts: tuple[int, ...],
    redefines: str | None,
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

    item_path = (*path, item.name)
    for index in _occurrence_indexes(item, opts):
        occ = (*subscripts, index) if index is not None else subscripts
        children = _child_items(item)
        if children:
            for child in children:
                _flatten_into(child, item_path, occ, inherited_redefines, opts, out)
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
