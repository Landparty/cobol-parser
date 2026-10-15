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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..batch import BatchResult, parse_files, parse_files_with_copybooks
from ..models.program import CobolProgram
from ..models.statements.base import CobolStatement
from ..models.statements.call import CallStatement
from ..parsers.statements.ibm_exec_statements import ExecCicsStatement
from ..preprocess.copy_statement_parser import extract_copy_statements
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
    """

    program_id: str
    path: str
    calls: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)
    parse_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "path": self.path,
            "calls": list(self.calls),
            "copies": list(self.copies),
            "parse_failed": self.parse_failed,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "is_dynamic": self.is_dynamic,
            "resolved": self.resolved,
            "kind": self.kind,
        }

    def _sort_key(self) -> tuple[str, str, str, bool, bool]:
        return (self.caller, self.callee, self.kind, self.is_dynamic, self.resolved)


@dataclass(frozen=True)
class CopyEdge:
    """A ``COPY`` dependency edge.

    ``program`` is a program id for a direct edge and the *outer member name*
    for a nested one (``nested=True``), which is what makes a chain such as
    ``PROG1 -> OUTER -> INNER`` walkable in either direction.
    """

    program: str
    member: str
    path: str | None = None
    nested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "member": self.member,
            "path": self.path,
            "nested": self.nested,
        }

    def _sort_key(self) -> tuple[bool, str, str, str]:
        return (self.nested, self.program, self.member, self.path or "")


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


@dataclass
class CodebaseGraph:
    """The aggregated dependency graph for a whole tree of COBOL source."""

    programs: list[ProgramNode] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    copy_edges: list[CopyEdge] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

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

        found: set[str] = set(direct)
        seen: set[str] = {wanted}
        queue: list[str] = [wanted]
        while queue:
            current = queue.pop()
            for edge in self.copy_edges:
                if edge.member != current:
                    continue
                if edge.nested:
                    if edge.program not in seen:
                        seen.add(edge.program)
                        queue.append(edge.program)
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

    def to_mermaid(self) -> str:
        """Render the graph as a Mermaid ``flowchart LR``.

        Node ids are sanitized the way :mod:`cobolparser.generators.flowchart`
        sanitizes them -- COBOL names are full of hyphens, which Mermaid reads
        as an arrow fragment rather than as part of an identifier.
        """
        programs, external, members = self._render_nodes()
        failed = self._failed_ids()

        lines: list[str] = ["flowchart LR"]
        for pid in programs:
            label = f"{pid} (unparsed)" if pid in failed else pid
            lines.append(f'    {_program_node_id(pid)}["{_mermaid_label(label)}"]')
        for pid in external:
            lines.append(
                f'    {_program_node_id(pid)}(["{_mermaid_label(pid)} (external)"])'
            )
        for member in members:
            lines.append(f'    {_member_node_id(member)}[/"{_mermaid_label(member)}"/]')

        for edge in self.call_edges:
            label = _mermaid_label(_call_edge_label(edge))
            # Quoted label text: an unquoted "(" inside a Mermaid `|label|`
            # is read by the flowchart lexer as the start of a node shape,
            # not as literal text -- "CALL (dynamic)" breaks parsing bare.
            lines.append(
                f'    {_program_node_id(edge.caller)} -->|"{label}"|'
                f" {_program_node_id(edge.callee)}"
            )
        for copy_edge in self.copy_edges:
            source = (
                _member_node_id(copy_edge.program)
                if copy_edge.nested
                else _program_node_id(copy_edge.program)
            )
            label = _mermaid_label("COPY (nested)" if copy_edge.nested else "COPY")
            lines.append(
                f'    {source} -.->|"{label}"| {_member_node_id(copy_edge.member)}'
            )

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
                f"    {_program_node_id(pid)} [label={label},"
                f' shape=box, fillcolor="{fill}", fontcolor="#000000"];'
            )
        for pid in external:
            lines.append(
                f"    {_program_node_id(pid)} [label={_dot_str(pid)},"
                ' shape=ellipse, fillcolor="#e9ecef", fontcolor="#000000"];'
            )
        for member in members:
            lines.append(
                f"    {_member_node_id(member)} [label={_dot_str(member)},"
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
                f"    {_program_node_id(edge.caller)} ->"
                f" {_program_node_id(edge.callee)} [{attrs}];"
            )
        for copy_edge in self.copy_edges:
            source = (
                _member_node_id(copy_edge.program)
                if copy_edge.nested
                else _program_node_id(copy_edge.program)
            )
            label = "COPY (nested)" if copy_edge.nested else "COPY"
            lines.append(
                f"    {source} -> {_member_node_id(copy_edge.member)}"
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
            the COPY scan.
        debug_lines: Compile fixed-format debugging lines (``D`` in column
            7) as code, so a CALL written on one is an edge.
    """

    def __init__(
        self,
        *,
        copybook_paths: list[str] | None = None,
        workers: int | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        encoding: str = "utf-8",
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
        # member -> resolved file path (None when it could not be resolved)
        self._member_paths: dict[str, str | None] = {}
        # member -> why it could not be resolved (only for failed members)
        self._member_failures: dict[str, str] = {}
        # (member, referrer) pairs already reported unresolved this build, so
        # a COPY and an INCLUDE of one missing member give one note, not two
        self._reported_failures: set[tuple[str, str]] = set()
        # member -> its own direct (member name, is EXEC SQL INCLUDE), sorted
        self._member_copies: dict[str, list[tuple[str, bool]]] = {}

    # -- public API -------------------------------------------------------

    def build(self, paths: list[str]) -> CodebaseGraph:
        """Build the graph for *paths* (files; directories are ignored)."""
        # Per-build caches: a copybook edited between two builds on one
        # long-lived builder must not serve the previous build's chain.
        self._member_paths = {}
        self._member_failures = {}
        self._reported_failures = set()
        self._member_copies = {}
        files = self._normalize_paths(paths)

        nodes: list[ProgramNode] = []
        call_edges: list[CallEdge] = []
        copy_edges: list[CopyEdge] = []
        unresolved: list[str] = []
        errors: list[dict[str, Any]] = []
        # path -> the program ids found in it, outermost first
        units_by_path: dict[str, list[str]] = {}
        seen_program_ids: dict[str, str] = {}

        for chunk in self._chunks(files):
            batch_results = self._parse_chunk(chunk)
            for batch_result in batch_results:
                self._absorb_parse(
                    batch_result,
                    nodes,
                    call_edges,
                    unresolved,
                    errors,
                    units_by_path,
                    seen_program_ids,
                )
            # Facts extracted; let this chunk's ASTs go before the next one.
            del batch_results

        if not self.copybook_paths:
            unresolved.append(
                "no copybook search path configured: COPY members were not "
                "resolved to files and nested COPY chains were not followed"
            )

        nodes_by_path: dict[str, list[ProgramNode]] = {}
        for node in nodes:
            nodes_by_path.setdefault(node.path, []).append(node)

        for path in files:
            self._collect_copy_edges(
                path,
                units_by_path.get(path, [_program_id_from_path(path)]),
                nodes_by_path.get(path, []),
                copy_edges,
                unresolved,
                errors,
            )

        for node in nodes:
            node.calls = sorted(set(node.calls))
            node.copies = sorted(set(node.copies))

        return CodebaseGraph(
            programs=sorted(nodes, key=lambda n: (n.program_id, n.path)),
            call_edges=sorted(set(call_edges), key=CallEdge._sort_key),
            copy_edges=sorted(set(copy_edges), key=CopyEdge._sort_key),
            unresolved=sorted(set(unresolved)),
            errors=sorted(errors, key=lambda e: (str(e["path"]), str(e["error"]))),
        )

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
        seen_program_ids: dict[str, str],
    ) -> None:
        path = str(batch_result.path)
        parse_result = batch_result.result
        ast = parse_result.ast if parse_result is not None else None
        parse_errors = list(parse_result.errors) if parse_result is not None else []

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

        for unit in units:
            declared = _normalize_program_name(unit.program_name or "")
            named = bool(declared) and declared != _UNNAMED_PROGRAM
            program_id = declared if named else _program_id_from_path(path)
            if not named:
                unresolved.append(
                    f"{path}: no PROGRAM-ID could be read; the program id is "
                    f"assumed from the file name ({program_id})"
                )
            unit_ids.append(program_id)
            previous = seen_program_ids.get(program_id)
            if previous is not None and previous != path:
                unresolved.append(
                    f"duplicate PROGRAM-ID {program_id} in {previous} and {path}: "
                    "call edges to it cannot be attributed to one file"
                )
            else:
                seen_program_ids[program_id] = path

            node = ProgramNode(
                program_id=program_id,
                path=path,
                # No PROGRAM-ID *and* parse errors: nothing usable came out of
                # this file, whatever the parser managed to hand back.
                parse_failed=bool(parse_errors) and not named,
            )
            # Built on first need: only a CICS transfer through a data-name
            # asks for the unit's tracked values.
            tracker: DynamicCallAnalyzer | None = None
            for statement in _unit_statements(unit):
                if isinstance(statement, CallStatement):
                    self._absorb_call(
                        statement, program_id, path, node, call_edges, unresolved
                    )
                elif (
                    isinstance(statement, ExecCicsStatement)
                    and statement.cics_command in _CICS_TRANSFER_KINDS
                ):
                    if tracker is None and "PROGRAM" not in statement.literal_options:
                        tracker = DynamicCallAnalyzer()
                        tracker.analyze(unit)
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
    ) -> None:
        target = statement.called_program or ""
        line = statement.location.line if statement.location else 0

        if not statement.is_dynamic:
            callee = _normalize_program_name(target)
            if not callee:
                unresolved.append(
                    f"{path}: {program_id}: CALL at line {line} has no target name"
                )
                return
            node.calls.append(callee)
            call_edges.append(CallEdge(caller=program_id, callee=callee))
            return

        values = sorted(callee_names(statement.possible_values))
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
            return Path(path).read_text(encoding=self.encoding, errors="replace")
        except (OSError, ValueError):
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
            member_path = self._resolve_member(
                member,
                statement.library_qualifier,
                path,
                unresolved,
                sql_include=statement.sql_include,
            )
            copy_edges.append(
                CopyEdge(program=owner, member=member, path=member_path, nested=False)
            )
            for node in owner_nodes:
                node.copies.append(member)
            self._walk_member(member, [member], copy_edges, unresolved)

    def _resolve_member(
        self,
        member: str,
        library: str | None,
        referrer: str,
        unresolved: list[str],
        *,
        sql_include: bool = False,
    ) -> str | None:
        """Resolve *member* to a file, caching the answer (and the failure).

        A failure is reported for every reference that is not an INCLUDE of
        a precompiler-supplied member (:data:`_PRECOMPILER_MEMBERS`), so a
        quiet ``INCLUDE SQLCA`` seen first cannot silence a later ``COPY
        SQLCA``. One note per (member, referrer): whichever of COPY / INCLUDE
        is seen first names it.
        """
        if self._resolver is None:
            return None
        if member not in self._member_paths:
            try:
                self._member_paths[member] = self._resolver.resolve(member, library)
            except Exception as exc:  # noqa: BLE001 -- an unresolvable member
                # is a finding, not a crash: record why and carry on.
                self._member_paths[member] = None
                self._member_failures[member] = f"{type(exc).__name__}: {exc}"
        resolved = self._member_paths[member]
        if (
            resolved is None
            and not (sql_include and member in _PRECOMPILER_MEMBERS)
            and (member, referrer) not in self._reported_failures
        ):
            self._reported_failures.add((member, referrer))
            kind = "EXEC SQL INCLUDE" if sql_include else "COPY"
            unresolved.append(
                f"{kind} member {member} (referenced by {referrer}) could not be "
                "resolved on the copybook search path: "
                f"{self._member_failures[member]}"
            )
        return resolved

    def _member_direct_copies(
        self, member: str, unresolved: list[str]
    ) -> list[tuple[str, bool]]:
        """What *member* itself COPYs or INCLUDEs (empty when unresolved).

        Each entry is ``(member name, is EXEC SQL INCLUDE)``.
        """
        if member in self._member_copies:
            return self._member_copies[member]
        self._member_copies[member] = []
        member_path = self._member_paths.get(member)
        if member_path is None:
            return []
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
                (_normalize_member(s.member_name), s.sql_include)
                for s in statements
                if _normalize_member(s.member_name)
            }
        )
        self._member_copies[member] = names
        return names

    def _walk_member(
        self,
        member: str,
        stack: list[str],
        copy_edges: list[CopyEdge],
        unresolved: list[str],
    ) -> None:
        """Emit nested member->member edges below *member*, cycle-safe."""
        seen: set[str] = set()
        for nested, sql_include in self._member_direct_copies(member, unresolved):
            nested_path = self._resolve_member(
                nested, None, member, unresolved, sql_include=sql_include
            )
            if nested in seen:
                # COPY and INCLUDE of one member: one edge, as for a program.
                continue
            seen.add(nested)
            copy_edges.append(
                CopyEdge(program=member, member=nested, path=nested_path, nested=True)
            )
            if nested in stack:
                unresolved.append(
                    "circular COPY chain: " + " -> ".join([*stack, nested])
                )
                continue
            self._walk_member(nested, [*stack, nested], copy_edges, unresolved)


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

        member_path = self._member_path(wanted)
        fields: list[str] = []
        if member_path is None:
            unresolved.append(
                f"member {wanted} was not resolved to a file, so the data items "
                "it contributes are unknown"
            )
        else:
            fields, field_problem = _member_fields(member_path)
            if field_problem is not None:
                unresolved.append(field_problem)

        return ImpactReport(
            member=wanted,
            direct_programs=direct,
            transitive_programs=transitive,
            chains=chains,
            fields=fields,
            unresolved=sorted(set(unresolved)),
        )

    def _member_path(self, member: str) -> str | None:
        for edge in self.graph.copy_edges:
            if edge.member == member and edge.path:
                return edge.path
        return None

    def _chains(self, member: str) -> list[list[str]]:
        """One ``[program, outer, ..., member]`` chain per transitive reach."""
        chains: list[list[str]] = []

        def walk(current: str, tail: list[str]) -> None:
            for edge in self.graph.copy_edges:
                if edge.member != current:
                    continue
                if edge.nested:
                    if edge.program in tail:
                        # Circular COPY chain: already reported by the builder.
                        continue
                    walk(edge.program, [edge.program, *tail])
                elif len(tail) > 1:
                    chains.append([edge.program, *tail])

        walk(member, [member])
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

    try:
        records = parse_copybook_records(source, filename=member_path)
    except Exception as exc:  # noqa: BLE001 -- a member that is not a record
        # layout (procedure-division text, say) is a reported gap, not a crash.
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
    return sorted(name for name in names if name in declared), None
