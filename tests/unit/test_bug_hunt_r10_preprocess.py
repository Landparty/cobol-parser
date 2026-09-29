"""Bug hunt round 10: lexer, preprocessing and CLI regressions.

Each test pins one defect that produced a wrong answer before its fix:

* ``UX"..."`` (UTF-8 hex) literals lexed as the word ``UX`` plus a text literal.
* A commented-out ``*> DECIMAL-POINT IS COMMA`` (or one inside a literal)
  switched the whole program's decimal point.
* ``tokenize_cobol`` fabricated COMMENT tokens out of free-format lines
  (after ``>>SOURCE FORMAT IS FREE``) whose column 7 held ``D`` / ``*`` / ``/``.
* ``parse`` / ``preprocess --define`` blanked ``>>SOURCE FORMAT IS FREE``
  before normalization, so every free-format line was column-sliced.
* ``>>EVALUATE FALSE`` and ``>>WHEN low THRU high`` never selected a branch.
* ``>>IF`` compared ``'nan'`` / ``'INF'`` text as floats.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser import parse_cobol
from cobolparser.cli import main
from cobolparser.lexer import (
    CobolLexer,
    TokenType,
    _declared_currency_symbols,
    declares_decimal_point_comma,
    tokenize_cobol,
)
from cobolparser.preprocess import preprocess_conditional_compilation


def _lex(text: str) -> tuple[list, CobolLexer]:
    lexer = CobolLexer(text, free_form=True)
    tokens = [
        t for t in lexer.tokenize() if t.type not in (TokenType.NEWLINE, TokenType.EOF)
    ]
    return tokens, lexer


def _run_cli(argv: list[str]) -> None:
    with patch("sys.argv", ["cobol-parser", "--no-config", *argv]):
        main()


# -- UX literals ---------------------------------------------------------------


class TestUxLiteral:
    def test_ux_utf8_hex_literal_is_one_token(self) -> None:
        tokens, lexer = _lex('MOVE UX"C3A9" TO A.')
        assert [t.type for t in tokens[:3]] == [
            TokenType.MOVE,
            TokenType.STRING_LITERAL,
            TokenType.TO,
        ]
        assert tokens[1].value == "C3A9"
        assert tokens[1].raw_value == 'UX"C3A9"'
        assert lexer.warnings == []

    def test_lowercase_ux_and_odd_digit_warning(self) -> None:
        tokens, lexer = _lex("MOVE ux'4' TO A.")
        assert tokens[1].type is TokenType.STRING_LITERAL
        assert tokens[1].raw_value == "ux'4'"
        assert any("odd number of hex digits" in w for w in lexer.warnings)

    def test_ux_prefixed_word_is_still_an_identifier(self) -> None:
        tokens, _ = _lex("MOVE UX-VAR TO A.")
        assert tokens[1].type is TokenType.IDENTIFIER
        assert tokens[1].value == "UX-VAR"

    def test_ux_literal_parses_as_move_source(self) -> None:
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. U1.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01 WS-U PIC U(4).\n"
            "PROCEDURE DIVISION.\n"
            '    MOVE UX"C3A9" TO WS-U\n'
            "    STOP RUN.\n"
        )
        result = parse_cobol(src, free_form=True)
        assert result.errors == []
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.to_dict()["operands"] == ['UX"C3A9"', "WS-U"]


# -- SPECIAL-NAMES scans ignore comments and literals ------------------------------


_DP_PROGRAM = """IDENTIFICATION DIVISION.
PROGRAM-ID. DP.
ENVIRONMENT DIVISION.
CONFIGURATION SECTION.
SPECIAL-NAMES.
{clause}
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9V99.
PROCEDURE DIVISION.
    MOVE {literal} TO WS-A
    STOP RUN.
"""


class TestSpecialNamesScanSkipsComments:
    def test_commented_out_decimal_point_is_comma_is_ignored(self) -> None:
        src = _DP_PROGRAM.format(
            clause="*> DECIMAL-POINT IS COMMA.\n    CURRENCY SIGN IS '$'.",
            literal="2.5",
        )
        result = parse_cobol(src, free_form=True)
        assert result.errors == []
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.to_dict()["operands"] == ["2.5", "WS-A"]

    def test_real_decimal_point_is_comma_still_applies(self) -> None:
        src = _DP_PROGRAM.format(
            clause="    DECIMAL-POINT IS COMMA. *> European build", literal="2,5"
        )
        result = parse_cobol(src, free_form=True)
        assert result.errors == []
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.to_dict()["operands"][0] in ("2.5", "2,5")

    @pytest.mark.parametrize(
        ("source", "fixed", "expected"),
        [
            ("SPECIAL-NAMES.\n*> DECIMAL-POINT IS COMMA.", False, False),
            ('DISPLAY "DECIMAL-POINT IS COMMA"', False, False),
            ("       DECIMAL-POINT\n       IS COMMA.", False, True),
            ("      * DECIMAL-POINT IS COMMA.", True, False),
            ("       DECIMAL-POINT IS COMMA.", True, True),
        ],
    )
    def test_decimal_point_scan(self, source: str, fixed: bool, expected: bool) -> None:
        assert declares_decimal_point_comma(source, fixed_format=fixed) is expected

    def test_commented_out_currency_sign_declares_nothing(self) -> None:
        assert _declared_currency_symbols("*> CURRENCY SIGN IS '#'.") == frozenset()
        assert _declared_currency_symbols("CURRENCY SIGN IS '#'. *> x") == {"#"}


# -- tokenize: free-format lines have no indicator column ------------------------------


def test_tokenize_free_format_lines_have_no_indicator_column() -> None:
    src = (
        "000100 IDENTIFICATION DIVISION.\n"
        "000200 PROGRAM-ID. SF4.\n"
        "000300 DATA DIVISION.\n"
        "000400 WORKING-STORAGE SECTION.\n"
        "000500 01 WS-V PIC 9.\n"
        "000600 01 X PIC 9.\n"
        "000700 PROCEDURE DIVISION.\n"
        "000800*    A REAL COMMENT\n"
        "000900 >>SOURCE FORMAT IS FREE\n"
        "    ADD WS-V TO X\n"
        "      / 2\n"
        "STOP RUN.\n"
    )
    comments = [
        (t.location.line, t.value)
        for t in tokenize_cobol(src)
        if t.type is TokenType.COMMENT
    ]
    assert comments == [(8, "*    A REAL COMMENT")]


# -- CLI --define keeps >>SOURCE FORMAT for normalization ------------------------------


_SF_PROGRAM = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. SF3.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01 WS-A PIC X(10).
000600 01 WS-B PIC X(10).
000700 PROCEDURE DIVISION.
000800     MOVE "A" TO WS-A.
000900     MOVE "B" TO WS-B.
001000 >>SOURCE FORMAT IS FREE
DISPLAY "FREE LINE".
>>IF DBG DEFINED
DISPLAY "DEBUG".
>>END-IF
STOP RUN.
"""


class TestDefineKeepsSourceFormat:
    def test_parse_define_keeps_source_format_free(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        program = tmp_path / "sf3.cbl"
        program.write_text(_SF_PROGRAM)
        _run_cli(["parse", str(program), "--define", "DBG", "--errors", "--compact"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["errors"] == []
        assert data["warnings"] == []
        assert "unknown compiler directive" not in captured.err
        text = json.dumps(data)
        assert "FREE LINE" in text
        assert "DEBUG" in text

    def test_preprocess_define_keeps_source_format_free(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        program = tmp_path / "sf3.cbl"
        program.write_text(_SF_PROGRAM)
        _run_cli(["preprocess", str(program), "--define", "DBG"])
        lines = capsys.readouterr().out.splitlines()
        assert lines[10] == 'DISPLAY "FREE LINE".'
        assert lines[12] == 'DISPLAY "DEBUG".'
        assert lines[14] == "STOP RUN."


# -- >>EVALUATE FALSE / >>WHEN ... THRU ... ----------------------------------------------


def _kept(source: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(source, warnings=warnings)
    return [line for line in out.split("\n") if line], warnings


class TestEvaluateDirective:
    def test_when_thru_range_selects_branch(self) -> None:
        kept, warnings = _kept(
            ">>DEFINE LVL AS 3\n>>EVALUATE LVL\n>>WHEN 1 THRU 5\nLOW\n"
            ">>WHEN OTHER\nHIGH\n>>END-EVALUATE\n"
        )
        assert kept == ["LOW"]
        assert warnings == []

    def test_when_through_range_outside_is_not_selected(self) -> None:
        kept, _ = _kept(
            ">>DEFINE LVL AS 3\n>>EVALUATE LVL\n>>WHEN 4 THROUGH 9\nIN\n"
            ">>WHEN OTHER\nOUT\n>>END-EVALUATE\n"
        )
        assert kept == ["OUT"]

    def test_evaluate_false_selects_first_false_condition(self) -> None:
        kept, warnings = _kept(
            ">>DEFINE LVL AS 3\n>>EVALUATE FALSE\n>>WHEN LVL = 3\nIS-3\n"
            ">>WHEN LVL = 4\nNOT-4\n>>WHEN OTHER\nOTHER\n>>END-EVALUATE\n"
        )
        assert kept == ["NOT-4"]
        assert warnings == []

    def test_evaluate_false_undefined_symbol_is_not_selected(self) -> None:
        kept, warnings = _kept(
            ">>EVALUATE FALSE\n>>WHEN NOPE = 1\nX\n>>WHEN OTHER\nY\n>>END-EVALUATE\n"
        )
        assert kept == ["Y"]
        assert any("NOPE" in w for w in warnings)


# -- numeric comparison only for numeric literals -------------------------------------


class TestDirectiveNumbers:
    def test_nan_text_equals_itself(self) -> None:
        kept, _ = _kept(">>DEFINE X AS 'nan'\n>>IF X = 'nan'\nEQ\n>>END-IF\n")
        assert kept == ["EQ"]

    def test_inf_and_infinity_are_different_text(self) -> None:
        kept, _ = _kept(">>DEFINE Y AS 'INF'\n>>IF Y = 'Infinity'\nBAD\n>>END-IF\n")
        assert kept == []

    def test_decimal_numbers_still_compare_numerically(self) -> None:
        kept, _ = _kept(
            ">>DEFINE Z AS 2.50\n>>IF Z = 2.5\nNUM\n>>END-IF\n"
            ">>IF Z > -1\nGT\n>>END-IF\n"
        )
        assert kept == ["NUM", "GT"]
