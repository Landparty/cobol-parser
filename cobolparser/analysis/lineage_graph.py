"""Field lineage across programs (layer 2): join per-program flow reports
through datasets, CALLs and DB2 tables, and answer "what does this field
feed" / "where does this field's value come from".

Input is one ``FieldFlowReport`` per program (``field_lineage.py``), as an
object or as its ``to_dict()`` form -- the form the LegacyLens backend
stores -- plus, for files, which dataset each program's DD names are bound
to. Bindings come from whatever parsed the JCL (jcl-parser, or the
backend's ``COBOL_DATASET_READS/WRITES`` rows); this module has no JCL
reader of its own and depends on none.

Joins:

- **datasets**: a writer's output-port field and a reader's input-port field
  on the same dataset meet on overlapping byte ranges (``exact`` when the
  ranges coincide, ``overlap`` otherwise). GDG relative references
  (``(0)``, ``(+1)``) and absolute generations (``.G0001V00``) normalise to
  the base name; ``&&`` temporaries only join within their own job.
  ``Passthrough``s describe utility steps (IEBGENER, IDCAMS REPRO, DFSORT
  without reformatting) that carry bytes from one dataset to another.
- **CALL**: argument *n* of a caller meets parameter *n* of the callee's
  ``PROCEDURE DIVISION USING``, on byte ranges within the argument. A
  callee with no report (not in the scan, or not COBOL) is *opaque*: every
  value passed to it is assumed to reach every value it hands back, marked
  ``confidence="opaque"``.
- **DB2**: a program writing ``TABLE.COLUMN`` meets every program reading it.

Example:
    ```python
    graph = LineageGraph(reports, bindings=[DatasetBinding("FEECALC", "TRANIN",
                                                           "BANK.PROD.TRAN.DAILY")])
    result = graph.impact("HV-TRAN-AMOUNT", program="CHKCLR")
    for hit in result.hits:
        print(hit.program, hit.field, [h.label for h in hit.path])
    ```
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .field_lineage import (
    ITEM,
    PORT_CALL,
    PORT_FILE,
    PORT_LINKAGE,
    PORT_SQL,
    VALUE_CHANGING_KINDS,
    FieldFlowReport,
    normalize_ddname,
)

#: System interfaces a CALL reaches that are neither a business program
#: nor a value transformer: MQ, IMS DL/I, LE callable services, DB2 attach.
#: Values sent to them leave (a queue, a database segment); values they hand
#: back come from outside. Never treated as an opaque pass-through.
_INTERFACE_RE = re.compile(
    r"^(MQ[A-Z]+|CBLTDLI|AIBTDLI|CEETDLI|AERTDLI|ASMTDLI|PLITDLI|CTDLI"
    r"|CEE[A-Z0-9]+|DSNTIAR|DSNTIAC|DSNALI|DSNHLI|DSNRLI|ILBO[A-Z0-9]*|IGZ[A-Z0-9]*)$"
)

_GDG_RELATIVE_RE = re.compile(r"\(\s*[+-]?\d+\s*\)$")
_GDG_ABSOLUTE_RE = re.compile(r"\.G\d{4}V\d{2}$")

# Node keys. Program-scoped: ("P", program, kind, name, offset, length).
# Shared: ("D", dataset, offset, length) and ("T", "TABLE.COLUMN").
NodeKey = tuple[Any, ...]
_State = tuple[NodeKey, bool]


def normalize_dataset(name: str, job: str | None = None) -> str:
    """The identity a dataset name joins on."""
    text = name.strip().strip("'\"").upper()
    text = _GDG_RELATIVE_RE.sub("", text)
    text = _GDG_ABSOLUTE_RE.sub("", text)
    if text.startswith("&&") or text.startswith("&") and not text.startswith("&&"):
        return f"{(job or '?').upper()}/{text}"
    return text


@dataclass(frozen=True)
class DatasetBinding:
    """One program's DD name bound to a dataset by a job step."""

    program: str
    ddname: str
    dataset: str
    job: str | None = None
    step: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetBinding:
        return cls(
            program=str(data["program"]),
            ddname=str(data["ddname"]),
            dataset=str(data["dataset"]),
            job=data.get("job"),
            step=data.get("step"),
        )


@dataclass(frozen=True)
class Passthrough:
    """A utility step that copies records from one dataset to another.

    ``kind="copy"`` keeps every byte where it was (IEBGENER, IDCAMS REPRO,
    a DFSORT that only sorts or filters). ``aggregate_ranges`` are the
    0-based ``(offset, length)`` ranges a DFSORT ``SUM FIELDS`` rewrites in
    place; bytes there arrive with ``kind="aggregate"``. ``kind="reformat"``
    (INREC/OUTREC/BUILD) moves bytes in ways this module does not
    interpret: the flow stops there, with a caveat.
    """

    input: str
    output: str
    kind: str = "copy"
    aggregate_ranges: tuple[tuple[int, int], ...] = ()
    job: str | None = None
    step: str | None = None
    program: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Passthrough:
        return cls(
            input=str(data["input"]),
            output=str(data["output"]),
            kind=str(data.get("kind") or "copy"),
            aggregate_ranges=tuple(
                (int(r[0]), int(r[1])) for r in data.get("aggregate_ranges") or []
            ),
            job=data.get("job"),
            step=data.get("step"),
            program=data.get("program"),
        )


@dataclass(frozen=True)
class _EdgeInfo:
    kind: str
    line: int = 0
    statement: str = ""
    confidence: str = "exact"
    cross: bool = False
    guarded: bool = False


@dataclass(frozen=True)
class Hop:
    """One step of an impact path."""

    program: str | None
    node: str
    kind: str
    line: int
    statement: str
    confidence: str

    @property
    def label(self) -> str:
        return f"{self.program}:{self.node}" if self.program else self.node

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "node": self.node,
            "kind": self.kind,
            "line": self.line,
            "statement": self.statement,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ImpactHit:
    """A field (or table column, or dataset range) the start field reaches."""

    program: str | None
    field: str
    node_kind: str
    path: tuple[Hop, ...]

    @property
    def derived(self) -> bool:
        return any(hop.kind in VALUE_CHANGING_KINDS for hop in self.path)

    @property
    def confidence(self) -> str:
        order = ["exact", "overlap", "candidate", "opaque"]
        worst = 0
        for hop in self.path:
            if hop.confidence in order:
                worst = max(worst, order.index(hop.confidence))
        return order[worst]

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "field": self.field,
            "node_kind": self.node_kind,
            "derived": self.derived,
            "confidence": self.confidence,
            "path": [hop.to_dict() for hop in self.path],
        }


@dataclass
class ImpactResult:
    start: list[str]
    direction: str
    depth: int | None
    hits: list[ImpactHit] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def programs(self) -> list[str]:
        return sorted({h.program for h in self.hits if h.program})

    @property
    def tables(self) -> list[str]:
        return sorted({h.field for h in self.hits if h.node_kind == "table"})

    @property
    def datasets(self) -> list[str]:
        return sorted(
            {h.field.split("@")[0] for h in self.hits if h.node_kind == "dataset"}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "direction": self.direction,
            "depth": self.depth,
            "programs": self.programs,
            "tables": self.tables,
            "datasets": self.datasets,
            "hits": [h.to_dict() for h in self.hits],
            "caveats": list(self.caveats),
        }

    def to_text(self) -> str:
        arrow = "feeds" if self.direction == "forward" else "is fed by"
        head = ", ".join(self.start) or "<nothing>"
        lines = [f"{head} {arrow}:", ""]
        if self.tables:
            lines.append("Tables: " + ", ".join(self.tables))
        if self.datasets:
            lines.append("Datasets: " + ", ".join(self.datasets))
        lines.append(f"Programs ({len(self.programs)}): " + ", ".join(self.programs))
        by_program: dict[str, list[ImpactHit]] = {}
        for hit in self.hits:
            if hit.node_kind == "item" and hit.program:
                by_program.setdefault(hit.program, []).append(hit)
        for program in sorted(by_program):
            lines.append("")
            lines.append(program)
            for hit in by_program[program]:
                last = hit.path[-1] if hit.path else None
                where = f" line {last.line}" if last and last.line else ""
                tags = [last.kind] if last else []
                if hit.derived:
                    tags.append("derived")
                if hit.confidence != "exact":
                    tags.append(hit.confidence)
                # Read from the hit back toward the start: "<-" (fed by)
                # going forward, "->" (feeds) going backward.
                via = (" <- " if self.direction == "forward" else " -> ").join(
                    h.label for h in reversed(hit.path[:-1]) if h.kind != "redefines"
                )
                lines.append(
                    f"  {hit.field}{where}  [{', '.join(tags)}]"
                    + (f"\n      via {via}" if via else "")
                )
        if self.caveats:
            lines.append("")
            lines.append("Caveats:")
            lines += [f"  - {c}" for c in self.caveats]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class KeyRelationship:
    """Values of ``source`` are used to look up records/rows by ``key``:
    a candidate key relationship between two datasets or tables."""

    source: str
    key: str
    program: str
    item: str
    line: int
    statement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "key": self.key,
            "program": self.program,
            "item": self.item,
            "line": self.line,
            "statement": self.statement,
        }


def _overlaps(
    a: tuple[int | None, int | None], b: tuple[int | None, int | None]
) -> bool:
    (ao, al), (bo, bl) = a, b
    if ao is None or bo is None or al is None or bl is None:
        return True
    return ao < bo + bl and bo < ao + al


class LineageGraph:
    """The cross-program field-flow graph built from per-program reports."""

    def __init__(
        self,
        reports: Sequence[FieldFlowReport | dict[str, Any]],
        bindings: Sequence[DatasetBinding | dict[str, Any]] = (),
        passthroughs: Sequence[Passthrough | dict[str, Any]] = (),
    ) -> None:
        self.reports: dict[str, dict[str, Any]] = {}
        for report in reports:
            data = report.to_dict() if isinstance(report, FieldFlowReport) else report
            program = str(data.get("program_id") or "").upper()
            if program in self.reports:
                continue
            self.reports[program] = data
        self.bindings = [
            b if isinstance(b, DatasetBinding) else DatasetBinding.from_dict(b)
            for b in bindings
        ]
        self.passthroughs = [
            p if isinstance(p, Passthrough) else Passthrough.from_dict(p)
            for p in passthroughs
        ]
        self.caveats: list[str] = []
        self.unjoined: list[str] = []
        self.opaque_callees: list[str] = []
        self._out: dict[NodeKey, list[tuple[NodeKey, _EdgeInfo]]] = {}
        self._in: dict[NodeKey, list[tuple[NodeKey, _EdgeInfo]]] = {}
        self._build()

    # -- building ----------------------------------------------------------

    def _add(self, src: NodeKey, dst: NodeKey, info: _EdgeInfo) -> None:
        if src == dst:
            return
        self._out.setdefault(src, []).append((dst, info))
        self._in.setdefault(dst, []).append((src, info))

    @staticmethod
    def _pnode(program: str, node: dict[str, Any]) -> NodeKey:
        return (
            "P",
            program,
            node["kind"],
            node["name"],
            node.get("offset"),
            node.get("length"),
        )

    def _build(self) -> None:
        # Ports by role: written (an intra edge ends there: the value leaves
        # the program) and read (an intra edge starts there).
        written: dict[str, set[NodeKey]] = {}
        read: dict[str, set[NodeKey]] = {}
        for program, data in self.reports.items():
            for edge in data.get("edges") or []:
                src = self._pnode(program, edge["source"])
                dst = self._pnode(program, edge["target"])
                self._add(
                    src,
                    dst,
                    _EdgeInfo(
                        kind=edge.get("kind") or "",
                        line=int(
                            (edge.get("origin") or {}).get("line")
                            or edge.get("line")
                            or 0
                        ),
                        statement=edge.get("statement") or "",
                        confidence="exact" if edge.get("exact", True) else "overlap",
                        guarded=bool(edge.get("guarded")),
                    ),
                )
                if src[2] != ITEM:
                    read.setdefault(program, set()).add(src)
                if dst[2] != ITEM:
                    written.setdefault(program, set()).add(dst)
        # Sorted, so the joins add edges (and so report paths) in the same
        # order on every run: a set of tuples of str iterates in hash order.
        written_ports = {p: sorted(v, key=repr) for p, v in written.items()}
        read_ports = {p: sorted(v, key=repr) for p, v in read.items()}
        self._join_files(written_ports, read_ports)
        self._join_sql(written_ports, read_ports)
        self._join_calls(written_ports, read_ports)
        for caveat_source in self.reports.values():
            for caveat in caveat_source.get("caveats") or []:
                text = f"{caveat_source.get('program_id')}: {caveat}"
                if text not in self.caveats:
                    self.caveats.append(text)

    def _datasets_for(self, program: str, ddname: str) -> list[DatasetBinding]:
        dd = normalize_ddname(ddname)
        return [
            b
            for b in self.bindings
            if b.program.upper() == program and normalize_ddname(b.ddname) == dd
        ]

    def _join_files(
        self, written: dict[str, list[NodeKey]], read: dict[str, list[NodeKey]]
    ) -> None:
        ranges: dict[str, set[tuple[int | None, int | None]]] = {}
        readers: dict[str, list[NodeKey]] = {}
        unbound: set[str] = set()
        for program in self.reports:
            for role, nodes in (
                ("out", written.get(program, [])),
                ("in", read.get(program, [])),
            ):
                for node in sorted(nodes, key=repr):
                    if node[2] != PORT_FILE:
                        continue
                    bindings = self._datasets_for(program, node[3])
                    if not bindings:
                        unbound.add(f"{program}: DD {node[3]}")
                        continue
                    for binding in bindings:
                        dsn = normalize_dataset(binding.dataset, binding.job)
                        span = (node[4], node[5])
                        if role == "out":
                            ranges.setdefault(dsn, set()).add(span)
                            self._add(
                                node,
                                ("D", dsn, *span),
                                _EdgeInfo(
                                    "dataset", statement=f"DD {node[3]}", cross=True
                                ),
                            )
                        else:
                            readers.setdefault(dsn, []).append(node)
        # A dataset nothing in scope writes (an external feed) is still known
        # by the ranges its readers read, and those are what a utility step
        # has to carry: seed them too.
        for dsn, reader_nodes in readers.items():
            for node in reader_nodes:
                ranges.setdefault(dsn, set()).add((node[4], node[5]))
        # Utility steps carry every known range across, both ways, to a
        # fixpoint (a chain SORT -> IEBGENER -> ...): a range read downstream
        # must exist upstream for a reader there to reach it.
        stopped: set[str] = set()
        linked: set[tuple[str, str, tuple[int | None, int | None]]] = set()
        changed = True
        while changed:
            changed = False
            for pt in self.passthroughs:
                src = normalize_dataset(pt.input, pt.job)
                dst = normalize_dataset(pt.output, pt.job)
                if pt.kind == "reformat":
                    if src in ranges and dst not in stopped:
                        stopped.add(dst)
                        self.caveats.append(
                            f"{pt.step or pt.program or 'a utility step'} reformats "
                            f"{src} into {dst}; values are not traced through it"
                        )
                    continue
                spans = ranges.get(src, set()) | ranges.get(dst, set())
                for span in sorted(spans, key=repr):
                    if (src, dst, span) in linked:
                        continue
                    linked.add((src, dst, span))
                    for dsn in (src, dst):
                        if span not in ranges.setdefault(dsn, set()):
                            ranges[dsn].add(span)
                            changed = True
                    kind = "copy"
                    if any(_overlaps(span, r) for r in pt.aggregate_ranges):
                        kind = "aggregate"
                    self._add(
                        ("D", src, *span),
                        ("D", dst, *span),
                        _EdgeInfo(
                            kind,
                            statement=f"{pt.program or 'utility'} {pt.step or ''}".strip(),
                            cross=True,
                        ),
                    )
        for dsn, reader_nodes in readers.items():
            for node in reader_nodes:
                span = (node[4], node[5])
                self._add(
                    ("D", dsn, *span),
                    node,
                    _EdgeInfo("dataset", statement=f"DD {node[3]}", cross=True),
                )
                for other in sorted(ranges.get(dsn, set()), key=repr):
                    if other == span or not _overlaps(other, span):
                        continue
                    self._add(
                        ("D", dsn, *other),
                        node,
                        _EdgeInfo(
                            "dataset",
                            statement=f"DD {node[3]}",
                            confidence="overlap",
                            cross=True,
                        ),
                    )
        self.unjoined.extend(
            f"{u} is not bound to any dataset" for u in sorted(unbound)
        )

    def _join_sql(
        self, written: dict[str, list[NodeKey]], read: dict[str, list[NodeKey]]
    ) -> None:
        for program in self.reports:
            for node in written.get(program, []):
                if node[2] == PORT_SQL:
                    self._add(node, ("T", node[3]), _EdgeInfo("table", cross=True))
            for node in read.get(program, []):
                if node[2] == PORT_SQL:
                    self._add(("T", node[3]), node, _EdgeInfo("table", cross=True))

    def _join_calls(
        self, written: dict[str, list[NodeKey]], read: dict[str, list[NodeKey]]
    ) -> None:
        # Callee parameters by "ENTRY#n", over every report.
        params_in: dict[str, list[NodeKey]] = {}
        params_out: dict[str, list[NodeKey]] = {}
        for program in self.reports:
            for node in read.get(program, []):
                if node[2] == PORT_LINKAGE:
                    params_in.setdefault(node[3], []).append(node)
            for node in written.get(program, []):
                if node[2] == PORT_LINKAGE:
                    params_out.setdefault(node[3], []).append(node)
        known_entries = {key.split("#")[0] for key in (*params_in, *params_out)}
        known_entries |= set(self.reports)
        opaque: dict[tuple[str, str], tuple[list[NodeKey], list[NodeKey]]] = {}
        for program in self.reports:
            sent = [n for n in written.get(program, []) if n[2] == PORT_CALL]
            back = [n for n in read.get(program, []) if n[2] == PORT_CALL]
            # A BY REFERENCE argument is in both lists: sent and handed back.
            for index, nodes in ((0, sent), (1, back)):
                for node in nodes:
                    callee = node[3].split("#")[0]
                    if callee in known_entries or _INTERFACE_RE.match(callee):
                        continue
                    opaque.setdefault((program, callee), ([], []))[index].append(node)
            for node in sent:
                for param in params_in.get(node[3], []):
                    if _overlaps((node[4], node[5]), (param[4], param[5])):
                        exact = (node[4], node[5]) == (param[4], param[5])
                        self._add(
                            node,
                            param,
                            _EdgeInfo(
                                "call",
                                statement="CALL USING",
                                confidence="exact" if exact else "overlap",
                                cross=True,
                            ),
                        )
            for node in back:
                for param in params_out.get(node[3], []):
                    if _overlaps((node[4], node[5]), (param[4], param[5])):
                        exact = (node[4], node[5]) == (param[4], param[5])
                        self._add(
                            param,
                            node,
                            _EdgeInfo(
                                "call",
                                statement="CALL USING",
                                confidence="exact" if exact else "overlap",
                                cross=True,
                            ),
                        )
        for (_program, callee), (sent, back) in sorted(opaque.items()):
            if callee not in self.opaque_callees:
                self.opaque_callees.append(callee)
            for src in sent:
                for dst in back:
                    self._add(
                        src,
                        dst,
                        _EdgeInfo(
                            "opaque-call",
                            statement=f"CALL {callee}",
                            confidence="opaque",
                        ),
                    )
        if self.opaque_callees:
            self.caveats.append(
                "not in the scan (or not COBOL), so assumed to pass every input "
                "argument through to every output argument: "
                + ", ".join(sorted(self.opaque_callees))
            )

    # -- queries -----------------------------------------------------------

    def _items_named(self, field_name: str, program: str | None) -> list[NodeKey]:
        parts = [p.strip().upper() for p in field_name.split(" OF ") if p.strip()]
        if not parts:
            return []
        name, qualifiers = parts[0], parts[1:]
        programs = [program.upper()] if program else list(self.reports)
        starts: list[NodeKey] = []
        for prog in programs:
            data = self.reports.get(prog)
            if data is None:
                continue
            matched: list[str] = []
            for item in data.get("items") or []:
                qname = str(item["qualified_name"]).upper()
                segments = qname.split(".")
                if qname == name or segments[-1] == name:
                    if all(q in segments[:-1] for q in qualifiers):
                        matched.append(qname)
            for node in list(self._out) + list(self._in):
                if node[0] != "P" or node[1] != prog or node[2] != ITEM:
                    continue
                qname = node[3]
                if any(qname == m or qname.startswith(m + ".") for m in matched):
                    if node not in starts:
                        starts.append(node)
        return starts

    def impact(
        self,
        field_name: str,
        program: str | None = None,
        direction: str = "forward",
        depth: int | None = None,
    ) -> ImpactResult:
        """Everything *field_name* (in *program*, or in every program when
        None) feeds (``direction="forward"``) or is fed by (``"backward"``).

        ``depth`` caps the number of joins between programs (dataset, CALL,
        table) a path may cross; ``None`` follows every one.
        """
        starts = self._items_named(field_name, program)
        label = (
            f"{program.upper()}:{field_name.upper()}" if program else field_name.upper()
        )
        return self._trace(starts, [label], direction, depth)

    def impact_table(
        self, table_column: str, direction: str = "forward", depth: int | None = None
    ) -> ImpactResult:
        """``table_column`` may omit the schema (``TRANSACTION_HIST.AMOUNT``
        matches ``BANK.TRANSACTION_HIST.AMOUNT``) or give it."""
        wanted = table_column.upper()
        starts = sorted(
            {
                node
                for node in (*self._out, *self._in)
                if node[0] == "T"
                and (
                    node[1] == wanted
                    or ("." in wanted and node[1].endswith("." + wanted))
                )
            },
            key=repr,
        )
        return self._trace(starts, [wanted], direction, depth)

    def impact_dataset(
        self, dataset: str, direction: str = "forward", depth: int | None = None
    ) -> ImpactResult:
        dsn = normalize_dataset(dataset)
        starts = sorted(
            {
                node
                for node in (*self._out, *self._in)
                if node[0] == "D" and node[1] == dsn
            },
            key=repr,
        )
        return self._trace(starts, [dsn], direction, depth)

    @staticmethod
    def _describe(node: NodeKey) -> tuple[str | None, str, str]:
        """(program, field label, node kind) for a node key."""
        if node[0] == "T":
            return None, node[1], "table"
        if node[0] == "D":
            span = f"@{node[2]}+{node[3]}" if node[2] is not None else ""
            return None, f"{node[1]}{span}", "dataset"
        _, program, kind, name, offset, length = node
        if kind == ITEM:
            return program, name, "item"
        span = f"@{offset}+{length}" if offset is not None else ""
        return program, f"{kind}:{name}{span}", "port"

    def _trace(
        self,
        starts: list[NodeKey],
        label: list[str],
        direction: str,
        depth: int | None,
    ) -> ImpactResult:
        result = ImpactResult(start=label, direction=direction, depth=depth)
        if not starts:
            result.caveats.append(f"{', '.join(label)}: no such field in any report")
            return result
        adjacency = self._out if direction == "forward" else self._in
        # 0-1 BFS: stepping into a program from outside it (from a dataset or
        # table, or across a CALL) costs 1; every other step costs 0. So
        # ``depth=1`` reaches the programs one join away.
        # A state is (node, arrived over a redefines edge): as in a
        # program's own summary, two overlays in a row are never chained,
        # or one field of a record would reach every other field of it
        # through an alias covering the whole record.
        best: dict[_State, int] = {}
        parent: dict[_State, tuple[_State, _EdgeInfo]] = {}
        queue: deque[tuple[_State, int]] = deque()
        for start in starts:
            best[(start, False)] = 0
            queue.append(((start, False), 0))
        while queue:
            state, cost = queue.popleft()
            if cost > best.get(state, cost):
                continue
            node, via_overlay = state
            for nxt, info in adjacency.get(node, []):
                overlay = info.kind == "redefines"
                if overlay and via_overlay:
                    continue
                enters = nxt[0] == "P" and (node[0] != "P" or node[1] != nxt[1])
                step = cost + (1 if enters else 0)
                if depth is not None and step > depth:
                    continue
                nstate = (nxt, overlay)
                if nstate in best and best[nstate] <= step:
                    continue
                best[nstate] = step
                parent[nstate] = (state, info)
                if enters:
                    queue.append((nstate, step))
                else:
                    queue.appendleft((nstate, step))
        # One hit per node, over its cheapest state (a plain arrival wins a
        # tie: its path has no overlay hop to explain).
        chosen: dict[NodeKey, _State] = {}
        for state, _cost in sorted(best.items(), key=lambda kv: (kv[1], kv[0][1])):
            chosen.setdefault(state[0], state)
        start_set = set(starts)
        hits: list[ImpactHit] = []
        for node, state in chosen.items():
            if node in start_set:
                continue
            program, name, kind = self._describe(node)
            if kind == "port" and adjacency.get(node):
                # A port is only worth reporting where the trail ends at it:
                # a DD no JCL binds, a CALL to nothing, a console line.
                continue
            path: list[Hop] = []
            cursor = state
            while cursor[0] not in start_set or cursor[1]:
                prev, info = parent[cursor]
                p, n, _ = self._describe(cursor[0])
                path.append(
                    Hop(p, n, info.kind, info.line, info.statement, info.confidence)
                )
                cursor = prev
            path.reverse()
            hits.append(ImpactHit(program, name, kind, tuple(path)))
        hits.sort(
            key=lambda h: (
                h.node_kind != "table",
                h.node_kind != "dataset",
                h.program or "",
                h.field,
            )
        )
        result.hits = hits
        reached = {h.program for h in hits if h.program}
        reached |= {s[1] for s in starts if s[0] == "P"}
        opaque = sorted(
            {
                hop.statement.removeprefix("CALL ")
                for hit in hits
                for hop in hit.path
                if hop.kind == "opaque-call"
            }
        )
        if opaque:
            result.caveats.append(
                "assumed to pass every argument it receives through to every "
                "argument it hands back (not in the scan, or not COBOL): "
                + ", ".join(opaque)
            )
        for caveat in self.caveats:
            if caveat.startswith("not in the scan"):
                continue
            if any(caveat.startswith(f"{p}:") for p in reached):
                result.caveats.append(caveat)
            elif not any(caveat.startswith(f"{p}:") for p in self.reports):
                result.caveats.append(caveat)
        return result

    def key_relationships(self) -> list[KeyRelationship]:
        """Candidate key relationships: a value read from one dataset or
        table that is used, inside some program, to look up records or rows
        in another (``READ ... KEY``, ``RECORD KEY``, ``WHERE col = :hv``).

        This is the inference half of the test-data plan's dataset key
        relationships; every candidate names the program and line that is
        its evidence.
        """
        out: list[KeyRelationship] = []
        seen: set[tuple[str, str, str, str]] = set()
        for program, data in self.reports.items():
            # A use with a statement line first: of two pieces of evidence
            # for one candidate, READ ... KEY beats SELECT ... RECORD KEY.
            uses = sorted(
                data.get("key_uses") or [],
                key=lambda u: (not u.get("line"), u.get("line") or 0),
            )
            for use in uses:
                key_port = self._pnode(program, use["port"])
                key_labels = self._shared_labels(key_port)
                item = str(use["item"]).upper()
                starts = [
                    n
                    for n in (*self._out, *self._in)
                    if n[0] == "P"
                    and n[1] == program
                    and n[2] == ITEM
                    and (n[3] == item or n[3].startswith(item + "."))
                ]
                sources = self._local_sources(starts)
                for src in sources:
                    for src_label in self._shared_labels(src, incoming=True):
                        for key_label in key_labels:
                            if src_label == key_label:
                                continue
                            # One candidate per dataset, not per byte range:
                            # overlapping records of one file are one source.
                            sig = (src_label.split("@")[0], key_label, program, item)
                            if sig in seen:
                                continue
                            seen.add(sig)
                            out.append(
                                KeyRelationship(
                                    source=src_label,
                                    key=key_label,
                                    program=program,
                                    item=item,
                                    line=int(use.get("line") or 0),
                                    statement=use.get("statement") or "",
                                )
                            )
        return sorted(out, key=lambda k: (k.key, k.source, k.program))

    def _local_sources(self, starts: list[NodeKey]) -> list[NodeKey]:
        """Input-port nodes of the same program whose values reach *starts*."""
        found: list[NodeKey] = []
        seen = set(starts)
        queue = deque(starts)
        while queue:
            node = queue.popleft()
            for prev, info in self._in.get(node, []):
                if info.cross or prev in seen or prev[0] != "P":
                    continue
                seen.add(prev)
                if prev[2] != ITEM:
                    found.append(prev)
                    continue
                queue.append(prev)
        return found

    def _shared_labels(self, port: NodeKey, incoming: bool = False) -> list[str]:
        """The dataset/table a program port is joined to."""
        if port[2] == PORT_SQL:
            return [port[3]]
        labels: list[str] = []
        if port[2] == PORT_FILE:
            for binding in self._datasets_for(port[1], port[3]):
                dsn = normalize_dataset(binding.dataset, binding.job)
                span = f"@{port[4]}+{port[5]}" if port[4] is not None else ""
                label = f"{dsn}{span}"
                if label not in labels:
                    labels.append(label)
            if not labels:
                span = f"@{port[4]}+{port[5]}" if port[4] is not None else ""
                labels.append(f"{port[1]}:DD {port[3]}{span}")
        return labels

    def to_dict(self) -> dict[str, Any]:
        nodes = set(self._out) | set(self._in)
        return {
            "programs": sorted(self.reports),
            "statistics": {
                "programs": len(self.reports),
                "nodes": len(nodes),
                "edges": sum(len(v) for v in self._out.values()),
                "datasets": len({n[1] for n in nodes if n[0] == "D"}),
                "tables": len({n[1] for n in nodes if n[0] == "T"}),
            },
            "opaque_callees": sorted(self.opaque_callees),
            "unjoined": list(self.unjoined),
            "caveats": list(self.caveats),
        }


def reports_from_scan(scan: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The ``lineage`` report of every program unit in a ``scan_files``
    result run with ``ScanOptions(analyzers=("lineage",))``, and one message
    per file or unit that produced none (so a program missing from the graph
    is never mistaken for one with no flows)."""
    reports: list[dict[str, Any]] = []
    problems: list[str] = []
    for file_scan in scan.files:
        if file_scan.error is not None:
            problems.append(f"{file_scan.path}: {file_scan.error}")
            continue
        for unit in file_scan.units:
            report = unit.reports.get("lineage")
            if report is not None:
                reports.append(report)
            else:
                reason = unit.failed_analyzers.get("lineage", "no report")
                problems.append(f"{file_scan.path}: {unit.program_name}: {reason}")
    return reports, problems
