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

from dataclasses import dataclass
from typing import Any

from ...models.data_items import CobolDataItem, ConditionNameItem
from .layout import expand_condition_values


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
        }


def _direct_data_children(item: CobolDataItem) -> list[CobolDataItem]:
    return [c for c in item.children if isinstance(c, CobolDataItem)]


def _direct_condition_children(item: CobolDataItem) -> list[ConditionNameItem]:
    return [c for c in item.children if isinstance(c, ConditionNameItem)]


def _elementary_byte_length(item: CobolDataItem) -> int:
    """One occurrence's real storage byte length.

    Mirrors ``CobolDataItem.calculate_size()``'s USAGE rules exactly --
    that method is correct for elementary items (COMP-3/COMP/COMP-1/COMP-2
    sizing); this module only needs its own walk because
    ``calculate_size()``'s *group*-item branch never applies a group's own
    OCCURS multiplier (see Task 5 below).
    """
    if item.usage in ("POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER"):
        return 4
    picture = item.picture_clause
    base_size = (picture.size or 0) if picture else 0
    usage = (item.usage or "DISPLAY").upper()
    if usage in ("COMP-3", "PACKED-DECIMAL"):
        digits = picture.total_digits if picture else None
        if digits:
            base_size = (digits + 1) // 2 + ((digits + 1) % 2)
    elif usage in ("COMP", "COMP-4", "COMP-5", "COMPUTATIONAL-4", "COMPUTATIONAL-5"):
        digits = picture.total_digits if picture else None
        if digits:
            base_size = 2 if digits <= 4 else 4 if digits <= 9 else 8
    elif usage == "COMP-1":
        base_size = 4
    elif usage == "COMP-2":
        base_size = 8
    return base_size


def _occurs_dict(item: CobolDataItem) -> dict[str, int] | None:
    occurs = item.occurs_clause
    if occurs is None:
        return None
    return {"min": occurs.min_times or 0, "max": occurs.max_times or occurs.min_times or 0}


def _walk_redefines_chain(item: CobolDataItem, siblings_by_name: dict[str, CobolDataItem]) -> list[str]:
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
        redefines_chain = _walk_redefines_chain(child, siblings_by_name) if child.redefines else []
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
            is_ambiguous = True
            member_footprint = one_occurrence_length  # unknown multiplier -- reserve one occurrence only
        elif occurs is not None:
            member_footprint = one_occurrence_length * (occurs.max_times or occurs.min_times or 1)
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
    item_path = (*path, item.name)
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
        usage = None
    else:
        one_occurrence_length = _elementary_byte_length(item)
        picture = item.picture_clause.pattern if item.picture_clause else None
        usage = (item.usage or "DISPLAY").upper()

    out.append(
        LayoutItem(
            name=item.name,
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
        )
    )

    for cond in _direct_condition_children(item):
        out.append(
            LayoutItem(
                name=cond.name,
                qualified_name=f"{qualified_name}.{cond.name}",
                level=88,
                is_group=False,
                picture=None,
                usage=None,
                byte_offset=start_offset,
                byte_length=one_occurrence_length,
                offset_ambiguous=item_ambiguous,
                redefines_chain=[],
                occurs=None,
                condition_values=expand_condition_values(cond.values),
                parent_qualified_name=qualified_name,
            )
        )

    return one_occurrence_length, trailing_ambiguous


def compute_record_layout(record: CobolDataItem) -> list[LayoutItem]:
    """Flatten *record* (a 01/77 root) into offset-annotated LayoutItems,
    depth-first in source order, including group items and level-88s."""
    out: list[LayoutItem] = []
    data_children = _direct_data_children(record)

    if not data_children:
        # 77-level elementary item or 01-level elementary item -- the
        # record root represents itself, not an empty group, so it needs
        # its own elementary byte length rather than defaulting to 0.
        record_length = _elementary_byte_length(record)
    else:
        record_length, _ = _layout_siblings(data_children, (record.name,), 0, False, out)

    out.insert(
        0,
        LayoutItem(
            name=record.name,
            qualified_name=record.name,
            level=record.level,
            is_group=bool(data_children),
            picture=record.picture_clause.pattern if record.picture_clause else None,
            usage=(record.usage or "DISPLAY").upper() if record.picture_clause else None,
            byte_offset=0,
            byte_length=record_length,
            offset_ambiguous=False,
            redefines_chain=[],
            occurs=None,
            condition_values=[],
            parent_qualified_name=None,
        ),
    )
    return out
