"""Items a SCREEN SECTION binds are used (#501).

The DATA DIVISION parser skips the SCREEN SECTION's grammar, so every
WORKING-STORAGE item a screen field binds with ``USING`` / ``FROM`` / ``TO``
was reported "never referenced" by unused-variables and lint, and xref listed
the screen itself (``DISPLAY MAIN-SCREEN``) as an undefined data item. The
skip now keeps the screen-item names and the bound operands.
"""

from __future__ import annotations

from cobolparser import LintAnalyzer, UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.xref import (
    KIND_SCREEN_ITEM,
    ROLE_READ,
    ROLE_REFERENCE,
    ROLE_SUBSCRIPT,
    ROLE_WRITE,
    XrefAnalyzer,
)

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. SCR.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-NAME PIC X(20).",
        "01 WS-AGE PIC 99.",
        "01 WS-GRP.",
        "   05 WS-OUT PIC X(10).",
        "01 WS-IDLE PIC X.",
        "SCREEN SECTION.",
        "01 MAIN-SCREEN.",
        "   05 LINE 1 COLUMN 1 VALUE 'NAME:'.",
        "   05 LINE 1 COLUMN 7 PIC X(20) USING WS-NAME.",
        "   05 S-AGE LINE 2 COLUMN 7 PIC 99 TO WS-AGE.",
        "   05 LINE 3 COLUMN 7 PIC X(10) FROM WS-OUT OF WS-GRP.",
        "   05 LINE 4 COLUMN 7 PIC X(3) FROM 'ABC'.",
        "PROCEDURE DIVISION.",
        "    DISPLAY MAIN-SCREEN",
        "    ACCEPT MAIN-SCREEN",
        "    GOBACK.",
    )
)


def _ast():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return result.ast


def test_screen_section_metadata_keeps_items_and_operands():
    (screen,) = [s for s in _ast().data_division.sections if s.section_name == "SCREEN"]
    assert [
        (i["name"], i["level"], i["line"]) for i in screen.metadata["screen_items"]
    ] == [("MAIN-SCREEN", 1, 11), ("S-AGE", 5, 14)]
    assert [
        (r["clause"], r["text"], r["line"])
        for r in screen.metadata["screen_references"]
    ] == [
        ("USING", "WS-NAME", 13),
        ("TO", "WS-AGE", 14),
        ("FROM", "WS-OUT OF WS-GRP", 15),
    ]


def test_unused_variables_and_lint_count_screen_bindings():
    report = UnusedVariableAnalyzer().analyze(_ast())
    assert {item.name for item in report.unused_items} == {"WS-IDLE"}
    findings = LintAnalyzer(["unused-variables"]).analyze(_ast()).findings
    assert [f.symbol for f in findings] == ["WS-IDLE"]


def test_xref_declares_screens_and_records_bindings():
    report = XrefAnalyzer().analyze(_ast())
    assert report.undefined == []
    screen = report.entry_for("MAIN-SCREEN")
    assert screen.kind == KIND_SCREEN_ITEM
    assert screen.definition is not None and screen.definition.line == 11
    assert [r.location.line for r in screen.references] == [18, 19]

    def roles(name):
        return [(r.location.line, r.role) for r in report.entry_for(name).references]

    assert sorted(roles("WS-NAME")) == [(13, ROLE_READ), (13, ROLE_WRITE)]
    assert roles("WS-AGE") == [(14, ROLE_WRITE)]
    assert roles("WS-OUT") == [(15, ROLE_READ)]
    assert roles("WS-IDLE") == []


POSITIONED = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. SCR2.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-ROW PIC 99.",
        "01 WS-COLR PIC 9.",
        "01 I PIC 9.",
        "01 WS-TAB.",
        "   05 WS-E PIC X(3) OCCURS 3.",
        "01 WS-IDLE PIC X.",
        "SCREEN SECTION.",
        "01 MAIN-SCREEN BLANK SCREEN.",
        "   05 LINE WS-ROW COLUMN PLUS 2 PIC X(3) USING WS-E(I)",
        "      FOREGROUND-COLOR IS WS-COLR.",
        "   05 LINE 2 COL 1 VALUE 'X'.",
        "PROCEDURE DIVISION.",
        "    DISPLAY MAIN-SCREEN",
        "    GOBACK.",
    )
)


def test_subscripts_and_positional_items_are_used():
    ast = parse_cobol(POSITIONED).ast
    report = UnusedVariableAnalyzer().analyze(ast)
    assert {item.name for item in report.unused_items} == {"WS-IDLE"}
    xref = XrefAnalyzer().analyze(ast)
    assert xref.undefined == []
    assert [r.role for r in xref.entry_for("I").references] == [ROLE_SUBSCRIPT]
    assert [r.role for r in xref.entry_for("WS-ROW").references] == [ROLE_REFERENCE]
    assert [r.role for r in xref.entry_for("WS-COLR").references] == [ROLE_REFERENCE]
    assert sorted(r.role for r in xref.entry_for("WS-E").references) == [
        ROLE_READ,
        ROLE_WRITE,
    ]
