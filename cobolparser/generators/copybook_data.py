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
from dataclasses import dataclass
from typing import Any

from ..models.data_items import (
    CobolDataItem,
)
from ..models.program import CobolProgram
from ..parser import parse_cobol
from ..plugins.core import ErrorRecoveryMode
from .data.layout import (
    FieldCategory,
    FieldSpec,
    _strip_literal_quotes,
    flatten_record,
)

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


# Line terminator shared by every CSV output path. Deliberately "\n" rather
# than the csv module's RFC 4180 "\r\n": both GeneratedDataset.to_csv and
# .write_csv must agree, or the same seed writes different bytes to stdout
# than to --output.
_DEFAULT_LINE_TERMINATOR = "\n"


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
