"""Regression: a decoded literal containing a double quote must be re-quoted
with that quote DOUBLED, not emitted raw.

A real copybook (CICS's DFHAID) legitimately declares
``05 DFHTRIG PIC X VALUE IS '"'`` -- a single-quote-delimited literal whose
content is one ``"`` character. The lexer decodes it to that one character;
every parser that re-emits a literal as COBOL source text used to wrap it in
``"..."`` verbatim, producing a three-quote, unterminated literal. Downstream
consumers that re-emit the clause (mockymock's generated
UT-RESET-WORKING-STORAGE paragraph) then desynchronized GnuCOBOL's tokenizer
for the rest of the program, which surfaced as a bogus ``invalid symbol '%'``
error lines away from the real cause.
"""

from cobolparser import parse_cobol
from cobolparser._literals import quote_literal

DQ = '"'


def _working_storage(ast):
    return {
        item.name: item
        for item in ast.get_division("DATA")._sections["WORKING-STORAGE"].data_items
    }


def test_quote_literal_doubles_embedded_quotes():
    assert quote_literal(DQ) == '""""'
    assert quote_literal('A"B') == '"A""B"'
    assert quote_literal("PLAIN") == '"PLAIN"'
    assert quote_literal("'") == '"\'"'
    assert quote_literal(None) == '""'


def _parse(source: str):
    result = parse_cobol(source, filename="quotes.cbl")
    assert result.errors == []
    return result.ast


def test_value_clause_with_embedded_double_quote_round_trips():
    ast = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUOTETST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  DFHTRIG PIC X VALUE IS '\"'.\n"
        "       01  WS-MIXED PIC X(3) VALUE 'A\"B'.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY DFHTRIG.\n"
    )
    items = _working_storage(ast)
    # Four quotes: the two delimiters plus the doubled content character.
    assert items["DFHTRIG"].value_clause == '""""'
    assert items["WS-MIXED"].value_clause == '"A""B"'


def test_value_all_literal_with_embedded_double_quote_round_trips():
    ast = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUOTEALL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-BAR PIC X(5) VALUE ALL '\"'.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY WS-BAR.\n"
    )
    assert _working_storage(ast)["WS-BAR"].value_clause == 'ALL """"'


def test_reemitted_value_clause_reparses_as_the_same_literal():
    """The round-trip property the fix exists for: feeding a re-emitted
    VALUE clause back through the parser yields the identical clause."""
    ast = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUOTERT.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  DFHTRIG PIC X VALUE IS '\"'.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY DFHTRIG.\n"
    )
    emitted = _working_storage(ast)["DFHTRIG"].value_clause
    reparsed = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUOTERT.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"       01  DFHTRIG PIC X VALUE IS {emitted}.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY DFHTRIG.\n"
    )
    assert _working_storage(reparsed)["DFHTRIG"].value_clause == emitted


def test_move_and_display_literals_double_embedded_quotes():
    ast = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. QUOTEMV.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-CH PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           MOVE '\"' TO WS-CH\n"
        "           DISPLAY '\"' WS-CH.\n"
    )
    move = ast.find_all_by_type("MoveStatement")[0]
    assert move.source == '""""'
    display = ast.find_all_by_type("DisplayStatement")[0]
    assert '""""' in display.display_items
