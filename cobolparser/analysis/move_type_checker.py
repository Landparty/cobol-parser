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

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem, PictureClause
from ..models.program import CobolProgram
from ..models.statements import MoveStatement
from ._names import base_data_name


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

# Intrinsic FUNCTION results whose category is fixed by the COBOL standard
# regardless of context. Both are fixed-length timestamp strings, so a
# "MOVE FUNCTION ... TO ..." using one of these was always ALPHANUMERIC and
# never actually depended on an unresolved COPY.
_ALPHANUMERIC_INTRINSIC_FUNCTIONS = frozenset({"CURRENT-DATE", "WHEN-COMPILED"})

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
        # Numeric-edited: contains 9s alongside editing characters
        if "9" in pattern:
            return DataCategory.NUMERIC_EDITED
        # Alphanumeric-edited: X with editing chars
        if "X" in pattern or "A" in pattern:
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
        self._unresolved_count = 0

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
        self._unresolved_count = 0
        violations: list[MoveTypeViolation] = []

        # Phase 1: build catalog from DATA DIVISION
        self._build_catalog(ast)
        self._index_catalog()

        # Phase 2: check every MOVE statement
        self._check_moves(ast, violations)

        return MoveTypeReport(
            violations=violations, unresolved_count=self._unresolved_count
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
            entry: tuple[DataCategory, bool, bool] | None = None
            pic = node.picture_clause
            if name and pic is not None:
                category = _classify_picture(pic)
                entry = (
                    category,
                    category == DataCategory.NUMERIC
                    and (
                        _is_non_integer_picture(pic)
                        or _is_floating_point_usage(getattr(node, "usage", None))
                    ),
                    False,
                )
            elif name and _is_floating_point_usage(getattr(node, "usage", None)):
                # COMP-1/COMP-2 carry no PICTURE: numeric, non-integer.
                entry = (DataCategory.NUMERIC, True, False)
            elif name and any(
                isinstance(child, CobolDataItem)
                for child in getattr(node, "children", ())
            ):
                entry = (DataCategory.ALPHANUMERIC, False, True)
            if entry is not None:
                self._declarations.setdefault(name, []).append(
                    (frozenset(ancestors), entry)
                )
            if name:
                child_ancestors = (*ancestors, name)

        if hasattr(node, "children"):
            for child in node.children:
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
                self._check_moves(child, violations)

    def _validate_move(
        self, stmt: MoveStatement, violations: list[MoveTypeViolation]
    ) -> None:
        """Check a single MOVE statement for category mismatches."""
        # MOVE CORRESPONDING resolves sub-fields structurally; skip type-checking
        if stmt.is_corresponding:
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
            return

        loc = getattr(stmt, "location", None)
        source_non_integer = source_cat == DataCategory.NUMERIC and (
            self._is_non_integer(source_name)
        )

        for target_name in stmt.targets or []:
            target_name = target_name.strip()
            if not target_name:
                continue
            target_cat = self._resolve_category(target_name)
            if target_cat == DataCategory.UNKNOWN:
                self._unresolved_count += 1
                continue  # Cannot validate unknown target
            if self._is_group(target_name):
                continue  # A group move is legal from any sending item

            if figurative is not None:
                if (
                    figurative in _FIGURATIVE_ZERO
                    and target_cat == DataCategory.ALPHABETIC
                ):
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
                    continue
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
                continue

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
                source_non_integer
                and target_cat in _NON_INTEGER_NUMERIC_ILLEGAL_TARGETS
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
        if upper.startswith("FUNCTION "):
            function_name = upper[len("FUNCTION ") :].strip()
            if function_name in _ALPHANUMERIC_INTRINSIC_FUNCTIONS:
                return DataCategory.ALPHANUMERIC
        return _classify_literal(name)

    def _is_non_integer(self, name: str) -> bool:
        """Whether a NUMERIC source is a non-integer: a catalogued item with
        decimal digits / leading P scaling / floating-point usage, or a
        numeric literal with a decimal point."""
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
