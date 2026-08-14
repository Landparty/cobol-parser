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


def _layout_item(
    item: CobolDataItem,
    path: tuple[str, ...],
    start_offset: int | None,
    ambiguous: bool,
    redefines_chain: list[str],
    out: list[LayoutItem],
) -> int:
    """Emit LayoutItems for *item* (and, recursively, its children) starting
    at *start_offset*. Returns this item's one-occurrence footprint in
    bytes, for the caller to compare against REDEFINES siblings / multiply
    by OCCURS.
    """
    item_path = (*path, item.name)
    qualified_name = ".".join(item_path)
    parent_qualified_name = ".".join(path) if path else None
    data_children = _direct_data_children(item)
    item_ambiguous = ambiguous or start_offset is None

    if data_children:
        one_occurrence_length = 0  # stub -- Task 3 replaces this branch with real recursion
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
            occurs=None,
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

    return one_occurrence_length


def compute_record_layout(record: CobolDataItem) -> list[LayoutItem]:
    """Flatten *record* (a 01/77 root) into offset-annotated LayoutItems,
    depth-first in source order, including group items and level-88s."""
    out: list[LayoutItem] = []
    data_children = _direct_data_children(record)

    if not data_children:
        # 77-level elementary item or 01-level elementary item
        record_length = _elementary_byte_length(record)
    else:
        offset = 0
        for child in data_children:
            length = _layout_item(child, (record.name,), offset, False, [], out)
            offset += length
        record_length = offset

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
