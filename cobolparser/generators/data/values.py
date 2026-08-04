"""Value generation for synthetic test-data fields."""

from __future__ import annotations

import random
import re
import string

from .layout import FieldCategory, FieldSpec, _strip_literal_quotes
from .options import DataGeneratorOptions

# Figurative constants: the standard COBOL literal values
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

# Semantic data corpora for generating realistic test values
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

# Word-split regex for parsing field names into semantic tokens
_WORD_SPLIT_RE = re.compile(r"[-_]+")


def _name_tokens(name: str) -> set[str]:
    """Extract semantic tokens from a COBOL field name."""
    return {t for t in _WORD_SPLIT_RE.split(name.upper()) if t}


class ValueFactory:
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

    def render(self, spec: FieldSpec, value: str) -> str:
        """Render an already-chosen *value* through the field's PICTURE.

        Thin public wrapper over :meth:`_fit_domain_value` -- the same
        numeric/text fitting a declared level-88 or VALUE-clause literal
        already goes through -- exposed so the Phase 4 constraint solver
        (``cobolparser.analysis.domains``) can render a solved witness the
        same way. ``allow_random_sign`` stays off, same reasoning: a solver
        picked *this exact* value to satisfy a constraint, so a random sign
        flip could silently produce a value that no longer does.
        """
        return self._fit_domain_value(str(value), spec)

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
