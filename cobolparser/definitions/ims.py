"""IMS database and program definitions: DBDGEN (DBD) and PSBGEN (PSB) source.

``parse_dbd(source)`` returns each database's segments (hierarchy, length,
key and search fields); ``parse_psb(source)`` returns each PSB's PCBs with
the segments they are sensitive to and the processing options they grant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._asm import AsmStatement, OperandValue, as_int, as_list, flatten, read_statements


def _first(value: OperandValue | None) -> str | None:
    """The first string of *value* (``(A,B)`` -> ``A``)."""
    items = flatten(value) if value is not None else []
    return items[0].upper() if items and items[0] else None


@dataclass
class ImsField:
    name: str
    bytes: int | None
    start: int | None
    type: str | None
    sequence: bool = False
    unique: bool = True
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bytes": self.bytes,
            "start": self.start,
            "type": self.type,
            "is_key": self.sequence,
            "unique": self.unique,
            "line": self.line,
        }


@dataclass
class ImsSegment:
    name: str
    parent: str | None
    bytes: int | None
    line: int
    pointer: str | None = None
    source: list[str] = field(default_factory=list)
    fields: list[ImsField] = field(default_factory=list)
    lchildren: list[dict[str, Any]] = field(default_factory=list)
    xdfields: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str | None:
        """The segment's sequence (key) field, if it has one."""
        for item in self.fields:
            if item.sequence:
                return item.name
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parent": self.parent,
            "bytes": self.bytes,
            "key": self.key,
            "pointer": self.pointer,
            "source": self.source,
            "line": self.line,
            "fields": [f.to_dict() for f in self.fields],
            "lchildren": self.lchildren,
            "xdfields": self.xdfields,
        }


@dataclass
class ImsDatabase:
    name: str
    access: list[str]
    line: int
    datasets: list[str] = field(default_factory=list)
    segments: list[ImsSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "access": self.access,
            "datasets": self.datasets,
            "line": self.line,
            "root": self.segments[0].name if self.segments else None,
            "segments": [s.to_dict() for s in self.segments],
        }


@dataclass
class DbdDefinitions:
    databases: list[ImsDatabase] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "DBD",
            "databases": [d.to_dict() for d in self.databases],
            "warnings": self.warnings,
        }


def _parent(value: OperandValue | None) -> str | None:
    """PARENT=0 -> None; PARENT=SEG or PARENT=((SEG,SNGL),...) -> SEG."""
    name = _first(value)
    return None if name in (None, "0") else name


def _bytes(value: OperandValue | None) -> int | None:
    """BYTES=n, or the maximum of BYTES=(max,min)."""
    items = as_list(value)
    return as_int(items[0]) if items else None


class _DbdBuilder:
    def __init__(self) -> None:
        self.result = DbdDefinitions()
        self.database: ImsDatabase | None = None
        self.segment: ImsSegment | None = None

    def warn(self, stmt: AsmStatement, message: str) -> None:
        self.result.warnings.append({"line": stmt.line, "message": message})

    def dbd(self, stmt: AsmStatement) -> None:
        name = _first(stmt.keyword("NAME"))
        if not name:
            self.warn(stmt, "DBD without NAME=")
            return
        self.database = ImsDatabase(
            name=name,
            access=[a.upper() for a in flatten(stmt.keyword("ACCESS") or [])],
            line=stmt.line,
        )
        self.result.databases.append(self.database)
        self.segment = None

    def dataset(self, stmt: AsmStatement) -> None:
        if self.database is None:
            return
        for key in ("DD1", "DD2", "OVFLW"):
            value = _first(stmt.keyword(key))
            if value:
                self.database.datasets.append(value)

    def segm(self, stmt: AsmStatement) -> None:
        if self.database is None:
            self.warn(stmt, "SEGM before a DBD statement")
            return
        name = _first(stmt.keyword("NAME"))
        if not name:
            self.warn(stmt, "SEGM without NAME=")
            return
        self.segment = ImsSegment(
            name=name,
            parent=_parent(stmt.keyword("PARENT")),
            bytes=_bytes(stmt.keyword("BYTES")),
            line=stmt.line,
            pointer=stmt.text("POINTER"),
            source=[s.upper() for s in flatten(stmt.keyword("SOURCE") or [])],
        )
        self.database.segments.append(self.segment)

    def field_(self, stmt: AsmStatement) -> None:
        if self.segment is None:
            self.warn(stmt, "FIELD outside a SEGM")
            return
        names = [n.upper() for n in flatten(stmt.keyword("NAME") or [])]
        if not names:
            self.warn(stmt, "FIELD without NAME=")
            return
        self.segment.fields.append(
            ImsField(
                name=names[0],
                bytes=as_int(stmt.keyword("BYTES")),
                start=as_int(stmt.keyword("START")),
                type=stmt.text("TYPE"),
                sequence="SEQ" in names[1:],
                unique="M" not in names[1:],
                line=stmt.line,
            )
        )

    def lchild(self, stmt: AsmStatement) -> None:
        if self.segment is None:
            return
        names = [n.upper() for n in flatten(stmt.keyword("NAME") or [])]
        self.segment.lchildren.append(
            {
                "segment": names[0] if names else None,
                "database": names[1] if len(names) > 1 else None,
                "pointer": stmt.text("POINTER"),
                "line": stmt.line,
            }
        )

    def xdfld(self, stmt: AsmStatement) -> None:
        if self.segment is None:
            return
        self.segment.xdfields.append(
            {
                "name": _first(stmt.keyword("NAME")),
                "search_fields": [
                    s.upper() for s in flatten(stmt.keyword("SRCH") or [])
                ],
                "line": stmt.line,
            }
        )


def parse_dbd(source: str) -> DbdDefinitions:
    """The databases (one per DBD statement) of a DBDGEN member."""
    builder = _DbdBuilder()
    handlers = {
        "DBD": builder.dbd,
        "DATASET": builder.dataset,
        "AREA": builder.dataset,
        "SEGM": builder.segm,
        "FIELD": builder.field_,
        "LCHILD": builder.lchild,
        "XDFLD": builder.xdfld,
    }
    for stmt in read_statements(source):
        handler = handlers.get(stmt.operation)
        if handler is not None:
            handler(stmt)
    return builder.result


# ---------------------------------------------------------------------------
# PSB
# ---------------------------------------------------------------------------


@dataclass
class SensitiveSegment:
    name: str
    parent: str | None
    procopt: str | None
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parent": self.parent,
            "procopt": self.procopt,
            "line": self.line,
        }


@dataclass
class ProgramCommunicationBlock:
    type: str
    line: int
    label: str | None = None
    dbdname: str | None = None
    procopt: str | None = None
    keylen: int | None = None
    lterm: str | None = None
    #: ``PROCSEQ=``: the secondary-index database the program reads through.
    procseq: str | None = None
    sensitive_segments: list[SensitiveSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.label,
            "dbdname": self.dbdname,
            "procopt": self.procopt,
            "keylen": self.keylen,
            "lterm": self.lterm,
            "procseq": self.procseq,
            "line": self.line,
            "sensitive_segments": [s.to_dict() for s in self.sensitive_segments],
        }


@dataclass
class ProgramSpecificationBlock:
    name: str | None
    line: int
    language: str | None = None
    pcbs: list[ProgramCommunicationBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "line": self.line,
            "databases": sorted({p.dbdname for p in self.pcbs if p.dbdname}),
            "pcbs": [p.to_dict() for p in self.pcbs],
        }


@dataclass
class PsbDefinitions:
    psbs: list[ProgramSpecificationBlock] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "PSB",
            "psbs": [p.to_dict() for p in self.psbs],
            "warnings": self.warnings,
        }


class _PsbBuilder:
    def __init__(self) -> None:
        self.result = PsbDefinitions()
        self.pending: list[ProgramCommunicationBlock] = []
        self.pcb: ProgramCommunicationBlock | None = None

    def pcb_statement(self, stmt: AsmStatement) -> None:
        pcb_type = (stmt.text("TYPE") or "DB").upper()
        name = stmt.text("PCBNAME") or stmt.name
        dbdname = _first(stmt.keyword("DBDNAME"))
        if dbdname is None and pcb_type in ("DB", "GSAM"):
            # PSBGEN takes the DBD name as NAME= too (older PSBs), or positionally.
            dbdname = _first(stmt.keyword("NAME")) or (
                _first(stmt.positional[0]) if stmt.positional else None
            )
            if dbdname is None:
                self.result.warnings.append(
                    {
                        "line": stmt.line,
                        "message": f"TYPE={pcb_type} PCB without a DBD name",
                    }
                )
        procseq = _first(stmt.keyword("PROCSEQ"))
        self.pcb = ProgramCommunicationBlock(
            type=pcb_type,
            line=stmt.line,
            label=name.upper() if name else None,
            dbdname=dbdname,
            procopt=stmt.text("PROCOPT"),
            keylen=as_int(stmt.keyword("KEYLEN")),
            lterm=stmt.text("LTERM"),
            procseq=procseq.upper() if procseq else None,
        )
        self.pending.append(self.pcb)

    def senseg(self, stmt: AsmStatement) -> None:
        name = _first(stmt.keyword("NAME"))
        if self.pcb is None or not name:
            self.result.warnings.append(
                {"line": stmt.line, "message": "SENSEG outside a PCB"}
            )
            return
        self.pcb.sensitive_segments.append(
            SensitiveSegment(
                name=name,
                parent=_parent(stmt.keyword("PARENT")),
                procopt=stmt.text("PROCOPT") or self.pcb.procopt,
                line=stmt.line,
            )
        )

    def psbgen(self, stmt: AsmStatement) -> None:
        name = stmt.text("PSBNAME")
        self.result.psbs.append(
            ProgramSpecificationBlock(
                name=name.upper() if name else None,
                line=stmt.line,
                language=stmt.text("LANG"),
                pcbs=self.pending,
            )
        )
        self.pending = []
        self.pcb = None

    def finish(self) -> None:
        if self.pending:
            self.result.warnings.append(
                {
                    "line": self.pending[0].line,
                    "message": "PCBs without a PSBGEN statement",
                }
            )
            self.result.psbs.append(
                ProgramSpecificationBlock(
                    name=None, line=self.pending[0].line, pcbs=self.pending
                )
            )


def parse_psb(source: str) -> PsbDefinitions:
    """The PSBs (one per PSBGEN statement) of a PSBGEN member."""
    builder = _PsbBuilder()
    handlers = {
        "PCB": builder.pcb_statement,
        "SENSEG": builder.senseg,
        "PSBGEN": builder.psbgen,
    }
    for stmt in read_statements(source):
        handler = handlers.get(stmt.operation)
        if handler is not None:
            handler(stmt)
    builder.finish()
    return builder.result
