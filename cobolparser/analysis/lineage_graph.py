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

from ._names import split_qualified_name
from .field_lineage import (
    ITEM,
    PORT_CALL,
    PORT_FILE,
    PORT_LINKAGE,
    PORT_SQL,
    VALUE_CHANGING_KINDS,
    FieldFlowReport,
    normalize_ddname,
    overlay_class,
)

#: System interfaces a CALL reaches that are neither a business program
#: nor a value transformer: MQ, IMS DL/I, LE callable services, DB2 attach.
#: Values sent to them leave (a queue, a database segment); values they hand
#: back come from outside. Never treated as an opaque pass-through.
_MQI_CALLS = (
    "MQBACK|MQBEGIN|MQBUFMH|MQCB|MQCLOSE|MQCMIT|MQCONN|MQCONNX|MQCRTMH|MQCTL"
    "|MQDISC|MQDLTMH|MQDLTMP|MQGET|MQINQ|MQINQMP|MQMHBUF|MQOPEN|MQPUT|MQPUT1"
    "|MQSET|MQSETMP|MQSTAT|MQSUB|MQSUBRQ"
)
_INTERFACE_RE = re.compile(
    rf"^({_MQI_CALLS}|CBLTDLI|AIBTDLI|CEETDLI|AERTDLI|ASMTDLI|PLITDLI|CTDLI"
    r"|CEE[A-Z0-9]+|DSNTIAR|DSNTIAC|DSNALI|DSNHLI|DSNRLI|ILBO[A-Z0-9]*|IGZ[A-Z0-9]*)$"
)
#: ``DD DUMMY`` / ``DSN=NULLFILE``: nothing is read or kept, so nothing joins.
_NULL_DATASETS = frozenset({"NULLFILE", "DUMMY"})
_DUP_SUFFIX_RE = re.compile(r"#\d+$")

_GDG_RELATIVE_RE = re.compile(r"\(\s*[+-]?\d+\s*\)$")
_GDG_ABSOLUTE_RE = re.compile(r"\.G\d{4}V\d{2}$")

# Node keys. Program-scoped: ("P", program, kind, name, offset, length).
# Shared: ("D", dataset, offset, length) and ("T", "TABLE.COLUMN").
NodeKey = tuple[Any, ...]
#: (node, overlay class of the edge it arrived over: see ``overlay_class``).
_State = tuple[NodeKey, int]

#: The caveat a second report for one PROGRAM-ID raises, naming the program.
_DUPLICATE_PROGRAM = re.compile(r"PROGRAM-ID (\S+) appears in more than one report")


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
    #: The file ``line`` is in, when the report was stamped with a source
    #: map (``apply_source_map``): a copybook's line and the program's own
    #: line of the same number are told apart by it (#489).
    origin_file: str | None = None


@dataclass(frozen=True)
class Hop:
    """One step of an impact path."""

    program: str | None
    node: str
    kind: str
    line: int
    statement: str
    confidence: str
    #: The file ``line`` is in, when known (see ``_EdgeInfo.origin_file``).
    #: Not part of ``to_dict()``: the CLI JSON shape is unchanged.
    origin_file: str | None = None

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
    #: False when nothing in any report matched the start.
    start_found: bool = True
    #: Facts about the answer that are not gaps in it (a declared field
    #: with no value flow at all).
    notes: list[str] = field(default_factory=list)
    #: The caveats (also in ``caveats``) saying the start named several
    #: fields of one program, for a caller that reports ambiguity apart.
    ambiguous: list[str] = field(default_factory=list)

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
            "start_found": self.start_found,
            "notes": list(self.notes),
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
            # Ports too (console, an unbound DD, a CALL, a LINKAGE
            # parameter): that is where the trail leaves the program, and
            # the JSON lists them (#528).
            if hit.node_kind in ("item", "port") and hit.program:
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
                    h.label
                    for h in reversed(hit.path[:-1])
                    if h.kind not in ("redefines", "occurrence")
                )
                label = f"port {hit.field}" if hit.node_kind == "port" else hit.field
                lines.append(
                    f"  {label}{where}  [{', '.join(tags)}]"
                    + (f"\n      via {via}" if via else "")
                )
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            lines += [f"  - {n}" for n in self.notes]
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


def _opaque_caveat(callees: list[str]) -> str:
    return (
        "not in the scan (or not COBOL), so assumed to pass every input "
        "argument through to every output argument: " + ", ".join(sorted(callees))
    )


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
        join_edges: Sequence[dict[str, Any]] | None = None,
        join_caveats: Sequence[str] | None = None,
        unjoined: Sequence[str] | None = None,
    ) -> None:
        """``join_edges`` (the output of :meth:`join_edges` on an earlier
        graph over the same reports) replaces the joins: the backend computes
        them once, at upload, and builds the graph from its stored rows
        afterwards without the JCL. ``bindings`` / ``passthroughs`` are then
        ignored.

        ``join_caveats`` and ``unjoined`` restore what the joins said besides
        their edges (a reformatting utility step, an opaque callee, a DD no
        JCL binds): the ``"caveats"`` and ``"unjoined"`` of
        :meth:`join_state`. Without them a graph rebuilt from stored edges
        only re-derives the opaque-callee caveat and has no ``unjoined``.
        When ``join_edges`` is None, ``unjoined`` is ignored and
        ``join_caveats`` are added to the joins' own caveats: what the
        binding source could not read (``lineage_jcl.bindings_from_jobs``'s
        ``caveats``).
        """
        self.reports: dict[str, dict[str, Any]] = {}
        duplicates: list[str] = []
        for report in reports:
            data = report.to_dict() if isinstance(report, FieldFlowReport) else report
            program = str(data.get("program_id") or "").upper()
            if program in self.reports:
                if program not in duplicates:
                    duplicates.append(program)
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
        self.caveats: list[str] = [
            f"PROGRAM-ID {program} appears in more than one report; only the "
            "first is in the graph"
            for program in duplicates
        ]
        self.unjoined: list[str] = []
        self.opaque_callees: list[str] = []
        #: The caveats the joins themselves raised (what :meth:`join_state`
        #: exports), apart from the reports' own.
        self._join_caveats: list[str] = []
        self._out: dict[NodeKey, list[tuple[NodeKey, _EdgeInfo]]] = {}
        self._in: dict[NodeKey, list[tuple[NodeKey, _EdgeInfo]]] = {}
        self._joins: list[tuple[NodeKey, NodeKey, _EdgeInfo]] = []
        self._recording = False
        self._build(join_edges, join_caveats, unjoined)

    # -- building ----------------------------------------------------------

    def _add(self, src: NodeKey, dst: NodeKey, info: _EdgeInfo) -> None:
        if src == dst:
            return
        if self._recording:
            self._joins.append((src, dst, info))
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

    def _join_caveat(self, text: str) -> None:
        self._join_caveats.append(text)
        self.caveats.append(text)

    def _build(
        self,
        join_edges: Sequence[dict[str, Any]] | None,
        join_caveats: Sequence[str] | None = None,
        unjoined: Sequence[str] | None = None,
    ) -> None:
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
                        origin_file=(edge.get("origin") or {}).get("file"),
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
        if join_edges is None:
            self._recording = True
            self._join_files(written_ports, read_ports)
            self._join_sql(written_ports, read_ports)
            self._join_calls(written_ports, read_ports)
            self._recording = False
            # What the binding source could not read (a JCL step left out,
            # from ``lineage_jcl.bindings_from_jobs(jobs, caveats)``).
            for caveat in join_caveats or []:
                if str(caveat) not in self._join_caveats:
                    self._join_caveat(str(caveat))
        else:
            # Recorded again, so the rebuilt graph exports the same state.
            self._recording = True
            for edge in join_edges:
                self._load_join_edge(edge)
            self._recording = False
            if join_caveats is not None:
                for caveat in join_caveats:
                    self._join_caveat(str(caveat))
            elif self.opaque_callees:
                self._join_caveat(_opaque_caveat(self.opaque_callees))
            self.unjoined = [str(u) for u in unjoined or []]
        for caveat_source in self.reports.values():
            for caveat in caveat_source.get("caveats") or []:
                text = f"{caveat_source.get('program_id')}: {caveat}"
                if text not in self.caveats:
                    self.caveats.append(text)

    def join_edges(self) -> list[dict[str, Any]]:
        """The edges the joins added (dataset, utility, CALL, table and
        opaque pass-through), JSON-shaped, in a stable order: what a caller
        stores to rebuild this graph later with ``LineageGraph(reports,
        join_edges=...)``. Node keys are lists: ``["P", program, kind, name,
        offset, length]``, ``["D", dataset, offset, length]`` or ``["T",
        "TABLE.COLUMN"]``."""
        return [
            {
                "source": list(src),
                "target": list(dst),
                "kind": info.kind,
                "line": info.line,
                "statement": info.statement,
                "confidence": info.confidence,
                "cross": info.cross,
            }
            for src, dst, info in self._joins
        ]

    def join_state(self) -> dict[str, Any]:
        """Everything the joins produced, JSON-shaped: ``{"edges":
        join_edges(), "caveats": [...], "unjoined": [...]}``. Rebuild with
        ``LineageGraph(reports, join_edges=state["edges"],
        join_caveats=state["caveats"], unjoined=state["unjoined"])`` for a
        graph whose ``to_dict()`` and impact caveats match this one."""
        return {
            "edges": self.join_edges(),
            "caveats": list(self._join_caveats),
            "unjoined": list(self.unjoined),
        }

    def _load_join_edge(self, edge: dict[str, Any]) -> None:
        info = _EdgeInfo(
            kind=str(edge.get("kind") or ""),
            line=int(edge.get("line") or 0),
            statement=str(edge.get("statement") or ""),
            confidence=str(edge.get("confidence") or "exact"),
            cross=bool(edge.get("cross")),
        )
        self._add(tuple(edge["source"]), tuple(edge["target"]), info)
        if info.kind == "opaque-call":
            callee = info.statement.removeprefix("CALL ")
            if callee and callee not in self.opaque_callees:
                self.opaque_callees.append(callee)

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
                    bindings = [
                        b
                        for b in self._datasets_for(program, node[3])
                        if normalize_dataset(b.dataset) not in _NULL_DATASETS
                    ]
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
                if src in _NULL_DATASETS or dst in _NULL_DATASETS:
                    continue
                if pt.kind == "reformat":
                    if src in ranges and dst not in stopped:
                        stopped.add(dst)
                        self._join_caveat(
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
        columns: set[str] = set()
        for program in self.reports:
            for node in written.get(program, []):
                if node[2] == PORT_SQL:
                    columns.add(node[3])
                    self._add(node, ("T", node[3]), _EdgeInfo("table", cross=True))
            for node in read.get(program, []):
                if node[2] == PORT_SQL:
                    columns.add(node[3])
                    self._add(("T", node[3]), node, _EdgeInfo("table", cross=True))
        # SCHEMA.TABLE.COLUMN and an unqualified TABLE.COLUMN may be one
        # column (the unqualified one resolves through CURRENT SQLID /
        # QUALIFIER at bind time, which no source says): join them both ways
        # as candidates. Two different schemas never join.
        unqualified = {c for c in columns if c.count(".") == 1}
        for column in sorted(columns):
            if column.count(".") < 2:
                continue
            short = ".".join(column.split(".")[-2:])
            if short in unqualified:
                info = _EdgeInfo(
                    "table-alias",
                    statement="schema not given",
                    confidence="candidate",
                )
                self._add(("T", column), ("T", short), info)
                self._add(("T", short), ("T", column), info)

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
            self._join_caveat(_opaque_caveat(self.opaque_callees))

    # -- queries -----------------------------------------------------------

    def _items_named(
        self, field_name: str, programs: Sequence[str] | None
    ) -> list[NodeKey]:
        groups, _matched = self._start_groups(field_name, programs)
        return sorted({n for group in groups for n in group}, key=repr)

    def _start_groups(
        self, field_name: str, programs: Sequence[str] | None
    ) -> tuple[list[list[NodeKey]], dict[str, list[str]]]:
        """The start nodes of *field_name*, one group per qualified name it
        matched (an item's own node, its occurrences and subordinate fields,
        in every program), and program -> the qualified names it matched."""
        parts = split_qualified_name(field_name)
        if not parts:
            return [], {}
        name, qualifiers = parts[0], parts[1:]
        wanted = [p.upper() for p in programs] if programs else list(self.reports)
        matched: dict[str, list[str]] = {}
        for prog in wanted:
            data = self.reports.get(prog)
            if data is None:
                continue
            for item in data.get("items") or []:
                qname = str(item["qualified_name"]).upper()
                segments = _DUP_SUFFIX_RE.sub("", qname).split(".")
                if qname == name or segments[-1] == name:
                    if all(q in segments[:-1] for q in qualifiers):
                        matched.setdefault(prog, []).append(qname)
        # Grouped by qualified name, not by program: a copybook field is one
        # group however many programs COPY it, so the trace count stays the
        # number of distinct fields matched.
        groups: dict[str, list[NodeKey]] = {}
        seen: set[NodeKey] = set()
        for node in (*self._out, *self._in):
            if node[0] != "P" or node[2] != ITEM or node in seen:
                continue
            owners = [
                m
                for m in matched.get(node[1], [])
                if node[3] == m or node[3].startswith((m + ".", m + "("))
            ]
            if owners:
                seen.add(node)
                # A node under two matched items (one nested in the other)
                # belongs to the closer one.
                owner = max(owners, key=len)
                groups.setdefault(owner, []).append(node)
        return (
            [sorted(groups[key], key=repr) for key in sorted(groups)],
            matched,
        )

    def impact(
        self,
        field_name: str,
        program: str | Sequence[str] | None = None,
        direction: str = "forward",
        depth: int | None = None,
    ) -> ImpactResult:
        """Everything *field_name* (in *program*, in any of several programs
        -- a copybook field lives in every program that COPYs it -- or in
        every program when None) feeds (``direction="forward"``) or is fed by
        (``"backward"``).

        ``depth`` caps the number of joins between programs (dataset, CALL,
        table) a path may cross; ``None`` follows every one.
        """
        programs = [program] if isinstance(program, str) else program
        groups, matched = self._start_groups(field_name, programs)
        starts = sorted({n for group in groups for n in group}, key=repr)
        if programs:
            label = [f"{p.upper()}:{field_name.upper()}" for p in programs]
        else:
            label = [field_name.upper()]
        # A bare name shared by several fields of one program (AMT in IN-REC
        # and OUT-REC) starts from all of them: say so, naming each (#540).
        # Computed before the no-flow return below, so an ambiguous name
        # whose matches carry no flow still gets the caveat.
        ambiguous: list[str] = []
        for prog in sorted(matched):
            names = sorted(set(matched[prog]))
            if len(names) > 1:
                ambiguous.append(
                    f"{prog}: {field_name.upper()} matches {len(names)} fields: "
                    f"{', '.join(names)}; qualify with OF to trace one"
                )
        if matched and not starts:
            # Declared, but no edge touches it: set only from literals or
            # VALUE, or only tested in a condition. That is "feeds nothing",
            # not "no such field" (which is for a name matching no item).
            result = ImpactResult(start=label, direction=direction, depth=depth)
            result.notes.append(
                f"{', '.join(label)}: declared, but no value flows into or out "
                "of it (only literals, VALUE clauses or conditions use it)"
            )
        else:
            result = self._trace(starts, label, direction, depth, groups)
        for caveat in ambiguous:
            result.ambiguous.append(caveat)
            result.caveats.insert(len(result.ambiguous) - 1, caveat)
        return result

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
        groups: list[list[NodeKey]] | None = None,
    ) -> ImpactResult:
        """Trace from *starts*. With several *groups* (one per field a bare
        name matched), each is traced on its own, so a field one start
        reaches is a hit even when it is another start (#540)."""
        result = ImpactResult(start=label, direction=direction, depth=depth)
        if not starts:
            result.start_found = False
            result.caveats.append(f"{', '.join(label)}: no such field in any report")
            return result
        adjacency = self._out if direction == "forward" else self._in
        merged: dict[NodeKey, ImpactHit] = {}
        for group in groups if groups and len(groups) > 1 else [starts]:
            for node, hit in self._reach(group, adjacency, depth):
                old = merged.get(node)
                if old is None or len(hit.path) < len(old.path):
                    merged[node] = hit
        hits = list(merged.values())
        hits.sort(
            key=lambda h: (
                h.node_kind != "table",
                h.node_kind != "dataset",
                h.program or "",
                h.field,
            )
        )
        return self._finish(result, hits, starts)

    def _reach(
        self,
        starts: list[NodeKey],
        adjacency: dict[NodeKey, list[tuple[NodeKey, _EdgeInfo]]],
        depth: int | None,
    ) -> list[tuple[NodeKey, ImpactHit]]:
        """Every node *starts* reach (other than themselves), with its path."""
        # 0-1 BFS: stepping into a program from outside it (from a dataset or
        # table, or across a CALL) costs 1; every other step costs 0. So
        # ``depth=1`` reaches the programs one join away.
        # A state is (node, overlay class it arrived over): as in a
        # program's own summary, two alias edges of one class in a row are
        # never chained, or one field of a record would reach every other
        # field of it through an alias covering the whole record (and one
        # occurrence of a table every other through the table as a whole).
        best: dict[_State, int] = {}
        parent: dict[_State, tuple[_State, _EdgeInfo]] = {}
        queue: deque[tuple[_State, int]] = deque()
        for start in starts:
            best[(start, 0)] = 0
            queue.append(((start, 0), 0))
        while queue:
            state, cost = queue.popleft()
            if cost > best.get(state, cost):
                continue
            node, arrived = state
            for nxt, info in adjacency.get(node, []):
                overlay = overlay_class(info.kind)
                if overlay and overlay == arrived:
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
        hits: list[tuple[NodeKey, ImpactHit]] = []
        for node, state in chosen.items():
            if node in start_set:
                continue
            program, name, kind = self._describe(node)
            if kind == "port" and any(
                info.cross or nxt[0] != "P" or nxt[1] != node[1]
                for nxt, info in adjacency.get(node, [])
            ):
                # A port is only worth reporting where the trail ends at it:
                # a DD no JCL binds, a CALL to nothing, a console line. A
                # join (a bound dataset, a callee in the scan) carries the
                # trail on; an edge back into the same program does not --
                # an I-O file, a BY REFERENCE argument and a LINKAGE
                # parameter are two-way ports and still trail ends (#510).
                continue
            path: list[Hop] = []
            cursor = state
            while cursor[0] not in start_set or cursor[1]:
                prev, info = parent[cursor]
                p, n, _ = self._describe(cursor[0])
                path.append(
                    Hop(
                        p,
                        n,
                        info.kind,
                        info.line,
                        info.statement,
                        info.confidence,
                        info.origin_file,
                    )
                )
                cursor = prev
            path.reverse()
            hits.append((node, ImpactHit(program, name, kind, tuple(path))))
        return hits

    def _finish(
        self, result: ImpactResult, hits: list[ImpactHit], starts: list[NodeKey]
    ) -> ImpactResult:
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
            duplicate = _DUPLICATE_PROGRAM.match(caveat)
            if duplicate:
                # Only a query that reaches the duplicated program can be
                # missing the flows of its other copy.
                if duplicate.group(1) in reached:
                    result.caveats.append(caveat)
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
            # From the dataset edges the join added, not the bindings, so a
            # graph rebuilt from stored join edges answers the same.
            span = f"@{port[4]}+{port[5]}" if port[4] is not None else ""
            neighbours = [n for n, _ in self._out.get(port, [])]
            neighbours += [n for n, _ in self._in.get(port, [])]
            for node in neighbours:
                if node[0] != "D":
                    continue
                label = f"{node[1]}{span}"
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
