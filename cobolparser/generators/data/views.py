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

So a :class:`RecordView` is one such reading: a name and its fields already
placed.  :func:`build_record_views` returns the base view (the record as
declared, redefinitions excluded) plus one overlay view per ``REDEFINES`` item
anywhere in the tree.  An overlay view is the *whole record* with that one
redefinition swapped in for the item it redefines (and, for a redefinition
nested inside another, the enclosing one swapped in too).  Two things follow
from reading the whole record rather than the overlay's bytes alone: a field
outside the redefined area -- a record key -- is still there to compare on,
and an overlay inside an ``OCCURS`` table is read at every occurrence, the
same way the base view reads the item it redefines.

Every offset here is *record-relative*: the record root starts at byte 0.
That matches :mod:`.layout_offsets`, which reports the same numbers for the
``data-items`` subcommand -- both are arithmetic on :mod:`.storage`'s widths,
so a byte the layout map calls offset 12 is the byte the decoder reads there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ...models.data_items import CobolDataItem
from .layout import (
    FieldSpec,
    HiddenCounter,
    flatten_overlay_view,
    flatten_record,
    occurs_expansion_caveats,
)
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
        offset: Record-relative byte offset the redefinition starts at --
            its first occurrence, when it sits inside a table.  Always 0
            for the base view.  The view's *fields* always start at 0: an
            overlay view is the whole record with the overlay swapped in.
        fields: The view's fields, in byte order, already placed.
        offset_ambiguous: True when an ``OCCURS ... DEPENDING ON`` table
            (whose real length is per-record data) makes this view's static
            offsets a guess for any record whose table is not full: for the
            base view, any such table in the record; for an overlay, one
            before or inside the overlay itself.  The decoder resolves those
            per record; the caller is simply told not to trust the listed
            offsets for every record.
        overlay_length: Bytes the redefinition itself covers (one
            occurrence); the base view's own length for the base view.
        hidden_counters: ``DEPENDING ON`` counters the overlay covers up.
            They are not fields of the view, but their tables still take
            their length from them, so the decoder reads them anyway.
    """

    name: str
    redefines: str | None
    offset: int
    fields: list[PlacedField]
    offset_ambiguous: bool = False
    overlay_length: int | None = None
    hidden_counters: tuple[HiddenCounter, ...] = ()
    #: True when this overlay (or one it is nested in) is wider than what it
    #: redefines, so the view is longer than the base record.
    widens: bool = False

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
        return self.fields[-1].end if self.fields else 0

    @property
    def overlay_end(self) -> int:
        """Offset one past the redefinition's own last byte (first occurrence)."""
        span = self.length if self.overlay_length is None else self.overlay_length
        return self.offset + span

    def to_dict(self) -> dict[str, Any]:
        """Serialise the view and its placed fields."""
        return {
            "name": self.name,
            "redefines": self.redefines,
            "is_base": self.is_base,
            "offset": self.offset,
            "length": self.length,
            "overlay_length": (
                self.length if self.overlay_length is None else self.overlay_length
            ),
            "offset_ambiguous": self.offset_ambiguous,
            "fields": [placed.to_dict() for placed in self.fields],
        }


class _LazyOverlayView(RecordView):
    """An overlay view whose fields are flattened on first use.

    Each overlay view is the whole record flattened again, so a layout with
    many overlays inside a large table would pay for every one of them up
    front even though a decode reads through just one.  Everything a
    :class:`RecordViews` needs without the fields -- name, offset, the
    ambiguity flag, whether the overlay grows the record -- is set eagerly;
    ``fields`` and ``hidden_counters`` are built the first time either is
    read, and then kept.
    """

    def __init__(
        self,
        name: str,
        redefines: str | None,
        offset: int,
        fields: list[PlacedField] | None = None,
        offset_ambiguous: bool = False,
        overlay_length: int | None = None,
        hidden_counters: tuple[HiddenCounter, ...] = (),
        widens: bool = False,
        *,
        build: (
            Callable[[], tuple[list[PlacedField], tuple[HiddenCounter, ...]]] | None
        ) = None,
    ) -> None:
        # The positional parameters mirror RecordView's own fields, so
        # dataclasses.replace() -- which passes every field back in -- still
        # works: it hands over the already-built fields and no builder.
        for attr, value in (
            ("name", name),
            ("redefines", redefines),
            ("offset", offset),
            ("offset_ambiguous", offset_ambiguous),
            ("overlay_length", overlay_length),
            ("widens", widens),
            ("_build", build),
            ("_built", None if build is not None else (fields or [], hidden_counters)),
        ):
            object.__setattr__(self, attr, value)

    def _materialize(self) -> tuple[list[PlacedField], tuple[HiddenCounter, ...]]:
        built: tuple[list[PlacedField], tuple[HiddenCounter, ...]] | None
        built = self.__dict__["_built"]
        if built is None:
            built = self.__dict__["_build"]()
            object.__setattr__(self, "_built", built)
        assert built is not None
        return built

    @property
    def fields(self) -> list[PlacedField]:
        return self._materialize()[0]

    @property
    def hidden_counters(self) -> tuple[HiddenCounter, ...]:
        return self._materialize()[1]


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

        :meth:`to_dict` (and therefore ``decode --list-views``) reports this
        alongside ``record_length`` rather than in place of it, so a consumer
        reading the serialized form frames records on the same number
        :class:`~.decoding.RecordDecoder` does.
        """
        # `end`, not `overlay_end`: an overlay view is the whole record, and
        # with a wider overlay swapped in the fields after it move along --
        # which is where data-items puts them too -- so the record is that
        # view's full length.
        return max(
            [self.base.length, *(view.end for view in self.overlays if view.widens)]
        )

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
        """Serialise every view (used by ``decode --list-views``).

        Carries **both** lengths, and they are not always the same number.
        ``record_length`` is the base view's own span -- the record as
        declared.  ``framing_length`` is the stride a fixed-length file is
        actually cut at, which is larger exactly when an overlay is wider
        than what it redefines (see :attr:`framing_length`).  Reporting only
        the first would leave a consumer framing records on a number the
        decoder itself does not use, which is the very mismatch
        :attr:`framing_length` exists to remove; :attr:`caveats` names the
        offending overlays whenever the two differ.
        """
        return {
            "record_name": self.record_name,
            "record_length": self.base.length,
            "framing_length": self.framing_length,
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
    # A table the expansion caps cut short leaves the view shorter than the
    # record it maps: every offset after it is wrong for a real file (#376).
    caveats: list[str] = occurs_expansion_caveats(record, opts)
    base_columns = {_column_key(spec): spec.column for spec in base_specs}
    first_odo = next((p.offset for p in base.fields if p.spec.odo_controls), None)
    _scan_overlays(
        record,
        record,
        (record.name,),
        0,
        opts,
        overlays,
        chain={},
        base_columns=base_columns,
        path_style=opts.header_style == "path",
        first_odo=first_odo,
        widened=False,
    )
    if any(view.offset_ambiguous for view in overlays):
        caveats.append(
            "these REDEFINES overlays are read through a record with a table "
            "whose length is per-record data, so their listed offsets hold "
            "for a record whose tables are full and may be too high "
            "otherwise: "
            + ", ".join(view.name for view in overlays if view.offset_ambiguous)
        )
    if base.offset_ambiguous:
        caveats.append(
            "this record has an OCCURS ... DEPENDING ON table, so every "
            "offset reported after it assumes a record whose tables are "
            "full; a decoded record's own offsets come from its counters"
        )
    oversized = [view for view in overlays if view.widens]
    if oversized:
        caveats.append(
            "these REDEFINES entries are wider than the item they redefine, "
            "which COBOL does not permit below level 01: the record is read "
            "as the widest of them ("
            + str(max(view.end for view in oversized))
            + f" bytes, not {base.length}). Read through one of them, the "
            "fields after it sit past the wider entry, where a compiler that "
            "accepts it puts them; the base view still reads them at the "
            "declared offsets: " + ", ".join(view.name for view in oversized)
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


def _scan_overlays(
    record: CobolDataItem,
    item: CobolDataItem,
    path: tuple[str, ...],
    start: int,
    opts: DataGeneratorOptions,
    out: list[RecordView],
    *,
    chain: dict[int, CobolDataItem],
    base_columns: dict[tuple[tuple[str, ...], tuple[int, ...]], str],
    path_style: bool,
    first_odo: int | None,
    widened: bool,
) -> None:
    """Walk *item*'s children, emitting a view for every ``REDEFINES``.

    Mirrors :func:`.layout_offsets._layout_siblings`' slot bookkeeping: a run
    of siblings that redefine each other share one slot, the slot starts
    where its first (non-redefining) member starts, and the slot's footprint
    is its widest member.  Each view is the whole *record* flattened with
    the redefinition swapped in for the slot's first member -- plus every
    enclosing redefinition already in *chain*, so a redefinition nested
    inside another is read through both.  *start* (and so
    :attr:`RecordView.offset`) is the first occurrence's offset; the fields
    themselves are placed at every occurrence by the flattening.
    """
    offset = start
    slot_start = start
    slot_item: CobolDataItem | None = None
    slot_footprint = 0
    slot_target = 0

    for child in _storage_children(item):
        if not child.redefines:
            offset += slot_footprint
            slot_footprint = 0
            slot_start = offset
            slot_item = child

        child_chain = chain
        child_widened = widened
        child_specs = flatten_record(child, opts, ignore_root_redefines=True)
        child_footprint = sum(spec.storage_size for spec in child_specs)
        if child.redefines:
            # Ambiguous when a DEPENDING ON table sits before the overlay's
            # end -- before it in the record, or inside it -- since only
            # then does a short table move the overlay's own bytes.
            ambiguous = any(spec.odo_controls for spec in child_specs) or (
                first_odo is not None and first_odo < slot_start + child_footprint
            )
            if slot_item is not None:
                child_chain = {**chain, id(slot_item): child}
                child_widened = widened or child_footprint > slot_target
                out.append(
                    _LazyOverlayView(
                        name=".".join((*path, child.name)),
                        redefines=child.redefines,
                        offset=slot_start,
                        offset_ambiguous=ambiguous,
                        overlay_length=child_footprint,
                        widens=child_widened,
                        build=partial(
                            _build_overlay,
                            record,
                            child_chain,
                            opts,
                            base_columns,
                            path_style,
                        ),
                    )
                )
            else:
                # A REDEFINES with nothing before it to redefine: no slot to
                # swap it into, so the view is the overlay's own bytes.
                out.append(
                    RecordView(
                        name=".".join((*path, child.name)),
                        redefines=child.redefines,
                        offset=slot_start,
                        fields=_place(child_specs, slot_start),
                        offset_ambiguous=ambiguous,
                        overlay_length=child_footprint,
                    )
                )
        else:
            slot_target = child_footprint
        _scan_overlays(
            record,
            child,
            (*path, child.name),
            slot_start,
            opts,
            out,
            chain=child_chain,
            base_columns=base_columns,
            path_style=path_style,
            first_odo=first_odo,
            widened=child_widened,
        )
        slot_footprint = max(slot_footprint, child_footprint)


def _build_overlay(
    record: CobolDataItem,
    substitutions: dict[int, CobolDataItem],
    opts: DataGeneratorOptions,
    base_columns: dict[tuple[tuple[str, ...], tuple[int, ...]], str],
    path_style: bool,
) -> tuple[list[PlacedField], tuple[HiddenCounter, ...]]:
    """Flatten *record* with *substitutions* swapped in, and place it."""
    specs, hidden = flatten_overlay_view(record, substitutions, opts)
    _align_columns(specs, base_columns, path_style=path_style)
    return _place(specs, 0), tuple(hidden)


def _column_key(spec: FieldSpec) -> tuple[tuple[str, ...], tuple[int, ...]]:
    return (spec.path, spec.subscripts)


def _align_columns(
    specs: list[FieldSpec],
    base_columns: dict[tuple[tuple[str, ...], tuple[int, ...]], str],
    *,
    path_style: bool,
) -> None:
    """Give an overlay view's fields the base view's column names.

    A field outside the overlay is the same field in both views, so it keeps
    the same header -- otherwise an overlay that happens to declare a name
    the base also uses (``AMT``) would qualify *both* (``R.A.AMT``) in its
    own view, and ``compare --view ... --key AMT`` would stop finding the
    key.  The overlay's own fields keep their short name unless that is
    taken, then the qualified path, then a numeric suffix -- the same
    fallbacks :func:`.layout._assign_columns` uses.
    """
    keyed = [(spec, base_columns.get(_column_key(spec))) for spec in specs]
    used = {column for _, column in keyed if column is not None}
    for spec, known in keyed:
        if known is not None:
            spec.column = known
            continue
        suffix = (
            "(" + ",".join(str(s) for s in spec.subscripts) + ")"
            if spec.subscripts
            else ""
        )
        column = (spec.qualified_name if path_style else spec.name) + suffix
        if column in used:
            column = spec.qualified_name + suffix
        base = column
        n = 2
        while column in used:
            column = f"{base}_{n}"
            n += 1
        used.add(column)
        spec.column = column
