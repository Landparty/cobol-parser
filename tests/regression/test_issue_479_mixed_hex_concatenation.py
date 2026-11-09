"""Issue #479 part 2: ``VALUE 'AB' & X'0102'`` was cut to ``'AB'``.

A basic and a hexadecimal literal are both alphanumeric literals, so IBM
Enterprise COBOL (and GnuCOBOL, which stores ``41420102``) joins them. The
lexer only joined literals of one spelling, so the data parser warned
"Unparsed token '0102' ... content dropped" and ``gen-data`` wrote ``AB  ``.
The lexer now joins them into one literal whose ``raw_value`` keeps every
part, and the record-image generator writes the hex parts' own bytes and the
basic parts in the record charset.
"""

from __future__ import annotations

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.encoding import Charset, EncodingOptions
from cobolparser.layout.fields import concatenated_literal_cell
from cobolparser.lexer import CobolLexer, TokenType

SOURCE = "\n".join(
    [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. V.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  REC.",
        "           05  F   PIC X(4) VALUE 'AB' & X'0102'.",
        "           05  H   PIC X(3) VALUE X'41' & 'B'.",
        "           05  K   PIC X(5) VALUE 'A' & X'FF'",
        "                              & 'C' & X'00'.",
        "       PROCEDURE DIVISION.",
        "           DISPLAY F H K.",
        "           STOP RUN.",
        "",
    ]
)


def _literals(source: str) -> list[tuple[str, str | None]]:
    tokens = CobolLexer(source, free_form=True).tokenize()
    return [
        (t.value, t.raw_value) for t in tokens if t.type == TokenType.STRING_LITERAL
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("'AB' & X'0102'", [("AB\x01\x02", "\"AB\" & X'0102'")]),
        ("X'41' & 'B'", [("AB", "X'41' & \"B\"")]),
        (
            "X'41' & 'B' & 'C' & X'42'",
            [("ABCB", "X'41' & \"B\" & \"C\" & X'42'")],
        ),
        # A part that holds an ampersand is literal text.
        ("'A&B' & X'26'", [("A&B&", "\"A&B\" & X'26'")]),
        # Without the ampersand, still two literals.
        ("'AB' X'01'", [("AB", None), ("01", "X'01'")]),
    ],
)
def test_lexer_joins_basic_and_hex_literals(source, expected) -> None:
    assert _literals(source) == expected


def _record():
    result = parse_cobol(SOURCE, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.errors == [] and result.warnings == []
    return next(
        item
        for item in result.ast.find_all_by_type("CobolDataItem")
        if item.name == "REC"
    )


def test_value_clause_keeps_every_part() -> None:
    items = {item.name: item for item in _record().children}
    assert items["F"].value_clause == "\"AB\" & X'0102'"
    assert items["K"].value_clause == "\"A\" & X'FF' & \"C\" & X'00'"


def test_cell_names_bytes_and_characters() -> None:
    cell = concatenated_literal_cell("\"AB\" & X'0102'")
    assert cell is not None
    assert cell.data == b"AB\x01\x02" and cell.text_runs == ((0, 2),)
    assert cell.cut(3).data == b"AB\x01"
    assert cell.cut(1).text_runs == ((0, 1),)
    # Plain parts only, or anything that is not a run of parts: not one.
    assert concatenated_literal_cell('"AB" & "CD"') is None
    assert concatenated_literal_cell("X'01'") is None
    assert concatenated_literal_cell("\"AB\" & X'0G'") is None
    assert concatenated_literal_cell('"AB" &') is None


@pytest.mark.parametrize(
    ("charset", "expected"),
    [
        (Charset.ASCII, b"AB\x01\x02" + b"AB " + b"A\xffC\x00 "),
        (
            Charset.EBCDIC,
            b"\xc1\xc2\x01\x02" + b"\x41\xc2\x40" + b"\xc1\xff\xc3\x00\x40",
        ),
    ],
)
def test_record_image_and_round_trip(charset, expected) -> None:
    opts = DataGeneratorOptions(rows=2, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_record(_record())
    enc = EncodingOptions(charset=charset)
    image = dataset.to_records(enc)
    assert image[:12] == expected
    decoded = RecordDecoder.from_record(_record(), opts=enc).decode_bytes(image)
    assert decoded.error_count == 0
    first = decoded.records[0].values()
    assert first["F"] == "AB\x01\x02"
    assert first["K"] == "A\xffC\x00"


def test_level_88_values_round_trip_in_ebcdic() -> None:
    # Review fix: the decoder only knew a VALUE clause's mixed literal.
    source = "\n".join(
        [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. C88.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01  REC.",
            "           05  D   PIC X(4).",
            "               88  D-OK  VALUE 'AB' & X'0D25'.",
            "               88  D-ALT VALUES 'CD' & X'0000' 'EF' & X'FFFF'.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
            "",
        ]
    )
    result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    record = next(
        i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == "REC"
    )
    opts = DataGeneratorOptions(rows=8, seed=3).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_record(record)
    for charset in (Charset.ASCII, Charset.EBCDIC):
        enc = EncodingOptions(charset=charset)
        image = dataset.to_records(enc)
        decoded = RecordDecoder.from_record(record, opts=enc).decode_bytes(image)
        assert [r.values()["D"] for r in decoded.records] == [
            row[0] for row in dataset.rows
        ]
