"""A fixed-format program whose code lines are tab-indented after a
comment banner must still be read as fixed format.

Format detection used to run after the pre-IDENTIFICATION-DIVISION banner
had been blanked, so it only sampled the tab-indented lines, classified
the source as free-form, and parsed a column-7 comment as a live MOVE.
`tokenize` (which detects on the raw source) still saw the comment, so the
two subcommands disagreed."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.lexer import tokenize_cobol

BANNER = "".join(f"      * BANNER LINE {n}\n" for n in range(1, 7))
SOURCE = BANNER + (
    "\tIDENTIFICATION DIVISION.\n"
    "\tPROGRAM-ID. TABPGM.\n"
    "\tPROCEDURE DIVISION.\n"
    '\t    DISPLAY "HI"\n'
    "      *    MOVE A TO B\n"
    "\t    STOP RUN.\n"
)


def test_comment_line_after_a_banner_is_not_parsed_as_a_statement() -> None:
    result = parse_cobol(SOURCE)
    assert result.ast is not None
    kinds = [type(s).__name__ for s in result.ast.get_all_statements()]
    assert kinds == ["DisplayStatement", "StopStatement"]


def test_parse_and_tokenize_agree_the_line_is_a_comment() -> None:
    values = [t.value for t in tokenize_cobol(SOURCE)]
    assert "*    MOVE A TO B" in values
    assert "MOVE" not in values
