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
  - CALL passes an argument BY VALUE/BY REFERENCE that disagrees with the
    callee's own declared ``PROCEDURE DIVISION USING BY VALUE``/``BY
    REFERENCE`` for that (positional) parameter

Passing a LINKAGE item ``BY VALUE`` is deliberately *not*, on its own, an
issue: COBOL has no rule tying an item's own section to how it may be
passed. ``BY VALUE`` is what a caller must write when the callee declares
``PROCEDURE DIVISION USING BY VALUE``, and the item's own section is
irrelevant to that (a former ``VALUE_TO_LINKAGE`` rule flagged exactly that
legal call as an error). What *is* checked instead is the callee's actual
declared convention: ``PASSING_MODE_MISMATCH`` fires only when the CALL's
own BY VALUE/BY REFERENCE (explicit or COBOL's own BY REFERENCE default)
disagrees with what the callee's ``PROCEDURE DIVISION USING`` explicitly
declares for that position, resolvable only for a static CALL to a program
in this same source whose implicit entry interface was collected -- an
ENTRY statement's own USING phrase carries no BY VALUE/REFERENCE in COBOL,
so a CALL to one is never checked for this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements import (
    AllocateStatement,
    CallStatement,
    EntryStatement,
    SetStatement,
)
from ._cics import cics_identifier_options

#: LINKAGE items the CICS command-level translator itself passes on the
#: PROCEDURE DIVISION USING it generates; a source that declares them is a
#: CICS program and references them by construction.
_CICS_TRANSLATOR_ITEMS: frozenset[str] = frozenset({"DFHEIBLK", "DFHCOMMAREA"})

#: ``ADDRESS OF item`` as it appears in a CICS option (``SET(ADDRESS OF
#: WS-REC)``) -- the item is being based, which is a reference to it.
_ADDRESS_OF_RE = re.compile(r"^\s*ADDRESS\s+OF\s+([A-Za-z0-9-]+)", re.IGNORECASE)


def _bare_name(operand: str) -> str:
    """The data name of *operand* without a subscript or OF/IN qualifier."""
    text = operand.strip()
    for stop in ("(", " OF ", " IN "):
        cut = text.upper().find(stop)
        if cut >= 0:
            text = text[:cut]
    return text.strip()


#: ``ADDRESS OF`` / ``LENGTH OF`` in front of a CALL argument: the item
#: after it is still the one being referenced.
_SPECIAL_REGISTER_OF_RE = re.compile(r"^\s*(?:ADDRESS|LENGTH)\s+OF\s+", re.IGNORECASE)
_PARENTHESISED_RE = re.compile(r"\([^()]*\)")
_QUALIFIER_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)


def _argument_names(operand: str) -> list[str]:
    """Every data name a CALL argument references.

    ``LK-REC(1:4)``, ``LK-ITEM(IDX) OF LK-REC`` and ``ADDRESS OF LK-REC``
    all reference their data items; the parameter's recorded text carries
    the subscript / reference modifier / qualifier / special register, so
    matching it against a bare 01-level name as-is never succeeded.
    """
    text = _SPECIAL_REGISTER_OF_RE.sub("", operand)
    previous = None
    while previous != text:  # nested subscripts: LK-T(LK-IX(1))
        previous = text
        text = _PARENTHESISED_RE.sub(" ", text)
    return [part.strip() for part in _QUALIFIER_RE.split(text) if part.strip()]


class LinkageViolationKind(Enum):
    """Types of LINKAGE / CALL parameter mismatches."""

    TOO_MANY_ARGS = auto()  # CALL passes more args than declared
    TOO_FEW_ARGS = auto()  # CALL passes fewer args than declared
    UNREFERENCED_LINKAGE = auto()  # 01-item in LINKAGE not used by any ENTRY/CALL
    UNKNOWN_ENTRY = auto()  # CALL targets an entry not found in this program
    PASSING_MODE_MISMATCH = auto()  # CALL's BY VALUE/REFERENCE disagrees with USING


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
        # entry_name (upper) → {parameter name (upper): "VALUE" | "REFERENCE"},
        # populated only for the implicit PROCEDURE DIVISION USING entry --
        # an ENTRY statement's own USING phrase carries no BY VALUE/BY
        # REFERENCE in COBOL, so it is never a key here, and a mismatch is
        # never checked against it.
        self._entry_parameter_modes: dict[str, dict[str, str]] = {}
        # 01-level linkage items of the unit being checked:
        # name (upper) → referenced?  (plus where each was declared)
        self._linkage_items: dict[str, bool] = {}
        self._linkage_locations: dict[str, SourceLocation | None] = {}
        # subordinate item name (upper) → the 01-level item(s) holding it
        self._linkage_owners: dict[str, set[str]] = {}
        self._all_linkage_items: set[str] = set()
        self._violations: list[LinkageViolation] = []

    def check(
        self,
        ast: CobolProgram,
        *,
        interface_scope: CobolProgram | None = None,
        entry_interfaces: dict[str, list[str]] | None = None,
        entry_parameter_modes: dict[str, dict[str, str]] | None = None,
    ) -> LinkageReport:
        """Analyze *ast* and return a LinkageReport.

        Args:
            ast: The parsed COBOL program AST (a unit, or a whole file).
            interface_scope: The program tree whose declared entry
                interfaces CALLs in *ast* may target. Defaults to *ast*
                itself; a caller checking one contained unit at a time
                passes the outermost program so calls to sibling units
                still resolve. Ignored when *entry_interfaces* is given.
            entry_interfaces: A precomputed
                :meth:`collect_entry_interfaces` result, when the caller
                already has one for *interface_scope*. A caller checking
                every unit of the same file in turn (``LintAnalyzer``) would
                otherwise pay this scope-wide collection pass again on each
                unit's own ``check()`` call -- O(units²) instead of O(units)
                for a file with several ``PROGRAM-ID``s.
            entry_parameter_modes: A precomputed
                :meth:`collect_entry_parameter_modes` result, the passing-
                mode counterpart of *entry_interfaces* shared the same way.
                Omitting it while *entry_interfaces* is given simply means
                no ``PASSING_MODE_MISMATCH`` is ever reported for this call.

        Returns:
            LinkageReport with all detected violations.
        """
        self._linkage_items = {}
        self._linkage_locations = {}
        self._linkage_owners = {}
        self._all_linkage_items = set()
        self._violations = []

        if entry_interfaces is not None:
            self._entry_interfaces = {k: list(v) for k, v in entry_interfaces.items()}
            self._entry_parameter_modes = (
                {k: dict(v) for k, v in entry_parameter_modes.items()}
                if entry_parameter_modes is not None
                else {}
            )
        else:
            self._entry_interfaces = {}
            self._entry_parameter_modes = {}
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

    @staticmethod
    def _collect_scope(scope: CobolProgram) -> LinkageChecker:
        """One scope-wide interface-collection walk, as a throwaway
        collector a caller reads either or both result dicts off of."""
        collector = LinkageChecker()
        for unit in scope.program_units():
            collector._collect_interfaces(unit)
        return collector

    @staticmethod
    def collect_entry_interfaces(scope: CobolProgram) -> dict[str, list[str]]:
        """Every ENTRY / ``PROCEDURE DIVISION USING`` interface declared
        anywhere in *scope*, keyed by entry name (upper) -- the scope-wide
        half of :meth:`check`'s work, computable once and reused across
        every unit of *scope* via ``check(..., entry_interfaces=...)``."""
        collector = LinkageChecker._collect_scope(scope)
        return {k: list(v) for k, v in collector._entry_interfaces.items()}

    @staticmethod
    def collect_entry_parameter_modes(scope: CobolProgram) -> dict[str, dict[str, str]]:
        """The BY VALUE/BY REFERENCE passing mode declared for each
        parameter of *scope*'s implicit ``PROCEDURE DIVISION USING``
        entries, keyed the same way as :meth:`collect_entry_interfaces` --
        its passing-mode counterpart, for sharing across a caller's own
        per-unit ``check()`` calls the same way."""
        collector = LinkageChecker._collect_scope(scope)
        return {k: dict(v) for k, v in collector._entry_parameter_modes.items()}

    @staticmethod
    def collect_scope_interfaces(
        scope: CobolProgram,
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
        """``(collect_entry_interfaces(scope), collect_entry_parameter_modes
        (scope))`` from a single scope walk -- what a caller needing both
        (``LintAnalyzer``) should call instead of calling each separately
        and walking every unit of *scope* twice."""
        collector = LinkageChecker._collect_scope(scope)
        return (
            {k: list(v) for k, v in collector._entry_interfaces.items()},
            {k: dict(v) for k, v in collector._entry_parameter_modes.items()},
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
                using_modes = proc_div.get_metadata("using_parameter_modes") or {}
                self._entry_parameter_modes[prog_name] = dict(using_modes)
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
        self._linkage_owners = {}

        # 1. Collect this unit's LINKAGE SECTION 01-level items
        self._collect_linkage_items(unit)
        self._all_linkage_items.update(self._linkage_items)

        # 2. Its PROCEDURE DIVISION USING / RETURNING clause references them
        proc_div = unit.procedure_division
        if proc_div:
            for p in proc_div.get_metadata("using_parameters") or []:
                self._mark_referenced(p if isinstance(p, str) else str(p))
            returning = proc_div.get_metadata("returning_parameter")
            if returning:
                self._mark_referenced(str(returning))

        # 2b. The CICS translator supplies DFHEIBLK and DFHCOMMAREA on the
        # PROCEDURE DIVISION USING it generates, so a CICS program that
        # declares either in LINKAGE (the translated form does, and the
        # untranslated form may declare DFHCOMMAREA) references it by
        # construction -- there is no USING clause in the source to see.
        for name in _CICS_TRANSLATOR_ITEMS:
            self._mark_referenced(name)

        # 3. So do its ENTRY USING clauses and every ``SET ADDRESS OF item
        # TO pointer`` (a based LINKAGE item is addressed, not passed --
        # the CICS ``SET(ADDRESS OF item)`` option and ``ALLOCATE item``,
        # which obtains its storage and sets its address, are the same
        # idiom, #570); its CALLs are validated
        for node in self._own_nodes(unit):
            if isinstance(node, EntryStatement):
                for p in node.using_parameters or []:
                    self._mark_referenced(p)
            elif isinstance(node, CallStatement):
                self._validate_call(node)
            elif isinstance(node, AllocateStatement) and node.data_item:
                self._mark_referenced(_bare_name(node.data_item))
            elif isinstance(node, SetStatement) and node.targets_are_address_of:
                for target in node.targets:
                    self._mark_referenced(_bare_name(target))
            elif getattr(node, "node_type", None) == "EXEC_CICS":
                for value in cics_identifier_options(node).values():
                    based = _ADDRESS_OF_RE.match(value)
                    if based:
                        self._mark_referenced(_bare_name(based.group(1)))

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
                            for child in item.get_all_children():
                                child_name = (child.name or "").upper().strip()
                                if child_name:
                                    self._linkage_owners.setdefault(
                                        child_name, set()
                                    ).add(name)

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
        # target and however it is passed -- subscripted, reference-modified,
        # qualified, as ADDRESS OF / LENGTH OF, or one of its subordinate
        # items -- and so does receiving the callee's RETURNING value in it.
        passed = [param.name for param in call_params]
        if stmt.returning_parameter:
            passed.append(stmt.returning_parameter)
        for operand in passed:
            for name in _argument_names(operand):
                self._mark_referenced(name)
                for owner in self._linkage_owners.get(name.upper(), ()):
                    self._mark_referenced(owner)

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

        # BY VALUE/BY REFERENCE, position by position -- only ever checked
        # against the implicit PROCEDURE DIVISION USING entry (the only kind
        # `_entry_parameter_modes` has an entry for at all; an ENTRY
        # statement's own USING carries no BY clause in COBOL).
        modes = self._entry_parameter_modes.get(target)
        if modes:
            # strict=False: declared_params/call_params length mismatches
            # are exactly TOO_MANY_ARGS/TOO_FEW_ARGS above, not a bug here --
            # only the positions present on both sides are mode-checked.
            for position, (declared_name, call_param) in enumerate(
                zip(declared_params, call_params, strict=False), start=1
            ):
                declared_mode = modes.get(declared_name.upper())
                if declared_mode is None:
                    continue
                call_mode = (call_param.passing_mode or "REFERENCE").upper()
                if call_mode == "CONTENT":
                    # BY CONTENT is its own passing convention -- a copy the
                    # callee may modify without affecting the caller -- and
                    # PROCEDURE DIVISION USING has no CONTENT form to
                    # compare it against, so it is never flagged either way.
                    continue
                if call_mode != declared_mode:
                    self._violations.append(
                        LinkageViolation(
                            kind=LinkageViolationKind.PASSING_MODE_MISMATCH,
                            call_target=target,
                            location=loc,
                            message=(
                                f"CALL '{target}' passes argument {position} "
                                f"('{call_param.name}') BY {call_mode} but "
                                f"the entry declares BY {declared_mode}"
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
