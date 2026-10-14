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
    encode_record,
)
from cobolparser.generators.data.layout import flatten_record, present_indexes
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


#: FILLER is the one column of EVERY_USAGE that does not round-trip, and by
#: the encoder's own deliberate choice: it
#: writes spaces rather than whatever the value generator put in a FILLER
#: cell, because FILLER names nothing a program reads. So the bytes really
#: do not carry the generated value, and a decoder that produced it anyway
#: would be inventing it.
_DISCARDED_COLUMN = "FILLER"


def _compare_row(decoded: list[str], expected: list[str], columns: list[str]):
    for value, cell, column in zip(decoded, expected, columns, strict=True):
        if column.startswith(_DISCARDED_COLUMN):
            assert value == ""
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


BINARY_ODO = """
       01  R.
           05  N PIC S9(4) COMP.
           05  T OCCURS 0 TO 3 DEPENDING ON N.
               10  X PIC X(2).
           05  K PIC S9(4) COMP.
"""


def test_variable_bare_newline_frames_by_layout_not_by_a_0a_in_the_data():
    # K = 10 is 0x000A: a newline byte *inside* the record.  Splitting on the
    # first separator cut the first record there and misread the rest.
    opts = EncodingOptions(
        record_format=RecordFormat.VARIABLE_BARE, record_separator=b"\n"
    )
    decoder = _decoder(BINARY_ODO, opts)
    specs = [placed.spec for placed in decoder.views.base.fields]
    rows = [["1", "ab", "", "", "10"], ["2", "cd", "ef", "", "266"]]
    data = b"".join(encode_record(specs, row, opts) + b"\n" for row in rows)
    result = decoder.decode_bytes(data)
    assert result.trailing == b""
    present = [
        {f.name: f.value for f in record.fields if f.present}
        for record in result.records
    ]
    assert present == [
        {"N": "1", "X(1)": "ab", "K": "10"},
        {"N": "2", "X(1)": "cd", "X(2)": "ef", "K": "266"},
    ]
    assert all(not r.errors for r in result.records)


def test_variable_bare_newline_falls_back_to_the_separator_for_short_lines():
    # Text lines that do not fill the layout: the separator is all there is.
    opts = EncodingOptions(
        record_format=RecordFormat.VARIABLE_BARE, record_separator=b"\n"
    )
    source = "       01  R.\n           05  A PIC X(5).\n"
    result = _decoder(source, opts).decode_bytes(b"ab\ncd\n")
    assert [r.fields[0].value for r in result.records] == ["ab", "cd"]


def test_an_odo_counter_outside_an_enclosing_fixed_table_is_found_by_name():
    source = """
       01  R.
           05  N PIC 9.
           05  T OCCURS 2.
               10  U OCCURS 1 TO 3 DEPENDING ON N.
                   15  Z PIC X.
"""
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    decoder = _decoder(source, opts)
    specs = [placed.spec for placed in decoder.views.base.fields]
    row = ["1", "a", "b", "c", "d", "e", "f"]
    data = encode_record(specs, row, opts)
    record = decoder.decode_bytes(data).records[0]
    present = {f.name: f.value for f in record.fields if f.present}
    # One occurrence of U under each of T's two: what the encoder wrote.
    assert present == {"N": "1", "Z(1,1)": "a", "Z(2,1)": "d"}
    assert record.errors == []


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_blank_when_zero_reads_spaces_as_zero(charset):
    source = (
        "       01  R.\n"
        "           05  D PIC 9(3) BLANK WHEN ZERO.\n"
        "           05  E PIC ZZ9.99 BLANK WHEN ZERO.\n"
    )
    opts = EncodingOptions(charset=charset)
    decoder = _decoder(source, opts)
    specs = [placed.spec for placed in decoder.views.base.fields]
    for row in (["0", "0.00"], ["12", "3.50"]):
        data = encode_record(specs, row, opts)
        record = decoder.decode_bytes(data).records[0]
        assert [f.value for f in record.fields] == row
        assert record.errors == []


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_justified_right_round_trips_and_is_right_aligned(charset):
    source = (
        "       01  R.\n"
        "           05  J PIC X(8) JUSTIFIED RIGHT.\n"
        "           05  K PIC X(4).\n"
    )
    opts = EncodingOptions(charset=charset)
    decoder = _decoder(source, opts)
    specs = [placed.spec for placed in decoder.views.base.fields]
    data = encode_record(specs, ["AB", "CD"], opts)
    space = bytes([opts.space])
    assert data[:8] == space * 6 + "AB".encode(
        "cp037" if opts.space == 0x40 else "ascii"
    )
    record = decoder.decode_bytes(data).records[0]
    assert [f.value for f in record.fields] == ["AB", "CD"]
    assert record.errors == []


def test_a_thirty_one_digit_packed_field_decodes_exactly():
    # ARITH(EXTEND): 31 digits, more than Decimal's default 28-digit context,
    # which used to read this back as ...456790.00.
    field = _one_field(
        "       01  R.\n           05  F PIC S9(29)V99 COMP-3.\n",
        bytes.fromhex("1234567890123456789012345678901d"),
        EncodingOptions(),
    )
    assert field.value == "-12345678901234567890123456789.01"
    assert field.error is None


def test_without_blank_when_zero_spaces_are_still_an_error():
    field = _one_field(
        "       01  R.\n           05  D PIC 9(3).\n", b"   ", EncodingOptions()
    )
    assert field.error is not None


def test_national_data_is_caveated_on_decode():
    source = "       01  R.\n           05  N1 PIC N(2).\n"
    result = _decoder(source, EncodingOptions()).decode_bytes(b"ab  ")
    assert any("UTF-16" in caveat for caveat in result.caveats)


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
    # The whole record, with the overlay swapped in for ADDR-HOME (#296).
    assert overlay.header == ["CUST-ID", "OS-COUNTRY", "OS-LINE"]
    assert len(overlay.records) == len(base.records)
    for base_record, overlay_record in zip(base.records, overlay.records, strict=True):
        # The values differ (one reading is two text fields, the other a
        # street and a zip), but they must come from exactly the same bytes.
        home = b"".join(f.raw for f in base_record.fields[1:])
        away = b"".join(f.raw for f in overlay_record.fields[1:])
        assert home == away
        assert overlay_record.fields[0].raw == base_record.fields[0].raw
        assert overlay_record.fields[1].offset == 6


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


def test_a_non_zero_packed_pad_nibble_is_reported_not_read_as_a_digit():
    # An even digit count leaves the first byte's high nibble as pad. Reading
    # it as a digit made PIC S9(2)V99 hold 123.45, which it cannot.
    source = "       01  R.\n           05  P PIC S9(2)V99 COMP-3.\n"
    field = _one_field(source, bytes.fromhex("12345c"), EncodingOptions())
    assert field.value == "23.45"
    assert field.error is not None and "pad nibble" in field.error
    clean = _one_field(source, bytes.fromhex("01234d"), EncodingOptions())
    assert (clean.value, clean.error) == ("-12.34", None)


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


@pytest.mark.parametrize(
    "tail",
    [
        b"\xf0\xf0\xf1",  # cut inside ORD-ID
        # ORD-COUNT says 3 lines but the bytes stop after the first one --
        # cut exactly on a field boundary, so no field reads as truncated.
        b"\xf0\xf0\xf0\xf0\xf1\xf0\xf3" + b"\xc1" * 6 + b"\x00\x1c",
    ],
)
def test_a_short_final_variable_bare_record_is_trailing_not_a_row(tail):
    # RECFM=F already reported a short tail as trailing bytes; the unframed
    # variable format decoded it into one more row of truncated rubbish.
    dataset = _dataset(ODO)
    opts = EncodingOptions(
        charset=Charset.EBCDIC, record_format=RecordFormat.VARIABLE_BARE
    )
    raw = dataset.to_records(opts)
    result = _decoder(ODO, opts).decode_bytes(raw + tail)
    assert len(result.records) == len(dataset.rows)
    assert result.trailing == tail
    assert result.bytes_read == len(raw)


def test_a_record_cut_mid_field_decodes_what_was_there():
    source = "       01  R.\n           05  A PIC X(4).\n           05  B PIC X(4).\n"
    view = build_record_views(parse_copybook_records(source)[0]).base
    fields = decode_record(view, b"ABCDEF", EncodingOptions())
    assert fields[0].value == "ABCD"
    assert fields[1].value == "EF"
    assert fields[1].truncated is True
    assert fields[1].length == 2
    assert fields[1].error == "2 of 4 bytes: record ends inside the field"


SHORT_NUMERIC = (
    "       01  R.\n"
    "           05  K PIC 9(2).\n"
    "           05  A PIC X(4).\n"
    "           05  N PIC 9(4).\n"
)


def test_a_numeric_field_cut_short_is_an_error_not_a_value():
    # Regression (#358): N's three bytes '001' are the high-order digits of a
    # four-digit field, yet decoded clean as the value 1.
    view = build_record_views(parse_copybook_records(SHORT_NUMERIC)[0]).base
    fields = decode_record(view, b"01ABCD001", EncodingOptions())
    assert fields[2].truncated is True
    assert fields[2].value == ""
    assert fields[2].raw == b"001"
    assert fields[2].error == "3 of 4 bytes: record ends inside the field"


@pytest.mark.parametrize(
    "picture", ["S9(7) COMP-3", "S9(9) COMP", "S9(9) COMP-5", "COMP-2"]
)
def test_a_binary_field_cut_short_is_an_error_not_a_value(picture):
    source = f"       01  R.\n           05  K PIC X.\n           05  N {picture}.\n"
    source = source.replace("PIC COMP-2", "COMP-2")
    view = build_record_views(parse_copybook_records(source)[0]).base
    fields = decode_record(view, b"K\x00\x01", EncodingOptions())
    assert fields[1].truncated is True
    assert fields[1].value == ""
    assert fields[1].error is not None


def test_a_variable_record_cut_inside_a_field_counts_as_an_error():
    body = b"01ABCD001"
    rdw = (len(body) + 4).to_bytes(2, "big") + b"\x00\x00"
    decoder = RecordDecoder.from_copybook_source(
        SHORT_NUMERIC, opts=EncodingOptions(record_format=RecordFormat.VARIABLE)
    )
    result = decoder.decode_bytes(rdw + body)
    assert result.error_count == 1
    assert result.records[0].errors == [
        "N: 3 of 4 bytes: record ends inside the field"
    ]


def test_a_fixed_record_length_shorter_than_the_layout_counts_as_an_error():
    decoder = RecordDecoder.from_copybook_source(
        SHORT_NUMERIC, opts=EncodingOptions(), record_length=8
    )
    result = decoder.decode_bytes(b"01ABCD0001ABCD00")
    assert len(result.records) == 2
    assert result.error_count == 2


def test_a_record_ending_on_a_field_boundary_is_not_an_error():
    view = build_record_views(parse_copybook_records(SHORT_NUMERIC)[0]).base
    fields = decode_record(view, b"01ABCD", EncodingOptions())
    assert [item.error for item in fields] == [None, None, None]
    assert fields[2].present is False


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


FLOATS = """
       01  FLOAT-REC.
           05  F-SINGLE    COMP-1.
           05  F-DOUBLE    COMP-2.
           05  F-TAG       PIC X(4).
"""


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
@pytest.mark.parametrize("endian", [Endian.BIG, Endian.LITTLE])
def test_generated_float_columns_round_trip_exactly(charset, endian):
    """A *generated* float value reads back as the same text, digit for digit.

    The decoder renders a COMP-1 to seven significant digits and a COMP-2
    with ``%g``; the generator used to draw a four-decimal value over
    +/-10,000 and render it with ``%.4f``, which agrees with neither.
    ``-9419.8954`` in four bytes came back ``-9419.896`` (binary32 cannot
    hold nine digits) and a COMP-2 ``-7960.5120`` came back ``-7960.512``
    (``%g`` drops the trailing zero) -- so a generated file disagreed with
    its own decoding in roughly one COMP-2 row in ten and in nearly every
    COMP-1 row. The generator now renders a drawn value the way the field
    will give it back.
    """
    dataset = _dataset(FLOATS, rows=400)
    opts = EncodingOptions(charset=charset, endian=endian)
    result = _decoder(FLOATS, opts).decode_bytes(dataset.to_records(opts))

    assert result.error_count == 0
    assert result.to_csv() == dataset.to_csv()


def test_a_generated_comp_1_survives_binary32():
    """The value in the CSV is one binary32 can hold, not a rounded-off one."""
    import struct

    dataset = _dataset(FLOATS, rows=200)
    single = dataset.header.index("F-SINGLE")
    for row in dataset.rows:
        value = float(row[single])
        stored = struct.unpack("<f", struct.pack("<f", value))[0]
        assert f"{stored:.7g}" == row[single]


# ---------------------------------------------------------------------------
# Issue #248: invalid records that used to decode with error_count 0
# ---------------------------------------------------------------------------

ODO_248 = """
       01  REC2.
           05  N    PIC 9.
           05  T    OCCURS 2 TO 5 DEPENDING ON N.
               10  TT  PIC XX.
           05  AFT  PIC X(3).
"""

_VB_ASCII = EncodingOptions(charset=Charset.ASCII, record_format=RecordFormat.VARIABLE)


def _vb(body: bytes) -> bytes:
    return (len(body) + 4).to_bytes(2, "big") + b"\0\0" + body


def test_an_odo_counter_below_its_minimum_is_flagged_on_the_counter():
    result = _decoder(ODO_248, _VB_ASCII).decode_bytes(_vb(b"1AAXYZ"))
    record = result.records[0]
    counter = next(item for item in record.fields if item.name == "N")
    assert counter.error is not None
    assert "1 outside 2..5" in counter.error
    assert result.error_count >= 1


def test_an_odo_counter_above_its_maximum_and_leftover_bytes_are_flagged():
    result = _decoder(ODO_248, _VB_ASCII).decode_bytes(_vb(b"7AABBCCDDEEFFGGXYZ"))
    record = result.records[0]
    counter = next(item for item in record.fields if item.name == "N")
    assert counter.error is not None and "7 outside 2..5" in counter.error
    # The four body bytes no field accounts for are a record-level error.
    assert any("4 byte" in error for error in record.errors)
    assert result.error_count == 2
    assert record.to_dict()["errors"] == record.errors
    assert "! record: 4 byte(s)" in decoded_hex_dump(result, _VB_ASCII)


def test_a_well_formed_variable_record_still_decodes_clean():
    result = _decoder(ODO_248, _VB_ASCII).decode_bytes(_vb(b"3AABBCCXYZ"))
    assert result.error_count == 0
    assert result.records[0].value("AFT") == "XYZ"


def test_a_negative_sign_nibble_on_an_unsigned_packed_field_is_an_error():
    source = "       01  R.\n           05  P PIC 9(3) COMP-3.\n"
    for raw in (b"\x12\x3d", b"\x12\x3b"):
        field = _one_field(source, raw, EncodingOptions())
        assert field.value == "123"  # not "-123": the field cannot hold it
        assert field.error is not None and "unsigned" in field.error
    clean = _one_field(source, b"\x12\x3f", EncodingOptions())
    assert (clean.value, clean.error) == ("123", None)


def test_a_binary_value_wider_than_its_picture_is_a_caveat_not_an_error():
    # Legal under TRUNC(BIN), invalid under TRUNC(STD): flagged, not failed.
    source = "       01  R.\n           05  B PIC 9(4) COMP.\n"
    result = _decoder(source, EncodingOptions()).decode_bytes(b"\xff\xff")
    assert result.records[0].value("B") == "65535"
    assert result.error_count == 0
    assert any("TRUNC" in caveat and "B" in caveat for caveat in result.caveats)
    fits = _decoder(source, EncodingOptions()).decode_bytes(b"\x27\x0f")
    assert not any("TRUNC" in caveat for caveat in fits.caveats)


TABLE_OVERLAY = """
       01  TBL-REC.
           05  TBL OCCURS 2 TIMES.
               10  T-VAL       PIC XX.
               10  T-ALT REDEFINES T-VAL.
                   15  T-A     PIC X.
                   15  T-B     PIC X.
"""


def test_an_overlay_inside_a_table_decodes_every_occurrence():
    """#296: `--view T-ALT` used to read occurrence 1 only."""
    decoder = _decoder(TABLE_OVERLAY, EncodingOptions())
    result = decoder.decode_bytes(b"ABCD", view="T-ALT")
    assert result.header == ["T-A(1)", "T-B(1)", "T-A(2)", "T-B(2)"]
    assert result.records[0].values() == {
        "T-A(1)": "A",
        "T-B(1)": "B",
        "T-A(2)": "C",
        "T-B(2)": "D",
    }


def test_an_overlay_of_a_depending_on_counter_still_sizes_the_table():
    """An overlay redefining an ODO counter drops the counter from its view,
    but the table still takes its length from those bytes: under RECFM=V
    every field after the table moved, with no error, before the fix."""
    source = """
       01  R.
           05  CNT         PIC 9.
           05  CNT-X REDEFINES CNT PIC X.
           05  TBL OCCURS 1 TO 3 TIMES DEPENDING ON CNT.
               10  V       PIC XX.
           05  TAIL        PIC XXX.
"""
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    specs = flatten_record(
        parse_copybook_records(source)[0], DataGeneratorOptions().for_record_image()
    )
    raw = encode_record(specs, ["2", "AA", "BB", "", "END"], opts)
    result = _decoder(source, opts).decode_bytes(raw, view="CNT-X")
    assert result.records[0].values() == {
        "CNT-X": "2",
        "V(1)": "AA",
        "V(2)": "BB",
        "V(3)": "",
        "TAIL": "END",
    }
    assert result.error_count == 0
    # The counter is read, so no caveat may say it is missing from the record.
    assert not any("not part of the record" in c for c in result.caveats)


def test_a_wider_overlay_reads_the_field_after_it():
    """Non-conforming, but compilers accept it: the slot is the widest
    member, so B sits after the 8-byte overlay and the record is 10 bytes."""
    source = """
       01  R.
           05 A PIC X(4).
           05 A-R REDEFINES A PIC X(8).
           05 B PIC X(2).
"""
    result = _decoder(source, EncodingOptions()).decode_bytes(b"12345678BB", view="A-R")
    assert result.records[0].values() == {"A-R": "12345678", "B": "BB"}
