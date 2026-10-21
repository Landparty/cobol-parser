"""Issue #491: the numeric-edited encoder knew only ``$``.  A program's own
``SPECIAL-NAMES. CURRENCY SIGN IS '#'`` symbol made ``edit_numeric`` give
up, so the record held the logical value left-justified (``17611.57  ``)
with no caveat, and ``decode(encode(row)) == row`` broke.  A one-character
currency string is now edited like ``$``; anything still not modelled (a
multi-character string such as ``'CHF '``) is named in a caveat.
"""

from __future__ import annotations

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.editing import deedit_numeric, edit_numeric
from cobolparser.generators.data.encoding import EncodingOptions, encoding_caveats
from cobolparser.generators.data.layout import flatten_record


def _program(currency: str, fields: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CS.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       CONFIGURATION SECTION.\n"
        "       SPECIAL-NAMES.\n"
        f"           {currency}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  REC.\n" + fields + "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


SINGLE = _program(
    "CURRENCY SIGN IS '#'",
    "           05  C1  PIC ###,##9.99.\n           05  C2  PIC #9(5).99.\n",
)
MULTI = _program(
    "CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'",
    "           05  C1  PIC #ZZ9.99.\n",
)


def _record(source: str):
    result = parse_cobol(
        source, filename="cs.cbl", error_recovery=ErrorRecoveryMode.FAIL_FAST
    )
    assert result.ast is not None, result.errors
    records = [
        item
        for section in result.ast.data_division.sections
        for item in section.data_items
        if item.name == "REC"
    ]
    return records[0]


def test_picture_carries_the_currency_string() -> None:
    record = _record(SINGLE)
    specs = flatten_record(record)
    assert [spec.currency_signs for spec in specs] == [{"#": "#"}, {"#": "#"}]
    specs = flatten_record(_record(MULTI))
    assert specs[0].currency_signs == {"#": "EUR"}


def test_single_character_sign_is_edited_like_dollar() -> None:
    signs = {"#": "#"}
    assert edit_numeric("###,##9.99", "17611.57", currency_signs=signs) == (
        "#17,611.57"
    )
    assert edit_numeric("#9(5).99", "8271.26", currency_signs=signs) == "#08271.26"
    assert deedit_numeric("###,##9.99", "#17,611.57", currency_signs=signs) == (
        1761157,
        False,
    )


def test_record_image_round_trips_and_has_no_caveat() -> None:
    opts = DataGeneratorOptions(rows=3, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_record(_record(SINGLE))
    image = dataset.to_records(EncodingOptions())
    assert image[:1] == b"#" and image[10:11] == b"#"
    assert not any("not modelled" in c for c in encoding_caveats(dataset.fields))
    decoded = RecordDecoder.from_record(
        _record(SINGLE), opts=EncodingOptions()
    ).decode_bytes(image)
    assert decoded.error_count == 0
    columns = [spec.name for spec in dataset.fields]
    for row, record in zip(dataset.rows, decoded.records, strict=True):
        values = record.values()
        for name, cell in zip(columns, row, strict=True):
            assert float(values[name]) == float(cell)


def test_multi_character_string_is_named_in_a_caveat() -> None:
    specs = flatten_record(_record(MULTI))
    assert any(
        "not modelled" in caveat and "REC.C1" in caveat
        for caveat in encoding_caveats(specs)
    )
