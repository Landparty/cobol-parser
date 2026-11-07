"""RD clause parsing: the branches ``test_report_section.py`` does not reach.

``ReportDescriptionClauseParser`` (``parsers/divisions/data_report_description``)
is driven here through ``parse_cobol`` with real REPORT SECTION entries, and
each test asserts on the ``rd_clauses`` mapping the first report group
carries: the optional ``IS`` / ``ARE`` / ``LIMITS`` noise words, a CONTROL
list cut short by the next clause keyword, ``IS GLOBAL``, an operand that is
not an integer, unclaimed words landing in ``raw``, and an RD with no
terminating period before its first group or before the PROCEDURE DIVISION.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDBRANCH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "RPT".
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE
           REPORT IS SALES-RPT.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT           PIC 9(5) VALUE 0.
       01  WS-REGION           PIC X(10).
       REPORT SECTION.
"""

TAIL = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT RPT-FILE
           INITIATE SALES-RPT
           TERMINATE SALES-RPT
           CLOSE RPT-FILE.
"""

GROUP = """\
       01  DETAIL-LINE TYPE DE.
           05  LINE 1.
               10  COLUMN 1        PIC X(3) VALUE "ABC".
"""

EMPTY_RD = {
    "code": None,
    "controls": [],
    "page_limit": None,
    "heading": None,
    "first_detail": None,
    "last_detail": None,
    "footing": None,
    "is_global": False,
    "raw": [],
}


def _parse(report: str):
    result = parse_cobol(HEADER + report + TAIL, filename="rdbranch.cbl")
    assert result.success, result.errors
    return result


def _groups(result):
    section = result.ast.data_division.get_section_by_name("REPORT")
    assert section is not None
    return section.data_items


def _rd(report: str) -> dict:
    groups = _groups(_parse(report))
    assert groups, "the report group after the RD was lost"
    return groups[0].get_metadata("rd_clauses")


def test_optional_noise_words_and_is_global():
    rd = _rd("""\
       RD  SALES-RPT
           CODE IS "AB"
           CONTROL IS FINAL
           PAGE LIMITS ARE 66
           IS GLOBAL.
""" + GROUP)
    assert rd == {
        **EMPTY_RD,
        "code": "AB",
        "controls": ["FINAL"],
        "page_limit": 66,
        "is_global": True,
    }


def test_control_list_stops_at_the_next_clause_keyword():
    # CONTROLS without IS/ARE, then PAGE (no LIMIT, no LINES) on the same
    # line: PAGE must start its own clause, not become a control name.
    # FIRST DE / LAST DE IS are the abbreviated DETAIL forms.
    rd = _rd("""\
       RD  SALES-RPT GLOBAL
           CONTROLS WS-REGION PAGE 40
           FIRST DE 3 LAST DE IS 30 HEADING IS 2 FOOTING 35.
""" + GROUP)
    assert rd == {
        **EMPTY_RD,
        "controls": ["WS-REGION"],
        "page_limit": 40,
        "heading": 2,
        "first_detail": 3,
        "last_detail": 30,
        "footing": 35,
        "is_global": True,
    }


def test_control_list_stops_at_code_and_global():
    # CODE and GLOBAL lex as plain identifiers, so the CONTROL loop has to
    # recognise them by spelling as clause starts.
    rd = _rd("""\
       RD  SALES-RPT
           CONTROLS ARE FINAL WS-REGION CODE "SR"
           CONTROL WS-AMOUNT GLOBAL.
""" + GROUP)
    assert rd == {
        **EMPTY_RD,
        "code": "SR",
        "controls": ["FINAL", "WS-REGION", "WS-AMOUNT"],
        "is_global": True,
    }


def test_decimal_page_operand_is_absent_not_truncated():
    # ``PAGE 60.5`` is not an integer line count: recorded as absent rather
    # than truncated to 60.
    rd = _rd("       RD  SALES-RPT PAGE 60.5 HEADING 2.\n" + GROUP)
    assert rd["page_limit"] is None
    assert rd["heading"] == 2


def test_stray_number_before_the_period_is_kept_raw():
    # A level-number-shaped token followed by the period is not a group
    # start, so it stays with the RD instead of ending it.
    rd = _rd("       RD  SALES-RPT FOOTING 55 5.\n" + GROUP)
    assert rd == {**EMPTY_RD, "footing": 55, "raw": ["5"]}


def test_unclaimed_words_are_kept_under_raw():
    rd = _rd("""\
       RD  SALES-RPT
           CODE "SR"
           SOMETHING-ELSE.
""" + GROUP)
    assert rd == {**EMPTY_RD, "code": "SR", "raw": ["SOMETHING-ELSE"]}


def test_code_with_no_operand_records_nothing():
    assert _rd("       RD  SALES-RPT CODE.\n" + GROUP) == EMPTY_RD


def test_non_integer_page_operand_is_absent_and_kept_raw():
    # PAGE LIMIT takes an integer; a data-name there is not guessed at.
    rd = _rd("       RD  SALES-RPT PAGE LIMIT WS-AMOUNT HEADING 1.\n" + GROUP)
    assert rd == {**EMPTY_RD, "heading": 1, "raw": ["WS-AMOUNT"]}


def test_missing_period_before_first_group_does_not_swallow_it():
    groups = _groups(_parse("""\
       RD  SALES-RPT
           PAGE 60 LINES
""" + GROUP))
    assert [g.name for g in groups] == ["DETAIL-LINE"]
    assert groups[0].get_metadata("rd_clauses") == {**EMPTY_RD, "page_limit": 60}


def test_missing_period_before_group_whose_name_is_on_the_next_line():
    # ``01`` alone on its line: the lookahead steps over the line break to
    # see the group name, so the 01 is a group, not an RD operand.
    groups = _groups(_parse("""\
       RD  SALES-RPT PAGE LIMIT 60
       01
           DETAIL-LINE TYPE DE.
           05  LINE 1.
               10  COLUMN 1        PIC X(3) VALUE "ABC".
"""))
    assert [g.name for g in groups] == ["DETAIL-LINE"]
    assert groups[0].get_metadata("rd_clauses")["page_limit"] == 60


def test_missing_period_before_filler_group():
    groups = _groups(_parse("""\
       RD  SALES-RPT PAGE 50
       01  FILLER TYPE DE.
           05  LINE 1.
               10  COLUMN 1        PIC X(3) VALUE "ABC".
"""))
    assert len(groups) == 1
    assert groups[0].get_metadata("rd_clauses")["page_limit"] == 50


def test_unterminated_rd_at_end_of_source():
    # A program cut off mid-RD (no period, no PROCEDURE DIVISION) still
    # parses; the RD has no group to carry its clauses.
    result = parse_cobol(HEADER + "       RD  SALES-RPT PAGE\n", filename="cut.cbl")
    assert result.success, result.errors
    assert result.warnings == []
    assert _groups(result) == []
    assert result.ast.data_division.metadata["has_report"] is True


def test_rd_without_groups_or_period_stops_at_procedure_division():
    result = _parse("       RD  SALES-RPT PAGE 60\n")
    assert _groups(result) == []
    # The PROCEDURE DIVISION header was not eaten as an RD operand.
    paragraphs = result.ast.procedure_division.paragraphs
    assert [p.paragraph_name for p in paragraphs] == ["MAIN-PARA"]
