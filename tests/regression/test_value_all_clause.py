"""Regression tests: VALUE ALL <literal> clauses.

`ALL` lexes as a FIGURATIVE_CONSTANT, so _parse_value_clause previously
consumed it as a complete value and left the repeated literal behind as an
unparsed token — `05 FILLER PIC X(133) VALUE ALL '='.` produced
value_clause="ALL" plus an "Unparsed token '='" content-drop warning.

These matter downstream: mockymock refuses any program whose parse reports
a warning (PARSE_WARNING, fail-closed), so a corpus program using the
common `VALUE ALL '='` report-separator idiom could not be mocked at all.
The returned string must also round-trip as legal COBOL, because
mockymock's working-storage reset splices it into `MOVE <value> TO <item>`.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALLREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="vallreg.cbl")
    assert result.success, result.errors
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


class TestValueAllLiterals:
    def test_all_string_literal(self):
        item = _single_item("       01  WS-X  PIC X(10) VALUE ALL '='.\n")
        assert item.value_clause == 'ALL "="'

    def test_value_is_all_literal(self):
        item = _single_item("       01  WS-X  PIC X(4) VALUE IS ALL 'AB'.\n")
        assert item.value_clause == 'ALL "AB"'

    def test_all_figurative_constant(self):
        item = _single_item("       01  WS-X  PIC X(4) VALUE ALL ZEROS.\n")
        assert item.value_clause == "ALL ZEROS"

    def test_all_literal_on_continuation_line(self):
        item = _single_item(
            "       01  WS-X  PIC X(4)\n"
            "                 VALUE ALL\n"
            "                 '*'.\n"
        )
        assert item.value_clause == 'ALL "*"'

    def test_all_literal_on_filler_emits_no_warning(self):
        result = _parse(
            "       01  WS-SEP.\n" "           05  FILLER PIC X(133) VALUE ALL '='.\n"
        )
        assert result.warnings == [], result.warnings

    def test_all_literal_in_subordinate_item(self):
        items = _working_storage_items(
            "       01  WS-SEP.\n" "           05  WS-DASH PIC X(133) VALUE ALL '-'.\n"
        )
        (group,) = [i for i in items if i.name == "WS-SEP"]
        children = [c for c in group.children if getattr(c, "level", None) is not None]
        (child,) = children
        assert child.value_clause == 'ALL "-"'
