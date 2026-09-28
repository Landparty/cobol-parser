"""Regression: ``&`` concatenation of literals (IBM Enterprise COBOL).

``"AB" & "CD"`` is the one literal ``"ABCD"`` wherever a literal may appear.
The lexer skipped ``&`` as a separator, so a VALUE clause kept only the
first literal (and warned about the rest) and a MOVE source read
``"AB" "CD"``. ``CobolLexer._merge_concatenated_literals`` (shared by the
pure-Python and Cython lexers through ``_post_tokenize``) now joins them.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType


def _literals(source: str, free_form: bool = True) -> list[tuple[str, str | None]]:
    tokens = CobolLexer(source, free_form=free_form).tokenize()
    return [
        (t.value, t.raw_value) for t in tokens if t.type == TokenType.STRING_LITERAL
    ]


def _program(ws: str, proc: str) -> str:
    return "\n".join(
        [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            ws,
            "       PROCEDURE DIVISION.",
            proc,
            "           STOP RUN.",
            "",
        ]
    )


class TestLexerMerge:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('"AB" & "CD"', [("ABCD", None)]),
            ('"AB"&"CD"', [("ABCD", None)]),
            ('"A" & \'B\' & "C"', [("ABC", None)]),
            ("'O''' & \"X\"\"\"", [("O'X\"", None)]),
            ("X\"C1\" & X'C2'", [("C1C2", 'X"C1C2"')]),
            ("N'ab' & N'cd'", [("abcd", "N'abcd'")]),
        ],
    )
    def test_merges(self, source, expected):
        assert _literals(source) == expected

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            # No ampersand: two literals, as before.
            ('"AB" "CD"', [("AB", None), ("CD", None)]),
            ('"AB", "CD"', [("AB", None), ("CD", None)]),
            # Literals of different kinds are not joined.
            ("\"AB\" & X'C1'", [("AB", None), ("C1", "X'C1'")]),
            # Null-terminated literals may not be concatenated.
            ("Z'A' & Z'B'", [("A", "Z'A'"), ("B", "Z'B'")]),
            # An ampersand inside a literal is literal text.
            ('"A & B" "C"', [("A & B", None), ("C", None)]),
        ],
    )
    def test_does_not_merge(self, source, expected):
        assert _literals(source) == expected

    def test_merges_across_lines_and_keeps_newline(self):
        tokens = CobolLexer('VALUE "AB" &\n      "CD".\n', free_form=True).tokenize()
        kinds = [t.type for t in tokens]
        assert kinds == [
            TokenType.VALUE,
            TokenType.STRING_LITERAL,
            TokenType.NEWLINE,
            TokenType.PERIOD,
            TokenType.NEWLINE,
            TokenType.EOF,
        ]
        assert tokens[1].value == "ABCD"
        assert tokens[1].location.line == 1

    def test_fixed_format_lexing(self):
        # Only columns 8-72 are read for the '&': the identification area
        # and the next line's sequence number are not program text.
        source = (
            '000100     MOVE "AB" &'.ljust(72)
            + "ABCD0001\n"
            + '000200         "CD" TO A.\n'
        )
        assert _literals(source, free_form=False) == [("ABCD", None)]


class TestParse:
    def test_value_clause(self):
        result = parse_cobol(_program('       01 A PIC X(4) VALUE "A" & "BC".', ""))
        assert result.warnings == []
        item = result.ast.find_all_by_type("CobolDataItem")[0]
        assert item.to_dict()["value_clause"] == '"ABC"'

    def test_value_clause_continued_on_next_line(self):
        result = parse_cobol(
            _program(
                '       01 A PIC X(4) VALUE "A" &\n                           "BC".',
                "",
            )
        )
        assert result.warnings == []
        item = result.ast.find_all_by_type("CobolDataItem")[0]
        assert item.to_dict()["value_clause"] == '"ABC"'

    def test_move_source(self):
        result = parse_cobol(
            _program("       01 A PIC X(4).", '           MOVE "AB" & "CD" TO A')
        )
        assert result.warnings == []
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.source == '"ABCD"'
        assert move.targets == ["A"]
