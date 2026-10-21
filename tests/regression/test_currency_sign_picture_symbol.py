"""Regression: a SPECIAL-NAMES currency symbol is a PICTURE editing symbol.

``CURRENCY SIGN IS '£'`` (or ``CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL
'#'``) makes that character usable in a PICTURE string exactly like ``$``.
The lexer did not know it and recorded one "Invalid character" error per
occurrence in ``PIC £££9.99``, failing a valid IBM Enterprise COBOL program;
and the PictureClause then flagged the symbol as invalid and mis-sized the
floating insertion string.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType, _CobolLexerPure
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause
from cobolparser.plugins.core import ErrorRecoveryMode

_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURSYM.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'
           CURRENCY SIGN IS '£'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EUR PIC ###,##9.99.
       01 WS-GBP PIC £££9.99.
       01 WS-USD PIC $$$9.99.
       PROCEDURE DIVISION.
           DISPLAY WS-EUR WS-GBP WS-USD.
           STOP RUN.
"""


def _items(result):
    return {item.name: item for item in result.ast.find_all_by_type("CobolDataItem")}


def test_declared_currency_symbols_lex_and_parse() -> None:
    result = parse_cobol(_SOURCE, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.errors == []
    assert result.warnings == []


def test_picture_keeps_symbol_and_sizes_like_dollar() -> None:
    items = _items(parse_cobol(_SOURCE))
    eur = items["WS-EUR"].picture_clause
    gbp = items["WS-GBP"].picture_clause
    usd = items["WS-USD"].picture_clause
    assert eur.pattern == "###,##9.99"
    assert gbp.pattern == "£££9.99"
    for pic, ref, extra in ((eur, "$$$,$$9.99", 2), (gbp, "$$$9.99", 0)):
        expected = PictureClause(ref, SourceLocation(1, 1))
        assert pic.is_valid, pic.validation_errors
        # The 3-character string 'EUR' fills its one position (#491).
        assert pic.size == expected.size + extra
        assert pic.integer_digits == expected.integer_digits
        assert pic.decimal_digits == expected.decimal_digits
        assert pic.is_numeric_edited
    assert gbp.to_dict()["metadata"]["currency_symbols"] == ["£"]
    assert usd.currency_symbols == frozenset()


def test_undeclared_symbol_is_still_an_error() -> None:
    source = _SOURCE.replace("CURRENCY SIGN IS '£'", "CURRENCY SIGN IS 'X'")
    result = parse_cobol(source)
    assert any("Invalid character: £" in str(e) for e in result.errors)


@pytest.mark.parametrize("lexer_cls", [_CobolLexerPure, CobolLexer])
def test_both_lexers_emit_currency_tokens(lexer_cls) -> None:
    text = "SPECIAL-NAMES. CURRENCY SIGN IS '€'.\n01 A PIC €€9.\n"
    lexer = lexer_cls(text, free_form=True)
    tokens = lexer.tokenize()
    assert not lexer.get_errors()
    assert [t.value for t in tokens if t.type == TokenType.CURRENCY] == ["€", "€"]
