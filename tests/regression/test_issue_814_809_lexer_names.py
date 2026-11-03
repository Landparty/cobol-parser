"""Regression tests for lexer name gluing.

#814: a COPY REPLACING placeholder name right after ``NOT(`` / ``AND(`` /
``OR(`` / ``UNTIL(`` stays one IDENTIFIER, as it does with a space.

#809: with ``CURRENCY ... PICTURE SYMBOL '#'``, a data name holding '#'
(``WS-#N``) stays one name; the '#' is a currency symbol only inside a
PICTURE string.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType


def _values(text: str) -> list[str]:
    return [
        t.value
        for t in CobolLexer("           " + text).tokenize()
        if t.type not in (TokenType.EOF, TokenType.NEWLINE)
    ]


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("IF NOT(FLG-(T)-OK)", "FLG-(T)-OK"),
        ("IF NOT (FLG-(T)-OK)", "FLG-(T)-OK"),
        ("IF A = 1 AND(FLG-(T)-OK)", "FLG-(T)-OK"),
        ("IF A = 1 OR(:P:-OK)", ":P:-OK"),
        ("PERFORM UNTIL(FLG-(T)-OK)", "FLG-(T)-OK"),
    ],
)
def test_placeholder_after_keyword_paren(text: str, name: str) -> None:
    values = _values(text)
    assert name in values
    assert values[-1] == ")"
    assert values[-3] == "("


def test_keyword_paren_without_placeholder_untouched() -> None:
    assert _values("IF NOT(A = 1)") == ["IF", "NOT", "(", "A", "=", "1", ")"]


_CURRENCY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMT PIC ###9.99.
       01 WS-#N PIC 9.
       PROCEDURE DIVISION.
           MOVE 1 TO WS-#N.
           GOBACK.
"""


def test_currency_symbol_inside_name() -> None:
    result = parse_cobol(_CURRENCY_SOURCE, "T.cbl")
    assert result.ast is not None
    items = {
        n.name: n.picture_clause.pattern
        for n in result.ast.find_all_by_type("DataItem")
    }
    assert items == {"WS-AMT": "###9.99", "WS-#N": "9"}
    moves = [m.targets for m in result.ast.find_all_by_type("MoveStatement")]
    assert moves == [["WS-#N"]]
    assert not any("Unparsed token" in w for w in result.warnings)


def test_currency_symbol_still_currency_in_picture() -> None:
    tokens = CobolLexer(_CURRENCY_SOURCE).tokenize()
    line9 = [t for t in tokens if t.location and t.location.line == 9]
    assert [t.type for t in line9 if t.value == "#"] == [TokenType.CURRENCY] * 3
