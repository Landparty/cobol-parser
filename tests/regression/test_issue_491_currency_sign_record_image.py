"""Issue #491: the numeric-edited encoder knew only ``$``.  A program's own
``SPECIAL-NAMES. CURRENCY SIGN IS '#'`` symbol made ``edit_numeric`` give
up, so the record held the logical value left-justified (``17611.57  ``)
with no caveat, and ``decode(encode(row)) == row`` broke.  A one-character
currency string is now edited like ``$``.  A multi-character string
(``'CHF '``) fills the one position the ``$`` would hold, so the item is
that much wider; a letter ``PICTURE SYMBOL`` (``'F'``) is recognized too.
Anything still not modelled (two symbols in one picture) is named in a
caveat.
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


LETTER = _program(
    "CURRENCY SIGN IS 'CHF ' WITH PICTURE SYMBOL 'F'",
    "           05  C1  PIC FFFF,FF9.99.\n           05  C2  PIC -FFF9.\n"
    "           05  C3  PIC 9(3).99F.\n",
)


def test_multi_character_string_is_edited_in_one_position() -> None:
    signs = {"F": "CHF "}
    cases = [
        ("FFFF,FF9.99", "1.26", "      CHF 1.26", (126, False)),
        ("FFFF,FF9.99", "17611.57", " CHF 17,611.57", (1761157, False)),
        ("FFFFF9.99", "1000", " CHF 1000.00", (100000, False)),
        ("-FFF9", "-5", "-  CHF 5", (5, True)),
        ("9(3).99F", "12.5", "012.50CHF ", (1250, False)),
        # Suppressed to spaces: the string's extra positions are spaces too.
        ("FFFFFF", "0", "         ", (0, False)),
    ]
    for picture, value, text, read_back in cases:
        assert edit_numeric(picture, value, currency_signs=signs) == text
        assert deedit_numeric(picture, text, currency_signs=signs) == read_back
    assert deedit_numeric("FFF9", "  $5", currency_signs=signs) is None
    assert deedit_numeric("FFF9", "XXX  5", currency_signs=signs) is None


def test_a_letter_picture_symbol_is_declared_and_sized() -> None:
    specs = flatten_record(_record(LETTER))
    assert [spec.currency_signs for spec in specs] == [{"F": "CHF "}] * 3
    # 11 / 5 / 7 pattern positions, each 3 wider for the 4-character string.
    assert [spec.storage_size for spec in specs] == [14, 8, 10]
    assert [spec.integer_digits for spec in specs] == [6, 3, 3]
    specs = flatten_record(_record(MULTI))
    assert specs[0].storage_size == 9


def test_multi_character_record_image_round_trips_with_no_caveat() -> None:
    for source in (LETTER, MULTI):
        opts = DataGeneratorOptions(rows=5, seed=1).for_record_image()
        dataset = CopybookDataGenerator(opts).generate_from_record(_record(source))
        assert not any("not modelled" in c for c in encoding_caveats(dataset.fields))
        image = dataset.to_records(EncodingOptions())
        decoded = RecordDecoder.from_record(
            _record(source), opts=EncodingOptions()
        ).decode_bytes(image)
        assert decoded.error_count == 0
        columns = [spec.name for spec in dataset.fields]
        for row, record in zip(dataset.rows, decoded.records, strict=True):
            values = record.values()
            for name, cell in zip(columns, row, strict=True):
                assert float(values[name]) == float(cell)
    # Values use every integer digit, not the one a misread picture gave.
    opts = DataGeneratorOptions(rows=20, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_record(_record(LETTER))
    assert max(abs(float(row[0])) for row in dataset.rows) >= 1000


def test_two_symbols_in_one_picture_are_named_in_a_caveat() -> None:
    source = _program(
        "CURRENCY SIGN IS 'CHF ' WITH PICTURE SYMBOL 'F'\n"
        "           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'",
        "           05  C1  PIC F#ZZ9.99.\n",
    )
    specs = flatten_record(_record(source))
    assert any(
        "not modelled" in caveat and "REC.C1" in caveat
        for caveat in encoding_caveats(specs)
    )


def test_a_letter_symbol_matches_its_own_case_only() -> None:
    # IBM documents the PICTURE SYMBOL literal as case-sensitive.
    source = _program(
        "CURRENCY SIGN IS 'CHF ' WITH PICTURE SYMBOL 'F'",
        "           05  C1  PIC FFF9.\n",
    )
    assert flatten_record(_record(source))[0].currency_signs == {"F": "CHF "}
    lower = _program(
        "CURRENCY SIGN IS 'CHF ' WITH PICTURE SYMBOL 'f'",
        "           05  C1  PIC FFF9.\n",
    )
    assert flatten_record(_record(lower))[0].currency_signs == {}
