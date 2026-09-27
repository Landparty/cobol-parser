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
    assert edit_numeric("9(3)PPP", "1000") is None


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
