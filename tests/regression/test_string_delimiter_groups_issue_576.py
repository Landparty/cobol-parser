"""STRING records which sources each DELIMITED BY applies to (#576).

``operands`` and ``delimiters`` are two flat lists, so ``STRING A B
DELIMITED BY SIZE C DELIMITED BY D1`` and ``STRING A DELIMITED BY SIZE B C
DELIMITED BY D1`` produced identical nodes and ``diff`` reported "No
structural changes" although B is copied whole in one and truncated at D1
in the other. ``StringStatement.groups`` now records the grouping.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer


def _program(statement: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. S2.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 A PIC X(3).",
        "01 B PIC X(3).",
        "01 C PIC X(3).",
        "01 D1 PIC X.",
        "01 OUT1 PIC X(12).",
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        f"    {statement}",
        "    STOP RUN.",
    )
    return "".join(f"       {line}\n" for line in lines)


S2 = _program("STRING A B DELIMITED BY SIZE C DELIMITED BY D1 INTO OUT1")
S2B = _program("STRING A DELIMITED BY SIZE B C DELIMITED BY D1 INTO OUT1")


def _string(source: str):
    result = parse_cobol(source)
    assert result.success, result.errors
    (stmt,) = [
        s for s in result.ast.get_all_statements() if s.statement_type == "STRING"
    ]
    return stmt


def test_groups_record_which_delimiter_applies_to_which_source():
    stmt = _string(S2)
    assert stmt.groups == [
        {"sources": ["A", "B"], "delimiter": "SIZE"},
        {"sources": ["C"], "delimiter": "D1"},
    ]
    # The flat lists are unchanged, for compatibility.
    assert stmt.operands == ["A", "B", "C"]
    assert stmt.delimiters == ["SIZE", "D1"]
    assert stmt.to_dict()["groups"] == stmt.groups

    assert _string(S2B).groups == [
        {"sources": ["A"], "delimiter": "SIZE"},
        {"sources": ["B", "C"], "delimiter": "D1"},
    ]


def test_trailing_sources_without_delimited_by_form_an_open_group():
    stmt = _string(_program("STRING A DELIMITED BY SIZE B INTO OUT1"))
    assert stmt.groups == [
        {"sources": ["A"], "delimiter": "SIZE"},
        {"sources": ["B"], "delimiter": None},
    ]


def test_diff_reports_a_source_moving_between_delimiter_groups():
    report = ProgramDiffer().diff(parse_cobol(S2).ast, parse_cobol(S2B).ast)
    text = report.to_text()
    assert "No structural changes" not in text
    assert "STRING A DELIMITED BY SIZE B C DELIMITED BY D1 INTO OUT1" in text
    assert report.changes
    assert ProgramDiffer().diff(parse_cobol(S2).ast, parse_cobol(S2).ast).changes == []
