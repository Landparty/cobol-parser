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

Every index is assembled from per-file facts (:mod:`.facts`): each program
is parsed once, through the workspace's own settings (``cobol.yml``'s
copybook paths, source format and ``>>DEFINE`` symbols), and that one parse
feeds all of them; after an edit only the changed files are parsed again.
Only small facts are kept: a root of thousands of programs never has more
than one AST live per worker.

A program that cannot be parsed is named, never skipped silently: every
index carries ``failed`` (file -> why) and the per-file caveats of the ones
that parsed with recovery or with a COPY left unexpanded.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..models.program import CobolProgram
from .envelope import Caveat
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
    #: ``COBOL``, or ``PL/I`` / ``assembler`` for a source read through a
    #: sibling parser (:mod:`.languages`).
    language: str = "COBOL"
    #: The services it requests itself (``CICS``, ``DB2 SQL``, ``IMS``,
    #: ``MQ``), and whether its LINKAGE SECTION declares DFHCOMMAREA:
    #: what ``RunsAs`` reads.
    services: list[str] = field(default_factory=list)
    commarea: bool = False

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
    #: MEMBER -> every COPY of it in a program file: {file, line}; a PL/I
    #: ``%INCLUDE`` or an assembler ``COPY`` adds ``language``.
    copy_sites: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Language -> source files of it read through a sibling parser.
    other_language_files: dict[str, int] = field(default_factory=dict)
    #: Language -> files of it left unread: its parser is not installed.
    not_installed: dict[str, list[str]] = field(default_factory=dict)

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


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------


def programs_index(workspace: Workspace) -> ProgramsIndex:
    def build() -> tuple[ProgramsIndex, dict[str, Stamp]]:
        return _build_programs(workspace)

    index: ProgramsIndex = workspace.index("programs", build)
    return index


def _build_programs(workspace: Workspace) -> tuple[ProgramsIndex, dict[str, Stamp]]:
    from ..analysis.codebase import CodebaseGraphBuilder
    from .facts import surveyed

    started = time.monotonic()
    index = ProgramsIndex()
    stamps = workspace.tree_stamps()
    all_facts = surveyed(workspace, index, stamps)
    for facts in all_facts:
        index.units.extend(facts.units)
    builder = CodebaseGraphBuilder(copybook_paths=list(workspace.config.copybook_path))
    index.graph = builder.assemble(f.graph_part for f in all_facts)
    for file, sites in index.graph.copy_sites.items():
        display = workspace.display(file)
        for member, line in sites:
            index.copy_sites.setdefault(member, []).append(
                {"file": display, "line": line}
            )
    _absorb_other_languages(workspace, index, stamps)
    index.seconds = time.monotonic() - started
    return index, stamps


def _absorb_other_languages(
    workspace: Workspace, index: ProgramsIndex, stamps: dict[str, Stamp]
) -> None:
    """The PL/I and assembler programs under the root, as units of the
    index and edges of its call graph: a CALL from COBOL to an assembler
    routine then reaches a program in the workspace, and the routine's own
    CALLs count in ``calls`` / ``called_by`` and in the cycles."""
    from ..analysis.codebase import (
        CALL_KIND_CALL,
        CALL_KIND_CICS_LINK,
        CALL_KIND_CICS_XCTL,
        CallEdge,
    )
    from .languages import languages_index

    languages = languages_index(workspace)
    index.not_installed = dict(languages.not_installed)
    for source in languages.sources:
        stamps[source.path] = source.stamp
        index.files.append(source.display)
        for caveat in source.caveats:
            index.note(source.display, caveat)
        if source.failed is not None:
            index.failed[source.display] = source.failed
            continue
        index.other_language_files[source.language] = (
            index.other_language_files.get(source.language, 0) + 1
        )
        index.units.append(
            UnitFacts(
                program_id=source.program_id,
                file=source.display,
                depth=0,
                graph_id=source.program_id,
                entries=list(source.entries),
                calls=source.calls,
                language=source.language,
                services=sorted({str(s.get("kind")) for s in source.services}),
            )
        )
        for include in source.includes:
            site = dict(include.get("location") or {"file": source.display})
            site["language"] = source.language
            index.copy_sites.setdefault(include["member"], []).append(site)

    graph = index.graph
    declared = {
        (u.graph_id or u.program_id).upper() for u in index.units if u.is_call_target
    }
    # A CALL to an assembler ENTRY name, a PL/I procedure's member name, ...
    # reaches that program: the same rule COBOL's ENTRY names follow (#521).
    by_entry: dict[str, str] = {}
    for unit in index.units:
        if unit.language == "COBOL":
            continue
        for entry in unit.entries:
            if entry not in declared:
                by_entry.setdefault(entry, unit.program_id.upper())
    edges = []
    for edge in graph.call_edges:
        owner = by_entry.get(edge.callee)
        if owner is not None:
            edge = CallEdge(
                caller=edge.caller,
                callee=owner,
                is_dynamic=edge.is_dynamic,
                resolved=edge.resolved,
                kind=edge.kind,
                entry=edge.callee,
            )
        edges.append(edge)
    kinds = {
        "EXEC CICS LINK": CALL_KIND_CICS_LINK,
        "EXEC CICS XCTL": CALL_KIND_CICS_XCTL,
    }
    for unit in index.units:
        if unit.language == "COBOL":
            continue
        caller = unit.program_id.upper()
        for row in unit.calls:
            kind = kinds.get(str(row.get("via")), CALL_KIND_CALL)
            if row.get("dynamic"):
                targets = [str(c).upper() for c in row.get("candidates") or []]
                resolved = bool(row.get("candidates_complete"))
            else:
                targets = [str(row.get("program") or "").upper()]
                resolved = True
            for target in targets:
                if not target:
                    continue
                owner = target if target in declared else by_entry.get(target)
                edges.append(
                    CallEdge(
                        caller=caller,
                        callee=owner or target,
                        is_dynamic=bool(row.get("dynamic")),
                        resolved=resolved,
                        kind=kind,
                        entry=target if owner and owner != target else None,
                    )
                )
    graph.call_edges = sorted(set(edges), key=CallEdge._sort_key)


# ---------------------------------------------------------------------------
# lineage
# ---------------------------------------------------------------------------


def lineage_index(workspace: Workspace) -> LineageIndex:
    def build() -> tuple[LineageIndex, dict[str, Stamp]]:
        return _build_lineage(workspace)

    index: LineageIndex = workspace.index("lineage", build)
    return index


def _build_lineage(workspace: Workspace) -> tuple[LineageIndex, dict[str, Stamp]]:
    from ..analysis.lineage_graph import LineageGraph
    from .facts import surveyed
    from .workspace import _stamp

    started = time.monotonic()
    index = LineageIndex()
    stamps = workspace.tree_stamps()
    reports: list[dict[str, Any]] = []
    for facts in surveyed(workspace, index, stamps, heavy=True):
        index.problems += facts.lineage_problems
        for unit in facts.lineage:
            reports.append(unit.report)
            if unit.program in index.program_files:
                continue  # LineageGraph keeps the first; its caveat says so
            index.program_files[unit.program] = facts.display
            if facts.expanded:
                index.expanded.add(unit.program)
            for key, file in unit.edge_files:
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
    from .tools.jcl_index import jcllib_directories, procedure_libraries

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
    from ..scan import FileScan, ScanReport, UnitScan, cross_file_clone_groups
    from .facts import surveyed

    started = time.monotonic()
    index = HealthIndex()
    stamps = workspace.tree_stamps()
    scan = ScanReport()
    expanded: set[str] = set()
    for facts in surveyed(workspace, index, stamps):
        if facts.failed is not None:
            continue
        if facts.expanded:
            expanded.add(facts.path)
        index.units.extend(facts.health)
        file_scan = FileScan(path=facts.path)
        for name, depth, fingerprints in facts.fingerprints:
            file_scan.units.append(
                UnitScan(
                    program_name=name,
                    depth=depth,
                    reports={"redundancy": fingerprints},
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
    from .tools.common import _flow

    return TechnicalDebtAnalyzer().analyze(
        unit, flow_report=_flow(parsed, unit), redundancy_report=redundancy
    )


#: How many CALL levels :func:`call_chain` follows below the program run.
CALL_CHAIN_DEPTH = 6


def call_chain(
    workspace: Workspace, program: str, max_depth: int = CALL_CHAIN_DEPTH
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every program *program* runs through its CALLs, LINKs and XCTLs,
    breadth first, in any language: one row per program reached (``program``,
    ``language`` and ``file`` when it is under the root, the ``called_by``
    program and ``via``, ``dynamic`` for a target taken from a data item, and
    ``depth``, 1 for a direct callee, and ``at``, the first call site).
    A program reached from several callers is listed once, the others in
    ``also_called_by``. Also the notes on what could not be followed (a
    dynamic CALL whose targets are not all known)."""
    index = programs_index(workspace)
    other = workspace.other_sources()
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    seen = {program.upper()}
    listed: dict[str, dict[str, Any]] = {}
    frontier = [program.upper()]
    for depth in range(1, max_depth + 1):
        following: list[str] = []
        for caller in frontier:
            for unit in index.units_named(caller):
                if unit.depth:
                    continue
                for row in unit.calls:
                    targets = (
                        [str(c).upper() for c in row.get("candidates") or []]
                        if row.get("dynamic")
                        else [str(row.get("program") or "").upper()]
                    )
                    if row.get("dynamic") and not row.get("candidates_complete"):
                        notes.append(
                            f"{caller} ({unit.file}): {row.get('via')} "
                            f"{row.get('program')} has targets that could not "
                            "all be traced"
                        )
                    for target in targets:
                        if not target:
                            continue
                        if target in seen:
                            again = listed.get(target)
                            if again is not None and caller != again["called_by"]:
                                others = again.setdefault("also_called_by", [])
                                if caller not in others:
                                    others.append(caller)
                            continue
                        seen.add(target)
                        hit: dict[str, Any] = {
                            "program": target,
                            "called_by": caller,
                            "via": row.get("via"),
                            "depth": depth,
                        }
                        sites = row.get("sites") or []
                        if sites and sites[0].get("location"):
                            where = sites[0]["location"]
                            hit["at"] = f"{where['file']}:{where['line']}"
                        listed[target] = hit
                        if row.get("dynamic"):
                            hit["dynamic"] = True
                        units = [u for u in index.units_named(target) if not u.depth]
                        if units:
                            hit["language"] = units[0].language
                            hit["file"] = units[0].file
                            if len(units) > 1:
                                hit["also_in"] = [
                                    {"file": u.file, "language": u.language}
                                    for u in units[1:]
                                ]
                            following.append(target)
                        elif target in other:
                            path, language = other[target][0]
                            hit["language"] = language
                            hit["file"] = workspace.display(path)
                            hit["analyzed"] = False
                        else:
                            hit["in_workspace"] = False
                        rows.append(hit)
        if not following:
            break
        frontier = following
    else:
        if frontier:
            notes.append(
                f"the chain was followed {max_depth} CALL levels deep; "
                "programs below that are not listed"
            )
    return rows, notes


#: DL/I call interfaces: a CALL to one is an IMS request, not a program.
_DLI_INTERFACES = frozenset({"CBLTDLI", "AIBTDLI", "CEETDLI", "AERTDLI"})


def unit_services(unit: Any) -> list[str]:
    """The services a COBOL unit requests itself: ``CICS``, ``DB2 SQL``,
    ``IMS`` (EXEC DLI or a CALL to a DL/I interface), the vocabulary of a
    PL/I or assembler source's ``services``."""
    from .tools.common import _own_statements

    found: set[str] = set()
    for statement in _own_statements(unit):
        kind = type(statement).__name__
        if kind == "ExecCicsStatement":
            found.add("CICS")
        elif kind == "ExecSQLStatement":
            found.add("DB2 SQL")
        elif kind == "ExecImsStatement":
            found.add("IMS")
        elif kind == "CallStatement":
            target = str(getattr(statement, "called_program", "") or "").upper()
            if target.strip("'\"") in _DLI_INTERFACES:
                found.add("IMS")
    return sorted(found)


def unit_commarea(unit: Any) -> bool:
    """Whether the unit's LINKAGE SECTION declares DFHCOMMAREA: a program
    CICS LINKs or XCTLs to, whether or not it issues EXEC CICS itself."""
    from .tools.structure import _walk_data_items

    return any(
        found.section == "LINKAGE" and found.item.name.upper() == "DFHCOMMAREA"
        for found in _walk_data_items(unit)
    )


class RunsAs:
    """Whether a program runs online under CICS, in batch, or under IMS,
    from what the index and the JCL know, with the evidence: its own EXEC
    CICS or DFHCOMMAREA, a JCL step that runs it, else what its callers
    are. Absent when nothing says, never guessed from a name."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.index = programs_index(workspace)
        self._callers: dict[str, set[str]] | None = None
        self._jcl: set[str] | None = None
        self._held: dict[str, dict[str, str] | None] = {}

    def callers(self) -> dict[str, set[str]]:
        if self._callers is None:
            self._callers = {}
            for unit in self.index.units:
                for row in unit.calls:
                    targets = {str(row.get("program") or "").upper()}
                    if row.get("dynamic"):
                        targets = {str(c).upper() for c in row.get("candidates") or []}
                    for target in targets - {""}:
                        self._callers.setdefault(target, set()).add(
                            unit.program_id.upper()
                        )
        return self._callers

    def jcl(self) -> set[str]:
        if self._jcl is None:
            from .tools.jcl_index import programs_run_by_jcl

            self._jcl = programs_run_by_jcl(self.workspace)
        return self._jcl

    def own(self, program: str) -> dict[str, str] | None:
        """What the program itself says: EXEC CICS, DFHCOMMAREA, a JCL
        step, DL/I calls."""
        units = self.index.units_named(program)
        services = {s for u in units for s in u.services}
        if "CICS" in services:
            return {"runs_as": "online (CICS)", "because": "it issues EXEC CICS"}
        if any(u.commarea for u in units):
            return {
                "runs_as": "online (CICS)",
                "because": "its LINKAGE SECTION declares DFHCOMMAREA, the "
                "COMMAREA a CICS LINK or XCTL passes",
            }
        if program.upper() in self.jcl():
            return {"runs_as": "batch", "because": "a JCL step runs it"}
        if "IMS" in services:
            return {"runs_as": "IMS", "because": "it issues DL/I calls"}
        return None

    def of(self, program: str) -> dict[str, str] | None:
        name = program.upper()
        if name not in self._held:
            self._held[name] = self._find(name)
        return self._held[name]

    def _find(self, name: str) -> dict[str, str] | None:
        found = self.own(name)
        if found is not None:
            return found
        by_kind: dict[str, list[str]] = {}
        for caller in sorted(self.callers().get(name, set()) - {name}):
            theirs = self.own(caller)
            if theirs is not None:
                by_kind.setdefault(theirs["runs_as"], []).append(caller)
        if not by_kind:
            return None
        kinds = sorted(by_kind)
        named = "; ".join(
            f"{kind}: {', '.join(by_kind[kind][:5])}"
            + (f" and {len(by_kind[kind]) - 5} more" if len(by_kind[kind]) > 5 else "")
            for kind in kinds
        )
        return {
            "runs_as": " and ".join(kinds),
            "because": f"a subroutine; its callers run {named}",
        }
