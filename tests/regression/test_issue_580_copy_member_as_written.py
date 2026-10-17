"""Regression tests for #580: codebase-graph / copybook-impact / MCP
impact_of_change resolved the upper-cased basename of a COPY member instead
of the member as written, so `COPY ordrec.` (a lowercase file on a
case-sensitive filesystem) and `COPY "sub/SUBREC.cpy".` (a path literal)
were reported unresolved although the expander inlines both -- and the
not-found note suggested the very name it had looked up."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cobolparser.analysis.codebase import CodebaseGraphBuilder, CopybookImpactAnalyzer
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.preprocess import CopybookNotFoundError
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver

case_sensitive_fs = pytest.mark.skipif(
    sys.platform in ("win32", "darwin"),
    reason="needs a case-sensitive filesystem",
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY ordrec.
       COPY "sub/SUBREC.cpy".
       PROCEDURE DIVISION.
           MOVE 1 TO ORD-ID
           MOVE 2 TO SUB-ID
           GOBACK.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "copybooks" / "sub").mkdir(parents=True)
    (tmp_path / "copybooks" / "ordrec.cpy").write_text(
        "       01 ORD-REC.\n          05 ORD-ID PIC 9(4).\n"
    )
    (tmp_path / "copybooks" / "sub" / "SUBREC.cpy").write_text(
        "       01 SUB-REC.\n          05 SUB-ID PIC 9(4).\n"
    )
    (tmp_path / "P1.cbl").write_text(PROGRAM)
    return tmp_path


@case_sensitive_fs
def test_codebase_graph_resolves_members_as_written(root: Path) -> None:
    graph = CodebaseGraphBuilder(copybook_paths=[str(root / "copybooks")]).build(
        [str(root / "P1.cbl")]
    )
    paths = {edge.member: edge.path for edge in graph.copy_edges}
    assert paths["ORDREC"] == str(root / "copybooks" / "ordrec.cpy")
    assert paths["SUBREC"] == str(root / "copybooks" / "sub" / "SUBREC.cpy")
    assert not any("could not be resolved" in note for note in graph.unresolved)


@case_sensitive_fs
def test_copybook_impact_reports_the_member_fields(root: Path) -> None:
    graph = CodebaseGraphBuilder(copybook_paths=[str(root / "copybooks")]).build(
        [str(root / "P1.cbl")]
    )
    report = CopybookImpactAnalyzer(graph).analyze("ordrec")
    assert "ORD-ID" in report.fields
    assert report.unresolved == []


@case_sensitive_fs
def test_mcp_impact_of_change_resolves_the_member(root: Path) -> None:
    tools = CobolTools(
        Workspace(root, ProjectConfig(copybook_path=(str(root / "copybooks"),)))
    )
    answer = tools.impact_of_change("ORDREC")["answer"]
    assert answer["resolved_to"] == ["copybooks/ordrec.cpy"]


@case_sensitive_fs
def test_not_found_never_suggests_the_name_it_looked_up(tmp_path: Path) -> None:
    (tmp_path / "ordrec.cpy").write_text("       01 ORD-REC PIC X.\n")
    resolver = PathResolver(CopybookSearchPath(directories=[str(tmp_path)]))
    with pytest.raises(CopybookNotFoundError) as caught:
        resolver.resolve("ORDREC")
    assert "ORDREC" not in caught.value.suggestions
    assert "Did you mean: ORDREC" not in str(caught.value)
    assert caught.value.case_variant_exists
    assert "different letter case" in str(caught.value)
