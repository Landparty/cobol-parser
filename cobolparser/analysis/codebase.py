"""
Whole-codebase call-graph and copybook-dependency analysis.

Every analyzer elsewhere in :mod:`cobolparser.analysis` is *program*-scoped:
it answers a question about one compilation unit. This module is the
cross-program one. It walks a whole tree of COBOL source, parses every file
through :mod:`cobolparser.batch` (parallel, with per-file fault isolation),
and aggregates the results into a single graph with two kinds of edge:

- **call edges** -- ``program A calls program B``, from static ``CALL "B"``
  and from dynamic ``CALL WS-TARGET`` resolved through
  :class:`~.value_tracker.DynamicCallAnalyzer`. A dynamic call whose value
  set that analyzer could not fully resolve still contributes its known
  targets, each marked ``resolved=False`` so the edge set is never mistaken
  for an exhaustive one. ``EXEC CICS LINK PROGRAM(...)`` and ``EXEC CICS
  XCTL PROGRAM(...)`` -- the program-to-program edges of a CICS shop -- are
  call edges too, told apart by :attr:`CallEdge.kind` (``call`` /
  ``cics-link`` / ``cics-xctl``) so ``callers_of`` and copybook-free impact
  questions see them with no extra step (#315). A quoted ``PROGRAM('X')`` is
  a static edge; a data-name operand is resolved through the same
  :class:`~.value_tracker.DynamicCallAnalyzer` value set a dynamic CALL
  gets, or reported unresolved.
- **copy edges** -- ``program A copies member X``, and ``member X copies
  member Y`` for nested copybooks. A DB2 ``EXEC SQL INCLUDE X END-EXEC`` is
  a copy edge too, with the same ``COPY`` label and the same unresolved-member
  reporting: it is how SQLCA and DCLGEN members are normally pulled in, so
  leaving it out made "what uses this DCLGEN?" answer nothing (#295). The
  output does not say which of the two produced an edge. An INCLUDE of
  ``SQLCA`` or ``SQLDA`` that is not on the path is not reported unresolved,
  since the precompiler supplies those. These are collected by re-scanning each
  source with :func:`~cobolparser.preprocess.copy_statement_parser.extract_copy_statements`
  rather than from an expanded parse, because expansion *consumes* the COPY
  statement and discards exactly the edge we are after. Members are resolved
  to real files through the same :class:`~cobolparser.preprocess.path_resolver.PathResolver`
  the expander uses, so a nested chain is followed to its leaves and a
  circular pair (``A COPY B``, ``B COPY A``) is reported, not looped on.

Two rules hold throughout:

1. **A quiet report is never a complete one.** A file that would not parse
   lands in :attr:`CodebaseGraph.errors` (and still contributes its COPY
   edges, since the COPY scan does not need a successful parse); a COPY
   whose member is not on the search path, a dynamic CALL with no resolvable
   target, a duplicate ``PROGRAM-ID``, a file holding several program units
   -- each lands in :attr:`CodebaseGraph.unresolved` with a reason. Nothing
   is dropped silently.
2. **Determinism.** The same tree produces byte-identical ``to_dict()``,
   ``to_dot()`` and ``to_mermaid()`` output. Files are parsed in sorted
   order, every emitted list is sorted, and no ``ProcessPoolExecutor``
   completion order reaches the output.

Example::

    from cobolparser.analysis.codebase import (
        CodebaseGraphBuilder,
        CopybookImpactAnalyzer,
    )

    graph = CodebaseGraphBuilder(
        copybook_paths=["./copybooks"]
    ).build_from_directory("./src")

    graph.callers_of("VALIDATE")      # who calls it
    graph.programs_using("CUSTOMER")  # who would a change to CUSTOMER.cpy hit
    graph.cycles()                    # mutually recursive program groups
    print(graph.to_mermaid())

    impact = CopybookImpactAnalyzer(graph).analyze("CUSTOMER")
    impact.chains                     # ["PROG1", "OUTER", "CUSTOMER"], ...
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._lines import split_source_lines
from ..batch import BatchResult, parse_files, parse_files_with_copybooks
from ..models.program import CobolProgram
from ..models.statements.base import CobolStatement
from ..models.statements.call import CallStatement, EntryStatement
from ..parsers.statements.ibm_exec_statements import ExecCicsStatement
from ..preprocess import PreprocessingError
from ..preprocess.copy_statement_parser import extract_copy_statements
from ..preprocess.copybook_expander import read_program_source
from ..preprocess.models import CopybookSearchPath
from ..preprocess.path_resolver import PathResolver
from ._names import callee_names
from .value_tracker import DynamicCallAnalyzer

__all__ = [
    "CallEdge",
    "CodebaseGraph",
    "CodebaseGraphBuilder",
    "CopyEdge",
    "CopybookImpactAnalyzer",
    "ImpactReport",
    "ProgramNode",
]

#: Members the DB2 precompiler supplies itself. An ``EXEC SQL INCLUDE`` of one
#: that is not on the copybook path is normal, not a gap: it still gets its
#: edge, but no ``unresolved`` note. This is narrower than the copybook
#: expander, which lets *every* unresolvable INCLUDE through silently: here a
#: missing DCLGEN is still a gap worth reporting, and so is a COPY of either.
_PRECOMPILER_MEMBERS = frozenset({"SQLCA", "SQLDA"})

#: File extensions :meth:`CodebaseGraphBuilder.build_from_directory` treats as
#: COBOL program source. Matched case-insensitively.
DEFAULT_PROGRAM_EXTENSIONS: tuple[str, ...] = (".cbl", ".cob", ".cobol")

#: Suffixes stripped from a member name given as a file name ("CUSTOMER.cpy"
#: and "CUSTOMER" address the same member).
_MEMBER_SUFFIXES = frozenset({".cpy", ".copy", ".cbl", ".cob", ".cobol"})

#: Files parsed per batch. Facts are extracted and the ASTs dropped between
#: chunks so a multi-thousand-file tree never has every AST live at once.
_DEFAULT_CHUNK_SIZE = 200

#: What the parser names a program whose PROGRAM-ID it could not read.
_UNNAMED_PROGRAM = "UNKNOWN"

#: :attr:`CallEdge.kind` values. ``call`` is a COBOL ``CALL``; the CICS kinds
#: are ``EXEC CICS LINK`` (returns to the linking program) and ``EXEC CICS
#: XCTL`` (transfers control for good -- the linking program is gone).
CALL_KIND_CALL = "call"
CALL_KIND_CICS_LINK = "cics-link"
CALL_KIND_CICS_XCTL = "cics-xctl"

#: CICS commands that name another program to run, by :attr:`CallEdge.kind`.
_CICS_TRANSFER_KINDS = {"LINK": CALL_KIND_CICS_LINK, "XCTL": CALL_KIND_CICS_XCTL}

#: A data-item declaration (level number, then name) whose name carries an
#: IBM ``:TAG:`` REPLACING placeholder, e.g. ``05 :Q:-AMT PIC 9(5).``
_PLACEHOLDER_DECLARATION = re.compile(
    r"(?:^|\s)\d{1,2}\s+([^\s.]*:[A-Z0-9_-]+:[^\s.]*)", re.IGNORECASE
)

#: Below this many files the sequential fast path in :func:`parse_files` beats
#: paying process-spawn cost.
_PARALLEL_THRESHOLD = 8


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def _normalize_program_name(name: str) -> str:
    """Canonical form of a program name: unquoted, stripped, uppercased."""
    text = name.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text.strip().upper()


def _nested_in(unit: Any) -> Any:
    """The PROGRAM unit *unit* is nested in, or None for an outermost or
    stacked program and for an object-oriented unit (#532)."""
    if getattr(unit, "unit_kind", "PROGRAM") != "PROGRAM":
        return None
    enclosing = getattr(unit, "enclosing_program", None)
    if enclosing is None or getattr(enclosing, "unit_kind", "PROGRAM") != "PROGRAM":
        return None
    return enclosing


def program_graph_ids(units: Iterable[Any], path: str) -> dict[int, str]:
    """Each unit's program id in the graph, keyed by ``id(unit)``.

    A nested program is not in the global namespace: only programs of its
    own compilation unit can CALL it, so its id is qualified by the programs
    it is nested in (``OUTER/INNER``), and a CALL reaches it only when
    COBOL scope says so (#532). An outermost or stacked unit keeps its
    PROGRAM-ID (or, with none, the file name's).
    """
    ids: dict[int, str] = {}
    for unit in units:
        declared = _normalize_program_name(unit.program_name or "")
        named = bool(declared) and declared != _UNNAMED_PROGRAM
        program_id = declared if named else _program_id_from_path(path)
        enclosing = _nested_in(unit)
        if enclosing is not None and id(enclosing) in ids:
            program_id = f"{ids[id(enclosing)]}/{program_id}"
        ids[id(unit)] = program_id
    return ids


def _normalize_member(name: str) -> str:
    """Canonical form of a copybook member name.

    Accepts a bare member (``CUSTOMER``), a file name (``CUSTOMER.cpy``) or a
    full path (``./copybooks/CUSTOMER.cpy``) so a CLI can pass through
    whatever the user typed.
    """
    text = name.strip().strip("\"'").strip()
    if not text:
        return ""
    base = os.path.basename(text.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    if ext.lower() in _MEMBER_SUFFIXES and stem:
        base = stem
    return base.upper()


def _normalize_library(name: str | None) -> str | None:
    """A ``COPY ... OF/IN`` library name, unquoted (None when absent).

    Case is kept: the resolver matches it against a directory name, as the
    expander does.
    """
    if name is None:
        return None
    text = name.strip().strip("\"'").strip()
    return text or None


def _program_id_from_path(path: str) -> str:
    """Fallback program id for a file whose PROGRAM-ID could not be read."""
    return Path(path).stem.upper() or "UNKNOWN"


# ---------------------------------------------------------------------------
# Graph elements
# ---------------------------------------------------------------------------


@dataclass
class ProgramNode:
    """One program unit found in the tree.

    Attributes:
        program_id: The ``PROGRAM-ID``, uppercased. For a file that would not
            parse this is the file stem instead (recorded as such in
            :attr:`CodebaseGraph.unresolved`).
        path: The file the unit was found in.
        calls: Program ids this unit CALLs, LINKs or XCTLs to -- static
            targets plus every resolved dynamic target. Sorted, deduplicated.
        copies: Copybook members this unit COPYs *directly*. Sorted,
            deduplicated.
        parse_failed: True when the file produced no AST; ``calls`` is then
            empty and unknown, not empty and known.
        entries: The alternate ``ENTRY 'name'`` names the unit declares,
            uppercased and sorted: a ``CALL 'name'`` reaches this program
            (#521).
    """

    program_id: str
    path: str
    calls: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)
    parse_failed: bool = False
    entries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "program_id": self.program_id,
            "path": self.path,
            "calls": list(self.calls),
            "copies": list(self.copies),
            "parse_failed": self.parse_failed,
        }
        if self.entries:
            out["entries"] = list(self.entries)
        return out


@dataclass(frozen=True)
class CallEdge:
    """A ``caller CALLs callee`` edge between two programs.

    ``resolved`` is False when the target came from a dynamic CALL whose
    possible-value set :class:`~.value_tracker.DynamicCallAnalyzer` marked
    incomplete: the edge is real, but the *set* of edges from that call site
    is not exhaustive.

    ``kind`` says how control reaches the callee: ``call`` (a COBOL
    ``CALL``), ``cics-link`` (``EXEC CICS LINK PROGRAM``) or ``cics-xctl``
    (``EXEC CICS XCTL PROGRAM``). ``is_dynamic`` means the same for all
    three: the target came from a data-name, not a literal.
    """

    caller: str
    callee: str
    is_dynamic: bool = False
    resolved: bool = True
    kind: str = CALL_KIND_CALL
    #: The alternate ``ENTRY`` name the CALL used when it reached *callee*
    #: through one rather than through its PROGRAM-ID (#521).
    entry: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "caller": self.caller,
            "callee": self.callee,
            "is_dynamic": self.is_dynamic,
            "resolved": self.resolved,
            "kind": self.kind,
        }
        if self.entry is not None:
            out["entry"] = self.entry
        return out

    def _sort_key(self) -> tuple[str, str, str, bool, bool, str]:
        return (
            self.caller,
            self.callee,
            self.kind,
            self.is_dynamic,
            self.resolved,
            self.entry or "",
        )


@dataclass(frozen=True)
class CopyEdge:
    """A ``COPY`` dependency edge.

    ``program`` is a program id for a direct edge and the *outer member name*
    for a nested one (``nested=True``), which is what makes a chain such as
    ``PROG1 -> OUTER -> INNER`` walkable in either direction.

    ``library`` is the ``OF``/``IN`` qualifier the COPY statement named, and
    ``parent_path`` (nested edges only) is the file of the outer member. Two
    libraries can each hold a member of one name, so a member name alone does
    not say which file a chain runs through; ``path`` / ``parent_path`` do.
    """

    program: str
    member: str
    path: str | None = None
    nested: bool = False
    library: str | None = None
    parent_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "member": self.member,
            "path": self.path,
            "nested": self.nested,
            "library": self.library,
            "parent_path": self.parent_path,
        }

    def _sort_key(self) -> tuple[bool, str, str, str, str, str]:
        return (
            self.nested,
            self.program,
            self.member,
            self.path or "",
            self.library or "",
            self.parent_path or "",
        )

    def _is_parent(self, parent: CopyEdge) -> bool:
        """Whether *parent* is the edge that pulled in the member this one is
        nested in -- by name, and by file once this edge knows its parent's.

        A nested edge with a ``parent_path`` came from reading that resolved
        file, so an unresolved edge of the same name is never its parent. Only
        a hand-built edge without ``parent_path`` matches by name alone.
        """
        if parent.member != self.program:
            return False
        if self.parent_path is None:
            return True
        return parent.path == self.parent_path


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


@dataclass
class GraphPart:
    """What one file contributes to a :class:`CodebaseGraph`
    (:meth:`CodebaseGraphBuilder.absorb`), picklable, so a file's part can be
    computed in a worker process or kept between builds while the file is
    unchanged."""

    path: str
    nodes: list[ProgramNode] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    copy_edges: list[CopyEdge] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    #: The program ids found in the file, outermost first; None when the
    #: parse result was missing, ``[]`` for a path that does not exist.
    unit_ids: list[str] | None = None
    #: The PROGRAM-IDs it declares, for the duplicate check across files.
    declared: list[str] = field(default_factory=list)
    #: (member, line) of each COPY written in the file.
    copy_sites: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class CodebaseGraph:
    """The aggregated dependency graph for a whole tree of COBOL source."""

    programs: list[ProgramNode] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    copy_edges: list[CopyEdge] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    #: Program file -> ``(member, line)`` of each COPY / EXEC SQL INCLUDE
    #: statement written in it, in source order: where a change to a member
    #: lands in each program. Not part of :meth:`to_dict`.
    copy_sites: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

    # -- queries ----------------------------------------------------------

    @property
    def program_ids(self) -> list[str]:
        """Every distinct program id in the tree, sorted."""
        return sorted({p.program_id for p in self.programs})

    @property
    def members(self) -> list[str]:
        """Every distinct copybook member referenced, sorted."""
        names: set[str] = set()
        for edge in self.copy_edges:
            names.add(edge.member)
            if edge.nested:
                names.add(edge.program)
        return sorted(names)

    def callers_of(self, program_id: str) -> list[str]:
        """Programs that CALL, LINK or XCTL to *program_id*, sorted and
        deduplicated."""
        wanted = _normalize_program_name(program_id)
        return sorted({e.caller for e in self.call_edges if e.callee == wanted})

    def callees_of(self, program_id: str) -> list[str]:
        """Programs *program_id* CALLs, LINKs or XCTLs to, sorted and
        deduplicated."""
        wanted = _normalize_program_name(program_id)
        return sorted({e.callee for e in self.call_edges if e.caller == wanted})

    def programs_using(self, member: str, *, transitive: bool = True) -> list[str]:
        """Programs that COPY *member*.

        With ``transitive=True`` (the default) a program that COPYs an outer
        member which itself COPYs *member* is included. Circular COPY chains
        are walked once, not looped on.
        """
        wanted = _normalize_member(member)
        if not wanted:
            return []
        direct = sorted(
            {e.program for e in self.copy_edges if e.member == wanted and not e.nested}
        )
        if not transitive:
            return direct

        # Walk up edge by edge rather than name by name: a nested edge reaches
        # only the programs whose COPY resolved to the *file* it sits in, not
        # every program copying some member of that name (#351).
        found: set[str] = set(direct)
        queue: list[CopyEdge] = [
            e for e in self.copy_edges if e.member == wanted and e.nested
        ]
        seen: set[CopyEdge] = set(queue)
        while queue:
            child = queue.pop()
            for edge in self.copy_edges:
                if not child._is_parent(edge):
                    continue
                if edge.nested:
                    if edge not in seen:
                        seen.add(edge)
                        queue.append(edge)
                else:
                    found.add(edge.program)
        return sorted(found)

    def cycles(self) -> list[list[str]]:
        """Call cycles between programs.

        Each entry is one strongly connected component of the call graph --
        the sorted membership of a mutually recursive group (or a single
        program that CALLs itself). A component with more than two members
        may contain several elementary cycles; they are reported as the one
        group they form, which is both bounded and deterministic.

        ``EXEC CICS XCTL`` edges are left out: XCTL ends the transferring
        program, so ``MENU XCTL ORDER``, ``ORDER XCTL MENU`` is the ordinary
        CICS menu loop, not recursion. ``LINK`` edges stay in -- a LINKed
        program returns, so a LINK cycle nests like a CALL cycle does.
        """
        adjacency: dict[str, set[str]] = {}
        for edge in self.call_edges:
            if edge.kind == CALL_KIND_CICS_XCTL:
                continue
            adjacency.setdefault(edge.caller, set()).add(edge.callee)
            adjacency.setdefault(edge.callee, set())

        # Iterative Tarjan: a deep call chain must not blow the Python stack.
        index_of: dict[str, int] = {}
        low_of: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        counter = 0
        components: list[list[str]] = []

        for root in sorted(adjacency):
            if root in index_of:
                continue
            work: list[tuple[str, list[str], int]] = [
                (root, sorted(adjacency[root]), 0)
            ]
            index_of[root] = low_of[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)

            while work:
                node, successors, position = work[-1]
                if position < len(successors):
                    work[-1] = (node, successors, position + 1)
                    successor = successors[position]
                    if successor not in index_of:
                        index_of[successor] = low_of[successor] = counter
                        counter += 1
                        stack.append(successor)
                        on_stack.add(successor)
                        work.append((successor, sorted(adjacency[successor]), 0))
                    elif successor in on_stack:
                        low_of[node] = min(low_of[node], index_of[successor])
                    continue

                work.pop()
                if work:
                    parent = work[-1][0]
                    low_of[parent] = min(low_of[parent], low_of[node])
                if low_of[node] == index_of[node]:
                    component: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1 or node in adjacency.get(node, set()):
                        components.append(sorted(component))

        return sorted(components)

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serializable form. Byte-identical for the same input tree."""
        cycles = self.cycles()
        return {
            "programs": [p.to_dict() for p in self.programs],
            "call_edges": [e.to_dict() for e in self.call_edges],
            "copy_edges": [e.to_dict() for e in self.copy_edges],
            "cycles": cycles,
            "unresolved": list(self.unresolved),
            "errors": [dict(e) for e in self.errors],
            "summary": {
                "program_count": len(self.programs),
                "call_edge_count": len(self.call_edges),
                "copy_edge_count": len(self.copy_edges),
                "member_count": len(self.members),
                "cycle_count": len(cycles),
                "unresolved_count": len(self.unresolved),
                "error_count": len(self.errors),
            },
        }

    # -- rendering --------------------------------------------------------

    def _render_nodes(self) -> tuple[list[str], list[str], list[str]]:
        """``(program ids, external callee ids, member names)``, each sorted."""
        program_ids = self.program_ids
        known = set(program_ids)
        external = sorted({e.callee for e in self.call_edges if e.callee not in known})
        return program_ids, external, self.members

    def _failed_ids(self) -> set[str]:
        return {p.program_id for p in self.programs if p.parse_failed}

    def _rendered_copy_edges(self) -> list[CopyEdge]:
        """Copy edges as the diagrams draw them: one per (program, member,
        nested), since a diagram has one node per member *name* and two
        libraries' members of one name would otherwise draw an edge twice."""
        seen: set[tuple[str, str, bool]] = set()
        edges: list[CopyEdge] = []
        for edge in self.copy_edges:
            key = (edge.program, edge.member, edge.nested)
            if key not in seen:
                seen.add(key)
                edges.append(edge)
        return edges

    def to_mermaid(self) -> str:
        """Render the graph as a Mermaid ``flowchart LR``.

        Node ids are sanitized the way :mod:`cobolparser.generators.flowchart`
        sanitizes them -- COBOL names are full of hyphens, which Mermaid reads
        as an arrow fragment rather than as part of an identifier.
        """
        programs, external, members = self._render_nodes()
        failed = self._failed_ids()
        ids = _NodeIds.for_nodes(programs, external, members)

        lines: list[str] = ["flowchart LR"]
        for pid in programs:
            label = f"{pid} (unparsed)" if pid in failed else pid
            lines.append(f'    {ids.program(pid)}["{_mermaid_label(label)}"]')
        for pid in external:
            lines.append(
                f'    {ids.program(pid)}(["{_mermaid_label(pid)} (external)"])'
            )
        for member in members:
            lines.append(f'    {ids.member(member)}[/"{_mermaid_label(member)}"/]')

        for edge in self.call_edges:
            label = _mermaid_label(_call_edge_label(edge))
            # Quoted label text: an unquoted "(" inside a Mermaid `|label|`
            # is read by the flowchart lexer as the start of a node shape,
            # not as literal text -- "CALL (dynamic)" breaks parsing bare.
            lines.append(
                f'    {ids.program(edge.caller)} -->|"{label}"|'
                f" {ids.program(edge.callee)}"
            )
        for copy_edge in self._rendered_copy_edges():
            source = (
                ids.member(copy_edge.program)
                if copy_edge.nested
                else ids.program(copy_edge.program)
            )
            label = _mermaid_label("COPY (nested)" if copy_edge.nested else "COPY")
            lines.append(f'    {source} -.->|"{label}"| {ids.member(copy_edge.member)}')

        if len(lines) == 1:
            lines.append('    EMPTY["No programs found"]')
        return "\n".join(lines)

    def to_dot(self) -> str:
        """Render the graph as a Graphviz DOT digraph.

        Ids are sanitized and every label is quoted, so a hyphenated COBOL
        name (illegal as a bare DOT identifier) survives intact.
        """
        programs, external, members = self._render_nodes()
        failed = self._failed_ids()
        ids = _NodeIds.for_nodes(programs, external, members)

        lines: list[str] = ["digraph codebase {"]
        lines.append("    rankdir=LR;")
        lines.append('    node [fontname="Courier New", fontsize=10, style=filled];')
        lines.append('    edge [fontname="Courier New", fontsize=9];')
        lines.append("")

        for pid in programs:
            fill = "#f8d7da" if pid in failed else "#cfe2ff"
            label = _dot_str(pid)
            if pid in failed:
                # The "\n" line break is DOT escape syntax and must reach the
                # output as-is: passed through _dot_str it became "\\n",
                # which Graphviz renders as a literal backslash-n (#274).
                label = f'{label[:-1]}\\n(unparsed)"'
            lines.append(
                f"    {ids.program(pid)} [label={label},"
                f' shape=box, fillcolor="{fill}", fontcolor="#000000"];'
            )
        for pid in external:
            lines.append(
                f"    {ids.program(pid)} [label={_dot_str(pid)},"
                ' shape=ellipse, fillcolor="#e9ecef", fontcolor="#000000"];'
            )
        for member in members:
            lines.append(
                f"    {ids.member(member)} [label={_dot_str(member)},"
                ' shape=note, fillcolor="#fff3cd", fontcolor="#000000"];'
            )

        if programs or external or members:
            lines.append("")
        else:
            lines.append('    EMPTY [label="No programs found"];')

        for edge in self.call_edges:
            attrs = f"label={_dot_str(_call_edge_label(edge))}"
            if not edge.resolved:
                attrs += ', style=dotted, color="#b02a37"'
            lines.append(
                f"    {ids.program(edge.caller)} ->"
                f" {ids.program(edge.callee)} [{attrs}];"
            )
        for copy_edge in self._rendered_copy_edges():
            source = (
                ids.member(copy_edge.program)
                if copy_edge.nested
                else ids.program(copy_edge.program)
            )
            label = "COPY (nested)" if copy_edge.nested else "COPY"
            lines.append(
                f"    {source} -> {ids.member(copy_edge.member)}"
                f" [label={_dot_str(label)}, style=dashed];"
            )

        lines.append("}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering helpers (same conventions as generators/flowchart.py)
# ---------------------------------------------------------------------------


def _sanitize_id(name: str) -> str:
    """Every character outside ``[A-Za-z0-9_]`` becomes ``_``.

    Mirrors :func:`cobolparser.generators.flowchart._sanitize_id`; kept local
    so this analyzer does not import the generators package (which pulls in
    the whole fixture-generation stack) just to render two diagrams.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if safe and safe[0].isdigit():
        safe = "N_" + safe
    return safe or "UNKNOWN"


def _program_node_id(program_id: str) -> str:
    return "P_" + _sanitize_id(program_id)


def _member_node_id(member: str) -> str:
    return "C_" + _sanitize_id(member)


class _NodeIds:
    """One diagram's mapping from a program or member name to a unique id.

    ``_sanitize_id`` is lossy: ``PAY#01`` / ``PAY@01`` / ``PAY$01`` and
    ``PAY-RTN`` / ``PAY_RTN`` all collide, which merged distinct programs
    into one node and drew false self-calls (#494, the codebase-graph twin
    of #266's ``flowchart._IdAllocator``). Every declaration and every edge
    endpoint asks this for its id, so one name always gets one id and two
    names never share one; a collision gets a numeric suffix (``P_PAY_01``,
    ``P_PAY_01_2``), and a diagram without collisions is unchanged.
    """

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], str] = {}
        self._taken: set[str] = set()

    @classmethod
    def for_nodes(
        cls, programs: list[str], external: list[str], members: list[str]
    ) -> _NodeIds:
        """Pre-allocated in declaration order: known programs keep the
        plain id over an external callee or a member of a colliding name."""
        ids = cls()
        for pid in [*programs, *external]:
            ids.program(pid)
        for member in members:
            ids.member(member)
        return ids

    def program(self, name: str) -> str:
        return self._get("P_", name)

    def member(self, name: str) -> str:
        return self._get("C_", name)

    def _get(self, prefix: str, name: str) -> str:
        key = (prefix, name)
        found = self._ids.get(key)
        if found is not None:
            return found
        base = prefix + _sanitize_id(name)
        chosen = base
        suffix = 2
        while chosen in self._taken:
            chosen = f"{base}_{suffix}"
            suffix += 1
        self._taken.add(chosen)
        self._ids[key] = chosen
        return chosen


def _mermaid_label(text: str) -> str:
    """Escape what Mermaid mangles inside a quoted label.

    ``"`` breaks the quoted-string lexer outright and its ``#quot;`` entity is
    not decoded on the SVG-text path, so it becomes an apostrophe; ``<``/``>``
    are silently swallowed by the label sanitizer unless entity-escaped.
    Same treatment as ``flowchart._escape_mermaid_label``.
    """
    return text.replace('"', "'").replace("<", "#lt;").replace(">", "#gt;")


def _dot_str(text: str) -> str:
    """Wrap *text* in double quotes, escaping backslashes and quotes."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _call_edge_label(edge: CallEdge) -> str:
    verb = {
        CALL_KIND_CICS_LINK: "CICS LINK",
        CALL_KIND_CICS_XCTL: "CICS XCTL",
    }.get(edge.kind, "CALL")
    if edge.entry is not None:
        verb = f"{verb} ENTRY {edge.entry}"
    if not edge.is_dynamic:
        return verb
    return f"{verb} (dynamic)" if edge.resolved else f"{verb} (dynamic, partial)"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class CodebaseGraphBuilder:
    """Builds a :class:`CodebaseGraph` from a set of COBOL source files.

    Args:
        copybook_paths: Directories to resolve COPY members against. Without
            them COPY edges are still emitted (the member names are in the
            source), but no member is resolved to a file and no *nested*
            COPY can be followed -- which is said once in
            :attr:`CodebaseGraph.unresolved` rather than left to be guessed.
        workers: Worker processes for the batch parse. ``None`` (default)
            lets small runs stay sequential and larger ones use every core.
            Ignored when ``copybook_paths`` is set, since copybook expansion
            runs in-process to share its caches.
        chunk_size: Files parsed per batch before their ASTs are dropped.
        encoding: Source encoding, passed through to the batch parser and to
            the COPY scan. None (default) detects it per file, the way a
            copybook's is detected (#522).
        debug_lines: Compile fixed-format debugging lines (``D`` in column
            7) as code, so a CALL written on one is an edge.
    """

    def __init__(
        self,
        *,
        copybook_paths: list[str] | None = None,
        workers: int | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        encoding: str | None = None,
        debug_lines: bool = False,
    ) -> None:
        self.copybook_paths: list[str] = list(copybook_paths or [])
        self.debug_lines = debug_lines
        self.workers = workers
        self.chunk_size = max(1, chunk_size)
        self.encoding = encoding
        self._resolver: PathResolver | None = None
        if self.copybook_paths:
            self._resolver = PathResolver(
                CopybookSearchPath(directories=list(self.copybook_paths))
            )
        # (member as written, library) -> resolved file path (None when
        # unresolved). The library is part of the key: COPY REC OF LIBA and
        # COPY REC OF LIBB are two different files (#351). The member is the
        # COPY text as written, not the normalized graph key: the expander
        # resolves `COPY ordrec.` / `COPY "sub/REC.cpy"` as written (#580).
        self._member_paths: dict[tuple[str, str | None], str | None] = {}
        # (member as written, library) -> why it could not be resolved
        self._member_failures: dict[tuple[str, str | None], str] = {}
        # (member, referrer) pairs already reported unresolved this build, so
        # a COPY and an INCLUDE of one missing member give one note, not two
        self._reported_failures: set[tuple[str, str]] = set()
        # resolved file path -> its own direct (member name, library, is EXEC
        # SQL INCLUDE, member as written), sorted
        self._member_copies: dict[str, list[tuple[str, str | None, bool, str]]] = {}
        # program file -> (member, line) of each COPY written in it
        self._copy_sites: dict[str, list[tuple[str, int]]] = {}

    # -- public API -------------------------------------------------------

    def build(self, paths: list[str]) -> CodebaseGraph:
        """Build the graph for *paths* (files; directories are ignored)."""
        files = self._normalize_paths(paths)
        return self.build_from_results(
            files,
            (
                result
                for chunk in self._chunks(files)
                for result in self._parse_chunk(chunk)
            ),
        )

    def build_from_results(
        self, paths: list[str], results: Iterable[BatchResult]
    ) -> CodebaseGraph:
        """Build the graph for *paths* from parses the caller already made.

        *results* holds one :class:`BatchResult` per path, with the same
        spelling of the path, and is consumed one at a time: a generator that
        parses on demand keeps a single AST live, as :meth:`build` does. For
        a caller with its own parse settings (the MCP server's ``>>DEFINE``
        symbols and cache) that must not parse every file a second time.
        COPY edges still come from each file's raw text, here.
        """
        self.begin_build()
        files = self._normalize_paths(paths)
        parts = [self.absorb(batch_result) for batch_result in results]
        absorbed = {part.path for part in parts}
        parts += [self.absorb_missing(path) for path in files if path not in absorbed]
        return self.assemble(parts)

    def begin_build(self) -> None:
        """Forget what the previous build resolved: a copybook edited between
        two builds on one long-lived builder must not serve the previous
        build's chain. :meth:`build_from_results` calls it; a caller driving
        :meth:`absorb` / :meth:`assemble` itself calls it first."""
        self._member_paths = {}
        self._member_failures = {}
        self._reported_failures = set()
        self._member_copies = {}
        self._copy_sites = {}

    def absorb(self, batch_result: BatchResult) -> GraphPart:
        """What one file adds to the graph: its program nodes and CALL edges
        from the parse, and its COPY edges from its raw text. Parts of
        different files are independent (each may come from another process)
        and :meth:`assemble` joins them."""
        path = str(batch_result.path)
        part = GraphPart(path=path)
        units_by_path: dict[str, list[str]] = {}
        self._absorb_parse(
            batch_result,
            part.nodes,
            part.call_edges,
            part.unresolved,
            part.errors,
            units_by_path,
            part.declared,
        )
        part.unit_ids = units_by_path.get(path)
        if not (part.unit_ids == [] and not os.path.exists(path)):
            self._collect_copy_edges(
                path,
                units_by_path.get(path, [_program_id_from_path(path)]),
                part.nodes,
                part.copy_edges,
                part.unresolved,
                part.errors,
            )
        part.copy_sites = list(self._copy_sites.get(path, []))
        return part

    def absorb_missing(self, path: str) -> GraphPart:
        """The part of a file no parse result came back for: its COPY edges
        only, attributed to the program its file name suggests."""
        part = GraphPart(path=path)
        self._collect_copy_edges(
            path,
            [_program_id_from_path(path)],
            part.nodes,
            part.copy_edges,
            part.unresolved,
            part.errors,
        )
        part.copy_sites = list(self._copy_sites.get(path, []))
        return part

    def assemble(self, parts: Iterable[GraphPart]) -> CodebaseGraph:
        """The graph of every file's :meth:`absorb` part, in the order given
        (the first file declaring a PROGRAM-ID is the one a duplicate is
        reported against)."""
        nodes: list[ProgramNode] = []
        call_edges: list[CallEdge] = []
        copy_edges: list[CopyEdge] = []
        unresolved: list[str] = []
        errors: list[dict[str, Any]] = []
        copy_sites: dict[str, list[tuple[str, int]]] = {}
        seen_program_ids: dict[str, str] = {}
        for part in parts:
            nodes += part.nodes
            call_edges += part.call_edges
            copy_edges += part.copy_edges
            unresolved += part.unresolved
            errors += [e for e in part.errors if e not in errors]
            if part.copy_sites:
                copy_sites[part.path] = list(part.copy_sites)
            for program_id in part.declared:
                previous = seen_program_ids.get(program_id)
                if previous is not None and previous != part.path:
                    # A nested id is qualified by its outermost program's, so
                    # a nested ERRHAND in PGMA and one in PGMB never collide.
                    unresolved.append(
                        f"duplicate PROGRAM-ID {program_id} in {previous} and "
                        f"{part.path}: call edges to it cannot be attributed "
                        "to one file"
                    )
                else:
                    seen_program_ids[program_id] = part.path

        if not self.copybook_paths:
            unresolved.append(
                "no copybook search path configured: COPY members were not "
                "resolved to files and nested COPY chains were not followed"
            )

        call_edges = self._resolve_entry_names(nodes, call_edges, unresolved)

        for node in nodes:
            node.calls = sorted(set(node.calls))
            node.copies = sorted(set(node.copies))

        return CodebaseGraph(
            programs=sorted(nodes, key=lambda n: (n.program_id, n.path)),
            call_edges=sorted(set(call_edges), key=CallEdge._sort_key),
            copy_edges=sorted(set(copy_edges), key=CopyEdge._sort_key),
            unresolved=sorted(set(unresolved)),
            errors=sorted(errors, key=lambda e: (str(e["path"]), str(e["error"]))),
            copy_sites=copy_sites,
        )

    @staticmethod
    def _resolve_entry_names(
        nodes: list[ProgramNode],
        call_edges: list[CallEdge],
        unresolved: list[str],
    ) -> list[CallEdge]:
        """Send a CALL to an alternate ``ENTRY`` name to the program that
        declares it, keeping the name on the edge (#521).

        A PROGRAM-ID wins over an ENTRY name of the same spelling. An ENTRY
        name two programs declare is left as written and, when something
        CALLs it, reported like a duplicate PROGRAM-ID.
        """
        program_ids = {node.program_id for node in nodes}
        owners: dict[str, set[tuple[str, str]]] = {}
        for node in nodes:
            for entry in node.entries:
                if entry not in program_ids:
                    owners.setdefault(entry, set()).add((node.program_id, node.path))
        if not owners:
            return call_edges
        resolved: list[CallEdge] = []
        for edge in call_edges:
            owner = owners.get(edge.callee)
            if not owner or edge.kind != CALL_KIND_CALL:
                resolved.append(edge)
                continue
            if len({program for program, _ in owner}) > 1:
                where = " and ".join(sorted(path for _, path in owner))
                unresolved.append(
                    f"duplicate ENTRY {edge.callee} in {where}: call edges to it "
                    "cannot be attributed to one program"
                )
                resolved.append(edge)
                continue
            (program, _), *_ = owner
            resolved.append(
                CallEdge(
                    caller=edge.caller,
                    callee=program,
                    is_dynamic=edge.is_dynamic,
                    resolved=edge.resolved,
                    kind=edge.kind,
                    entry=edge.callee,
                )
            )
            for node in nodes:
                if node.program_id == edge.caller and edge.callee in node.calls:
                    node.calls = [
                        program if callee == edge.callee else callee
                        for callee in node.calls
                    ]
        return resolved

    def build_from_directory(
        self,
        root: str,
        *,
        extensions: tuple[str, ...] = DEFAULT_PROGRAM_EXTENSIONS,
    ) -> CodebaseGraph:
        """Build the graph for every COBOL source file under *root*.

        Raises:
            NotADirectoryError: if *root* is not an existing directory. A
                mistyped root must not read as "a codebase with no programs".
        """
        root_path = Path(root)
        if not root_path.is_dir():
            raise NotADirectoryError(f"not a directory: {root}")

        wanted = {
            (ext if ext.startswith(".") else f".{ext}").lower() for ext in extensions
        }
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames.sort()
            for filename in sorted(filenames):
                if Path(filename).suffix.lower() in wanted:
                    found.append(str(Path(dirpath) / filename))
        return self.build(found)

    # -- internals --------------------------------------------------------

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        """Sorted, de-duplicated file paths (duplicates are parsed once)."""
        seen: set[str] = set()
        unique: list[str] = []
        for raw in sorted(str(p) for p in paths):
            key = os.path.abspath(raw)
            if key in seen:
                continue
            seen.add(key)
            # ``str(Path(...))`` is the spelling ``BatchResult.path`` comes
            # back with (``./PROG.cbl`` -> ``PROG.cbl``); keying on the raw
            # spelling instead left the parsed units unmatched and every
            # COPY edge attributed to a phantom program named after the file.
            unique.append(str(Path(raw)))
        return unique

    def _chunks(self, files: list[str]) -> list[list[str]]:
        return [
            files[i : i + self.chunk_size]
            for i in range(0, len(files), self.chunk_size)
        ]

    def _parse_chunk(self, chunk: list[str]) -> list[BatchResult]:
        """Parse one chunk, in input order, with per-file fault isolation."""
        if self.copybook_paths:
            return parse_files_with_copybooks(
                chunk,
                copybook_paths=list(self.copybook_paths),
                encoding=self.encoding,
                debug_lines=self.debug_lines,
            )
        workers = self.workers
        if workers is None and len(chunk) < _PARALLEL_THRESHOLD:
            workers = 1
        return parse_files(
            chunk,
            workers=workers,
            encoding=self.encoding,
            debug_lines=self.debug_lines,
        )

    def _absorb_parse(
        self,
        batch_result: BatchResult,
        nodes: list[ProgramNode],
        call_edges: list[CallEdge],
        unresolved: list[str],
        errors: list[dict[str, Any]],
        units_by_path: dict[str, list[str]],
        declared_ids: list[str],
    ) -> None:
        path = str(batch_result.path)
        parse_result = batch_result.result
        ast = parse_result.ast if parse_result is not None else None
        parse_errors = list(parse_result.errors) if parse_result is not None else []

        if ast is None and not os.path.exists(path):
            # A mistyped path is an input error, not a program that failed to
            # parse: no phantom node named after it (#325).
            errors.append({"path": path, "error": "no such file or directory"})
            unresolved.append(
                f"{path}: no such file or directory; it is not in the graph"
            )
            units_by_path[path] = []
            return

        if ast is None:
            reason = batch_result.read_error or (
                str(parse_errors[0]) if parse_errors else "no AST produced"
            )
            errors.append({"path": path, "error": reason})
            fallback = _program_id_from_path(path)
            unresolved.append(
                f"{path}: not parsed ({reason}); its CALL edges are unknown and "
                f"its program id is assumed from the file name ({fallback})"
            )
            units_by_path[path] = [fallback]
            nodes.append(ProgramNode(program_id=fallback, path=path, parse_failed=True))
            return

        for warning in parse_result.warnings if parse_result is not None else []:
            if str(warning).startswith("Lossy decode of "):
                # Bytes the encoding could not map are U+FFFD in the parse
                # (#522): a name or literal there may be wrong.
                unresolved.append(f"{path}: {warning}")

        if parse_errors:
            # COLLECT_ALL always hands back *some* AST, so a file full of
            # garbage arrives here rather than above. Its parse errors are
            # recorded per file all the same -- "it produced a node" is not
            # the same claim as "its edges are complete".
            errors.append(
                {
                    "path": path,
                    "error": (
                        f"{len(parse_errors)} parse error(s); "
                        f"first: {parse_errors[0]}"
                    ),
                }
            )
            unresolved.append(
                f"{path}: parsed with {len(parse_errors)} error(s); "
                "some CALL/COPY edges in this file may be missing"
            )

        units = ast.program_units()
        unit_ids: list[str] = []
        for unit in units:
            # Outermost first, so a contained unit's own data pool wins for
            # its own dynamic calls (the outer pass sees it first, the inner
            # pass rewrites it with the narrower, correct scope).
            DynamicCallAnalyzer().analyze(unit)

        # Only a PROGRAM-ID (outermost, nested or stacked) or a CLASS-ID is a
        # graph node: a FACTORY / OBJECT paragraph or a METHOD-ID cannot be
        # the target of a CALL, so it is never a program id. What such a
        # member unit CALLs is its class's (#500).
        graph_ids = program_graph_ids(units, path)
        for unit in [u for u in units if u.unit_kind not in _OO_MEMBER_KINDS]:
            program_id = graph_ids[id(unit)]
            declared = _normalize_program_name(unit.program_name or "")
            named = bool(declared) and declared != _UNNAMED_PROGRAM
            if not named:
                unresolved.append(
                    f"{path}: no PROGRAM-ID could be read; the program id is "
                    f"assumed from the file name ({program_id})"
                )

            def scoped(callee: str, unit: Any = unit) -> str:
                target = unit.nested_program_called(callee)
                return graph_ids.get(id(target), callee) if target else callee

            unit_ids.append(program_id)
            declared_ids.append(program_id)

            node = ProgramNode(
                program_id=program_id,
                path=path,
                # No PROGRAM-ID *and* parse errors: nothing usable came out of
                # this file, whatever the parser managed to hand back.
                parse_failed=bool(parse_errors) and not named,
            )
            # Built on first need: only a CICS transfer through a data-name
            # asks for the unit's tracked values.
            trackers: dict[int, DynamicCallAnalyzer] = {}
            for owner, statement in _node_statements(unit):
                tracker = trackers.get(id(owner))
                if isinstance(statement, EntryStatement) and statement.entry_name:
                    entry = _normalize_program_name(statement.entry_name)
                    if entry and entry not in node.entries:
                        node.entries.append(entry)
                        node.entries.sort()
                if isinstance(statement, CallStatement):
                    self._absorb_call(
                        statement,
                        program_id,
                        path,
                        node,
                        call_edges,
                        unresolved,
                        scoped,
                    )
                elif (
                    isinstance(statement, ExecCicsStatement)
                    and statement.cics_command in _CICS_TRANSFER_KINDS
                ):
                    if tracker is None and "PROGRAM" not in statement.literal_options:
                        tracker = trackers[id(owner)] = DynamicCallAnalyzer()
                        tracker.analyze(owner)
                    self._absorb_cics_transfer(
                        statement,
                        program_id,
                        path,
                        node,
                        call_edges,
                        unresolved,
                        tracker,
                    )
            nodes.append(node)

        units_by_path[path] = unit_ids

    @staticmethod
    def _absorb_call(
        statement: CallStatement,
        program_id: str,
        path: str,
        node: ProgramNode,
        call_edges: list[CallEdge],
        unresolved: list[str],
        scoped: Callable[[str], str] | None = None,
    ) -> None:
        """One CALL's edges. *scoped* maps a target name to the graph id of
        the nested program COBOL scope says it reaches (#532), or returns
        the name unchanged for a separately compiled program."""
        target = statement.called_program or ""
        line = statement.location.line if statement.location else 0

        if not statement.is_dynamic:
            callee = _normalize_program_name(target)
            if not callee:
                unresolved.append(
                    f"{path}: {program_id}: CALL at line {line} has no target name"
                )
                return
            if scoped is not None:
                callee = scoped(callee)
            node.calls.append(callee)
            call_edges.append(CallEdge(caller=program_id, callee=callee))
            return

        values = sorted(callee_names(statement.possible_values))
        if scoped is not None:
            values = sorted({scoped(value) for value in values})
        incomplete = bool(statement.get_metadata("possible_values_incomplete"))

        if not values:
            unresolved.append(
                f"{path}: {program_id}: dynamic CALL {target} at line {line}: "
                "no possible target could be resolved, so its call edges are missing"
            )
            return

        if incomplete:
            unresolved.append(
                f"{path}: {program_id}: dynamic CALL {target} at line {line}: "
                f"{len(values)} target(s) resolved but the value set is not "
                "exhaustive; further call edges may exist"
            )
        for callee in values:
            node.calls.append(callee)
            call_edges.append(
                CallEdge(
                    caller=program_id,
                    callee=callee,
                    is_dynamic=True,
                    resolved=not incomplete,
                )
            )

    @staticmethod
    def _absorb_cics_transfer(
        statement: ExecCicsStatement,
        program_id: str,
        path: str,
        node: ProgramNode,
        call_edges: list[CallEdge],
        unresolved: list[str],
        tracker: DynamicCallAnalyzer | None,
    ) -> None:
        """One ``EXEC CICS LINK`` / ``XCTL`` statement's edges (#315).

        ``PROGRAM('X')`` is a static edge. ``PROGRAM(WS-PGM)`` takes the
        values :class:`~.value_tracker.DynamicCallAnalyzer` tracked for
        ``WS-PGM``, exactly as ``CALL WS-PGM`` would; with none, the
        statement is reported unresolved rather than dropped.
        """
        command = statement.cics_command
        kind = _CICS_TRANSFER_KINDS[command]
        line = statement.location.line if statement.location else 0
        operand = (statement.options.get("PROGRAM") or "").strip()
        where = f"{path}: {program_id}: EXEC CICS {command}"

        if not operand:
            unresolved.append(
                f"{where} at line {line} has no PROGRAM name, so its edge is missing"
            )
            return

        if "PROGRAM" in statement.literal_options:
            callee = _normalize_program_name(operand)
            node.calls.append(callee)
            call_edges.append(CallEdge(caller=program_id, callee=callee, kind=kind))
            return

        values: list[str] = []
        incomplete = True
        if tracker is not None:
            tracked, incomplete = tracker.resolve_variable(operand)
            values = sorted(callee_names(tracked))

        if not values:
            unresolved.append(
                f"{where} PROGRAM({operand}) at line {line}: no possible target "
                "could be resolved, so its edges are missing"
            )
            return

        if incomplete:
            unresolved.append(
                f"{where} PROGRAM({operand}) at line {line}: {len(values)} "
                "target(s) resolved but the value set is not exhaustive; "
                "further edges may exist"
            )
        for callee in values:
            node.calls.append(callee)
            call_edges.append(
                CallEdge(
                    caller=program_id,
                    callee=callee,
                    is_dynamic=True,
                    resolved=not incomplete,
                    kind=kind,
                )
            )

    # -- COPY edges -------------------------------------------------------

    def _read_source(self, path: str) -> str | None:
        try:
            return read_program_source(path, self.encoding)
        except (OSError, ValueError, PreprocessingError):
            return None

    def _collect_copy_edges(
        self,
        path: str,
        unit_ids: list[str],
        nodes: list[ProgramNode],
        copy_edges: list[CopyEdge],
        unresolved: list[str],
        errors: list[dict[str, Any]],
    ) -> None:
        """COPY edges for one program file, plus every nested member below it.

        The scan runs on the *raw* source: expansion resolves a COPY and then
        throws the edge away, and a file that failed to parse still has real
        COPY dependencies worth recording.
        """
        source = self._read_source(path)
        if source is None:
            error = {"path": path, "error": "could not be read for the COPY scan"}
            if error not in errors:
                errors.append(error)
            unresolved.append(f"{path}: COPY statements could not be scanned")
            return

        owner = unit_ids[0] if unit_ids else _program_id_from_path(path)
        if len(unit_ids) > 1:
            unresolved.append(
                f"{path}: holds {len(unit_ids)} program units "
                f"({', '.join(unit_ids)}); its COPY edges are attributed to the "
                f"outermost one ({owner})"
            )

        warnings: list[str] = []
        statements = extract_copy_statements(
            source, source_file=path, warnings=warnings, sql_include=True
        )
        for warning in warnings:
            unresolved.append(f"{path}: COPY statement not usable: {warning}")

        owner_nodes = [n for n in nodes if n.program_id == owner] or nodes
        for statement in statements:
            member = _normalize_member(statement.member_name)
            if not member:
                continue
            if statement.source_location is not None:
                self._copy_sites.setdefault(path, []).append(
                    (member, statement.source_location[1])
                )
            library = _normalize_library(statement.library_qualifier)
            member_path = self._resolve_member(
                member,
                library,
                path,
                unresolved,
                sql_include=statement.sql_include,
                written=statement.member_name,
            )
            copy_edges.append(
                CopyEdge(
                    program=owner,
                    member=member,
                    path=member_path,
                    nested=False,
                    library=library,
                )
            )
            for node in owner_nodes:
                node.copies.append(member)
            self._walk_member(
                member, member_path, [(member, member_path)], copy_edges, unresolved
            )

    def _resolve_member(
        self,
        member: str,
        library: str | None,
        referrer: str,
        unresolved: list[str],
        *,
        sql_include: bool = False,
        written: str | None = None,
    ) -> str | None:
        """Resolve *member* to a file, caching the answer (and the failure).

        *written* is the member as the COPY statement spells it; it is what
        is resolved, exactly as the expander resolves it (#580) -- *member*,
        the upper-cased basename, is only the graph key. A lowercase file
        (`COPY ordrec.`) or a path literal (`COPY "sub/REC.cpy"`) is found
        through *written* and would be missed through *member*.

        A failure is reported for every reference that is not an INCLUDE of
        a precompiler-supplied member (:data:`_PRECOMPILER_MEMBERS`), so a
        quiet ``INCLUDE SQLCA`` seen first cannot silence a later ``COPY
        SQLCA``. One note per (member, referrer): whichever of COPY / INCLUDE
        is seen first names it.
        """
        if self._resolver is None:
            return None
        target = written.strip() if written and written.strip() else member
        key = (target, library)
        if key not in self._member_paths:
            try:
                self._member_paths[key] = self._resolver.resolve(target, library)
            except Exception as exc:  # noqa: BLE001 -- an unresolvable member
                # is a finding, not a crash: record why and carry on.
                self._member_paths[key] = None
                self._member_failures[key] = f"{type(exc).__name__}: {exc}"
        resolved = self._member_paths[key]
        if (
            resolved is None
            and not (sql_include and member in _PRECOMPILER_MEMBERS)
            and (member, referrer) not in self._reported_failures
        ):
            self._reported_failures.add((member, referrer))
            kind = "EXEC SQL INCLUDE" if sql_include else "COPY"
            named = f"{member} OF {library}" if library else member
            unresolved.append(
                f"{kind} member {named} (referenced by {referrer}) could not be "
                "resolved on the copybook search path: "
                f"{self._member_failures[key]}"
            )
        return resolved

    def _member_direct_copies(
        self, member: str, member_path: str | None, unresolved: list[str]
    ) -> list[tuple[str, str | None, bool, str]]:
        """What the file *member_path* itself COPYs or INCLUDEs.

        Keyed by file, not by member name: two libraries' members of one name
        are two files with their own nested COPY statements. Each entry is
        ``(member name, library, is EXEC SQL INCLUDE, member as written)``;
        empty when the member did not resolve.
        """
        if member_path is None:
            return []
        if member_path in self._member_copies:
            return self._member_copies[member_path]
        self._member_copies[member_path] = []
        source = self._read_source(member_path)
        if source is None:
            unresolved.append(
                f"copybook {member} ({member_path}) could not be read; its own "
                "nested COPY statements are unknown"
            )
            return []
        warnings: list[str] = []
        statements = extract_copy_statements(
            source, source_file=member_path, warnings=warnings, sql_include=True
        )
        for warning in warnings:
            unresolved.append(f"{member_path}: COPY statement not usable: {warning}")
        names = sorted(
            {
                (
                    _normalize_member(s.member_name),
                    _normalize_library(s.library_qualifier),
                    s.sql_include,
                    s.member_name,
                )
                for s in statements
                if _normalize_member(s.member_name)
            },
            key=lambda entry: (entry[0], entry[1] or "", entry[2], entry[3]),
        )
        self._member_copies[member_path] = names
        return names

    def _walk_member(
        self,
        member: str,
        member_path: str | None,
        stack: list[tuple[str, str | None]],
        copy_edges: list[CopyEdge],
        unresolved: list[str],
    ) -> None:
        """Emit nested member->member edges below *member*, cycle-safe.

        *stack* holds ``(member, file)`` pairs, so ``LIBA/REC`` copying
        ``LIBB/REC`` is a chain, not a cycle.
        """
        seen: set[tuple[str, str | None]] = set()
        for nested, library, sql_include, written in self._member_direct_copies(
            member, member_path, unresolved
        ):
            # The nested COPY's own library, as the expander resolves it.
            nested_path = self._resolve_member(
                nested,
                library,
                member,
                unresolved,
                sql_include=sql_include,
                written=written,
            )
            if (nested, library) in seen:
                # COPY and INCLUDE of one member: one edge, as for a program.
                continue
            seen.add((nested, library))
            copy_edges.append(
                CopyEdge(
                    program=member,
                    member=nested,
                    path=nested_path,
                    nested=True,
                    library=library,
                    parent_path=member_path,
                )
            )
            if (nested, nested_path) in stack:
                unresolved.append(
                    "circular COPY chain: "
                    + " -> ".join([name for name, _ in stack] + [nested])
                )
                continue
            self._walk_member(
                nested,
                nested_path,
                [*stack, (nested, nested_path)],
                copy_edges,
                unresolved,
            )


#: Object-oriented member units: never a CALL target, so never a graph node.
_OO_MEMBER_KINDS = frozenset({"FACTORY", "OBJECT", "METHOD"})


def _node_statements(
    unit: CobolProgram,
) -> list[tuple[CobolProgram, CobolStatement]]:
    """``(owning unit, statement)`` for every statement of graph node *unit*:
    its own, plus, for a class, those of its FACTORY / OBJECT / METHOD
    units (#500)."""
    out = [(unit, statement) for statement in _unit_statements(unit)]
    for member in unit.contained_programs:
        if member.unit_kind in _OO_MEMBER_KINDS:
            out += _node_statements(member)
    return out


def _unit_statements(unit: CobolProgram) -> list[CobolStatement]:
    """Statements belonging to *unit* itself, not to a program contained in it.

    ``CobolProgram.get_all_statements()`` walks children, and a contained
    program unit *is* a child -- so an inner unit's CALL would otherwise be
    attributed to the outer program that merely encloses it.
    """
    own = unit.get_all_statements()
    if not unit.contained_programs:
        return list(own)
    inner_ids = {
        id(statement)
        for contained in unit.contained_programs
        for statement in contained.get_all_statements()
    }
    return [s for s in own if id(s) not in inner_ids]


# ---------------------------------------------------------------------------
# Copybook change-impact analysis
# ---------------------------------------------------------------------------


@dataclass
class ImpactReport:
    """Everything a change to one copybook member would touch."""

    member: str
    direct_programs: list[str] = field(default_factory=list)
    transitive_programs: list[str] = field(default_factory=list)
    chains: list[list[str]] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    # Every file the member name resolved to. More than one when libraries
    # (COPY X OF LIB) hold different members of the same name.
    paths: list[str] = field(default_factory=list)

    @property
    def program_count(self) -> int:
        """Distinct programs affected, directly or transitively."""
        return len(set(self.direct_programs) | set(self.transitive_programs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "direct_programs": list(self.direct_programs),
            "transitive_programs": list(self.transitive_programs),
            "chains": [list(chain) for chain in self.chains],
            "fields": list(self.fields),
            "unresolved": list(self.unresolved),
            "paths": list(self.paths),
            "summary": {
                "direct_count": len(self.direct_programs),
                "transitive_count": len(self.transitive_programs),
                "program_count": self.program_count,
                "field_count": len(self.fields),
                "unresolved_count": len(self.unresolved),
            },
        }


class CopybookImpactAnalyzer:
    """Answers "can I safely change this copybook?" against a built graph.

    Reverses the COPY direction of a :class:`CodebaseGraph`: from a member,
    up through every nesting chain, to the programs a change would reach --
    plus the data items the member itself contributes, when its file resolved
    and could be parsed.
    """

    def __init__(self, graph: CodebaseGraph) -> None:
        self.graph = graph

    def analyze(self, member: str) -> ImpactReport:
        """Impact of changing *member* (bare name, file name or path)."""
        wanted = _normalize_member(member)
        unresolved: list[str] = []
        if not wanted:
            return ImpactReport(
                member=member,
                unresolved=[f"{member!r} is not a usable copybook member name"],
            )

        direct = self.graph.programs_using(wanted, transitive=False)
        everyone = self.graph.programs_using(wanted, transitive=True)
        transitive = sorted(set(everyone) - set(direct))

        chains = self._chains(wanted)
        if wanted not in self.graph.members:
            unresolved.append(
                f"no COPY statement in the graph references member {wanted}"
            )

        member_paths = self._member_paths(wanted)
        fields: set[str] = set()
        if not member_paths:
            unresolved.append(
                f"member {wanted} was not resolved to a file, so the data items "
                "it contributes are unknown"
            )
        else:
            if len(member_paths) > 1:
                unresolved.append(
                    f"member {wanted} resolves to {len(member_paths)} different "
                    f"files ({', '.join(member_paths)}); its fields are the union "
                    "of theirs"
                )
            for member_path in member_paths:
                path_fields, field_problem = _member_fields(member_path)
                fields.update(path_fields)
                if field_problem is not None:
                    unresolved.append(field_problem)

        return ImpactReport(
            member=wanted,
            direct_programs=direct,
            transitive_programs=transitive,
            chains=chains,
            fields=sorted(fields),
            unresolved=sorted(set(unresolved)),
            paths=member_paths,
        )

    def _member_paths(self, member: str) -> list[str]:
        return sorted(
            {e.path for e in self.graph.copy_edges if e.member == member and e.path}
        )

    def _chains(self, member: str) -> list[list[str]]:
        """One ``[program, outer, ..., member]`` chain per transitive reach.

        Walked edge by edge, so a chain only continues to the programs whose
        COPY resolved to the file the nested edge sits in (#351).
        """
        chains: list[list[str]] = []

        def walk(child: CopyEdge, tail: list[str]) -> None:
            for edge in self.graph.copy_edges:
                if not child._is_parent(edge):
                    continue
                if edge.nested:
                    if edge.program in tail:
                        # Circular COPY chain: already reported by the builder.
                        continue
                    walk(edge, [edge.program, *tail])
                else:
                    chains.append([edge.program, *tail])

        for edge in self.graph.copy_edges:
            if edge.member == member and edge.nested:
                walk(edge, [edge.program, member])
        unique = {tuple(chain) for chain in chains}
        return [list(chain) for chain in sorted(unique)]


def _member_fields(member_path: str) -> tuple[list[str], str | None]:
    """Data-item names a copybook file contributes, plus a reason on failure."""
    try:
        source = Path(member_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        return [], f"{member_path} could not be read: {exc}"

    # Imported lazily: the generators package pulls in the whole fixture
    # stack, which a call-graph build has no use for.
    from ..generators.data.copybook import parse_copybook_records
    from ..models.data_items import CobolDataItem

    # A ``:TAG:``-named item's real name only exists once a COPY ... REPLACING
    # fills the tag in, so it is reported as a gap rather than silently left
    # out (#356) -- whether or not the rest of the member parses.
    placeholders = _placeholder_names(source)
    placeholder_note = (
        f"{member_path}: data item(s) {', '.join(placeholders)} are named "
        "by REPLACING placeholders, so their names depend on each COPY "
        "... REPLACING and are not listed in fields"
        if placeholders
        else None
    )

    try:
        records = parse_copybook_records(source, filename=member_path)
    except Exception as exc:  # noqa: BLE001 -- a member that is not a record
        # layout (procedure-division text, say) is a reported gap, not a crash.
        if placeholder_note is not None:
            return [], placeholder_note
        return [], (
            f"{member_path}: data items could not be read "
            f"({type(exc).__name__}: {exc})"
        )

    names: set[str] = set()
    for record in records:
        for node in [record, *record.find_all_by_type("CobolDataItem")]:
            if isinstance(node, CobolDataItem) and node.name and not node.is_filler:
                names.add(node.name.upper())
    # A copybook holding only subordinate items gets a synthetic level-01 root
    # from parse_copybook_records ("LEVEL3-RECORD"). That name is this parser's
    # invention, not something the member contributes, so keep only names the
    # member's own text actually declares.
    declared = source.upper()
    fields = sorted(name for name in names if name in declared)
    # A ``:TAG:``-named item that does parse comes back under a generated
    # ANONYMOUS-* name, which the filter above drops; the note says why.
    return fields, placeholder_note


def _placeholder_names(source: str) -> list[str]:
    """``:TAG:``-placeholder data names a copybook declares, in source order."""
    found: list[str] = []
    for line in split_source_lines(source):
        if len(line) > 6 and line[6] in "*/":
            continue  # fixed-format comment line
        for match in _PLACEHOLDER_DECLARATION.finditer(line):
            name = match.group(1).upper()
            if name not in found:
                found.append(name)
    return found
