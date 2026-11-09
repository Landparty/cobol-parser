"""One program's text and data: ``read_source``, ``explain_symbol`` and
``record_layout``, with the data-item walk and byte-layout helpers they
share (also used by :mod:`..claims` and :mod:`..codebase_index`)."""

from __future__ import annotations

import difflib
import functools
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ...models.data_items import CobolDataItem, ConditionNameItem, RenamesItem
from ...models.program import CobolProgram, CobolSection
from ...preprocess import PreprocessingError
from ..envelope import Response, ToolError, clamp_limit
from ..workspace import ParsedProgram, stdout_to_stderr
from .common import (
    BaseTools,
    _attempt,
    _carry_parse_caveats,
    _declared_elsewhere,
    _file_facts,
    _worth_showing,
)

#: Prefixes of the xref caveats that are about undeclared names only.
_UNDECLARED_CAVEATS: tuple[str, ...] = (
    "the kind of an undefined symbol",
    "'undefined' means",
    "special registers",
)


#: Most lines :meth:`CobolTools.read_source` returns in one call.
MAX_SOURCE_LINES = 200


#: DATA DIVISION sections a record can be declared in, as
#: ``compute_program_data_items`` walks them.
_DATA_SECTIONS: tuple[str, ...] = (
    "FILE",
    "WORKING-STORAGE",
    "LOCAL-STORAGE",
    "LINKAGE",
)


def _source_lines(path: Path) -> Iterator[str]:
    """*path*'s lines, decoded as the parse decodes it (#522), so a line
    number in any other answer is the same line here.

    An ASCII-shaped encoding streams (newline="" splits on \n, \r\n and \r
    only, as split_source_lines does: never on a form feed inside a record),
    so a huge file costs no memory; EBCDIC / UTF-16 go through the same
    whole-file conversion the parse uses.
    """
    from ...preprocess.copybook_expander import (
        _is_ebcdic_codec,
        detect_encoding,
        read_program_source,
    )

    encoding = detect_encoding(str(path))
    if _is_ebcdic_codec(encoding) or encoding.startswith("utf-16"):
        yield from split_source_lines(read_program_source(str(path), encoding))
        return
    with path.open(encoding=encoding, errors="replace", newline="") as handle:
        for text in handle:
            yield text.rstrip("\r\n")


class StructureTools(BaseTools):
    """``read_source``, ``explain_symbol`` and ``record_layout``."""

    # -- read_source ---------------------------------------------------------

    def read_source(
        self, file: str, line: int = 1, before: int = 10, after: int = 10
    ) -> dict[str, Any]:
        """The lines around ``file:line``, numbered as an editor numbers them."""
        path = self.workspace.resolve(file)
        before = max(0, before)
        after = max(0, after)
        # The cap trims context, never the cited line (#537): lines are kept
        # from at most MAX_SOURCE_LINES - 1 either side of *line* while the
        # file streams past (the rest is only counted, so a huge file under
        # the root costs no memory), then cut to the budget once the end of
        # the file is known -- *line* and its ``after`` lines first, the
        # rest of the budget from ``before``.
        first_kept = max(1, line - min(before, MAX_SOURCE_LINES - 1))
        last_kept = line + min(after, MAX_SOURCE_LINES - 1)
        kept: dict[int, str] = {}
        total = 0
        try:
            for total, text in enumerate(_source_lines(path), start=1):
                if first_kept <= total <= last_kept:
                    kept[total] = text
        except (OSError, PreprocessingError) as exc:
            raise ToolError(f"cannot read {path.name}: {exc}") from exc
        if line < 1 or (total and line > total):
            raise ToolError(f"line {line} is outside {file} (1-{total})")
        requested_start = max(1, line - before)
        requested_end = min(total, line + after)
        end = min(requested_end, line + MAX_SOURCE_LINES - 1)
        start = max(requested_start, end - MAX_SOURCE_LINES + 1)
        response = Response()
        if requested_end - requested_start + 1 > MAX_SOURCE_LINES:
            response.truncated.append(
                {
                    "field": "lines",
                    "shown": end - start + 1,
                    "total": requested_end - requested_start + 1,
                }
            )
        return response.build(
            {
                "file": self.workspace.display(path),
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "lines": [{"line": n, "text": kept[n]} for n in range(start, end + 1)],
            }
        )

    # -- explain_symbol ------------------------------------------------------

    def explain_symbol(
        self,
        file: str,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """What *name* is in *file*: declaration, layout, every reference."""
        from ...analysis.xref import XrefAnalyzer, is_special_register

        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no symbol name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        with stdout_to_stderr():
            report = XrefAnalyzer().analyze(unit)

        # A qualified name is resolved as the compiler resolves it: partial
        # chains, ``IN`` for ``OF``, and no need to qualify a unique name.
        matches = report.entries_named(wanted)

        program_info = parsed.program_info(unit)
        undeclared_asked = not matches or any(e.definition is None for e in matches)
        for caveat in report.caveats:
            # xref's notes about *undeclared* names only bear on an answer
            # about one; on every other answer they are noise a model pays for.
            if undeclared_asked or not caveat.startswith(_UNDECLARED_CAVEATS):
                response.caveat("incomplete-analysis", caveat)
        if not matches:
            undeclared = wanted in {u.upper() for u in report.undefined}
            special = is_special_register(wanted)
            names = sorted({e.name.upper() for e in report.entries})
            not_found: dict[str, Any] = {
                "name": wanted,
                "found": False,
                "referenced_but_undeclared": undeclared,
                "special_register": special,
                # A near-miss spelling is no help for RETURN-CODE or SQLCODE:
                # the name is right, it is just never declared.
                "suggestions": (
                    [] if special else difflib.get_close_matches(wanted, names, n=5)
                ),
            }
            if special:
                not_found["note"] = (
                    f"{wanted} is a special register or a precompiler/"
                    "translator-supplied item: the compiler provides it, so "
                    "the program never declares it"
                )
            _declared_elsewhere(
                not_found,
                parsed,
                unit,
                lambda other: any(
                    e.definition is not None
                    for e in XrefAnalyzer().analyze(other).entries_named(wanted)
                ),
            )
            return response.build(not_found, program_info)

        if len(matches) > 1:
            response.caveat(
                "ambiguous-name",
                f"{len(matches)} declarations are named {wanted}",
                "qualify the name (X OF Y) to ask about one of them",
            )
        if any(d.upper() == wanted for d in report.duplicate_declarations):
            response.caveat(
                "duplicate-declaration",
                f"{wanted} is declared more than once in one namespace",
                "every reference is attributed to the first declaration",
            )

        layout = _layout_index(unit, response)
        cap = clamp_limit(limit)
        symbols: list[dict[str, Any]] = []
        for index, entry in enumerate(matches):
            roles: dict[str, int] = {}
            for ref in entry.references:
                roles[ref.role] = roles.get(ref.role, 0) + 1
            refs = response.cap(
                list(entry.references), cap, f"symbols[{index}].references"
            )
            symbol: dict[str, Any] = {
                "name": entry.name,
                "kind": entry.kind,
                "qualified_name": entry.qualified_name,
                "level": entry.level,
                "section": entry.section,
                "declared_at": (
                    parsed.locate(
                        entry.definition.line, entry.definition.column, response
                    )
                    if entry.definition
                    else None
                ),
                "declared": entry.definition is not None,
                "reference_count": entry.reference_count,
                "references_by_role": roles,
                "references": [
                    {
                        # xref's column is the statement's, not the
                        # operand's: the line is exact, a column would mislead.
                        "location": parsed.locate(
                            ref.location.line,
                            None,
                            response,
                            column_known=False,
                        ),
                        "role": ref.role,
                        "statement": ref.statement,
                        "paragraph": ref.context,
                    }
                    for ref in refs
                ],
            }
            # data-items places a level-66 RENAMES item itself (#563).
            item = _layout_for(entry.name, entry.qualified_name, layout)
            if item is None and entry.level == 66:
                response.caveat(
                    "incomplete-analysis",
                    f"RENAMES item {entry.name}: the bytes it renames "
                    "could not be placed",
                    "no layout is reported for it",
                )
            if item is not None:
                _layout_caveats(item, layout, response)
                symbol["layout"] = {
                    key: item.get(key)
                    for key in (
                        "qualified_name",
                        "picture",
                        "usage",
                        "byte_offset",
                        "byte_length",
                        "offset_ambiguous",
                        "redefines_chain",
                        "occurs",
                        "condition_values",
                        "condition_ranges",
                    )
                    if _worth_showing(item.get(key))
                }
            symbols.append(symbol)

        return response.build(
            {"name": wanted, "found": True, "symbols": symbols}, program_info
        )

    # -- record_layout -------------------------------------------------------

    def record_layout(
        self,
        file: str,
        record: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The byte map of one record (or of every record of one FD)."""
        wanted = " ".join(record.split()).upper().replace(" IN ", " OF ")
        if not wanted:
            raise ToolError("no record name given")
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        cap = clamp_limit(limit)

        answer: dict[str, Any] = {"name": wanted}
        facts = _attempt(
            response, "file descriptions", lambda: _file_facts(parsed, unit)
        )
        fact = (facts or {}).get(wanted)
        if fact is not None:
            items = [
                item
                for record_name in fact.record_names
                for item in _data_items_named(unit, record_name.upper())
            ]
            answer["file"] = {
                "name": fact.file_name,
                "organization": fact.organization,
                "record_key": fact.record_key,
                "records": list(fact.record_names),
            }
            if len(items) > 1:
                answer["file"]["note"] = (
                    "several record descriptions under one FD share the same "
                    "record area, as if each REDEFINES the first"
                )
        else:
            items = _data_items_named(unit, wanted)
        if not items:
            renames = _renames_records(unit, wanted, parsed, response, cap)
            if renames:
                answer["found"] = True
                answer["records"] = renames
                answer["offsets_from"] = "the start of each record's 01/77 item"
                return response.build(answer, program_info)
            renames_name = wanted.split(" OF ")[0].strip()
            if _renames_node(unit, renames_name) is not None:
                # Declared, but data-items could not place it: say so rather
                # than let found: false read as "no such item" (#563).
                response.caveat(
                    "incomplete-analysis",
                    f"RENAMES item {renames_name}: the bytes it renames "
                    "could not be placed",
                    "no layout is reported for it",
                )
            names = sorted(
                {
                    found.item.name.upper()
                    for found in _walk_data_items(unit)
                    if not found.item.is_filler
                }
            )
            answer.update(
                {
                    "found": False,
                    "suggestions": difflib.get_close_matches(wanted, names, n=5),
                }
            )
            _declared_elsewhere(
                answer,
                parsed,
                unit,
                lambda other: bool(
                    (_file_facts(parsed, other)).get(wanted)
                    or _data_items_named(other, wanted)
                    or _renames_node(other, wanted.split(" OF ")[0].strip())
                ),
            )
            return response.build(answer, program_info)
        if len(items) > 1 and fact is None:
            response.caveat(
                "ambiguous-name",
                f"{len(items)} data items are named {wanted}",
                "qualify the name (X OF Y) to ask about one of them",
            )

        records = []
        for index, found in enumerate(items):
            layout = _attempt(
                response,
                "byte layout",
                functools.partial(_record_layout, found.root, response),
            )
            if layout is not None:
                records.append(
                    _layout_answer(found, layout, parsed, response, cap, index)
                )
        answer["found"] = True
        answer["records"] = records
        answer["offsets_from"] = "the start of each record's 01/77 item"
        return response.build(answer, program_info)


@dataclass
class _FoundItem:
    """A data item, the 01/77 record it lies in, and its section."""

    item: CobolDataItem
    root: CobolDataItem
    section: str
    #: Names from the record down to the item, as layouts name them.
    path: tuple[str, ...]


def _walk_data_items(unit: CobolProgram) -> Iterator[_FoundItem]:
    data = unit.get_division("DATA")
    if data is None:
        return
    for name in _DATA_SECTIONS:
        section = data.get_section_by_name(name)
        if not isinstance(section, CobolSection):
            continue
        for root in section.data_items:
            stack: list[tuple[CobolDataItem, tuple[str, ...]]] = [(root, (root.name,))]
            while stack:
                item, path = stack.pop()
                yield _FoundItem(item, root, name, path)
                children = [
                    c
                    for c in item.children
                    if isinstance(c, CobolDataItem) and c.level != 77
                ]
                for child in reversed(children):
                    stack.append((child, (*path, child.layout_name)))


def _data_items_named(unit: CobolProgram, wanted: str) -> list[_FoundItem]:
    """Data items named *wanted* (``X`` or ``X OF Y [OF Z]``), groups first."""
    parts = [p.strip() for p in wanted.split(" OF ")]
    name, qualifiers = parts[0], parts[1:]
    found = []
    for candidate in _walk_data_items(unit):
        if candidate.item.name.upper() != name:
            continue
        ancestors = {p.upper() for p in candidate.path[:-1]}
        if all(q in ancestors for q in qualifiers):
            found.append(candidate)
    return found


def _record_layout(root: CobolDataItem, response: Response) -> list[dict[str, Any]]:
    """*root*'s byte layout, with what it cannot vouch for (``SYNCHRONIZED``
    slack, partial level-88 values) flagged and carried as caveats -- the
    same flags ``data-items`` reports (#488)."""
    from ...layout.offsets import (
        compute_record_layout,
        flag_record_layout,
    )

    layout = compute_record_layout(root)
    for line in flag_record_layout(root, layout):
        response.caveat("incomplete-analysis", line, _unresolved_layout_effect(line))
    return [item.to_dict() for item in layout]


def _declarations(root: CobolDataItem) -> dict[str, list[tuple[int, Any]]]:
    """Each layout qualified name -> (source order, location) per declaration.

    FILLER repeats a qualified name; the layout lists same-named entries in
    source order, so the n-th layout entry of a name is its n-th
    declaration. The layout emits a group after its members, so the order
    is what puts the fields back in the order they are written.
    """
    out: dict[str, list[tuple[int, Any]]] = {}
    order = itertools.count()

    def add(qualified: str, location: Any) -> None:
        out.setdefault(qualified, []).append((next(order), location))

    def walk(item: CobolDataItem, path: tuple[str, ...]) -> None:
        qualified = ".".join(path)
        add(qualified, item.location)
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                add(f"{qualified}.{child.name}", child.location)
            elif isinstance(child, CobolDataItem) and child.level != 77:
                walk(child, (*path, child.layout_name))

    walk(root, (root.name,))
    return out


def _layout_answer(
    found: _FoundItem,
    layout: list[dict[str, Any]],
    parsed: ParsedProgram,
    response: Response,
    cap: int,
    index: int,
) -> dict[str, Any]:
    prefix = ".".join(found.path)
    declared = _declarations(found.root)
    used: dict[str, int] = {}
    own: dict[str, Any] | None = None
    fields: list[tuple[int, dict[str, Any]]] = []
    for entry in layout:
        qualified = str(entry["qualified_name"])
        n = used.get(qualified, 0)
        used[qualified] = n + 1
        if qualified != prefix and not qualified.startswith(prefix + "."):
            continue
        declarations = declared.get(qualified, [])
        order, location = (
            declarations[n] if n < len(declarations) else (len(layout), None)
        )
        row = {
            key: entry.get(key)
            for key in (
                "level",
                "name",
                "picture",
                "usage",
                "byte_offset",
                "byte_length",
                "offset_ambiguous",
                "occurs",
                "redefines_chain",
                "condition_values",
                "condition_ranges",
            )
            if _worth_showing(entry.get(key))
        }
        row["declared_at"] = (
            parsed.locate(location.line, location.column, response)
            if location is not None
            else None
        )
        if qualified == prefix and own is None:
            own = row
        else:
            fields.append((order, row))
    own = own or {}
    record: dict[str, Any] = {
        "name": found.item.name,
        "qualified_name": " OF ".join(reversed(found.path)),
        "section": found.section,
        "level": found.item.level,
        "declared_at": own.get("declared_at"),
        "byte_offset": own.get("byte_offset"),
        "byte_length": own.get("byte_length"),
    }
    if found.item is found.root and found.root.redefines:
        record["redefines"] = found.root.redefines
    elif own.get("redefines_chain"):
        record["redefines_chain"] = own["redefines_chain"]
    if own.get("offset_ambiguous"):
        record["offset_ambiguous"] = True
    ordered = [row for _, row in sorted(fields, key=lambda pair: pair[0])]
    record["field_count"] = len(ordered)
    record["fields"] = response.cap(ordered, cap, f"records[{index}].fields")
    return record


def _unresolved_layout_effect(line: str) -> str:
    """The effect of one byte-layout ``unresolved`` *line*: only SYNC slack
    puts offsets in doubt; a partial level-88 list leaves them exact."""
    if "condition_values lists only part" in line:
        return (
            "a value missing from condition_values may still satisfy the "
            "condition; read condition_ranges"
        )
    return (
        "offsets marked offset_ambiguous may be short; do not build a record "
        "image from them"
    )


def _layout_index(
    unit: CobolProgram, response: Response
) -> dict[str, list[dict[str, Any]]]:
    """Every data item's byte layout, by upper-cased name.

    The layout's ``unresolved`` lines are kept under :data:`_UNRESOLVED_KEY`
    for :func:`_layout_caveats` to carry the ones that bear on an answer.
    """
    from ...layout.offsets import compute_program_data_items

    try:
        with stdout_to_stderr():
            computed = compute_program_data_items(unit)
            items = computed["items"]
    except Exception as exc:  # noqa: BLE001 -- one analyzer must not sink the answer
        response.caveat(
            "analyzer-failed",
            f"byte layout could not be computed: {exc}",
            "no layout is reported for data items",
        )
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        index.setdefault(str(item["name"]).upper(), []).append(item)
    index[_UNRESOLVED_KEY] = [{"line": line} for line in computed["unresolved"]]
    return index


#: Not a COBOL name (it has a space), so it cannot collide with an item.
_UNRESOLVED_KEY = " unresolved"


def _layout_caveats(
    item: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
    response: Response,
) -> None:
    """Carry the layout's ``unresolved`` lines about *item*'s record."""
    record = str(item.get("qualified_name") or "").split(".")[0]
    for entry in layout.get(_UNRESOLVED_KEY, []):
        line = str(entry["line"])
        if line.split(":", 1)[0].split(".")[0] == record:
            response.caveat(
                "incomplete-analysis", line, _unresolved_layout_effect(line)
            )


#: A cap no record reaches: :func:`_renames_records` filters first, caps after.
_UNCAPPED = 1 << 30


def _renames_records(
    unit: CobolProgram,
    wanted: str,
    parsed: ParsedProgram,
    response: Response,
    cap: int,
) -> list[dict[str, Any]]:
    """``record_layout`` answers for the level-66 RENAMES items named
    *wanted* (#563): the byte range ``data-items`` places each at, within
    the record it renames, with that record's fields lying in the range.
    """
    name = wanted.split(" OF ")[0].strip()
    layout = _layout_index(unit, response)
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(
        e for e in layout.get(name, []) if e.get("level") == 66
    ):
        root_name = str(entry.get("parent_qualified_name") or "")
        roots = [f for f in _data_items_named(unit, root_name) if f.item is f.root]
        if len(roots) != 1:
            continue
        found = roots[0]
        # Every field of the record (no cap yet): the range picks from them.
        rows = _layout_answer(
            found,
            _record_layout(found.root, response),
            parsed,
            response,
            _UNCAPPED,
            index,
        )["fields"]
        start = int(entry["byte_offset"])
        end = start + int(entry["byte_length"])
        covered = [
            row
            for row in rows
            if row.get("byte_offset") is not None
            and start <= int(row["byte_offset"])
            and int(row["byte_offset"]) + int(row.get("byte_length") or 0) <= end
        ]
        location = _renames_location(unit, name)
        record: dict[str, Any] = {
            "name": entry["name"],
            "qualified_name": entry["name"],
            "section": found.section,
            "level": 66,
            "renames": found.root.name,
            "declared_at": (
                parsed.locate(location.line, location.column, response)
                if location is not None
                else None
            ),
            "byte_offset": start,
            "byte_length": int(entry["byte_length"]),
        }
        for key in ("picture", "usage"):
            if entry.get(key) and not entry.get("is_group"):
                record[key] = entry[key]
        if entry.get("offset_ambiguous"):
            record["offset_ambiguous"] = True
        record["field_count"] = len(covered)
        record["fields"] = response.cap(covered, cap, f"records[{index}].fields")
        records.append(record)
    return records


def _renames_location(unit: CobolProgram, name: str) -> Any:
    """Where the level-66 RENAMES item *name* is declared, or None."""
    node = _renames_node(unit, name)
    return node.location if node is not None else None


def _renames_node(unit: CobolProgram, name: str) -> RenamesItem | None:
    """The level-66 RENAMES item *name* of *unit*, or None."""
    data_div = unit.data_division
    if data_div is None:
        return None
    for section in data_div.sections:
        if not isinstance(section, CobolSection):
            continue
        for node in section.children:
            if isinstance(node, RenamesItem) and node.name.upper() == name:
                return node
    return None


def _layout_for(
    name: str,
    xref_qualified: str | None,
    layout: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """The layout item an xref entry describes, or None when it is unclear.

    xref qualifies a duplicated name as ``AMT OF OUT-REC``; the layout as
    ``OUT-REC.AMT``. Every ``OF`` qualifier must be one of the item's
    ancestors.
    """
    candidates = layout.get(name.upper(), [])
    if xref_qualified:
        qualifiers = [
            q.strip().upper() for q in xref_qualified.upper().split(" OF ")[1:]
        ]
        candidates = [
            c
            for c in candidates
            if set(qualifiers)
            <= set(str(c.get("qualified_name", "")).upper().split(".")[:-1])
        ]
    return candidates[0] if len(candidates) == 1 else None
