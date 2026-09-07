"""Record views: the byte map a decoder reads one record through.

Everywhere else in this package a layout is a *sequence* -- a list of
:class:`~.layout.FieldSpec` whose widths, concatenated, are the record.  That
is all an encoder needs, because it is writing the bytes and therefore knows
where it is.  A *decoder* is handed bytes somebody else wrote and has to say
what each one means, which needs the two things the sequence leaves implicit:

* **Where each field starts.**  A running sum of
  :attr:`~.layout.FieldSpec.storage_size`, which is the same arithmetic
  :func:`.encoding.encode_record` does implicitly by concatenating.  Computing
  it from the same widths is what keeps a decoded offset and an encoded byte
  position from ever disagreeing.
* **Which layout the bytes are being read through.**  ``REDEFINES`` means one
  run of bytes has two or more meanings, and only the program knows which one
  applies to the record in front of you.  A generator can duck that (it picks
  one and writes it); a decoder cannot, so every redefinition becomes a
  *view* of its own that a caller can switch to.

So a :class:`RecordView` is one such reading: a name, the offset it starts at,
and its fields already placed.  :func:`build_record_views` returns the base
view (the record as declared, redefinitions excluded) plus one overlay per
``REDEFINES`` item anywhere in the tree, each rooted at the offset of the item
it redefines.

Every offset here is *record-relative*: the record root starts at byte 0.
That matches :mod:`.layout_offsets`, which reports the same numbers for the
``data-items`` subcommand -- both are arithmetic on :mod:`.storage`'s widths,
so a byte the layout map calls offset 12 is the byte the decoder reads there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models.data_items import CobolDataItem
from .layout import FieldSpec, flatten_record
from .options import DataGeneratorOptions

#: Levels that name no storage of their own: 66 RENAMES and 88 condition
#: names.  ``_flatten_into`` skips both, and the overlay scan has to skip
#: them for the same reason -- counting a level-88 as a sibling would move
#: every offset after it.
_NON_STORAGE_LEVELS = frozenset({66, 88})


@dataclass(frozen=True)
class PlacedField:
    """One field of a view, with the offset its bytes start at.

    Attributes:
        spec: The flattened field itself -- PICTURE, USAGE, digit counts,
            sign, subscripts, ODO controls.
        offset: Record-relative byte offset of this occurrence's first byte.
    """

    spec: FieldSpec
    offset: int

    @property
    def length(self) -> int:
        """Bytes this occurrence occupies -- :attr:`FieldSpec.storage_size`."""
        return self.spec.storage_size

    @property
    def end(self) -> int:
        """Offset one past this field's last byte."""
        return self.offset + self.length

    def to_dict(self) -> dict[str, Any]:
        """Serialise the placement (the field spec, plus where it sits)."""
        return {"offset": self.offset, "length": self.length, **self.spec.to_dict()}


@dataclass(frozen=True)
class RecordView:
    """One way of reading a record's bytes.

    Attributes:
        name: How a caller names this view.  The record's own name for the
            base view; the redefining item's qualified path for an overlay,
            so two redefinitions of the same name in different groups stay
            distinguishable.
        redefines: The item this view redefines, or ``None`` for the base
            view.
        offset: Record-relative byte offset the view starts at.  Always 0
            for the base view; the redefined item's own offset for an
            overlay.
        fields: The view's fields, in byte order, already placed.
        offset_ambiguous: True when something before this view makes its
            offset a guess rather than a fact -- an ``OCCURS ... DEPENDING
            ON`` table earlier in the record (whose real length is per-record
            data), or an enclosing ``OCCURS`` table (this view is reported at
            occurrence 1).  The bytes are still decoded; the caller is simply
            told not to trust the offset for every record.
    """

    name: str
    redefines: str | None
    offset: int
    fields: list[PlacedField]
    offset_ambiguous: bool = False

    @property
    def is_base(self) -> bool:
        """True for the record as declared, False for a redefinition."""
        return self.redefines is None

    @property
    def length(self) -> int:
        """Bytes the view covers, every occurrence present."""
        return sum(placed.length for placed in self.fields)

    @property
    def end(self) -> int:
        """Offset one past the view's last byte."""
        return self.offset + self.length

    def to_dict(self) -> dict[str, Any]:
        """Serialise the view and its placed fields."""
        return {
            "name": self.name,
            "redefines": self.redefines,
            "is_base": self.is_base,
            "offset": self.offset,
            "length": self.length,
            "offset_ambiguous": self.offset_ambiguous,
            "fields": [placed.to_dict() for placed in self.fields],
        }


@dataclass(frozen=True)
class RecordViews:
    """Every way of reading one record: the base layout plus its overlays.

    Attributes:
        record_name: The level-01/77 record these views describe.
        base: The record as declared, redefinitions excluded.  Its length is
            the record's own length -- the ``LRECL`` of a fixed-length file.
        overlays: One view per ``REDEFINES`` item found anywhere in the
            record, in source order.
        caveats: Reasons a view's offsets may not hold for every record.
            Reported rather than raised: the decode is still the best
            available answer, and a caller that surfaces these leaves the
            user better off than one that refuses.
    """

    record_name: str
    base: RecordView
    overlays: list[RecordView] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def views(self) -> list[RecordView]:
        """Base first, then every overlay -- the order a UI should list them."""
        return [self.base, *self.overlays]

    @property
    def framing_length(self) -> int:
        """Bytes one record of this layout occupies in a fixed-length file.

        :attr:`base`'s own length in every conforming case, and the number a
        decoder must cut records at.  They differ only for a ``REDEFINES``
        entry *wider* than what it redefines: standard COBOL forbids that
        below level 01 and IBM rejects it, but compilers that accept it grow
        the record to the widest member, and a decoder framing on the base
        length alone would then walk the file at the wrong stride and shred
        every record after the first.  Taking the maximum costs nothing when
        the layout is legal (no overlay can exceed the base) and is the only
        answer that reads such a file at all.  :attr:`caveats` says when this
        is in play; :mod:`.layout_offsets` reserves the same widest-member
        slot for ``data-items``.
        """
        return max([self.base.length, *(view.end for view in self.overlays)])

    @property
    def names(self) -> list[str]:
        """Every view name, in the same order as :attr:`views`."""
        return [view.name for view in self.views]

    def get(self, name: str | None) -> RecordView | None:
        """The view called *name*, or the base view when *name* is ``None``.

        Matching is case-insensitive and accepts either the view's full name
        (``CUST-REC.ADDR-DETAIL``) or the redefining item's own short name
        (``ADDR-DETAIL``), because that is what a user reading the copybook
        has in front of them.
        """
        if name is None:
            return self.base
        wanted = name.upper()
        for view in self.views:
            if view.name.upper() == wanted:
                return view
        for view in self.views:
            if view.name.rsplit(".", 1)[-1].upper() == wanted:
                return view
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise every view (used by ``decode --list-views``)."""
        return {
            "record_name": self.record_name,
            "record_length": self.base.length,
            "views": [view.to_dict() for view in self.views],
            "caveats": list(self.caveats),
        }


def build_record_views(
    record: CobolDataItem,
    options: DataGeneratorOptions | None = None,
) -> RecordViews:
    """Map *record* into its base view and one overlay per ``REDEFINES``.

    *options* are normalised through
    :meth:`~.options.DataGeneratorOptions.for_record_image` first: a byte map
    has to account for every byte, and the CSV-shaped defaults deliberately
    do not (FILLER skipped, OCCURS capped).  Passing generation options here
    is therefore safe -- they cannot silently produce a layout with holes in
    it.
    """
    opts = (options or DataGeneratorOptions()).for_record_image()
    base_specs = flatten_record(record, opts, ignore_root_redefines=True)
    base = RecordView(
        name=record.name,
        redefines=None,
        offset=0,
        fields=_place(base_specs, 0),
        # A DEPENDING ON table anywhere in the record puts every field after
        # it at an offset only that record's own counter decides. The base
        # view used to be built with this defaulted to False -- the flag
        # existed but only overlays could ever carry it -- so `--list-views`
        # reported a maximum-length guess as a fact, where `data-items`
        # reports byte_offset: null for the very same field.
        offset_ambiguous=any(spec.odo_controls for spec in base_specs),
    )
    overlays: list[RecordView] = []
    caveats: list[str] = []
    _scan_overlays(
        record,
        (record.name,),
        0,
        opts,
        overlays,
        ambiguous=False,
        in_table=False,
    )
    if any(view.offset_ambiguous for view in overlays):
        caveats.append(
            "these REDEFINES overlays sit inside or after a table whose "
            "length is per-record data, so their offsets hold for a record "
            "whose tables are full and may be too high otherwise: "
            + ", ".join(view.name for view in overlays if view.offset_ambiguous)
        )
    if base.offset_ambiguous:
        caveats.append(
            "this record has an OCCURS ... DEPENDING ON table, so every "
            "offset reported after it assumes a record whose tables are "
            "full; a decoded record's own offsets come from its counters"
        )
    oversized = [view for view in overlays if view.end > base.length]
    if oversized:
        caveats.append(
            "these REDEFINES entries are wider than the item they redefine, "
            "which COBOL does not permit below level 01: the record is read "
            "as the widest of them ("
            + str(max(view.end for view in oversized))
            + f" bytes, not {base.length}), and offsets after the "
            "redefined item are the base layout's own: "
            + ", ".join(view.name for view in oversized)
        )
    return RecordViews(
        record_name=record.name, base=base, overlays=overlays, caveats=caveats
    )


def _place(specs: list[FieldSpec], start: int) -> list[PlacedField]:
    """Give every spec its offset, by running sum from *start*.

    The same arithmetic :func:`.encoding.encode_record` performs implicitly
    when it concatenates each field's bytes, which is exactly why it is the
    right one: an offset computed any other way could drift from where the
    encoder actually put the field.
    """
    placed: list[PlacedField] = []
    offset = start
    for spec in specs:
        placed.append(PlacedField(spec=spec, offset=offset))
        offset += spec.storage_size
    return placed


def _storage_children(item: CobolDataItem) -> list[CobolDataItem]:
    """*item*'s children that occupy bytes, in source order."""
    return [
        child
        for child in item.children
        if isinstance(child, CobolDataItem) and child.level not in _NON_STORAGE_LEVELS
    ]


def _footprint(item: CobolDataItem, opts: DataGeneratorOptions) -> int:
    """Bytes *item* occupies, every occurrence of its own ``OCCURS`` included.

    Measured by flattening the subtree and summing the same widths the base
    view was built from, so a group's footprint and the sum of its fields'
    placements are the same number by construction rather than by agreement
    between two implementations.
    """
    return sum(
        spec.storage_size
        for spec in flatten_record(item, opts, ignore_root_redefines=True)
    )


def _scan_overlays(
    item: CobolDataItem,
    path: tuple[str, ...],
    start: int,
    opts: DataGeneratorOptions,
    out: list[RecordView],
    *,
    ambiguous: bool,
    in_table: bool,
) -> None:
    """Walk *item*'s children, emitting a view for every ``REDEFINES``.

    Mirrors :func:`.layout_offsets._layout_siblings`' slot bookkeeping: a run
    of siblings that redefine each other share one slot, the slot starts
    where its first (non-redefining) member starts, and the slot's footprint
    is its widest member.  What differs is the output -- placed
    :class:`FieldSpec` s rather than :class:`~.layout_offsets.LayoutItem` s --
    and that the walk continues *into* a redefining child, so a redefinition
    nested inside a redefinition gets a view of its own.
    """
    offset = start
    slot_start = start
    slot_footprint = 0
    trailing_odo = ambiguous

    for child in _storage_children(item):
        if not child.redefines:
            offset += slot_footprint
            slot_footprint = 0
            slot_start = offset

        occurs = child.occurs_clause
        if child.redefines:
            out.append(
                RecordView(
                    name=".".join((*path, child.name)),
                    redefines=child.redefines,
                    offset=slot_start,
                    fields=_place(
                        flatten_record(child, opts, ignore_root_redefines=True),
                        slot_start,
                    ),
                    offset_ambiguous=trailing_odo or in_table,
                )
            )
        _scan_overlays(
            child,
            (*path, child.name),
            slot_start,
            opts,
            out,
            ambiguous=trailing_odo,
            in_table=in_table or occurs is not None,
        )

        if occurs is not None and occurs.depending_on:
            # Everything after a DEPENDING ON table sits at an offset only
            # that record's own counter decides. The decoder resolves it per
            # record; a static view cannot, so say so rather than imply the
            # maximum-length offset is the only one.
            trailing_odo = True
        slot_footprint = max(slot_footprint, _footprint(child, opts))
