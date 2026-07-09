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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem, PictureClause
from ..models.program import CobolProgram
from ..models.statements import MoveStatement


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
    #: DataCategory (e.g. an undeclared identifier, or an unexpanded
    #: copybook field) and were therefore skipped rather than checked. A
    #: report with zero violations and a non-zero unresolved_count means
    #: "nothing was found wrong" is not the same as "everything was
    #: checked" -- see reports/open-findings.md H5.
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
_PIC_ALPHA_ONLY_RE = re.compile(r"^(?:A+|A\(\d+\))$", re.IGNORECASE)
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

# Illegal MOVE combinations: (source_category, target_category)
_ILLEGAL_MOVES: frozenset[tuple[DataCategory, DataCategory]] = frozenset(
    {
        (DataCategory.NUMERIC, DataCategory.ALPHABETIC),
        (DataCategory.NUMERIC_EDITED, DataCategory.ALPHABETIC),
        (DataCategory.ALPHABETIC, DataCategory.NUMERIC),
        (DataCategory.ALPHABETIC, DataCategory.NUMERIC_EDITED),
    }
)

# Potentially problematic (warning-level) combinations
_WARN_MOVES: frozenset[tuple[DataCategory, DataCategory]] = frozenset(
    {
        (DataCategory.ALPHANUMERIC, DataCategory.NUMERIC),
        (DataCategory.ALPHANUMERIC, DataCategory.NUMERIC_EDITED),
        (DataCategory.ALPHANUMERIC_EDITED, DataCategory.NUMERIC),
        (DataCategory.NUMERIC_EDITED, DataCategory.NUMERIC),
    }
)


def _classify_picture(pic: PictureClause) -> DataCategory:
    """Determine the COBOL data category from a PictureClause node."""
    pattern = (pic.pattern or "").upper().strip()

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
        self._unresolved_count = 0

    def check(self, ast: CobolProgram) -> MoveTypeReport:
        """Analyze *ast* and return a MoveTypeReport.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            MoveTypeReport with all detected type violations.
        """
        self._catalog = {}
        self._unresolved_count = 0
        violations: list[MoveTypeViolation] = []

        # Phase 1: build catalog from DATA DIVISION
        self._build_catalog(ast)

        # Phase 2: check every MOVE statement
        self._check_moves(ast, violations)

        return MoveTypeReport(
            violations=violations, unresolved_count=self._unresolved_count
        )

    # ------------------------------------------------------------------
    # Catalog building
    # ------------------------------------------------------------------

    def _build_catalog(self, node: ASTNode) -> None:
        """Recursively collect PIC clauses from CobolDataItem nodes."""
        if isinstance(node, CobolDataItem):
            name = (node.name or "").upper().strip()
            pic = node.picture_clause
            if name and pic is not None:
                self._catalog[name] = _classify_picture(pic)

        if hasattr(node, "children"):
            for child in node.children:
                self._build_catalog(child)

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
        if source_cat in (DataCategory.UNKNOWN, DataCategory.FIGURATIVE):
            # Cannot determine source category statically -- every target of
            # this MOVE goes unchecked as a result, so count the statement
            # once rather than the number of targets.
            self._unresolved_count += 1
            return

        loc = getattr(stmt, "location", None)

        for target_name in stmt.targets or []:
            target_name = target_name.strip()
            if not target_name:
                continue
            target_cat = self._resolve_category(target_name)
            if target_cat == DataCategory.UNKNOWN:
                self._unresolved_count += 1
                continue  # Cannot validate unknown target

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
        """Look up a data item name in the catalog, falling back to literal classification."""
        upper = name.upper()
        if upper in self._catalog:
            return self._catalog[upper]
        return _classify_literal(name)

    def get_catalog(self) -> dict[str, str]:
        """Return the data item category catalog (name → category name).

        Useful for debugging or displaying type information.
        """
        return {k: v.name for k, v in self._catalog.items()}
