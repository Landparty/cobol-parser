"""CICS BMS map definitions: DFHMSD (mapset), DFHMDI (map), DFHMDF (field).

``parse_bms(source)`` returns the mapsets of a member with their maps and
fields, each field at its row and column, so a screen can be drawn and a
program's ``SEND MAP`` / ``RECEIVE MAP`` tied to what the user sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._asm import AsmStatement, as_int, as_list, flatten, read_statements

#: BMS defaults a screen to 24 x 80 when DFHMDI / DFHMSD give no SIZE.
DEFAULT_SIZE = (24, 80)


@dataclass
class BmsField:
    """One DFHMDF: a constant, an input field or an output field."""

    name: str | None
    row: int | None
    column: int | None
    length: int | None
    attributes: list[str]
    initial: str | None
    line: int
    picin: str | None = None
    picout: str | None = None
    color: str | None = None
    occurs: int | None = None

    @property
    def kind(self) -> str:
        """``input`` (UNPROT), ``output`` (named, protected) or ``constant``."""
        if "UNPROT" in self.attributes:
            return "input"
        if self.name:
            return "output"
        return "constant"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "row": self.row,
            "column": self.column,
            "length": self.length,
            "attributes": self.attributes,
            "initial": self.initial,
            "picin": self.picin,
            "picout": self.picout,
            "color": self.color,
            "occurs": self.occurs,
            "line": self.line,
        }


@dataclass
class BmsMap:
    """One DFHMDI and its fields."""

    name: str
    rows: int
    columns: int
    line: int
    origin_line: int | None = None
    origin_column: int | None = None
    fields: list[BmsField] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        named = [f for f in self.fields if f.name]
        return {
            "name": self.name,
            "rows": self.rows,
            "columns": self.columns,
            "origin_line": self.origin_line,
            "origin_column": self.origin_column,
            "line": self.line,
            "field_count": len(self.fields),
            "input_fields": [f.name for f in named if f.kind == "input"],
            "output_fields": [f.name for f in named if f.kind == "output"],
            "title": self.title,
            "fields": [f.to_dict() for f in self.fields],
        }

    @property
    def title(self) -> str | None:
        """The first constant on the top-most row that has one (the screen's heading)."""
        constants = [
            f
            for f in self.fields
            if f.kind == "constant" and f.initial and f.initial.strip()
        ]
        if not constants:
            return None
        first = min(constants, key=lambda f: ((f.row or 0), (f.column or 0)))
        return first.initial.strip() if first.initial else None


@dataclass
class BmsMapset:
    """One DFHMSD and its maps."""

    name: str
    line: int
    mode: str | None = None
    language: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    maps: list[BmsMap] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "language": self.language,
            "attributes": self.attributes,
            "line": self.line,
            "maps": [m.to_dict() for m in self.maps],
        }


@dataclass
class BmsDefinitions:
    """Every mapset of one member, and what could not be read."""

    mapsets: list[BmsMapset] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "BMS",
            "mapsets": [m.to_dict() for m in self.mapsets],
            "warnings": self.warnings,
        }


def _size(value: Any) -> tuple[int, int] | None:
    items = as_list(value)
    if len(items) == 2:
        rows, cols = as_int(items[0]), as_int(items[1])
        if rows and cols:
            return rows, cols
    return None


def _position(stmt: AsmStatement, width: int) -> tuple[int | None, int | None]:
    """``(row, column)`` of a DFHMDF, 1-based; ``POS=n`` is an offset from 0."""
    value = stmt.keyword("POS")
    items = as_list(value)
    if len(items) == 2:
        return as_int(items[0]), as_int(items[1])
    offset = as_int(value) if isinstance(value, str) else None
    if offset is None:
        return None, None
    return offset // width + 1, offset % width + 1


class _BmsBuilder:
    def __init__(self) -> None:
        self.result = BmsDefinitions()
        self.mapset: BmsMapset | None = None
        self.current: BmsMap | None = None

    def warn(self, stmt: AsmStatement, message: str) -> None:
        self.result.warnings.append({"line": stmt.line, "message": message})

    def mapset_statement(self, stmt: AsmStatement) -> None:
        if (stmt.text("TYPE") or "").upper() == "FINAL":
            self.mapset = None
            self.current = None
            return
        if not stmt.name:
            self.warn(stmt, "DFHMSD without a mapset name")
            return
        attributes = {
            key: ",".join(flatten(value))
            for key, value in stmt.keywords.items()
            if key not in ("MODE", "LANG")
        }
        self.mapset = BmsMapset(
            name=stmt.name.upper(),
            line=stmt.line,
            mode=stmt.text("MODE"),
            language=stmt.text("LANG"),
            attributes=attributes,
        )
        self.result.mapsets.append(self.mapset)
        self.current = None

    def map_statement(self, stmt: AsmStatement) -> None:
        if self.mapset is None:
            self.warn(stmt, "DFHMDI outside a DFHMSD")
            return
        if not stmt.name:
            self.warn(stmt, "DFHMDI without a map name")
            return
        size = (
            _size(stmt.keyword("SIZE")) or _size_of_mapset(self.mapset) or DEFAULT_SIZE
        )
        self.current = BmsMap(
            name=stmt.name.upper(),
            rows=size[0],
            columns=size[1],
            line=stmt.line,
            origin_line=as_int(stmt.keyword("LINE")),
            origin_column=as_int(stmt.keyword("COLUMN")),
        )
        self.mapset.maps.append(self.current)

    def field_statement(self, stmt: AsmStatement) -> None:
        if self.current is None:
            self.warn(stmt, "DFHMDF outside a DFHMDI")
            return
        row, column = _position(stmt, self.current.columns)
        attributes = [a.upper() for a in flatten(stmt.keyword("ATTRB") or [])]
        initial = stmt.text("INITIAL")
        if initial is None and stmt.keyword("XINIT") is not None:
            initial = _hex_text(stmt.text("XINIT") or "")
        self.current.fields.append(
            BmsField(
                name=stmt.name.upper() if stmt.name else None,
                row=row,
                column=column,
                length=as_int(stmt.keyword("LENGTH")),
                attributes=attributes,
                initial=initial,
                line=stmt.line,
                picin=stmt.text("PICIN"),
                picout=stmt.text("PICOUT"),
                color=stmt.text("COLOR"),
                occurs=as_int(stmt.keyword("OCCURS")),
            )
        )


def _size_of_mapset(mapset: BmsMapset) -> tuple[int, int] | None:
    size = mapset.attributes.get("SIZE")
    if not size:
        return None
    parts = size.split(",")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None


def _hex_text(value: str) -> str | None:
    """XINIT hex as text (EBCDIC cp037); None when it is not valid hex."""
    try:
        return bytes.fromhex(value).decode("cp037")
    except ValueError:
        return None


def parse_bms(source: str) -> BmsDefinitions:
    """The mapsets, maps and fields of a BMS member."""
    builder = _BmsBuilder()
    handlers = {
        "DFHMSD": builder.mapset_statement,
        "DFHMDI": builder.map_statement,
        "DFHMDF": builder.field_statement,
    }
    for stmt in read_statements(source):
        handler = handlers.get(stmt.operation)
        if handler is not None:
            handler(stmt)
    return builder.result
