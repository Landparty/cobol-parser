"""Field-level value flow inside one COBOL program (field lineage, layer 1).

``xref`` knows every place a field is read or written. This module keeps the
one thing xref throws away: *which* field a written value came from. Every
statement that moves a value becomes one or more ``LineageEdge``s,
``source -> target``, each carrying the statement, its line, its paragraph
and whether it sits under a condition or loop (``guarded``).

The edges end at the program's **ports**, the places a value enters or
leaves it:

====== ========================================= ===========================
kind   key                                       field within the port
====== ========================================= ===========================
file   DD name (``ASSIGN TO``, prefix stripped)  byte range in the record
call   ``CALLEE#n`` (argument position n)        byte range in the argument
linkage ``PROGRAM#n`` (USING position n)         byte range in the parameter
sql    ``TABLE.COLUMN``                          the whole column
console ``SYSIN`` / ``SYSOUT`` / ACCEPT FROM name the whole item
====== ========================================= ===========================

A field is named by its qualified data name inside the program, and by a
byte range on a port across programs: two programs reading one dataset
through different copybooks agree on bytes, not on names. Byte ranges come
from ``compute_program_data_items()``, the same numbers ``data-items``
reports and the record encoder writes.

It is a **may-flow** analysis: flow-insensitive, over-approximating. For
change impact a false "might be affected" costs a glance at the evidence
line; a missed one costs an outage. Everything that could not be followed
is listed in ``caveats``; nothing is dropped silently.

Group moves are byte overlays: ``MOVE IN-REC TO WS-REC`` becomes one edge per
pair of elementary fields whose byte ranges overlap, ``exact`` only when the
two ranges coincide. ``REDEFINES`` (and the implicit redefinition between the
01 records of one FD) adds a two-way ``redefines`` edge between overlapping
elementary fields.

Example:
    ```python
    from cobolparser import parse_cobol
    from cobolparser.analysis.field_lineage import FieldFlowAnalyzer

    report = FieldFlowAnalyzer().analyze(parse_cobol(source).ast)
    for edge in report.edges:
        print(edge.source.label(), "->", edge.target.label(), edge.kind, edge.line)
    for flow in report.summary:    # port field -> port field
        print(flow.source.label(), "=>", flow.target.label(), flow.kinds)
    ```
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

from ..models.ast_base import ASTNode, SourceLocation
from ..models.program import CobolProgram, CobolSection
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.base import CobolStatement
from ..models.statements.call import CallStatement
from ..models.statements.data import (
    DisplayStatement,
    InitializeStatement,
    InspectStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.io import (
    IOAcceptStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
)
from ..models.statements.misc import (
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
    XmlJsonStatement,
)
from ._sql_flow import analyze_sql
from .value_tracker import DynamicCallAnalyzer
from .xref import ROLE_READ, ROLE_WRITE, XrefAnalyzer, _contained_node_ids

#: Bumped whenever the shape of ``FieldFlowReport.to_dict()`` changes, so a
#: consumer that stored reports (the LegacyLens backend) knows to recompute.
LINEAGE_VERSION = "1"

ITEM = "item"
PORT_FILE = "file"
PORT_CALL = "call"
PORT_LINKAGE = "linkage"
PORT_SQL = "sql"
PORT_CONSOLE = "console"
PORT_KINDS = (PORT_FILE, PORT_CALL, PORT_LINKAGE, PORT_SQL, PORT_CONSOLE)

#: Edge kinds whose target holds a value *computed* from the source, rather
#: than a copy of it.
VALUE_CHANGING_KINDS = frozenset({"arith", "string", "aggregate", "sql-expr"})

# Leading ASSIGN-name segments that are a device class or organization code,
# never part of the DD name (``UT-S-INFILE`` is DD ``INFILE``). The same list
# the LegacyLens backend's ``normalize_ddname`` strips, so the two agree on
# which DD a file is.
_ASSIGN_PREFIX_TOKENS = frozenset(
    {"UT", "UR", "DA", "S", "AS", "DISK", "TAPE", "SYSDA", "VIO"}
    | {"VS", "GS", "SD", "SQ"}
)

_REFMOD_RE = re.compile(r"\(\s*(\d+)\s*:\s*(\d+)?\s*\)\s*$")
_QUOTED_RE = re.compile(r"^\s*(['\"]).*\1\s*$")


def normalize_ddname(value: str | None) -> str:
    """Reduce an ``ASSIGN TO`` name to the DD name JCL binds it with."""
    if not value:
        return ""
    token = value.strip().rstrip(".").strip().strip("'\"").upper()
    if not token:
        return ""
    token = token.split()[-1]
    parts = token.split("-")
    while len(parts) > 1 and parts[0] in _ASSIGN_PREFIX_TOKENS:
        parts.pop(0)
    return "-".join(parts)


# --------------------------------------------------------------------------
# Report shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class LineageNode:
    """One endpoint of a value flow.

    ``kind`` is ``"item"`` for a data item of the program (``name`` is its
    qualified name, ``offset``/``length`` its record-relative bytes), or a
    port kind (``name`` is the port key, ``offset``/``length`` the field's
    bytes within the port; ``None`` for a SQL column or console item).
    """

    kind: str
    name: str
    offset: int | None = None
    length: int | None = None

    @property
    def is_port(self) -> bool:
        return self.kind != ITEM

    def label(self) -> str:
        if self.kind == ITEM:
            return self.name
        span = (
            f"@{self.offset}+{self.length}"
            if self.offset is not None and self.length is not None
            else ""
        )
        return f"{self.kind}:{self.name}{span}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "offset": self.offset,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineageNode:
        return cls(
            kind=data["kind"],
            name=data["name"],
            offset=data.get("offset"),
            length=data.get("length"),
        )


@dataclass(frozen=True)
class LineageEdge:
    """``source``'s value may end up in ``target``."""

    source: LineageNode
    target: LineageNode
    kind: str
    line: int
    statement: str
    paragraph: str | None = None
    guarded: bool = False
    exact: bool = True
    #: Where ``line`` really is on disk when the parsed text was the
    #: copybook-expanded source (see :func:`apply_source_map`).
    origin_file: str | None = None
    origin_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "kind": self.kind,
            "line": self.line,
            "statement": self.statement,
            "paragraph": self.paragraph,
            "guarded": self.guarded,
            "exact": self.exact,
        }
        if self.origin_line is not None:
            data["origin"] = {"file": self.origin_file, "line": self.origin_line}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineageEdge:
        return cls(
            source=LineageNode.from_dict(data["source"]),
            target=LineageNode.from_dict(data["target"]),
            kind=data["kind"],
            line=int(data.get("line") or 0),
            statement=data.get("statement") or "",
            paragraph=data.get("paragraph"),
            guarded=bool(data.get("guarded")),
            exact=bool(data.get("exact", True)),
            origin_file=(data.get("origin") or {}).get("file"),
            origin_line=(data.get("origin") or {}).get("line"),
        )


@dataclass
class Port:
    """A place values enter (``"in"``) or leave (``"out"``) the program."""

    kind: str
    key: str
    directions: set[str] = field(default_factory=set)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "directions": sorted(self.directions),
            "detail": dict(sorted(self.detail.items())),
        }


@dataclass(frozen=True)
class KeyUse:
    """A field used to select records or rows: a READ/START KEY, a RECORD
    KEY, or a ``WHERE column = :host-var``. The raw material for key
    relationships between datasets and tables."""

    port: LineageNode
    item: str
    line: int
    statement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port.to_dict(),
            "item": self.item,
            "line": self.line,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class PortFlow:
    """One input-port field reaches one output-port field inside the
    program: the program's interface-level summary."""

    source: LineageNode
    target: LineageNode
    kinds: tuple[str, ...]
    via: tuple[str, ...]
    lines: tuple[int, ...]
    guarded: bool

    @property
    def derived(self) -> bool:
        """True when the value is computed on the way, not copied."""
        return any(kind in VALUE_CHANGING_KINDS for kind in self.kinds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "kinds": list(self.kinds),
            "derived": self.derived,
            "via": list(self.via),
            "lines": list(self.lines),
            "guarded": self.guarded,
        }


@dataclass
class FieldFlowReport:
    program_id: str
    items: list[dict[str, Any]] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)
    summary: list[PortFlow] = field(default_factory=list)
    key_uses: list[KeyUse] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def port(self, kind: str, key: str) -> Port | None:
        for port in self.ports:
            if port.kind == kind and port.key == key:
                return port
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_version": LINEAGE_VERSION,
            "program_id": self.program_id,
            "items": self.items,
            "ports": [p.to_dict() for p in self.ports],
            "edges": [e.to_dict() for e in self.edges],
            "summary": [s.to_dict() for s in self.summary],
            "key_uses": [k.to_dict() for k in self.key_uses],
            "caveats": list(self.caveats),
            "statistics": {
                "items": len(self.items),
                "ports": len(self.ports),
                "edges": len(self.edges),
                "summary": len(self.summary),
                "key_uses": len(self.key_uses),
            },
        }

    def to_text(self) -> str:
        lines = [f"Field lineage: {self.program_id or '<unnamed>'}", ""]
        lines.append(f"Ports ({len(self.ports)}):")
        for port in self.ports:
            directions = "/".join(sorted(port.directions)) or "-"
            lines.append(f"  {port.kind:<8} {port.key:<40} {directions}")
        lines.append("")
        lines.append(f"Port to port ({len(self.summary)}):")
        for flow in self.summary:
            tag = " derived" if flow.derived else ""
            cond = " guarded" if flow.guarded else ""
            via = " via " + " -> ".join(flow.via) if flow.via else ""
            lines.append(
                f"  {flow.source.label()} => {flow.target.label()}"
                f"{via}  [{', '.join(flow.kinds)}{tag}{cond}]"
            )
        if self.caveats:
            lines.append("")
            lines.append("Caveats:")
            lines += [f"  - {c}" for c in self.caveats]
        return "\n".join(lines) + "\n"


def apply_source_map(
    report: FieldFlowReport, source_map: dict[int, tuple[str, int]] | None
) -> FieldFlowReport:
    """Stamp every edge with the file and line it really came from.

    Lines count in whatever text was parsed; with copybook expansion that is
    the expanded listing, not the file on disk. ``source_map`` is
    ``ParseResult.expansion_source_map``. A ``None`` map, or a line it does
    not cover, leaves the edge as it was. Modifies *report* in place and
    returns it.
    """
    if not source_map:
        return report
    edges: list[LineageEdge] = []
    for edge in report.edges:
        origin = source_map.get(edge.line) if edge.line else None
        if origin is not None:
            edge = replace(edge, origin_file=origin[0], origin_line=origin[1])
        edges.append(edge)
    report.edges = edges
    return report


# --------------------------------------------------------------------------
# Analyzer
# --------------------------------------------------------------------------


@dataclass
class _Item:
    qname: str
    name: str
    level: int
    is_group: bool
    offset: int | None
    length: int
    parent: str | None
    redefines_chain: list[str]
    root: str = ""
    children: list[str] = field(default_factory=list)


@dataclass
class _Context:
    paragraph: str | None
    guarded: bool
    location: SourceLocation | None


class FieldFlowAnalyzer:
    """Build the value-flow edges and port summary of one program unit.

    Follows this package's ``<Analyzer>().analyze(ast) -> <Report>`` shape.
    Single program unit: a contained program's statements are not walked
    (analyze each unit from ``ast.program_units()`` on its own).
    """

    def __init__(self) -> None:
        self._xref = XrefAnalyzer()
        self._reset()

    def _reset(self) -> None:
        self._items: dict[str, _Item] = {}
        self._by_name: dict[str, list[str]] = {}
        self._leaves_cache: dict[str, list[_Item]] = {}
        self._file_dd: dict[str, str] = {}
        self._file_records: dict[str, list[str]] = {}
        self._record_file: dict[str, str] = {}
        self._record_keys: dict[str, list[str]] = {}
        self._ports: dict[tuple[str, str], Port] = {}
        self._edges: dict[tuple[Any, ...], LineageEdge] = {}
        self._key_uses: list[KeyUse] = []
        self._caveats: list[str] = []
        self._caveat_set: set[str] = set()
        self._cursors: dict[str, str] = {}
        self._program_id = ""

    # -- entry point -------------------------------------------------------

    def analyze(self, ast: CobolProgram) -> FieldFlowReport:
        self._reset()
        self._program_id = (ast.program_name or "").upper()
        # xref's own pass decides what is *undeclared* (reserved words,
        # special registers, intrinsic functions and level-88 / index names
        # are not), so the caveat below lists only real gaps.
        undefined = self._xref.analyze(ast).undefined
        # Fills CallStatement.possible_values: which programs a dynamic CALL
        # can reach, from the MOVEs and VALUE clauses of its identifier.
        DynamicCallAnalyzer().analyze(ast)
        self._index_items(ast)
        self._index_files(ast)
        inner = _contained_node_ids(ast)
        statements = [
            node
            for node in ast.traverse_depth_first()
            if isinstance(node, CobolStatement) and id(node) not in inner
        ]
        # DECLARE CURSOR first: a FETCH needs its cursor's SELECT list, and
        # the DECLARE usually sits in WORKING-STORAGE or after the FETCH.
        for stmt in statements:
            if type(stmt).__name__ == "DeclareCursorStatement" or (
                getattr(stmt, "sql_text", "").upper().lstrip().startswith("DECLARE")
            ):
                self._visit_sql(stmt, _Context(None, False, stmt.location))
        self._redefines_edges()
        self._linkage_edges(ast)
        visited: set[int] = set()
        proc = ast.procedure_division
        if proc is not None:
            for item in self._xref._ordered_procedures(proc):
                if isinstance(item, CobolSection):
                    for para in item.paragraphs:
                        self._walk_paragraph(para, visited)
                else:
                    self._walk_paragraph(item, visited)
        for stmt in statements:
            if id(stmt) not in visited and not isinstance(stmt, SelectStatement):
                visited.add(id(stmt))
                self._visit(stmt, _Context(None, False, stmt.location))

        if undefined:
            names = ", ".join(undefined[:20])
            more = len(undefined) - 20
            suffix = f" (and {more} more)" if more > 0 else ""
            self._caveat(
                "names used in statements but not declared in this program "
                "(an unexpanded COPY member, a special register, or a "
                f"precompiler item) were not traced: {names}{suffix}"
            )

        report = FieldFlowReport(program_id=self._program_id)
        report.items = [
            {
                "qualified_name": item.qname,
                "name": item.name,
                "level": item.level,
                "is_group": item.is_group,
                "offset": item.offset,
                "length": item.length,
                "record": item.root,
            }
            for item in self._items.values()
        ]
        report.ports = sorted(self._ports.values(), key=lambda p: (p.kind, p.key))
        report.edges = sorted(
            self._edges.values(),
            key=lambda e: (e.line, e.source, e.target, e.kind),
        )
        report.key_uses = sorted(
            set(self._key_uses), key=lambda k: (k.line, k.port, k.item)
        )
        report.summary = self._summarize(report.edges)
        report.caveats = list(self._caveats)
        return report

    def _caveat(self, text: str) -> None:
        if text not in self._caveat_set:
            self._caveat_set.add(text)
            self._caveats.append(text)

    # -- data items --------------------------------------------------------

    def _index_items(self, ast: CobolProgram) -> None:
        from ..generators.data.layout_offsets import compute_program_data_items

        data = compute_program_data_items(ast)
        for entry in data["items"]:
            level = int(entry.get("level") or 0)
            if level in (66, 88):
                continue
            name = (entry.get("name") or "").upper()
            if not name or name == "FILLER":
                # FILLER is still bytes: keep it for overlays, unnamed.
                pass
            item = _Item(
                qname=entry["qualified_name"].upper(),
                name=name,
                level=level,
                is_group=bool(entry.get("is_group")),
                offset=entry.get("byte_offset"),
                length=int(entry.get("byte_length") or 0),
                parent=(entry.get("parent_qualified_name") or None),
                redefines_chain=[
                    str(r).upper() for r in entry.get("redefines_chain") or []
                ],
            )
            if item.parent:
                item.parent = item.parent.upper()
            if item.qname in self._items:
                continue
            self._items[item.qname] = item
            if name and name != "FILLER":
                self._by_name.setdefault(name, []).append(item.qname)
        for item in self._items.values():
            if item.parent and item.parent in self._items:
                self._items[item.parent].children.append(item.qname)
            root = item
            while root.parent and root.parent in self._items:
                root = self._items[root.parent]
            item.root = root.qname
        for message in data.get("unresolved") or []:
            self._caveat(f"byte layout: {message}")

    def _leaves(self, qname: str) -> list[_Item]:
        cached = self._leaves_cache.get(qname)
        if cached is not None:
            return cached
        item = self._items[qname]
        if not item.children:
            out = [item]
        else:
            out = []
            for child in item.children:
                out.extend(self._leaves(child))
        self._leaves_cache[qname] = out
        return out

    def _resolve(self, text: str) -> list[str]:
        """Qualified names a (possibly ``A OF B``-qualified) name means."""
        parts = [p.strip().upper() for p in text.split(" OF ") if p.strip()]
        if not parts:
            return []
        name, qualifiers = parts[0], parts[1:]
        candidates = self._by_name.get(name, [])
        if qualifiers:
            narrowed = [
                q
                for q in candidates
                if all(qual in q.split(".")[:-1] for qual in qualifiers)
            ]
            if narrowed:
                candidates = narrowed
        return list(candidates)

    def _operand(self, value: Any, role: str) -> list[str]:
        """Resolve one operand value (operand text or expression) to the
        qualified names it reads or writes in *role*; subscripts, reference
        modifiers and qualifiers are never the value itself."""
        if value is None:
            return []
        if isinstance(value, str) and _QUOTED_RE.match(value):
            return []
        out: list[str] = []
        for name, resolved_role, _exact in self._xref._names_for(value, role):
            if resolved_role != role:
                continue
            for qname in self._resolve(name):
                if qname not in out:
                    out.append(qname)
        return out

    @staticmethod
    def _refmod(value: Any) -> tuple[int, int | None] | None:
        """A literal reference modifier ``(start:length)`` on *value*, as a
        0-based offset and an optional length."""
        if not isinstance(value, str):
            return None
        match = _REFMOD_RE.search(value)
        if not match:
            return None
        start = int(match.group(1)) - 1
        length = int(match.group(2)) if match.group(2) else None
        return max(start, 0), length

    def _item_node(self, qname: str) -> LineageNode:
        item = self._items[qname]
        return LineageNode(ITEM, qname, item.offset, item.length)

    # -- files -------------------------------------------------------------

    def _index_files(self, ast: CobolProgram) -> None:
        inner = _contained_node_ids(ast)
        for node in ast.traverse_depth_first():
            if id(node) in inner or not isinstance(node, SelectStatement):
                continue
            if not node.file_name:
                continue
            file_name = node.file_name.upper()
            dd = normalize_ddname(
                node.assign_external_name or node.assign_to or node.assign_using
            )
            self._file_dd[file_name] = dd or file_name
            keys = [node.record_key] if node.record_key else []
            for alternate in node.alternate_keys:
                if alternate.get("key"):
                    keys.append(alternate["key"])
            self._record_keys[file_name] = [str(k) for k in keys]
        try:
            from ..generators.data.program_layout import ProgramLayoutIndex

            index = ProgramLayoutIndex.build(ast)
        except Exception as exc:  # pragma: no cover - defensive
            self._caveat(f"file/record index could not be built: {exc}")
            return
        for file_name in index.file_names():
            records = [
                r.name.upper()
                for r in index.records_for_file(file_name)
                if r.name and r.name.upper() in self._items
            ]
            upper = file_name.upper()
            self._file_records[upper] = records
            self._file_dd.setdefault(upper, upper)
            for record in records:
                self._record_file[record] = upper
        for file_name, keys in self._record_keys.items():
            for key in keys:
                for qname in self._resolve(key):
                    port = self._port_node_for_file_item(file_name, qname)
                    if port is not None:
                        self._key_uses.append(
                            KeyUse(port, qname, 0, "SELECT RECORD KEY")
                        )

    def _file_port(self, file_name: str) -> Port:
        upper = file_name.upper()
        dd = self._file_dd.get(upper, upper)
        port = self._port(PORT_FILE, dd)
        port.detail["file"] = upper
        return port

    def _port_node_for_file_item(
        self, file_name: str, qname: str
    ) -> LineageNode | None:
        item = self._items.get(qname)
        if item is None or item.offset is None:
            return None
        dd = self._file_dd.get(file_name.upper(), file_name.upper())
        root = self._items.get(item.root)
        base = root.offset or 0 if root else 0
        return LineageNode(PORT_FILE, dd, item.offset - base, item.length)

    # -- ports and edges ---------------------------------------------------

    def _port(self, kind: str, key: str) -> Port:
        port = self._ports.get((kind, key))
        if port is None:
            port = Port(kind=kind, key=key)
            self._ports[(kind, key)] = port
        return port

    def _edge(
        self,
        source: LineageNode,
        target: LineageNode,
        kind: str,
        ctx: _Context,
        statement: str,
        exact: bool = True,
    ) -> None:
        if source == target:
            return
        line = ctx.location.line if ctx.location is not None else 0
        key = (source, target, kind, line)
        if key in self._edges:
            return
        self._edges[key] = LineageEdge(
            source=source,
            target=target,
            kind=kind,
            line=line,
            statement=statement,
            paragraph=ctx.paragraph,
            guarded=ctx.guarded,
            exact=exact,
        )

    def _overlay(
        self,
        source: str,
        target: str,
        kind: str,
        ctx: _Context,
        statement: str,
        source_window: tuple[int, int | None] | None = None,
        target_window: tuple[int, int | None] | None = None,
    ) -> None:
        """Edges for a byte-for-byte transfer from *source* to *target*.

        Two elementary items: one edge (a numeric MOVE aligns by decimal
        point, not by byte). Anything involving a group: one edge per pair
        of elementary fields whose byte ranges, measured from the start of
        each operand, overlap.
        """
        src, tgt = self._items[source], self._items[target]
        if not src.children and not tgt.children:
            self._edge(
                self._item_node(source), self._item_node(target), kind, ctx, statement
            )
            return
        if src.offset is None or tgt.offset is None:
            for s in self._leaves(source):
                for t in self._leaves(target):
                    self._edge(
                        self._item_node(s.qname),
                        self._item_node(t.qname),
                        kind,
                        ctx,
                        statement,
                        exact=False,
                    )
            return
        s_base, s_len = src.offset, src.length
        t_base, t_len = tgt.offset, tgt.length
        if source_window is not None:
            s_base += source_window[0]
            s_len = source_window[1] or max(s_len - source_window[0], 0)
        if target_window is not None:
            t_base += target_window[0]
            t_len = target_window[1] or max(t_len - target_window[0], 0)
        span = min(s_len, t_len)
        sources = [
            (s, s.offset - s_base)
            for s in self._leaves(source)
            if s.offset is not None
            and s.offset + s.length > s_base
            and s.offset < s_base + span
        ]
        targets = [
            (t, t.offset - t_base)
            for t in self._leaves(target)
            if t.offset is not None
            and t.offset + t.length > t_base
            and t.offset < t_base + span
        ]
        for s, s_rel in sources:
            for t, t_rel in targets:
                if s_rel < t_rel + t.length and t_rel < s_rel + s.length:
                    self._edge(
                        self._item_node(s.qname),
                        self._item_node(t.qname),
                        kind,
                        ctx,
                        statement,
                        exact=(s_rel == t_rel and s.length == t.length),
                    )

    def _to_port(
        self,
        qname: str,
        port: Port,
        kind: str,
        ctx: _Context,
        statement: str,
        *,
        into_program: bool,
        out_of_program: bool,
    ) -> None:
        """Connect every elementary field of *qname* to its byte range on
        *port*, measured from the start of *qname*."""
        item = self._items[qname]
        base = item.offset or 0
        for leaf in self._leaves(qname):
            rel = (leaf.offset - base) if leaf.offset is not None else None
            node = LineageNode(port.kind, port.key, rel, leaf.length)
            if out_of_program:
                port.directions.add("out")
                self._edge(self._item_node(leaf.qname), node, kind, ctx, statement)
            if into_program:
                port.directions.add("in")
                self._edge(node, self._item_node(leaf.qname), kind, ctx, statement)

    def _redefines_edges(self) -> None:
        """Two-way edges between elementary fields that share bytes:
        ``REDEFINES``, and the 01 records of one FD (one buffer)."""
        buffers: dict[str, list[str]] = {}
        for item in self._items.values():
            if item.parent is None:
                anchor = (
                    item.redefines_chain[-1] if item.redefines_chain else item.qname
                )
                anchor = anchor.upper()
                file_name = self._record_file.get(item.qname) or self._record_file.get(
                    anchor
                )
                key = f"FD:{file_name}" if file_name else anchor
                buffers.setdefault(key, []).append(item.qname)
        ctx = _Context(None, False, None)
        for roots in buffers.values():
            leaves = [leaf for root in roots for leaf in self._leaves(root)]
            leaves = [leaf for leaf in leaves if leaf.offset is not None]
            leaves.sort(key=lambda leaf: (leaf.offset, leaf.qname))
            for i, a in enumerate(leaves):
                assert a.offset is not None
                for b in leaves[i + 1 :]:
                    assert b.offset is not None
                    if b.offset >= a.offset + a.length:
                        break
                    if a.qname == b.qname or a.length == 0 or b.length == 0:
                        continue
                    exact = a.offset == b.offset and a.length == b.length
                    na, nb = self._item_node(a.qname), self._item_node(b.qname)
                    self._edge(na, nb, "redefines", ctx, "REDEFINES", exact)
                    self._edge(nb, na, "redefines", ctx, "REDEFINES", exact)

    def _linkage_edges(self, ast: CobolProgram) -> None:
        from .program_signature import ProgramSignatureExtractor

        signature = ProgramSignatureExtractor().analyze(ast)
        for entry in signature.entry_points:
            name = (entry.name or self._program_id).upper().strip("'\"")
            for position, parameter in enumerate(entry.parameters, start=1):
                for qname in self._resolve(parameter.name):
                    port = self._port(PORT_LINKAGE, f"{name}#{position}")
                    port.detail.update({"entry": name, "position": position})
                    ctx = _Context(None, False, ast.location)
                    self._to_port(
                        qname,
                        port,
                        "linkage",
                        ctx,
                        (
                            "PROCEDURE DIVISION USING"
                            if entry.kind == "procedure-division"
                            else "ENTRY USING"
                        ),
                        into_program=True,
                        out_of_program=True,
                    )

    # -- statement walk ----------------------------------------------------

    def _walk_paragraph(self, para: Any, visited: set[int]) -> None:
        for stmt in para.statements:
            self._walk(stmt, para.paragraph_name, para.location, False, visited)

    def _walk(
        self,
        node: ASTNode,
        paragraph: str | None,
        fallback: SourceLocation | None,
        guarded: bool,
        visited: set[int],
    ) -> None:
        if id(node) in visited:
            return
        visited.add(id(node))
        nested = guarded
        if isinstance(node, CobolStatement):
            location = node.location if node.location.line > 0 else fallback
            self._visit(node, _Context(paragraph, guarded, location))
            nested = True
        for child in node.children:
            self._walk(child, paragraph, fallback, nested, visited)

    def _visit(self, stmt: CobolStatement, ctx: _Context) -> None:
        name = type(stmt).__name__
        if isinstance(stmt, MoveStatement):
            self._visit_move(stmt, ctx)
        elif isinstance(stmt, (ComputeStatement, ArithmeticStatement)):
            self._reads_to_writes(stmt, "arith", ctx)
        elif isinstance(stmt, (StringStatement, UnstringStatement, InspectStatement)):
            self._reads_to_writes(stmt, "string", ctx)
        elif isinstance(stmt, (InitializeStatement, SetStatement, XmlJsonStatement)):
            kind = "set" if isinstance(stmt, SetStatement) else "move"
            self._reads_to_writes(stmt, kind, ctx)
        elif isinstance(stmt, IOReadStatement):
            self._visit_read(stmt, ctx)
        elif isinstance(stmt, (IOWriteStatement, IORewriteStatement)):
            self._visit_write(stmt, ctx)
        elif isinstance(stmt, IOStartStatement):
            self._key_use(stmt.file_name, stmt.key_name, ctx, "START")
        elif isinstance(stmt, ReleaseStatement):
            if stmt.record_name and stmt.from_source:
                for src in self._operand(stmt.from_source, ROLE_READ):
                    for rec in self._operand(stmt.record_name, ROLE_READ):
                        self._overlay(src, rec, "move", ctx, "RELEASE FROM")
        elif isinstance(stmt, ReturnStatement):
            if stmt.file_name and stmt.into_target:
                for rec in self._file_records.get(stmt.file_name.upper(), []):
                    for tgt in self._operand(stmt.into_target, ROLE_WRITE):
                        self._overlay(rec, tgt, "move", ctx, "RETURN INTO")
        elif isinstance(stmt, (SortStatement, MergeStatement)):
            self._visit_sort(stmt, ctx)
        elif isinstance(stmt, IOAcceptStatement):
            source = (stmt.from_source or "SYSIN").upper()
            port = self._port(PORT_CONSOLE, source)
            for tgt in self._operand(stmt.target, ROLE_WRITE):
                self._to_port(
                    tgt,
                    port,
                    "accept",
                    ctx,
                    "ACCEPT",
                    into_program=True,
                    out_of_program=False,
                )
        elif isinstance(stmt, DisplayStatement):
            port = self._port(PORT_CONSOLE, "SYSOUT")
            for item in stmt.display_items:
                for src in self._operand(item, ROLE_READ):
                    self._to_port(
                        src,
                        port,
                        "display",
                        ctx,
                        "DISPLAY",
                        into_program=False,
                        out_of_program=True,
                    )
        elif isinstance(stmt, CallStatement):
            self._visit_call(stmt, ctx)
        elif hasattr(stmt, "sql_text"):
            self._visit_sql(stmt, ctx)
        elif name == "ExecCicsStatement":
            self._caveat(
                "EXEC CICS data areas (COMMAREA, containers, TS/TD queues) are "
                "not traced yet"
            )
        elif name == "ExecImsStatement":
            self._caveat("EXEC DLI I/O areas are not traced yet")

    def _reads_to_writes(self, stmt: CobolStatement, kind: str, ctx: _Context) -> None:
        reads: list[str] = []
        writes: list[str] = []
        for value, role, _exact in self._xref._role_assignments(stmt):
            if role == ROLE_READ:
                reads += [q for q in self._operand(value, ROLE_READ) if q not in reads]
            elif role == ROLE_WRITE:
                writes += [
                    q for q in self._operand(value, ROLE_WRITE) if q not in writes
                ]
        statement = stmt.statement_type or type(stmt).__name__
        for src in reads:
            for tgt in writes:
                for s in self._leaves(src):
                    for t in self._leaves(tgt):
                        self._edge(
                            self._item_node(s.qname),
                            self._item_node(t.qname),
                            kind,
                            ctx,
                            statement,
                        )

    def _visit_move(self, stmt: MoveStatement, ctx: _Context) -> None:
        if not stmt.source:
            return
        sources = self._operand(stmt.source, ROLE_READ)
        if not sources:
            return
        src_window = self._refmod(stmt.source)
        for target_text in stmt.targets:
            tgt_window = self._refmod(target_text)
            for tgt in self._operand(target_text, ROLE_WRITE):
                for src in sources:
                    if stmt.is_corresponding:
                        self._corresponding(src, tgt, ctx)
                    else:
                        self._overlay(
                            src, tgt, "move", ctx, "MOVE", src_window, tgt_window
                        )

    def _corresponding(self, source: str, target: str, ctx: _Context) -> None:
        def paths(root: str) -> dict[tuple[str, ...], str]:
            base = self._items[root].qname.split(".")
            out: dict[tuple[str, ...], str] = {}
            for leaf in self._leaves(root):
                rel = tuple(leaf.qname.split(".")[len(base) :])
                if rel and "FILLER" not in rel:
                    out[rel] = leaf.qname
            return out

        target_paths = paths(target)
        for rel, s in paths(source).items():
            t = target_paths.get(rel)
            if t is not None:
                self._edge(
                    self._item_node(s),
                    self._item_node(t),
                    "move",
                    ctx,
                    "MOVE CORRESPONDING",
                )

    def _visit_read(self, stmt: IOReadStatement, ctx: _Context) -> None:
        file_name = (stmt.file_name or "").upper()
        if not file_name:
            return
        records = self._file_records.get(file_name, [])
        if not records:
            self._caveat(
                f"READ {file_name}: no FD record layout is known, so the record "
                "is not traced"
            )
            return
        port = self._file_port(file_name)
        for record in records:
            self._to_port(
                record,
                port,
                "read",
                ctx,
                "READ",
                into_program=True,
                out_of_program=False,
            )
            if stmt.into_target:
                for tgt in self._operand(stmt.into_target, ROLE_WRITE):
                    self._overlay(record, tgt, "move", ctx, "READ INTO")
        self._key_use(file_name, stmt.key_name, ctx, "READ KEY")

    def _visit_write(self, stmt: Any, ctx: _Context) -> None:
        if not stmt.record_name:
            return
        verb = "REWRITE" if isinstance(stmt, IORewriteStatement) else "WRITE"
        for record in self._operand(stmt.record_name, ROLE_READ):
            if stmt.from_clause:
                for src in self._operand(stmt.from_clause, ROLE_READ):
                    self._overlay(src, record, "move", ctx, f"{verb} FROM")
            root = self._items[record].root
            file_name = self._record_file.get(root)
            if file_name is None:
                self._caveat(
                    f"{verb} {record}: the record belongs to no FD this analyzer "
                    "could find, so its file is not traced"
                )
                continue
            self._to_port(
                record,
                self._file_port(file_name),
                "write",
                ctx,
                verb,
                into_program=False,
                out_of_program=True,
            )

    def _visit_sort(self, stmt: Any, ctx: _Context) -> None:
        sd = (getattr(stmt, "file_name", None) or "").upper()
        sd_records = self._file_records.get(sd, [])
        verb = type(stmt).__name__.replace("Statement", "").upper()
        for using in getattr(stmt, "using_files", None) or []:
            using = using.upper()
            port = self._file_port(using)
            for record in self._file_records.get(using, []):
                self._to_port(
                    record,
                    port,
                    "read",
                    ctx,
                    f"{verb} USING",
                    into_program=True,
                    out_of_program=False,
                )
                for sd_record in sd_records:
                    self._overlay(record, sd_record, "move", ctx, f"{verb} USING")
        for giving in getattr(stmt, "giving_files", None) or []:
            giving = giving.upper()
            port = self._file_port(giving)
            for record in self._file_records.get(giving, []):
                for sd_record in sd_records:
                    self._overlay(sd_record, record, "move", ctx, f"{verb} GIVING")
                self._to_port(
                    record,
                    port,
                    "write",
                    ctx,
                    f"{verb} GIVING",
                    into_program=False,
                    out_of_program=True,
                )

    def _key_use(
        self, file_name: str | None, key: str | None, ctx: _Context, statement: str
    ) -> None:
        if not file_name or not key:
            return
        for qname in self._resolve(key):
            node = self._port_node_for_file_item(file_name, qname)
            if node is not None:
                line = ctx.location.line if ctx.location is not None else 0
                self._key_uses.append(KeyUse(node, qname, line, statement))

    def _visit_call(self, stmt: CallStatement, ctx: _Context) -> None:
        target = (stmt.called_program or "").strip().strip("'\"").upper()
        if not target:
            return
        callees = [target]
        if stmt.is_dynamic:
            values = [
                v.strip().strip("'\"").upper()
                for v in getattr(stmt, "possible_values", None) or []
            ]
            if values:
                callees = values
            else:
                callees = [f"?{target}"]
                self._caveat(
                    f"dynamic CALL {target}: no candidate program names were "
                    "found, so its arguments are joined to no callee"
                )
        for callee in callees:
            for position, parameter in enumerate(stmt.using_parameters, start=1):
                if not parameter.name or _QUOTED_RE.match(parameter.name):
                    continue
                mode = (parameter.passing_mode or "REFERENCE").upper()
                by_reference = mode not in ("CONTENT", "VALUE")
                port = self._port(PORT_CALL, f"{callee}#{position}")
                port.detail.update(
                    {"callee": callee, "position": position, "dynamic": stmt.is_dynamic}
                )
                for qname in self._resolve(parameter.name):
                    self._to_port(
                        qname,
                        port,
                        "call",
                        ctx,
                        "CALL",
                        into_program=by_reference,
                        out_of_program=True,
                    )
            for attr in ("returning_parameter", "giving_parameter"):
                value = getattr(stmt, attr, None)
                if not value:
                    continue
                port = self._port(PORT_CALL, f"{callee}#RETURNING")
                port.detail.update({"callee": callee, "position": "RETURNING"})
                for qname in self._resolve(value):
                    self._to_port(
                        qname,
                        port,
                        "call",
                        ctx,
                        "CALL RETURNING",
                        into_program=True,
                        out_of_program=False,
                    )

    def _visit_sql(self, stmt: Any, ctx: _Context) -> None:
        text = getattr(stmt, "sql_text", "") or ""
        select = getattr(stmt, "select_statement", None)
        if (
            type(stmt).__name__ == "DeclareCursorStatement"
            and select
            and stmt.cursor_name
        ):
            text = f"DECLARE {stmt.cursor_name} CURSOR FOR {select}"
        result = analyze_sql(text, self._cursors)
        if result.declared_cursor is not None:
            name, body = result.declared_cursor
            if name in self._cursors:
                return  # seen in the pre-pass
            self._cursors[name] = body
        for caveat in result.caveats:
            self._caveat(
                f"EXEC SQL (line {ctx.location.line if ctx.location else 0}): {caveat}"
            )
        for flow in result.flows:
            port = self._port(PORT_SQL, f"{flow.table}.{flow.column}")
            port.detail.update({"table": flow.table, "column": flow.column})
            column = LineageNode(PORT_SQL, port.key)
            for qname in self._resolve(flow.host_var):
                for leaf in self._leaves(qname):
                    node = self._item_node(leaf.qname)
                    if flow.direction == "out":
                        port.directions.add("out")
                        self._edge(node, column, flow.kind, ctx, "EXEC SQL", flow.exact)
                    else:
                        port.directions.add("in")
                        self._edge(column, node, flow.kind, ctx, "EXEC SQL", flow.exact)
        line = ctx.location.line if ctx.location is not None else 0
        for key in result.keys:
            node = LineageNode(PORT_SQL, f"{key.table}.{key.column}")
            for qname in self._resolve(key.host_var):
                self._key_uses.append(KeyUse(node, qname, line, "EXEC SQL WHERE"))

    # -- summary -----------------------------------------------------------

    @staticmethod
    def _summarize(edges: list[LineageEdge]) -> list[PortFlow]:
        """Every input-port field -> every output-port field it reaches,
        through item nodes only (a port is a boundary, never a pass-through
        inside one program)."""
        out_edges: dict[LineageNode, list[LineageEdge]] = {}
        for edge in edges:
            out_edges.setdefault(edge.source, []).append(edge)
        flows: dict[tuple[LineageNode, LineageNode], PortFlow] = {}
        starts = sorted({e.source for e in edges if e.source.is_port})
        # State is (node, arrived over a redefines edge). Two overlays in a row
        # would carry a value from one field of a record to an unrelated
        # field of the same record through the alias covering both, so a
        # redefines edge is never followed by another one.
        State = tuple[LineageNode, bool]
        for start in starts:
            parent: dict[State, tuple[State, LineageEdge]] = {}
            first: State = (start, False)
            queue: deque[State] = deque([first])
            seen = {first}
            while queue:
                state = queue.popleft()
                node, via_overlay = state
                for edge in out_edges.get(node, []):
                    overlay = edge.kind == "redefines"
                    if overlay and via_overlay:
                        continue
                    nxt: State = (edge.target, overlay)
                    if nxt in seen:
                        continue
                    seen.add(nxt)
                    parent[nxt] = (state, edge)
                    if edge.target.is_port:
                        if (start, edge.target) in flows:
                            continue
                        path: list[LineageEdge] = []
                        cursor = nxt
                        while cursor != first:
                            cursor, step = parent[cursor]
                            path.append(step)
                        path.reverse()
                        flows[(start, edge.target)] = PortFlow(
                            source=start,
                            target=edge.target,
                            kinds=tuple(dict.fromkeys(e.kind for e in path)),
                            via=tuple(e.target.name for e in path[:-1]),
                            lines=tuple(sorted({e.line for e in path if e.line})),
                            guarded=any(e.guarded for e in path),
                        )
                        continue
                    queue.append(nxt)
        return sorted(flows.values(), key=lambda f: (f.source, f.target))
