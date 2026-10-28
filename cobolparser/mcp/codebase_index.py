"""Indexes over every program under the workspace root, for the
cross-program tools.

Three of them, each built on its first use and kept until a file it read
changes (:meth:`.Workspace.index`), so a session that only asks who calls a
program never pays for field lineage:

* ``programs`` -- every program unit, the programs it CALLs, LINKs or XCTLs
  to and from which lines, and the COPY graph
  (:class:`~cobolparser.analysis.codebase.CodebaseGraph`) with the line of
  every COPY statement in a program.
* ``lineage`` -- every unit's field-flow report, joined into one
  :class:`~cobolparser.analysis.lineage_graph.LineageGraph` through CALL
  arguments and DB2 columns, and through datasets when the root holds JCL
  and jcl-parser is installed.
* ``health`` -- every unit's health grade, and the duplicated paragraphs
  that span programs.

Each build parses every program once, through the workspace's own settings
(``cobol.yml``'s copybook paths, source format and ``>>DEFINE`` symbols),
using a cached parse when it is current but never filling the cache. Only
small facts are kept: a root of thousands of programs never has more than
one AST live.

A program that cannot be parsed is named, never skipped silently: every
index carries ``failed`` (file -> why) and the per-file caveats of the ones
that parsed with recovery or with a COPY left unexpanded.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.program import CobolProgram
from .envelope import Caveat, Response, ToolError
from .workspace import ParsedProgram, Stamp, Workspace


@dataclass
class UnitFacts:
    """One program unit, as the ``programs`` index keeps it."""

    program_id: str
    file: str
    #: 0 for an outermost (or stacked) unit of its file, 1 for one nested in
    #: it, ...
    depth: int
    #: ``PROGRAM``, or ``CLASS`` / ``FACTORY`` / ``OBJECT`` / ``METHOD``.
    unit_kind: str = "PROGRAM"
    #: Its id in the codebase graph: the PROGRAM-ID, qualified by the
    #: programs it is nested in for a nested one (``OUTER/INNER``, #532).
    graph_id: str = ""
    #: Its alternate ``ENTRY 'name'`` names, uppercased: a ``CALL 'name'``
    #: reaches this program too (#521).
    entries: list[str] = field(default_factory=list)
    #: ``program_brief``'s ``calls`` rows: target, via, dynamic, candidates
    #: and the sites (on-disk locations) of every CALL / LINK / XCTL.
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_call_target(self) -> bool:
        """False for a FACTORY / OBJECT / METHOD-ID unit: no ``CALL`` can
        reach one, and the codebase graph has no node for it -- what it
        CALLs is counted on its class (#500)."""
        return self.unit_kind not in ("FACTORY", "OBJECT", "METHOD")


@dataclass
class _Survey:
    """What every index records about the walk itself."""

    files: list[str] = field(default_factory=list)
    #: file -> why it produced no program at all.
    failed: dict[str, str] = field(default_factory=dict)
    #: file -> what limits its answers (partial parse, unexpanded COPY, an
    #: analyzer that raised on one unit).
    file_caveats: dict[str, list[Caveat]] = field(default_factory=dict)
    seconds: float = 0.0

    def note(self, file: str, caveat: Caveat) -> None:
        held = self.file_caveats.setdefault(file, [])
        if caveat not in held:
            held.append(caveat)

    def summary(self) -> dict[str, Any]:
        return {
            "program_files": len(self.files),
            "failed_files": len(self.failed),
            "built_in_seconds": round(self.seconds, 2),
        }


@dataclass
class ProgramsIndex(_Survey):
    units: list[UnitFacts] = field(default_factory=list)
    graph: Any = None  # CodebaseGraph
    #: MEMBER -> every COPY of it in a program file: {file, line}.
    copy_sites: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def units_named(self, program_id: str) -> list[UnitFacts]:
        """The units a ``CALL 'program_id'`` could reach: those whose
        PROGRAM-ID is *program_id*, or, when none is, those that declare it
        as an ``ENTRY`` name (#521). A FACTORY / OBJECT / METHOD-ID unit is
        never one (#500)."""
        wanted = program_id.upper()
        targets = [u for u in self.units if u.is_call_target]
        named = [u for u in targets if u.program_id.upper() == wanted]
        return named or [u for u in targets if wanted in u.entries]


@dataclass
class LineageIndex(_Survey):
    graph: Any = None  # LineageGraph
    #: PROGRAM-ID -> the file it was read from (the first, on a duplicate).
    program_files: dict[str, str] = field(default_factory=dict)
    #: PROGRAM-IDs whose parse expanded copybooks, so that a bare line number
    #: from its report may be in a copybook rather than in its own file.
    expanded: set[str] = field(default_factory=set)
    #: (PROGRAM-ID, line, edge kind, statement) -> the file the line is in;
    #: None when two files claim the key (a program line and a copybook line
    #: of the same number). Only a fallback: a hop carries its own
    #: ``origin_file`` when the report was source-mapped (#489).
    edge_files: dict[tuple[str, int, str, str], str | None] = field(
        default_factory=dict
    )
    #: Units or files that produced no lineage report, and JCL problems.
    problems: list[str] = field(default_factory=list)
    #: JCL files found under the root, and whether their datasets joined.
    jcl_files: list[str] = field(default_factory=list)
    jcl_note: str | None = None


@dataclass
class HealthIndex(_Survey):
    #: {program, file, depth, grade, score}, one per unit.
    units: list[dict[str, Any]] = field(default_factory=list)
    #: cross_file_clone_groups' groups, members already placed on disk:
    #: {clone_type, statement_count, members: [{program, paragraph, location}]}.
    clones: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def _units_with_depth(
    program: CobolProgram, depth: int = 0
) -> Iterator[tuple[CobolProgram, int]]:
    yield program, depth
    for contained in program.contained_programs:
        # The source nesting: a stacked unit is outermost, not contained
        # (#532).
        yield from _units_with_depth(contained, contained.nesting_depth)


def _entry_names(unit: CobolProgram) -> list[str]:
    """*unit*'s own ``ENTRY 'name'`` names, normalized like PROGRAM-IDs."""
    from ..analysis.codebase import _normalize_program_name, _unit_statements
    from ..models.statements.call import EntryStatement

    return sorted(
        {
            _normalize_program_name(statement.entry_name)
            for statement in _unit_statements(unit)
            if isinstance(statement, EntryStatement) and statement.entry_name
        }
        - {""}
    )


def _programs(
    workspace: Workspace,
    survey: _Survey,
    stamps: dict[str, Stamp],
    only: list[Path] | None = None,
) -> Iterator[tuple[Path, ParsedProgram | None]]:
    """Every program file under the root (or just *only*), parsed; None for
    one that failed (recorded in ``survey.failed``). Fills *stamps* with
    what was read."""
    from .workspace import _stamp

    paths = workspace.program_files() if only is None else only
    for done, path in enumerate(paths):
        display = workspace.display(path)
        workspace.report_progress(done, len(paths), f"reading {display}")
        survey.files.append(display)
        try:
            parsed = workspace.cached_or_parse(path)
        except ToolError as exc:
            survey.failed[display] = str(exc)
            stamps[str(path)] = _stamp(str(path))
            yield path, None
            continue
        except Exception as exc:  # noqa: BLE001 -- one file must not sink the root
            survey.failed[display] = f"{type(exc).__name__}: {exc}"
            stamps[str(path)] = _stamp(str(path))
            yield path, None
            continue
        stamps.update(parsed.stamps)
        for caveat in parsed.caveats:
            survey.note(display, caveat)
        yield path, parsed


def _per_file(
    workspace: Workspace,
    survey: _Survey,
    stamps: dict[str, Stamp],
    namespace: str,
    compute: Callable[[Path, ParsedProgram, str], Any],
) -> Iterator[tuple[Path, Any]]:
    """``(path, facts)`` for every program file under the root: *compute*'s
    JSON-shaped facts for its parse, or None for a file that failed.

    With :attr:`.Workspace.cache_dir`, a file whose source, copybooks and
    copybook directories are unchanged since an earlier build is not parsed
    at all: its facts, the caveats noted for it and its stamps come back
    from the cache.
    """
    cache = workspace.facts_cache(namespace)
    if cache is None:
        for path, parsed in _programs(workspace, survey, stamps):
            yield path, (
                None
                if parsed is None
                else compute(path, parsed, workspace.display(path))
            )
        return

    def held(path: Path) -> Any:
        entry = cache.get(str(path))
        try:
            return (
                entry["facts"],
                [Caveat(**c) for c in entry["caveats"]],
                {
                    name: tuple(value) if value is not None else None
                    for name, value in entry["stamps"].items()
                },
            )
        except (TypeError, KeyError, ValueError):
            return None

    remaining: list[Path] = []
    hits: dict[Path, Any] = {}
    for path in workspace.program_files():
        found = held(path)
        if found is None:
            remaining.append(path)
        else:
            hits[path] = found
    misses = iter(_programs(workspace, survey, stamps, only=remaining))
    for path in workspace.program_files():
        if path not in hits:
            missed, parsed = next(misses)
            assert missed == path
            if parsed is None:
                yield path, None
                continue
            display = workspace.display(path)
            facts = compute(path, parsed, display)
            cache.put(
                str(path),
                {
                    "facts": facts,
                    "caveats": [
                        {"kind": c.kind, "detail": c.detail, "effect": c.effect}
                        for c in survey.file_caveats.get(display, [])
                    ],
                    "stamps": {
                        name: list(value) if value is not None else None
                        for name, value in parsed.stamps.items()
                    },
                },
                parsed.stamps,
            )
            yield path, facts
            continue
        facts, caveats, file_stamps = hits[path]
        display = workspace.display(path)
        survey.files.append(display)
        stamps.update(file_stamps)
        for caveat in caveats:
            survey.note(display, caveat)
        yield path, facts


def _analyzer_failed(survey: _Survey, file: str, what: str, exc: Exception) -> None:
    survey.note(
        file,
        Caveat(
            "analyzer-failed",
            f"{file}: {what} could not be analyzed: {type(exc).__name__}: {exc}",
            f"cross-program answers miss what {file} would add",
        ),
    )


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------


def programs_index(workspace: Workspace) -> ProgramsIndex:
    def build() -> tuple[ProgramsIndex, dict[str, Stamp]]:
        return _build_programs(workspace)

    index: ProgramsIndex = workspace.index("programs", build)
    return index


def _build_programs(workspace: Workspace) -> tuple[ProgramsIndex, dict[str, Stamp]]:
    from dataclasses import asdict

    from ..analysis.codebase import (
        CodebaseGraphBuilder,
        FileGraphFacts,
        program_graph_ids,
    )
    from ..batch import BatchResult
    from .tools import _calls, _flow

    started = time.monotonic()
    index = ProgramsIndex()
    stamps = workspace.tree_stamps()
    files = [str(p) for p in workspace.program_files()]
    builder = CodebaseGraphBuilder(copybook_paths=list(workspace.config.copybook_path))

    def compute(path: Path, parsed: ParsedProgram, display: str) -> dict[str, Any]:
        response = Response()
        graph_ids = program_graph_ids(parsed.ast.program_units(), str(Path(str(path))))
        units: list[dict[str, Any]] = []
        for unit, depth in _units_with_depth(parsed.ast):
            facts = UnitFacts(
                program_id=unit.program_name or "",
                file=display,
                depth=depth,
                unit_kind=unit.unit_kind,
                graph_id=graph_ids.get(id(unit), ""),
                entries=_entry_names(unit),
            )
            try:
                facts.calls = _calls(parsed, unit, _flow(parsed, unit), response)
            except Exception as exc:  # noqa: BLE001
                _analyzer_failed(index, display, "called programs", exc)
            units.append(asdict(facts))
        for caveat in response.caveats:
            index.note(display, caveat)
        graph = builder.file_facts(
            BatchResult(path=Path(str(path)), result=parsed.result, read_error=None)
        )
        return {"units": units, "graph": graph.to_dict()}

    def results() -> Iterator[BatchResult | FileGraphFacts]:
        for path, facts in _per_file(workspace, index, stamps, "programs", compute):
            if facts is None:
                yield BatchResult(
                    path=Path(str(path)),
                    result=None,
                    read_error=index.failed[workspace.display(path)],
                )
                continue
            index.units.extend(UnitFacts(**unit) for unit in facts["units"])
            yield FileGraphFacts.from_dict(facts["graph"])

    index.graph = builder.build_from_results(files, results())
    for file, sites in index.graph.copy_sites.items():
        display = workspace.display(file)
        for member, line in sites:
            index.copy_sites.setdefault(member, []).append(
                {"file": display, "line": line}
            )
    index.seconds = time.monotonic() - started
    return index, stamps


# ---------------------------------------------------------------------------
# lineage
# ---------------------------------------------------------------------------


def lineage_index(workspace: Workspace) -> LineageIndex:
    def build() -> tuple[LineageIndex, dict[str, Stamp]]:
        return _build_lineage(workspace)

    index: LineageIndex = workspace.index("lineage", build)
    return index


def _build_lineage(workspace: Workspace) -> tuple[LineageIndex, dict[str, Stamp]]:
    from ..analysis.field_lineage import apply_source_map
    from ..analysis.lineage_graph import LineageGraph
    from .workspace import _stamp

    started = time.monotonic()
    index = LineageIndex()
    stamps = workspace.tree_stamps()
    reports: list[dict[str, Any]] = []

    def compute(path: Path, parsed: ParsedProgram, display: str) -> dict[str, Any]:
        units: list[dict[str, Any]] = []
        for unit, _depth in _units_with_depth(parsed.ast):
            name = unit.program_name or "<unnamed>"
            try:
                report = parsed.report(
                    "lineage", unit, functools.partial(_field_flow, unit)
                )
                report = apply_source_map(report, parsed.source_map)
            except Exception as exc:  # noqa: BLE001
                _analyzer_failed(index, display, f"field lineage of {name}", exc)
                units.append({"problem": f"{display}: {name}: no lineage report"})
                continue
            edges = []
            for edge in report.edges:
                line = edge.origin_line or edge.line
                if not line:
                    continue
                file = (
                    workspace.display(edge.origin_file) if edge.origin_file else display
                )
                edges.append([line, edge.kind, edge.statement, file])
            units.append({"report": report.to_dict(), "edges": edges})
        return {"units": units, "expanded": bool(parsed.source_map)}

    for path, facts in _per_file(workspace, index, stamps, "lineage", compute):
        if facts is None:
            continue
        for unit_facts in facts["units"]:
            if "problem" in unit_facts:
                index.problems.append(unit_facts["problem"])
                continue
            data = unit_facts["report"]
            program = str(data.get("program_id") or "").upper()
            reports.append(data)
            if program in index.program_files:
                continue  # LineageGraph keeps the first; its caveat says so
            index.program_files[program] = workspace.display(path)
            if facts["expanded"]:
                index.expanded.add(program)
            for line, kind, statement, file in unit_facts["edges"]:
                key = (program, line, kind, statement)
                if key in index.edge_files and index.edge_files[key] != file:
                    index.edge_files[key] = None  # ambiguous: never guess
                else:
                    index.edge_files[key] = file

    bindings: list[Any] = []
    passthroughs: list[Any] = []
    jcl_caveats: list[str] = []
    jcl = workspace.files_named((".jcl", ".job"))
    index.jcl_files = [workspace.display(p) for p in jcl]
    for path in jcl:
        stamps[str(path)] = _stamp(str(path))
    proc_dirs, skipped_procs = workspace.proc_directories()
    if skipped_procs:
        index.problems.append(
            "proc_path folders outside the workspace were not searched: "
            + ", ".join(skipped_procs)
        )
    # The libraries the JCL tools expand from too: proc_path folders first,
    # then PROCLIB-named folders, JCLLIB-named folders and .prc / .proc ones.
    from .jcl_tools import jcllib_directories, procedure_libraries

    libraries = procedure_libraries(workspace)
    # A .jcl member of a procedure library is a procedure, not a job.
    jcl = [p for p in jcl if p.parent not in libraries.configured]
    index.jcl_files = [workspace.display(p) for p in jcl]
    proc_dirs = list(
        dict.fromkeys(
            proc_dirs
            + libraries.configured
            + jcllib_directories(libraries, jcl)
            + libraries.discovered
        )
    )
    for folder in proc_dirs:
        # The folder itself (a PROC added or removed) and each member in it.
        stamps[str(folder)] = _stamp(str(folder))
        if folder.is_dir():
            for member in folder.iterdir():
                if member.is_file():
                    stamps[str(member)] = _stamp(str(member))
    if jcl:
        try:
            from ..analysis.lineage_jcl import bindings_from_jobs, load_jobs

            jobs, problems = load_jobs(jcl, proc_path=proc_dirs)
            if not proc_dirs and any("PROCs not expanded" in p for p in problems):
                problems.append(
                    "cataloged PROCs are looked up in .prc / .proc files, "
                    "folders named like a PROCLIB or for a JCLLIB library, "
                    "and the folders cobol.yml lists as project.proc_path; "
                    "there is none under the root"
                )
        except ImportError:
            index.jcl_note = (
                f"{len(jcl)} JCL file(s) under the root were not read: "
                "jcl-parser is not installed (pip install 'cobol-parser[jcl]'), "
                "so no file is joined to another program through a dataset"
            )
        else:
            found, carried = bindings_from_jobs(jobs, jcl_caveats)
            bindings += found
            passthroughs += carried
            index.problems += [str(p) for p in problems]
    index.graph = LineageGraph(
        reports, bindings, passthroughs, join_caveats=jcl_caveats
    )
    index.seconds = time.monotonic() - started
    return index, stamps


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def health_index(workspace: Workspace) -> HealthIndex:
    def build() -> tuple[HealthIndex, dict[str, Stamp]]:
        return _build_health(workspace)

    index: HealthIndex = workspace.index("health", build)
    return index


def _build_health(workspace: Workspace) -> tuple[HealthIndex, dict[str, Stamp]]:
    from ..analysis.lint import stamp_report_origins
    from ..scan import (
        FileScan,
        ScanReport,
        UnitScan,
        _stamp_body_origins,
        cross_file_clone_groups,
    )

    started = time.monotonic()
    index = HealthIndex()
    stamps = workspace.tree_stamps()
    scan = ScanReport()
    expanded: set[str] = set()

    def compute(path: Path, parsed: ParsedProgram, display: str) -> dict[str, Any]:
        units: list[dict[str, Any]] = []
        for unit, depth in _units_with_depth(parsed.ast):
            name = unit.program_name or "<unnamed>"
            try:
                redundancy = parsed.report(
                    "redundancy", unit, functools.partial(_redundancy, unit)
                )
                debt = parsed.report(
                    "debt", unit, functools.partial(_debt, parsed, unit, redundancy)
                )
            except Exception as exc:  # noqa: BLE001
                _analyzer_failed(index, display, f"health of {name}", exc)
                continue
            fingerprints = stamp_report_origins(redundancy.to_dict(), parsed.source_map)
            if parsed.source_map:
                # A body COPYed under each program's own header is one
                # source, as in ``scan`` (#470).
                _stamp_body_origins(fingerprints, parsed.source_map)
            units.append(
                {
                    "row": {
                        "program": unit.program_name,
                        "unit_kind": unit.unit_kind,
                        "file": display,
                        "depth": depth,
                        "grade": debt.grade,
                        "score": debt.score,
                    },
                    "name": name,
                    "depth": depth,
                    "fingerprints": fingerprints,
                }
            )
        return {"units": units, "expanded": bool(parsed.source_map)}

    for path, facts in _per_file(workspace, index, stamps, "health", compute):
        if facts is None:
            continue
        if facts["expanded"]:
            expanded.add(str(path))
        file_scan = FileScan(path=str(path))
        for unit_facts in facts["units"]:
            index.units.append(unit_facts["row"])
            file_scan.units.append(
                UnitScan(
                    program_name=unit_facts["name"],
                    depth=unit_facts["depth"],
                    reports={"redundancy": unit_facts["fingerprints"]},
                )
            )
        scan.files.append(file_scan)

    for group in cross_file_clone_groups(scan):
        members = []
        for member in group.members:
            location: dict[str, Any] | None
            if member.origin_file and member.origin_line:
                location = {
                    "file": workspace.display(member.origin_file),
                    "line": member.origin_line,
                }
            elif member.path not in expanded and member.line:
                location = {"file": workspace.display(member.path), "line": member.line}
            else:
                location = None
            members.append(
                {
                    "program": member.program_name,
                    "paragraph": member.paragraph,
                    "location": location,
                }
            )
        index.clones.append(
            {
                "clone_type": group.clone_type,
                "statement_count": group.statement_count,
                "copies": group.source_count,
                "members": members,
            }
        )
    index.seconds = time.monotonic() - started
    return index, stamps


def _field_flow(unit: CobolProgram) -> Any:
    from ..analysis.field_lineage import FieldFlowAnalyzer

    return FieldFlowAnalyzer().analyze(unit)


def _redundancy(unit: CobolProgram) -> Any:
    from ..analysis.redundancy import RedundancyAnalyzer

    return RedundancyAnalyzer().analyze(unit)


def _debt(parsed: ParsedProgram, unit: CobolProgram, redundancy: Any) -> Any:
    """The health score, sharing the flow graph and redundancy report the
    other tools already computed (the same key as ``program_brief``'s)."""
    from ..analysis.technical_debt import TechnicalDebtAnalyzer
    from .tools import _flow

    return TechnicalDebtAnalyzer().analyze(
        unit, flow_report=_flow(parsed, unit), redundancy_report=redundancy
    )
