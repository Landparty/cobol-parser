"""Regression tests for #500: codebase-graph made every FACTORY / OBJECT /
METHOD-ID unit of an OO class a program node, so ``CALL 'AUDIT'`` to an
unrelated external program resolved to a method, and two classes produced
"duplicate PROGRAM-ID FACTORY / OBJECT / ..." notes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "enterprise" / "OOCOBOL.cbl"

BATCH1 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BATCH1.
       PROCEDURE DIVISION.
           CALL 'AUDIT'
           CALL 'OBJECT'
           GOBACK.
"""

METHOD_CALLS = """\
       IDENTIFICATION DIVISION.
       CLASS-ID. CALLER-CLS INHERITS BASE.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           CLASS BASE IS "java.lang.Object".
       FACTORY.
       PROCEDURE DIVISION.
       IDENTIFICATION DIVISION.
       METHOD-ID. "run-it".
       PROCEDURE DIVISION.
           CALL 'HELPER'
           GOBACK.
       END METHOD "run-it".
       END FACTORY.
       END CLASS CALLER-CLS.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copy(SAMPLE, tmp_path / "OOCOBOL.cbl")
    (tmp_path / "LOAN.cbl").write_text(
        SAMPLE.read_text().replace("CLASS-ID. ACCOUNT", "CLASS-ID. LOAN")
    )
    (tmp_path / "BATCH1.cbl").write_text(BATCH1)
    return tmp_path


def _build(root: Path):
    return CodebaseGraphBuilder().build(sorted(str(p) for p in root.glob("*.cbl")))


def test_only_programs_and_classes_are_nodes(root: Path) -> None:
    graph = _build(root)
    assert graph.program_ids == ["ACCOUNT", "BATCH1", "LOAN"]
    assert not any("duplicate PROGRAM-ID" in note for note in graph.unresolved)


def test_call_to_a_method_name_stays_external(root: Path) -> None:
    graph = _build(root)
    known = set(graph.program_ids)
    callees = graph.callees_of("BATCH1")
    assert callees == ["AUDIT", "OBJECT"]
    assert not known & set(callees)


def test_a_method_call_belongs_to_its_class(tmp_path: Path) -> None:
    (tmp_path / "CLS.cbl").write_text(METHOD_CALLS)
    graph = CodebaseGraphBuilder().build([str(tmp_path / "CLS.cbl")])
    assert graph.program_ids == ["CALLER-CLS"]
    assert graph.callees_of("CALLER-CLS") == ["HELPER"]


def test_mcp_does_not_declare_a_method_as_a_program(root: Path) -> None:
    tools = CobolTools(Workspace(root, ProjectConfig()))
    answer = tools.callers_of(None, "AUDIT")["answer"]
    assert answer["declared_in"] == []
    result = tools.callers_of(None, "OBJECT")
    assert "duplicate-declaration" not in [c["kind"] for c in result["caveats"]]


def test_mcp_overview_does_not_count_a_call_on_a_method(root: Path) -> None:
    answer = CobolTools(Workspace(root, ProjectConfig())).codebase_overview()["answer"]
    graph = answer["call_graph"]
    external = {e["program"] for e in graph["not_in_workspace"]}
    assert {"AUDIT", "OBJECT"} <= external
    assert "AUDIT" not in {row["program"] for row in graph["most_called"]}
    methods = [r for r in answer["programs"] if r.get("unit_kind") == "METHOD"]
    assert methods and all(r["called_by"] == 0 for r in methods)
