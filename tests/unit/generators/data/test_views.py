"""Record views: the offset-annotated byte map a decoder reads through.

The invariant every test here is really defending is that a view's offsets
are the *encoder's* offsets. ``build_record_views`` and
``encoding.encode_record`` compute them from the same ``storage_size``
widths, so a field the map calls offset 26 has to be the byte the encoder
put it at -- see ``test_base_offsets_match_the_encoded_record``, which
checks that against real bytes rather than against a second hand-written
table of numbers.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.encoding import (
    EncodingOptions,
    encode_field,
    record_length,
)
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.data.views import build_record_views

FLAT = """
       01  CUST-REC.
           05  CUST-ID         PIC 9(6).
           05  CUST-NAME       PIC X(20).
           05  CUST-BAL        PIC S9(7)V99 COMP-3.
"""

OVERLAID = """
       01  CUST-REC.
           05  CUST-ID         PIC 9(6).
           05  ADDR-HOME.
               10  HOME-STREET PIC X(15).
               10  HOME-ZIP    PIC 9(5).
           05  ADDR-OVERSEAS REDEFINES ADDR-HOME.
               10  OS-COUNTRY  PIC X(4).
               10  OS-LINE     PIC X(16).
           05  CUST-FLAG       PIC X.
"""

NESTED = """
       01  MSG-REC.
           05  MSG-KIND        PIC X.
           05  MSG-BODY        PIC X(30).
           05  MSG-ORDER REDEFINES MSG-BODY.
               10  ORD-NUM     PIC 9(8).
               10  ORD-REST    PIC X(22).
           05  MSG-SHIP REDEFINES MSG-BODY.
               10  SHIP-CODE   PIC X(3).
               10  SHIP-REST   PIC X(27).
"""

TABLE = """
       01  ORDER-REC.
           05  ORD-COUNT       PIC 9(2).
           05  ORD-LINE OCCURS 1 TO 5 TIMES DEPENDING ON ORD-COUNT.
               10  LINE-SKU    PIC X(6).
           05  ORD-TAIL        PIC X(4).
           05  ORD-TAIL-ALT REDEFINES ORD-TAIL.
               10  TAIL-A      PIC XX.
               10  TAIL-B      PIC XX.
"""


def _views(source: str):
    record = parse_copybook_records(source)[0]
    return build_record_views(record, DataGeneratorOptions())


def test_base_view_places_every_field_at_a_running_offset():
    views = _views(FLAT)
    assert views.base.is_base
    assert views.base.offset == 0
    assert [(p.spec.column, p.offset, p.length) for p in views.base.fields] == [
        ("CUST-ID", 0, 6),
        ("CUST-NAME", 6, 20),
        ("CUST-BAL", 26, 5),
    ]
    assert views.base.length == 31


def test_base_offsets_match_the_encoded_record():
    """The offsets are the encoder's own, not a second implementation."""
    views = _views(OVERLAID)
    opts = EncodingOptions()
    cells = {
        "CUST-ID": "123456",
        "HOME-STREET": "1 MAIN ST",
        "HOME-ZIP": "90210",
        "CUST-FLAG": "Y",
    }
    raw = b"".join(
        encode_field(p.spec, cells.get(p.spec.column, ""), opts)
        for p in views.base.fields
    )
    for placed in views.base.fields:
        expected = encode_field(placed.spec, cells.get(placed.spec.column, ""), opts)
        assert raw[placed.offset : placed.end] == expected


def test_redefines_becomes_an_overlay_at_the_redefined_offset():
    views = _views(OVERLAID)
    assert views.names == ["CUST-REC", "CUST-REC.ADDR-OVERSEAS"]
    overlay = views.overlays[0]
    assert overlay.redefines == "ADDR-HOME"
    assert overlay.is_base is False
    # ADDR-HOME starts right after the 6-byte id, and so does its overlay.
    assert overlay.offset == 6
    assert [(p.spec.column, p.offset) for p in overlay.fields] == [
        ("OS-COUNTRY", 6),
        ("OS-LINE", 10),
    ]


def test_the_overlay_does_not_move_the_fields_after_it():
    """A redefinition aliases bytes; it does not add any."""
    views = _views(OVERLAID)
    flag = next(p for p in views.base.fields if p.spec.column == "CUST-FLAG")
    assert flag.offset == 26  # 6 + 20, not 6 + 20 + 20
    assert views.base.length == record_length([p.spec for p in views.base.fields])


def test_two_redefinitions_of_one_item_are_two_views():
    views = _views(NESTED)
    assert views.names == ["MSG-REC", "MSG-REC.MSG-ORDER", "MSG-REC.MSG-SHIP"]
    assert [v.offset for v in views.overlays] == [1, 1]
    assert [v.length for v in views.overlays] == [30, 30]


def test_get_accepts_the_short_name_and_the_qualified_one():
    views = _views(NESTED)
    assert views.get("MSG-SHIP") is views.overlays[1]
    assert views.get("MSG-REC.MSG-SHIP") is views.overlays[1]
    assert views.get("msg-ship") is views.overlays[1]
    assert views.get(None) is views.base
    assert views.get("NOPE") is None


def test_an_overlay_after_a_depending_on_table_is_flagged_ambiguous():
    views = _views(TABLE)
    overlay = views.overlays[0]
    assert overlay.offset_ambiguous is True
    assert any("offsets hold for a record" in c for c in views.caveats)


def test_to_dict_round_trips_the_placements():
    views = _views(OVERLAID)
    data = views.to_dict()
    assert data["record_name"] == "CUST-REC"
    assert data["record_length"] == views.base.length
    overlay = data["views"][1]
    assert overlay["redefines"] == "ADDR-HOME"
    assert overlay["fields"][0]["offset"] == 6
    assert overlay["fields"][0]["length"] == 4
    # The spec's own keys are carried through alongside the placement.
    assert overlay["fields"][0]["picture"] == "X(4)"


@pytest.mark.parametrize("source", [FLAT, OVERLAID, NESTED, TABLE])
def test_every_view_is_contiguous(source):
    """No gaps and no overlaps inside a single view -- that is what makes
    the decoder able to walk it with one running position."""
    for view in _views(source).views:
        offset = view.offset
        for placed in view.fields:
            assert placed.offset == offset
            offset += placed.length
        assert offset == view.end
