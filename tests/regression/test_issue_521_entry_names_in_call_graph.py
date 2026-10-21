"""Regression tests for #521: a ``CALL 'X'`` to an alternate ``ENTRY 'X'``
of another program was drawn as a call to an external program X, and the
program that declares the ENTRY read as never called -- in codebase-graph,
MCP ``callers_of`` and ``codebase_overview``."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-A  PIC X(5).
       PROCEDURE DIVISION USING LK-A.
       MAIN-PARA.
           MOVE 'HELLO' TO LK-A
           GOBACK.
       ALT-PARA.
           ENTRY 'CALLALT' USING LK-A.
           MOVE 'ALTER' TO LK-A
           GOBACK.
"""

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A  PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'CALLALT' USING WS-A
           GOBACK.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "CALLEE.cbl").write_text(CALLEE)
    (tmp_path / "CALLER.cbl").write_text(CALLER)
    return tmp_path


def test_codebase_graph_sends_the_call_to_the_entry_owner(root: Path) -> None:
    graph = CodebaseGraphBuilder().build(
        [str(root / "CALLEE.cbl"), str(root / "CALLER.cbl")]
    )
    (edge,) = graph.call_edges
    assert (edge.caller, edge.callee, edge.entry) == ("CALLER", "CALLEE", "CALLALT")
    assert edge.to_dict()["entry"] == "CALLALT"
    assert graph.callers_of("CALLEE") == ["CALLER"]
    callee = next(p for p in graph.programs if p.program_id == "CALLEE")
    assert callee.entries == ["CALLALT"]
    assert "ENTRY CALLALT" in graph.to_dot()


def test_an_entry_two_programs_declare_is_reported(root: Path) -> None:
    (root / "TWIN.cbl").write_text(
        CALLEE.replace("PROGRAM-ID. CALLEE", "PROGRAM-ID. TWIN")
    )
    graph = CodebaseGraphBuilder().build(
        [str(root / n) for n in ("CALLEE.cbl", "CALLER.cbl", "TWIN.cbl")]
    )
    assert any("duplicate ENTRY CALLALT" in note for note in graph.unresolved)
    assert graph.callees_of("CALLER") == ["CALLALT"]


def _tools(root: Path) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig()))


def test_mcp_callers_of_the_program_and_of_the_entry(root: Path) -> None:
    by_program = _tools(root).callers_of(None, "CALLEE")["answer"]
    assert by_program["calling_programs"] == ["CALLER"]
    assert by_program["callers"][0]["entry"] == "CALLALT"
    by_entry = _tools(root).callers_of(None, "CALLALT")["answer"]
    assert by_entry["calling_programs"] == ["CALLER"]
    assert by_entry["declared_in"] == [{"file": "CALLEE.cbl", "program": "CALLEE"}]


def test_mcp_overview_counts_the_entry_call(root: Path) -> None:
    answer = _tools(root).codebase_overview()["answer"]
    rows = {r["program"]: r for r in answer["programs"]}
    assert rows["CALLEE"]["called_by"] == 1
    external = [e["program"] for e in answer["call_graph"]["not_in_workspace"]]
    assert "CALLALT" not in external
