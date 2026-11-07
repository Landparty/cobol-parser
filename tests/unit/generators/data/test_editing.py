"""Numeric-edited pictures: the edited form a MOVE produces, and back.

Every expected string below was checked against GnuCOBOL 3 by compiling
``01 E PIC <picture>.`` / ``MOVE <value> TO E`` / ``DISPLAY "[" E "]"`` for
each case and comparing the bracketed output byte for byte.
"""

from decimal import Decimal

import pytest

from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    RecordDecoder,
)
from cobolparser.generators.data.editing import deedit_numeric, edit_numeric
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause

GNUCOBOL_CASES = [
    ("$$,$$9.99", "1234.56", "$1,234.56"),
    ("$$,$$9.99", "5.00", "    $5.00"),
    ("$$,$$9.99", "0", "    $0.00"),
    ("ZZ9.99", "0.05", "  0.05"),
    ("ZZZ.ZZ", "0.05", "   .05"),
    ("ZZZ.ZZ", "0", "      "),
    ("ZZZ.ZZ", "-5.25", "  5.25"),
    ("***9.99", "12.3", "**12.30"),
    ("****.**", "0", "****.**"),
    ("**,**9.99", "0.5", "*****0.50"),
    ("-ZZ,ZZ9.99", "-1234.5", "- 1,234.50"),
    ("-ZZ,ZZ9.99", "1234.5", "  1,234.50"),
    ("-ZZ9.99", "-12.34", "- 12.34"),
    ("+++9", "12", " +12"),
    ("+++9", "-12", " -12"),
    ("---9", "-5", "  -5"),
    ("---9", "5", "   5"),
    ("++,++9", "0", "    +0"),
    ("--,--9", "-1234", "-1,234"),
    ("--,--9", "-12", "   -12"),
    ("9(3)CR", "-12", "012CR"),
    ("9(3)CR", "12", "012  "),
    ("9(3)DB", "-1", "001DB"),
    ("$$,$$$.99CR", "-12.5", "   $12.50CR"),
    ("$$$,$$$.99-", "-0.5", "      $.50-"),
    ("$$,$$$.$$", "0.05", "     $.05"),
    ("$$,$$$", "0", "      "),
    ("-$$$9", "-12", "- $12"),
    ("999B99", "12345", "123 45"),
    ("ZZBZZ", "34", "   34"),
    ("99/99/99", "123456", "12/34/56"),
    ("0009", "7", "0007"),
    ("Z(3)V99", "1.5", "  150"),
    ("Z,ZZ9.99+", "1000", "1,000.00+"),
    ("+9(3)", "-7", "-007"),
    ("9(3)-", "7", "007 "),
]


@pytest.mark.parametrize(("picture", "value", "expected"), GNUCOBOL_CASES)
def test_edit_matches_gnucobol(picture, value, expected):
    assert edit_numeric(picture, value) == expected


@pytest.mark.parametrize(("picture", "value", "expected"), GNUCOBOL_CASES)
def test_deedit_inverts_edit(picture, value, expected):
    magnitude, negative = deedit_numeric(picture, expected)
    scale = PictureClause(picture, SourceLocation(1, 1)).decimal_digits
    read_back = Decimal(-magnitude if negative else magnitude).scaleb(-scale)
    # What was read back re-edits to exactly the same text...
    assert edit_numeric(picture, str(read_back)) == expected
    # ...and is the value that was moved in, less any sign the picture
    # has no symbol to show.
    assert abs(read_back) == abs(Decimal(value))


def test_unmodelled_picture_is_left_alone():
    # A P run between digit positions is no picture this module edits (an
    # end-of-picture P run is: see test_bug_hunt_r11_generators.py).
    assert edit_numeric("Z9P9", "1000") is None


def test_deedit_rejects_text_no_edit_could_produce():
    assert deedit_numeric("ZZ9.99", "  A.00") is None


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
@pytest.mark.parametrize(
    "picture", ["$$,$$9.99", "-ZZ,ZZ9.99", "9(3)CR", "99/99/99", "Z(3)V99", "***9.99"]
)
def test_record_image_round_trips(picture, charset):
    source = f"       01 REC.\n          05 F1 PIC {picture}.\n"
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=40, seed=11).for_record_image()
    ).generate_from_source(source)
    opts = EncodingOptions(charset=charset)
    result = RecordDecoder.from_copybook_source(source).decode_bytes(
        dataset.to_records(opts), opts=opts
    )
    assert result.error_count == 0
    assert [r.values()["F1"] for r in result.records] == [
        row[0] for row in dataset.rows
    ]


def test_record_image_holds_the_edited_form():
    source = "       01 REC.\n          05 F1 PIC $$,$$9.99.\n"
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=1, seed=5).for_record_image()
    ).generate_from_source(source)
    value = dataset.rows[0][0]
    assert dataset.to_records(EncodingOptions()) == edit_numeric(
        "$$,$$9.99", value
    ).encode("ascii")


@pytest.mark.parametrize(
    "picture, value, edited",
    [
        # The floating sign lands on the insertion comma inside the string.
        ("+++,+++", "-514", "   -514"),
        ("---,---.99", "-5", "     -5.00"),
        ("+,+++,+++", "-1000", "   -1,000"),
    ],
)
def test_floating_sign_on_an_insertion_position_reads_back_negative(
    picture, value, edited
):
    assert edit_numeric(picture, value) == edited
    magnitude, negative = deedit_numeric(picture, edited)
    assert negative is True
    assert magnitude != 0


# IBM Enterprise COBOL Language Reference, "PICTURE clause editing": the
# worked examples in its editing tables, one row per example (picture,
# value moved in, result).  The comment on each group names the table.
IBM_LRM_CASES = [
    # Simple insertion editing
    ("99,B999,B000", "1234", "01, 234, 000"),
    ("99,999", "12345", "12,345"),
    # Special insertion editing (the decimal point; excess places truncate)
    ("999.99", "1.234", "001.23"),
    ("999.99", "12.34", "012.34"),
    ("999.99", "123.45", "123.45"),
    ("999.99", "1234.5", "234.50"),
    # Fixed insertion editing
    ("999.99+", "6555.556", "555.55+"),
    ("+9999.99", "-6555.555", "-6555.55"),
    ("9999.99", "1234.56", "1234.56"),
    ("$999.99", "-123.45", "$123.45"),
    ("-$999.99", "-123.456", "-$123.45"),
    ("-$999.99", "123.456", " $123.45"),
    ("$9999.99CR", "123.45", "$0123.45  "),
    ("$9999.99DB", "-123.45", "$0123.45DB"),
    # Floating insertion editing
    ("$$$$.99", ".123", "   $.12"),
    ("$$$9.99", ".12", "  $0.12"),
    ("$,$$$,999.99", "-1234.56", "   $1,234.56"),
    ("+,+++,999.99", "-123456.789", " -123,456.78"),
    ("$$,$$$,$$$.99CR", "-1234567", "$1,234,567.00CR"),
    ("++,+++,+++.+++", "0", " " * 14),
    # Zero suppression and replacement editing
    ("****.**", "0", "****.**"),
    ("ZZZZ.ZZ", "0", "       "),
    ("ZZZZ.99", "0", "    .00"),
    ("****.99", "0", "****.00"),
    ("ZZ99.99", "0", "  00.00"),
    ("Z,ZZZ.ZZ+", "123.456", "  123.45+"),
    ("*,***.**+", "-123.45", "**123.45-"),
    ("**,***,***.**+", "12345678.9", "12,345,678.90+"),
    ("$Z,ZZZ,ZZZ.ZZCR", "12345.67", "$   12,345.67  "),
    ("$B*,***,***.**BBDB", "-12345.67", "$ ***12,345.67  DB"),
    # The two cases reports/open-findings.md recorded as written unedited.
    ("$$$,$$9", "2208", " $2,208"),
    ("9(5)DB", "-38848", "38848DB"),
]


@pytest.mark.parametrize(("picture", "value", "expected"), IBM_LRM_CASES)
def test_edit_matches_ibm_lrm_examples(picture, value, expected):
    assert edit_numeric(picture, value) == expected


@pytest.mark.parametrize(("picture", "value", "expected"), IBM_LRM_CASES)
def test_ibm_lrm_examples_round_trip(picture, value, expected):
    magnitude, negative = deedit_numeric(picture, expected)
    clause = PictureClause(picture, SourceLocation(1, 1))
    scale = clause.decimal_digits
    read_back = Decimal(-magnitude if negative else magnitude).scaleb(-scale)
    assert edit_numeric(picture, str(read_back)) == expected
    # The value moved in, less the places and high-order digits the picture
    # has no room for (truncated, as a MOVE does), and less a sign it has no
    # symbol to show.
    moved = Decimal(value)
    kept = int(moved.copy_abs().scaleb(scale)) % 10**clause.total_digits
    assert magnitude == kept
    signed = any(s in picture for s in ("+", "-", "CR", "DB"))
    assert negative == (signed and moved < 0 and kept != 0)


@pytest.mark.parametrize(
    "picture, expected",
    [
        # Every position but the decimal point is an asterisk, a fixed sign
        # and CR / DB included (IBM LRM, zero suppression and replacement).
        ("***.**", "***.**"),
        ("***.**-", "***.***"),
        ("+***.**", "****.**"),
        ("$***.**", "****.**"),
        ("***.**CR", "***.****"),
        ("*,***.**DB", "*****.****"),
        ("*(3)V**", "*****"),
    ],
)
def test_all_asterisk_zero_fills_every_position(picture, expected):
    assert edit_numeric(picture, "0") == expected
    assert deedit_numeric(picture, expected) == (0, False)


def test_ibm_lrm_examples_through_record_images():
    """Each IBM example's picture in one record, read back by the decoder:
    the bytes are the edited form and decode to the generated value."""
    pictures = sorted({picture for picture, _, _ in IBM_LRM_CASES})
    source = "       01 REC.\n" + "".join(
        f"          05 F{i} PIC {picture}.\n" for i, picture in enumerate(pictures)
    )
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=60, seed=3).for_record_image()
    ).generate_from_source(source)
    for charset in (Charset.ASCII, Charset.EBCDIC):
        opts = EncodingOptions(charset=charset)
        result = RecordDecoder.from_copybook_source(source).decode_bytes(
            dataset.to_records(opts), opts=opts
        )
        assert result.error_count == 0
        for record, row in zip(result.records, dataset.rows, strict=True):
            assert list(record.values().values()) == list(row)
    # The ASCII bytes are exactly the concatenated edited forms.
    first = dataset.rows[0]
    expected = "".join(
        edit_numeric(picture, value)
        for picture, value in zip(pictures, first, strict=True)
    )
    width = len(expected)
    assert dataset.to_records(EncodingOptions())[:width] == expected.encode("ascii")


@pytest.mark.parametrize("picture", ["ZZ,ZZ9.99", "$$$,$$9", "***,**9.99", "Z(5)"])
def test_unsigned_edited_pictures_generate_no_negative_values(picture):
    # A MOVE of a negative value into a picture with no sign symbol loses
    # the sign, so a generated negative would not round-trip.
    source = f"       01 REC.\n          05 F1 PIC {picture}.\n"
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=300, seed=9).for_record_image()
    ).generate_from_source(source)
    assert all(Decimal(row[0]) >= 0 for row in dataset.rows)


@pytest.mark.parametrize("picture", ["9(5)DB", "-ZZ,ZZ9.99", "$$,$$$.99CR"])
def test_signed_edited_pictures_generate_and_round_trip_negatives(picture):
    source = f"       01 REC.\n          05 F1 PIC {picture}.\n"
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=300, seed=9).for_record_image()
    ).generate_from_source(source)
    values = [row[0] for row in dataset.rows]
    assert any(Decimal(v) < 0 for v in values)
    opts = EncodingOptions()
    result = RecordDecoder.from_copybook_source(source).decode_bytes(
        dataset.to_records(opts), opts=opts
    )
    assert result.error_count == 0
    assert [r.values()["F1"] for r in result.records] == values


def test_blank_when_zero_edited_field_is_spaces_and_reads_back_zero():
    source = "       01 REC.\n          05 F1 PIC $$,$$9.99 BLANK WHEN ZERO.\n"
    decoder = RecordDecoder.from_copybook_source(source)
    result = decoder.decode_bytes(b" " * 9, opts=EncodingOptions())
    assert result.error_count == 0
    assert Decimal(result.records[0].values()["F1"]) == 0
