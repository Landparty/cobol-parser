"""SPECIAL-NAMES. DECIMAL-POINT IS COMMA is honoured.

Before: the clause was recorded in metadata and a warning said the lexer
ignored it. ``VALUE 1,5`` parsed as ``1`` (the ``,5`` dropped),
``MOVE 2,75 TO X`` gave the source ``2, 75``, and ``PIC 9(3),99`` was sized
as a five-digit integer with an insertion comma.

Now a comma between digits is the decimal point of a numeric literal (the
token value is the canonical ``2.75``, the source text stays in
``raw_value``), ``.`` is no longer a decimal point, and PICTURE exchanges
the roles of ``,`` and ``.``. A comma followed by a space stays a separator.
Both lexers (pure Python and ``_lexer_fast``) are exercised.
"""

from __future__ import annotations

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.editing import deedit_numeric, edit_numeric
from cobolparser.lexer import TokenType, _CobolLexerPure, declares_decimal_point_comma
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause

try:
    from cobolparser._lexer_fast import CobolLexer as _FastLexer
except ImportError:  # pragma: no cover - pure-Python install
    _FastLexer = None

LEXERS = [pytest.param(_CobolLexerPure, id="pure")]
if _FastLexer is not None:
    LEXERS.append(pytest.param(_FastLexer, id="fast"))

HEADER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DPC.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
"""

PROGRAM = HEADER + """       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 A PIC 9V9 VALUE 1,5.
          05 B PIC 9(3),99.
          05 C PIC Z.ZZ9,99.
          05 D PIC 9(3)V99.
          05 E PIC X(3).
          05 F PIC S9V99 VALUE -0,25.
          05 G PIC 9V99.
             88 G-LOW VALUE 0,01 THRU 1,50.
       PROCEDURE DIVISION.
           MOVE 2,75 TO D.
           MOVE A, B TO E.
           COMPUTE D = A * 1,5 + 3.
           STOP RUN.
"""


def _parse(source: str):
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)
    assert result.ast is not None
    return result


def _items(result):
    return {i.name: i for i in result.ast.find_all_by_type("CobolDataItem")}


class TestLexer:
    @pytest.mark.parametrize("lexer_cls", LEXERS)
    def test_comma_between_digits_is_the_decimal_point(self, lexer_cls):
        tokens = lexer_cls(
            HEADER + "           MOVE 2,75 TO X, Y. MOVE A,B TO C.\n", free_form=True
        ).tokenize()
        numbers = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert [(t.value, t.raw_value) for t in numbers] == [("2.75", "2,75")]
        commas = [t for t in tokens if t.type == TokenType.COMMA]
        assert len(commas) == 2  # "X, Y" and "A,B" stay separators

    @pytest.mark.parametrize("lexer_cls", LEXERS)
    def test_period_between_digits_is_not_a_decimal_point(self, lexer_cls):
        tokens = lexer_cls(
            HEADER + "           DISPLAY 1.5\n", free_form=True
        ).tokenize()
        kinds = [(t.type, t.value) for t in tokens][-5:-2]
        assert kinds == [
            (TokenType.LEVEL_NUMBER, "1"),
            (TokenType.PERIOD, "."),
            (TokenType.LEVEL_NUMBER, "5"),
        ]

    @pytest.mark.parametrize("lexer_cls", LEXERS)
    def test_leading_comma_decimal_after_a_space(self, lexer_cls):
        tokens = lexer_cls(
            HEADER + "           VALUE ,5 X,5\n", free_form=True
        ).tokenize()
        numbers = [t.value for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert numbers == [".5"]

    @pytest.mark.parametrize("lexer_cls", LEXERS)
    def test_default_program_unchanged(self, lexer_cls):
        tokens = lexer_cls("MOVE 1,5 TO X. MOVE 2.5 TO Y.", free_form=True).tokenize()
        numbers = [t.value for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert numbers == ["2.5"]

    def test_detection(self):
        assert declares_decimal_point_comma("SPECIAL-NAMES. DECIMAL-POINT COMMA.")
        assert declares_decimal_point_comma("decimal-point is\n  comma.")
        assert not declares_decimal_point_comma("MOVE X-DECIMAL-POINT IS COMMAS")
        assert not declares_decimal_point_comma("SPECIAL-NAMES. CURRENCY '$'.")


class TestParse:
    def test_no_warning_and_values(self):
        result = _parse(PROGRAM)
        assert not result.errors
        assert not any("DECIMAL-POINT" in w for w in result.warnings)
        items = _items(result)
        assert items["A"].value_clause == "1.5"
        assert items["F"].value_clause == "-0.25"
        (g_low,) = items["G"].to_dict()["condition_names"]
        assert g_low["values"] == ["0.01", "THROUGH:1.50"]

    def test_statements(self):
        result = _parse(PROGRAM)
        moves = result.ast.find_all_by_type("MoveStatement")
        assert moves[0].source == "2.75"
        # Between identifiers the comma is still a separator, not a decimal
        # point -- and a separator is a space (#569).
        assert moves[1].source == "A B"
        compute = result.ast.find_all_by_type("ComputeStatement")[0]
        assert "1.5" in compute.to_dict()["expression"]
        assert "1 , 5" not in compute.to_dict()["expression"]

    def test_picture_sizes(self):
        items = _items(_parse(PROGRAM))
        b = items["B"].picture_clause
        assert (b.pattern, b.size, b.integer_digits, b.decimal_digits) == (
            "9(3),99",
            6,
            3,
            2,
        )
        assert b.is_numeric_edited and b.is_valid
        c = items["C"].picture_clause
        assert (c.pattern, c.size, c.integer_digits, c.decimal_digits) == (
            "Z.ZZ9,99",
            8,
            4,
            2,
        )
        assert c.is_valid, c.validation_errors
        assert c.to_dict()["metadata"]["decimal_point_is_comma"] is True

    def test_picture_clause_default_unchanged(self):
        pic = PictureClause("Z,ZZ9.99", SourceLocation(1, 1, 1))
        assert (pic.size, pic.integer_digits, pic.decimal_digits) == (8, 4, 2)
        swapped = PictureClause(
            "9.999,99", SourceLocation(1, 1, 1), decimal_point_is_comma=True
        )
        # ``.`` is an insertion character, ``,`` the decimal point
        assert (swapped.size, swapped.integer_digits, swapped.decimal_digits) == (
            8,
            4,
            2,
        )
        assert swapped.pattern == "9.999,99" and swapped.is_valid


class TestGenerators:
    def test_edit_and_deedit(self):
        assert (
            edit_numeric("Z.ZZ9,99", "1234.56", decimal_point_is_comma=True)
            == "1.234,56"
        )
        assert deedit_numeric("Z.ZZ9,99", "1.234,56", decimal_point_is_comma=True) == (
            123456,
            False,
        )
        assert edit_numeric("Z,ZZ9.99", "1234.56") == "1,234.56"

    def test_record_image_round_trip(self, tmp_path):
        path = tmp_path / "DPC.cbl"
        path.write_text(PROGRAM)
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=3, seed=3).for_record_image()
        ).generate_from_file(str(path))
        specs = {f.name: f for f in dataset.fields}
        assert specs["C"].decimal_point_is_comma
        assert (specs["B"].integer_digits, specs["B"].decimal_digits) == (3, 2)
        image = dataset.to_records()
        c = specs["C"]
        c_off = sum(f.storage_size for f in dataset.fields[: dataset.fields.index(c)])
        c_text = image[c_off : c_off + 8].decode("latin-1")
        assert c_text[1] == "." and c_text[5] == ",", c_text
        out = tmp_path / "DPC.bin"
        dataset.write_records(str(out))
        decoded = RecordDecoder.from_copybook_file(str(path)).decode_file(str(out))
        assert decoded.error_count == 0
        assert decoded.to_csv() == dataset.to_csv()
