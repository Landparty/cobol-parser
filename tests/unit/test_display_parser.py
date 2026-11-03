"""Tests for DisplayStatementParser -- subscripted DISPLAY operands.

Targets a real-world gap found via mockymock's corpus sweep against
legacy-application/cobol/ACCTMNT.cbl:
`DISPLAY 'ACCTMNT: DORMANT ACCOUNTS FLAGGED=' SQLERRD(3)` -- a subscripted
identifier (SQLERRD is an OCCURS array, here the generated SQLCA's
SQLERRD(6)) as a DISPLAY item. The parser used to stop at the bare
LEFT_PAREN token (neither STRING_LITERAL, IDENTIFIER, nor NUMERIC_LITERAL),
dropping the subscript and everything after it from the AST with a
PARSE_WARNING.
"""

from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TABLE PIC S9(9) OCCURS 6 TIMES.
       01  WS-IDX   PIC 9(1) VALUE 1.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestDisplaySubscriptedOperand:
    def test_display_subscripted_identifier(self):
        """DISPLAY 'literal' identifier(subscript) -- the ACCTMNT shape."""
        result = parse_cobol(_prog("           DISPLAY 'FLAGGED=' WS-TABLE(3)."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert len(stmts) == 1
        assert stmts[0].display_items == ['"FLAGGED="', "WS-TABLE(3)"]

    def test_display_subscripted_identifier_by_data_name(self):
        """Subscript is a data-name, not a literal index."""
        result = parse_cobol(_prog("           DISPLAY WS-TABLE(WS-IDX)."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["WS-TABLE(WS-IDX)"]

    def test_display_plain_identifier_unaffected(self):
        """A bare (non-subscripted) identifier is unaffected by the fix."""
        result = parse_cobol(_prog("           DISPLAY WS-IDX."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["WS-IDX"]

    def test_display_multiple_items_one_subscripted(self):
        """A subscripted item followed by more items on the same DISPLAY."""
        result = parse_cobol(_prog("           DISPLAY WS-TABLE(1) ' - ' WS-TABLE(2)."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["WS-TABLE(1)", '" - "', "WS-TABLE(2)"]

    def test_display_subscript_with_nested_function_call(self):
        """A subscript containing its own parens (an intrinsic function
        call, e.g. `TAB(FUNCTION MOD(3 2))`) must round-trip its nested
        parens literally rather than flattening them into a single space-
        joined pair -- a real gap flagged in review of the initial fix."""
        result = parse_cobol(_prog("           DISPLAY WS-TABLE(FUNCTION MOD(3 2))."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["WS-TABLE(FUNCTION MOD(3 2))"]

    def test_display_multi_dimension_subscript(self):
        """A two-dimension subscript (`TAB(I J)`) keeps a single space
        between the two index tokens (not glued together, not dropped)."""
        result = parse_cobol(_prog("           DISPLAY WS-TABLE(WS-IDX WS-IDX)."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["WS-TABLE(WS-IDX WS-IDX)"]


class TestDisplayIntrinsicFunction:
    """``FUNCTION name(args)`` is one DISPLAY item, rendered the way MOVE /
    CALL render it. It used to split into a bare ``"FUNCTION"`` item and the
    call that follows it."""

    def test_function_with_arguments_is_one_item(self):
        result = parse_cobol(
            _prog("           DISPLAY FUNCTION TRIM(WS-IDX) ' ' WS-IDX.")
        )
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ["FUNCTION TRIM(WS-IDX)", '" "', "WS-IDX"]

    def test_function_without_arguments_is_one_item(self):
        result = parse_cobol(_prog("           DISPLAY 'D=' FUNCTION CURRENT-DATE."))
        assert not result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[0].display_items == ['"D="', "FUNCTION CURRENT-DATE"]

    def test_function_text_matches_move_source(self):
        result = parse_cobol(
            _prog(
                "           DISPLAY FUNCTION UPPER-CASE(WS-IDX).\n"
                "           MOVE FUNCTION UPPER-CASE(WS-IDX) TO WS-IDX."
            )
        )
        display = result.ast.find_statements("DISPLAY")[0]
        move = result.ast.find_statements("MOVE")[0]
        assert display.display_items == [move.source]


class TestDisplayScreenPhrases:
    """Screen DISPLAYs (2026-11-03, mockymock's sample sweep: a positioned
    DISPLAY switches GnuCOBOL to screen mode, so a test runner has to know
    one when it sees one)."""

    def _display(self, text: str):
        result = parse_cobol(_prog(f"           {text}\n           DISPLAY 'NEXT'."))
        assert not result.warnings, result.warnings
        stmts = result.ast.find_statements("DISPLAY")
        assert stmts[-1].display_items == ['"NEXT"']
        return stmts[0]

    def test_at_and_attributes(self):
        stmt = self._display("DISPLAY 'A' AT 0101 WITH BLANK SCREEN")
        assert stmt.display_items == ['"A"']
        assert stmt.screen_phrases == ["AT 0101", "BLANK SCREEN"]
        assert stmt.is_screen_display

    def test_line_column_without_at(self):
        stmt = self._display("DISPLAY 'A' LINE 3 COLUMN 5 HIGHLIGHT")
        assert stmt.display_items == ['"A"']
        assert stmt.screen_phrases == ["LINE 3", "COLUMN 5", "HIGHLIGHT"]

    def test_col_and_colour_by_data_name(self):
        stmt = self._display(
            "DISPLAY WS-IDX AT LINE 3 COL WS-IDX\n"
            "               WITH FOREGROUND-COLOR IS 2"
        )
        assert stmt.display_items == ["WS-IDX"]
        assert stmt.screen_phrases == [
            "AT LINE 3",
            "COLUMN WS-IDX",
            "FOREGROUND-COLOR IS 2",
        ]

    def test_one_position_per_item(self):
        stmt = self._display("DISPLAY 'YOU: ' AT 0204 WS-IDX AT 0217")
        assert stmt.display_items == ['"YOU: "', "WS-IDX"]
        assert stmt.screen_phrases == ["AT 0204", "AT 0217"]

    def test_omitted_clears_the_screen(self):
        stmt = self._display("DISPLAY OMITTED AT 0101 WITH BLANK SCREEN")
        assert stmt.display_items == ["OMITTED"]
        assert stmt.is_screen_display

    def test_upon_crt_is_a_screen_display(self):
        assert self._display("DISPLAY 'A' UPON CRT").is_screen_display

    def test_a_plain_display_is_not(self):
        stmt = self._display("DISPLAY 'A' WS-IDX WITH NO ADVANCING")
        assert stmt.screen_phrases == []
        assert not stmt.is_screen_display
        assert "screen_phrases" not in stmt.to_dict()

    def test_a_lone_attribute_word_is_an_item(self):
        """`DISPLAY BELL` shows a SYMBOLIC CHARACTER named BELL (#519)."""
        stmt = self._display("DISPLAY BELL")
        assert stmt.display_items == ["BELL"]
        assert not stmt.is_screen_display
