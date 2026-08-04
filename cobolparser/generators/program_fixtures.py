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

import os
import random
import zlib

from ..analysis.boundary_inventory import (
    Boundary,
    BoundaryInventoryAnalyzer,
    BoundaryRef,
    BoundaryReport,
)
from ..analysis.const_fold import ConstantFolder
from ..analysis.constraints import ConstraintExtractor
from ..analysis.program_flow import ProgramFlowAnalyzer
from ..models.program import CobolProgram
from ..models.statements.call import CallStatement
from .data.bundle import (
    BoundaryFixture,
    CoverageSummary,
    Expectation,
    FixtureBundle,
    Scenario,
)
from .data.errors import ProgramLayoutError
from .data.layout import FieldSpec, flatten_record
from .data.options import DataGeneratorOptions
from .data.program_layout import ProgramLayoutIndex
from .data.values import ValueFactory
from .scenarios import PlannedScenario, ScenarioPlanner

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


def _call_count_expectation(ref: BoundaryRef, times: int) -> Expectation:
    """Tier 1 (Phase 7): a structural expectation derivable exactly from the
    scenario's own generated sequence -- the scenario *defines* how many
    times a mocked boundary is invoked, so this is always safe, never a
    guess. Emitted for every boundary that gets an actual fixture (STATUS_ONLY
    included, always exactly once); an OUT-only boundary has nothing mocked
    to count, so it gets no call_count expectation."""
    return Expectation(
        kind="call_count",
        ref=f"{ref.category}:{ref.key}",
        value=times,
        note="derived from this scenario's own generated sequence length",
    )


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

        for boundary in report.boundaries:
            fixture, expectations, extra_unresolved = self._build_fixture(
                boundary, index, bundle_seed, layouts, _SCENARIO_NAME
            )
            if fixture is not None:
                scenario.fixtures.append(fixture)
            scenario.expectations.extend(expectations)
            unresolved.extend(extra_unresolved)
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
        """
        if mode not in _SCENARIO_MODES:
            raise ValueError(
                f"unknown scenario mode: {mode!r} (expected one of {_SCENARIO_MODES})"
            )
        if mode == "happy":
            return self.generate(ast, index, report, seed=seed)

        bundle_seed = seed if seed is not None else random.randrange(2**31)
        constraint_report = ConstraintExtractor().extract(ast, index, report)
        flow_report = ProgramFlowAnalyzer().analyze(ast)
        scenario_plan = ScenarioPlanner().plan(
            constraint_report, flow_report, report, mode=mode
        )

        layouts: dict[str, list[FieldSpec]] = {}
        unresolved: list[str] = list(report.unresolved)
        scenarios: list[Scenario] = []

        for planned in scenario_plan.scenarios:
            scenario = Scenario(
                name=planned.name,
                intent=planned.intent,
                entry=self._entry_paragraph(ast),
            )
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
                scenario.expectations.extend(expectations)
                unresolved.extend(extra_unresolved)
            scenario.expectations.extend(self._tier2_expectations(ast, index, scenario))
            scenarios.append(scenario)

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
            return status_fixture, [_call_count_expectation(ref, 1)], unresolved

        if boundary.direction == "OUT":
            expectation = Expectation(
                kind="stub",
                ref=f"{ref.category}:{ref.key}",
                note="value produced by the program under test",
            )
            return None, [expectation], unresolved

        # IN or BIDIRECTIONAL: generate the value(s) a mock would supply.
        fields = self._fields_for_names(boundary.record_names, index)
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
            self._register_layout(layouts, boundary, fields)
            terminal = None
            if "AT_END" in boundary.handlers:
                terminal = {(boundary.status_field or "FILE-STATUS"): "10"}
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
        if fixture is not None:
            times = len(fixture.sequence) + (1 if fixture.terminal else 0)
            expectations.append(_call_count_expectation(ref, times))
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
                    return seq.length
        return default_rows if boundary.ref.category == "READ" else 1

    @staticmethod
    def _value_for(
        spec: FieldSpec,
        factory: ValueFactory,
        row: int,
        override: PlannedScenario | None,
    ) -> str:
        if override is not None and spec.qualified_name in override.witnesses:
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

        row = {
            spec.column: self._value_for(spec, factory, 0, override) for spec in fields
        }
        self._register_layout(layouts, boundary, fields)
        fixture = BoundaryFixture(
            ref=ref,
            direction=boundary.direction,
            layout=fields,
            sequence=[row],
            unresolved=list(boundary.unresolved),
        )
        return fixture, [_call_count_expectation(ref, 1), *expectations], unresolved

    # -- helpers -------------------------------------------------------------

    def _fields_for_names(
        self, names: list[str], index: ProgramLayoutIndex
    ) -> list[FieldSpec]:
        fields: list[FieldSpec] = []
        seen_columns: set[str] = set()
        for name in names:
            for spec in self._fields_for_name(name, index):
                if spec.column in seen_columns:
                    continue
                seen_columns.add(spec.column)
                fields.append(spec)
        return fields

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

    @staticmethod
    def _register_layout(
        layouts: dict[str, list[FieldSpec]],
        boundary: Boundary,
        fields: list[FieldSpec],
    ) -> None:
        key = boundary.record_names[0] if boundary.record_names else boundary.ref.key
        layouts.setdefault(key, fields)

    @staticmethod
    def _status_dict(
        boundary: Boundary,
        index: ProgramLayoutIndex,
        *,
        override: PlannedScenario | None = None,
    ) -> dict[str, str]:
        field_name: str | None
        default: str
        if boundary.ref.category == "SQL":
            field_name, default = "SQLCODE", "0"
        elif boundary.status_field:
            field_name, default = boundary.status_field, "00"
        else:
            facts = index.file_facts(boundary.ref.key)
            field_name = facts.file_status_field if facts is not None else None
            default = "00"

        if field_name is None:
            return {}
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
            for candidate in candidates:
                for ext in _CALLEE_EXTENSIONS:
                    path = os.path.join(directory, candidate + ext)
                    if os.path.isfile(path):
                        return path
        return None


__all__ = ["ProgramFixtureGenerator"]
