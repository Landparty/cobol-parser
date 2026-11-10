"""Byte offset/length and REDEFINES-chain layout for one record.

Complements ``program_layout.py`` (name resolution) and ``layout.py``
(DISPLAY-form field flattening for data generation) with the byte-accurate
positional facts neither computes: cumulative record-relative byte offset,
multi-hop REDEFINES chains, and level-88 condition values attached to
their own entry (not merged across siblings, unlike ``layout.py``'s
``_condition_values``).

Offsets are record-relative: a 01/77 root always starts at byte 0, not at
its program-wide absolute memory position -- what a hover popup needs is
"field X is at offset 12 of record Y", not an absolute address.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .._storage import (
    BINARY_USAGES,
    FLOAT_USAGES,
    POINTER_USAGES,
    is_known_usage,
    storage_size,
)
from ..models.data_items import CobolDataItem, ConditionNameItem, RenamesItem
from ..models.program import CobolProgram, CobolSection
from .fields import (
    FieldCategory,
    _classify,
    condition_ranges,
    condition_values_exhaustive,
    expand_condition_values,
)

_SECTION_NAMES = ("FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE")


@dataclass
class LayoutItem:
    name: str
    qualified_name: str
    level: int
    is_group: bool
    picture: str | None
    usage: str | None
    byte_offset: int | None
    byte_length: int
    offset_ambiguous: bool
    redefines_chain: list[str]
    occurs: dict[str, int] | None
    condition_values: list[str]
    parent_qualified_name: str | None
    #: A level-88's ``THRU`` ranges as written, ``(from, to)``.
    #: ``condition_values`` lists a range only in part, so this is the one
    #: complete statement of what the condition admits.
    condition_ranges: list[tuple[str, str]] = field(default_factory=list)
    #: Whether ``condition_values`` is every value the condition admits. Not
    #: serialized: :func:`compute_program_data_items` turns a False into an
    #: ``unresolved`` entry instead.
    condition_values_complete: bool = True
    #: ``OCCURS UNBOUNDED``: no declared maximum, so ``occurs.max`` and the
    #: byte lengths are only what was sized. Not serialized:
    #: :func:`flag_record_layout` says it in ``unresolved`` instead (#311).
    occurs_unbounded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "level": self.level,
            "is_group": self.is_group,
            "picture": self.picture,
            "usage": self.usage,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
            "offset_ambiguous": self.offset_ambiguous,
            "redefines_chain": self.redefines_chain,
            "occurs": self.occurs,
            "condition_values": self.condition_values,
            "parent_qualified_name": self.parent_qualified_name,
            "condition_ranges": [
                {"from": low, "to": high} for low, high in self.condition_ranges
            ],
        }


def _direct_data_children(item: CobolDataItem) -> list[CobolDataItem]:
    # A level-77 item is, by COBOL's own level-number rules, always a
    # standalone record -- never legitimately subordinate to a group.
    # The parser's hierarchy builder nests purely by level-number
    # comparison though, so a 77 declared right after a record whose
    # deepest preceding item has a lower level number (e.g. a 05) ends
    # up as that item's AST child (77 > 5). Counting it as a real data
    # child here would misclassify its *parent* as a GROUP item and
    # discard the parent's own elementary PIC/length -- exclude it.
    return [c for c in item.children if isinstance(c, CobolDataItem) and c.level != 77]


def _direct_condition_children(item: CobolDataItem) -> list[ConditionNameItem]:
    return [c for c in item.children if isinstance(c, ConditionNameItem)]


def _is_numeric_field(item: CobolDataItem) -> bool:
    """An elementary numeric item; a group is alphanumeric whatever is in it."""
    if _direct_data_children(item):
        return False
    return _classify(item, item.picture_clause) is FieldCategory.NUMERIC


def _condition_item(
    cond: ConditionNameItem,
    parent: CobolDataItem,
    parent_qualified_name: str,
    byte_offset: int | None,
    byte_length: int,
    offset_ambiguous: bool,
) -> LayoutItem:
    """The LayoutItem for level-88 *cond* declared under *parent*."""
    ranges = condition_ranges(cond.values)
    decimal_digits = (
        (parent.picture_clause.decimal_digits or 0) if parent.picture_clause else 0
    )
    return LayoutItem(
        name=cond.name,
        qualified_name=f"{parent_qualified_name}.{cond.name}",
        level=88,
        is_group=False,
        picture=None,
        usage=None,
        byte_offset=byte_offset,
        byte_length=byte_length,
        offset_ambiguous=offset_ambiguous,
        redefines_chain=[],
        occurs=None,
        condition_values=expand_condition_values(cond.values),
        parent_qualified_name=parent_qualified_name,
        condition_ranges=ranges,
        # Only a THRU range makes the list partial here: a figurative
        # constant (VALUE SPACES) is listed as its word, which is the value.
        # A range over a non-numeric field is never enumerable: the parser
        # drops the quotes of '01' THRU '12', which then reads as an integer
        # range, but on PIC XX it also admits '1A' and excludes '1'.
        condition_values_complete=not ranges
        or (
            _is_numeric_field(parent)
            and condition_values_exhaustive(cond.values, decimal_digits)
        ),
    )


def _find_misnested_level_77_items(item: CobolDataItem) -> list[CobolDataItem]:
    """Recover level-77 items buried anywhere in *item*'s AST subtree.

    ``_direct_data_children`` excludes level-77 children at every nesting
    level so a misnested 77 can't corrupt its AST parent's own PIC/length
    (see that function's docstring). That guard alone makes the 77 vanish
    from the layout entirely whenever it was its parent's *only* child --
    the parent looks childless and the 77 is never visited by anything
    else. Walk the raw (unfiltered) child tree to find every such 77 so
    the caller can re-root each one as its own independent top-level
    record instead of silently dropping it.
    """
    found: list[CobolDataItem] = []
    for child in item.children:
        if isinstance(child, CobolDataItem):
            if child.level == 77:
                found.append(child)
            else:
                found.extend(_find_misnested_level_77_items(child))
    return found


def elementary_byte_length(item: CobolDataItem) -> int:
    """One occurrence's real storage byte length.

    Delegates to :func:`.storage.storage_size`, which is the package's one
    authority on the question -- a record image built by :mod:`.encoding`
    and the offsets reported here are then arithmetic on the same widths,
    and cannot disagree.  Two cases this module used to get wrong on its
    own, both now fixed by that shared implementation: ``USAGE INDEX`` (no
    PICTURE, so it was sized as zero bytes and silently collapsed every
    following offset) and DISPLAY ``SIGN IS SEPARATE`` (a byte the PICTURE
    does not count).
    """
    picture = item.picture_clause
    return storage_size(
        item.usage,
        picture_size=picture.size if picture else None,
        total_digits=picture.total_digits if picture else None,
        sign_clause=item.sign_clause,
        is_signed=bool(picture and picture.is_signed),
        national_picture=bool(picture and picture.is_national),
    )


def _occurs_dict(item: CobolDataItem) -> dict[str, int] | None:
    occurs = item.occurs_clause
    if occurs is None:
        return None
    return {
        "min": occurs.min_times or 0,
        "max": occurs.max_times or occurs.min_times or 0,
    }


def _walk_redefines_chain(
    item: CobolDataItem, siblings_by_name: dict[str, CobolDataItem]
) -> list[str]:
    chain: list[str] = []
    seen: set[str] = set()
    target = item.redefines
    while target:
        upper = target.upper()
        if upper in seen:
            break  # malformed source with a cycle -- don't hang
        seen.add(upper)
        chain.append(target)
        sibling = siblings_by_name.get(upper)
        target = sibling.redefines if sibling else None
    return chain


def _layout_siblings(
    children: list[CobolDataItem],
    path: tuple[str, ...],
    start_offset: int | None,
    ambiguous: bool,
    out: list[LayoutItem],
) -> tuple[int, bool]:
    """Lay out one sibling list (a record's direct children, or one
    group's direct children) starting at *start_offset*. Returns a
    ``(footprint, trailing_ambiguous)`` pair: *footprint* is the total
    footprint consumed (for the caller -- a group item, or the synthetic
    record root -- to report as its own byte_length); *trailing_ambiguous*
    reports whether this sibling list ended in an ambiguous state (either
    because it started ambiguous, one of its own direct children carries
    OCCURS ... DEPENDING ON, or a nested group child's own children went
    ambiguous). The caller (one level up, itself a ``_layout_siblings``
    loop) uses that to flag everything *after* the offending group child
    as offset_ambiguous too -- ambiguity inside a nested group must
    propagate to the group's own siblings, not stay trapped at that
    nesting level.
    """
    siblings_by_name = {c.name.upper(): c for c in children}
    offset = start_offset
    total = 0
    slot_start = offset
    slot_footprint = 0  # replaces slot_max_length -- now OCCURS-aware per member
    is_ambiguous = ambiguous

    def close_slot() -> None:
        nonlocal offset, total, slot_footprint
        total += slot_footprint
        if offset is not None:
            offset += slot_footprint
        slot_footprint = 0

    for child in children:
        if not child.redefines:
            close_slot()
            slot_start = offset

        child_ambiguous = is_ambiguous or slot_start is None
        redefines_chain = (
            _walk_redefines_chain(child, siblings_by_name) if child.redefines else []
        )
        one_occurrence_length, child_trailing_ambiguous = _layout_item(
            child,
            path,
            None if child_ambiguous else slot_start,
            child_ambiguous,
            redefines_chain,
            out,
        )

        occurs = child.occurs_clause
        if occurs is not None and occurs.depending_on:
            # Everything after the table moves with its counter, but its
            # own footprint is the MAXIMUM: what IBM Enterprise COBOL
            # allocates for an ODO group and what ``encoding.py`` writes
            # (``storage.py``'s widths times every occurrence), so a
            # group's and a record's byte_length agree with the encoder.
            is_ambiguous = True
        if occurs is not None:
            member_footprint = one_occurrence_length * (
                occurs.max_times or occurs.min_times or 1
            )
        else:
            member_footprint = one_occurrence_length

        if child_trailing_ambiguous:
            # A nested group child's own children carried an ODO table
            # somewhere inside -- everything after this child in THIS
            # sibling list is now offset-ambiguous too, even though the
            # group child itself still had a known starting offset.
            is_ambiguous = True

        slot_footprint = max(slot_footprint, member_footprint)

    close_slot()
    return total, is_ambiguous


def _layout_item(
    item: CobolDataItem,
    path: tuple[str, ...],
    start_offset: int | None,
    ambiguous: bool,
    redefines_chain: list[str],
    out: list[LayoutItem],
) -> tuple[int, bool]:
    """Emit LayoutItems for *item* (and, recursively, its children) starting
    at *start_offset*. Returns a ``(footprint, trailing_ambiguous)`` pair:
    *footprint* is this item's one-occurrence footprint in bytes, for the
    caller to compare against REDEFINES siblings / multiply by OCCURS.
    *trailing_ambiguous* is only ever True for a group item whose own
    nested ``_layout_siblings`` call ended ambiguous (e.g. an OCCURS ...
    DEPENDING ON table among its own children) -- it lets the CALLING
    sibling list know that this child, despite starting at a known
    offset itself, leaves everything after it ambiguous. Elementary
    items always report False here: a directly-attached DEPENDING ON is
    already handled by the caller's own check on ``occurs_clause``.
    """
    item_path = (*path, item.layout_name)
    qualified_name = ".".join(item_path)
    parent_qualified_name = ".".join(path) if path else None
    data_children = _direct_data_children(item)
    item_ambiguous = ambiguous or start_offset is None
    trailing_ambiguous = False

    if data_children:
        one_occurrence_length, trailing_ambiguous = _layout_siblings(
            data_children, item_path, start_offset, item_ambiguous, out
        )
        picture = None
        usage = item.usage.upper() if item.usage else None
    else:
        one_occurrence_length = elementary_byte_length(item)
        picture = item.picture_clause.pattern if item.picture_clause else None
        usage = (item.usage or "DISPLAY").upper()

    out.append(
        LayoutItem(
            name=item.layout_name,
            qualified_name=qualified_name,
            level=item.level,
            is_group=bool(data_children),
            picture=picture,
            usage=usage,
            byte_offset=start_offset,
            byte_length=one_occurrence_length,
            offset_ambiguous=item_ambiguous,
            redefines_chain=redefines_chain,
            occurs=_occurs_dict(item),
            condition_values=[],
            parent_qualified_name=parent_qualified_name,
            occurs_unbounded=bool(
                item.occurs_clause is not None and item.occurs_clause.is_unbounded
            ),
        )
    )

    for cond in _direct_condition_children(item):
        out.append(
            _condition_item(
                cond,
                item,
                qualified_name,
                start_offset,
                one_occurrence_length,
                item_ambiguous,
            )
        )

    return one_occurrence_length, trailing_ambiguous


def compute_record_layout(record: CobolDataItem) -> list[LayoutItem]:
    """Flatten *record* (a 01/77 root) into offset-annotated LayoutItems,
    group items and level-88s included.

    The root comes first, then its level-88s; below it, depth first, each
    group comes *after* its members (its length is their footprint), with
    its own level-88s right after it. Callers rely on that order:
    ``FieldFlowAnalyzer`` finds an entry's enclosing group as the next
    entry of the parent's name, which tells same-named groups apart.
    """
    out: list[LayoutItem] = []
    data_children = _direct_data_children(record)

    if not data_children:
        # 77-level elementary item or 01-level elementary item -- the
        # record root represents itself, not an empty group, so it needs
        # its own elementary byte length rather than defaulting to 0.
        record_length = elementary_byte_length(record)
    else:
        record_length, _ = _layout_siblings(
            data_children, (record.name,), 0, False, out
        )

    out.insert(
        0,
        LayoutItem(
            name=record.name,
            qualified_name=record.name,
            level=record.level,
            is_group=bool(data_children),
            picture=record.picture_clause.pattern if record.picture_clause else None,
            # Mirror _layout_item: an elementary root always has a usage
            # (defaulting to DISPLAY) — gating on PICTURE presence nulled the
            # usage of PIC-less USAGE-only roots (77 X USAGE COMP-1.) whose
            # byte length was itself derived from that very usage.
            usage=(
                (record.usage.upper() if record.usage else None)
                if data_children
                else (record.usage or "DISPLAY").upper()
            ),
            byte_offset=0,
            byte_length=record_length,
            offset_ambiguous=False,
            redefines_chain=[],
            occurs=None,
            condition_values=[],
            parent_qualified_name=None,
        ),
    )

    # The record root bypasses _layout_item's own construction path (it
    # has this separate inline path above), so it also bypasses that
    # function's condition-children loop. Without this, a level-88
    # declared directly under a 01/77 record root (COBOL's most common
    # flag idiom) would be silently dropped -- mirror _layout_item's
    # condition-children loop here for the root itself.
    root_conditions = [
        _condition_item(cond, record, record.name, 0, record_length, False)
        for cond in _direct_condition_children(record)
    ]
    out[1:1] = root_conditions
    return out


def _alignment(item: CobolDataItem) -> int:
    """The boundary a ``SYNCHRONIZED`` *item* is aligned on, or 0 when
    SYNCHRONIZED has no effect on it (DISPLAY, packed decimal, a group).
    Binary, floating-point, pointer and index items align on their own
    width: 2, 4 or 8 bytes."""
    if not item.synchronized or _direct_data_children(item):
        return 0
    usage = (item.usage or "DISPLAY").upper()
    if usage in BINARY_USAGES or usage in FLOAT_USAGES:
        return elementary_byte_length(item)
    if usage == "INDEX" or usage in POINTER_USAGES:
        return elementary_byte_length(item)
    return 0


def _first_unaligned_sync(
    record: CobolDataItem, offsets: dict[str, int | None]
) -> tuple[str, list[str]] | None:
    """The first ``SYNCHRONIZED`` item in *record* (source order) whose
    alignment this module cannot vouch for, plus every item's qualified name
    from it to the end of the record in source order.

    ``SYNCHRONIZED`` slack bytes are not modelled (by the record encoder
    either -- see ``encoding.py``), so an aligned item that already sits on
    its boundary is harmless, but one that does not -- or that sits inside
    an OCCURS table, where slack can also fall *between* occurrences --
    shifts itself and everything after it by bytes these offsets omit.
    """
    order: list[tuple[str, CobolDataItem, bool]] = []

    def walk(item: CobolDataItem, path: tuple[str, ...], in_table: bool) -> None:
        item_path = (*path, item.layout_name)
        in_table = in_table or item.occurs_clause is not None
        order.append((".".join(item_path), item, in_table))
        for child in _direct_data_children(item):
            walk(child, item_path, in_table)

    walk(record, (), False)
    for index, (name, item, in_table) in enumerate(order):
        boundary = _alignment(item)
        if not boundary:
            continue
        offset = offsets.get(name)
        if in_table or offset is None or offset % boundary:
            return name, [later for later, _, _ in order[index:]]
    return None


def compute_program_data_items(ast: CobolProgram) -> dict[str, Any]:
    """Compute layout facts for every top-level (01/77) record in every
    DATA DIVISION section of *ast*. Record-relative offsets -- see the
    module docstring.

    Unlike ``compute_record_layout`` (which lays out one record in
    isolation, with no knowledge of its section siblings), this function
    also resolves top-level REDEFINES chains: a 01-item that redefines
    another 01-item in the same section has its own record root's
    ``redefines_chain`` corrected here after the fact, since
    ``compute_record_layout`` always hardcodes an empty chain for the
    record root (top-level REDEFINES was out of scope for that function --
    it only walks REDEFINES among the record's own nested children, via
    ``_layout_siblings``'s own ``siblings_by_name``, built from *that
    group's* children, not the section's top-level records).
    """
    items: list[dict[str, Any]] = []
    unresolved: list[str] = []
    data_div = ast.get_division("DATA")
    if data_div is None:
        return {"items": items, "unresolved": unresolved}

    for canonical in _SECTION_NAMES:
        section = data_div.get_section_by_name(canonical)
        if not isinstance(section, CobolSection):
            continue
        records = [r for r in section.data_items if isinstance(r, CobolDataItem)]
        siblings_by_name = {r.name.upper(): r for r in records}
        placed: list[tuple[CobolDataItem, list[dict[str, Any]]]] = []
        for record in records:
            record_layout = compute_record_layout(record)
            if record.redefines:
                record_layout[0].redefines_chain = _walk_redefines_chain(
                    record, siblings_by_name
                )
            unresolved.extend(flag_record_layout(record, record_layout))
            record_items = [layout_item.to_dict() for layout_item in record_layout]
            placed.append((record, record_items))
            items.extend(record_items)

            for misnested in _find_misnested_level_77_items(record):
                misnested_layout = compute_record_layout(misnested)
                if misnested.redefines:
                    misnested_layout[0].redefines_chain = _walk_redefines_chain(
                        misnested, siblings_by_name
                    )
                _flag_partial_condition_values(misnested_layout, unresolved)
                for layout_item in misnested_layout:
                    items.append(layout_item.to_dict())

        for node in section.children:
            if isinstance(node, RenamesItem):
                entry = renames_layout(node, placed)
                if entry is None:
                    unresolved.append(
                        f"{node.name.upper()}: the RENAMES range "
                        f"{_renames_text(node)} could not be placed"
                    )
                else:
                    items.append(entry)

    return {"items": items, "unresolved": unresolved}


def _renames_text(node: RenamesItem) -> str:
    """``A THRU B`` as the RENAMES clause names it."""
    text = " OF ".join([node.renames_from, *node.renames_from_qualifiers])
    if node.renames_through:
        through = " OF ".join([node.renames_through, *node.renames_through_qualifiers])
        text += f" THRU {through}"
    return text


def renames_layout(
    node: RenamesItem,
    placed: list[tuple[CobolDataItem, list[dict[str, Any]]]],
) -> dict[str, Any] | None:
    """The ``data-items`` entry of a level-66 RENAMES item, or None when the
    bytes it renames cannot be placed (#563).

    A RENAMES regroups a contiguous run of the record just before it: from
    the start of its first operand to the end of its THRU operand. *placed*
    is each record of the section with its layout entries, in source order;
    the operands are looked up in the last record declared before *node*
    (an ``OF`` qualifier must name an ancestor). A single-operand RENAMES
    takes the renamed item's description (PICTURE, USAGE, group-ness).
    """
    line = getattr(node.location, "line", None)
    before = [
        (record, layout)
        for record, layout in placed
        if line is None or (getattr(record.location, "line", 0) or 0) < line
    ]
    if not before:
        return None
    record, layout = before[-1]

    def find(name: str, qualifiers: list[str]) -> dict[str, Any] | None:
        wanted = {q.upper() for q in qualifiers}
        matches = [
            entry
            for entry in layout
            if str(entry["name"]).upper() == name.upper()
            and wanted <= set(str(entry["qualified_name"]).upper().split(".")[:-1])
            and entry["level"] != 88
        ]
        return matches[0] if len(matches) == 1 else None

    first = find(node.renames_from, node.renames_from_qualifiers)
    if first is None:
        return None
    last: dict[str, Any] | None = first
    if node.renames_through:
        last = find(node.renames_through, node.renames_through_qualifiers)
    if last is None:
        return None
    start, end_at = first["byte_offset"], last["byte_offset"]
    if start is None or end_at is None:
        return None
    length = int(end_at) + int(last["byte_length"] or 0) - int(start)
    if length <= 0:
        return None
    single = last is first
    root = record.name.upper()
    return {
        "name": node.name,
        "qualified_name": f"{root}.{node.name.upper()}",
        "level": 66,
        "is_group": bool(first["is_group"]) if single else True,
        "picture": first["picture"] if single else None,
        "usage": first["usage"] if single else "DISPLAY",
        "byte_offset": int(start),
        "byte_length": length,
        "offset_ambiguous": bool(first["offset_ambiguous"] or last["offset_ambiguous"]),
        "redefines_chain": [],
        "occurs": None,
        "condition_values": [],
        "parent_qualified_name": root,
        "condition_ranges": [],
    }


def flag_record_layout(record: CobolDataItem, layout: list[LayoutItem]) -> list[str]:
    """What :func:`compute_record_layout`'s *layout* of *record* cannot vouch
    for, as ``unresolved`` lines -- marking the offsets a ``SYNCHRONIZED``
    item's slack bytes could shift ``offset_ambiguous`` on the way.

    :func:`compute_program_data_items` runs it on every record; a caller
    laying out one record on its own (MCP ``record_layout``) must run it too,
    or its offsets read as exact when they are short by the slack (#488).
    """
    unresolved: list[str] = []
    _flag_sync_slack(record, layout, unresolved)
    _flag_unknown_usage(layout, unresolved)
    _flag_partial_condition_values(layout, unresolved)
    _flag_unbounded_occurs(layout, unresolved)
    return unresolved


def _flag_unbounded_occurs(layout: list[LayoutItem], unresolved: list[str]) -> None:
    """Say in *unresolved* which tables are ``OCCURS UNBOUNDED``: with no
    declared maximum they are sized at their minimum, so ``occurs.max`` and
    the byte length of the table and of every group holding it are a lower
    bound, not the definite figures they otherwise read as (#311)."""
    for entry in layout:
        if not entry.occurs_unbounded:
            continue
        times = entry.occurs["max"] if entry.occurs else 1
        unresolved.append(
            f"{entry.qualified_name}: OCCURS UNBOUNDED has no maximum; sized "
            f"as {times} occurrence(s), so its occurs.max and the byte_length "
            "of every group holding it are a lower bound"
        )


def _flag_unknown_usage(layout: list[LayoutItem], unresolved: list[str]) -> None:
    """A USAGE word nothing here can size (``USAGE IS COMPX``) leaves its
    item's length a guess: mark it and every later offset in the record
    ``offset_ambiguous`` and say so, rather than a quiet 0-byte item (#524)."""
    for entry in layout:
        if entry.level == 88 or is_known_usage(entry.usage):
            continue
        for other in layout:
            if other is entry or (other.byte_offset or 0) > (entry.byte_offset or 0):
                other.offset_ambiguous = True
        unresolved.append(
            f"{entry.qualified_name}: USAGE {entry.usage} is not supported; its "
            "byte length is unknown, so it and every later offset in the record "
            "may be wrong"
        )


def _flag_partial_condition_values(
    layout: list[LayoutItem], unresolved: list[str]
) -> None:
    """Say in *unresolved* which level-88s list only part of their values --
    without it, a reader of ``condition_values`` takes 66 or 'M' to be
    outside ``VALUE 1 THRU 99999`` or ``VALUE 'A' THRU 'Z'``."""
    for entry in layout:
        if entry.condition_values_complete:
            continue
        spans = ", ".join(f"{low} THRU {high}" for low, high in entry.condition_ranges)
        unresolved.append(
            f"{entry.qualified_name}: condition_values lists only part of "
            f"VALUE {spans}; condition_ranges holds the full range"
        )


def _flag_sync_slack(
    record: CobolDataItem, layout: list[LayoutItem], unresolved: list[str]
) -> None:
    """Mark every offset a ``SYNCHRONIZED`` item's slack bytes could shift
    as ``offset_ambiguous``, and say why in *unresolved* -- a quiet report
    of confident offsets that are short by the slack would be wrong."""
    offsets = {entry.qualified_name: entry.byte_offset for entry in layout}
    found = _first_unaligned_sync(record, offsets)
    if found is None:
        return
    first, affected = found
    shifted = set(affected)
    for entry in layout:
        base = (
            entry.parent_qualified_name
            if entry.level == 88 and entry.parent_qualified_name
            else entry.qualified_name
        )
        if base in shifted:
            entry.offset_ambiguous = True
    unresolved.append(
        f"{first}: SYNCHRONIZED alignment is not modelled; its offset and "
        "every later one in the record may be short by slack bytes"
    )
