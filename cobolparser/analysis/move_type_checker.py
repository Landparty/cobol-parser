"""
MOVE statement type compatibility checker for COBOL programs.

Walks the AST, builds a catalog of data items from the DATA DIVISION,
then checks every MOVE statement for category mismatches according to
IBM Enterprise COBOL data movement rules.

COBOL data categories (simplified):
  NUMERIC        — PIC 9, S9, 9V9, COMP, etc.
  NUMERIC-EDITED — PIC Z9, 9.9, -9, etc. (contains editing characters)
  ALPHABETIC     — PIC A (letters and spaces only)
  ALPHANUMERIC   — PIC X (any characters)
  ALPHANUMERIC-EDITED — PIC X with editing characters (B, 0, /, etc.)
  FIGURATIVE     — ZERO/ZEROS, SPACE/SPACES, HIGH-VALUE, LOW-VALUE, etc.

Key incompatibility rules caught:
  - NUMERIC  →  ALPHABETIC  (ILLEGAL)
  - ALPHABETIC  →  NUMERIC  (ILLEGAL)
  - SPACES/HIGH-VALUE/LOW-VALUE/QUOTE  →  NUMERIC/NUMERIC-EDITED  (ILLEGAL;
    none of these figurative constants has a digit value)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from ..dialects.le_signatures import intrinsic_signature
from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem, PictureClause
from ..models.program import CobolProgram
from ..models.statements import MoveStatement
from ._names import base_data_name
from .unused_variables import inherited_data_records


class DataCategory(Enum):
    """COBOL data item categories relevant to MOVE compatibility."""

    NUMERIC = auto()
    NUMERIC_EDITED = auto()
    ALPHABETIC = auto()
    ALPHANUMERIC = auto()
    ALPHANUMERIC_EDITED = auto()
    FIGURATIVE = auto()
    UNKNOWN = auto()


class MoveViolationKind(Enum):
    """Severity of a MOVE type mismatch."""

    ERROR = auto()  # Illegal move (e.g., numeric → alphabetic)
    WARNING = auto()  # Legal but potentially lossy (e.g., alphanumeric → numeric)


@dataclass
class MoveTypeViolation:
    """A single MOVE type compatibility issue."""

    kind: MoveViolationKind
    source_name: str
    target_name: str
    source_category: DataCategory
    target_category: DataCategory
    location: SourceLocation | None
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "source": self.source_name,
            "target": self.target_name,
            "source_category": self.source_category.name,
            "target_category": self.target_category.name,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location
                else None
            ),
            "message": self.message,
        }


@dataclass
class MoveTypeReport:
    """Result of a MOVE type compatibility analysis."""

    violations: list[MoveTypeViolation] = field(default_factory=list)
    #: Count of source/target operands that could not be resolved to a known
    #: DataCategory (e.g. an undeclared identifier, an unexpanded copybook
    #: field, or a NULL/NULLS figurative constant -- legal only into a
    #: POINTER receiver, which this checker does not model) and were
    #: therefore skipped rather than checked. A report with zero violations
    #: and a non-zero unresolved_count means "nothing was found wrong" is
    #: not the same as "everything was checked" -- see
    #: reports/open-findings.md H5.
    unresolved_count: int = 0
    #: The part of ``unresolved_count`` that no copybook could ever resolve:
    #: a MOVE whose source is an intrinsic FUNCTION this checker has no
    #: category for (a NATIONAL result, or a name the intrinsic catalog does
    #: not list), or a numeric FUNCTION result that may or may not be an
    #: integer moved to an alphanumeric item. Counted separately so a caveat can name the real reason
    #: instead of pointing at a COPY that is not missing.
    unresolved_function_count: int = 0

    @property
    def errors(self) -> list[MoveTypeViolation]:
        return [v for v in self.violations if v.kind == MoveViolationKind.ERROR]

    @property
    def warnings(self) -> list[MoveTypeViolation]:
        return [v for v in self.violations if v.kind == MoveViolationKind.WARNING]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict:
        return {
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "unresolved_count": self.unresolved_count,
            "unresolved_function_count": self.unresolved_function_count,
            "violations": [v.to_dict() for v in self.violations],
        }


# Regex patterns for picture category classification
_PIC_NUMERIC_ONLY_RE = re.compile(r"^[S9VP()\d]+$", re.IGNORECASE)
_PIC_ALPHA_ONLY_RE = re.compile(r"^(?:A(?:\(\d+\))?)+$", re.IGNORECASE)
_PIC_X_ONLY_RE = re.compile(r"^X(\(\d+\))?$", re.IGNORECASE)
_PIC_EDITED_CHARS_RE = re.compile(r"[Z\*\+\-\$\.,/B0]", re.IGNORECASE)
# Strip repetition counts like (10) or (20) before checking for edit chars so
# that PIC 9(10) is not misclassified as NUMERIC_EDITED because of the '0'
# inside the parenthesised repeat count.
_PIC_REPEAT_RE = re.compile(r"\(\d+\)")

_FIGURATIVE_CONSTANTS = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)

# ZERO has a digit value, so it is a legal MOVE source into every category
# this checker models (numeric, numeric-edited, alphabetic, alphanumeric,
# alphanumeric-edited) -- unlike the other figurative constants below, it
# never produces a violation and never needs the catalog to resolve it.
_FIGURATIVE_ZERO = frozenset({"ZERO", "ZEROS", "ZEROES"})

# The "fill" figurative constants: legal into an alphabetic, alphanumeric or
# alphanumeric-edited receiver (they fill it with the given character/byte),
# illegal into a numeric or numeric-edited one -- none of them has a digit
# value. NULL/NULLS are deliberately excluded from both sets: per the COBOL
# standard they are legal only into a USAGE POINTER (or FUNCTION-POINTER /
# OBJECT REFERENCE) receiving item, a category this checker does not model,
# so a NULL source is left statically unresolved rather than risk a wrong
# verdict against an ordinary numeric/alphanumeric target.
_FIGURATIVE_FILL = frozenset(
    {
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
    }
)

# Receiver categories a fill figurative constant has no digit value for.
_FIGURATIVE_FILL_ILLEGAL_TARGETS: frozenset[DataCategory] = frozenset(
    {DataCategory.NUMERIC, DataCategory.NUMERIC_EDITED}
)

# COBOL special registers with a fixed, implicit numeric picture -- they never
# appear in the DATA DIVISION with a PICTURE clause of their own, so the
# catalog built from CobolDataItem nodes can never contain them. Without this,
# every MOVE touching RETURN-CODE (by far the most common of the three) was
# silently counted as unresolved rather than checked.
_NUMERIC_SPECIAL_REGISTERS = frozenset({"RETURN-CODE", "TALLY", "LINAGE-COUNTER"})

# Intrinsic FUNCTION result categories, keyed by the ``returns`` wording of
# ``dialects.le_signatures``' intrinsic catalog (which lists every intrinsic).
# An integer function is numeric with no decimal places. Whether a numeric
# function's result has any is not known at compile time (NUMVAL("12") is an
# integer, NUMVAL("1.5") is not), so its integer-ness is ``None``: unknown,
# never assumed either way.
_INTRINSIC_RETURN_CATEGORIES: dict[str, tuple[DataCategory, bool | None]] = {
    "alphanumeric": (DataCategory.ALPHANUMERIC, False),
    "integer": (DataCategory.NUMERIC, False),
    "numeric": (DataCategory.NUMERIC, None),
}

# Numeric functions whose integer-ness follows their arguments, like MAX / MIN
# / ABS: a sum, remainder or range of integers is an integer, and one with a
# non-integer argument is not.
_INTEGER_WHEN_ARGUMENTS_ARE = frozenset({"SUM", "REM", "RANGE"})

# Alphanumeric-catalogued functions that really return their argument's class
# (a national argument gives a national result): their argument must resolve.
_ARGUMENT_CLASS_ALPHANUMERIC = frozenset({"LOWER-CASE", "UPPER-CASE", "REVERSE"})

# Intrinsics whose result takes the class of their argument(s) (TRIM, ABS,
# USUBSTR, MAX, MIN): resolved from the first argument's category.
_ARGUMENT_CLASS_RETURNS = frozenset(
    {"same class as argument-1", "same class as the arguments"}
)

# Words inside an intrinsic's argument list that are not arguments: TRIM's
# LEADING/TRAILING mode keyword.
_FUNCTION_ARGUMENT_KEYWORDS = frozenset({"LEADING", "TRAILING"})

# An intrinsic function reference as the MOVE parser folds it:
# ``FUNCTION TRIM(X OF G LEADING)``, ``FUNCTION CURRENT-DATE(1:8)``.
_FUNCTION_REFERENCE_RE = re.compile(
    r"^FUNCTION\s+([A-Za-z0-9][A-Za-z0-9-]*)\s*(.*)$", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class _FunctionSource:
    """An intrinsic FUNCTION sending operand, split into its parts."""

    name: str
    arguments: tuple[str, ...]
    reference_modified: bool


def _paren_groups(text: str) -> list[str] | None:
    """The contents of each top-level ``( ... )`` group in *text*, in order.

    Quotes are respected, so a ``)`` inside a literal argument does not close
    a group. ``None`` when *text* is anything but a run of balanced groups.
    """
    groups: list[str] = []
    depth = 0
    quote = ""
    start = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            if depth == 0:
                return None
            quote = ch
        elif ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                groups.append(text[start:i])
        elif depth == 0 and not ch.isspace():
            return None
    if depth or quote:
        return None
    return groups


def _split_arguments(text: str) -> tuple[str, ...]:
    """One string per argument of an intrinsic's argument list.

    Arguments are separated by blanks or commas outside parentheses and
    quotes; an ``OF``/``IN`` qualifier stays with the name it qualifies, a
    subscript group stays with the item it subscripts, and a nested
    ``FUNCTION name(...)`` stays one argument.
    """
    words: list[str] = []
    current = ""
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            current += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and (ch.isspace() or ch == ","):
            if current:
                words.append(current)
                current = ""
            continue
        current += ch
    if current:
        words.append(current)

    arguments: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        if word.upper() in _FUNCTION_ARGUMENT_KEYWORDS:
            i += 1
            continue
        if word.upper() == "FUNCTION" and i + 1 < len(words):
            # A nested intrinsic is one argument: FUNCTION NUMVAL(X).
            i += 1
            word = f"{word} {words[i]}"
        while i + 2 < len(words) and words[i + 1].upper() in ("OF", "IN"):
            word = f"{word} {words[i + 1]} {words[i + 2]}"
            i += 2
        arguments.append(word)
        i += 1
    return tuple(arguments)


def _function_source(name: str) -> _FunctionSource | None:
    """Split ``FUNCTION NAME(args)(start:length)`` into its parts."""
    match = _FUNCTION_REFERENCE_RE.match(name.strip())
    if match is None:
        return None
    groups = _paren_groups(match.group(2))
    if groups is None:
        return None
    # A reference modifier is the one group with a ``:`` at its top level;
    # an argument list never has one (arguments are blank/comma separated).
    reference_modified = bool(groups) and ":" in _strip_nested(groups[-1])
    if reference_modified:
        groups = groups[:-1]
    if len(groups) > 1:
        return None
    arguments = _split_arguments(groups[0]) if groups else ()
    return _FunctionSource(match.group(1).upper(), arguments, reference_modified)


def _strip_nested(text: str) -> str:
    """*text* with every nested ``( ... )`` group and literal removed."""
    out = ""
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            out += ch
    return out


# Illegal MOVE combinations: (source_category, target_category), per the
# IBM Enterprise COBOL Language Reference's "Valid and invalid elementary
# moves" table. An alphanumeric-edited sending item may only go to an
# alphabetic, alphanumeric or alphanumeric-edited receiver -- never to a
# numeric or numeric-edited one (the editing characters have no numeric
# meaning; de-editing is defined for numeric-edited sources only).
_ILLEGAL_MOVES: frozenset[tuple[DataCategory, DataCategory]] = frozenset(
    {
        (DataCategory.NUMERIC, DataCategory.ALPHABETIC),
        (DataCategory.NUMERIC_EDITED, DataCategory.ALPHABETIC),
        (DataCategory.ALPHABETIC, DataCategory.NUMERIC),
        (DataCategory.ALPHABETIC, DataCategory.NUMERIC_EDITED),
        (DataCategory.ALPHANUMERIC_EDITED, DataCategory.NUMERIC),
        (DataCategory.ALPHANUMERIC_EDITED, DataCategory.NUMERIC_EDITED),
    }
)

# The same table splits numeric *sending* items by integer-ness: an integer
# (PIC 9(5), COMP-3 with no V) may be moved to an alphanumeric or
# alphanumeric-edited receiver, a non-integer (PIC 9(5)V99, PIC PPP9, a
# COMP-1/COMP-2 floating-point item) may not -- there is no way to place the
# implied decimal point in a character field. These are the receivers that
# rule forbids for a non-integer numeric source.
_NON_INTEGER_NUMERIC_ILLEGAL_TARGETS: frozenset[DataCategory] = frozenset(
    {DataCategory.ALPHANUMERIC, DataCategory.ALPHANUMERIC_EDITED}
)

# Potentially problematic (warning-level) combinations
_WARN_MOVES: frozenset[tuple[DataCategory, DataCategory]] = frozenset(
    {
        (DataCategory.ALPHANUMERIC, DataCategory.NUMERIC),
        (DataCategory.ALPHANUMERIC, DataCategory.NUMERIC_EDITED),
        (DataCategory.NUMERIC_EDITED, DataCategory.NUMERIC),
    }
)

# A reference folded with its subscript / reference-modification group glued
# on (``T-E(2)``, ``WS-A(1:3)``, ``T-E(IX)(1:2)``) -- the MOVE parser folds a
# *source* operand this way, while ``base_data_name`` only splits the spaced
# ``WS-TAB ( 3 )`` form, so a glued source missed the catalog entirely.
_GLUED_REFERENCE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)\s*\(")

# The group names an ``OF``/``IN`` qualifier chain names in a folded operand.
_QUALIFIER_RE = re.compile(r"\b(?:OF|IN)\s+([A-Za-z0-9][A-Za-z0-9-]*)", re.IGNORECASE)


def _reference_name(name: str) -> str:
    """The referenced item's own name from a folded operand string."""
    match = _GLUED_REFERENCE_RE.match(name.strip())
    if match:
        return match.group(1)
    return base_data_name(name)


def _is_reference_modified(name: str) -> bool:
    """Whether a folded reference carries a ``(start:length)`` group.

    A reference-modified operand is an alphanumeric item whatever its base
    item's category (IBM Language Reference, "Reference modification").
    """
    base = _reference_name(name)
    if base == name.strip():
        return False
    return ":" in name.strip()[len(base) :]


# USAGE keywords of internal floating-point items: numeric, never integer,
# and declared without a PICTURE clause of their own.
_FLOATING_POINT_USAGES = frozenset({"COMP-1", "COMP-2"})


def _is_non_integer_picture(pic: PictureClause) -> bool:
    """True for a numeric PICTURE describing a non-integer value: digits
    after an assumed decimal point (``9(5)V99``) or a leading decimal-scaling
    ``P`` run (``PPP9``, value .000n).

    ``decimal_digits`` alone is the single canonical source for this: a
    leading-``P`` picture already reports ``decimal_digits = P-count +
    9-count`` from ``PictureClause._parse_scaled_pattern`` (a trailing-``P``
    picture like ``9(3)PPP`` is a *scaled integer* -- ``decimal_digits == 0``
    -- and correctly excluded). This used to also re-derive the leading-P
    case from the raw pattern string independently; that duplicate check was
    redundant with (and could disagree with) the canonical parse.
    """
    return (pic.decimal_digits or 0) > 0


def _is_floating_point_usage(usage: str | None) -> bool:
    normalized = (usage or "").upper().replace("COMPUTATIONAL", "COMP")
    return normalized in _FLOATING_POINT_USAGES


def _classify_picture(pic: PictureClause) -> DataCategory:
    """Determine the COBOL data category from a PictureClause node."""
    pattern = (pic.pattern or "").upper().strip()

    # A trailing CR/DB credit/debit sign symbol makes the item
    # numeric-edited. DB used to be caught only by accident (its 'B'
    # matched the blank-insertion edit char) while CR fell through to
    # UNKNOWN — the two equivalent sign symbols must classify identically.
    if pattern.endswith(("CR", "DB")):
        return DataCategory.NUMERIC_EDITED

    # Pure alphabetic: A or A(n)
    if _PIC_ALPHA_ONLY_RE.match(pattern):
        return DataCategory.ALPHABETIC

    # Pure alphanumeric: X or X(n)
    if _PIC_X_ONLY_RE.match(pattern):
        return DataCategory.ALPHANUMERIC

    # Strip repetition counts before checking for edit chars so that a
    # pattern like 9(10) is not misclassified due to the '0' in '(10)'.
    pattern_no_reps = _PIC_REPEAT_RE.sub("", pattern)
    has_edit_chars = bool(_PIC_EDITED_CHARS_RE.search(pattern_no_reps))

    if has_edit_chars:
        # Test symbols on pattern_no_reps: the 9 in a repeat count such as
        # X(9)BX(9) is not a digit position.
        # Numeric-edited: contains 9s alongside editing characters
        if "9" in pattern_no_reps:
            return DataCategory.NUMERIC_EDITED
        # Alphanumeric-edited: X with editing chars
        if "X" in pattern_no_reps or "A" in pattern_no_reps:
            return DataCategory.ALPHANUMERIC_EDITED
        return DataCategory.NUMERIC_EDITED  # default for edited

    # Pure numeric: only S, 9, V, P and grouping digits
    if _PIC_NUMERIC_ONLY_RE.match(pattern):
        return DataCategory.NUMERIC

    # Mixed X/9 or X/A — treat as alphanumeric
    if "X" in pattern or "A" in pattern:
        return DataCategory.ALPHANUMERIC

    return DataCategory.UNKNOWN


def _classify_literal(value: str) -> DataCategory:
    """Classify an unresolved source operand (literal or figurative constant)."""
    upper = value.upper().strip()

    if upper in _FIGURATIVE_CONSTANTS:
        return DataCategory.FIGURATIVE

    # Quoted string literal
    if (upper.startswith('"') and upper.endswith('"')) or (
        upper.startswith("'") and upper.endswith("'")
    ):
        return DataCategory.ALPHANUMERIC

    # Numeric literal
    stripped = upper.lstrip("+-")
    if stripped.replace(".", "", 1).isdigit():
        return DataCategory.NUMERIC

    return DataCategory.UNKNOWN


def _item_entry(node: CobolDataItem) -> tuple[DataCategory, bool, bool] | None:
    """``(category, non-integer, is-group)`` of a data item, or ``None`` when
    its description gives it no category this checker models."""
    pic = node.picture_clause
    if pic is not None:
        category = _classify_picture(pic)
        return (
            category,
            category == DataCategory.NUMERIC
            and (
                _is_non_integer_picture(pic)
                or _is_floating_point_usage(getattr(node, "usage", None))
            ),
            False,
        )
    if _is_floating_point_usage(getattr(node, "usage", None)):
        # COMP-1/COMP-2 carry no PICTURE: numeric, non-integer.
        return (DataCategory.NUMERIC, True, False)
    if any(isinstance(child, CobolDataItem) for child in getattr(node, "children", ())):
        return (DataCategory.ALPHANUMERIC, False, True)
    return None


#: USAGEs whose items never take part in MOVE CORRESPONDING (IBM Language
#: Reference, "CORRESPONDING phrase").
_CORRESPONDING_EXCLUDED_USAGES = frozenset(
    {"INDEX", "POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "OBJECT-REFERENCE"}
)


def _corresponding_paths(
    root: CobolDataItem,
) -> dict[tuple[str, ...], CobolDataItem]:
    """Each subordinate of *root* that can take part in a CORRESPONDING
    pairing, keyed by its name path below *root*.

    FILLER, level 66/77/88, REDEFINES, OCCURS and INDEX/POINTER items --
    and everything beneath a REDEFINES or OCCURS item -- are left out, as
    the IBM rules require. *root* itself may carry REDEFINES or OCCURS.
    """
    out: dict[tuple[str, ...], CobolDataItem] = {}

    def walk(item: CobolDataItem, path: tuple[str, ...]) -> None:
        for child in item.children:
            if not isinstance(child, CobolDataItem):
                continue
            name = (child.name or "").upper().strip()
            if (
                not name
                or child.is_filler
                or child.level in (66, 77, 88)
                or child.redefines
                or child.occurs_clause is not None
                or (child.usage or "").upper() in _CORRESPONDING_EXCLUDED_USAGES
                or child.object_class is not None
            ):
                continue
            child_path = (*path, name)
            out.setdefault(child_path, child)
            walk(child, child_path)

    walk(root, ())
    return out


class MoveTypeChecker:
    """Checks MOVE statements for data category incompatibilities.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import MoveTypeChecker

        result = parse_cobol(source)
        checker = MoveTypeChecker()
        report = checker.check(result.ast)
        for v in report.violations:
            print(v.message)
    """

    def __init__(self) -> None:
        # Map of upper-case data-item name → DataCategory
        self._catalog: dict[str, DataCategory] = {}
        # NUMERIC catalog entries that are *not* integers (a V or leading P
        # in the PICTURE, or COMP-1/COMP-2 usage) -- the IBM move rules
        # treat those as a category of their own on the sending side.
        self._non_integer: set[str] = set()
        # Group items (catalogued ALPHANUMERIC). A MOVE *into* a group is a
        # group move -- the sending item's bytes copied as if both were
        # alphanumeric, legal whatever the sender's category -- so no
        # elementary MOVE rule applies to a group receiver.
        self._groups: set[str] = set()
        # Every declaration of each data name: (group ancestors, (category,
        # non-integer, is-group)).
        self._declarations: dict[
            str, list[tuple[frozenset[str], tuple[DataCategory, bool, bool]]]
        ] = {}
        # Every named data item node, with its group ancestors -- what a
        # MOVE CORRESPONDING operand is resolved to so its subordinates can
        # be paired.
        self._items: dict[str, list[tuple[frozenset[str], CobolDataItem]]] = {}
        self._unresolved_count = 0
        self._unresolved_function_count = 0

    def check(self, ast: CobolProgram) -> MoveTypeReport:
        """Analyze *ast* and return a MoveTypeReport.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            MoveTypeReport with all detected type violations.
        """
        self._catalog = {}
        self._non_integer = set()
        self._groups = set()
        self._declarations = {}
        self._items = {}
        self._unresolved_count = 0
        self._unresolved_function_count = 0
        violations: list[MoveTypeViolation] = []

        # Phase 1: build catalog from DATA DIVISION -- *ast*'s own, plus the
        # GLOBAL records of the programs containing it (#504). A contained
        # program's data and MOVEs are its own unit's business: walking them
        # here let an inner namesake poison an outer item's category.
        self._build_catalog(ast)
        for _owner, _section, record in inherited_data_records(ast):
            self._build_catalog(record)
        self._index_catalog()

        # Phase 2: check every MOVE statement
        self._check_moves(ast, violations)

        return MoveTypeReport(
            violations=violations,
            unresolved_count=self._unresolved_count,
            unresolved_function_count=self._unresolved_function_count,
        )

    # ------------------------------------------------------------------
    # Catalog building
    # ------------------------------------------------------------------

    def _build_catalog(self, node: ASTNode, ancestors: tuple[str, ...] = ()) -> None:
        """Recursively collect PIC clauses from CobolDataItem nodes.

        A group item (e.g. an 01/05-level header with no PICTURE of its own,
        only subordinate elementary items) is cataloged as ALPHANUMERIC: an
        elementary MOVE of a group operand always moves it byte-for-byte, as
        though described PIC X, regardless of what its subordinate items
        contain. Without this, every group-level MOVE target/source (a very
        common pattern -- e.g. `MOVE FUNCTION CURRENT-DATE TO` a date/time
        group) was silently counted as unresolved rather than checked.

        A name declared more than once (``WS-A`` under both ``GRP1`` and
        ``GRP2``) is only catalogued by bare name when every declaration
        agrees; otherwise its declarations are kept with their group
        ancestors and a reference is resolved by its ``OF``/``IN``
        qualifiers (see ``_qualified_entry``) -- last-declaration-wins gave
        ``WS-A OF GRP1`` the category of ``GRP2``'s ``WS-A``.
        """
        child_ancestors = ancestors
        if isinstance(node, CobolDataItem):
            name = (node.name or "").upper().strip()
            entry = _item_entry(node) if name else None
            if entry is not None:
                self._declarations.setdefault(name, []).append(
                    (frozenset(ancestors), entry)
                )
            if name:
                self._items.setdefault(name, []).append((frozenset(ancestors), node))
                child_ancestors = (*ancestors, name)

        if hasattr(node, "children"):
            for child in node.children:
                if not isinstance(child, CobolProgram):
                    self._build_catalog(child, child_ancestors)

    def _index_catalog(self) -> None:
        """Fill the bare-name catalog from the collected declarations."""
        for name, declarations in self._declarations.items():
            if len({entry for _, entry in declarations}) != 1:
                continue  # differs by qualification: see _qualified_entry
            category, non_integer, is_group = declarations[0][1]
            self._catalog[name] = category
            if non_integer:
                self._non_integer.add(name)
            if is_group:
                self._groups.add(name)

    def _qualified_entry(self, name: str) -> tuple[DataCategory, bool, bool] | None:
        """The declaration a qualified reference (``WS-A OF GRP1``) names,
        for a data name whose declarations disagree."""
        declarations = self._declarations.get(_reference_name(name).upper())
        if not declarations:
            return None
        qualifiers = {q.upper() for q in _QUALIFIER_RE.findall(name)}
        entries = {
            entry for ancestors, entry in declarations if qualifiers <= ancestors
        }
        return entries.pop() if len(entries) == 1 else None

    # ------------------------------------------------------------------
    # MOVE checking
    # ------------------------------------------------------------------

    def _check_moves(self, node: ASTNode, violations: list[MoveTypeViolation]) -> None:
        """Recursively walk AST finding MoveStatement nodes to validate."""
        if isinstance(node, MoveStatement):
            self._validate_move(node, violations)

        if hasattr(node, "children"):
            for child in node.children:
                if not isinstance(child, CobolProgram):
                    self._check_moves(child, violations)

    def _validate_move(
        self, stmt: MoveStatement, violations: list[MoveTypeViolation]
    ) -> None:
        """Check a single MOVE statement for category mismatches."""
        if stmt.is_corresponding:
            self._validate_corresponding(stmt, violations)
            return

        source_name = (stmt.source or "").strip()
        if not source_name:
            return

        source_cat = self._resolve_category(source_name)
        figurative = (
            source_name.upper().strip()
            if source_cat == DataCategory.FIGURATIVE
            else None
        )
        if source_cat == DataCategory.UNKNOWN or (
            figurative is not None
            and figurative not in _FIGURATIVE_ZERO
            and figurative not in _FIGURATIVE_FILL
        ):
            # Cannot determine source category statically -- either an
            # undeclared identifier, or a figurative constant with no fixed
            # rule here (NULL/NULLS). Every target of this MOVE goes
            # unchecked as a result, so count the statement once rather than
            # the number of targets.
            self._unresolved_count += 1
            function = _function_source(source_name)
            if function is not None and self._function_has_no_category(function):
                self._unresolved_function_count += 1
            return

        loc = getattr(stmt, "location", None)
        integer_flag = (
            self._is_non_integer(source_name)
            if source_cat == DataCategory.NUMERIC
            else False
        )

        for target_name in stmt.targets or []:
            target_name = target_name.strip()
            if not target_name:
                continue
            target_cat = self._resolve_category(target_name)
            if target_cat == DataCategory.UNKNOWN:
                self._unresolved_count += 1
                continue  # Cannot validate unknown target
            self._check_pair(
                source_name,
                source_cat,
                integer_flag,
                figurative,
                target_name,
                target_cat,
                self._is_group(target_name),
                loc,
                violations,
            )

    def _validate_corresponding(
        self, stmt: MoveStatement, violations: list[MoveTypeViolation]
    ) -> None:
        """Check ``MOVE CORRESPONDING`` as the elementary MOVEs it stands for.

        Subordinates of the two groups with the same name path pair up when
        at least one of the two is elementary (two groups of one name are not
        a pair; their own subordinates may be), and each pair is checked like
        an ordinary MOVE. A group operand that does not resolve to exactly
        one declared group leaves its pairs unknown, so the receiving
        operand is counted as unresolved rather than passed as clean.
        """
        source_ref = (stmt.source or "").strip()
        if not source_ref:
            return
        source = self._resolve_group_item(source_ref)
        loc = getattr(stmt, "location", None)
        for target_ref in stmt.targets or []:
            target_ref = target_ref.strip()
            if not target_ref:
                continue
            target = self._resolve_group_item(target_ref)
            if source is None or target is None:
                self._unresolved_count += 1
                continue
            target_paths = _corresponding_paths(target)
            for path, source_item in sorted(_corresponding_paths(source).items()):
                target_item = target_paths.get(path)
                if target_item is None:
                    continue
                source_entry = _item_entry(source_item)
                target_entry = _item_entry(target_item)
                if source_entry is None or target_entry is None:
                    self._unresolved_count += 1
                    continue
                if source_entry[2] and target_entry[2]:
                    continue  # two groups: their subordinates pair instead
                if DataCategory.UNKNOWN in (source_entry[0], target_entry[0]):
                    # No rule applies to a category not modelled here (e.g.
                    # PIC N): count the pair unchecked, as a plain MOVE does.
                    self._unresolved_count += 1
                    continue
                suffix = " OF ".join(reversed(path))
                self._check_pair(
                    f"{suffix} OF {source_ref}",
                    source_entry[0],
                    source_entry[1],
                    None,
                    f"{suffix} OF {target_ref}",
                    target_entry[0],
                    target_entry[2],
                    loc,
                    violations,
                )

    def _resolve_group_item(self, ref: str) -> CobolDataItem | None:
        """The one group item a (possibly qualified) reference names."""
        candidates = self._items.get(_reference_name(ref).upper(), [])
        qualifiers = {q.upper() for q in _QUALIFIER_RE.findall(ref)}
        matches = [item for ancestors, item in candidates if qualifiers <= ancestors]
        if len(matches) != 1:
            return None
        entry = _item_entry(matches[0])
        return matches[0] if entry is not None and entry[2] else None

    def _check_pair(
        self,
        source_name: str,
        source_cat: DataCategory,
        integer_flag: bool | None,
        figurative: str | None,
        target_name: str,
        target_cat: DataCategory,
        target_is_group: bool,
        loc: SourceLocation | None,
        violations: list[MoveTypeViolation],
    ) -> None:
        """Check one sending item against one resolved receiving item."""
        if target_is_group:
            return  # A group move is legal from any sending item
        source_non_integer = integer_flag is True

        if figurative is not None:
            if figurative in _FIGURATIVE_ZERO and target_cat == DataCategory.ALPHABETIC:
                # ZERO is numeric, and a numeric value has no place in
                # an alphabetic item (letters and spaces only).
                violations.append(
                    MoveTypeViolation(
                        kind=MoveViolationKind.ERROR,
                        source_name=source_name,
                        target_name=target_name,
                        source_category=source_cat,
                        target_category=target_cat,
                        location=loc,
                        message=(
                            f"Illegal MOVE: figurative constant '{source_name}' "
                            f"is numeric and cannot be moved to ALPHABETIC "
                            f"item '{target_name}'"
                        ),
                    )
                )
                return
            # ZERO has a digit value and is legal everywhere else; a fill
            # constant (SPACES, HIGH-VALUE, ...) is legal into anything
            # but a numeric/numeric-edited receiver, which has no room
            # for it.
            if (
                figurative in _FIGURATIVE_FILL
                and target_cat in _FIGURATIVE_FILL_ILLEGAL_TARGETS
            ):
                violations.append(
                    MoveTypeViolation(
                        kind=MoveViolationKind.ERROR,
                        source_name=source_name,
                        target_name=target_name,
                        source_category=source_cat,
                        target_category=target_cat,
                        location=loc,
                        message=(
                            f"Illegal MOVE: figurative constant '{source_name}' "
                            f"has no digit value and cannot be moved to "
                            f"{target_cat.name} item '{target_name}'"
                        ),
                    )
                )
            return

        pair = (source_cat, target_cat)
        if pair in _ILLEGAL_MOVES:
            violations.append(
                MoveTypeViolation(
                    kind=MoveViolationKind.ERROR,
                    source_name=source_name,
                    target_name=target_name,
                    source_category=source_cat,
                    target_category=target_cat,
                    location=loc,
                    message=(
                        f"Illegal MOVE: cannot move {source_cat.name} item "
                        f"'{source_name}' to {target_cat.name} item '{target_name}'"
                    ),
                )
            )
        elif (
            integer_flag is None and target_cat in _NON_INTEGER_NUMERIC_ILLEGAL_TARGETS
        ):
            # A numeric FUNCTION result (NUMVAL, MEAN, ...) is legal here
            # only if it is an integer, which the source cannot tell us.
            self._unresolved_count += 1
            self._unresolved_function_count += 1
        elif source_non_integer and target_cat in _NON_INTEGER_NUMERIC_ILLEGAL_TARGETS:
            violations.append(
                MoveTypeViolation(
                    kind=MoveViolationKind.ERROR,
                    source_name=source_name,
                    target_name=target_name,
                    source_category=source_cat,
                    target_category=target_cat,
                    location=loc,
                    message=(
                        f"Illegal MOVE: cannot move non-integer NUMERIC item "
                        f"'{source_name}' to {target_cat.name} item "
                        f"'{target_name}' (only an integer may be moved to "
                        "an alphanumeric or alphanumeric-edited item)"
                    ),
                )
            )
        elif pair in _WARN_MOVES:
            violations.append(
                MoveTypeViolation(
                    kind=MoveViolationKind.WARNING,
                    source_name=source_name,
                    target_name=target_name,
                    source_category=source_cat,
                    target_category=target_cat,
                    location=loc,
                    message=(
                        f"Suspicious MOVE: moving {source_cat.name} item "
                        f"'{source_name}' to {target_cat.name} item "
                        f"'{target_name}' may lose data or cause runtime error"
                    ),
                )
            )

    def _resolve_category(self, name: str) -> DataCategory:
        """Look up a data item name in the catalog, falling back to literal classification.

        A qualified/subscripted reference string ("WS-NUM OF GRP-1",
        "WS-TAB ( 3 )") is looked up by its base data name -- the catalog is
        keyed by bare item names, so the folded reference would otherwise
        miss every entry and silently classify as a literal.

        Special registers (RETURN-CODE and friends) and a handful of
        intrinsic FUNCTION results have a category fixed by the COBOL
        standard itself -- neither ever shows up as a CobolDataItem with a
        PICTURE clause, so the catalog built from the DATA DIVISION can never
        resolve them on its own.
        """
        function = _function_source(name)
        if function is not None:
            return self._resolve_function(function)[0]
        upper = _reference_name(name).upper()
        qualified = None if upper in self._catalog else self._qualified_entry(name)
        if upper in self._catalog or qualified is not None:
            if _is_reference_modified(name):
                return DataCategory.ALPHANUMERIC
            if qualified is not None:
                return qualified[0]
            return self._catalog[upper]
        if upper in self._declarations:
            return DataCategory.UNKNOWN  # ambiguous without its qualifiers
        if upper in _NUMERIC_SPECIAL_REGISTERS:
            return DataCategory.NUMERIC
        return _classify_literal(name)

    def _resolve_function(
        self, function: _FunctionSource
    ) -> tuple[DataCategory, bool | None]:
        """The category of an intrinsic FUNCTION result, and whether it is a
        non-integer (``None`` when that is not known at compile time).

        The return category comes from the intrinsic catalog in
        ``dialects.le_signatures``; TRIM / ABS / MAX / MIN / USUBSTR take
        the class of their argument(s), so the first argument is resolved
        instead. A reference-modified result is alphanumeric whatever the
        function returns. UNKNOWN for a NATIONAL result (not modelled here),
        a name the catalog does not list, or an argument that does not
        resolve. SUM / REM / RANGE / MAX / MIN / ABS take their integer-ness
        from their arguments the same way: a non-integer argument makes a
        non-integer result, all-integer arguments an integer one. Any other
        numeric function's integer-ness is unknown.
        """
        if function.reference_modified:
            return DataCategory.ALPHANUMERIC, False
        signature = intrinsic_signature(function.name)
        if signature is None:
            return DataCategory.UNKNOWN, False
        if function.name in _ARGUMENT_CLASS_ALPHANUMERIC:
            if not function.arguments or self._resolve_category(
                function.arguments[0]
            ) in (DataCategory.UNKNOWN, DataCategory.FIGURATIVE):
                return DataCategory.UNKNOWN, False
            return DataCategory.ALPHANUMERIC, False
        if function.name in _INTEGER_WHEN_ARGUMENTS_ARE and all(
            self._resolve_category(argument) == DataCategory.NUMERIC
            for argument in function.arguments
        ):
            return DataCategory.NUMERIC, self._arguments_non_integer(function)
        if signature.returns in _INTRINSIC_RETURN_CATEGORIES:
            return _INTRINSIC_RETURN_CATEGORIES[signature.returns]
        if signature.returns in _ARGUMENT_CLASS_RETURNS and function.arguments:
            category = self._resolve_category(function.arguments[0])
            if category in (DataCategory.UNKNOWN, DataCategory.FIGURATIVE):
                return DataCategory.UNKNOWN, False
            if category != DataCategory.NUMERIC:
                return category, False
            return category, self._arguments_non_integer(function)
        return DataCategory.UNKNOWN, False

    def _arguments_non_integer(self, function: _FunctionSource) -> bool | None:
        """Integer-ness of a result derived from numeric arguments: True if
        any argument is a non-integer, False if every one is an integer,
        ``None`` when an argument's integer-ness is itself unknown."""
        if not function.arguments:
            return None
        flags = [self._is_non_integer(argument) for argument in function.arguments]
        if any(flag is True for flag in flags):
            return True
        return None if None in flags else False

    def _is_declared_without_category(self, name: str) -> bool:
        """Whether *name* is a DATA DIVISION item this checker has no
        category for (a PIC N / national item): declared, so no copybook is
        missing."""
        upper = _reference_name(name).upper()
        if upper in self._catalog:
            return self._catalog[upper] == DataCategory.UNKNOWN
        qualified = self._qualified_entry(name)
        return qualified is not None and qualified[0] == DataCategory.UNKNOWN

    def _function_has_no_category(self, function: _FunctionSource) -> bool:
        """Whether an intrinsic result is UNKNOWN because of the function
        itself (a NATIONAL result, an uncatalogued name) rather than an
        argument a copybook might have declared. A function that returns its
        argument's class has a national result when that argument is a
        declared national item."""
        if function.reference_modified:
            return False
        signature = intrinsic_signature(function.name)
        if signature is None:
            return True
        if (
            function.name in _ARGUMENT_CLASS_ALPHANUMERIC
            or signature.returns in _ARGUMENT_CLASS_RETURNS
        ):
            return not function.arguments or self._is_declared_without_category(
                function.arguments[0]
            )
        return signature.returns not in _INTRINSIC_RETURN_CATEGORIES

    def _is_non_integer(self, name: str) -> bool | None:
        """Whether a NUMERIC source is a non-integer: a catalogued item with
        decimal digits / leading P scaling / floating-point usage, or a
        numeric literal with a decimal point. ``None`` for a numeric
        FUNCTION result whose integer-ness is not known at compile time."""
        function = _function_source(name)
        if function is not None:
            return self._resolve_function(function)[1]
        upper = _reference_name(name).upper()
        if upper in self._catalog:
            return upper in self._non_integer
        qualified = self._qualified_entry(name)
        if qualified is not None:
            return qualified[1]
        return "." in name.strip()

    def _is_group(self, name: str) -> bool:
        upper = _reference_name(name).upper()
        if upper in self._catalog:
            return upper in self._groups
        qualified = self._qualified_entry(name)
        return qualified is not None and qualified[2]

    def get_catalog(self) -> dict[str, str]:
        """Return the data item category catalog (name → category name).

        Useful for debugging or displaying type information.
        """
        return {k: v.name for k, v in self._catalog.items()}
