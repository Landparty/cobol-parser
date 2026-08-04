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
    BoundaryReport,
)
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

_SCENARIO_NAME = "happy path"

#: Extensions tried, in order, when searching --callee-path directories for
#: a program name's source file.
_CALLEE_EXTENSIONS = ("", ".cbl", ".CBL", ".cob", ".COB")


def _sub_seed(bundle_seed: int, scenario: str, category: str, key: str) -> int:
    """Derive a per-boundary seed so adding one boundary never reshuffles
    every value generated after it (a single shared RNG in iteration order
    would). `zlib.crc32` is stdlib -- the zero-dependency rule holds."""
    text = f"{scenario}|{category}|{key}".encode()
    return zlib.crc32(text) ^ bundle_seed


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
                boundary, index, bundle_seed, layouts
            )
            if fixture is not None:
                scenario.fixtures.append(fixture)
            scenario.expectations.extend(expectations)
            unresolved.extend(extra_unresolved)

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
    ) -> tuple[BoundaryFixture | None, list[Expectation], list[str]]:
        ref = boundary.ref
        rng = random.Random(
            _sub_seed(bundle_seed, _SCENARIO_NAME, ref.category, ref.key)
        )
        factory = ValueFactory(rng, self.options)
        unresolved = list(boundary.unresolved)

        if ref.category in ("CALL", "DYNCALL"):
            return self._build_call_fixture(boundary, index, factory, layouts)

        if boundary.direction == "STATUS_ONLY":
            status_fixture = BoundaryFixture(
                ref=ref,
                direction=boundary.direction,
                status=self._status_dict(boundary, index),
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
        fields = self._fields_for_names(boundary.record_names, index)
        fixture: BoundaryFixture | None
        if not fields:
            if boundary.record_names:
                unresolved.append(
                    f"{ref.category} {ref.key}: no generatable fields in resolved layout"
                )
            fixture = None
        else:
            rows_count = self.options.rows if ref.category == "READ" else 1
            sequence = [
                {spec.column: factory.value_for(spec, row) for spec in fields}
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
                status=self._status_dict(boundary, index),
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

    def _build_call_fixture(
        self,
        boundary: Boundary,
        index: ProgramLayoutIndex,
        factory: ValueFactory,
        layouts: dict[str, list[FieldSpec]],
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

        row = {spec.column: factory.value_for(spec, 0) for spec in fields}
        self._register_layout(layouts, boundary, fields)
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
    def _status_dict(boundary: Boundary, index: ProgramLayoutIndex) -> dict[str, str]:
        if boundary.ref.category == "SQL":
            return {"SQLCODE": "0"}
        if boundary.status_field:
            return {boundary.status_field: "00"}
        facts = index.file_facts(boundary.ref.key)
        if facts is not None and facts.file_status_field:
            return {facts.file_status_field: "00"}
        return {}

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
