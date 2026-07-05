"""Regression tests: numeric VALUE clause literals that lex as LEVEL_NUMBER.

The lexer types any 1-2 digit integer as TokenType.LEVEL_NUMBER regardless
of context (including inside PIC 9(4) and after VALUE). _parse_value_clause
previously only accepted NUMERIC_LITERAL, so `VALUE 5` / `VALUE 42` silently
lost the literal (value_clause=None) and the orphaned LEVEL_NUMBER token then
started a bogus anonymous data item. `VALUE IS <n>` and signed literals
(`VALUE -5`) were dropped the same way, and level-88 items lost small numeric
values entirely (values == []).

These matter downstream: mockymock's working-storage reset restores each item
to its declared VALUE clause, so a dropped VALUE silently changes the
behaviour of the program under test.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _working_storage_items(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="valreg.cbl")
    assert result.success, result.errors
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


class TestNumericValueLiterals:
    def test_one_digit_value_literal(self):
        item = _single_item("       01  WS-X  PIC 9(4) VALUE 5.\n")
        assert item.value_clause == "5"

    def test_two_digit_value_literal(self):
        item = _single_item("       01  WS-X  PIC 9(4) VALUE 42.\n")
        assert item.value_clause == "42"

    def test_three_digit_value_literal_still_works(self):
        item = _single_item("       01  WS-X  PIC 9(4) VALUE 100.\n")
        assert item.value_clause == "100"

    def test_value_is_small_numeric(self):
        item = _single_item("       01  WS-X  PIC 9(4) VALUE IS 5.\n")
        assert item.value_clause == "5"

    def test_value_is_large_numeric(self):
        item = _single_item("       01  WS-X  PIC 9(4) VALUE IS 100.\n")
        assert item.value_clause == "100"

    def test_value_is_string_literal(self):
        item = _single_item('       01  WS-X  PIC X(3) VALUE IS "ABC".\n')
        assert item.value_clause == '"ABC"'

    def test_negative_value_literal(self):
        item = _single_item("       01  WS-X  PIC S9(4) VALUE -5.\n")
        assert item.value_clause == "-5"

    def test_positive_signed_decimal_value_literal(self):
        item = _single_item("       01  WS-X  PIC S9V9 VALUE +2.5.\n")
        assert item.value_clause == "+2.5"

    def test_no_anonymous_item_spawned_by_dropped_literal(self):
        items = _working_storage_items(
            "       01  WS-X  PIC 9(4) VALUE 5.\n       01  WS-Y  PIC X.\n"
        )
        names = [i.name for i in items]
        assert names == ["WS-X", "WS-Y"]

    def test_group_child_with_small_numeric_value(self):
        items = _working_storage_items(
            "       01  WS-GROUP.\n"
            "           05  WS-A  PIC 9(3) VALUE 5.\n"
            "           05  WS-B  PIC X(5).\n"
        )
        assert [i.name for i in items] == ["WS-GROUP"]
        children = {c.name: c for c in items[0].children if getattr(c, "name", None)}
        assert set(children) == {"WS-A", "WS-B"}
        assert children["WS-A"].value_clause == "5"

    def test_level_77_with_small_numeric_value(self):
        items = _working_storage_items("       77  WS-COUNT  PIC 9(4) VALUE 7.\n")
        assert [i.name for i in items] == ["WS-COUNT"]
        assert items[0].value_clause == "7"


class TestConditionNameValues:
    def test_88_small_numeric_value(self):
        items = _working_storage_items(
            "       01  WS-FLAG  PIC 9 VALUE 0.\n" "           88  FLAG-ON  VALUE 1.\n"
        )
        assert [i.name for i in items] == ["WS-FLAG"]
        condition = next(
            c for c in items[0].children if getattr(c, "name", None) == "FLAG-ON"
        )
        assert condition.values == ["1"]

    def test_88_large_numeric_value_still_works(self):
        items = _working_storage_items(
            "       01  WS-FLAG  PIC 9(3) VALUE 0.\n"
            "           88  FLAG-BIG  VALUE 100.\n"
        )
        condition = next(
            c for c in items[0].children if getattr(c, "name", None) == "FLAG-BIG"
        )
        assert condition.values == ["100"]

    def test_88_small_numeric_through_range(self):
        items = _working_storage_items(
            "       01  WS-GRADE  PIC 9(2) VALUE 0.\n"
            "           88  GRADE-LOW  VALUE 1 THROUGH 9.\n"
        )
        condition = next(
            c for c in items[0].children if getattr(c, "name", None) == "GRADE-LOW"
        )
        assert condition.values == ["1", "THROUGH:9"]

    def test_88_negative_numeric_value(self):
        items = _working_storage_items(
            "       01  WS-TEMP  PIC S9(2) VALUE 0.\n"
            "           88  TEMP-FREEZING  VALUE -1.\n"
        )
        condition = next(
            c for c in items[0].children if getattr(c, "name", None) == "TEMP-FREEZING"
        )
        assert condition.values == ["-1"]
