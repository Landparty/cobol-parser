"""ScenarioPlanner: constraints + control flow -> a named scenario set.

Phase 5 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md`). Turns
Phase 4's `ConstraintReport` and `ProgramFlowAnalyzer`'s control-flow graph
into a set of named `PlannedScenario`s -- one (or a merge of several) per
reachable, satisfiable branch arm -- plus, for `mode="all"`, fixed scenario
families that exist regardless of branching (empty input, declared error
statuses, numeric boundary values).

v1 path-condition simplification (stated up front, not discovered later): a
scenario targets *one* arm and takes only that arm's own conjuncts;
enclosing branches on the path to it are not accumulated. Full
path-sensitivity is a v2 item -- `ArmOutcome` records "targeted" the same way
whether or not the surrounding path was considered, so a coverage summary
here is arm coverage, not full path coverage.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from ..analysis.boundary_inventory import BoundaryReport
from ..analysis.constraints import (
    BranchConstraints,
    ConstraintReport,
    FieldConstraint,
    SequenceConstraint,
)
from ..analysis.domains import Unsatisfiable, Witness, solve
from ..analysis.program_flow import BranchArm, BranchNode, ProgramFlowReport
from .data.bundle import _unique_names
from .data.layout import FieldCategory, FieldSpec

# Boundary categories the empty-input family cares about -- an "input"
# boundary is one a program reads *from*.
_IN_FILE_CATEGORIES = frozenset({"READ"})


def _base_arm_id(arm_id: str) -> str:
    """Strip an OR-split "#N" suffix: "THEN#2" -> "THEN"."""
    return arm_id.split("#", 1)[0]


def _arm_type_map(branch_node: BranchNode) -> dict[str, BranchArm]:
    """Map this module's arm-id convention to `branch_node`'s own `BranchArm`s.

    THEN/ELSE map directly; WHEN arms map positionally (`BranchNode` does not
    number them, `BranchConstraints` does) since both walks visit `WHEN`
    clauses in the same source order.
    """
    mapping: dict[str, BranchArm] = {}
    when_index = 0
    for arm in branch_node.arms:
        if arm.arm_type == "THEN":
            mapping["THEN"] = arm
        elif arm.arm_type == "ELSE":
            mapping["ELSE"] = arm
        elif arm.arm_type == "WHEN":
            when_index += 1
            mapping[f"WHEN_{when_index}"] = arm
        elif arm.arm_type == "WHEN_OTHER":
            mapping["WHEN_OTHER"] = arm
    return mapping


@dataclass(frozen=True)
class ArmOutcome:
    """What became of one branch arm during planning."""

    arm_key: str  # "<branch_id>/<arm_id>"
    parent_proc: str | None
    status: str  # "targeted" | "merged" | "missed"
    merged_into: str | None = None
    reason: str | None = None
    #: (original file, original line), when ``arm_key``'s own line number
    #: counts lines in a copybook-expanded source rather than the file on
    #: disk. ``stamp_arm_origins`` fills this in after planning, from the
    #: same ``expansion_source_map`` ``lint``/``parse`` already use for
    #: their own findings. ``None`` when nothing needed translating.
    origin: tuple[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_key": self.arm_key,
            "parent_proc": self.parent_proc,
            "status": self.status,
            "merged_into": self.merged_into,
            "reason": self.reason,
            "origin": (
                {"file": self.origin[0], "line": self.origin[1]}
                if self.origin is not None
                else None
            ),
        }


@dataclass
class ScenarioCoverage:
    """Exact arm-coverage accounting: targeted + merged + missed == total."""

    total_arms: int = 0
    targeted: int = 0
    merged: int = 0
    missed: int = 0
    details: list[ArmOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_arms": self.total_arms,
            "targeted": self.targeted,
            "merged": self.merged,
            "missed": self.missed,
            "details": [d.to_dict() for d in self.details],
        }


_ARM_KEY_LOCATION_RE = re.compile(r"^(?P<proc>.*)@(?P<line>\d+):(?P<col>\d+)/")


def stamp_arm_origins(
    coverage: ScenarioCoverage, source_map: dict[int, tuple[str, int]] | None
) -> ScenarioCoverage:
    """Fill in ``ArmOutcome.origin`` for every detail, from *source_map*.

    ``arm_key`` embeds the line :class:`ProgramFlowAnalyzer` saw it at --
    which, when ``source_map`` is not ``None``, is a line in the
    copybook-*expanded* source, not in the file on disk (the same gap
    :func:`cobolparser.analysis.lint.apply_source_map` closes for ``lint``
    findings). A ``None`` map, or a line it does not cover, leaves that
    detail's ``origin`` at its default ``None`` -- never a guess.

    Mutates *coverage* in place (``ArmOutcome`` is frozen, so each stamped
    detail is a fresh instance) and returns it, for chaining.
    """
    if not source_map:
        return coverage
    stamped: list[ArmOutcome] = []
    for detail in coverage.details:
        match = _ARM_KEY_LOCATION_RE.match(detail.arm_key)
        origin = source_map.get(int(match.group("line"))) if match else None
        stamped.append(detail if origin is None else replace(detail, origin=origin))
    coverage.details = stamped
    return coverage


@dataclass
class PlannedScenario:
    """One planned scenario: which fields to constrain, to what witness."""

    name: str
    intent: str
    field_constraints: dict[str, list[FieldConstraint]] = field(default_factory=dict)
    #: qualified field name -> its solved witness value, already
    #: PICTURE-valid (see `domains.solve`). Applies to EVERY generated row
    #: of every boundary that owns the field.
    witnesses: dict[str, str] = field(default_factory=dict)
    #: 0-based row index -> {qualified field name: witness value}, overriding
    #: `witnesses` for that ONE row of a multi-row (READ/FETCH) sequence.
    #:
    #: Groundwork for branches whose reachability is a property of the
    #: *sequence*, not of any single record: "a prior '05' record sharing a
    #: key with a following '09' record" cannot be expressed by `witnesses`,
    #: which pins one value to every row. Nothing populates this yet -- the
    #: analysis that would recognize such a correlation is not built (see
    #: docs/plans/2026-09-04-cross-record-correlation-design.md); it exists so the
    #: pinning path is no longer the blocker, and so a caller assembling a
    #: correlated scenario by hand has a supported way to say it.
    row_witnesses: dict[int, dict[str, str]] = field(default_factory=dict)
    sequence_constraints: list[SequenceConstraint] = field(default_factory=list)
    #: "<CATEGORY>:<KEY>" -> an overriding status value (e.g. FILE STATUS
    #: "23", SQLCODE "-911") for the fixed error-status family.
    status_overrides: dict[str, str] = field(default_factory=dict)
    arm_keys: list[str] = field(default_factory=list)
    #: Enclosing arms on this scenario's path whose own conditions could NOT
    #: be folded in (the arm is not in the constraint report at all, or it
    #: was recorded with no modeled conjuncts). Each entry is a reason
    #: string. A non-empty list means this scenario pins its own arm but
    #: leaves part of the path to whatever the generator happened to
    #: produce -- so the arm may not actually be reached, and saying so
    #: beats a silently optimistic label.
    path_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "intent": self.intent,
            "field_constraints": {
                name: [c.to_dict() for c in constraints]
                for name, constraints in self.field_constraints.items()
            },
            "witnesses": dict(self.witnesses),
            "row_witnesses": {
                row: dict(values) for row, values in self.row_witnesses.items()
            },
            "sequence_constraints": [s.to_dict() for s in self.sequence_constraints],
            "status_overrides": dict(self.status_overrides),
            "arm_keys": list(self.arm_keys),
            "path_gaps": list(self.path_gaps),
        }


@dataclass
class ScenarioPlan:
    scenarios: list[PlannedScenario] = field(default_factory=list)
    coverage: ScenarioCoverage = field(default_factory=ScenarioCoverage)
    #: One note per arm the planner could not target because of a gap in
    #: the tool rather than a fact about the program -- today, an arm whose
    #: precondition the constraint extractor did not model
    #: (`BranchConstraints.unmodeled_arms`). An unreachable or unsatisfiable
    #: arm is the program's own business and is not listed. The fixture
    #: generator carries these into `FixtureBundle.unresolved`, so
    #: `gen-fixtures --strict` refuses the bundle (#509).
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios": [s.to_dict() for s in self.scenarios],
            "coverage": self.coverage.to_dict(),
            "unresolved": list(self.unresolved),
        }


class ScenarioPlanner:
    """Turns constraints + the CFG into a scenario set.

    ``plan(constraint_report, flow_report, boundary_report, mode=...)`` --
    `mode="branches"` covers reachable/satisfiable branch arms only;
    `mode="all"` additionally adds the fixed scenario families (empty-input,
    error-status, boundary-values). `mode="happy"` is not handled here --
    Phase 3's `ProgramFixtureGenerator` already produces the unconstrained
    happy-path scenario on its own.
    """

    def plan(
        self,
        constraint_report: ConstraintReport,
        flow_report: ProgramFlowReport,
        boundary_report: BoundaryReport,
        *,
        mode: str = "branches",
    ) -> ScenarioPlan:
        branch_nodes_by_loc = {
            (bn.location.line, bn.location.column): bn
            for bn in flow_report.branch_nodes
        }
        unreachable = {name.upper() for name in flow_report.unreachable_nodes}
        # Every arm's own conjuncts, keyed the way `BranchConstraints.
        # enclosing` names them, so a nested arm can pick up the conditions
        # that must hold for it to be REACHED (see `_path_constraints`).
        arms_by_key: dict[tuple[str, str], list[FieldConstraint]] = {
            (b.branch_id, arm_id): constraints
            for b in constraint_report.branches
            for arm_id, constraints in b.arms.items()
        }

        details: list[ArmOutcome] = []
        unresolved: list[str] = []
        candidates: list[tuple[str, PlannedScenario]] = []  # (sort_key, candidate)
        shared_areas = _shared_record_areas(boundary_report)

        for branch in constraint_report.branches:
            branch_node = (
                branch_nodes_by_loc.get((branch.line, branch.column))
                if branch.line is not None and branch.column is not None
                else None
            )
            arm_types = _arm_type_map(branch_node) if branch_node else {}
            # The CFG's own owner of this branch when it has one: sentences
            # before a section's (or the division's) first paragraph carry
            # no paragraph name in the constraint report, but the flow
            # graph attributes them to the section (or the division node).
            owner = (
                branch_node.parent_proc
                if branch_node is not None
                else branch.parent_proc
            )
            is_unreachable = bool(owner and owner.upper() in unreachable)
            verb = _branch_verb(branch, branch_node)

            # Every arm-id actually present in branch.arms -- this includes
            # OR-split variants ("ELSE#1"/"ELSE#2"), which represent full
            # coverage of their base arm ("ELSE") even though that literal
            # key is absent.
            present_bases: set[str] = set()
            for arm_id in sorted(branch.arms):
                present_bases.add(_base_arm_id(arm_id))
                arm_key = f"{branch.branch_id}/{arm_id}"
                if is_unreachable:
                    details.append(
                        ArmOutcome(
                            arm_key, branch.parent_proc, "missed", reason="unreachable"
                        )
                    )
                    continue

                unmodeled = branch.unmodeled_arms.get(arm_id)
                if unmodeled is not None:
                    # Its `[]` means "precondition unknown", not "anything
                    # goes": solving it would target the arm with random
                    # rows that usually (for a level-88 field drawn from its
                    # own condition values, always) run an earlier WHEN, and
                    # verification would then call zero conjuncts "verified".
                    reason = f"precondition not modeled: {unmodeled}"
                    details.append(
                        ArmOutcome(arm_key, branch.parent_proc, "missed", reason=reason)
                    )
                    unresolved.append(f"arm {arm_key} not targeted: {reason}")
                    continue

                options, path_gaps = _path_options(branch, arms_by_key)
                witnesses, unsat_reason, path = _solve_with_path(
                    options, branch.arms[arm_id]
                )
                constraints = path + branch.arms[arm_id]
                if unsat_reason is not None:
                    details.append(
                        ArmOutcome(
                            arm_key,
                            branch.parent_proc,
                            "missed",
                            reason=(
                                f"unsatisfiable with its own path condition: "
                                f"{unsat_reason}"
                                if path
                                else f"unsatisfiable: {unsat_reason}"
                            ),
                        )
                    )
                    continue

                name = _scenario_name(
                    branch,
                    arm_id,
                    arm_types.get(_base_arm_id(arm_id)),
                    verb,
                )
                by_field: dict[str, list[FieldConstraint]] = {}
                for c in constraints:
                    by_field.setdefault(c.field.spec.qualified_name, []).append(c)
                intent = f"targets branch arm {arm_key}"
                if path:
                    enclosing_keys = ", ".join(
                        f"{bid}/{aid}" for bid, aid in branch.enclosing
                    )
                    intent += f" (path condition from {enclosing_keys} included)"
                scenario = PlannedScenario(
                    name=name,
                    intent=intent,
                    field_constraints=by_field,
                    witnesses=witnesses,
                    arm_keys=[arm_key],
                    path_gaps=path_gaps,
                )
                spanned = _view_conflicts(_record_areas(scenario, shared_areas))
                if spanned:
                    # One READ fills its record area through ONE 01 record
                    # per scenario (the generator cannot write two views of
                    # the same bytes at once), so an arm whose own path pins
                    # fields of two of them is never generated as asked.
                    details.append(
                        ArmOutcome(
                            arm_key,
                            branch.parent_proc,
                            "missed",
                            reason=(
                                "pins fields of several 01 records of one FD "
                                f"({spanned}); rows are generated through "
                                "one record view at a time"
                            ),
                        )
                    )
                    continue
                sort_key = f"{branch.line or 0:010d}:{branch.column or 0:010d}:{arm_id}"
                candidates.append((sort_key, scenario))

            # A base arm the control-flow graph expects (e.g. "ELSE") with no
            # representation at all in branch.arms -- neither bare nor any
            # "#N" split variant -- is a genuine gap, not just an unusual key.
            for missing_base in sorted(set(arm_types) - present_bases):
                arm_key = f"{branch.branch_id}/{missing_base}"
                reason = (
                    "unreachable"
                    if is_unreachable
                    else _reason_for_missing_arm(branch, missing_base)
                )
                details.append(
                    ArmOutcome(arm_key, branch.parent_proc, "missed", reason=reason)
                )

        candidates.sort(key=lambda pair: pair[0])
        scenarios, merge_outcomes = _merge_candidates(candidates, shared_areas)
        details.extend(merge_outcomes)

        if mode == "all":
            scenarios.extend(_fixed_families(constraint_report, boundary_report))
        # Branch scenarios are already unique among themselves (see
        # `_merge_candidates`) and come first, so this pass can only ever
        # rename a fixed-family scenario -- never a merge target some
        # `ArmOutcome.merged_into` already points at.
        for scenario, unique in zip(
            scenarios, _unique_names([s.name for s in scenarios]), strict=True
        ):
            scenario.name = unique

        coverage = ScenarioCoverage(
            total_arms=len(details),
            targeted=sum(1 for d in details if d.status == "targeted"),
            merged=sum(1 for d in details if d.status == "merged"),
            missed=sum(1 for d in details if d.status == "missed"),
            details=details,
        )
        return ScenarioPlan(
            scenarios=scenarios, coverage=coverage, unresolved=unresolved
        )


def _path_options(
    branch: BranchConstraints,
    arms_by_key: dict[tuple[str, str], list[FieldConstraint]],
) -> tuple[list[list[list[FieldConstraint]]], list[str]]:
    """Per enclosing arm, the alternative conjunct sets that reach it, plus
    a reason for each enclosing arm that offers none.

    v1 of this planner took only the targeted arm's own conjuncts and left
    every enclosing condition to whatever the generator happened to produce.
    On a nested `IF A > 500 / IF B = "X"` that means the scenario named for
    the inner arm pins B and lets A fall wherever chance puts it -- so the
    scenario's own name is a claim its data does not support, and the only
    way to find out was to run it under `--trace`. Folding the path in makes
    the name true by construction where the enclosing arms are modeled, and
    `path_gaps` says so where they are not, rather than staying quiet.

    **Alternatives, not one set, because an OR-split arm is a disjunction.**
    `_register_variants` registers `THEN#1`/`THEN#2`/... and NO bare `THEN`
    for a condition containing an OR, while `BranchConstraints.enclosing`
    names the base arm id -- so a plain `arms_by_key[(branch_id, "THEN")]`
    lookup misses every such arm and the path silently goes unfolded. Each
    `#N` variant is one way to satisfy the same arm, so they are returned as
    alternatives and the caller picks whichever one stays satisfiable
    alongside the targeted arm's own conjuncts (`_solve_with_path`).

    An enclosing arm the constraint report never recorded (an unsupported
    condition shape, or a nesting whose branch produced no
    `BranchConstraints` at all) is a gap, not an error: the scenario is
    still worth generating, it just cannot promise the arm is reached. So
    is an arm recorded with no conjuncts -- a `SEARCH ... AT END` or an
    `EVALUATE`'s unsupported `WHEN OTHER`, whose real precondition is not a
    field constraint at all.
    """
    options: list[list[list[FieldConstraint]]] = []
    gaps: list[str] = []
    for branch_id, arm_id in branch.enclosing:
        exact = arms_by_key.get((branch_id, arm_id))
        if exact:
            options.append([exact])
            continue
        variants = [
            constraints
            for key, constraints in arms_by_key.items()
            if key[0] == branch_id
            and _base_arm_id(key[1]) == arm_id
            and key[1] != arm_id
            and constraints
        ]
        if variants:
            options.append(variants)
            continue
        gaps.append(
            f"enclosing arm {branch_id}/{arm_id} "
            + (
                "was modeled with no conjuncts"
                if exact is not None
                else "has no modeled constraints"
            )
            + ", so reaching this arm is not pinned by the generated data"
        )
    return options, gaps


#: Cap on the enclosing-path combinations tried before giving up. An OR-split
#: enclosing arm contributes one alternative per disjunct, so a deep chain of
#: them is a cross product; enclosing depth is small in practice and this only
#: has to keep a pathological program from stalling the planner.
_MAX_PATH_COMBINATIONS = 32


def _solve_with_path(
    options: list[list[list[FieldConstraint]]],
    own: list[FieldConstraint],
) -> tuple[dict[str, str], str | None, list[FieldConstraint]]:
    """Solve the targeted arm's conjuncts together with one alternative from
    each enclosing arm, returning `(witnesses, None, path)` for the first
    combination that solves.

    Trying combinations rather than fixing on the first disjunct matters:
    for `IF A = 1 OR A = 2 / IF A = 2`, picking `A = 1` for the enclosing
    arm makes the whole set unsatisfiable and would report the inner arm as
    unreachable, when in fact `A = 2` reaches it. The last failure's reason
    is returned when every combination is unsatisfiable, which is the honest
    answer for an arm genuinely unreachable under its own path.
    """
    reason: str | None = None
    for index, combination in enumerate(itertools.product(*options)):
        if index >= _MAX_PATH_COMBINATIONS:
            break
        path = [c for alternative in combination for c in alternative]
        witnesses, reason = _solve_arm(path + own)
        if reason is None:
            return witnesses, None, path
    if reason is None:
        # No options at all (or the cap cut in before any attempt): solve the
        # arm on its own, exactly as this planner did before path folding.
        witnesses, reason = _solve_arm(own)
        return witnesses, reason, []
    return {}, reason, []


def _solve_arm(
    constraints: list[FieldConstraint],
) -> tuple[dict[str, str], str | None]:
    """Solve every distinct field an arm's conjuncts touch.

    Returns `(witnesses, None)` on success, or `({}, reason)` on the first
    unsatisfiable field -- an arm with any unsatisfiable field cannot be
    targeted at all, since every conjunct in it must hold simultaneously.
    """
    by_field: dict[str, list[FieldConstraint]] = {}
    for c in constraints:
        by_field.setdefault(c.field.spec.qualified_name, []).append(c)

    witnesses: dict[str, str] = {}
    for qualified_name, field_constraints in by_field.items():
        spec = field_constraints[0].field.spec
        result = solve(spec, field_constraints)
        if isinstance(result, Unsatisfiable):
            return {}, f"{qualified_name}: {result.reason}"
        assert isinstance(result, Witness)
        witnesses[qualified_name] = result.value
    return witnesses, None


def _reason_for_missing_arm(branch: BranchConstraints, arm_id: str) -> str:
    base = _base_arm_id(arm_id)
    if base == "ELSE":
        suffix = "/ELSE"
    elif base.startswith("WHEN_") and base != "WHEN_OTHER":
        suffix = f"/WHEN#{base.split('_', 1)[1]}"
    else:
        suffix = None
    if suffix:
        for reason in branch.unsupported:
            if suffix in reason:
                return reason
    return (
        branch.unsupported[0]
        if branch.unsupported
        else "no constraints extracted for this arm"
    )


def _branch_verb(branch: BranchConstraints, branch_node: BranchNode | None) -> str:
    """The decision verb (``IF`` / ``EVALUATE`` / ``SEARCH``) of *branch*.

    Read off any conjunct's ``origin`` (``"IF@11"``, ``"EVALUATE@90/WHEN#2"``,
    ``"SEARCH@40/WHEN#1"``), which names the verb exactly; else the flow
    graph's own ``branch_type``; else inferred from the arm ids.
    """
    for constraints in branch.arms.values():
        for c in constraints:
            verb = c.origin.split("@", 1)[0]
            if verb:
                return verb
    if branch_node is not None:
        return branch_node.branch_type
    bases = {_base_arm_id(a) for a in branch.arms}
    if bases & {"THEN", "ELSE"}:
        return "IF"
    if "AT_END" in bases:
        return "SEARCH"
    return "EVALUATE"


_OP_TEXT = {
    "eq": "=",
    "ne": "NOT =",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
    "in_set": "IN",
    "not_in_set": "NOT IN",
}


def _render_constraint(c: FieldConstraint) -> str:
    name = c.field.spec.name
    numeric = c.field.spec.category in (FieldCategory.NUMERIC, FieldCategory.FLOAT)
    values = ", ".join(v if numeric else f"'{v}'" for v in c.values)
    if c.op in ("in_set", "not_in_set"):
        return f"{name} {_OP_TEXT[c.op]} ({values})"
    if c.op in _OP_TEXT:
        return f"{name} {_OP_TEXT[c.op]} {values}"
    if c.op in ("class_numeric", "class_alphabetic"):
        test = "NUMERIC" if c.op == "class_numeric" else "ALPHABETIC"
        return f"{name} IS {'NOT ' if c.negated else ''}{test}"
    if c.op == "figurative":
        rendered = ", ".join(c.values)
        return f"{name} {'NOT = ' if c.negated else '= '}{rendered}"
    return f"{name} {c.op} {', '.join(c.values)}".rstrip()


def _scenario_name(
    branch: BranchConstraints,
    arm_id: str,
    matched_arm: BranchArm | None,
    verb: str = "IF",
) -> str:
    """One arm's scenario name: ``"<proc>: <VERB>@<line> <arm>[ [disjunct]]"``.

    The verb and line are always present -- two IFs in one paragraph used to
    both read ``"<proc>: THEN"`` -- and an OR-split arm (``THEN#2``) names
    its own disjunct, since every disjunct of one arm is a scenario of its
    own.
    """
    proc = branch.parent_proc or "?"
    where = f"{verb}@{branch.line if branch.line is not None else '?'}"
    base = _base_arm_id(arm_id)
    if matched_arm is not None:
        arm = matched_arm.label
    elif base == "THEN":
        arm = "condition is true"
    elif base == "ELSE":
        arm = "condition is false"
    else:
        arm = arm_id if base == arm_id else base
    name = f"{proc}: {where} {arm}"
    if "#" in arm_id:
        constraints = branch.arms.get(arm_id) or []
        disjunct = " AND ".join(_render_constraint(c) for c in constraints)
        name += f" [{disjunct or 'alt ' + arm_id.split('#', 1)[1]}]"
    return name


#: Longest a merged scenario's spelled-out name may get before the later
#: arms are summarized as "(+N more arms)".
_MAX_MERGED_NAME = 120


def _merged_name(arm_names: list[str]) -> str:
    """One name for a scenario that targets every arm in *arm_names*.

    Later arms in the first arm's own paragraph drop the repeated
    ``"<proc>: "`` prefix.
    """
    first = arm_names[0]
    prefix = first.split(": ", 1)[0] + ": " if ": " in first else ""
    parts = [first] + [
        n[len(prefix) :] if prefix and n.startswith(prefix) else n
        for n in arm_names[1:]
    ]
    joined = " + ".join(parts)
    if len(joined) <= _MAX_MERGED_NAME:
        return joined
    return f"{first} (+{len(arm_names) - 1} more arms)"


def _touched_fields(scenario: PlannedScenario) -> set[str]:
    return set(scenario.field_constraints)


def _sequence_boundaries(scenario: PlannedScenario) -> dict[str, int | None]:
    return {
        f"{s.boundary.category}:{s.boundary.key}": s.length
        for s in scenario.sequence_constraints
    }


def _shared_record_areas(boundary_report: BoundaryReport) -> dict[str, str]:
    """01 record name -> the READ boundary whose record area it shares.

    Only a READ with no INTO names several 01 records for one FD: those
    records are views of ONE record area, and the generator fills a READ's
    rows through exactly one of them per scenario (issue #364). Records of
    an FD with a single 01 never appear here.
    """
    areas: dict[str, str] = {}
    for boundary in boundary_report.boundaries:
        if boundary.ref.category != "READ" or len(boundary.record_names) <= 1:
            continue
        area = f"{boundary.ref.category}:{boundary.ref.key}"
        for name in boundary.record_names:
            areas.setdefault(name.upper(), area)
    return areas


def _record_areas(
    scenario: PlannedScenario, shared_areas: dict[str, str]
) -> dict[str, set[str]]:
    """Shared record area -> the 01 records whose fields *scenario* pins."""
    used: dict[str, set[str]] = {}
    for constraints in scenario.field_constraints.values():
        for c in constraints:
            record = c.field.record.name.upper()
            area = shared_areas.get(record)
            if area is not None:
                used.setdefault(area, set()).add(record)
    return used


def _view_conflicts(used: dict[str, set[str]]) -> str:
    """A description of every area pinned through more than one record,
    or "" when each area is pinned through one record at most."""
    return "; ".join(
        f"{area}: {', '.join(sorted(records))}"
        for area, records in sorted(used.items())
        if len(records) > 1
    )


def _compatible(
    existing: PlannedScenario,
    candidate: PlannedScenario,
    shared_areas: dict[str, str] | None = None,
) -> bool:
    if _touched_fields(existing) & _touched_fields(candidate):
        return False
    if shared_areas:
        # Fields of two 01 records under one FD are "disjoint" by name but
        # share bytes: merged, only one record's pins could be generated.
        combined = _record_areas(existing, shared_areas)
        for area, records in _record_areas(candidate, shared_areas).items():
            combined.setdefault(area, set()).update(records)
        if _view_conflicts(combined):
            return False
    existing_seq = _sequence_boundaries(existing)
    for key, length in _sequence_boundaries(candidate).items():
        if key in existing_seq and existing_seq[key] != length:
            return False
    return True


def _merge_candidates(
    candidates: list[tuple[str, PlannedScenario]],
    shared_areas: dict[str, str] | None = None,
) -> tuple[list[PlannedScenario], list[ArmOutcome]]:
    """Greedily merge scenarios whose constraints touch disjoint fields.

    Deterministic: candidates arrive pre-sorted by (line, column, arm_id); a
    candidate merges into the first open scenario it is compatible with,
    else starts a new one.

    A zero-constraint arm (``WHEN OTHER``, an EVALUATE ``Any`` selector, or
    any arm the constraint extractor couldn't derive conjuncts for) is
    never a merge candidate in either direction. Its *real* precondition is
    "none of this branch's other arms matched" -- but with no conjuncts of
    its own, `_compatible` sees an empty touched-field set, which is
    trivially "disjoint" from everything, including a sibling arm's
    scenario that pins the very field this arm's condition depends on.
    Merging either way would silently claim a branch is exercised by a
    fixture that provably can never reach it.
    """
    open_scenarios: list[PlannedScenario] = []
    outcomes: list[ArmOutcome] = []
    #: Parallel to `outcomes`: the scenario a "merged" outcome merged into,
    #: so `merged_into` can name it once its final name is known.
    merged_targets: list[PlannedScenario | None] = []
    arm_names: dict[int, list[str]] = {}

    for _, candidate in candidates:
        arm_key = candidate.arm_keys[0]
        # arm_key is "<parent_proc>@<line>:<column>/<arm_id>" (see _branch_id
        # in constraints.py) -- recovering parent_proc here avoids losing it
        # off ArmOutcome just because PlannedScenario itself doesn't carry it.
        parent_proc = arm_key.split("@", 1)[0] or None
        target = (
            next(
                (
                    s
                    for s in open_scenarios
                    if s.field_constraints and _compatible(s, candidate, shared_areas)
                ),
                None,
            )
            if candidate.field_constraints
            else None
        )
        if target is None:
            open_scenarios.append(candidate)
            arm_names[id(candidate)] = [candidate.name]
            outcomes.append(ArmOutcome(arm_key, parent_proc, "targeted"))
            merged_targets.append(None)
        else:
            target.field_constraints.update(candidate.field_constraints)
            target.witnesses.update(candidate.witnesses)
            target.sequence_constraints.extend(candidate.sequence_constraints)
            target.arm_keys.append(arm_key)
            # A merged-in candidate brings its own unpinned enclosing arms
            # with it. Dropping them here would let the merged scenario
            # report "verified" while one of the arms it now claims is not
            # in fact pinned by the generated data -- the exact silent
            # false positive `path_gaps` exists to prevent.
            for gap in candidate.path_gaps:
                if gap not in target.path_gaps:
                    target.path_gaps.append(gap)
            target.intent = f"targets {len(target.arm_keys)} branch arms: {', '.join(target.arm_keys)}"
            arm_names[id(target)].append(candidate.name)
            outcomes.append(ArmOutcome(arm_key, parent_proc, "merged"))
            merged_targets.append(target)

    # A merged scenario is named for every arm it targets, not just the one
    # it started from -- then made unique, since two scenarios can still
    # target same-named arms (e.g. a duplicated paragraph body).
    names = [_merged_name(arm_names[id(s)]) for s in open_scenarios]
    for scenario, unique in zip(open_scenarios, _unique_names(names), strict=True):
        scenario.name = unique
    outcomes = [
        replace(outcome, merged_into=target.name) if target is not None else outcome
        for outcome, target in zip(outcomes, merged_targets, strict=True)
    ]
    return open_scenarios, outcomes


def _fixed_families(
    constraint_report: ConstraintReport, boundary_report: BoundaryReport
) -> list[PlannedScenario]:
    scenarios: list[PlannedScenario] = []

    empty_input = _empty_input_scenario(boundary_report)
    if empty_input is not None:
        scenarios.append(empty_input)

    scenarios.extend(_error_status_scenarios(boundary_report))
    scenarios.extend(_boundary_value_scenarios(constraint_report))
    return scenarios


def _empty_input_scenario(boundary_report: BoundaryReport) -> PlannedScenario | None:
    sequence_constraints = []
    status_overrides = {}
    for boundary in boundary_report.boundaries:
        if boundary.direction != "IN":
            continue
        if boundary.ref.category in _IN_FILE_CATEGORIES:
            sequence_constraints.append(
                SequenceConstraint(
                    boundary=boundary.ref, length=0, origin="empty-input-family"
                )
            )
        elif boundary.ref.category == "SQL":
            status_overrides[f"{boundary.ref.category}:{boundary.ref.key}"] = "100"

    if not sequence_constraints and not status_overrides:
        return None
    return PlannedScenario(
        name="empty input",
        intent="every IN boundary is empty on its first read (EOF / SQLCODE 100)",
        sequence_constraints=sequence_constraints,
        status_overrides=status_overrides,
    )


def _error_status_scenarios(boundary_report: BoundaryReport) -> list[PlannedScenario]:
    scenarios: list[PlannedScenario] = []
    for boundary in boundary_report.boundaries:
        key = f"{boundary.ref.category}:{boundary.ref.key}"
        if "INVALID_KEY" in boundary.handlers:
            scenarios.append(
                PlannedScenario(
                    name=f"error status: {boundary.ref.category} {boundary.ref.key} INVALID KEY",
                    intent=(
                        f"{boundary.ref.category} {boundary.ref.key} fails with an "
                        "INVALID KEY status the program declares a handler for"
                    ),
                    status_overrides={key: "23"},
                )
            )
        if boundary.ref.category == "CALL" and "ON_EXCEPTION" in boundary.handlers:
            scenarios.append(
                PlannedScenario(
                    name=f"error status: CALL {boundary.ref.key} ON EXCEPTION",
                    intent=f"CALL {boundary.ref.key} returns a non-zero RETURN-CODE",
                    status_overrides={key: "12"},
                )
            )
        if boundary.ref.category == "OPEN" and boundary.status_field:
            scenarios.append(
                PlannedScenario(
                    name=f"error status: OPEN {boundary.ref.key} not found",
                    intent=f"OPEN {boundary.ref.key} fails with FILE STATUS 35",
                    status_overrides={key: "35"},
                )
            )
    return scenarios


def _boundary_value_scenarios(
    constraint_report: ConstraintReport,
) -> list[PlannedScenario]:
    numeric_fields: dict[str, FieldConstraint] = {}
    for branch in constraint_report.branches:
        for constraints in branch.arms.values():
            for c in constraints:
                spec = c.field.spec
                if spec.category in (
                    FieldCategory.NUMERIC,
                    FieldCategory.NUMERIC_EDITED,
                    FieldCategory.FLOAT,
                ):
                    numeric_fields.setdefault(spec.qualified_name, c)

    if not numeric_fields:
        return []

    min_witnesses: dict[str, str] = {}
    max_witnesses: dict[str, str] = {}
    for qualified_name, sample in numeric_fields.items():
        spec = sample.field.spec
        ceiling = _picture_ceiling(spec)
        floor = f"-{ceiling}" if spec.is_signed else "0"
        # eq pins the domain to a single point -- ge/le alone only narrow the
        # interval, and solve()'s witness is always the interval's midpoint,
        # not either edge (found writing this family's own test).
        lo_result = solve(spec, [_bound_constraint(sample, "eq", floor)])
        hi_result = solve(spec, [_bound_constraint(sample, "eq", ceiling)])
        if isinstance(lo_result, Witness):
            min_witnesses[qualified_name] = lo_result.value
        if isinstance(hi_result, Witness):
            max_witnesses[qualified_name] = hi_result.value

    scenarios = []
    if min_witnesses:
        scenarios.append(
            PlannedScenario(
                name="boundary values: minimum",
                intent="every constrained numeric field at its picture's minimum",
                witnesses=min_witnesses,
            )
        )
    if max_witnesses:
        scenarios.append(
            PlannedScenario(
                name="boundary values: maximum",
                intent="every constrained numeric field at its picture's maximum",
                witnesses=max_witnesses,
            )
        )
    return scenarios


def _bound_constraint(sample: FieldConstraint, op: str, value: str) -> FieldConstraint:
    return FieldConstraint(sample.field, op, (value,), origin="boundary-values-family")


def _picture_ceiling(spec: FieldSpec) -> str:
    """Exact decimal text, never float: ``str(float(10**18 - 1))`` is
    ``'1e+18'`` -- scientific notation the solver would then mis-handle,
    and one past the field's actual ceiling."""
    digits = spec.integer_digits
    decimals = spec.decimal_digits
    if decimals == 0:
        return str(10**digits - 1)
    return str(Decimal(10**digits) - Decimal(1).scaleb(-decimals))


__all__ = [
    "ArmOutcome",
    "ScenarioCoverage",
    "PlannedScenario",
    "ScenarioPlan",
    "ScenarioPlanner",
]
