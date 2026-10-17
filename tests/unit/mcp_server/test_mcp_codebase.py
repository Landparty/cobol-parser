"""The cross-program MCP tools and the root-wide indexes behind them."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.codebase_index import (
    health_index,
    lineage_index,
    programs_index,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
ENTERPRISE = SAMPLES / "enterprise"
LINEAGE = SAMPLES / "lineage"

DYNAMIC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8).
       01  WS-ANY               PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'SUBPROG' TO WS-PGM
           CALL WS-PGM
           ACCEPT WS-ANY
           CALL WS-ANY
           STOP RUN.
"""

CLONE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC 9(3).
       01  WS-B                 PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 2000-TOTALS
           STOP RUN.
       2000-TOTALS.
           MOVE 1 TO WS-A
           ADD WS-A TO WS-B
           MULTIPLY 2 BY WS-B
           DISPLAY WS-B.
"""

FIELDREC = """\
      * A record copied into one program.
       01  CPY-REC.
           05  CPY-A            PIC 9(3).
           05  CPY-B            PIC 9(3).
           05  CPY-C            PIC 9(3).
"""

USESREC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USESREC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY FIELDREC.
       01  WS-OUT               PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE CPY-A TO WS-OUT
           DISPLAY WS-OUT
           STOP RUN.
"""

CICSDYN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSDYN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8) VALUE 'SUBPROG'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS LINK PROGRAM(WS-PGM) END-EXEC
           EXEC CICS RETURN END-EXEC.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A private copy of the enterprise samples, safe to edit."""
    target = tmp_path / "src"
    shutil.copytree(ENTERPRISE, target)
    return target


@pytest.fixture
def lineage_root(tmp_path: Path) -> Path:
    target = tmp_path / "lineage"
    shutil.copytree(LINEAGE, target)
    return target


def workspace(root: Path, **config: object) -> Workspace:
    return Workspace(root, ProjectConfig(**config))  # type: ignore[arg-type]


def with_copybooks(root: Path) -> CobolTools:
    return CobolTools(workspace(root, copybook_path=(str(root / "copybooks"),)))


def line_of(root: Path, location: dict) -> str:
    lines = (root / location["file"]).read_text().splitlines()
    return lines[location["line"] - 1]


def kinds(result: dict) -> list[str]:
    return [c["kind"] for c in result["caveats"]]


def touch_later(path: Path, text: str) -> None:
    """Write *text* and move the mtime on, so a stamp sees the change even on
    a filesystem with a coarse clock."""
    before = path.stat().st_mtime_ns if path.exists() else 0
    path.write_text(text)
    os.utime(path, ns=(before + 10**9, before + 10**9))


# -- the indexes ---------------------------------------------------------------


def _unreadable(root: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make *name* a program under *root* that cannot be read."""
    (root / name).write_text("       PROGRAM-ID. X.\n")
    original = Workspace.read_text

    def read_text(path: Path, warnings: list[str] | None = None) -> str:
        if path.name == name:
            raise ToolError(f"cannot read {name}: unreadable")
        return original(path, warnings)

    monkeypatch.setattr(Workspace, "read_text", staticmethod(read_text))


class TestIndexes:
    def test_program_files_follow_cobol_yml(self, root: Path) -> None:
        (root / ".hidden").mkdir()
        (root / ".hidden" / "SKIPPED.cbl").write_text(DYNAMIC)
        (root / "copybooks" / "MEMBER.cbl").write_text(FIELDREC)
        ws = workspace(root, copybook_path=(str(root / "copybooks"),))
        names = {p.name for p in ws.program_files()}
        assert "BATCHSEQ.cbl" in names
        assert "SKIPPED.cbl" not in names  # hidden directory
        assert "MEMBER.cbl" not in names  # a copybook directory holds members
        only = workspace(root, extensions=(".txt",))
        assert only.program_files() == []

    def test_built_once_and_kept_out_of_the_parse_cache(self, root: Path) -> None:
        ws = workspace(root)
        first = programs_index(ws)
        assert programs_index(ws) is first
        assert len(first.files) == 22
        # A walk over the root must not evict what a client asked about.
        assert ws._cache == {}

    def test_rebuilt_when_a_program_is_added_or_edited(self, root: Path) -> None:
        ws = workspace(root)
        first = programs_index(ws)
        (root / "DYNCALL.cbl").write_text(DYNAMIC)
        second = programs_index(ws)
        assert second is not first
        assert "DYNCALL.cbl" in second.files
        touch_later(root / "DYNCALL.cbl", DYNAMIC.replace("DYNCALL", "DYNCAL2"))
        third = programs_index(ws)
        assert third is not second
        assert third.units_named("DYNCAL2")

    def test_a_current_cached_parse_is_reused(self, root: Path) -> None:
        ws = workspace(root)
        parsed = ws.program("BATCHSEQ.cbl")
        assert ws.cached_or_parse(parsed.path) is parsed

    def test_a_config_change_drops_the_indexes(self, root: Path) -> None:
        ws = workspace(root)
        first = programs_index(ws)
        ws._use_config(ProjectConfig(copybook_path=(str(root / "copybooks"),)))
        assert programs_index(ws) is not first

    def test_an_unreadable_program_is_named(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A Latin-1 program is decoded, not refused, since #522: an
        # unreadable one is simulated instead.
        _unreadable(root, monkeypatch, "LATIN1.cbl")
        index = programs_index(workspace(root))
        assert "cannot read LATIN1.cbl" in index.failed["LATIN1.cbl"]
        assert index.graph.programs  # the rest still answered

    def test_lineage_and_health_are_separate_builds(self, root: Path) -> None:
        ws = workspace(root)
        assert "lineage" not in ws._indexes
        health_index(ws)
        assert set(ws._indexes) == {"health"}
        lineage_index(ws)
        assert set(ws._indexes) == {"health", "lineage"}

    # -- callers_of at program level -------------------------------------------------

    def test_a_symlink_out_of_the_root_is_not_indexed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "SECRET.cbl").write_text(DYNAMIC.replace("DYNCALL", "SECRET"))
        (outside / "SECRET.jcl").write_text("//SECRET JOB\n")
        inside = tmp_path / "root"
        inside.mkdir()
        (inside / "DYNCALL.cbl").write_text(DYNAMIC)
        (inside / "LINKED.cbl").symlink_to(outside / "SECRET.cbl")
        (inside / "LINKED.jcl").symlink_to(outside / "SECRET.jcl")
        ws = workspace(inside)
        assert [p.name for p in ws.program_files()] == ["DYNCALL.cbl"]
        assert ws.files_named((".jcl",)) == []
        answer = CobolTools(ws).codebase_overview()["answer"]
        assert [r["program"] for r in answer["programs"]] == ["DYNCALL"]

    def test_a_symlink_inside_the_root_is_indexed(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "DYNCALL.cbl").write_text(DYNAMIC)
        (tmp_path / "ALIAS.cbl").symlink_to(tmp_path / "real" / "DYNCALL.cbl")
        files = workspace(tmp_path).program_files()
        assert {p.name for p in files} == {"DYNCALL.cbl"}

    def test_progress_is_reported_while_indexing(self, root: Path) -> None:
        ws = workspace(root)
        seen: list[tuple[float, float | None, str]] = []
        ws.progress = lambda done, total, message: seen.append((done, total, message))
        programs_index(ws)
        assert len(seen) == 22
        assert seen[0][:2] == (0, 22)
        assert seen[0][2].startswith("reading ")

    def test_a_failing_progress_listener_is_dropped(self, root: Path) -> None:
        def broken(done: float, total: float | None, message: str) -> None:
            raise RuntimeError("client gone")

        ws = workspace(root)
        ws.progress = broken
        assert programs_index(ws).units
        assert ws.progress is None


class TestProgramCallers:
    def test_contained_program_called_from_two_siblings(self, root: Path) -> None:
        answer = CobolTools(workspace(root)).callers_of(None, "logger")["answer"]
        assert answer["kind"] == "program"
        assert answer["scope"] == "workspace"
        assert answer["declared_in"] == [{"file": "NESTED.cbl", "contained": True}]
        assert answer["calling_programs"] == ["POSTER", "VALIDATE"]
        for caller in answer["callers"]:
            assert "LOGGER" in line_of(root, caller["location"])
            assert caller["from"]

    def test_a_name_that_is_no_paragraph_falls_through_to_programs(
        self, root: Path
    ) -> None:
        answer = CobolTools(workspace(root)).callers_of("MQBATCH.cbl", "MQPUT1")
        assert answer["program"]["file"] == "MQBATCH.cbl"
        found = answer["answer"]
        assert found["calling_programs"] == ["MQBATCH"]
        assert found["declared_in"] == []
        assert "external" in found["note"]

    def test_a_program_nobody_calls(self, root: Path) -> None:
        answer = CobolTools(workspace(root)).callers_of(None, "BATCHSEQ")["answer"]
        assert answer["found"] is True
        assert answer["callers"] == []
        assert "started some other way" in answer["note"]

    def test_unknown_program_suggests(self, root: Path) -> None:
        answer = CobolTools(workspace(root)).callers_of(None, "BATCHSQ")["answer"]
        assert answer["found"] is False
        assert "BATCHSEQ" in answer["suggestions"]

    def test_dynamic_calls(self, root: Path) -> None:
        (root / "DYNCALL.cbl").write_text(DYNAMIC)
        result = CobolTools(workspace(root)).callers_of(None, "SUBPROG")
        (caller,) = result["answer"]["callers"]
        assert caller["program"] == "DYNCALL"
        assert caller["dynamic"] is True
        assert caller["target_from"] == "WS-PGM"
        assert "CALL WS-PGM" in line_of(root, caller["location"])
        (unknown,) = result["answer"]["unresolved_dynamic_calls"]
        assert unknown["target_from"] == "WS-ANY"
        assert "incomplete-analysis" in kinds(result)

    def test_a_dynamic_cics_link_is_resolved(self, root: Path) -> None:
        (root / "CICSDYN.cbl").write_text(CICSDYN)
        tools = CobolTools(workspace(root))
        result = tools.callers_of(None, "SUBPROG")
        (caller,) = [
            c for c in result["answer"]["callers"] if c["program"] == "CICSDYN"
        ]
        assert caller["via"] == "EXEC CICS LINK"
        assert caller["dynamic"] is True
        assert caller["target_from"] == "WS-PGM"
        assert not [
            u
            for u in result["answer"].get("unresolved_dynamic_calls", [])
            if u["program"] == "CICSDYN"
        ]
        brief = tools.program_brief("CICSDYN.cbl")["answer"]
        (link,) = brief["calls"]
        assert link["candidates"] == ["SUBPROG"]
        assert link["candidates_complete"] is True

    def test_a_program_id_declared_twice(self, root: Path) -> None:
        (root / "COPY2.cbl").write_text(DYNAMIC.replace("DYNCALL", "BATCHSEQ"))
        result = CobolTools(workspace(root)).callers_of(None, "BATCHSEQ")
        assert len(result["answer"]["declared_in"]) == 2
        assert "duplicate-declaration" in kinds(result)

    def test_unparsed_files_are_a_caveat(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unreadable(root, monkeypatch, "LATIN1.cbl")
        result = CobolTools(workspace(root)).callers_of(None, "LOGGER")
        (caveat,) = [c for c in result["caveats"] if "LATIN1.cbl" in c["detail"]]
        assert caveat["kind"] == "incomplete-analysis"


# -- impact_of_change: copybook members ------------------------------------------


class TestCopybookImpact:
    def test_a_member_with_its_copy_lines(self, root: Path) -> None:
        result = with_copybooks(root).impact_of_change("CUSTREC")
        answer = result["answer"]
        assert answer["kind"] == "copybook"
        assert answer["resolved_to"] == ["copybooks/CUSTREC.cpy"]
        (copier,) = answer["copied_by"]
        assert copier["program"] == "COPYREPL"
        assert len(copier["copy_sites"]) == 2
        for site in copier["copy_sites"]:
            assert "COPY CUSTREC" in line_of(root, site)
        # The library's notes name files the way every location does.
        for caveat in result["caveats"]:
            assert str(root) not in caveat["detail"]

    def test_a_member_reached_through_another(self, root: Path) -> None:
        answer = with_copybooks(root).impact_of_change("WSFLAGS.cpy")["answer"]
        assert answer["copied_by"] == []
        (through,) = answer["copied_through_other_members"]
        assert through["chains"] == [["COPYREPL", "WSCOUNTS", "WSFLAGS"]]
        assert "WS-EOF-FLAG" in answer["fields"]

    def test_a_program_id_declared_twice_keeps_each_file(self, tmp_path: Path) -> None:
        (tmp_path / "copy").mkdir()
        (tmp_path / "copy" / "FIELDREC.cpy").write_text(FIELDREC)
        (tmp_path / "A.cbl").write_text(USESREC)
        (tmp_path / "B.cbl").write_text(USESREC.replace("COPY FIELDREC.", ""))
        tools = CobolTools(workspace(tmp_path, copybook_path=(str(tmp_path / "copy"),)))
        result = tools.impact_of_change("FIELDREC")
        (copier,) = result["answer"]["copied_by"]
        assert copier["file"] == "A.cbl"
        assert [s["file"] for s in copier["copy_sites"]] == ["A.cbl"]
        assert "duplicate-declaration" in kinds(result)

    def test_an_unknown_member(self, root: Path) -> None:
        answer = with_copybooks(root).impact_of_change("CUSTRECX.cpy")["answer"]
        assert answer["found"] is False
        assert "CUSTREC" in answer["suggestions"]


# -- impact_of_change / where_from: fields ---------------------------------------


class TestFieldLineage:
    def test_forward_across_a_call_and_a_job(self, lineage_root: Path) -> None:
        pytest.importorskip("jclparser")
        tools = CobolTools(workspace(lineage_root))
        result = tools.impact_of_change("WS-FEE", "WRITER.cbl")
        answer = result["answer"]
        assert answer["kind"] == "field"
        assert answer["programs"] == ["READER", "SUBPGM", "WRITER"]
        assert "PROD.FEE.SUMMARY" in answer["datasets"]
        by_field = {(h["program"], h["field"]): h for h in answer["hits"]}
        linkage = by_field[("SUBPGM", "LK-FEE")]
        # The USING line itself, not the first line of the program.
        assert "PROCEDURE DIVISION USING" in line_of(lineage_root, linkage["location"])
        read = by_field[("READER", "FEE-REC.FEE-FEE")]
        assert read["file"] == "READER.cbl"
        assert "READ" in line_of(lineage_root, read["location"])
        assert any("DD FEEIN" in step for step in read["path"])
        assert any("WRITER.cbl:38" in step for step in read["path"])

    def test_backward(self, lineage_root: Path) -> None:
        pytest.importorskip("jclparser")
        answer = CobolTools(workspace(lineage_root)).where_from(
            "FEE-FEE", "READER.cbl"
        )["answer"]
        assert answer["direction"] == "backward"
        assert "WRITER" in answer["programs"]
        assert "PROD.TRAN.DAILY" in answer["datasets"]

    def test_depth_zero_stays_in_the_program(self, lineage_root: Path) -> None:
        answer = CobolTools(workspace(lineage_root)).impact_of_change(
            "WS-FEE", "WRITER.cbl", depth=0
        )["answer"]
        assert answer["programs"] == ["WRITER"]
        with pytest.raises(ToolError, match="depth"):
            CobolTools(workspace(lineage_root)).where_from(
                "WS-FEE", "WRITER.cbl", depth=-1
            )

    def test_unbound_files_without_jcl(self, lineage_root: Path) -> None:
        (lineage_root / "FEEJOB.jcl").unlink()
        result = CobolTools(workspace(lineage_root)).impact_of_change(
            "WS-FEE", "WRITER.cbl"
        )
        assert result["answer"]["programs"] == ["SUBPGM", "WRITER"]
        details = " ".join(c["detail"] for c in result["caveats"])
        assert "no JCL under the root binds them" in details

    def test_jcl_without_jcl_parser(
        self, lineage_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cobolparser.analysis.lineage_jcl as lineage_jcl

        def missing(*_args: object, **_kwargs: object) -> None:
            raise ImportError("no jclparser")

        monkeypatch.setattr(lineage_jcl, "load_jobs", missing)
        result = CobolTools(workspace(lineage_root)).impact_of_change(
            "WS-FEE", "WRITER.cbl"
        )
        details = " ".join(c["detail"] for c in result["caveats"])
        assert "jcl-parser is not installed" in details

    def test_every_program_declaring_the_name(self, lineage_root: Path) -> None:
        # No file: the name in every program, here WRITER's and READER's.
        answer = CobolTools(workspace(lineage_root)).impact_of_change("WS-FEE")[
            "answer"
        ]
        assert answer["kind"] == "field"
        assert {"READER", "WRITER"} <= set(answer["programs"])

    def test_unknown_field_suggests(self, lineage_root: Path) -> None:
        answer = CobolTools(workspace(lineage_root)).where_from(
            "WS-FEEE", "WRITER.cbl"
        )["answer"]
        assert answer["found"] is False
        assert "WS-FEE" in answer["suggestions"]

    def test_a_member_asked_as_a_field_gets_a_hint(self, root: Path) -> None:
        answer = with_copybooks(root).impact_of_change("CUSTREC", "COPYREPL.cbl")[
            "answer"
        ]
        assert answer["found"] is False
        assert "copybook member" in answer["hint"]

    def test_an_unknown_field_gets_no_member_hint(self, root: Path) -> None:
        answer = with_copybooks(root).impact_of_change("NOSUCH", "COPYREPL.cbl")[
            "answer"
        ]
        assert "hint" not in answer

    def test_a_duplicate_program_caveat_only_where_it_is_reached(
        self, lineage_root: Path
    ) -> None:
        (lineage_root / "DUP1.cbl").write_text(CLONE.format(name="DUPPROG"))
        (lineage_root / "DUP2.cbl").write_text(CLONE.format(name="DUPPROG"))
        tools = CobolTools(workspace(lineage_root))
        unrelated = tools.impact_of_change("WS-FEE", "WRITER.cbl")
        assert not [c for c in unrelated["caveats"] if "DUPPROG" in c["detail"]]
        related = tools.impact_of_change("WS-A", "DUP1.cbl")
        assert [c for c in related["caveats"] if "DUPPROG" in c["detail"]]

    def test_lines_inside_an_expanded_program(self, tmp_path: Path) -> None:
        (tmp_path / "copy").mkdir()
        (tmp_path / "copy" / "FIELDREC.cpy").write_text(FIELDREC)
        (tmp_path / "USESREC.cbl").write_text(USESREC)
        tools = CobolTools(workspace(tmp_path, copybook_path=(str(tmp_path / "copy"),)))
        answer = tools.impact_of_change("CPY-A", "USESREC.cbl")["answer"]
        (moved,) = [h for h in answer["hits"] if h["field"] == "WS-OUT"]
        # The expanded listing is five lines longer than the file: the
        # location is the MOVE in the file on disk, not in the listing.
        assert moved["location"] == {"file": "USESREC.cbl", "line": 9}

    def test_blank_names_are_refused(self, root: Path) -> None:
        tools = CobolTools(workspace(root))
        with pytest.raises(ToolError):
            tools.impact_of_change("  ")
        with pytest.raises(ToolError):
            tools.where_from(" ")
        with pytest.raises(ToolError):
            tools.callers_of(None, " ")


# -- codebase_overview -----------------------------------------------------------


class TestCodebaseOverview:
    def test_the_enterprise_samples(self, root: Path) -> None:
        result = with_copybooks(root).codebase_overview()
        answer = result["answer"]
        assert answer["index"]["program_files"] == 22
        assert answer["index"]["failed_files"] == 0
        rows = {r["program"]: r for r in answer["programs"]}
        assert rows["LOGGER"]["contained"] is True
        assert rows["LOGGER"]["called_by"] == 2
        assert rows["ACCOUNT"]["unit_kind"] == "CLASS"
        external = {e["program"]: e for e in answer["call_graph"]["not_in_workspace"]}
        assert external["CBLTDLI"]["called_by"] == ["IMSDLIB", "IMSMPP"]
        # A nested program is graphed under its container (#532).
        assert ["SUBPROG/FACTORL"] in answer["call_graph"]["cycles"]
        assert "BATCHSEQ" in answer["call_graph"]["entry_programs"]
        assert answer["copybooks"]["most_used"][0]["member"] == "SQLCA"
        assert sum(answer["health"]["grades"].values()) == len(answer["programs"])
        worst = answer["health"]["worst"]
        assert worst == sorted(worst, key=lambda u: -u["score"])

    def test_duplicated_paragraphs_across_programs(self, tmp_path: Path) -> None:
        for name in ("CLONEA", "CLONEB", "CLONEC"):
            (tmp_path / f"{name}.cbl").write_text(CLONE.format(name=name))
        answer = CobolTools(workspace(tmp_path)).codebase_overview(limit=2)["answer"]
        (group,) = answer["duplicated_code"]["groups"]
        assert group["clone_type"] == "TYPE_1"
        assert group["member_count"] == 3
        assert len(group["members"]) == 2
        for member in group["members"]:
            assert member["paragraph"] == "2000-TOTALS"
            assert "2000-TOTALS." in line_of(tmp_path, member["location"])

    def test_calls_count_resolved_targets(self, tmp_path: Path) -> None:
        (tmp_path / "DYNCALL.cbl").write_text(
            DYNAMIC.replace(
                "           ACCEPT WS-ANY\n           CALL WS-ANY\n",
                "           MOVE 'OTHER' TO WS-PGM\n           CALL WS-PGM\n",
            )
        )
        for name in ("SUBPROG", "OTHER"):
            (tmp_path / f"{name}.cbl").write_text(CLONE.format(name=name))
        answer = CobolTools(workspace(tmp_path)).codebase_overview()["answer"]
        rows = {r["program"]: r for r in answer["programs"]}
        assert rows["DYNCALL"]["calls"] == 2
        assert rows["SUBPROG"]["called_by"] == 1
        assert rows["OTHER"]["called_by"] == 1

    def test_limit_truncates_with_totals(self, root: Path) -> None:
        result = CobolTools(workspace(root)).codebase_overview(limit=3)
        assert len(result["answer"]["programs"]) == 3
        truncated = {t["field"]: t for t in result["truncated"]}
        assert truncated["programs"]["total"] == 34
