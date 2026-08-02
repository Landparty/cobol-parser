"""Synthetic test-data generation from a COBOL copybook layout.

Turns a copybook (or the record layouts of a full program) into a CSV of
generated rows: one column per elementary field, one row per generated
record.  Values honour each field's PICTURE category, size, digit counts,
sign, ``USAGE``, ``VALUE`` clause, and any level-88 condition values, so a
generated row is always assignable to the record it was generated from.

Typical use::

    from cobolparser.generators import (
        CopybookDataGenerator,
        DataGeneratorOptions,
    )

    generator = CopybookDataGenerator(DataGeneratorOptions(rows=100, seed=7))
    dataset = generator.generate_from_file("CUSTOMER.cpy")
    print(dataset.to_csv())

Generation is deterministic for a given ``seed``: the same seed and the same
copybook always produce byte-identical CSV.  When no seed is supplied one is
drawn at random and recorded on :attr:`GeneratedDataset.seed`, so an
interesting run can always be reproduced after the fact.

Design notes
------------

* **REDEFINES are excluded by default.**  A redefining item aliases the same
  bytes as the item it redefines, so emitting both would put two
  contradictory values in one row.  ``include_redefines`` opts in anyway
  (useful when the redefinition is the layout you actually care about).
* **OCCURS are expanded** into one column per occurrence, named with the
  COBOL subscript convention (``ITEM-CODE(1)``, ``ITEM-CODE(2)``, ...).
  ``OCCURS ... DEPENDING ON`` uses the maximum bound.
* **Edited pictures** (``-ZZ,ZZ9.99``) contribute their *logical* numeric
  value, not the edited display form.  A CSV is consumed by tooling that
  wants the value; the edit mask is a presentation concern of the COBOL
  program.
* **FILLER is skipped** by default -- it names no field a consumer can use.
"""

from __future__ import annotations

import csv
import io
import os
import random
import re
import string
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    PictureClause,
)
from ..models.program import CobolProgram
from ..parser import parse_cobol
from ..plugins.core import ErrorRecoveryMode

__all__ = [
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "DataGeneratorOptions",
    "FieldCategory",
    "FieldSpec",
    "GeneratedDataset",
    "flatten_record",
    "parse_copybook_records",
]

from .data.errors import CopybookLayoutError
from .data.options import DataGeneratorOptions


class FieldCategory(StrEnum):
    """Data category of an elementary field, driving value generation."""

    ALPHANUMERIC = "alphanumeric"
    ALPHABETIC = "alphabetic"
    NATIONAL = "national"
    NUMERIC = "numeric"
    NUMERIC_EDITED = "numeric-edited"
    ALPHANUMERIC_EDITED = "alphanumeric-edited"
    FLOAT = "float"


# ---------------------------------------------------------------------------
# Copybook parsing
# ---------------------------------------------------------------------------

# A copybook is a DATA DIVISION fragment, not a compilable program, so it is
# wrapped in a minimal program skeleton before being handed to the parser.
_WRAPPER_HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. COPYBOOK-LAYOUT.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
_WRAPPER_TAIL = "       PROCEDURE DIVISION.\n           CONTINUE.\n"

_PROGRAM_RE = re.compile(r"^\s*IDENTIFICATION\s+DIVISION\s*\.", re.IGNORECASE | re.M)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\s*\.", re.IGNORECASE | re.M)
_REPEAT_COUNT_RE = re.compile(r"\(\d+\)")
_THROUGH_RE = re.compile(r"^THROUGH:(.*)$", re.IGNORECASE)
# An optionally-signed integer literal, used to decide whether a level-88
# ``THRU`` range can be expanded. Both endpoints are tested the same way: the
# sign has to be accepted on either side, not just the first.
_INTEGER_LITERAL_RE = re.compile(r"^[+-]?\d+$")
_WORD_SPLIT_RE = re.compile(r"[-_]+")
# A one- or two-digit level number inside the sequence area (columns 1-6),
# followed by a separator -- the decisive free-form signal. Six-digit sequence
# numbers cannot match, and fixed-format code cannot start before column 8.
_FREE_FORM_LEVEL_RE = re.compile(r"^ {0,5}\d{1,2}[ .]")


def _looks_like_program(source: str) -> bool:
    """True when *source* is a whole program rather than a bare fragment."""
    return bool(_PROGRAM_RE.search(source) or _PROGRAM_ID_RE.search(source))


def _looks_fixed_format(source: str) -> bool:
    """Heuristically detect fixed-format column layout in a copybook fragment.

    A fixed-format line keeps columns 1-6 for the sequence number and column 7
    for the indicator, so real code never starts before column 8.  A free-form
    copybook, by contrast, starts its level numbers in column 1.

    A **short level number in the sequence area** (``01 REC.``, ``05 FLD``) is
    decisive: one or two digits followed by a space or period cannot be a
    six-digit sequence number, and cannot be fixed-format code, which starts
    at column 8.  Only one such line is needed -- a copybook that puts its 01
    in column 1 but indents subordinate items past column 8 is common, and
    majority-scoring it as fixed would slice the ``01`` line away entirely.

    Absent that signal, lines are scored on their sequence area: a blank one
    (indented code) or an all-digit one (a real sequence number, as in the
    NIST corpus) is fixed-shaped; anything else is code starting too early to
    be fixed format.  Scoring rather than requiring agreement keeps real
    copybooks -- which mix blank lines, comments, and continuations -- from
    being decided by a single odd line.

    When the two are tied the verdict is *fixed*: mis-indenting a fixed-format
    copybook pushes real code past column 72 and truncates it, which is worse
    than leaving an already-indented free-form copybook alone.
    """
    fixed = 0
    free = 0
    for raw in source.splitlines():
        line = raw.expandtabs(8)
        if not line.strip():
            continue
        if _FREE_FORM_LEVEL_RE.match(line):
            return False
        sequence_area = line[:6].strip()
        if not sequence_area or sequence_area.isdigit():
            fixed += 1
        else:
            free += 1
    return fixed >= free


def _wrap_fragment(source: str) -> str:
    """Embed a copybook fragment in a minimal, parseable program skeleton."""
    if _looks_fixed_format(source):
        body = source
    else:
        # Free-form fragment: shift into Area B so the fixed-format wrapper and
        # the fragment agree on a single column convention.
        body = "\n".join(
            "       " + line if line.strip() else "" for line in source.splitlines()
        )
    if not body.endswith("\n"):
        body += "\n"
    return _WRAPPER_HEAD + body + _WRAPPER_TAIL


def parse_copybook_records(
    source: str,
    *,
    filename: str = "<copybook>",
) -> list[CobolDataItem]:
    """Parse *source* and return its record roots (the level-01/77 items).

    Accepts either a bare copybook fragment or a complete COBOL program; a
    fragment is wrapped in a program skeleton first.  Parsing runs in
    ``COLLECT_ALL`` recovery so an unrelated defect elsewhere in a program
    still yields the data items that did parse.

    Raises:
        CopybookLayoutError: if the source yields no usable record layout.
    """
    if not source.strip():
        raise CopybookLayoutError(f"{filename}: copybook is empty")

    text = source if _looks_like_program(source) else _wrap_fragment(source)
    result = parse_cobol(
        text,
        filename=filename,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    ast = result.ast
    if ast is None:
        detail = result.errors[0] if result.errors else "no AST produced"
        raise CopybookLayoutError(f"{filename}: could not parse copybook ({detail})")

    roots = _top_level_items(ast)
    records = [item for item in roots if item.level in (1, 77) and not item.is_filler]
    if records:
        return records

    # A copybook holding only subordinate items (level 02-49, no 01) is a
    # legitimate idiom: it is meant to be COPY'd *inside* an existing record.
    # Synthesise the record root its author assumed, so such a fragment is
    # still generatable rather than rejected.
    subordinate = [item for item in roots if 2 <= item.level <= 49]
    if subordinate:
        return [_synthesise_record(subordinate, filename)]

    raise CopybookLayoutError(
        f"{filename}: no level-01 record layout found in copybook"
    )


def _all_data_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return every data item in *ast*, outermost first, in source order."""
    items = ast.find_all_by_type("DataItem")
    return [item for item in items if isinstance(item, CobolDataItem)]


def _top_level_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return the data items that are not nested inside another data item."""
    items = _all_data_items(ast)
    nested = {id(child) for item in items for child in item.get_all_children()}
    return [item for item in items if id(item) not in nested]


def _synthesise_record(items: list[CobolDataItem], filename: str) -> CobolDataItem:
    """Wrap orphan subordinate items in a virtual level-01 record."""
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    # Reduce the stem to a legal COBOL data name: illegal characters become
    # hyphens, runs collapse, and leading/trailing hyphens are dropped, so the
    # placeholder filename "<copybook>" yields COPYBOOK-RECORD rather than
    # the malformed "-COPYBOOK--RECORD".
    name = re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]", "-", stem)).strip("-")
    root = CobolDataItem(f"{name or 'COPYBOOK'}-RECORD", 1, items[0].location)
    for item in items:
        root.add_child(item)
    return root


# ---------------------------------------------------------------------------
# Field flattening
# ---------------------------------------------------------------------------


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


_MAX_RANGE_EXPANSION = 64

# Line terminator shared by every CSV output path. Deliberately "\n" rather
# than the csv module's RFC 4180 "\r\n": both GeneratedDataset.to_csv and
# .write_csv must agree, or the same seed writes different bytes to stdout
# than to --output.
_DEFAULT_LINE_TERMINATOR = "\n"


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
    elif opts.max_occurs is not None:
        times = min(times, opts.max_occurs)
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
# Value generation
# ---------------------------------------------------------------------------

_FIGURATIVE_CONSTANTS: dict[str, str] = {
    "SPACE": "",
    "SPACES": "",
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
    "LOW-VALUE": "",
    "LOW-VALUES": "",
    "HIGH-VALUE": "",
    "HIGH-VALUES": "",
    "NULL": "",
    "NULLS": "",
    "QUOTE": '"',
    "QUOTES": '"',
}

_FIRST_NAMES = (
    "JAMES",
    "MARIA",
    "ROBERT",
    "LINDA",
    "MICHAEL",
    "PATRICIA",
    "DAVID",
    "JENNIFER",
    "WILLIAM",
    "ELIZABETH",
    "RICHARD",
    "SUSAN",
    "JOSEPH",
    "MARGARET",
    "THOMAS",
    "DOROTHY",
    "CHARLES",
    "NANCY",
    "DANIEL",
    "KAREN",
)
_LAST_NAMES = (
    "SMITH",
    "JOHNSON",
    "WILLIAMS",
    "BROWN",
    "JONES",
    "GARCIA",
    "MILLER",
    "DAVIS",
    "RODRIGUEZ",
    "MARTINEZ",
    "HERNANDEZ",
    "LOPEZ",
    "WILSON",
    "ANDERSON",
    "THOMAS",
    "TAYLOR",
    "MOORE",
    "JACKSON",
    "MARTIN",
    "LEE",
)
_CITIES = (
    "NEW YORK",
    "LOS ANGELES",
    "CHICAGO",
    "HOUSTON",
    "PHOENIX",
    "PHILADELPHIA",
    "SAN ANTONIO",
    "SAN DIEGO",
    "DALLAS",
    "AUSTIN",
    "COLUMBUS",
    "CHARLOTTE",
    "SEATTLE",
    "DENVER",
    "BOSTON",
    "PORTLAND",
)
_STATES = (
    "AL",
    "AZ",
    "CA",
    "CO",
    "CT",
    "FL",
    "GA",
    "IL",
    "IN",
    "MA",
    "MD",
    "MI",
    "MN",
    "MO",
    "NC",
    "NJ",
    "NY",
    "OH",
    "PA",
    "TX",
    "VA",
    "WA",
    "WI",
)
_STREETS = (
    "MAIN ST",
    "OAK AVE",
    "PARK RD",
    "ELM ST",
    "CEDAR LN",
    "MAPLE DR",
    "WASHINGTON BLVD",
    "LAKE VIEW DR",
    "HIGHLAND AVE",
    "SUNSET BLVD",
)
_WORDS = (
    "ALPHA",
    "BRAVO",
    "CHARLIE",
    "DELTA",
    "ECHO",
    "FOXTROT",
    "GOLF",
    "HOTEL",
    "INDIA",
    "JULIET",
    "KILO",
    "LIMA",
    "MIKE",
    "NOVEMBER",
)
_DOMAINS = ("EXAMPLE.COM", "TEST.ORG", "SAMPLE.NET")

# Name tokens that select a semantic value provider.  Matched against the
# hyphen/underscore-separated words of the field name, so ``CUST-ZIP-CODE``
# matches ``ZIP`` but ``ZIPPER`` does not.
_MONEY_TOKENS = frozenset(
    {
        "AMT",
        "AMOUNT",
        "BAL",
        "BALANCE",
        "SALARY",
        "PRICE",
        "COST",
        "TOTAL",
        "FEE",
        "PAY",
        "CHARGE",
        "CREDIT",
        "DEBIT",
        "WAGE",
    }
)
_COUNT_TOKENS = frozenset({"CNT", "COUNT", "QTY", "QUANTITY", "NUM", "SEQ"})
_ID_TOKENS = frozenset({"ID", "KEY", "NBR", "NO", "ACCT", "ACCOUNT"})
_DATE_TOKENS = frozenset({"DATE", "DT", "DOB", "BIRTHDATE"})
_TIME_TOKENS = frozenset({"TIME", "TM", "TIMESTAMP", "TS"})
_FLAG_TOKENS = frozenset({"FLAG", "FLG", "IND", "INDICATOR", "SW", "SWITCH"})
_RATE_TOKENS = frozenset({"RATE", "PCT", "PERCENT", "RATIO"})

# Longest run of random filler generated for a wide alphanumeric field. A
# PIC X(200) comment field reads better in a CSV as a short token than as 200
# characters of noise, and a shorter value is still valid for the field.
_MAX_RANDOM_TEXT = 32


def _name_tokens(name: str) -> set[str]:
    return {t for t in _WORD_SPLIT_RE.split(name.upper()) if t}


class _ValueFactory:
    """Builds one field's value for one row.

    Every provider funnels through :meth:`_fit_text` or
    :meth:`_format_number`, so a semantic value can never violate the field's
    PICTURE.  That ordering is deliberate: heuristics improve readability, but
    the layout is the contract.

    A ``unique_fields`` column retries up to 32 times for a fresh value before
    falling back to :meth:`_sequential`.  The fallback is a counter, so it
    terminates even when the field is too narrow to supply the requested
    number of distinct values (``PIC 9`` has ten); in that case duplicates are
    unavoidable and the caller gets them rather than a hang.
    """

    def __init__(self, rng: random.Random, opts: DataGeneratorOptions) -> None:
        self._rng = rng
        self._opts = opts
        self._unique = {u.upper() for u in opts.unique_fields}
        self._used: dict[str, set[str]] = {}
        self._counters: dict[str, int] = {}

    def value_for(self, spec: FieldSpec, row: int) -> str:
        """Generate the CSV cell for *spec* in row *row* (0-based)."""
        if self._opts.blank_rate and self._rng.random() < self._opts.blank_rate:
            return ""

        needs_unique = spec.name.upper() in self._unique or (
            spec.column.upper() in self._unique
        )
        if not needs_unique:
            return self._make(spec, row)

        # Retry a bounded number of times, then fall back to a deterministic
        # counter so a narrow field (PIC 9, 10 possible values) cannot hang.
        seen = self._used.setdefault(spec.column, set())
        for _ in range(32):
            candidate = self._make(spec, row)
            if candidate not in seen:
                seen.add(candidate)
                return candidate
        candidate = self._sequential(spec)
        seen.add(candidate)
        return candidate

    # -- dispatch -----------------------------------------------------------

    def _make(self, spec: FieldSpec, row: int) -> str:
        if self._opts.use_condition_values and spec.condition_values:
            return self._fit_domain_value(self._rng.choice(spec.condition_values), spec)
        if self._opts.respect_values and spec.value_clause:
            fixed = self._from_value_clause(spec)
            if fixed is not None:
                return fixed

        if spec.category is FieldCategory.FLOAT:
            return self._float_value(spec)
        if spec.category in (
            FieldCategory.NUMERIC,
            FieldCategory.NUMERIC_EDITED,
        ):
            return self._numeric_value(spec, row)
        return self._text_value(spec, row)

    def _from_value_clause(self, spec: FieldSpec) -> str | None:
        """Resolve a VALUE clause into a constant, or ``None`` to ignore it."""
        raw = (spec.value_clause or "").strip()
        if not raw:
            return None
        figurative = _FIGURATIVE_CONSTANTS.get(raw.upper())
        if figurative is not None:
            # SPACES/LOW-VALUES mean "no meaningful initial content"; generate
            # a real value instead of filling the column with blanks.
            return figurative if figurative else None
        return self._fit_domain_value(_strip_literal_quotes(raw), spec)

    def _fit_domain_value(self, value: str, spec: FieldSpec) -> str:
        """Coerce a copybook-declared literal into the field's shape.

        The literal came from a level-88 VALUE or a VALUE clause, so it *is*
        the declared domain: ``allow_random_sign`` is off, otherwise a signed
        field could flip ``VALUE 5`` to ``-5`` and emit a value the copybook
        never permits.
        """
        if spec.category in (
            FieldCategory.NUMERIC,
            FieldCategory.NUMERIC_EDITED,
            FieldCategory.FLOAT,
        ):
            try:
                number = float(value)
            except ValueError:
                return self._fit_text(value, spec)
            return self._format_number(number, spec, allow_random_sign=False)
        return self._fit_text(value, spec)

    # -- numeric ------------------------------------------------------------

    def _numeric_value(self, spec: FieldSpec, row: int) -> str:
        tokens = _name_tokens(spec.name) if self._opts.semantic_hints else set()
        digits = spec.integer_digits
        if digits <= 0 and spec.decimal_digits <= 0:
            digits = 1

        if tokens & _DATE_TOKENS and spec.decimal_digits == 0:
            dated = self._date_digits(digits)
            if dated is not None:
                return dated
        if tokens & _TIME_TOKENS and spec.decimal_digits == 0:
            timed = self._time_digits(digits)
            if timed is not None:
                return timed
        if tokens & _ID_TOKENS:
            return self._format_number(self._sequential_number(spec, row), spec)
        if tokens & _MONEY_TOKENS:
            return self._format_number(self._money_amount(spec), spec)
        if tokens & _COUNT_TOKENS:
            ceiling = min(10**digits - 1, 999) if digits > 0 else 9
            return self._format_number(self._rng.randint(0, max(0, ceiling)), spec)
        if tokens & _RATE_TOKENS:
            return self._format_number(self._rng.uniform(0, 100), spec)

        upper = 10**digits - 1 if digits > 0 else 0
        whole = self._rng.randint(0, max(0, upper))
        fraction = self._rng.random() if spec.decimal_digits else 0.0
        return self._format_number(whole + fraction, spec)

    def _money_amount(self, spec: FieldSpec) -> float:
        """A plausible currency magnitude that still fits the field."""
        digits = spec.integer_digits
        ceiling = 10 ** min(digits, 6) - 1 if digits > 0 else 0
        amount = self._rng.uniform(0, max(1.0, float(ceiling)))
        return min(amount, float(ceiling)) if ceiling else 0.0

    def _sequential_number(self, spec: FieldSpec, row: int) -> int:
        """A monotonically increasing identifier that uses the field's width.

        The starting point scales with the declared digit count (capped at six
        digits, so a ``PIC 9(18)`` key stays human-readable) and each row adds
        one, which keeps a key column naturally near-unique.
        """
        digits = max(1, spec.integer_digits)
        modulus: int = 10**digits
        ceiling: int = min(modulus - 1, 10 ** min(digits, 6) - 1)
        base = self._rng.randint(1, ceiling) if ceiling >= 1 else 0
        return (base + row) % modulus

    def _sequential(self, spec: FieldSpec) -> str:
        """Deterministic fallback used when unique retries are exhausted."""
        count = self._counters.get(spec.column, 0)
        self._counters[spec.column] = count + 1
        if spec.category in (
            FieldCategory.NUMERIC,
            FieldCategory.NUMERIC_EDITED,
            FieldCategory.FLOAT,
        ):
            digits = max(1, spec.integer_digits)
            return self._format_number(count % (10**digits), spec)
        return self._fit_text(f"{spec.name[:4]}{count}", spec)

    def _date_digits(self, digits: int) -> str | None:
        """A valid date rendered as *digits* digits, or ``None`` if it won't fit."""
        year = self._rng.randint(1970, 2030)
        month = self._rng.randint(1, 12)
        # 28 days keeps every month valid without a calendar lookup.
        day = self._rng.randint(1, 28)
        if digits >= 8:
            return f"{year:04d}{month:02d}{day:02d}".rjust(digits, "0")[-digits:]
        if digits >= 6:
            return f"{year % 100:02d}{month:02d}{day:02d}"
        return None

    def _time_digits(self, digits: int) -> str | None:
        """A valid time of day rendered as *digits* digits."""
        hour = self._rng.randint(0, 23)
        minute = self._rng.randint(0, 59)
        second = self._rng.randint(0, 59)
        if digits >= 6:
            return f"{hour:02d}{minute:02d}{second:02d}".rjust(digits, "0")[-digits:]
        if digits >= 4:
            return f"{hour:02d}{minute:02d}"
        return None

    def _float_value(self, spec: FieldSpec) -> str:
        del spec  # COMP-1/COMP-2 carry no picture to constrain the value.
        return f"{self._rng.uniform(-10_000, 10_000):.4f}"

    def _format_number(
        self,
        value: float | int,
        spec: FieldSpec,
        *,
        allow_random_sign: bool = True,
    ) -> str:
        """Render *value* so it fits the field's digit counts and sign.

        ``allow_random_sign`` lets a signed field occasionally negate a
        freshly generated magnitude, so negative values are exercised. Callers
        formatting a value the copybook *declared* pass ``False`` -- see
        :meth:`_fit_domain_value`.
        """
        decimals = spec.decimal_digits
        digits = spec.integer_digits
        magnitude = abs(float(value))
        if digits > 0:
            ceiling = 10**digits - 10**-decimals if decimals else 10**digits - 1
            magnitude = min(magnitude, float(ceiling))
        elif decimals:
            magnitude = min(magnitude, 1 - 10.0**-decimals)
        else:
            magnitude = 0.0

        negative = spec.is_signed and (
            float(value) < 0
            or (allow_random_sign and magnitude > 0 and self._rng.random() < 0.25)
        )
        text = f"{magnitude:.{decimals}f}" if decimals else str(int(round(magnitude)))
        # Rounding at the boundary can push the value one digit over.
        if digits > 0:
            integer_part = text.split(".")[0]
            if len(integer_part) > digits:
                text = ("9" * digits) + (text[len(integer_part) :] if decimals else "")
        return f"-{text}" if negative and float(text) != 0 else text

    # -- text ---------------------------------------------------------------

    def _text_value(self, spec: FieldSpec, row: int) -> str:
        """Generate an alphanumeric value for *spec*.

        Random filler is capped at :data:`_MAX_RANDOM_TEXT` characters rather
        than filling the whole picture: a ``PIC X(200)`` comment field is more
        useful in a CSV as a short readable token than as 200 characters of
        noise.  The value is still valid -- shorter than the field, which
        COBOL pads on the MOVE.  Semantic and declared values are unaffected.
        """
        tokens = _name_tokens(spec.name) if self._opts.semantic_hints else set()
        size = spec.size

        if tokens & _FLAG_TOKENS and size <= 2:
            return self._rng.choice(("Y", "N"))
        if self._opts.semantic_hints:
            semantic = self._semantic_text(tokens, spec, row)
            if semantic is not None:
                return self._fit_text(semantic, spec)

        if spec.category is FieldCategory.ALPHABETIC:
            alphabet = string.ascii_uppercase
        else:
            alphabet = string.ascii_uppercase + string.digits
        length = min(size, _MAX_RANDOM_TEXT)
        return "".join(self._rng.choice(alphabet) for _ in range(max(1, length)))

    def _semantic_text(self, tokens: set[str], spec: FieldSpec, row: int) -> str | None:
        """Pick a readable value from the field name, or ``None`` for random."""
        rng = self._rng
        if {"EMAIL", "MAIL"} & tokens:
            return (
                f"{rng.choice(_FIRST_NAMES).lower()}."
                f"{rng.choice(_LAST_NAMES).lower()}@{rng.choice(_DOMAINS).lower()}"
            )
        if {"PHONE", "TEL", "MOBILE", "FAX"} & tokens:
            return f"{rng.randint(200, 989)}{rng.randint(200, 989)}{rng.randint(0, 9999):04d}"
        if "STATE" in tokens or "ST" in tokens:
            return rng.choice(_STATES)
        if {"ZIP", "POSTAL", "POSTCODE"} & tokens:
            return f"{rng.randint(1000, 99999):05d}"
        if "CITY" in tokens:
            return rng.choice(_CITIES)
        if {"STREET", "ADDR", "ADDRESS"} & tokens:
            return f"{rng.randint(1, 9999)} {rng.choice(_STREETS)}"
        if {"FIRST", "FNAME", "GIVEN"} & tokens:
            return rng.choice(_FIRST_NAMES)
        if {"LAST", "LNAME", "SURNAME", "FAMILY"} & tokens:
            return rng.choice(_LAST_NAMES)
        if "NAME" in tokens:
            return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        if tokens & _DATE_TOKENS:
            return f"{rng.randint(1970, 2030):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        if {"DESC", "DESCRIPTION", "TEXT", "COMMENT", "NOTE", "MEMO"} & tokens:
            words = [rng.choice(_WORDS) for _ in range(3)]
            return " ".join(words)
        if "CODE" in tokens or "CD" in tokens or "TYPE" in tokens:
            length = max(1, min(spec.size, 4))
            return "".join(rng.choice(string.ascii_uppercase) for _ in range(length))
        if tokens & _ID_TOKENS:
            return f"{spec.name.split('-')[0][:3]}{row + 1:0{max(1, spec.size - 3)}d}"
        return None

    def _fit_text(self, value: str, spec: FieldSpec) -> str:
        """Truncate *value* to the field's character capacity.

        Values are not space-padded: a CSV cell carries the value, and the
        COBOL program pads on the MOVE.  Trailing blanks in a CSV are lost or
        misread by most consumers anyway.
        """
        size = spec.size if spec.size > 0 else len(value)
        return value[:size]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass
class GeneratedDataset:
    """The generated rows plus the layout they were generated from.

    Attributes:
        record_name: Name of the level-01 record the columns came from.
        fields: Column specifications, in record order.
        rows: Generated rows, each a list of cells aligned to ``fields``.
        seed: The seed actually used -- pass it back to reproduce this run.
    """

    record_name: str
    fields: list[FieldSpec]
    rows: list[list[str]]
    seed: int

    @property
    def header(self) -> list[str]:
        """CSV header: one column name per field."""
        return [f.column for f in self.fields]

    def to_csv(self, *, line_terminator: str = _DEFAULT_LINE_TERMINATOR) -> str:
        """Render the dataset as CSV text, header row first."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator=line_terminator)
        writer.writerow(self.header)
        writer.writerows(self.rows)
        return buffer.getvalue()

    def write_csv(
        self,
        path: str | os.PathLike[str],
        *,
        line_terminator: str = _DEFAULT_LINE_TERMINATOR,
    ) -> None:
        """Write the dataset to *path* as CSV.

        Uses ``newline=""`` per the :mod:`csv` module's contract, so quoted
        cells containing newlines round-trip correctly on every platform.

        The line terminator defaults to the same ``"\\n"`` :meth:`to_csv`
        uses, *not* the :mod:`csv` module's ``"\\r\\n"``.  Sharing the default
        is what makes the byte-identical guarantee hold across output paths:
        otherwise ``gen-data -o out.csv`` and ``gen-data > out.csv`` would
        write different bytes for the same seed.  Pass ``"\\r\\n"`` explicitly
        for strict RFC 4180 output.
        """
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator=line_terminator)
            writer.writerow(self.header)
            writer.writerows(self.rows)

    def to_dicts(self) -> list[dict[str, str]]:
        """Return the rows as column-name-keyed dicts."""
        header = self.header
        return [dict(zip(header, row, strict=True)) for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the dataset (layout plus rows) for JSON output."""
        return {
            "record_name": self.record_name,
            "seed": self.seed,
            "row_count": len(self.rows),
            "fields": [f.to_dict() for f in self.fields],
            "rows": self.to_dicts(),
        }


class CopybookDataGenerator:
    """Generates synthetic CSV test data from a COBOL copybook layout.

    Example::

        generator = CopybookDataGenerator(DataGeneratorOptions(rows=50, seed=1))
        dataset = generator.generate_from_source(copybook_text)
        dataset.write_csv("customers.csv")
    """

    def __init__(self, options: DataGeneratorOptions | None = None) -> None:
        self.options = options or DataGeneratorOptions()

    # -- entry points -------------------------------------------------------

    def generate_from_file(
        self,
        path: str | os.PathLike[str],
        *,
        record: str | None = None,
    ) -> GeneratedDataset:
        """Read a copybook from *path* and generate a dataset from it."""
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        return self.generate_from_source(source, filename=str(path), record=record)

    def generate_from_source(
        self,
        source: str,
        *,
        filename: str = "<copybook>",
        record: str | None = None,
    ) -> GeneratedDataset:
        """Parse *source* and generate a dataset from one of its records.

        Args:
            source: Copybook text, or a full COBOL program.
            filename: Name used in error messages.
            record: Which level-01 record to use.  Defaults to the first.

        Raises:
            CopybookLayoutError: if the copybook has no usable layout, or the
                requested *record* is not present.
        """
        records = parse_copybook_records(source, filename=filename)
        chosen = self._select_record(records, record, filename)
        return self.generate_from_record(chosen)

    def generate_from_record(self, record: CobolDataItem) -> GeneratedDataset:
        """Generate a dataset from an already-parsed record item."""
        fields = flatten_record(record, self.options)
        if not fields:
            raise CopybookLayoutError(
                f"{record.name}: record has no generatable fields "
                "(all FILLER, REDEFINES, or empty)"
            )

        seed = self.options.seed
        if seed is None:
            seed = random.randrange(2**31)
        rng = random.Random(seed)
        factory = _ValueFactory(rng, self.options)

        rows = [
            [factory.value_for(spec, row) for spec in fields]
            for row in range(self.options.rows)
        ]
        return GeneratedDataset(
            record_name=record.name,
            fields=fields,
            rows=rows,
            seed=seed,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _select_record(
        records: list[CobolDataItem],
        record: str | None,
        filename: str,
    ) -> CobolDataItem:
        if record is None:
            return records[0]
        wanted = record.upper()
        for item in records:
            if item.name.upper() == wanted:
                return item
        available = ", ".join(item.name for item in records)
        raise CopybookLayoutError(
            f"{filename}: record '{record}' not found (available: {available})"
        )
