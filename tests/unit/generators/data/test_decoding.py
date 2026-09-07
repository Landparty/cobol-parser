"""Record decoding: real storage bytes -> the values behind them.

The load-bearing property is the round trip. ``encoding.py``'s own expected
bytes are ground truth from GnuCOBOL (see ``test_encoding.py``'s module
docstring), so a decoder that reproduces the generated CSV from those bytes
is verified against a real compiler at one remove -- which is worth far more
than any table of expected values written here by hand. The hand-written
cases below are for the things a round trip *cannot* reach: sign
conventions this module reads but never writes, bytes that are not what the
PICTURE says, short records, and a copybook pointed at the wrong file.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.copybook import (
    CopybookDataGenerator,
    parse_copybook_records,
)
from cobolparser.generators.data.decoding import (
    RecordDecoder,
    RecordDecodingError,
    decode_record,
    decoded_hex_dump,
)
from cobolparser.generators.data.encoding import (
    Charset,
    EncodingOptions,
    Endian,
    RecordFormat,
)
from cobolparser.generators.data.layout import present_indexes
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.data.views import build_record_views

EVERY_USAGE = """
       01  WIDE-REC.
           05  W-ID        PIC 9(6).
           05  W-NAME      PIC X(20).
           05  W-PACKED    PIC S9(7)V99 COMP-3.
           05  W-BINARY    PIC S9(4) COMP.
           05  W-BIG       PIC S9(9) COMP-4.
           05  W-ZONED     PIC S9(5).
           05  W-SEPARATE  PIC S9(5) SIGN IS LEADING SEPARATE.
           05  W-SCALED    PIC S9(4)V99.
           05  W-DOUBLE    COMP-2.
           05  FILLER      PIC XX.
"""

OVERLAID = """
       01  CUST-REC.
           05  CUST-ID     PIC 9(6).
           05  ADDR-HOME.
               10  HOME-STREET PIC X(9).
               10  HOME-ZIP    PIC 9(5).
           05  ADDR-OVERSEAS REDEFINES ADDR-HOME.
               10  OS-COUNTRY  PIC X(4).
               10  OS-LINE     PIC X(10).
"""

ODO = """
       01  ORDER-REC.
           05  ORD-ID      PIC 9(5).
           05  ORD-COUNT   PIC 9(2).
           05  ORD-LINE OCCURS 1 TO 6 TIMES DEPENDING ON ORD-COUNT.
               10  LINE-SKU PIC X(6).
               10  LINE-QTY PIC S9(3) COMP-3.
           05  ORD-TOTAL   PIC S9(7)V99 COMP-3.
"""

SMALL = """
       01  SMALL-REC.
           05  S-CODE      PIC X(3).
           05  S-AMT       PIC S9(3)V99 COMP-3.
"""


def _dataset(source: str, *, rows: int = 5, **kwargs):
    options = DataGeneratorOptions(rows=rows, seed=13, **kwargs).for_record_image()
    return CopybookDataGenerator(options).generate_from_source(source)


def _decoder(source: str, opts: EncodingOptions, **kwargs) -> RecordDecoder:
    return RecordDecoder.from_copybook_source(source, opts=opts, **kwargs)


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


#: The one column of EVERY_USAGE that does not round-trip *as text*: a float
#: is rendered in shortest form on the way back, so the generator's
#: ``2675.6950`` reads as ``2675.695``. The number is identical; only the
#: trailing zero the generator's own ``%.4f`` added is gone, and inventing it
#: back would mean claiming a precision the bytes do not carry.
_FLOAT_COLUMN = "W-DOUBLE"

#: FILLER is the other one, and by the encoder's own deliberate choice: it
#: writes spaces rather than whatever the value generator put in a FILLER
#: cell, because FILLER names nothing a program reads. So the bytes really
#: do not carry the generated value, and a decoder that produced it anyway
#: would be inventing it.
_DISCARDED_COLUMN = "FILLER"


def _compare_row(decoded: list[str], expected: list[str], columns: list[str]):
    for value, cell, column in zip(decoded, expected, columns, strict=True):
        if column.startswith(_DISCARDED_COLUMN):
            assert value == ""
        elif column == _FLOAT_COLUMN:
            assert float(value) == pytest.approx(float(cell))
        else:
            assert value == cell


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_every_usage_round_trips(charset):
    """decode(encode(row)) == row, for every storage class in one record."""
    dataset = _dataset(EVERY_USAGE)
    opts = EncodingOptions(charset=charset)
    result = _decoder(EVERY_USAGE, opts).decode_bytes(dataset.to_records(opts))

    assert len(result.records) == len(dataset.rows)
    assert result.error_count == 0
    assert result.trailing == b""
    columns = dataset.header
    for record, row in zip(result.records, dataset.rows, strict=True):
        _compare_row([f.value for f in record.fields], row, columns)


def test_the_decoder_and_the_generator_agree_on_column_names():
    """A decoded table has to be addressable the same way a generated one is."""
    dataset = _dataset(EVERY_USAGE)
    opts = EncodingOptions(charset=Charset.EBCDIC)
    result = _decoder(EVERY_USAGE, opts).decode_bytes(dataset.to_records(opts))
    assert result.header == dataset.header


def test_round_trip_reproduces_the_generated_csv_byte_for_byte():
    """The two halves render values identically, or the table a decoder
    shows would not be the table the generator wrote."""
    dataset = _dataset(ODO, rows=3)
    opts = EncodingOptions(charset=Charset.EBCDIC)
    result = _decoder(ODO, opts).decode_bytes(dataset.to_records(opts))
    assert result.to_csv() == dataset.to_csv()


@pytest.mark.parametrize(
    "record_format",
    [RecordFormat.FIXED, RecordFormat.VARIABLE, RecordFormat.VARIABLE_BARE],
)
def test_depending_on_tables_round_trip_under_every_record_format(record_format):
    dataset = _dataset(ODO)
    opts = EncodingOptions(charset=Charset.EBCDIC, record_format=record_format)
    result = _decoder(ODO, opts).decode_bytes(dataset.to_records(opts))

    assert len(result.records) == len(dataset.rows)
    assert result.trailing == b""
    for decoded, row in zip(result.records, dataset.rows, strict=True):
        if record_format is RecordFormat.FIXED:
            # RECFM=F reserves every occurrence, so every field is there.
            assert [f.value for f in decoded.fields] == row
            continue
        present = set(present_indexes(dataset.fields, row))
        for index, (field, cell) in enumerate(zip(decoded.fields, row, strict=True)):
            if index in present:
                assert field.value == cell
                assert field.present
            else:
                assert field.value == ""
                assert not field.present


def test_a_variable_record_reports_its_rdw():
    dataset = _dataset(ODO)
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    result = _decoder(ODO, opts).decode_bytes(dataset.to_records(opts))
    for record in result.records:
        assert record.rdw is not None
        assert int.from_bytes(record.rdw[:2], "big") == record.length
        assert record.rdw[2:] == b"\x00\x00"


def test_a_record_separator_is_consumed_between_records():
    dataset = _dataset(SMALL)
    opts = EncodingOptions(record_separator=b"\n")
    result = _decoder(SMALL, opts).decode_bytes(dataset.to_records(opts))
    assert len(result.records) == len(dataset.rows)
    assert result.trailing == b""


# ---------------------------------------------------------------------------
# REDEFINES: one set of bytes, two readings
# ---------------------------------------------------------------------------


def test_an_overlay_reads_the_same_bytes_differently():
    dataset = _dataset(OVERLAID)
    opts = EncodingOptions()
    raw = dataset.to_records(opts)
    decoder = _decoder(OVERLAID, opts)

    base = decoder.decode_bytes(raw)
    overlay = decoder.decode_bytes(raw, view="ADDR-OVERSEAS")

    assert base.header == ["CUST-ID", "HOME-STREET", "HOME-ZIP"]
    assert overlay.header == ["OS-COUNTRY", "OS-LINE"]
    assert len(overlay.records) == len(base.records)
    for base_record, overlay_record in zip(base.records, overlay.records, strict=True):
        # The values differ (one reading is two text fields, the other a
        # street and a zip), but they must come from exactly the same bytes.
        home = b"".join(f.raw for f in base_record.fields[1:])
        away = b"".join(f.raw for f in overlay_record.fields)
        assert home == away
        assert overlay_record.fields[0].offset == 6


def test_framing_uses_the_base_record_length_whatever_the_view():
    """A 20-byte record read through a 14-byte overlay is still 20 bytes."""
    dataset = _dataset(OVERLAID)
    opts = EncodingOptions()
    decoder = _decoder(OVERLAID, opts)
    result = decoder.decode_bytes(dataset.to_records(opts), view="ADDR-OVERSEAS")
    assert len(result.records) == len(dataset.rows)
    assert {r.length for r in result.records} == {dataset.record_length()}
    assert result.trailing == b""


def test_an_unknown_view_names_the_ones_that_exist():
    decoder = _decoder(OVERLAID, EncodingOptions())
    with pytest.raises(RecordDecodingError) as excinfo:
        decoder.decode_bytes(b"", view="NO-SUCH-VIEW")
    assert "ADDR-OVERSEAS" in str(excinfo.value)


def test_the_view_list_is_reported_on_every_result():
    decoder = _decoder(OVERLAID, EncodingOptions())
    result = decoder.decode_bytes(b"")
    assert result.views == ["CUST-REC", "CUST-REC.ADDR-OVERSEAS"]
    assert result.view == "CUST-REC"


# ---------------------------------------------------------------------------
# Sign conventions this module reads but does not write
# ---------------------------------------------------------------------------


def _one_field(source: str, raw: bytes, opts: EncodingOptions):
    view = build_record_views(parse_copybook_records(source)[0]).base
    return decode_record(view, raw, opts)[0]


SIGNED_ZONED = "       01  R.\n           05  N PIC S9(3).\n"


@pytest.mark.parametrize(
    ("charset", "raw", "expected"),
    [
        # EBCDIC: C is positive, D negative, F unsigned -- what a compiler
        # writes.  A and B are the architecture's alternates, which older
        # compilers and assembler do emit.
        (Charset.EBCDIC, b"\xf1\xf2\xc3", "123"),
        (Charset.EBCDIC, b"\xf1\xf2\xd3", "-123"),
        (Charset.EBCDIC, b"\xf1\xf2\xf3", "123"),
        (Charset.EBCDIC, b"\xf1\xf2\xb3", "-123"),
        (Charset.EBCDIC, b"\xf1\xf2\xa3", "123"),
        # ASCII as GnuCOBOL writes it: 0x40 set in the signed digit's zone.
        (Charset.ASCII, b"12s", "-123"),
        (Charset.ASCII, b"123", "123"),
        # ASCII an EBCDIC file turns into when a transfer transcodes it:
        # `C` is +3, `L` is -3.
        (Charset.ASCII, b"12C", "123"),
        (Charset.ASCII, b"12L", "-123"),
    ],
)
def test_zoned_sign_conventions(charset, raw, expected):
    field = _one_field(SIGNED_ZONED, raw, EncodingOptions(charset=charset))
    assert field.value == expected
    assert field.error is None


def test_a_sign_zone_outside_the_sign_position_is_an_error_not_a_negation():
    field = _one_field(
        SIGNED_ZONED, b"\xd1\xf2\xf3", EncodingOptions(charset=Charset.EBCDIC)
    )
    assert field.value == "123"  # not "-123"
    assert field.error is not None and "sign zone" in field.error


# ---------------------------------------------------------------------------
# Bytes that are not what the PICTURE says
# ---------------------------------------------------------------------------


def test_a_bad_packed_sign_nibble_is_reported_with_a_best_effort_value():
    source = "       01  R.\n           05  P PIC S9(3) COMP-3.\n"
    field = _one_field(source, b"\x12\x35", EncodingOptions())
    assert field.value == "123"
    assert field.error is not None and "sign nibble" in field.error


def test_a_non_digit_packed_nibble_is_reported():
    source = "       01  R.\n           05  P PIC S9(3) COMP-3.\n"
    field = _one_field(source, b"\x1a\x3c", EncodingOptions())
    assert field.error is not None and "not a digit" in field.error


def test_spaces_in_a_numeric_field_are_reported_rather_than_read_as_zero():
    field = _one_field(
        SIGNED_ZONED, b"\x40\x40\x40", EncodingOptions(charset=Charset.EBCDIC)
    )
    assert field.value == "0"
    assert field.error is not None and "space" in field.error


def test_the_wrong_copybook_shows_up_as_a_wall_of_errors():
    """The single most useful thing the decoder can tell you."""
    dataset = _dataset(EVERY_USAGE)
    ebcdic = EncodingOptions(charset=Charset.EBCDIC)
    raw = dataset.to_records(ebcdic)
    # Same bytes, read as if they were ASCII: the zoned and packed fields
    # cannot possibly be valid.
    result = _decoder(EVERY_USAGE, EncodingOptions()).decode_bytes(raw)
    assert result.error_count > 0


# ---------------------------------------------------------------------------
# Short records and paging
# ---------------------------------------------------------------------------


def test_a_short_final_record_is_reported_as_trailing_bytes():
    dataset = _dataset(SMALL)
    opts = EncodingOptions()
    raw = dataset.to_records(opts) + b"\xf1\xf2"
    result = _decoder(SMALL, opts).decode_bytes(raw)
    assert len(result.records) == len(dataset.rows)
    assert result.trailing == b"\xf1\xf2"


def test_a_record_cut_mid_field_decodes_what_was_there():
    source = "       01  R.\n           05  A PIC X(4).\n           05  B PIC X(4).\n"
    view = build_record_views(parse_copybook_records(source)[0]).base
    fields = decode_record(view, b"ABCDEF", EncodingOptions())
    assert fields[0].value == "ABCD"
    assert fields[1].value == "EF"
    assert fields[1].truncated is True
    assert fields[1].length == 2


def test_a_field_past_the_end_is_absent_rather_than_missing():
    source = "       01  R.\n           05  A PIC X(4).\n           05  B PIC X(4).\n"
    view = build_record_views(parse_copybook_records(source)[0]).base
    fields = decode_record(view, b"ABCD", EncodingOptions())
    assert len(fields) == 2  # the column is still there, for a stable table
    assert fields[1].present is False
    assert fields[1].value == ""


def test_max_records_and_skip_page_through_a_file():
    dataset = _dataset(SMALL)
    opts = EncodingOptions()
    raw = dataset.to_records(opts)
    decoder = _decoder(SMALL, opts)

    page = decoder.decode_bytes(raw, skip=1, max_records=2)
    assert [r.index for r in page.records] == [1, 2]
    assert [[f.value for f in r.fields] for r in page.records] == dataset.rows[1:3]
    # Bytes left because a page was asked for, not because the file is broken.
    assert page.trailing == b""


def test_an_explicit_record_length_cuts_records_with_trailing_slack():
    dataset = _dataset(SMALL)
    opts = EncodingOptions()
    padded = b"".join(
        dataset.to_records(opts)[i : i + dataset.record_length()] + b"\x00\x00\x00"
        for i in range(0, len(dataset.to_records(opts)), dataset.record_length())
    )
    decoder = _decoder(SMALL, opts, record_length=dataset.record_length() + 3)
    result = decoder.decode_bytes(padded)
    assert len(result.records) == len(dataset.rows)
    assert result.trailing == b""
    assert [[f.value for f in r.fields] for r in result.records] == dataset.rows


def test_an_rdw_longer_than_the_file_is_refused_rather_than_guessed_at():
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    decoder = _decoder(SMALL, opts)
    with pytest.raises(RecordDecodingError) as excinfo:
        decoder.decode_bytes(b"\xff\xff\x00\x00abc")
    assert "RDW" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------


def test_json_carries_offset_length_and_raw_bytes_per_field():
    dataset = _dataset(SMALL)
    opts = EncodingOptions()
    result = _decoder(SMALL, opts).decode_bytes(dataset.to_records(opts), max_records=1)
    data = result.to_dict()
    assert data["record_count"] == 1
    field = data["records"][0]["fields"][0]
    assert field["offset"] == 0
    assert field["length"] == 3
    assert len(field["hex"].split()) == 3
    assert field["picture"] == "X(3)"


def test_the_hex_pane_lines_up_with_the_field_boundaries():
    dataset = _dataset(SMALL)
    opts = EncodingOptions(charset=Charset.EBCDIC)
    result = _decoder(SMALL, opts).decode_bytes(dataset.to_records(opts), max_records=1)
    dump = decoded_hex_dump(result, opts)
    assert "S-CODE" in dump and "S-AMT" in dump
    assert "* view: SMALL-REC" in dump
    # The COMP-3 field's own bytes, at its own offset.
    amount = result.records[0].fields[1]
    assert amount.hex in dump
    assert f"{amount.offset:06X}" in dump


def test_comp_1_is_flagged_as_not_round_tripping():
    source = "       01  R.\n           05  F COMP-1.\n"
    decoder = _decoder(source, EncodingOptions())
    result = decoder.decode_bytes(b"\x00\x00\x00\x00")
    assert any("COMP-1" in caveat for caveat in result.caveats)


def test_index_and_pointer_decode_to_hex_not_to_a_number():
    source = "       01  R.\n           05  I USAGE INDEX.\n"
    field = _one_field(source, b"\x00\x00\x00\x07", EncodingOptions())
    assert field.value == "0x00000007"


def test_values_and_value_lookups():
    dataset = _dataset(SMALL)
    opts = EncodingOptions()
    result = _decoder(SMALL, opts).decode_bytes(dataset.to_records(opts), max_records=1)
    record = result.records[0]
    assert record.values()["S-CODE"] == dataset.rows[0][0]
    assert record.value("s-code") == dataset.rows[0][0]
    assert record.value("SMALL-REC.S-AMT") == dataset.rows[0][1]
    assert record.value("NOT-A-FIELD") is None


def test_decode_file_reads_binary(tmp_path):
    dataset = _dataset(SMALL)
    opts = EncodingOptions(charset=Charset.EBCDIC)
    path = tmp_path / "SMALL.DAT"
    dataset.write_records(path, opts)
    copybook = tmp_path / "SMALL.cpy"
    copybook.write_text(SMALL, encoding="utf-8")

    decoder = RecordDecoder.from_copybook_file(copybook, opts=opts)
    result = decoder.decode_file(path)
    assert [[f.value for f in r.fields] for r in result.records] == dataset.rows


def test_the_endian_option_reaches_comp_5():
    source = "       01  R.\n           05  N PIC S9(9) COMP-5.\n"
    big = _one_field(source, b"\x00\x00\x01\x00", EncodingOptions(endian=Endian.BIG))
    little = _one_field(
        source, b"\x00\x00\x01\x00", EncodingOptions(endian=Endian.LITTLE)
    )
    assert big.value == "256"
    assert little.value == "65536"
