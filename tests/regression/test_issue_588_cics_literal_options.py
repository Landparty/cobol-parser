"""An EXEC CICS literal operand never references a same-named item (#588).

``ExecCicsStatement.options`` strips the quotes off an argument, so
``FILE('CUSTFIL')`` read the same as ``FILE(CUSTFIL)``: unused-variables, xref
and lint counted a literal as a reference to a data item that happened to
share its text. The options the parser records in ``literal_options`` are now
skipped by every sweep.
"""

from __future__ import annotations

from cobolparser import LintAnalyzer, UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis._cics import cics_identifier_options
from cobolparser.analysis.xref import XrefAnalyzer

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. CI.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 CUSTFIL PIC X(8).",
        "01 SUBPGM  PIC X(8).",
        "01 WS-REC  PIC X(10).",
        "01 WS-RESP PIC S9(8) COMP.",
        "01 WS-FILE PIC X(8).",
        "PROCEDURE DIVISION.",
        "P1.",
        "    EXEC CICS READ FILE('CUSTFIL') INTO(WS-REC)",
        "         RIDFLD('KEY01') RESP(WS-RESP)",
        "    END-EXEC",
        "    EXEC CICS LINK PROGRAM('SUBPGM') RESP(WS-RESP)",
        "    END-EXEC",
        "    EXEC CICS READ FILE(WS-FILE) INTO(WS-REC) RIDFLD(WS-RESP)",
        "    END-EXEC",
        "    EXEC CICS RETURN END-EXEC.",
    )
)


def _ast():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return result.ast


def test_identifier_options_skip_literals():
    stmt = _ast().find_all_by_type("EXEC_CICS")[0]
    options = cics_identifier_options(stmt)
    assert "FILE" not in options and "RIDFLD" not in options
    assert options["INTO"] == "WS-REC"


def test_unused_variables_reports_items_named_like_literals():
    report = UnusedVariableAnalyzer().analyze(_ast())
    assert {item.name for item in report.unused_items} == {"CUSTFIL", "SUBPGM"}


def test_xref_has_no_reference_from_a_literal():
    report = XrefAnalyzer().analyze(_ast())
    assert report.entry_for("CUSTFIL").references == []
    assert report.entry_for("SUBPGM").references == []
    assert report.entry_for("WS-FILE").references != []


def test_lint_reports_both_unused_items():
    findings = LintAnalyzer(["unused-variables"]).analyze(_ast()).findings
    assert sorted(f.symbol for f in findings) == ["CUSTFIL", "SUBPGM"]
