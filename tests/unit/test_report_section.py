"""REPORT SECTION parsing (2026-09-02).

Before this, the DATA DIVISION parser consumed the REPORT SECTION header and
discarded its body with a "not supported" warning, so a Report Writer
program could never parse warning-free -- and every ``RD``/report-group
declaration was absent from the AST. Now:

* ``RD report-name`` clauses (CODE, CONTROL(S), PAGE LIMIT + HEADING /
  FIRST DETAIL / LAST DETAIL / FOOTING, GLOBAL) are captured as a mapping on
  each 01-level report group's ``metadata["rd_clauses"]``, with the report
  name on ``metadata["rd_report_name"]``.
* Report groups are ordinary ``CobolDataItem`` trees. An entry whose level
  is followed by a clause word (``01 TYPE IS DETAIL.``, ``05 LINE 1.``,
  ``10 COLUMN 1 PIC X``) is anonymous. TYPE, LINE, NEXT GROUP, COLUMN,
  SOURCE, SUM (with UPON / RESET ON), GROUP INDICATE and PRESENT WHEN land
  in ``metadata["report_clauses"]``; PICTURE / VALUE / JUSTIFIED / BLANK
  WHEN ZERO / USAGE use the ordinary clause branches.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RWSECT.
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
           GENERATE DETAIL-LINE
           TERMINATE SALES-RPT
           CLOSE RPT-FILE.
"""

REPORT = """\
       RD  SALES-RPT
           CODE "SR"
           CONTROLS ARE FINAL WS-REGION
           PAGE LIMIT IS 60 LINES
           HEADING 1
           FIRST DETAIL 5
           LAST DETAIL 50
           FOOTING 55.
       01  TYPE IS PAGE HEADING.
           05  LINE NUMBER IS 1.
               10  COLUMN 1        PIC X(12) VALUE "SALES REPORT".
               10  COLUMN 60       PIC ZZ9 SOURCE PAGE-COUNTER.
       01  TYPE IS CONTROL HEADING WS-REGION
               NEXT GROUP IS PLUS 1.
           05  LINE PLUS 2.
               10  COLUMN 1        PIC X(10) SOURCE IS WS-REGION
                                   GROUP INDICATE.
       01  DETAIL-LINE TYPE DE.
           05  LINE IS PLUS 1.
               10  COLUMN 1        PIC X(10) SOURCE WS-REGION.
               10  DL-AMOUNT       COLUMN 20 PIC ZZ,ZZ9 SOURCE WS-AMOUNT.
       01  TYPE IS CONTROL FOOTING WS-REGION
               LINE PLUS 1 NEXT GROUP NEXT PAGE.
           05  COLUMN 20           PIC ZZ,ZZ9
                                   SUM WS-AMOUNT UPON DETAIL-LINE
                                   RESET ON WS-REGION.
       01  TYPE IS CF FINAL.
           05  COLUMN 20           PIC ZZZ,ZZ9 SUM DL-AMOUNT.
       01  TYPE IS PAGE FOOTING.
           05  LINE 59 COLUMN 30   PIC X(11) VALUE "END OF PAGE"
                                   JUSTIFIED RIGHT.
"""


def _parse(report: str = REPORT):
    result = parse_cobol(HEADER + report + TAIL, filename="rwsect.cbl")
    assert result.success, result.errors
    return result


def _report_groups(result):
    section = result.ast.data_division.get_section_by_name("REPORT")
    assert section is not None
    return section.data_items


def _leaves(group):
    """Every elementary (level-10-or-deeper) item under a group, in order."""
    out = []

    def walk(item):
        for child in item.children:
            if hasattr(child, "level"):
                out.append(child)
                walk(child)

    walk(group)
    return out


def test_report_section_parses_without_warnings():
    result = _parse()
    assert result.warnings == []
    assert result.ast.data_division.metadata["has_report"] is True


def test_rd_clauses_are_captured_on_every_group():
    groups = _report_groups(_parse())
    assert len(groups) == 6
    for group in groups:
        assert group.get_metadata("rd_report_name") == "SALES-RPT"
    rd = groups[0].get_metadata("rd_clauses")
    assert rd == {
        "code": "SR",
        "controls": ["FINAL", "WS-REGION"],
        "page_limit": 60,
        "heading": 1,
        "first_detail": 5,
        "last_detail": 50,
        "footing": 55,
        "is_global": False,
        "raw": [],
    }


def test_working_storage_is_untouched():
    section = _parse().ast.data_division.get_section_by_name("WORKING-STORAGE")
    assert [d.name for d in section.data_items] == ["WS-AMOUNT", "WS-REGION"]


def test_anonymous_and_named_groups_and_type_clause():
    groups = _report_groups(_parse())
    assert [g.get_metadata("report_clauses")["type"] for g in groups] == [
        "PAGE HEADING",
        "CONTROL HEADING WS-REGION",
        "DE",
        "CONTROL FOOTING WS-REGION",
        "CF FINAL",
        "PAGE FOOTING",
    ]
    assert groups[0].name.startswith("ANONYMOUS-1-")
    assert groups[2].name == "DETAIL-LINE"
    assert groups[1].get_metadata("report_clauses")["next_group"] == "PLUS 1"
    footing = groups[3].get_metadata("report_clauses")
    assert footing["line"] == ["PLUS 1"]
    assert footing["next_group"] == "NEXT PAGE"


def test_line_column_source_and_picture_clauses():
    groups = _report_groups(_parse())
    heading_line, col1, col60 = _leaves(groups[0])
    assert heading_line.get_metadata("report_clauses") == {"line": ["1"]}
    assert col1.get_metadata("report_clauses") == {"column": ["1"]}
    assert col1.picture_clause.pattern == "X(12)"
    assert col1.value_clause == '"SALES REPORT"'
    assert col60.get_metadata("report_clauses") == {
        "column": ["60"],
        "source": "PAGE-COUNTER",
    }
    assert col60.picture_clause.pattern == "ZZ9"

    _, region_col = _leaves(groups[1])
    assert region_col.get_metadata("report_clauses") == {
        "column": ["1"],
        "source": "WS-REGION",
        "group_indicate": True,
    }

    _, _, dl_amount = _leaves(groups[2])
    assert dl_amount.name == "DL-AMOUNT"
    assert dl_amount.get_metadata("report_clauses") == {
        "column": ["20"],
        "source": "WS-AMOUNT",
    }
    assert dl_amount.picture_clause.pattern == "ZZ,ZZ9"


def test_sum_clause_with_upon_and_reset():
    groups = _report_groups(_parse())
    (control_sum,) = _leaves(groups[3])
    assert control_sum.get_metadata("report_clauses") == {
        "column": ["20"],
        "sum": [
            {
                "operands": ["WS-AMOUNT"],
                "upon": ["DETAIL-LINE"],
                "reset_on": "WS-REGION",
            }
        ],
    }
    (final_sum,) = _leaves(groups[4])
    assert final_sum.get_metadata("report_clauses")["sum"] == [
        {"operands": ["DL-AMOUNT"]}
    ]


def test_line_and_column_on_one_entry_with_justified():
    groups = _report_groups(_parse())
    (footer,) = _leaves(groups[5])
    assert footer.get_metadata("report_clauses") == {"line": ["59"], "column": ["30"]}
    assert footer.justified is True
    assert footer.value_clause == '"END OF PAGE"'


def test_to_dict_serializes_report_metadata():
    groups = _report_groups(_parse())
    d = groups[2].to_dict()
    assert d["metadata"]["rd_report_name"] == "SALES-RPT"
    assert d["metadata"]["report_clauses"] == {"type": "DE"}
    assert d["metadata"]["rd_clauses"]["page_limit"] == 60


def test_procedure_division_still_parses_after_report_section():
    result = _parse()
    kinds = [s.statement_type for s in result.ast.get_all_statements()]
    assert kinds == ["OPEN", "INITIATE", "GENERATE", "TERMINATE", "CLOSE"]


def test_missing_rd_period_does_not_swallow_the_first_group():
    """A missing period after the RD clauses is a common slip; the first
    01 must still become a report group rather than an RD clause operand."""
    report = (
        "       RD  SALES-RPT\n"
        "           PAGE LIMIT 60\n"
        "       01  DETAIL-LINE TYPE DETAIL.\n"
        "           05  COLUMN 1 PIC X(5) SOURCE WS-REGION.\n"
    )
    groups = _report_groups(_parse(report))
    assert [g.name for g in groups] == ["DETAIL-LINE"]
    assert groups[0].get_metadata("rd_clauses")["page_limit"] == 60


def test_fd_report_is_clause_is_still_not_a_section_header():
    """``REPORT IS name`` inside an FD must not start a REPORT SECTION."""
    source = HEADER.replace("       REPORT SECTION.\n", "") + TAIL
    result = parse_cobol(source, filename="rwsect.cbl")
    assert result.success
    assert result.ast.data_division.get_section_by_name("REPORT") is None
    assert result.ast.data_division.metadata["has_report"] is False
