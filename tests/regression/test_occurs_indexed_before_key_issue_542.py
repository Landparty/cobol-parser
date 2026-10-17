"""OCCURS KEY and INDEXED BY phrases in either order (#542).

The OCCURS walk read the ASCENDING/DESCENDING KEY phrases first and INDEXED
BY second, and its INDEXED BY loop took any IDENTIFIER as an index name. A
table written ``INDEXED BY IX2 ASCENDING KEY IS K2`` (IBM accepts either
order) got ``index_names == ['IX2', 'ASCENDING']``, no key, an "Unparsed
token 'KEY'" warning, an xref data item named ASCENDING, and a key change
that ``diff`` could not see. Fixed identically in the pure-Python walk and
its Cython mirror in ``_data_fast.pyx``.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.analysis.xref import XrefAnalyzer


def _program(table_lines: list[str]) -> str:
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. OCCKEY.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-N PIC 9 VALUE 5.",
        *table_lines,
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        "    SEARCH ALL E2 WHEN K2(IX2) = 'A' DISPLAY 'F' END-SEARCH",
        "    STOP RUN.",
    ]
    return "".join(f"       {line}\n" for line in lines)


TABLES = [
    "01 T2.",
    "   05 E2 OCCURS 5 INDEXED BY IX2 ASCENDING KEY IS K2.",
    "      10 K2 PIC X.",
    "01 T4.",
    "   05 E4 OCCURS 5 TIMES",
    "         INDEXED BY IX4",
    "         ASCENDING KEY K4.",
    "      10 K4 PIC X.",
    "01 T5.",
    "   05 E5 OCCURS 1 TO 5 DEPENDING ON WS-N",
    "         DESCENDING KEY IS K5 INDEXED BY IX5, IX6",
    "         ASCENDING L5.",
    "      10 K5 PIC X.",
    "      10 L5 PIC X.",
]


def _parse(source: str):
    result = parse_cobol(source, filename="occkey.cbl")
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return result


def _occurs(result, name: str):
    for item in result.ast.find_all_by_type("CobolDataItem"):
        if item.name == name:
            return item.occurs_clause
    raise AssertionError(name)


def test_key_after_indexed_by_is_a_key_not_an_index_name():
    result = _parse(_program(TABLES))
    e2 = _occurs(result, "E2")
    assert e2.index_names == ["IX2"]
    assert e2.key_clauses == [{"direction": "ASCENDING", "keys": ["K2"]}]
    e4 = _occurs(result, "E4")
    assert e4.index_names == ["IX4"]
    assert e4.key_clauses == [{"direction": "ASCENDING", "keys": ["K4"]}]


def test_phrases_interleave_and_repeat():
    e5 = _occurs(_parse(_program(TABLES)), "E5")
    assert e5.index_names == ["IX5", "IX6"]
    assert e5.key_clauses == [
        {"direction": "DESCENDING", "keys": ["K5"]},
        {"direction": "ASCENDING", "keys": ["L5"]},
    ]


def test_xref_has_no_data_item_named_ascending():
    xref = XrefAnalyzer().analyze(_parse(_program(TABLES)).ast)
    assert "ASCENDING" not in {entry.name for entry in xref.entries}


def test_diff_sees_a_key_change_after_indexed_by():
    old = _program(TABLES)
    new = old.replace("ASCENDING KEY IS K2.", "ASCENDING KEY IS K9.").replace(
        "10 K2 PIC X.", "10 K2 PIC X.\n             10 K9 PIC X."
    )
    report = ProgramDiffer().diff(_parse(old).ast, _parse(new).ast)
    kinds = {(c.kind, c.symbol) for c in report.changes}
    assert ("occurs-changed", "T2.E2") in kinds, report.to_text()
