"""REPORT SECTION SOURCE / SUM / CONTROL operands are xref references (#571).

``UnusedVariableAnalyzer`` counted the fields a Report Writer report prints,
totals and breaks on as used, but ``XrefAnalyzer`` had no REPORT SECTION
branch: every such field showed 0 references in ``xref`` and MCP
``explain_symbol``.
"""

from __future__ import annotations

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.xref import ROLE_REFERENCE, XrefAnalyzer

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. RW.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        "    SELECT PRT ASSIGN TO PRTDD.",
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD PRT REPORT IS RPT.",
        "WORKING-STORAGE SECTION.",
        "01 WS-NAME  PIC X(10) VALUE 'ABC'.",
        "01 WS-DEPT  PIC X(4) VALUE 'D1'.",
        "01 WS-AMT   PIC 9(5) VALUE 10.",
        "01 WS-TITLE PIC X(20) VALUE 'TITLE'.",
        "01 WS-IDLE  PIC X.",
        "REPORT SECTION.",
        "RD RPT CONTROLS ARE WS-DEPT PAGE LIMIT 60 LINES.",
        "01 TYPE PAGE HEADING.",
        "   05 LINE 1 COLUMN 1 PIC X(20) SOURCE WS-TITLE.",
        "01 DET TYPE DETAIL LINE PLUS 1.",
        "   05 COLUMN 1 PIC X(10) SOURCE WS-NAME.",
        "   05 COLUMN 20 PIC ZZZZ9 SOURCE WS-AMT.",
        "01 TYPE CONTROL FOOTING WS-DEPT.",
        "   05 COLUMN 20 PIC ZZZZZ9 SUM WS-AMT.",
        "PROCEDURE DIVISION.",
        "MAIN.",
        "    OPEN OUTPUT PRT",
        "    INITIATE RPT",
        "    GENERATE DET",
        "    TERMINATE RPT",
        "    CLOSE PRT",
        "    STOP RUN.",
    )
)


def _ast():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return result.ast


def test_report_operands_are_referenced_at_their_entries():
    report = XrefAnalyzer().analyze(_ast())
    counts = {
        name: len(report.entry_for(name).references)
        for name in ("WS-TITLE", "WS-NAME", "WS-AMT", "WS-DEPT", "WS-IDLE")
    }
    # WS-AMT: SOURCE on the detail line and SUM on the footing. WS-DEPT: the
    # RD's CONTROLS, once (not once per report group the RD's clauses are
    # copied onto); the CONTROL FOOTING's own name is TYPE text, not an
    # operand the parser keeps.
    assert counts == {
        "WS-TITLE": 1,
        "WS-NAME": 1,
        "WS-AMT": 2,
        "WS-DEPT": 1,
        "WS-IDLE": 0,
    }
    refs = report.entry_for("WS-NAME").references
    assert refs[0].role == ROLE_REFERENCE
    assert refs[0].statement == "REPORT SECTION"
    assert refs[0].location is not None and refs[0].location.line == 21
    # The RD is no node: its CONTROLS are recorded at its first report group.
    assert report.entry_for("WS-DEPT").references[0].location.line == 18


def test_xref_agrees_with_unused_variables():
    ast = _ast()
    unused = {item.name for item in UnusedVariableAnalyzer().analyze(ast).unused_items}
    xref = XrefAnalyzer().analyze(ast)
    for name in ("WS-TITLE", "WS-NAME", "WS-AMT", "WS-DEPT", "WS-IDLE"):
        assert (name in unused) == (not xref.entry_for(name).is_referenced)
