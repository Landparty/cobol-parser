"""
File I/O sequencing validation for COBOL programs.

Walks the AST in execution order and reports violations of the required
OPEN → {READ/WRITE/REWRITE/DELETE/START} → CLOSE lifecycle for each file.

Common bugs caught:
- READ/WRITE/REWRITE/DELETE/START against a file that was never OPENed
- OPEN of a file that is already open (double-open)
- CLOSE of a file that was never opened or already closed
- Files left open at program exit (STOP RUN / GOBACK)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.ast_base import ASTNode, SourceLocation
from ..models.program import CobolProgram
from ..models.statements import (
    GobackStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
    StopStatement,
)


class IOViolationKind(Enum):
    """Categories of file I/O sequencing violations."""

    READ_BEFORE_OPEN = auto()
    WRITE_BEFORE_OPEN = auto()
    REWRITE_BEFORE_OPEN = auto()
    DELETE_BEFORE_OPEN = auto()
    START_BEFORE_OPEN = auto()
    DOUBLE_OPEN = auto()
    CLOSE_NOT_OPEN = auto()
    DOUBLE_CLOSE = auto()
    FILE_LEFT_OPEN = auto()  # open at STOP RUN / GOBACK / end-of-program


@dataclass
class IOSequenceViolation:
    """A single file I/O sequencing violation."""

    kind: IOViolationKind
    file_name: str
    location: SourceLocation | None
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "file_name": self.file_name,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location
                else None
            ),
            "message": self.message,
        }


@dataclass
class IOSequenceReport:
    """Result of an I/O sequencing analysis."""

    violations: list[IOSequenceViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict:
        return {
            "has_violations": self.has_violations,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
        }


# Maps verb-to-ViolationKind for unopened-file errors
_OP_TO_VIOLATION: dict[str, IOViolationKind] = {
    "READ": IOViolationKind.READ_BEFORE_OPEN,
    "WRITE": IOViolationKind.WRITE_BEFORE_OPEN,
    "REWRITE": IOViolationKind.REWRITE_BEFORE_OPEN,
    "DELETE": IOViolationKind.DELETE_BEFORE_OPEN,
    "START": IOViolationKind.START_BEFORE_OPEN,
}


class IOSequenceAnalyzer:
    """Analyzes a parsed COBOL AST for file I/O sequencing violations.

    The analyzer walks all statements in program order, maintaining a set of
    currently-open files.  It emits a violation for each rule broken.

    Note: this is a conservative static analysis.  Dynamic file names (variables)
    are tracked by their variable name string as-is.  Conditional branches are
    *not* forked — both paths share state — so the report may contain false
    positives in heavily branched code.  It will not produce false negatives for
    straight-line programs.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import IOSequenceAnalyzer

        result = parse_cobol(source)
        analyzer = IOSequenceAnalyzer()
        report = analyzer.analyze(result.ast)
        for v in report.violations:
            print(v.message)
    """

    def __init__(self) -> None:
        self._open_files: set[str] = set()
        self._closed_files: set[str] = set()
        self._violations: list[IOSequenceViolation] = []

    def analyze(self, ast: CobolProgram) -> IOSequenceReport:
        """Analyze the AST and return an IOSequenceReport.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            IOSequenceReport containing all detected violations.
        """
        self._open_files = set()
        self._closed_files = set()
        self._violations = []
        self._walk(ast)
        # Any files still open at end-of-program are violations
        for file_name in sorted(self._open_files):
            self._violations.append(
                IOSequenceViolation(
                    kind=IOViolationKind.FILE_LEFT_OPEN,
                    file_name=file_name,
                    location=None,
                    message=(
                        f"File '{file_name}' is still open at end of program "
                        "(missing CLOSE statement)"
                    ),
                )
            )
        return IOSequenceReport(violations=list(self._violations))

    # ------------------------------------------------------------------
    # Internal traversal
    # ------------------------------------------------------------------

    def _walk(self, node: ASTNode) -> None:
        """Recursively walk the AST, handling IO statements."""
        self._dispatch(node)
        if hasattr(node, "children"):
            for child in node.children:
                self._walk(child)

    def _dispatch(self, node: ASTNode) -> None:
        """Handle a single node if it is an IO-relevant statement."""
        loc = getattr(node, "location", None)

        if isinstance(node, IOOpenStatement):
            self._handle_open(node, loc)
        elif isinstance(node, IOCloseStatement):
            self._handle_close(node, loc)
        elif isinstance(node, IOReadStatement):
            self._check_open(node.file_name or "", "READ", loc)
        elif isinstance(node, IOWriteStatement):
            # WRITE uses the record name; file_name may be absent
            name = node.file_name or node.record_name or ""
            self._check_open(name, "WRITE", loc)
        elif isinstance(node, IORewriteStatement):
            name = node.file_name or node.record_name or ""
            self._check_open(name, "REWRITE", loc)
        elif isinstance(node, IODeleteStatement):
            self._check_open(node.file_name or "", "DELETE", loc)
        elif isinstance(node, IOStartStatement):
            self._check_open(node.file_name or "", "START", loc)
        elif isinstance(node, (StopStatement, GobackStatement)):
            # Treat as end-of-program for leak detection (violations added later
            # by analyze() for remaining open files, but we clear here so
            # subsequent statements don't also trigger them)
            for file_name in sorted(self._open_files):
                self._violations.append(
                    IOSequenceViolation(
                        kind=IOViolationKind.FILE_LEFT_OPEN,
                        file_name=file_name,
                        location=loc,
                        message=(
                            f"File '{file_name}' is still open when program "
                            "terminates (STOP RUN / GOBACK)"
                        ),
                    )
                )
            self._open_files.clear()
            self._closed_files.clear()

    def _handle_open(self, node: IOOpenStatement, loc: SourceLocation | None) -> None:
        """Process an OPEN statement."""
        files = self._get_open_files(node)
        for file_name in files:
            if not file_name.strip():
                continue  # Skip empty/whitespace names
            key = file_name.upper()
            if key in self._open_files:
                self._violations.append(
                    IOSequenceViolation(
                        kind=IOViolationKind.DOUBLE_OPEN,
                        file_name=file_name,
                        location=loc,
                        message=f"File '{file_name}' is already open (duplicate OPEN)",
                    )
                )
            else:
                self._closed_files.discard(key)  # Allow reopen after close
                self._open_files.add(key)

    def _handle_close(self, node: IOCloseStatement, loc: SourceLocation | None) -> None:
        """Process a CLOSE statement."""
        files = self._get_close_files(node)
        for file_name in files:
            if not file_name.strip():
                continue  # Skip empty/whitespace names
            key = file_name.upper()
            if key in self._open_files:
                self._open_files.discard(key)
                self._closed_files.add(key)
            elif key in self._closed_files:
                self._violations.append(
                    IOSequenceViolation(
                        kind=IOViolationKind.DOUBLE_CLOSE,
                        file_name=file_name,
                        location=loc,
                        message=f"CLOSE of file '{file_name}' that is already closed (duplicate CLOSE)",
                    )
                )
            else:
                self._violations.append(
                    IOSequenceViolation(
                        kind=IOViolationKind.CLOSE_NOT_OPEN,
                        file_name=file_name,
                        location=loc,
                        message=(f"CLOSE of file '{file_name}' that was never opened"),
                    )
                )

    def _check_open(
        self, file_name: str, verb: str, loc: SourceLocation | None
    ) -> None:
        """Emit a violation if *file_name* is not currently open."""
        if not file_name:
            return  # Cannot determine file name statically
        key = file_name.upper()
        if key not in self._open_files:
            kind = _OP_TO_VIOLATION.get(verb, IOViolationKind.READ_BEFORE_OPEN)
            self._violations.append(
                IOSequenceViolation(
                    kind=kind,
                    file_name=file_name,
                    location=loc,
                    message=(f"{verb} on file '{file_name}' before it was OPENed"),
                )
            )

    # ------------------------------------------------------------------
    # Helpers to extract file names from IO nodes
    # ------------------------------------------------------------------

    @staticmethod
    def _get_open_files(node: IOOpenStatement) -> list[str]:
        """Return the list of file names in an OPEN statement.

        IOOpenStatement uses ``file_names`` (a list) populated via add_file().
        We fall back to the legacy ``open_files`` attribute and finally to
        ``operands`` for forward-compatibility.
        """
        names: list[str] = []
        # Primary path: IOOpenStatement.file_names (list[str])
        if hasattr(node, "file_names") and node.file_names:
            names.extend(node.file_names)
            return names
        # Legacy / alternative path: open_files (list of str or dict)
        if hasattr(node, "open_files") and node.open_files:
            for entry in node.open_files:
                if isinstance(entry, dict):
                    name = entry.get("file_name") or entry.get("name") or ""
                    if name:
                        names.append(str(name))
                elif isinstance(entry, str):
                    names.append(entry)
            if names:
                return names
        # Singular file_name attribute
        if hasattr(node, "file_name") and node.file_name:
            names.append(node.file_name)
            return names
        # Last resort: operands list
        if hasattr(node, "operands"):
            names.extend(node.operands)
        return names

    @staticmethod
    def _get_close_files(node: IOCloseStatement) -> list[str]:
        """Return the list of file names in a CLOSE statement."""
        names: list[str] = []
        if hasattr(node, "file_names") and node.file_names:
            names.extend(node.file_names)
        elif hasattr(node, "file_name") and node.file_name:
            names.append(node.file_name)
        if not names and hasattr(node, "operands"):
            names.extend(node.operands)
        return names
