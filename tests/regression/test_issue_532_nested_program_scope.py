"""Regression tests for #532: nested programs were treated as globally
CALL-able. The parser did not record nesting (every unit hung flat off the
first program), so codebase-graph and MCP ``callers_of`` drew edges from
other files to a nested program, flagged two files' nested ERRHANDs as a
duplicate PROGRAM-ID, and reported a stacked program as contained."""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.models.program import CobolProgram
from cobolparser.scan import ScanOptions, scan_files

OUTER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
           CALL 'INNER'
           CALL 'SIBLING'
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER IS COMMON.
       PROCEDURE DIVISION.
           CALL 'DEEP'
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEEP.
       PROCEDURE DIVISION.
           GOBACK.
       END PROGRAM DEEP.
       END PROGRAM INNER.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIBLING.
       PROCEDURE DIVISION.
           CALL 'INNER'
           GOBACK.
       END PROGRAM SIBLING.
       END PROGRAM OUTER.
"""

OTHER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OTHER.
       PROCEDURE DIVISION.
           CALL 'INNER'
           GOBACK.
"""


def _with_errhand(name: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {name}.\n"
        "       PROCEDURE DIVISION.\n"
        "           CALL 'ERRHAND'\n"
        "           GOBACK.\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. ERRHAND.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
        "       END PROGRAM ERRHAND.\n"
        f"       END PROGRAM {name}.\n"
    )


STACKED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIRSTP.
       PROCEDURE DIVISION.
           GOBACK.
       END PROGRAM FIRSTP.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECONDP.
       PROCEDURE DIVISION.
           GOBACK.
       END PROGRAM SECONDP.
"""


def _units(source: str) -> dict[str, CobolProgram]:
    result = parse_cobol(source)
    assert result.errors == []
    return {u.program_name: u for u in result.ast.program_units()}


class TestParserRecordsNesting:
    def test_nested_programs_know_their_container(self) -> None:
        units = _units(OUTER)
        assert units["OUTER"].enclosing_program is None
        assert units["INNER"].enclosing_program is units["OUTER"]
        assert units["DEEP"].enclosing_program is units["INNER"]
        assert units["SIBLING"].enclosing_program is units["OUTER"]
        assert [units[n].nesting_depth for n in ("OUTER", "INNER", "DEEP")] == [
            0,
            1,
            2,
        ]
        assert units["INNER"].is_common
        assert not units["SIBLING"].is_common

    def test_stacked_program_is_not_nested(self) -> None:
        units = _units(STACKED)
        assert not units["SECONDP"].is_nested
        assert units["SECONDP"].nesting_depth == 0

    def test_call_scope(self) -> None:
        units = _units(OUTER)
        assert units["OUTER"].nested_program_called("INNER") is units["INNER"]
        # INNER is COMMON: its sibling may call it.
        assert units["SIBLING"].nested_program_called("INNER") is units["INNER"]
        # SIBLING is not COMMON: INNER cannot reach it.
        assert units["INNER"].nested_program_called("SIBLING") is None
        # DEEP is visible only from INNER, which directly contains it.
        assert units["OUTER"].nested_program_called("DEEP") is None
        assert units["INNER"].nested_program_called("DEEP") is units["DEEP"]

    def test_nesting_survives_json(self) -> None:
        source = STACKED + OUTER
        restored = CobolProgram.from_json(parse_cobol(source).ast.to_json())
        units = {u.program_name: u for u in restored.program_units()}
        assert not units["OUTER"].is_nested
        assert units["DEEP"].enclosing_program is units["INNER"]
        assert units["INNER"].enclosing_program is units["OUTER"]


class TestCodebaseGraph:
    def test_no_edge_from_another_file_to_a_nested_program(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "outer.cbl").write_text(OUTER)
        (tmp_path / "other.cbl").write_text(OTHER)
        graph = CodebaseGraphBuilder().build(
            [str(tmp_path / "outer.cbl"), str(tmp_path / "other.cbl")]
        )
        edges = {(e.caller, e.callee) for e in graph.call_edges}
        assert ("OUTER", "OUTER/INNER") in edges
        assert ("OUTER/SIBLING", "OUTER/INNER") in edges
        assert ("OUTER/INNER", "OUTER/INNER/DEEP") in edges
        # OTHER's CALL 'INNER' reaches a separately compiled INNER.
        assert ("OTHER", "INNER") in edges
        assert graph.callers_of("OUTER/INNER") == ["OUTER", "OUTER/SIBLING"]

    def test_each_file_reaches_its_own_nested_program(self, tmp_path: Path) -> None:
        (tmp_path / "PGMA.cbl").write_text(_with_errhand("PGMA"))
        (tmp_path / "PGMB.cbl").write_text(_with_errhand("PGMB"))
        graph = CodebaseGraphBuilder().build(
            [str(tmp_path / "PGMA.cbl"), str(tmp_path / "PGMB.cbl")]
        )
        assert not any("duplicate PROGRAM-ID" in n for n in graph.unresolved)
        assert graph.callees_of("PGMA") == ["PGMA/ERRHAND"]
        assert graph.callees_of("PGMB") == ["PGMB/ERRHAND"]

    def test_stacked_program_is_global(self, tmp_path: Path) -> None:
        (tmp_path / "stk.cbl").write_text(STACKED)
        graph = CodebaseGraphBuilder().build([str(tmp_path / "stk.cbl")])
        assert graph.program_ids == ["FIRSTP", "SECONDP"]


def _tools(root: Path) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig()))


class TestMcp:
    def test_callers_of_a_nested_program(self, tmp_path: Path) -> None:
        (tmp_path / "outer.cbl").write_text(OUTER)
        (tmp_path / "other.cbl").write_text(OTHER)
        answer = _tools(tmp_path).callers_of(None, "INNER")["answer"]
        assert answer["calling_programs"] == ["OUTER", "SIBLING"]
        assert all(c.get("nested") for c in answer["callers"])
        assert answer["out_of_scope_callers"] == ["OTHER"]

    def test_nested_duplicates_are_not_a_load_order_question(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "PGMA.cbl").write_text(_with_errhand("PGMA"))
        (tmp_path / "PGMB.cbl").write_text(_with_errhand("PGMB"))
        result = _tools(tmp_path).callers_of(None, "ERRHAND")
        assert "duplicate-declaration" not in [c["kind"] for c in result["caveats"]]
        assert result["answer"]["calling_programs"] == ["PGMA", "PGMB"]

    def test_stacked_program_is_not_contained(self, tmp_path: Path) -> None:
        (tmp_path / "stk.cbl").write_text(STACKED)
        answer = _tools(tmp_path).callers_of(None, "SECONDP")["answer"]
        assert answer["declared_in"] == [{"file": "stk.cbl"}]
        overview = _tools(tmp_path).codebase_overview()["answer"]
        assert "SECONDP" in overview["call_graph"]["entry_programs"]


def test_scan_depth_is_the_source_nesting(tmp_path: Path) -> None:
    (tmp_path / "stk.cbl").write_text(STACKED + OUTER)
    report = scan_files([str(tmp_path / "stk.cbl")], ScanOptions(), workers=1)
    (scanned,) = report.files
    depths = {u.program_name: u.depth for u in scanned.units}
    assert depths == {
        "FIRSTP": 0,
        "SECONDP": 0,
        "OUTER": 0,
        "INNER": 1,
        "DEEP": 2,
        "SIBLING": 1,
    }
