"""SPECIAL-NAMES declarations are xref symbols (#519).

The parser keeps SPECIAL-NAMES in the CONFIGURATION SECTION's metadata, but
xref never read it: UPSI condition names and SYMBOLIC CHARACTERS were listed
as undefined data items, and mnemonic and class names were not found at all
(MCP ``explain_symbol`` answered ``declared: false`` / ``found: false``).
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.xref import (
    KIND_ALPHABET_NAME,
    KIND_CLASS_NAME,
    KIND_CONDITION_NAME,
    KIND_MNEMONIC_NAME,
    KIND_SYMBOLIC_CHARACTER,
    ROLE_CONDITION,
    XrefAnalyzer,
)
from cobolparser.mcp import CobolTools, Workspace

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. SN.",
        "ENVIRONMENT DIVISION.",
        "CONFIGURATION SECTION.",
        "SPECIAL-NAMES.",
        "    C01 IS TOP-PAGE",
        "    CLASS HEX-CHARS IS '0' THRU '9' 'A' THRU 'F'",
        "    ALPHABET MY-ALPHA IS EBCDIC",
        "    SYMBOLIC CHARACTERS BELL IS 8",
        "    UPSI-0 ON STATUS IS SW-ON OFF STATUS IS SW-OFF.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        "    SELECT PF ASSIGN TO PRT.",
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD PF.",
        "01 PF-REC PIC X(80).",
        "WORKING-STORAGE SECTION.",
        "01 W PIC X.",
        "PROCEDURE DIVISION.",
        "MAIN.",
        "    OPEN OUTPUT PF",
        "    WRITE PF-REC AFTER ADVANCING TOP-PAGE",
        "    IF W IS HEX-CHARS DISPLAY BELL END-IF",
        "    IF SW-ON DISPLAY 'ON' END-IF",
        "    CLOSE PF",
        "    STOP RUN.",
    )
)


def _report():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return XrefAnalyzer().analyze(result.ast)


def test_nothing_is_undefined():
    assert _report().undefined == []


def test_each_name_is_declared_with_its_kind():
    report = _report()
    expected = {
        "TOP-PAGE": KIND_MNEMONIC_NAME,
        "HEX-CHARS": KIND_CLASS_NAME,
        "MY-ALPHA": KIND_ALPHABET_NAME,
        "BELL": KIND_SYMBOLIC_CHARACTER,
        "SW-ON": KIND_CONDITION_NAME,
        "SW-OFF": KIND_CONDITION_NAME,
    }
    for name, kind in expected.items():
        entry = report.entry_for(name)
        assert entry is not None, name
        assert entry.kind == kind
        # No line per entry in the metadata: the CONFIGURATION SECTION's.
        assert entry.definition is not None and entry.definition.line == 4


def test_references_resolve_to_the_declarations():
    report = _report()
    lines = {
        name: [ref.location.line for ref in report.entry_for(name).references]
        for name in ("TOP-PAGE", "HEX-CHARS", "BELL", "SW-ON", "MY-ALPHA")
    }
    assert lines == {
        "TOP-PAGE": [23],
        "HEX-CHARS": [24],
        "BELL": [24],
        "SW-ON": [25],
        "MY-ALPHA": [],
    }
    assert report.entry_for("HEX-CHARS").references[0].role == ROLE_CONDITION


def test_mcp_explain_symbol_finds_them(tmp_path: Path):
    (tmp_path / "SN.cbl").write_text(SOURCE)
    tools = CobolTools(Workspace(tmp_path))
    for name, kind in (
        ("SW-ON", KIND_CONDITION_NAME),
        ("BELL", KIND_SYMBOLIC_CHARACTER),
        ("TOP-PAGE", KIND_MNEMONIC_NAME),
    ):
        result = tools.explain_symbol("SN.cbl", name)
        (symbol,) = result["answer"]["symbols"]
        assert symbol["kind"] == kind
        assert symbol["declared"] is True
