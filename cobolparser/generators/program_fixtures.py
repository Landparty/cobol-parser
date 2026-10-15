"""ProgramFixtureGenerator: the gen-fixtures orchestrator (Phase 3).

Turns a program's :class:`~.data.program_layout.ProgramLayoutIndex` (Phase 1)
and :class:`~cobolparser.analysis.boundary_inventory.BoundaryReport` (Phase 2)
into a :class:`~.data.bundle.FixtureBundle`: layout-valid random values for
every boundary the program touches, assembled into one "happy path" scenario.
Reuses the Phase 0 value engine (:class:`ValueFactory` / :func:`flatten_record`)
directly against whatever :class:`FieldSpec` list each boundary resolves to --
no parallel value engine.
"""

from __future__ import annotations

import dataclasses
import os
import random
import zlib

from .._literals import is_quoted_literal
from ..analysis.boundary_inventory import (
    Boundary,
    BoundaryInventoryAnalyzer,
    BoundaryRef,
    BoundaryReport,
)
from ..analysis.const_fold import ConstantFolder
from ..analysis.constraints import ConstraintExtractor
from ..analysis.invocation_counts import (
    InvocationCounts,
    count_invocations,
    is_plain_eof_loop,
)
from ..analysis.program_flow import ProgramFlowAnalyzer
from ..models.program import CobolProgram
from ..models.statements.call import CallStatement
from ..models.statements.control import PerformStatement
from .data.bundle import (
    BoundaryFixture,
    CoverageSummary,
    Expectation,
    FixtureBundle,
    Scenario,
)
from .data.errors import ProgramLayoutError
from .data.layout import FieldSpec, _assign_columns, flatten_record
from .data.options import DataGeneratorOptions
from .data.program_layout import ProgramLayoutIndex
from .data.values import ValueFactory
from .scenarios import (
    PlannedScenario,
    ScenarioCoverage,
    ScenarioPlanner,
    stamp_arm_origins,
)
from .verification import ScenarioVerification, verify_scenario

_SCENARIO_NAME = "happy path"
_SCENARIO_MODES = ("happy", "branches", "all")

#: Extensions tried, in order, when searching --callee-path directories for
#: a program name's source file.
_CALLEE_EXTENSIONS = ("", ".cbl", ".CBL", ".cob", ".COB")


def _sub_seed(bundle_seed: int, scenario: str, category: str, key: str) -> int:
    """Derive a per-boundary seed so adding one boundary never reshuffles
    every value generated after it (a single shared RNG in iteration order
    would). `zlib.crc32` is stdlib -- the zero-dependency rule holds."""
    text = f"{scenario}|{category}|{key}".encode()
    return zlib.crc32(text) ^ bundle_seed


def _min_rows_for(override: PlannedScenario) -> int:
    """How many rows a scenario's own `row_witnesses` require to exist.

    A witness pinned to row 3 does nothing at all if the sequence is only two
    rows long -- so a per-row pin implies a minimum sequence length. Returns 0
    when the scenario pins no per-row values, leaving the ordinary length
    rules untouched.
    """
    if not override.row_witnesses:
        return 0
    return max(override.row_witnesses) + 1


#: Unchanged from when every count was taken from the sequence length, so
#: bundles whose counts were already right stay byte-identical.
_COUNT_NOTE = "derived from this scenario's own generated sequence length"


@dataclasses.dataclass
class _CallCounter:
    """Tier 1 (Phase 7): how many times each mocked boundary is invoked.

    A count is stated only when it is exact. For most boundaries that means
    every statement invoking it sits on the program's unconditional path
    (`count_invocations`): a CALL inside an IF arm, or an ACCEPT inside a
    `PERFORM UNTIL`, runs a data-dependent number of times, so it gets no
    `call_count` at all. The one data-dependent count that *is* exact is
    the read-until-end-of-file idiom: a file whose READ sets the flag a
    `PERFORM UNTIL` loop tests -- that flag alone, with nothing in the body
    able to leave early, and the loop on the unconditional path -- is
    read once per row of the scenario's own sequence plus once more to hit
    end of file -- however many READ statements share the work (a priming
    READ and the loop's own READ are one count, not two).
    """

    counts: InvocationCounts
    #: (category, key) of every READ boundary driven by such an EOF loop.
    eof_files: set[tuple[str, str]]

    @classmethod
    def build(
        cls, ast: CobolProgram, index: ProgramLayoutIndex, report: BoundaryReport
    ) -> _CallCounter:
        counts = count_invocations(ast, report, index)
        eof_files: set[tuple[str, str]] = set()
        if any(b.ref.category == "READ" for b in report.boundaries):
            constraints = ConstraintExtractor().extract(ast, index, report)
            for seq in constraints.sequence_constraints:
                _, _, line = seq.origin.partition("@")
                if not line.isdigit():
                    continue
                loops = counts.statements_at(int(line), PerformStatement)
                if (
                    len(loops) == 1
                    and counts.count_at(int(line), PerformStatement) == 1
                    and is_plain_eof_loop(ast, loops[0], index)
                ):
                    eof_files.add((seq.boundary.category, seq.boundary.key))
        return cls(counts=counts, eof_files=eof_files)

    def insert(
        self,
        report: BoundaryReport,
        scenario: Scenario,
        anchors: dict[tuple[str, str], int],
    ) -> None:
        """Put each count where its boundary's own expectations start.

        *anchors* maps a (category, key) to the index in
        `scenario.expectations` where the first of its boundaries that got a
        fixture began adding expectations -- the position a per-boundary
        count always had, so bundles keep their order.
        """
        found = self.expectations(report, scenario)
        ordered = sorted(found, key=lambda group: anchors.get(group, 0))
        for inserted, group in enumerate(ordered):
            scenario.expectations.insert(anchors.get(group, 0) + inserted, found[group])

    def expectations(
        self, report: BoundaryReport, scenario: Scenario
    ) -> dict[tuple[str, str], Expectation]:
        """One `call_count` per mocked (category, key) whose count is exact.

        A boundary with no fixture in *scenario* (OUT-only, or nothing
        generatable) has nothing mocked to count, so it gets none.
        """
        groups: dict[tuple[str, str], list[BoundaryRef]] = {}
        for boundary in report.boundaries:
            ref = boundary.ref
            groups.setdefault((ref.category, ref.key), []).append(ref)
        expectations: dict[tuple[str, str], Expectation] = {}
        for group, refs in groups.items():
            fixtures = [
                f for f in scenario.fixtures if (f.ref.category, f.ref.key) == group
            ]
            if not fixtures:
                continue
            counted = [self.counts.for_boundary(ref) for ref in refs]
            times: int | None = None
            if all(count is not None for count in counted):
                times = sum(count for count in counted if count is not None)
            elif group in self.eof_files:
                lengths = {len(f.sequence) for f in fixtures}
                if len(lengths) == 1:
                    times = lengths.pop() + 1
            if times is None:
                continue
            expectations[group] = Expectation(
                kind="call_count",
                ref=f"{group[0]}:{group[1]}",
                value=times,
                note=_COUNT_NOTE,
            )
        return expectations


def _drop_failure_path_counts(
    expectations: list[Expectation], planned: PlannedScenario
) -> list[Expectation]:
    """Remove the tier-1 counts a status override makes untrue (#318).

    A scenario that fails a boundary (OPEN status 35, READ INVALID KEY 23,
    CALL ON EXCEPTION, SQLCODE 100) sends the program down its error path,
    where the downstream READ loop, CLOSE or WRITE may run zero times or a
    different number of times. The boundary order here is source order, not
    execution order, so no other boundary is provably *before* the failure:
    every count but the overridden boundary's own is dropped. The overridden
    one keeps its count only when it is one invocation by construction (an
    OPEN, a CALL, an SQL statement); a READ's count comes from its generated
    row sequence, which a failing READ does not consume.
    """
    kept_refs = {key for key in planned.status_overrides if not key.startswith("READ:")}
    return [e for e in expectations if e.kind != "call_count" or e.ref in kept_refs]


def _demote_violated_arms(
    coverage: ScenarioCoverage,
    planned: PlannedScenario,
    verification: ScenarioVerification,
) -> list[str]:
    """Re-count *planned*'s arms as missed when its own data violates them.

    The planner counts an arm `targeted` (or `merged`) once its conjuncts
    solve; verification then re-reads the data actually emitted. A field
    verdict of `violated` means the scenario named for the arm provably does
    not reach it, so leaving the arm `targeted` would be a coverage claim
    the bundle contradicts. Only `violated` demotes: `absent`/`unknown` are
    "could not tell", which the scenario's own `unverified` status already
    says. Returns one `unresolved` entry per demoted arm, so `--strict`
    refuses the bundle rather than passing over a gap it reports.
    """
    violated = [v for v in verification.fields if v.status == "violated"]
    if not violated:
        return []
    reason = "witness failed verification: " + "; ".join(
        f"{v.field}: {v.detail}" for v in violated
    )
    keys = set(planned.arm_keys)
    gaps: list[str] = []
    for position, outcome in enumerate(coverage.details):
        if outcome.arm_key not in keys or outcome.status == "missed":
            continue
        if outcome.status == "targeted":
            coverage.targeted -= 1
        else:
            coverage.merged -= 1
        coverage.missed += 1
        coverage.details[position] = dataclasses.replace(
            outcome, status="missed", merged_into=None, reason=reason
        )
        gaps.append(f"scenario {planned.name!r}: arm {outcome.arm_key} {reason}")
    return gaps


class ProgramFixtureGenerator:
    """Generates a :class:`FixtureBundle` for one program.

    ``generate(ast, index, report, seed=...)`` works from already-built
    Phase 1/2 artifacts; ``generate_from_file(path, ...)`` parses and
    analyzes for you, optionally expanding copybooks and resolving CALL
    callees (from ``--callee-path`` directories, or automatically from
    ``CobolProgram.contained_programs`` in the same compilation unit).
    """

    def __init__(self, options: DataGeneratorOptions | None = None) -> None:
        self.options = options or DataGeneratorOptions()

    def generate(
        self,
        ast: CobolProgram,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
        *,
        seed: int | None = None,
    ) -> FixtureBundle:
        bundle_seed = seed if seed is not None else random.randrange(2**31)
        scenario = Scenario(
            name=_SCENARIO_NAME,
            intent="layout-valid values for every boundary, no branch targeting",
            entry=self._entry_paragraph(ast),
        )
        layouts: dict[str, list[FieldSpec]] = {}
        unresolved: list[str] = list(report.unresolved)
        unresolved.extend(self._alternate_view_notes(report))
        counter = _CallCounter.build(ast, index, report)
        anchors: dict[tuple[str, str], int] = {}

        for boundary in report.boundaries:
            fixture, expectations, extra_unresolved = self._build_fixture(
                boundary, index, bundle_seed, layouts, _SCENARIO_NAME
            )
            if fixture is not None:
                scenario.fixtures.append(fixture)
                anchors.setdefault(
                    (boundary.ref.category, boundary.ref.key),
                    len(scenario.expectations),
                )
            scenario.expectations.extend(expectations)
            unresolved.extend(extra_unresolved)
        counter.insert(report, scenario, anchors)
        scenario.expectations.extend(self._tier2_expectations(ast, index, scenario))

        unresolved_count = sum(1 for b in report.boundaries if b.unresolved)
        coverage = CoverageSummary(
            total_boundaries=len(report.boundaries),
            resolved_boundaries=len(report.boundaries) - unresolved_count,
            unresolved_boundaries=unresolved_count,
        )

        return FixtureBundle(
            program_name=ast.program_name,
            seed=bundle_seed,
            scenarios=[scenario],
            layouts=layouts,
            coverage=coverage,
            unresolved=unresolved,
        )

    def generate_with_scenarios(
        self,
        ast: CobolProgram,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
        *,
        mode: str = "happy",
        seed: int | None = None,
    ) -> FixtureBundle:
        """Phase 5/6: `mode="branches"`/`"all"` drive scenario selection
        through `ScenarioPlanner` instead of emitting only the "happy path".

        `mode="happy"` delegates to :meth:`generate` unchanged (byte-identical
        output, same seed -- this method adds a capability, it does not
        change the existing one). For `"branches"`/`"all"`, every scenario
        still gets a complete fixture for *every* boundary (the program under
        test touches all of them regardless of which branch is targeted) --
        only the specific fields a `PlannedScenario` constrains are pinned to
        its solved witness; everything else is generated the same
        `ValueFactory` way the happy path already is.

        The "happy path" scenario always comes first in these modes too,
        byte-identical to the one `mode="happy"` emits for the same seed.
        Branch targeting adds scenarios on top of it; it never replaces it.
        Before, a program with no targetable arm (every arm unreachable,
        fed by a field no boundary writes, or comparing two fields) got a
        bundle with zero scenarios -- asking for more coverage yielded
        less, and a consumer like mockymock had nothing to scaffold.
        """
        if mode not in _SCENARIO_MODES:
            raise ValueError(
                f"unknown scenario mode: {mode!r} (expected one of {_SCENARIO_MODES})"
            )
        if mode == "happy":
            return self.generate(ast, index, report, seed=seed)

        bundle_seed = seed if seed is not None else random.randrange(2**31)
        happy = self.generate(ast, index, report, seed=bundle_seed)
        constraint_report = ConstraintExtractor().extract(ast, index, report)
        flow_report = ProgramFlowAnalyzer().analyze(ast)
        scenario_plan = ScenarioPlanner().plan(
            constraint_report, flow_report, report, mode=mode
        )
        stamp_arm_origins(scenario_plan.coverage, index.source_map)
        counter = _CallCounter.build(ast, index, report)

        layouts: dict[str, list[FieldSpec]] = dict(happy.layouts)
        unresolved: list[str] = list(happy.unresolved)
        scenarios: list[Scenario] = list(happy.scenarios)

        for planned in scenario_plan.scenarios:
            scenario = Scenario(
                name=planned.name,
                intent=planned.intent,
                entry=self._entry_paragraph(ast),
            )
            anchors: dict[tuple[str, str], int] = {}
            for boundary in report.boundaries:
                fixture, expectations, extra_unresolved = self._build_fixture(
                    boundary,
                    index,
                    bundle_seed,
                    layouts,
                    planned.name,
                    override=planned,
                )
                if fixture is not None:
                    scenario.fixtures.append(fixture)
                    anchors.setdefault(
                        (boundary.ref.category, boundary.ref.key),
                        len(scenario.expectations),
                    )
                scenario.expectations.extend(expectations)
                unresolved.extend(extra_unresolved)
            counter.insert(report, scenario, anchors)
            if planned.status_overrides:
                # The fold walks the normal path; a failure path may stop
                # before any site it observed, so no field_equals is known
                # to hold there -- not even one folded from literals alone.
                scenario.expectations = _drop_failure_path_counts(
                    scenario.expectations, planned
                )
            else:
                scenario.expectations.extend(
                    self._tier2_expectations(ast, index, scenario)
                )
            # Self-verify BEFORE the scenario is written out: re-read the
            # data this scenario actually emitted and re-check it against the
            # conditions that motivated it. Without this the scenario's name
            # is a claim the bundle cannot support, and the only way to check
            # it was to run the suite under a tracer, per scenario.
            verification = verify_scenario(planned, scenario)
            scenario.verification = verification.to_dict()
            scenarios.append(scenario)
            unresolved.extend(
                _demote_violated_arms(scenario_plan.coverage, planned, verification)
            )

        unresolved_count = sum(1 for b in report.boundaries if b.unresolved)
        coverage = CoverageSummary(
            total_boundaries=len(report.boundaries),
            resolved_boundaries=len(report.boundaries) - unresolved_count,
            unresolved_boundaries=unresolved_count,
        )

        return FixtureBundle(
            program_name=ast.program_name,
            seed=bundle_seed,
            scenarios=scenarios,
            layouts=layouts,
            coverage=coverage,
            unresolved=unresolved,
            scenario_coverage=scenario_plan.coverage.to_dict(),
        )

    def generate_from_file(
        self,
        path: str,
        *,
        copybook_paths: list[str] | None = None,
        callee_paths: list[str] | None = None,
        seed: int | None = None,
    ) -> FixtureBundle:
        ast, index, report = self.analyze_from_file(
            path, copybook_paths=copybook_paths, callee_paths=callee_paths
        )
        return self.generate(ast, index, report, seed=seed)

    def generate_with_scenarios_from_file(
        self,
        path: str,
        *,
        copybook_paths: list[str] | None = None,
        callee_paths: list[str] | None = None,
        mode: str = "happy",
        seed: int | None = None,
    ) -> FixtureBundle:
        ast, index, report = self.analyze_from_file(
            path, copybook_paths=copybook_paths, callee_paths=callee_paths
        )
        return self.generate_with_scenarios(ast, index, report, mode=mode, seed=seed)

    def analyze_from_file(
        self,
        path: str,
        *,
        copybook_paths: list[str] | None = None,
        callee_paths: list[str] | None = None,
    ) -> tuple[CobolProgram, ProgramLayoutIndex, BoundaryReport]:
        """Parse *path* and run Phases 1-2 without generating a bundle --
        the shared entry point behind both `generate_from_file` and the
        CLI's `--list-boundaries` (which has no use for generated values)."""
        index = ProgramLayoutIndex.from_file(
            path, copybook_paths=copybook_paths, strict_copybooks=True
        )
        assert index.ast is not None  # from_file() always sets it on success
        ast = index.ast
        callee_indexes, callee_asts = self._resolve_callees(ast, callee_paths)
        report = BoundaryInventoryAnalyzer().analyze(
            ast, index, callee_indexes=callee_indexes, callee_asts=callee_asts
        )
        return ast, index, report

    # -- per-boundary fixture assembly --------------------------------------

    def _build_fixture(
        self,
        boundary: Boundary,
        index: ProgramLayoutIndex,
        bundle_seed: int,
        layouts: dict[str, list[FieldSpec]],
        scenario_name: str,
        *,
        override: PlannedScenario | None = None,
    ) -> tuple[BoundaryFixture | None, list[Expectation], list[str]]:
        ref = boundary.ref
        rng = random.Random(
            _sub_seed(bundle_seed, scenario_name, ref.category, ref.key)
        )
        factory = ValueFactory(rng, self.options)
        unresolved = list(boundary.unresolved)

        if ref.category in ("CALL", "DYNCALL"):
            return self._build_call_fixture(
                boundary, index, factory, layouts, override=override
            )

        if boundary.direction == "STATUS_ONLY":
            status_fixture = BoundaryFixture(
                ref=ref,
                direction=boundary.direction,
                status=self._status_dict(boundary, index, override=override),
            )
            return status_fixture, [], unresolved

        if boundary.direction == "OUT":
            expectation = Expectation(
                kind="stub",
                ref=f"{ref.category}:{ref.key}",
                note="value produced by the program under test",
            )
            return None, [expectation], unresolved

        # IN or BIDIRECTIONAL: generate the value(s) a mock would supply.
        record_names, dropped = self._record_view(boundary, index, override)
        if dropped:
            unresolved.append(
                f"{ref.category} {ref.key}: scenario {scenario_name!r} pins "
                f"{', '.join(dropped)} in another 01 record of the same FD; "
                f"rows use the {record_names[0]} view, so those pins are not "
                "applied (one record area cannot hold both views at once)"
            )
        fields = self._fields_for_names(record_names, index)
        fixture: BoundaryFixture | None
        if not fields:
            if boundary.record_names:
                unresolved.append(
                    f"{ref.category} {ref.key}: no generatable fields in resolved layout"
                )
            fixture = None
        else:
            rows_count = self._sequence_length(boundary, override, self.options.rows)
            sequence = [
                {
                    spec.column: self._value_for(spec, factory, row, override)
                    for spec in fields
                }
                for row in range(rows_count)
            ]
            self._register_layout(layouts, record_names, boundary, fields)
            terminal = None
            if "AT_END" in boundary.handlers:
                terminal_field = self._resolve_status_field(boundary, index)
                if terminal_field is not None:
                    terminal = {terminal_field: "10"}
            fixture = BoundaryFixture(
                ref=ref,
                direction=boundary.direction,
                layout=fields,
                sequence=sequence,
                terminal=terminal,
                status=self._status_dict(boundary, index, override=override),
                unresolved=list(boundary.unresolved),
            )

        expectations = []
        if boundary.direction == "BIDIRECTIONAL":
            expectations.append(
                Expectation(
                    kind="stub",
                    ref=f"{ref.category}:{ref.key}",
                    note="bidirectional: OUT aspect not asserted in v1",
                )
            )
        return fixture, expectations, unresolved

    @staticmethod
    def _sequence_length(
        boundary: Boundary, override: PlannedScenario | None, default_rows: int
    ) -> int:
        if override is not None:
            for seq in override.sequence_constraints:
                if (
                    seq.boundary.category == boundary.ref.category
                    and seq.boundary.key == boundary.ref.key
                    and seq.length is not None
                ):
                    return max(seq.length, _min_rows_for(override))
        base = default_rows if boundary.ref.category == "READ" else 1
        if override is not None:
            # A row a scenario pinned but never generates is a witness that
            # silently does nothing -- the sequence must be long enough to
            # actually contain every pinned row index.
            return max(base, _min_rows_for(override))
        return base

    @staticmethod
    def _value_for(
        spec: FieldSpec,
        factory: ValueFactory,
        row: int,
        override: PlannedScenario | None,
    ) -> str:
        """The value for one field in one row: a pinned witness, else generated.

        `row` is 0-based. A `row_witnesses` entry for this exact row wins over
        the scenario-wide `witnesses`, which pins one value to EVERY row --
        the distinction matters for any branch whose reachability is a
        property of the sequence rather than of a single record (see
        `PlannedScenario.row_witnesses`).
        """
        if override is not None:
            per_row = override.row_witnesses.get(row)
            if per_row is not None and spec.qualified_name in per_row:
                return per_row[spec.qualified_name]
            if spec.qualified_name in override.witnesses:
                return override.witnesses[spec.qualified_name]
        return factory.value_for(spec, row)

    def _build_call_fixture(
        self,
        boundary: Boundary,
        index: ProgramLayoutIndex,
        factory: ValueFactory,
        layouts: dict[str, list[FieldSpec]],
        *,
        override: PlannedScenario | None = None,
    ) -> tuple[BoundaryFixture | None, list[Expectation], list[str]]:
        ref = boundary.ref
        unresolved = list(boundary.unresolved)
        fields: list[FieldSpec] = []
        expectations: list[Expectation] = []

        for arg in boundary.call_args:
            if is_quoted_literal(arg.name):
                # ``BY CONTENT 'A'`` / ``X'00'``: a constant the caller
                # supplies, not a data item the layout index could hold.
                continue
            arg_fields = self._fields_for_names([arg.name], index)
            if not arg_fields:
                unresolved.append(
                    f"{ref.category} {ref.key}: argument {arg.name} not resolvable "
                    "in layout index"
                )
                continue
            if arg.direction in ("IN", "BIDIRECTIONAL"):
                fields.extend(arg_fields)
            if arg.direction == "OUT":
                expectations.append(
                    Expectation(
                        kind="stub",
                        ref=arg.name,
                        note="value supplied by the program under test, not "
                        f"mock-generated (provenance={arg.provenance})",
                    )
                )
            elif arg.direction == "BIDIRECTIONAL":
                expectations.append(
                    Expectation(
                        kind="stub",
                        ref=arg.name,
                        note="bidirectional: the OUT aspect (value the caller "
                        f"supplies) is not asserted in v1 (provenance={arg.provenance})",
                    )
                )

        if not fields:
            return None, expectations, unresolved

        # Each argument's columns are unique only within that argument: two
        # USING records that both hold an ``AMT`` would otherwise share one
        # row entry, so one value would stand for two fields (#365).
        fields = self._unique_columns(fields)
        row = {
            spec.column: self._value_for(spec, factory, 0, override) for spec in fields
        }
        self._register_layout(layouts, boundary.record_names, boundary, fields)
        fixture = BoundaryFixture(
            ref=ref,
            direction=boundary.direction,
            layout=fields,
            sequence=[row],
            unresolved=list(boundary.unresolved),
        )
        return fixture, expectations, unresolved

    # -- helpers -------------------------------------------------------------

    def _fields_for_names(
        self, names: list[str], index: ProgramLayoutIndex
    ) -> list[FieldSpec]:
        fields: list[FieldSpec] = []
        for name in names:
            fields.extend(self._fields_for_name(name, index))
        return self._unique_columns(fields)

    def _unique_columns(self, fields: list[FieldSpec]) -> list[FieldSpec]:
        """Drop repeats of the same field, then give every column a unique name.

        Fields gathered from several records (READ INTO several records, a
        CALL with several USING arguments) only had their columns made unique
        within their own record, so ``REC-A.AMT`` and ``REC-B.AMT`` both
        arrive as ``AMT``. A row is keyed by column, so that would leave one
        value for two fields. Identity is the qualified name (plus subscripts),
        never the column. On a collision the columns are reassigned over the
        whole list the way a single record's are -- on copies, since a spec
        from `ProgramLayoutIndex.resolve()` is the index's own.
        """
        unique: list[FieldSpec] = []
        seen: set[tuple[str, tuple[int, ...]]] = set()
        for spec in fields:
            identity = (spec.qualified_name, tuple(spec.subscripts))
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(spec)
        if len({spec.column for spec in unique}) == len(unique):
            return unique
        copies = [dataclasses.replace(spec) for spec in unique]
        _assign_columns(copies, self.options)
        return copies

    def _fields_for_name(self, name: str, index: ProgramLayoutIndex) -> list[FieldSpec]:
        """A name may resolve to one elementary field or a whole record --
        try both (`record_named()` exists precisely because `resolve()`
        alone never finds a group)."""
        resolved = index.resolve(name)
        if resolved:
            return [resolved.spec]
        record = index.record_named(name)
        if record:
            return flatten_record(record, self.options)
        return []

    def _record_view(
        self,
        boundary: Boundary,
        index: ProgramLayoutIndex,
        override: PlannedScenario | None,
    ) -> tuple[list[str], list[str]]:
        """The one record a file boundary's rows are generated through.

        A READ with no INTO names every 01 record under the FD (issue #364),
        but those records are alternative views of ONE record area -- the
        same bytes, as an implicit REDEFINES. Joining their fields into one
        row gives a byte two values (`HDR-TYPE` and `DTL-TYPE` both sit at
        offset 0) and drops a field name the second record repeats.

        So exactly one record is used: the one holding the most of the
        scenario's pinned fields (the first in source order on a tie, and
        always the first with no scenario). Returns that record as a
        one-element list, plus the pinned fields of the records left out --
        a pin those rows cannot honour, which the caller reports.
        """
        names = boundary.record_names
        # Only a READ names several records for the one FD: an SQL boundary's
        # several names are distinct host variables, a CALL's distinct args.
        if len(names) <= 1 or boundary.ref.category != "READ":
            return list(names), []
        pinned: set[str] = set()
        if override is not None:
            pinned.update(override.witnesses)
            for row in override.row_witnesses.values():
                pinned.update(row)
        per_record = {
            name: {spec.qualified_name for spec in self._fields_for_name(name, index)}
            for name in names
        }
        chosen = max(names, key=lambda name: len(per_record[name] & pinned))
        dropped = sorted(
            {q for name in names if name != chosen for q in per_record[name] & pinned}
            - per_record[chosen]
        )
        return [chosen], dropped

    @staticmethod
    def _alternate_view_notes(report: BoundaryReport) -> list[str]:
        """One note per file boundary whose FD's other 01 records are not
        generated -- see :meth:`_record_view`."""
        notes = []
        for boundary in report.boundaries:
            names = boundary.record_names
            if len(names) <= 1 or boundary.ref.category != "READ":
                continue
            notes.append(
                f"{boundary.ref.category} {boundary.ref.key}: the FD has "
                f"{len(names)} 01 records sharing one record area; rows are "
                "generated through one of them per scenario (the first unless "
                "the scenario pins fields of another) -- alternate view(s) not "
                f"generated: {', '.join(names[1:])}"
            )
        return notes

    @staticmethod
    def _register_layout(
        layouts: dict[str, list[FieldSpec]],
        record_names: list[str],
        boundary: Boundary,
        fields: list[FieldSpec],
    ) -> None:
        key = record_names[0] if record_names else boundary.ref.key
        layouts.setdefault(key, fields)

    @staticmethod
    def _resolve_status_field(
        boundary: Boundary, index: ProgramLayoutIndex
    ) -> str | None:
        """The real WORKING-STORAGE/FILE SECTION field name to report this
        boundary's status in, or None when the program declares none.

        Never invents a placeholder name: a MOVE to a name that doesn't
        exist in the program's DATA DIVISION fails to compile downstream
        (mockymock splices this straight into generated COBOL). Checks
        `boundary.status_field` first (resolved by BoundaryInventoryAnalyzer
        from an explicit `FILE STATUS IS` clause), then falls back to
        `index.file_facts(...)` (a second, independent resolution path) --
        only when both come up empty is there truly nothing to report a
        status into.
        """
        if boundary.ref.category == "SQL":
            return "SQLCODE"
        if boundary.status_field:
            return boundary.status_field
        facts = index.file_facts(boundary.ref.key)
        return facts.file_status_field if facts is not None else None

    @classmethod
    def _status_dict(
        cls,
        boundary: Boundary,
        index: ProgramLayoutIndex,
        *,
        override: PlannedScenario | None = None,
    ) -> dict[str, str]:
        field_name = cls._resolve_status_field(boundary, index)
        if field_name is None:
            return {}
        default = "0" if boundary.ref.category == "SQL" else "00"
        override_key = f"{boundary.ref.category}:{boundary.ref.key}"
        if override is not None and override_key in override.status_overrides:
            return {field_name: override.status_overrides[override_key]}
        return {field_name: default}

    @staticmethod
    def _tier2_expectations(
        ast: CobolProgram, index: ProgramLayoutIndex, scenario: Scenario
    ) -> list[Expectation]:
        """Tier 2 (Phase 7): constant-fold this scenario's own straight-line
        chain, seeded by its own single-invocation mocked inputs, and turn
        every field still knowable at a DISPLAY/WRITE into a `field_equals`
        expectation. Only a fixture with *exactly one* generated row seeds
        the fold -- a multi-row READ sequence (or a zero-row "empty input"
        one) has no single representative value, and (not coincidentally)
        every field a `PERFORM UNTIL`/`VARYING` loop writes is poisoned by
        the folder's own loop-abort rule anyway, since that is exactly where
        a multi-row READ is read from in practice."""
        seed_values: dict[str, str] = {}
        for fixture in scenario.fixtures:
            if len(fixture.sequence) != 1:
                continue
            for spec in fixture.layout:
                seed_values[spec.qualified_name] = fixture.sequence[0].get(
                    spec.column, ""
                )
        fold_result = ConstantFolder().fold(ast, index, seed_values=seed_values)
        return [
            Expectation(
                kind="field_equals",
                ref=qualified_name,
                value=value,
                note="constant-folded from this scenario's own mock-supplied inputs",
            )
            for qualified_name, value in fold_result.known.items()
        ]

    @staticmethod
    def _entry_paragraph(ast: CobolProgram) -> str | None:
        procedure = ast.get_division("PROCEDURE")
        if procedure is None:
            return None
        if procedure.paragraphs:
            return str(procedure.paragraphs[0].paragraph_name)
        for section in procedure.sections:
            if getattr(section, "is_declarative", False):
                continue  # USE procedures: control enters after END DECLARATIVES
            paragraphs = getattr(section, "paragraphs", None)
            if paragraphs:
                return str(paragraphs[0].paragraph_name)
        return None

    # -- callee resolution (Phase 2b rung 2 support) -------------------------

    def _resolve_callees(
        self, ast: CobolProgram, callee_paths: list[str] | None
    ) -> tuple[dict[str, ProgramLayoutIndex], dict[str, CobolProgram]]:
        callee_indexes: dict[str, ProgramLayoutIndex] = {}
        callee_asts: dict[str, CobolProgram] = {}

        # Free: a caller/callee pair bundled in one compilation unit needs no
        # file search at all.
        for contained in ast.contained_programs:
            name = (contained.program_name or "").upper()
            if name:
                callee_asts[name] = contained
                callee_indexes[name] = ProgramLayoutIndex.build(contained)

        if not callee_paths:
            return callee_indexes, callee_asts

        static_names = {
            (stmt.called_program or "").upper().strip("\"'")
            for stmt in ast.get_all_statements()
            if isinstance(stmt, CallStatement)
            and not stmt.is_dynamic
            and stmt.called_program
        }
        for name in static_names:
            if not name or name in callee_asts:
                continue
            found = self._find_callee_file(name, callee_paths)
            if found is None:
                continue
            try:
                callee_index = ProgramLayoutIndex.from_file(found)
            except ProgramLayoutError:
                continue
            assert callee_index.ast is not None
            callee_indexes[name] = callee_index
            callee_asts[name] = callee_index.ast

        return callee_indexes, callee_asts

    @staticmethod
    def _find_callee_file(name: str, callee_paths: list[str]) -> str | None:
        candidates = (name, name.lower())
        for directory in callee_paths:
            # Match against the directory listing itself, not os.path.isfile,
            # so the exact-name attempt can't silently "succeed" against a
            # differently-cased file on a case-insensitive filesystem (macOS,
            # Windows) and skip the lowercase fallback that would have
            # returned the real on-disk name.
            try:
                entries = set(os.listdir(directory))
            except OSError:
                continue
            for candidate in candidates:
                for ext in _CALLEE_EXTENSIONS:
                    filename = candidate + ext
                    if filename in entries:
                        return os.path.join(directory, filename)
        return None


__all__ = ["ProgramFixtureGenerator"]
