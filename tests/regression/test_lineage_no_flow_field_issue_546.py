"""Issue #546: a declared field with no value flow (set only from a literal,
only tested in a condition) was reported as "no such field in any report":
``field-impact`` exited 1 and MCP ``where_from`` / ``impact_of_change``
answered ``found: false`` with the asked-for name as the only suggestion.
Such a field is found and feeds / is fed by nothing; "no such field" and
exit 1 stay for a name that matches no declared item.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.cli.parse import main
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. Q.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LONELY PIC X.
       01 USED-ONLY-READ PIC X VALUE 'A'.
       01 SINK PIC X.
       PROCEDURE DIVISION.
           MOVE 'Z' TO LONELY
           IF USED-ONLY-READ = 'A' MOVE 'B' TO SINK END-IF
           STOP RUN.
"""

NO_FLOW = ("LONELY", "USED-ONLY-READ", "SINK")


@pytest.fixture(scope="module")
def graph() -> LineageGraph:
    result = parse_cobol(SOURCE, "Q.cbl")
    assert result.ast is not None
    return LineageGraph([FieldFlowAnalyzer().analyze(result.ast)])


@pytest.mark.parametrize("name", NO_FLOW)
@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_declared_field_without_flow_is_found(graph, name, direction) -> None:
    result = graph.impact(name, direction=direction)
    assert result.start_found
    assert result.hits == []
    assert not any("no such field" in c for c in result.caveats)
    assert result.notes and "no value flows" in result.notes[0]
    assert result.to_dict()["notes"] == result.notes
    assert "Notes:" in result.to_text()


def test_missing_name_still_not_found(graph) -> None:
    result = graph.impact("NOPE")
    assert not result.start_found
    assert result.caveats == ["NOPE: no such field in any report"]
    assert result.notes == []


def _cli(monkeypatch, capsys, path: Path, name: str) -> tuple[int, str]:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cobol-parser",
            "--no-config",
            "field-impact",
            name,
            str(path),
            "--direction",
            "backward",
            "--format",
            "text",
            "--workers",
            "1",
        ],
    )
    try:
        main()
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, capsys.readouterr().out


def test_cli_exit_codes(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "Q.cbl"
    path.write_text(SOURCE)
    code, out = _cli(monkeypatch, capsys, path, "SINK")
    assert code == 0
    assert "no such field" not in out
    assert "no value flows" in out
    code, out = _cli(monkeypatch, capsys, path, "NOPE")
    assert code == 1
    assert "no such field" in out


def test_mcp_where_from(tmp_path) -> None:
    (tmp_path / "Q.cbl").write_text(SOURCE)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    answer = tools.where_from("SINK", "Q.cbl")["answer"]
    assert answer["found"] is True
    assert answer["hits"] == []
    assert answer["notes"]
    answer = tools.impact_of_change("LONELY", "Q.cbl")["answer"]
    assert answer["found"] is True
    # A real miss never suggests the very name that was asked for.
    missing = tools.where_from("SINKX", "Q.cbl")["answer"]
    assert missing["found"] is False
    assert "SINKX" not in missing["suggestions"]
    assert json.dumps(missing)
