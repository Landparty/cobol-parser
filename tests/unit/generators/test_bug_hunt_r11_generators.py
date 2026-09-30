"""Bug hunt round 11: generators (test data, record images, decoding).

Each test reproduces one defect found in round 11 and pins the fix.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cobolparser.generators.data.copybook import CopybookDataGenerator
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.editing import (
    deedit_float,
    deedit_numeric,
    edit_numeric,
    is_float_picture,
)
from cobolparser.generators.data.encoding import (
    Charset,
    EncodingOptions,
    RecordFormat,
)
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause


def _picture(pattern: str) -> PictureClause:
    return PictureClause(pattern, SourceLocation(1, 1))


def _generate(source: str, rows: int = 40, seed: int = 11):
    options = DataGeneratorOptions(rows=rows, seed=seed).for_record_image()
    return CopybookDataGenerator(options).generate_from_source(source)


def _round_trip(source: str, opts: EncodingOptions, rows: int = 40):
    dataset = _generate(source, rows)
    data = dataset.to_records(opts)
    decoded = RecordDecoder.from_copybook_source(source).decode_bytes(data, opts=opts)
    return dataset, data, decoded


# -- external floating-point pictures ----------------------------------------


@pytest.mark.parametrize(
    ("pattern", "integer", "decimal", "size"),
    [
        ("-9.9(5)E-99", 1, 5, 12),
        ("+.9(3)E+99", 0, 3, 9),
        ("+99V9(4)E-99", 2, 4, 11),
    ],
)
def test_external_float_counts_only_mantissa_digits(pattern, integer, decimal, size):
    # The exponent's sign and digits were counted as fraction digits (the
    # exponent sign read as a second floating '-'), so -9.9(5)E-99 was an
    # eight-place fraction and generated values did not fit the picture.
    picture = _picture(pattern)
    assert (picture.integer_digits, picture.decimal_digits) == (integer, decimal)
    assert picture.total_digits == integer + decimal
    assert picture.size == size


def test_external_float_edits_and_deedits_normalized():
    assert edit_numeric("-9.9(5)E-99", "8.85686") == " 8.85686E 00"
    assert edit_numeric("-9.9(5)E-99", "0.5") == " 5.00000E-01"
    assert edit_numeric("+9.9(5)E+99", "-123.456") == "-1.23456E+02"
    assert edit_numeric("+.9(3)E+99", "0") == "+.000E+00"
    assert deedit_float("-9.9(5)E-99", " 5.00000E-01") == Decimal("0.5")
    assert deedit_float("+9.9(5)E+99", "-1.23456E+02") == Decimal("-123.456")
    assert deedit_float("+9.9(5)E+99", "garbage-text") is None


def test_external_float_under_decimal_point_is_comma():
    text = edit_numeric("-9,9(5)E-99", "-0.5", decimal_point_is_comma=True)
    assert text == "-5,00000E-01"
    assert is_float_picture("-9,9(5)E-99", decimal_point_is_comma=True)
    assert deedit_float("-9,9(5)E-99", text, decimal_point_is_comma=True) == Decimal(
        "-0.5"
    )


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_external_float_record_image_is_a_float_and_round_trips(charset):
    source = "       01 REC.\n          05 F PIC -9.9(5)E-99.\n"
    opts = EncodingOptions(charset=charset)
    dataset, data, decoded = _round_trip(source, opts)
    # Every value fits the mantissa: one integer digit, five places.
    for (cell,) in dataset.rows:
        whole, _, fraction = cell.lstrip("-").partition(".")
        assert len(whole) == 1 and len(fraction) == 5
    first = data[:12].decode("cp037" if charset is Charset.EBCDIC else "ascii")
    assert first[-4] == "E" and first[2] == "."
    assert decoded.error_count == 0
    assert decoded.to_dicts() == dataset.to_dicts()


# -- P scaling positions in an edited picture ---------------------------------


def test_edited_picture_with_trailing_p_counts_scaling_positions():
    # ZZPPP holds multiples of 1000 up to 99000; integer_digits was 2.
    picture = _picture("ZZPPP")
    assert picture.integer_digits == 5
    assert picture.decimal_digits == 0
    assert picture.total_digits == 2
    assert picture.size == 2
    assert picture.scaling_leading is False


def test_edited_picture_with_p_edits_stored_digits_only():
    assert edit_numeric("ZZPPP", "57000") == "57"
    assert edit_numeric("ZZPPP", "57999") == "57"
    assert deedit_numeric("ZZPPP", "57") == (57, False)
    assert edit_numeric("$$9PP", "2300") == "$23"


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_edited_picture_with_p_generates_scaled_values_and_round_trips(charset):
    source = "       01 REC.\n          05 F PIC ZZPPP.\n          05 G PIC $$9PP.\n"
    dataset, data, decoded = _round_trip(source, EncodingOptions(charset=charset))
    for f_cell, g_cell in dataset.rows:
        assert int(f_cell) % 1000 == 0 and int(f_cell) <= 99000
        assert int(g_cell) % 100 == 0 and int(g_cell) <= 9900
    assert len(data) == 40 * 5
    assert decoded.error_count == 0
    assert decoded.to_dicts() == dataset.to_dicts()


# -- level-88 figurative constants ------------------------------------------

_FIGURATIVE_88 = """       01 REC.
          05 F PIC X(8).
             88 F-BLANK VALUE SPACES.
             88 F-A VALUE 'A'.
          05 N PIC 9(3).
             88 N-ZERO VALUE ZERO.
             88 N-ONE VALUE 1.
          05 H PIC X(2).
             88 H-HI VALUE HIGH-VALUES.
          05 Z PIC X(3).
             88 Z-ZERO VALUE ZEROES.
"""


def test_level_88_figurative_constants_are_not_written_as_words():
    # VALUE SPACES / ZERO / HIGH-VALUES were fitted as literal text: the
    # field held "SPACES", "ZER" and "HI".
    dataset = _generate(_FIGURATIVE_88, rows=30)
    f_values = {row[0] for row in dataset.rows}
    n_values = {row[1] for row in dataset.rows}
    assert f_values == {"", "A"}
    assert n_values == {"0", "1"}
    assert all(row[2] != "HI" for row in dataset.rows)
    assert {row[3] for row in dataset.rows} == {"000"}
    decoded = RecordDecoder.from_copybook_source(_FIGURATIVE_88).decode_bytes(
        dataset.to_records(EncodingOptions())
    )
    assert decoded.to_dicts() == dataset.to_dicts()


def test_value_zero_fills_an_alphanumeric_field():
    source = "       01 REC.\n          05 A PIC X(3) VALUE ZERO.\n"
    dataset = _generate(source, rows=2)
    assert dataset.rows == [["000"], ["000"]]


# -- alphanumeric-edited pictures ----------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "check"),
    [
        ("X(2)/X(2)", lambda v: len(v) == 5 and v[2] == "/"),
        ("XXBXX", lambda v: len(v) == 5 and v[2] == " "),
        ("A(2)0A", lambda v: v[2] == "0" and (v[:2] + v[3:]).isalpha()),
    ],
)
def test_alphanumeric_edited_values_hold_their_insertion_characters(pattern, check):
    source = f"       01 REC.\n          05 F PIC {pattern}.\n"
    dataset = _generate(source, rows=25)
    for (value,) in dataset.rows:
        assert check(value), value


# -- OCCURS DEPENDING ON CNT OF HDR ------------------------------------------

_QUALIFIED_ODO = """       01 REC.
          05 HDR.
             10 CNT PIC 9(2).
          05 TBL OCCURS 0 TO 5 TIMES DEPENDING ON CNT OF HDR.
             10 ITEM PIC X(3).
          05 TRL.
             10 CNT PIC 9(2).
"""


def test_qualified_depending_on_names_only_its_own_counter():
    # TRL.CNT shares the counter's name; it was treated as a counter too,
    # and the encoder sized the table from whichever CNT came last.
    dataset = _generate(_QUALIFIED_ODO, rows=30, seed=5)
    bounds = {spec.column: spec.odo_counter_bounds for spec in dataset.fields}
    assert bounds["REC.HDR.CNT"] == (0, 5)
    assert bounds["REC.TRL.CNT"] is None
    opts = EncodingOptions(record_format=RecordFormat.VARIABLE)
    decoded = RecordDecoder.from_copybook_source(_QUALIFIED_ODO).decode_bytes(
        dataset.to_records(opts), opts=opts
    )
    assert decoded.error_count == 0
    for row, record in zip(dataset.rows, decoded.records, strict=True):
        count = int(row[0])
        values = record.values()
        assert values["REC.HDR.CNT"] == row[0]
        assert values["REC.TRL.CNT"] == row[-1]
        for index in range(1, 6):
            expected = row[index] if index <= count else ""
            assert values[f"ITEM({index})"] == expected


# -- copybook line splitting ---------------------------------------------------


def test_free_form_copybook_keeps_a_form_feed_inside_a_literal():
    # str.splitlines() split the record at the form feed, cutting the
    # literal short: VALUE 'A<FF>B' became VALUE 'A'.
    source = "01 REC.\n   05 A PIC X(3) VALUE 'A\x0cB'.\n   05 B PIC 9(2) VALUE 7.\n"
    options = DataGeneratorOptions(rows=1, seed=1)
    dataset = CopybookDataGenerator(options).generate_from_source(source)
    assert dataset.rows == [["A\x0cB", "7"]]
