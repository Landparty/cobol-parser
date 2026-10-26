"""Data items named only in a SELECT clause are referenced (#549, #556).

xref recorded a SELECT's FILE STATUS / PASSWORD / ASSIGN USING items but not
its RECORD KEY, ALTERNATE RECORD KEY, RELATIVE KEY or PADDING CHARACTER items,
so they had 0 references in xref and MCP ``explain_symbol`` (#549).
unused-variables counted the keys but not ``PADDING CHARACTER IS data-name``,
so lint reported the padding item unused (#556).
"""

from __future__ import annotations

from cobolparser import LintAnalyzer, UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.xref import XrefAnalyzer


def _program(select: list[str], fd: list[str], ws: list[str]) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. P1.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        *select,
        "DATA DIVISION.",
        "FILE SECTION.",
        *fd,
        "WORKING-STORAGE SECTION.",
        *ws,
        "PROCEDURE DIVISION.",
        "MAIN.",
        "    OPEN I-O F1",
        "    READ F1 NEXT RECORD AT END CONTINUE END-READ",
        "    CLOSE F1",
        "    STOP RUN.",
    )
    return "".join(f"       {line}\n" for line in lines)


INDEXED = _program(
    [
        "    SELECT F1 ASSIGN TO DD1 ORGANIZATION INDEXED",
        "        ACCESS DYNAMIC RECORD KEY F1-KEY",
        "        ALTERNATE RECORD KEY F1-ALT WITH DUPLICATES",
        "        FILE STATUS WS-FS.",
    ],
    [
        "FD F1.",
        "01 F1-REC.",
        "   05 F1-KEY PIC X(5).",
        "   05 F1-ALT PIC X(5).",
        "   05 F1-DATA PIC X(5).",
    ],
    ["01 WS-FS PIC XX."],
)

RELATIVE = _program(
    [
        "    SELECT F1 ASSIGN TO DD1 ORGANIZATION RELATIVE",
        "        ACCESS DYNAMIC RELATIVE KEY WS-RRN",
        "        FILE STATUS WS-FS.",
    ],
    ["FD F1.", "01 F1-REC PIC X(10)."],
    ["01 WS-FS PIC XX.", "01 WS-RRN PIC 9(8) COMP."],
)

PADDED = _program(
    [
        "    SELECT F1 ASSIGN TO PRT",
        "        PADDING CHARACTER IS WS-PAD.",
    ],
    ["FD F1.", "01 F1-REC PIC X(10)."],
    ["01 WS-PAD PIC X.", "01 WS-UNUSED PIC X."],
)

PADDED_LITERAL = _program(
    [
        "    SELECT F1 ASSIGN TO PRT",
        "        PADDING CHARACTER IS '*'.",
    ],
    ["FD F1.", "01 F1-REC PIC X(10)."],
    ["01 WS-UNUSED PIC X."],
)


def _ast(source: str):
    result = parse_cobol(source)
    assert result.success, result.errors
    return result.ast


def _ref_count(source: str, name: str) -> int:
    return len(XrefAnalyzer().analyze(_ast(source)).entry_for(name).references)


def test_xref_records_record_and_alternate_keys():
    assert _ref_count(INDEXED, "F1-KEY") == 1
    assert _ref_count(INDEXED, "F1-ALT") == 1
    assert _ref_count(INDEXED, "WS-FS") == 1


def test_xref_records_relative_key():
    assert _ref_count(RELATIVE, "WS-RRN") == 1


def test_xref_records_padding_character_item():
    assert _ref_count(PADDED, "WS-PAD") == 1


def test_unused_variables_counts_padding_character_item():
    report = UnusedVariableAnalyzer().analyze(_ast(PADDED))
    assert {item.name for item in report.unused_items} == {"F1-REC", "WS-UNUSED"}
    findings = LintAnalyzer(["unused-variables"]).analyze(_ast(PADDED)).findings
    assert "WS-PAD" not in {f.symbol for f in findings}


def test_padding_literal_references_nothing():
    report = UnusedVariableAnalyzer().analyze(_ast(PADDED_LITERAL))
    assert {item.name for item in report.unused_items} == {"F1-REC", "WS-UNUSED"}
