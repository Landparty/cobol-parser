"""Regression tests: VALUE/PICTURE clause operands that start on the line
after the VALUE/PIC/PICTURE keyword (or after an optional IS), with no
fixed-format `-` continuation indicator required -- ordinary multi-line
clause continuation, legal COBOL, the same shape every other clause in this
division already tolerates.

Two independent, previously-unhandled shapes:

- `_parse_value_clause` had no NEWLINE handling at all: `VALUE\\n  "lit".`
  (or `VALUE IS\\n  "lit".`) left the literal on the next physical line
  unconsumed. The clause loop then saw no value returned, moved on, and
  the orphaned literal token was dropped as "clause not fully supported"
  by the fallback unknown-token warning.
- `_parse_picture_clause` had no branch for TokenType.IS at all, so
  `PIC IS X(99)` (the optional-IS form of PICTURE, seen in the NIST
  CCVS85 corpus's own boilerplate) left "IS" unconsumed; the same
  fallback then dropped IS, the whole pattern, AND misread the numeric
  literal inside the parentheses as a new data item's level number.

Both matter downstream: mockymock's working-storage reset restores each
item to its declared VALUE clause, and a dropped clause changes program
behavior silently; a dropped PICTURE loses the item's type/length entirely.
Found via mocky-mock's examples/nist-cobol85/IC101A.CBL and IC116M.CBL,
both of which contain the CCVS85 corpus's shared boilerplate header using
exactly these two shapes.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALPICREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="valpicreg.cbl")
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return result


def _working_storage_items(ws_source: str):
    result = _parse(ws_source)
    data = result.ast.get_division("DATA")
    for section in getattr(data, "sections", data.children):
        name = getattr(section, "_own_section_name", None) or getattr(
            section, "section_name", None
        )
        if name and "WORKING-STORAGE" in name.upper():
            return [c for c in section.children if getattr(c, "name", None)]
    raise AssertionError("no WORKING-STORAGE section found")


def _single_item(ws_source: str):
    items = _working_storage_items(ws_source)
    named = [i for i in items if not i.name.startswith("ANONYMOUS")]
    assert len(named) == 1, [i.name for i in items]
    return named[0]


class TestValueClauseContinuationLine:
    def test_value_literal_on_the_next_line(self):
        item = _single_item(
            "       01  WS-X   PIC X(9)   VALUE\n" '                  "CONTINUED".\n'
        )
        assert item.value_clause == '"CONTINUED"'

    def test_value_is_literal_on_the_next_line(self):
        item = _single_item(
            "       01  WS-X   PIC X(9)   VALUE IS\n" '                  "CONTINUED".\n'
        )
        assert item.value_clause == '"CONTINUED"'

    def test_value_is_on_its_own_line_before_the_literal(self):
        item = _single_item(
            "       01  WS-X   PIC X(9)   VALUE\n"
            "                  IS\n"
            '                  "CONTINUED".\n'
        )
        assert item.value_clause == '"CONTINUED"'


class TestPictureIsClause:
    def test_picture_is_x(self):
        item = _single_item("       01  WS-X   PIC IS X(99)   VALUE SPACE.\n")
        assert item.picture_clause is not None
        assert item.picture_clause.pattern == "X(99)"
        assert item.value_clause == "SPACE"

    def test_picture_is_9(self):
        item = _single_item("       01  WS-N   PICTURE IS 9(5).\n")
        assert item.picture_clause is not None
        assert item.picture_clause.pattern == "9(5)"

    def test_picture_is_does_not_swallow_the_following_sibling_item(self):
        items = _working_storage_items(
            "       01  WS-X   PIC IS X(2)   VALUE SPACE.\n"
            "       01  WS-Y   PIC 9(3)      VALUE ZERO.\n"
        )
        named = {i.name: i for i in items if not i.name.startswith("ANONYMOUS")}
        assert set(named) == {"WS-X", "WS-Y"}
        assert named["WS-X"].picture_clause.pattern == "X(2)"
        assert named["WS-Y"].picture_clause.pattern == "9(3)"
