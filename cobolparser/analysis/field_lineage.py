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
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field, replace
from functools import total_ordering
from typing import Any

from .._literals import is_quoted_literal
from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import RenamesItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
    CobolStatement,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)
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
from ._files import same_record_area_groups
from ._names import callee_names
from ._sql_flow import analyze_sql
from .value_tracker import DynamicCallAnalyzer
from .xref import (
    ROLE_READ,
    ROLE_WRITE,
    XrefAnalyzer,
    _contained_node_ids,
    _qualifier_names,
    _split_operand,
)

#: Bumped whenever the shape of ``FieldFlowReport.to_dict()`` changes, so a
#: consumer that stored reports (the LegacyLens backend) knows to recompute.
#: "2" (2026-10-08): OCCURS occurrences, ``PROGRAM#RETURNING`` linkage ports
#: and unique keys for same-named items (``FILLER#2``).
LINEAGE_VERSION = "2"

ITEM = "item"
PORT_FILE = "file"
PORT_CALL = "call"
PORT_LINKAGE = "linkage"
PORT_SQL = "sql"
PORT_CONSOLE = "console"
PORT_KINDS = (PORT_FILE, PORT_CALL, PORT_LINKAGE, PORT_SQL, PORT_CONSOLE)

#: ACCEPT sources the runtime fills from its own clock: no data enters the
#: program there, so they are not a console port. Matched on the source's
#: first word -- the parser keeps a format qualifier (``DATE YYYYMMDD``).
_CLOCK_ACCEPT_SOURCES = frozenset({"DATE", "DAY", "DAY-OF-WEEK", "TIME"})

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
#: Any trailing reference modifier, literal or not: ``(WS-POS:10)``.
_ANY_REFMOD_RE = re.compile(r"\(\s*([^():]+?)\s*:\s*([^():]*?)\s*\)\s*$")
#: One data reference: a (qualified) name, an optional subscript group and an
#: optional reference modifier -- nothing else (no operator, no second name).
_SINGLE_REF_RE = re.compile(
    r"^\s*(?P<name>[A-Z0-9][\w-]*(?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)*)\s*"
    r"(?:\((?P<subs>[^():]*)\))?\s*(?:\([^()]*:[^()]*\))?\s*$",
    re.IGNORECASE,
)

#: Occurrences of one table field mapped one by one; a table with more is
#: treated as one byte range spanning every occurrence.
_PLACEMENT_CAP = 1024

#: Edge kinds a path may not take twice in a row (see ``_summarize``).
_OVERLAY_CLASS = {"redefines": 1, "occurrence": 2, "table-alias": 3}


def overlay_class(kind: str) -> int:
    """0 for an ordinary edge; otherwise the class of alias edge *kind* is.
    Two alias edges of one class are never chained: a redefines after a
    redefines would carry one field of a record into every other through an
    alias covering both, an occurrence after an occurrence would carry
    ``T(1)`` into ``T(3)`` through the table as a whole, and a
    ``table-alias`` (``LineageGraph``'s schema-less column match) after
    another one ``PROD.T.C`` into ``TEST.T.C`` through ``T.C``."""
    return _OVERLAY_CLASS.get(kind, 0)


def _constant_subscripts(text: str) -> tuple[int, ...] | None:
    """The literal subscripts of a single reference (``AMT (3)``,
    ``T (2, 1)``); None when it has none or any is not a plain integer."""
    match = _SINGLE_REF_RE.match(text)
    if not match or match.group("subs") is None:
        return None
    tokens = [t for t in re.split(r"[\s,]+", match.group("subs").strip()) if t]
    if not tokens or not all(t.isdigit() for t in tokens):
        return None
    return tuple(int(t) for t in tokens)


def _expression_leaves(expr: Any) -> list[Any]:
    """Every operand value inside a condition/arithmetic expression tree,
    unsplit (``"Y ( I )"`` stays one operand, so its subscript can still be
    told apart from the value)."""
    if isinstance(expr, LogicalExpression):
        return _expression_leaves(expr.left_condition) + _expression_leaves(
            expr.right_condition
        )
    if isinstance(expr, FunctionCall):
        out: list[Any] = []
        for arg in expr.arguments:
            out += _expression_leaves(arg)
        return out
    if isinstance(expr, (ConditionalExpression, ArithmeticExpression)):
        return _expression_leaves(expr.left_operand) + _expression_leaves(
            expr.right_operand
        )
    if isinstance(expr, CobolExpression):
        if expr.operands:
            return [str(op) for op in expr.operands]
        raw = expr.get_metadata("raw_condition")
        return [str(raw)] if raw else []
    return [] if expr is None else [expr]


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


@total_ordering
@dataclass(frozen=True)
class LineageNode:
    """One endpoint of a value flow.

    ``kind`` is ``"item"`` for a data item of the program (``name`` is its
    qualified name, ``offset``/``length`` its record-relative bytes), or a
    port kind (``name`` is the port key, ``offset``/``length`` the field's
    bytes within the port; ``None`` for a SQL column or console item, and
    for a field whose offset moves with an ``OCCURS ... DEPENDING ON``
    table before it).

    An item named ``NAME(3)`` (``NAME(2,1)``) is one occurrence of a table
    field, addressed with literal subscripts; ``NAME`` alone stands for any
    occurrence. A second item with an already-used qualified name (two
    ``01 FILLER`` groups) is keyed ``NAME#2``.

    Nodes order by ``sort_key()``, where an unknown offset or length sorts
    first.
    """

    kind: str
    name: str
    offset: int | None = None
    length: int | None = None

    def sort_key(self) -> tuple[str, str, int, int]:
        return (
            self.kind,
            self.name,
            -1 if self.offset is None else self.offset,
            -1 if self.length is None else self.length,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LineageNode):
            return NotImplemented
        return self.sort_key() < other.sort_key()

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
    #: Unique key: the qualified name, ``#n``-suffixed for the n-th item
    #: sharing one (two ``01 FILLER`` groups).
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
    #: The qualified name as the layout spells it (no ``#n``).
    raw: str = ""
    #: ``OCCURS`` count (the maximum for DEPENDING ON); None when not a table.
    occurs: int | None = None
    #: ``"numeric"``, ``"numeric-edited"`` or ``""`` (anything else), for an
    #: elementary item: which items ADD/SUBTRACT CORRESPONDING pair up.
    category: str = ""


_FLOAT_USAGES = frozenset(
    {"COMP-1", "COMP-2", "COMPUTATIONAL-1", "COMPUTATIONAL-2"}
    | {"FLOAT-SHORT", "FLOAT-LONG", "FLOAT-EXTENDED"}
)


def _category(picture: Any, usage: Any) -> str:
    """``"numeric"``, ``"numeric-edited"`` or ``""`` for an elementary item's
    PICTURE / USAGE (only what ADD/SUBTRACT CORRESPONDING needs to know)."""
    if not picture:
        return "numeric" if str(usage or "").upper() in _FLOAT_USAGES else ""
    symbols = set(re.sub(r"\(\d+\)", "", str(picture).upper()))
    if symbols <= set("9SVP"):
        return "numeric"
    if symbols & set("XANGU"):
        return ""
    return "numeric-edited"


@dataclass(frozen=True)
class _Ref:
    """One operand: the item, a literal reference modifier ``(start, length)``
    (0-based) and literal subscripts, when the operand has them.
    ``loose_window``: the reference modifier's start (or length) is a data
    name, so the bytes it names may be anywhere in the item; ``window`` then
    holds ``(0, length)`` when the length is a literal (#527)."""

    qname: str
    window: tuple[int, int | None] | None = None
    subscripts: tuple[int, ...] | None = None
    loose_window: bool = False


@dataclass(frozen=True)
class _Piece:
    """One elementary field (or one occurrence of it) inside an operand:
    its node, its byte range relative to the operand's start, and whether
    an edge through it can be exact."""

    node: LineageNode
    rel: int
    length: int
    exact: bool


@dataclass
class _Context:
    paragraph: str | None
    guarded: bool
    location: SourceLocation | None


_NO_CONTEXT = _Context(None, False, None)


@dataclass
class _PortLink:
    """A table field mapped to a port: every literal-subscript occurrence of
    it the program also names gets an exact edge to its own bytes there."""

    leaf: str
    kind: str
    key: str
    base: int
    extent: int
    edge_kind: str
    statement: str
    into_program: bool
    out_of_program: bool
    context: _Context


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
        self._by_raw: dict[str, list[str]] = {}
        self._leaves_cache: dict[str, list[_Item]] = {}
        self._placements_cache: dict[str, list[tuple[int, int]] | None] = {}
        self._wide: set[str] = set()
        self._occ_nodes: dict[str, dict[str, LineageNode]] = {}
        self._port_links: list[_PortLink] = []
        self._file_dd: dict[str, str] = {}
        self._file_records: dict[str, list[str]] = {}
        self._record_file: dict[str, str] = {}
        self._record_keys: dict[str, list[str]] = {}
        #: File -> the first file of its ``SAME RECORD AREA`` group: the
        #: records of every file in a group share one area.
        self._record_area: dict[str, str] = {}
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
        self._index_renames(ast)
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
        self._link_occurrences()

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
                **({"occurs": item.occurs} if item.occurs is not None else {}),
            }
            for item in self._items.values()
        ]
        report.ports = sorted(self._ports.values(), key=lambda p: (p.kind, p.key))
        report.edges = sorted(
            self._edges.values(),
            key=lambda e: (e.line, e.source.sort_key(), e.target.sort_key(), e.kind),
        )
        report.key_uses = sorted(
            set(self._key_uses),
            key=lambda k: (k.line, k.port.sort_key(), k.item, k.statement),
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
        # One block per 01/77 record: the layout emits the record root first,
        # then its subordinates with every group *after* its own children.
        blocks: list[list[dict[str, Any]]] = []
        for entry in data["items"]:
            if int(entry.get("level") or 0) in (66, 88):
                continue
            if not entry.get("parent_qualified_name") or not blocks:
                blocks.append([entry])
            else:
                blocks[-1].append(entry)
        used: dict[str, int] = {}
        for block in blocks:
            raws = [str(e["qualified_name"]).upper() for e in block]
            keys: list[str] = []
            for raw in raws:
                used[raw] = used.get(raw, 0) + 1
                keys.append(raw if used[raw] == 1 else f"{raw}#{used[raw]}")
            for index, entry in enumerate(block):
                parent_raw = str(entry.get("parent_qualified_name") or "").upper()
                parent = None
                if parent_raw:
                    # The enclosing group is the next entry of that name (a
                    # group follows its children), else the record root.
                    for later in range(index + 1, len(block)):
                        if raws[later] == parent_raw:
                            parent = keys[later]
                            break
                    else:
                        parent = keys[0] if raws[0] == parent_raw else None
                name = (entry.get("name") or "").upper()
                occurs = entry.get("occurs")
                item = _Item(
                    qname=keys[index],
                    name=name,
                    level=int(entry.get("level") or 0),
                    is_group=bool(entry.get("is_group")),
                    offset=entry.get("byte_offset"),
                    length=int(entry.get("byte_length") or 0),
                    parent=parent,
                    redefines_chain=[
                        str(r).upper() for r in entry.get("redefines_chain") or []
                    ],
                    raw=raws[index],
                    occurs=(
                        int(occurs.get("max") or occurs.get("min") or 1)
                        if isinstance(occurs, dict)
                        else None
                    ),
                    category=_category(entry.get("picture"), entry.get("usage")),
                )
                self._items[item.qname] = item
                self._by_raw.setdefault(item.raw, []).append(item.qname)
                # FILLER is still bytes: kept for overlays, never by name.
                if name and name != "FILLER":
                    self._by_name.setdefault(name, []).append(item.qname)
        # Children in source order: within a block a group follows its
        # children, so attach them in block order.
        for item in self._items.values():
            if item.parent and item.parent in self._items:
                self._items[item.parent].children.append(item.qname)
            root = item
            while root.parent and root.parent in self._items:
                root = self._items[root.parent]
            item.root = root.qname
        for message in data.get("unresolved") or []:
            self._caveat(f"byte layout: {message}")

    def _index_renames(self, ast: CobolProgram) -> None:
        """Map each level-66 ``RENAMES`` item onto the bytes it names (#485).

        ``66 R-AB RENAMES R-A THRU R-B`` is an alias for the contiguous run
        of its record from the start of ``R-A`` to the end of ``R-B``. It
        becomes an item of its own whose children are the elementary fields
        inside that run, so a MOVE to or from it flows through them like
        through a group. One that cannot be placed (an operand not found,
        found twice, in another record, or at an unknown offset) is named in
        a caveat rather than silently left untraced.
        """
        data_div = ast.data_division
        if data_div is None:
            return
        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            for node in section.children:
                if isinstance(node, RenamesItem) and node.name:
                    reason = self._place_renames(node)
                    if reason:
                        self._caveat(
                            f"RENAMES item {node.name.upper()} not traced: {reason}"
                        )

    def _place_renames(self, node: RenamesItem) -> str | None:
        """Add the alias item for *node*; the reason it could not be, else None."""
        name = node.name.upper()
        if name in self._items or name in self._by_name:
            return "its name is also a data item's"
        ends: list[_Item] = []
        operands = [(node.renames_from, node.renames_from_qualifiers)]
        if node.renames_through:
            operands.append((node.renames_through, node.renames_through_qualifiers))
        for operand, qualifiers in operands:
            text = " OF ".join([str(operand), *qualifiers])
            found = self._resolve(text)
            if len(found) != 1:
                what = "not found" if not found else "ambiguous"
                return f"{text.upper()} is {what}"
            ends.append(self._items[found[0]])
        first, last = ends[0], ends[-1]
        if first.root != last.root:
            return "its operands are in different records"
        if first.offset is None or last.offset is None:
            return "its byte offset is unknown"
        start, end = first.offset, last.offset + last.length
        if end <= start:
            return "its THRU operand precedes its first operand"
        leaves = [
            leaf.qname
            for leaf in self._leaves(first.root)
            if leaf.offset is not None
            and leaf.offset >= start
            and leaf.offset + leaf.length <= end
        ]
        if not leaves:
            return "no elementary field lies in its byte range"
        alias = _Item(
            qname=name,
            name=name,
            level=66,
            is_group=True,
            offset=start,
            length=end - start,
            parent=None,
            redefines_chain=[],
            root=first.root,
            children=leaves,
            raw=name,
        )
        self._items[name] = alias
        self._by_raw.setdefault(name, []).append(name)
        self._by_name.setdefault(name, []).append(name)
        return None

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

    def _ancestry(self, qname: str) -> list[_Item]:
        """*qname* and every group enclosing it, innermost first."""
        chain: list[_Item] = []
        node: _Item | None = self._items[qname]
        while node is not None:
            chain.append(node)
            node = self._items.get(node.parent) if node.parent else None
        return chain

    def _dims(self, qname: str) -> list[tuple[int, int]]:
        """``(stride, count)`` of every OCCURS level over *qname*, outermost
        first: the subscripts a reference to it takes."""
        return [
            (node.length, node.occurs)
            for node in reversed(self._ancestry(qname))
            if node.occurs is not None
        ]

    def _table(self, qname: str) -> str | None:
        """The innermost OCCURS item at or above *qname* (with more than one
        occurrence), or None."""
        for node in self._ancestry(qname):
            if node.occurs is not None and node.occurs > 1:
                return node.qname
        return None

    def _placements(self, qname: str) -> list[tuple[int, int]] | None:
        """Every ``(offset, length)`` the bytes of *qname* occupy, one per
        occurrence when it sits in a table; None when its offset is unknown
        (after an ``OCCURS ... DEPENDING ON``). Past ``_PLACEMENT_CAP``
        occurrences, one range spanning them all."""
        if qname in self._placements_cache:
            return self._placements_cache[qname]
        item = self._items[qname]
        out: list[tuple[int, int]] | None = None
        if item.offset is not None:
            offsets = [item.offset]
            end = item.offset + item.length
            wide = False
            for node in self._ancestry(qname):
                if node.occurs is None or node.occurs <= 1:
                    continue
                end += (node.occurs - 1) * node.length
                if wide or len(offsets) * node.occurs > _PLACEMENT_CAP:
                    wide = True
                    continue
                offsets = [
                    o + k * node.length for o in offsets for k in range(node.occurs)
                ]
            if wide:
                self._wide.add(qname)
                out = [(item.offset, end - item.offset)]
            else:
                out = sorted((o, item.length) for o in offsets)
        self._placements_cache[qname] = out
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
                if all(
                    qual in self._items[q].raw.split(".")[:-1] for qual in qualifiers
                )
            ]
            if narrowed:
                candidates = narrowed
        return list(candidates)

    def _occurrence(
        self, qname: str, subscripts: tuple[int, ...] | None
    ) -> tuple[int, ...] | None:
        """*subscripts* when they address one occurrence of *qname* (one per
        OCCURS level, each within its bounds), else None."""
        if subscripts is None:
            return None
        dims = self._dims(qname)
        if len(dims) != len(subscripts) or not dims:
            return None
        if any(
            s < 1 or s > count
            for s, (_stride, count) in zip(subscripts, dims, strict=True)
        ):
            return None
        return subscripts

    def _refs(self, value: Any, role: str) -> list[_Ref]:
        """The operands one value (operand text or expression) reads or
        writes in *role*. Subscripts, reference-modifier offsets/lengths and
        qualifiers locate the operand: they are never its value."""
        if value is None:
            return []
        out: list[_Ref] = []
        if isinstance(value, CobolExpression):
            for leaf in _expression_leaves(value):
                for ref in self._refs(leaf, role):
                    if ref not in out:
                        out.append(ref)
            return out
        if not isinstance(value, str):
            names = [
                name
                for name, resolved, _exact in self._xref._names_for(value, role)
                if resolved == role
            ]
            single: re.Match[str] | None = None
        else:
            if is_quoted_literal(value):
                return []
            base, _refmod, _subscripts, exact = _split_operand(value)
            if exact:
                names = sorted(base - _qualifier_names(value))
            else:
                # An intrinsic FUNCTION: its arguments, best-effort.
                names = sorted(base)
            single = _SINGLE_REF_RE.match(value)
        window = self._refmod(value) if single else None
        loose = False
        if single and window is None and isinstance(value, str):
            variable = _ANY_REFMOD_RE.search(value)
            if variable:
                loose = True
                length = variable.group(2)
                window = (0, int(length)) if length.isdigit() else None
                shown = re.sub(r"\s*([():])\s*", r"\1", " ".join(value.split()))
                self._caveat(
                    f"{shown}: reference modifier with a "
                    "non-literal start or length; mapped inexactly to every "
                    "field it can reach"
                )
        subscripts = _constant_subscripts(value) if single else None
        for name in names:
            for qname in self._resolve(name):
                ref = _Ref(qname, window, self._occurrence(qname, subscripts), loose)
                if ref not in out:
                    out.append(ref)
        return out

    def _operand(self, value: Any, role: str) -> list[str]:
        """Qualified names of the operands :meth:`_refs` finds."""
        out: list[str] = []
        for ref in self._refs(value, role):
            if ref.qname not in out:
                out.append(ref.qname)
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

    def _occ_node(self, qname: str, subscripts: tuple[int, ...]) -> LineageNode | None:
        """The node of one literal-subscript occurrence of elementary
        *qname*, joined both ways to the table field as a whole (inexact
        ``occurrence`` edges: an unknown subscript may be this one)."""
        item = self._items[qname]
        if item.offset is None:
            return None
        offset = item.offset + sum(
            (s - 1) * stride
            for s, (stride, _n) in zip(subscripts, self._dims(qname), strict=True)
        )
        name = f"{qname}({','.join(str(s) for s in subscripts)})"
        nodes = self._occ_nodes.setdefault(qname, {})
        node = nodes.get(name)
        if node is None:
            node = LineageNode(ITEM, name, offset, item.length)
            nodes[name] = node
            generic = self._item_node(qname)
            self._edge(node, generic, "occurrence", _NO_CONTEXT, "OCCURS", False)
            self._edge(generic, node, "occurrence", _NO_CONTEXT, "OCCURS", False)
        return node

    def _ref_base(self, ref: _Ref) -> int | None:
        """Where the operand's bytes start, record-relative."""
        item = self._items[ref.qname]
        if item.offset is None:
            return None
        base = item.offset
        if ref.subscripts is not None:
            dims = self._dims(ref.qname)
            base += sum(
                (s - 1) * stride
                for s, (stride, _n) in zip(ref.subscripts, dims, strict=True)
            )
        return base

    def _pieces(self, ref: _Ref) -> list[_Piece] | None:
        """Elementary fields inside the operand, relative to its start;
        None when its offset is unknown. A reference modifier with a
        non-literal start makes every piece inexact (#527)."""
        item = self._items[ref.qname]
        if not item.children:
            if ref.subscripts is not None:
                node = self._occ_node(ref.qname, ref.subscripts)
                if node is not None:
                    return [_Piece(node, 0, item.length, not ref.loose_window)]
            exact = self._table(ref.qname) is None and not ref.loose_window
            return [_Piece(self._item_node(ref.qname), 0, item.length, exact)]
        base = self._ref_base(ref)
        if base is None:
            return None
        end = base + item.length
        out: list[_Piece] = []
        for leaf in self._leaves(ref.qname):
            placements = self._placements(leaf.qname)
            if placements is None:
                continue
            node = self._item_node(leaf.qname)
            exact = self._table(leaf.qname) is None and not ref.loose_window
            for offset, length in placements:
                if offset + length > base and offset < end:
                    out.append(_Piece(node, offset - base, length, exact))
        return out

    # -- files -------------------------------------------------------------

    def _index_files(self, ast: CobolProgram) -> None:
        inner = _contained_node_ids(ast)
        for group in same_record_area_groups(ast):
            for member in group:
                self._record_area[member] = group[0]
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
        existing = self._edges.get(key)
        if existing is not None:
            if existing.exact and not exact:
                self._edges[key] = replace(existing, exact=False)
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

    @staticmethod
    def _as_ref(value: str | _Ref) -> _Ref:
        return value if isinstance(value, _Ref) else _Ref(value)

    def _overlay(
        self,
        source: str | _Ref,
        target: str | _Ref,
        kind: str,
        ctx: _Context,
        statement: str,
    ) -> None:
        """Edges for a byte-for-byte transfer from *source* to *target*.

        Two elementary items: one edge (a numeric MOVE aligns by decimal
        point, not by byte). Anything involving a group: one edge per pair
        of elementary fields whose byte ranges, measured from the start of
        each operand, overlap -- every occurrence of a table field counted
        at its own bytes, the edge inexact (the node stands for any
        occurrence).
        """
        src_ref, tgt_ref = self._as_ref(source), self._as_ref(target)
        src, tgt = self._items[src_ref.qname], self._items[tgt_ref.qname]
        sources = self._pieces(src_ref)
        targets = self._pieces(tgt_ref)
        loose = src_ref.loose_window or tgt_ref.loose_window
        if not src.children and not tgt.children and sources and targets:
            s, t = sources[0], targets[0]
            exact = s.exact and t.exact and not loose
            self._edge(s.node, t.node, kind, ctx, statement, exact)
            return
        if sources is None or targets is None:
            for s_leaf in self._leaves(src_ref.qname):
                for t_leaf in self._leaves(tgt_ref.qname):
                    self._edge(
                        self._item_node(s_leaf.qname),
                        self._item_node(t_leaf.qname),
                        kind,
                        ctx,
                        statement,
                        exact=False,
                    )
            return
        s_start, s_len = 0, src.length
        t_start, t_len = 0, tgt.length
        if src_ref.window is not None:
            s_start = src_ref.window[0]
            s_len = src_ref.window[1] or max(s_len - s_start, 0)
        if tgt_ref.window is not None:
            t_start = tgt_ref.window[0]
            t_len = tgt_ref.window[1] or max(t_len - t_start, 0)
        span = min(s_len, t_len)
        if loose:
            # A side whose window may start anywhere can reach every field
            # under it; how it lines up with the other side is unknown, so
            # every pair is an inexact edge (#527).
            s_reach = (
                sources
                if src_ref.loose_window
                else [
                    p
                    for p in sources
                    if p.rel + p.length > s_start and p.rel < s_start + span
                ]
            )
            t_reach = (
                targets
                if tgt_ref.loose_window
                else [
                    p
                    for p in targets
                    if p.rel + p.length > t_start and p.rel < t_start + span
                ]
            )
            for s in s_reach:
                for t in t_reach:
                    self._edge(s.node, t.node, kind, ctx, statement, False)
            return
        # Both sides relative to the start of the bytes actually moved.
        moved_s = [
            replace(p, rel=p.rel - s_start)
            for p in sources
            if p.rel + p.length > s_start and p.rel < s_start + span
        ]
        moved_t = sorted(
            (
                replace(p, rel=p.rel - t_start)
                for p in targets
                if p.rel + p.length > t_start and p.rel < t_start + span
            ),
            key=lambda p: p.rel,
        )
        starts = [p.rel for p in moved_t]
        longest = max((p.length for p in moved_t), default=0)
        for s in moved_s:
            low = bisect_left(starts, s.rel - longest + 1)
            for t in moved_t[low:]:
                if t.rel >= s.rel + s.length:
                    break
                if s.rel < t.rel + t.length:
                    exact = (
                        s.exact and t.exact and s.rel == t.rel and s.length == t.length
                    )
                    self._edge(s.node, t.node, kind, ctx, statement, exact)

    def _to_port(
        self,
        operand: str | _Ref,
        port: Port,
        kind: str,
        ctx: _Context,
        statement: str,
        *,
        into_program: bool,
        out_of_program: bool,
    ) -> None:
        """Connect every elementary field of *operand* to its byte range on
        *port*, measured from the start of *operand*. A table field reaches
        the bytes of every occurrence (inexact); an occurrence the program
        names with literal subscripts gets its own exact edge
        (:meth:`_link_occurrences`)."""
        ref = self._as_ref(operand)
        if into_program:
            port.directions.add("in")
        if out_of_program:
            port.directions.add("out")

        def connect(node: LineageNode, pnode: LineageNode, exact: bool) -> None:
            if out_of_program:
                self._edge(node, pnode, kind, ctx, statement, exact)
            if into_program:
                self._edge(pnode, node, kind, ctx, statement, exact)

        pieces = self._pieces(ref)
        item = self._items[ref.qname]
        if pieces is None or item.children:
            # A field whose offset moves with an OCCURS DEPENDING ON table
            # before it has no byte range of its own on the port.
            for leaf in self._leaves(ref.qname):
                if pieces is None or self._placements(leaf.qname) is None:
                    node = LineageNode(port.kind, port.key, None, leaf.length)
                    connect(self._item_node(leaf.qname), node, True)
        if not pieces:
            return
        base = self._ref_base(ref)
        linked: set[str] = set()
        for piece in pieces:
            pnode = LineageNode(port.kind, port.key, piece.rel, piece.length)
            connect(piece.node, pnode, piece.exact)
            if (
                not piece.exact
                and item.children
                and base is not None
                and piece.node.name not in linked
            ):
                linked.add(piece.node.name)
                self._port_links.append(
                    _PortLink(
                        leaf=piece.node.name,
                        kind=port.kind,
                        key=port.key,
                        base=base,
                        extent=item.length,
                        edge_kind=kind,
                        statement=statement,
                        into_program=into_program,
                        out_of_program=out_of_program,
                        context=ctx,
                    )
                )

    def _link_occurrences(self) -> None:
        """Exact port edges for literal-subscript occurrences of table fields
        that reach a port as part of their record or group."""
        for link in self._port_links:
            ctx = link.context
            for node in self._occ_nodes.get(link.leaf, {}).values():
                if node.offset is None or not (
                    link.base <= node.offset < link.base + link.extent
                ):
                    continue
                pnode = LineageNode(
                    link.kind, link.key, node.offset - link.base, node.length
                )
                if link.out_of_program:
                    self._edge(node, pnode, link.edge_kind, ctx, link.statement)
                if link.into_program:
                    self._edge(pnode, node, link.edge_kind, ctx, link.statement)

    def _redefines_edges(self) -> None:
        """Two-way edges between elementary fields that share bytes:
        ``REDEFINES``, the 01 records of one FD (one buffer), and the
        records of every file one ``SAME RECORD AREA`` clause names (one
        area, across FDs)."""
        buffers: dict[str, list[str]] = {}
        for item in self._items.values():
            # A RENAMES alias is a view of bytes its record already holds.
            if item.parent is None and item.level != 66:
                anchor = item.qname
                if item.redefines_chain:
                    raw = item.redefines_chain[-1].upper()
                    anchor = (self._by_raw.get(raw) or [raw])[0]
                file_name = self._record_file.get(item.qname) or self._record_file.get(
                    anchor
                )
                if file_name:
                    file_name = self._record_area.get(file_name, file_name)
                key = f"FD:{file_name}" if file_name else anchor
                buffers.setdefault(key, []).append(item.qname)
        for roots in buffers.values():
            pieces: list[tuple[int, int, _Item]] = []
            for root in roots:
                for leaf in self._leaves(root):
                    for offset, length in self._placements(leaf.qname) or []:
                        if length:
                            pieces.append((offset, length, leaf))
            pieces.sort(key=lambda p: (p[0], p[2].qname))
            for i, (a_off, a_len, a) in enumerate(pieces):
                for b_off, b_len, b in pieces[i + 1 :]:
                    if b_off >= a_off + a_len:
                        break
                    if a.qname == b.qname:
                        continue
                    a_table, b_table = self._table(a.qname), self._table(b.qname)
                    if (
                        (a.qname in self._wide or b.qname in self._wide)
                        and a_table is not None
                        and a_table == b_table
                    ):
                        continue  # two fields of one table, spanned as a whole
                    exact = (
                        a_off == b_off
                        and a_len == b_len
                        and a_table is None
                        and b_table is None
                    )
                    na, nb = self._item_node(a.qname), self._item_node(b.qname)
                    self._edge(na, nb, "redefines", _NO_CONTEXT, "REDEFINES", exact)
                    self._edge(nb, na, "redefines", _NO_CONTEXT, "REDEFINES", exact)

    def _linkage_edges(self, ast: CobolProgram) -> None:
        from .program_signature import ProgramSignatureExtractor

        signature = ProgramSignatureExtractor().analyze(ast)
        for entry in signature.entry_points:
            name = (entry.name or self._program_id).upper().strip("'\"")
            # The USING line itself, so a linkage step cites it, not line 1.
            ctx = _Context(None, False, entry.location or ast.location)
            verb = (
                "PROCEDURE DIVISION" if entry.kind == "procedure-division" else "ENTRY"
            )
            for position, parameter in enumerate(entry.parameters, start=1):
                for qname in self._resolve(parameter.name):
                    port = self._port(PORT_LINKAGE, f"{name}#{position}")
                    port.detail.update({"entry": name, "position": position})
                    self._to_port(
                        qname,
                        port,
                        "linkage",
                        ctx,
                        f"{verb} USING",
                        into_program=True,
                        out_of_program=True,
                    )
            if entry.returning:
                # The value handed back to ``CALL ... RETURNING``.
                for qname in self._resolve(entry.returning):
                    port = self._port(PORT_LINKAGE, f"{name}#RETURNING")
                    port.detail.update({"entry": name, "position": "RETURNING"})
                    self._to_port(
                        qname,
                        port,
                        "linkage",
                        ctx,
                        f"{verb} RETURNING",
                        into_program=False,
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
        elif isinstance(stmt, ArithmeticStatement) and stmt.is_corresponding:
            self._visit_arith_corresponding(stmt, ctx)
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
                for src in self._refs(stmt.from_source, ROLE_READ):
                    for rec in self._refs(stmt.record_name, ROLE_READ):
                        self._overlay(src, rec, "move", ctx, "RELEASE FROM")
        elif isinstance(stmt, ReturnStatement):
            if stmt.file_name and stmt.into_target:
                for record in self._file_records.get(stmt.file_name.upper(), []):
                    for into in self._refs(stmt.into_target, ROLE_WRITE):
                        self._overlay(record, into, "move", ctx, "RETURN INTO")
        elif isinstance(stmt, (SortStatement, MergeStatement)):
            self._visit_sort(stmt, ctx)
        elif isinstance(stmt, IOAcceptStatement):
            self._visit_accept(stmt, ctx)
        elif isinstance(stmt, DisplayStatement):
            port = self._port(PORT_CONSOLE, "SYSOUT")
            for item in stmt.display_items:
                for src in self._refs(item, ROLE_READ):
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
        reads: list[_Ref] = []
        writes: list[_Ref] = []
        for value, role, _exact in self._xref._role_assignments(stmt):
            if role == ROLE_READ:
                reads += [r for r in self._refs(value, ROLE_READ) if r not in reads]
            elif role == ROLE_WRITE:
                writes += [r for r in self._refs(value, ROLE_WRITE) if r not in writes]
        statement = stmt.statement_type or type(stmt).__name__
        self_only = self._self_feeding(stmt, reads, writes)
        for src in reads:
            for s in self._pieces(src) or self._loose_pieces(src):
                for tgt in writes:
                    if src.qname in self_only and src.qname != tgt.qname:
                        continue
                    for t in self._pieces(tgt) or self._loose_pieces(tgt):
                        self._edge(
                            s.node, t.node, kind, ctx, statement, s.exact and t.exact
                        )

    def _self_feeding(
        self, stmt: CobolStatement, reads: list[_Ref], writes: list[_Ref]
    ) -> set[str]:
        """Receivers that only accumulate into themselves (#535):
        ``ADD 1 TO A B`` is ``A = A + 1; B = B + 1``, so A feeds nothing
        else the statement writes. The same holds for SUBTRACT / MULTIPLY /
        DIVIDE without GIVING, INSPECT TALLYING counters and a STRING /
        UNSTRING POINTER or TALLYING IN item. COMPUTE (``COMPUTE A B = A +
        1`` does feed B) and a GIVING form keep every edge; a receiver that
        is also a sending operand (``ADD A TO A B``) feeds the others too."""
        if isinstance(stmt, ComputeStatement):
            return set()
        if isinstance(stmt, ArithmeticStatement):
            if stmt.givings or stmt.giving:
                return set()
            receivers = [*stmt.targets, *([stmt.target] if stmt.target else [])]
            out = {r.qname for text in receivers for r in self._refs(text, ROLE_WRITE)}
            for text in stmt.source_operands or []:
                out -= {r.qname for r in self._refs(text, ROLE_READ)}
            return out
        if isinstance(stmt, (StringStatement, UnstringStatement, InspectStatement)):
            out = {r.qname for r in reads} & {w.qname for w in writes}
            if isinstance(stmt, InspectStatement) and stmt.target:
                # The inspected item is the sending operand, even when
                # REPLACING also writes it.
                out -= {r.qname for r in self._refs(stmt.target, ROLE_READ)}
            return out
        return set()

    def _loose_pieces(self, ref: _Ref) -> list[_Piece]:
        """Every elementary field of an operand whose offset is unknown."""
        return [
            _Piece(self._item_node(leaf.qname), 0, leaf.length, False)
            for leaf in self._leaves(ref.qname)
        ]

    def _visit_move(self, stmt: MoveStatement, ctx: _Context) -> None:
        if not stmt.source:
            return
        sources = self._refs(stmt.source, ROLE_READ)
        if not sources:
            return
        for target_text in stmt.targets:
            for tgt in self._refs(target_text, ROLE_WRITE):
                for src in sources:
                    if stmt.is_corresponding:
                        self._corresponding(src.qname, tgt.qname, ctx)
                    else:
                        self._overlay(src, tgt, "move", ctx, "MOVE")

    def _visit_arith_corresponding(
        self, stmt: ArithmeticStatement, ctx: _Context
    ) -> None:
        """``ADD``/``SUBTRACT CORRESPONDING A TO/FROM B``: each numeric
        elementary item of A adds into the one of the same name path in B,
        and nothing else flows (B's own value feeds itself, no edge)."""
        targets = [*stmt.targets, *([stmt.target] if stmt.target else [])]
        if stmt.source_operands is not None:
            sources = list(stmt.source_operands)
        else:
            consumed = {t.upper() for t in targets}
            sources = [op for op in stmt.operands if op.upper() not in consumed]
        verb = f"{stmt.statement_type or type(stmt).__name__} CORRESPONDING"
        seen: set[tuple[str, str]] = set()
        for target_text in targets:
            for tgt in self._refs(target_text, ROLE_WRITE):
                for source_text in sources:
                    for src in self._refs(source_text, ROLE_READ):
                        if (src.qname, tgt.qname) in seen:
                            continue
                        seen.add((src.qname, tgt.qname))
                        self._corresponding(
                            src.qname, tgt.qname, ctx, arith=True, statement=verb
                        )

    def _corresponding(
        self,
        source: str,
        target: str,
        ctx: _Context,
        arith: bool = False,
        statement: str = "MOVE CORRESPONDING",
    ) -> None:
        """``MOVE CORRESPONDING``: subordinates with the same name path below
        the two groups pair up when at least one of the two is elementary
        (two groups of one name are not a pair; their own subordinates may
        be). FILLER, REDEFINES and OCCURS items, and what is under them, do
        not take part.

        With *arith* (``ADD``/``SUBTRACT CORRESPONDING``) only elementary
        pairs count, the sending item numeric and the receiving one numeric
        or numeric-edited, and each pair is one ``arith`` edge."""

        def paths(root: str) -> dict[tuple[str, ...], str]:
            base = len(self._items[root].raw.split("."))
            out: dict[tuple[str, ...], str] = {}
            pending = list(self._items[root].children)
            while pending:
                qname = pending.pop()
                item = self._items[qname]
                if (
                    item.name in ("", "FILLER")
                    or item.redefines_chain
                    or item.occurs is not None
                ):
                    continue
                out.setdefault(tuple(item.raw.split(".")[base:]), qname)
                pending.extend(item.children)
            return out

        target_paths = paths(target)
        for rel, s in sorted(paths(source).items()):
            t = target_paths.get(rel)
            if t is None:
                continue
            if arith:
                s_item, t_item = self._items[s], self._items[t]
                if s_item.children or t_item.children:
                    continue
                if s_item.category != "numeric" or not t_item.category:
                    continue
                self._edge(
                    self._item_node(s), self._item_node(t), "arith", ctx, statement
                )
                continue
            if self._items[s].children and self._items[t].children:
                continue
            self._overlay(s, t, "move", ctx, statement)

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
                for tgt in self._refs(stmt.into_target, ROLE_WRITE):
                    self._overlay(record, tgt, "move", ctx, "READ INTO")
        self._key_use(file_name, stmt.key_name, ctx, "READ KEY")

    def _visit_write(self, stmt: Any, ctx: _Context) -> None:
        if not stmt.record_name:
            return
        verb = "REWRITE" if isinstance(stmt, IORewriteStatement) else "WRITE"
        for record in self._operand(stmt.record_name, ROLE_READ):
            if stmt.from_clause:
                for src in self._refs(stmt.from_clause, ROLE_READ):
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

    def _visit_accept(self, stmt: IOAcceptStatement, ctx: _Context) -> None:
        source = (stmt.from_source or "SYSIN").upper()
        words = source.split()
        if words and words[0] in _CLOCK_ACCEPT_SOURCES:
            return  # the runtime's clock, not data entering the program
        port = self._port(PORT_CONSOLE, source)
        for tgt in self._refs(stmt.target, ROLE_WRITE):
            self._to_port(
                tgt,
                port,
                "accept",
                ctx,
                "ACCEPT",
                into_program=True,
                out_of_program=False,
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
            values = callee_names(getattr(stmt, "possible_values", None) or [])
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
                if not parameter.name or is_quoted_literal(parameter.name):
                    continue
                mode = (parameter.passing_mode or "REFERENCE").upper()
                by_reference = mode not in ("CONTENT", "VALUE")
                port = self._port(PORT_CALL, f"{callee}#{position}")
                port.detail.update(
                    {"callee": callee, "position": position, "dynamic": stmt.is_dynamic}
                )
                # The same operand path a MOVE takes: subscripts, reference
                # modification and qualifiers locate the argument.
                for ref in self._refs(parameter.name, ROLE_READ):
                    self._to_port(
                        ref,
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
                for ref in self._refs(value, ROLE_WRITE):
                    self._to_port(
                        ref,
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
        starts = sorted(
            {e.source for e in edges if e.source.is_port}, key=LineageNode.sort_key
        )
        # State is (node, overlay class of the edge it arrived over). Two
        # alias edges of one class in a row are never followed (see
        # ``overlay_class``): two redefines would carry a value from one
        # field of a record to an unrelated one through the alias covering
        # both, two occurrence edges one occurrence into another.
        State = tuple[LineageNode, int]
        for start in starts:
            parent: dict[State, tuple[State, LineageEdge]] = {}
            first: State = (start, 0)
            queue: deque[State] = deque([first])
            seen = {first}
            while queue:
                state = queue.popleft()
                node, arrived = state
                for edge in out_edges.get(node, []):
                    overlay = overlay_class(edge.kind)
                    if overlay and overlay == arrived:
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
        return sorted(
            flows.values(), key=lambda f: (f.source.sort_key(), f.target.sort_key())
        )
