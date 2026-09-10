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
  - LINKAGE SECTION 01-items not referenced by any ENTRY or CALL

Passing a LINKAGE item ``BY VALUE`` is deliberately *not* an issue: COBOL has
no such rule. ``BY VALUE`` is what a caller must write when the callee
declares ``PROCEDURE DIVISION USING BY VALUE``, and the item's own section is
irrelevant to that (a former ``VALUE_TO_LINKAGE`` rule flagged exactly that
legal call as an error).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements import CallStatement, EntryStatement


class LinkageViolationKind(Enum):
    """Types of LINKAGE / CALL parameter mismatches."""

    TOO_MANY_ARGS = auto()  # CALL passes more args than declared
    TOO_FEW_ARGS = auto()  # CALL passes fewer args than declared
    UNREFERENCED_LINKAGE = auto()  # 01-item in LINKAGE not used by any ENTRY/CALL
    UNKNOWN_ENTRY = auto()  # CALL targets an entry not found in this program


@dataclass
class LinkageViolation:
    """A single LINKAGE / CALL correlation issue."""

    kind: LinkageViolationKind
    call_target: str | None
    location: SourceLocation | None
    message: str
    # The LINKAGE item an UNREFERENCED_LINKAGE finding is about (None for
    # the CALL-shaped kinds, which name their target in ``call_target``).
    item_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "call_target": self.call_target,
            "item_name": self.item_name,
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

    Every finding is scoped to one *program unit*: a unit's LINKAGE SECTION
    items are checked against that unit's own ``PROCEDURE DIVISION USING``,
    ``ENTRY`` and ``CALL ... USING`` clauses. By default every unit in *ast*
    (the program and each of its ``contained_programs``) is checked in turn;
    pass ``include_contained_programs=False`` to check just the unit given,
    which is what a caller already iterating ``program_units()`` wants
    (``LintAnalyzer``). Entry interfaces -- what each program or ENTRY
    declares -- are gathered from the whole tree regardless, so a CALL from
    one unit to a sibling or nested unit is validated against the right
    parameter list; ``interface_scope`` widens that to a tree the checked
    unit is part of but not the root of.

    Keeping the item bookkeeping per unit is what makes the report
    attributable: two units declaring a same-named LINKAGE item used to
    collapse into one location-less finding.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import LinkageChecker

        result = parse_cobol(source)
        checker = LinkageChecker()
        report = checker.check(result.ast)
        for v in report.violations:
            print(v.message)
    """

    def __init__(self, *, include_contained_programs: bool = True) -> None:
        self._include_contained_programs = include_contained_programs
        # entry_name (upper) → list of parameter names from ENTRY USING /
        # PROCEDURE DIVISION USING, across every unit in scope
        self._entry_interfaces: dict[str, list[str]] = {}
        # 01-level linkage items of the unit being checked:
        # name (upper) → referenced?  (plus where each was declared)
        self._linkage_items: dict[str, bool] = {}
        self._linkage_locations: dict[str, SourceLocation | None] = {}
        self._all_linkage_items: set[str] = set()
        self._violations: list[LinkageViolation] = []

    def check(
        self, ast: CobolProgram, *, interface_scope: CobolProgram | None = None
    ) -> LinkageReport:
        """Analyze *ast* and return a LinkageReport.

        Args:
            ast: The parsed COBOL program AST (a unit, or a whole file).
            interface_scope: The program tree whose declared entry
                interfaces CALLs in *ast* may target. Defaults to *ast*
                itself; a caller checking one contained unit at a time
                passes the outermost program so calls to sibling units
                still resolve.

        Returns:
            LinkageReport with all detected violations.
        """
        self._entry_interfaces = {}
        self._linkage_items = {}
        self._linkage_locations = {}
        self._all_linkage_items = set()
        self._violations = []

        scope = interface_scope if interface_scope is not None else ast
        for unit in scope.program_units():
            self._collect_interfaces(unit)

        units = ast.program_units() if self._include_contained_programs else [ast]
        for unit in units:
            self._check_unit(unit)

        return LinkageReport(
            violations=list(self._violations),
            entry_interfaces={k: list(v) for k, v in self._entry_interfaces.items()},
            linkage_items=sorted(self._all_linkage_items),
        )

    # ------------------------------------------------------------------
    # Interface collection (whole scope)
    # ------------------------------------------------------------------

    def _collect_interfaces(self, unit: CobolProgram) -> None:
        """Register *unit*'s PROCEDURE DIVISION USING and ENTRY interfaces."""
        proc_div = unit.procedure_division
        if proc_div:
            # The parser stores PROCEDURE DIVISION USING params in metadata
            using_params = proc_div.get_metadata("using_parameters") or []
            if using_params:
                # Use the program name as key for the implicit entry interface
                prog_name = (unit.program_name or "PROGRAM").upper()
                self._entry_interfaces[prog_name] = [
                    p if isinstance(p, str) else str(p) for p in using_params
                ]
        for node in self._own_nodes(unit):
            if isinstance(node, EntryStatement):
                entry_name = (node.entry_name or "").upper().strip()
                if entry_name:
                    self._entry_interfaces[entry_name] = [
                        p.upper() for p in (node.using_parameters or [])
                    ]

    @staticmethod
    def _own_nodes(unit: CobolProgram) -> list[ASTNode]:
        """Every node of *unit* except those belonging to a nested program.

        A contained program hangs off its parent as a child node, so a plain
        recursive walk of ``children`` would attribute its statements to the
        outer unit.
        """
        found: list[ASTNode] = []
        stack: list[ASTNode] = list(reversed(getattr(unit, "children", [])))
        while stack:
            node = stack.pop()
            if isinstance(node, CobolProgram):
                continue
            found.append(node)
            stack.extend(reversed(getattr(node, "children", [])))
        return found

    # ------------------------------------------------------------------
    # Per-unit check
    # ------------------------------------------------------------------

    def _check_unit(self, unit: CobolProgram) -> None:
        """Check one program unit's LINKAGE items and CALL statements."""
        self._linkage_items = {}
        self._linkage_locations = {}

        # 1. Collect this unit's LINKAGE SECTION 01-level items
        self._collect_linkage_items(unit)
        self._all_linkage_items.update(self._linkage_items)

        # 2. Its PROCEDURE DIVISION USING clause references them
        proc_div = unit.procedure_division
        if proc_div:
            for p in proc_div.get_metadata("using_parameters") or []:
                self._mark_referenced(p if isinstance(p, str) else str(p))

        # 3. So do its ENTRY USING clauses; its CALLs are validated
        for node in self._own_nodes(unit):
            if isinstance(node, EntryStatement):
                for p in node.using_parameters or []:
                    self._mark_referenced(p)
            elif isinstance(node, CallStatement):
                self._validate_call(node)

        # 4. Warn on unreferenced LINKAGE items
        self._check_unreferenced_linkage()

    def _collect_linkage_items(self, unit: CobolProgram) -> None:
        """Find all 01-level items in *unit*'s LINKAGE SECTION."""
        data_div = unit.data_division
        if not data_div:
            return
        # Look for a section named LINKAGE (use public .sections property)
        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            section_name = section.section_name or ""
            if "LINKAGE" in section_name.upper():
                for item in section.data_items:
                    if isinstance(item, CobolDataItem) and item.level == 1:
                        name = (item.name or "").upper().strip()
                        if name:
                            self._linkage_items[name] = False  # not yet referenced
                            self._linkage_locations[name] = getattr(
                                item, "location", None
                            )

    def _mark_referenced(self, name: str) -> None:
        key = name.upper()
        if key in self._linkage_items:
            self._linkage_items[key] = True

    # ------------------------------------------------------------------
    # Validation pass
    # ------------------------------------------------------------------

    def _validate_call(self, stmt: CallStatement) -> None:
        """Validate a single CALL statement against the known entry interfaces."""
        call_params = stmt.using_parameters or []
        # Passing a LINKAGE item on to a callee references it, whatever the
        # target and however it is passed.
        for param in call_params:
            self._mark_referenced(param.name)

        target = (stmt.called_program or "").upper().strip()
        if not target or stmt.is_dynamic:
            return  # Cannot validate dynamic calls statically

        # Only validate if the target is an entry we know about
        if target not in self._entry_interfaces:
            # We don't have the target's source — skip (not a violation for external calls)
            return

        declared_params = self._entry_interfaces[target]
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
                        location=self._linkage_locations.get(name),
                        message=(
                            f"LINKAGE SECTION item '{name}' is declared but never "
                            "referenced by any ENTRY or CALL USING clause"
                        ),
                        item_name=name,
                    )
                )
