"""Qualified names are looked up as COBOL resolves them (#541).

MCP ``explain_symbol`` compared a qualified name with
``XrefEntry.qualified_name``, which is set only for namesakes and only to
the full ancestor chain, so ``SOLO OF SOLO-REC`` (unique), ``AMT OF
OUT-REC`` (skipping OUT-GRP) and ``... IN ...`` all came back ``found:
false``. ``field-impact`` / ``lineage --field`` split the start on ``OF``
only, so ``AMT IN IN-REC`` was "no such field".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.mcp import CobolTools, Workspace

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. Q.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 IN-REC.
          05 IN-GRP.
             10 AMT PIC 9(5).
       01 OUT-REC.
          05 OUT-GRP.
             10 AMT PIC 9(5).
       01 SOLO-REC.
          05 SOLO PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE AMT OF IN-REC TO AMT OF OUT-GRP
           MOVE 'A' TO SOLO OF SOLO-REC
           STOP RUN.
"""


@pytest.fixture()
def tools(tmp_path: Path) -> CobolTools:
    (tmp_path / "Q.cbl").write_text(SOURCE)
    return CobolTools(Workspace(tmp_path))


@pytest.mark.parametrize(
    "name, line",
    [
        ("SOLO OF SOLO-REC", 12),
        ("SOLO IN SOLO-REC", 12),
        ("AMT OF OUT-REC", 10),
        ("AMT OF OUT-GRP", 10),
        ("AMT IN OUT-GRP OF OUT-REC", 10),
        ("AMT OF IN-REC", 7),
        ("amt  of   in-grp", 7),
    ],
)
def test_explain_symbol_resolves_qualified_names(tools, name, line) -> None:
    answer = tools.explain_symbol(file="Q.cbl", name=name)["answer"]
    assert answer.get("found", True) is not False, answer
    (symbol,) = answer["symbols"]
    assert symbol["declared_at"]["line"] == line, answer


def test_wrong_or_misordered_qualifier_is_not_found(tools) -> None:
    for name in ("AMT OF SOLO-REC", "AMT OF OUT-REC OF OUT-GRP"):
        answer = tools.explain_symbol(file="Q.cbl", name=name)["answer"]
        assert answer["found"] is False, name


def test_xref_entries_named() -> None:
    report = XrefAnalyzer().analyze(parse_cobol(SOURCE).ast)
    assert len(report.entries_named("AMT")) == 2
    (entry,) = report.entries_named("AMT IN OUT-REC")
    assert entry.qualified_name == "AMT OF OUT-GRP OF OUT-REC"
    assert report.entry_for("SOLO OF SOLO-REC") is report.entry_for("SOLO")
    assert "ancestors" not in entry.to_dict()


def test_field_impact_accepts_in() -> None:
    graph = LineageGraph([FieldFlowAnalyzer().analyze(parse_cobol(SOURCE).ast)])
    with_in = graph.impact("AMT IN IN-REC").to_dict()
    with_of = graph.impact("AMT OF IN-REC").to_dict()
    assert with_in["hits"], with_in
    assert with_in["hits"] == with_of["hits"]
