"""
LINKAGE SECTION ↔ CALL / ENTRY parameter correlation analysis.

For programs parsed within the same source unit (nested programs, multi-program
sources), this module cross-references:

  1. ENTRY statements in the PROCEDURE DIVISION — their USING parameter lists
     define the expected calling interface.
  2. CALL statements that target those entry names — their USING parameter
     lists are compared against the declared interface.
  3. The LINKAGE SECTION of the DATA DIVISION — 01-level items should correspond
     to the declared parameters of at least one ENTRY or the implicit PROCEDURE
     DIVISION USING clause.

Detected issues:
  - CALL has more arguments than the matching ENTRY / PROCEDURE DIVISION USING
  - CALL has fewer arguments than declared (missing required args)
  - Argument passed BY VALUE to a LINKAGE item (must be BY REFERENCE)
  - LINKAGE SECTION 01-items not referenced by any ENTRY or CALL
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements import CallStatement, EntryStatement


class LinkageViolationKind(Enum):
    """Types of LINKAGE / CALL parameter mismatches."""

    TOO_MANY_ARGS = auto()  # CALL passes more args than declared
    TOO_FEW_ARGS = auto()  # CALL passes fewer args than declared
    VALUE_TO_LINKAGE = auto()  # BY VALUE passed to a LINKAGE item
    UNREFERENCED_LINKAGE = auto()  # 01-item in LINKAGE not used by any ENTRY/CALL
    UNKNOWN_ENTRY = auto()  # CALL targets an entry not found in this program


@dataclass
class LinkageViolation:
    """A single LINKAGE / CALL correlation issue."""

    kind: LinkageViolationKind
    call_target: str | None
    location: SourceLocation | None
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "call_target": self.call_target,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location
                else None
            ),
            "message": self.message,
        }


@dataclass
class LinkageReport:
    """Result of a LINKAGE / CALL correlation analysis."""

    violations: list[LinkageViolation] = field(default_factory=list)
    # Map of entry_name → list of declared parameter names
    entry_interfaces: dict[str, list[str]] = field(default_factory=dict)
    # Names of 01-level LINKAGE items
    linkage_items: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict:
        return {
            "has_violations": self.has_violations,
            "violation_count": len(self.violations),
            "entry_interfaces": self.entry_interfaces,
            "linkage_items": self.linkage_items,
            "violations": [v.to_dict() for v in self.violations],
        }


class LinkageChecker:
    """Correlates CALL arguments with ENTRY/LINKAGE declarations.

    This checker operates within a single parsed program unit.  When a CALL
    target matches an ENTRY statement defined inside the same program, the
    argument count is validated.  Additionally, all 01-level LINKAGE SECTION
    items are checked for use.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import LinkageChecker

        result = parse_cobol(source)
        checker = LinkageChecker()
        report = checker.check(result.ast)
        for v in report.violations:
            print(v.message)
    """

    def __init__(self) -> None:
        # entry_name (upper) → list of parameter names from ENTRY USING
        self._entry_interfaces: dict[str, list[str]] = {}
        # 01-level linkage items: name (upper) → bool referenced
        self._linkage_items: dict[str, bool] = {}
        self._violations: list[LinkageViolation] = []

    def check(self, ast: CobolProgram) -> LinkageReport:
        """Analyze *ast* and return a LinkageReport.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            LinkageReport with all detected violations.
        """
        self._entry_interfaces = {}
        self._linkage_items = {}
        self._violations = []

        # 1. Collect LINKAGE SECTION 01-level items
        self._collect_linkage_items(ast)

        # 2. Collect PROCEDURE DIVISION USING clause (implicit ENTRY)
        self._collect_procedure_using(ast)

        # 3. Collect all ENTRY statements from PROCEDURE DIVISION
        self._collect_entry_statements(ast)

        # 4. Validate all CALL statements
        self._validate_call_statements(ast)

        # 5. Warn on unreferenced LINKAGE items
        self._check_unreferenced_linkage()

        return LinkageReport(
            violations=list(self._violations),
            entry_interfaces={k: list(v) for k, v in self._entry_interfaces.items()},
            linkage_items=sorted(self._linkage_items.keys()),
        )

    # ------------------------------------------------------------------
    # Collection passes
    # ------------------------------------------------------------------

    def _collect_linkage_items(self, ast: CobolProgram) -> None:
        """Find all 01-level items in the LINKAGE SECTION."""
        data_div = ast.data_division
        if not data_div:
            return

        # Look for a section named LINKAGE (use public .sections property)
        for section in data_div.sections:
            section_name = section.section_name or ""
            if "LINKAGE" in section_name.upper():
                for item in section.data_items:
                    if isinstance(item, CobolDataItem) and item.level == 1:
                        name = (item.name or "").upper().strip()
                        if name:
                            self._linkage_items[name] = False  # not yet referenced

    def _collect_procedure_using(self, ast: CobolProgram) -> None:
        """Collect parameters from PROCEDURE DIVISION USING clause."""
        proc_div = ast.procedure_division
        if not proc_div:
            return

        # The parser stores PROCEDURE DIVISION USING params in metadata
        using_params = proc_div.get_metadata("using_parameters") or []
        if using_params:
            # Use the program name as key for the implicit entry interface
            prog_name = (ast.program_name or "PROGRAM").upper()
            self._entry_interfaces[prog_name] = [
                p if isinstance(p, str) else str(p) for p in using_params
            ]
            # Mark them as referenced
            for p in using_params:
                pname = (p if isinstance(p, str) else str(p)).upper()
                if pname in self._linkage_items:
                    self._linkage_items[pname] = True

    def _collect_entry_statements(self, ast: ASTNode) -> None:
        """Recursively collect ENTRY statements and their USING clauses."""
        if isinstance(ast, EntryStatement):
            entry_name = (ast.entry_name or "").upper().strip()
            if entry_name:
                params = [p.upper() for p in (ast.using_parameters or [])]
                self._entry_interfaces[entry_name] = params
                # Mark LINKAGE items as referenced
                for p in params:
                    if p in self._linkage_items:
                        self._linkage_items[p] = True

        if hasattr(ast, "children"):
            for child in ast.children:
                self._collect_entry_statements(child)

    # ------------------------------------------------------------------
    # Validation pass
    # ------------------------------------------------------------------

    def _validate_call_statements(self, node: ASTNode) -> None:
        """Recursively find and validate CALL statements."""
        if isinstance(node, CallStatement):
            self._validate_call(node)

        if hasattr(node, "children"):
            for child in node.children:
                self._validate_call_statements(child)

    def _validate_call(self, stmt: CallStatement) -> None:
        """Validate a single CALL statement against the known entry interfaces."""
        target = (stmt.called_program or "").upper().strip()
        if not target or stmt.is_dynamic:
            return  # Cannot validate dynamic calls statically

        # Only validate if the target is an entry we know about
        if target not in self._entry_interfaces:
            # We don't have the target's source — skip (not a violation for external calls)
            return

        declared_params = self._entry_interfaces[target]
        call_params = stmt.using_parameters or []
        loc = getattr(stmt, "location", None)

        declared_count = len(declared_params)
        call_count = len(call_params)

        if call_count > declared_count:
            self._violations.append(
                LinkageViolation(
                    kind=LinkageViolationKind.TOO_MANY_ARGS,
                    call_target=target,
                    location=loc,
                    message=(
                        f"CALL '{target}' passes {call_count} argument(s) but "
                        f"entry declares {declared_count}"
                    ),
                )
            )
        elif call_count < declared_count:
            self._violations.append(
                LinkageViolation(
                    kind=LinkageViolationKind.TOO_FEW_ARGS,
                    call_target=target,
                    location=loc,
                    message=(
                        f"CALL '{target}' passes {call_count} argument(s) but "
                        f"entry declares {declared_count}"
                    ),
                )
            )

        # Check BY VALUE against LINKAGE items (LINKAGE items must be BY REFERENCE)
        for i, param in enumerate(call_params):
            if param.passing_mode.upper() == "VALUE":
                param_name = param.name.upper()
                if param_name in self._linkage_items:
                    self._violations.append(
                        LinkageViolation(
                            kind=LinkageViolationKind.VALUE_TO_LINKAGE,
                            call_target=target,
                            location=loc,
                            message=(
                                f"CALL '{target}' passes LINKAGE item '{param.name}' "
                                f"BY VALUE (arg {i + 1}); LINKAGE items must be "
                                "passed BY REFERENCE"
                            ),
                        )
                    )

        # Mark matching LINKAGE items as referenced
        for param in call_params:
            pname = param.name.upper()
            if pname in self._linkage_items:
                self._linkage_items[pname] = True

    # ------------------------------------------------------------------
    # Unreferenced linkage check
    # ------------------------------------------------------------------

    def _check_unreferenced_linkage(self) -> None:
        """Emit a violation for every 01-level LINKAGE item not referenced."""
        for name, referenced in self._linkage_items.items():
            if not referenced:
                self._violations.append(
                    LinkageViolation(
                        kind=LinkageViolationKind.UNREFERENCED_LINKAGE,
                        call_target=None,
                        location=None,
                        message=(
                            f"LINKAGE SECTION item '{name}' is declared but never "
                            "referenced by any ENTRY or CALL USING clause"
                        ),
                    )
                )
