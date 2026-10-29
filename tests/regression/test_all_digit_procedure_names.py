"""Regression tests: procedure names made of digits and hyphens only.

A procedure name may consist of digits alone (``1000-0``, ``0100-0200``),
and an arithmetic minus needs a space on both sides, so ``1000-0`` with no
space is one word. The lexer read it as ``1000`` ``-`` ``0``: the paragraph
header and every PERFORM / GO TO naming it were dropped as unparsed tokens,
which surfaced in a corpus sweep as parse warnings on otherwise clean
programs. Names with a letter in them (``1000-INIT``, ``22310-01-TRAITE``)
were never affected.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType


def _program(statements: str, paragraphs: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  X  PIC 9 VALUE 1.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{statements}"
        "           GOBACK.\n"
        f"{paragraphs}"
    )


_PARAGRAPHS = (
    "       1000-0.\n"
    "           DISPLAY 'A'.\n"
    "       1000-9.\n"
    "           EXIT.\n"
    "       20-10.\n"
    "           EXIT.\n"
)


def _words(source: str) -> list[tuple[str, str]]:
    return [
        (t.type.name, t.value)
        for t in CobolLexer(source, free_form=True).tokenize()
        if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE, TokenType.EOF)
    ]


@pytest.mark.parametrize(
    "statement, targets",
    [
        ("           PERFORM 1000-0\n", ["1000-0"]),
        ("           PERFORM 1000-0 THRU 1000-9\n", ["1000-0"]),
        ("           PERFORM 20-10 2 TIMES\n", ["20-10"]),
    ],
)
def test_perform_of_an_all_digit_paragraph(statement, targets):
    result = parse_cobol(_program(statement, _PARAGRAPHS), filename="T.cbl")
    assert result.success, [str(e) for e in result.errors]
    assert result.warnings == []
    performs = result.ast.find_all_by_type("PerformStatement")
    assert [p.target_paragraph for p in performs] == targets
    names = [p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")]
    assert names == ["MAIN-PARA", "1000-0", "1000-9", "20-10"]


def test_go_to_depending_on_all_digit_paragraphs():
    statement = "           GO TO 1000-0 20-10 DEPENDING ON X\n"
    result = parse_cobol(_program(statement, _PARAGRAPHS), filename="T.cbl")
    assert result.success, [str(e) for e in result.errors]
    assert result.warnings == []


class TestLexing:
    def test_hyphenated_digits_are_one_word(self):
        assert _words("PERFORM 1000-0 THRU 0100-0200.") == [
            ("PERFORM", "PERFORM"),
            ("IDENTIFIER", "1000-0"),
            ("IDENTIFIER", "THRU"),
            ("IDENTIFIER", "0100-0200"),
            ("PERIOD", "."),
        ]

    @pytest.mark.parametrize(
        "source",
        [
            "COMPUTE X = 1000 - 0",  # spaced: arithmetic
            "COMPUTE X = 1000-0.5",  # a decimal abuts it
        ],
    )
    def test_arithmetic_is_unchanged(self, source):
        assert ("MINUS", "-") in _words(source)

    def test_sql_arithmetic_is_unchanged(self):
        words = _words("EXEC SQL SELECT A INTO :X FROM T WHERE B = 10-5 END-EXEC")
        assert ("MINUS", "-") in words
        assert ("IDENTIFIER", "10-5") not in words
