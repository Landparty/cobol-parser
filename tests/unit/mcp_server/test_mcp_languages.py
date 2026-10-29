"""PL/I and assembler programs in the cross-program tools, read through the
sibling parsers (the [pl1] / [hlasm] extras), over tests/samples/mixed/: a
PL/I driver CALLs a COBOL subprogram, both CALL an assembler routine (the
COBOL one through its ENTRY name), and JCL runs the driver and the routine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cobolparser.mcp import CobolTools, ToolError, Workspace, languages
from cobolparser.mcp.languages import languages_index, read_facts

pytest.importorskip("pl1_parser")
pytest.importorskip("hlasmparser")

MIXED = Path(__file__).resolve().parents[2] / "samples" / "mixed"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "mixed"
    shutil.copytree(MIXED, target)
    return target


@pytest.fixture
def tools(root: Path) -> CobolTools:
    return CobolTools(Workspace(root))


class TestFacts:
    def test_pli_calls_keep_the_real_program_of_an_alias(self, root: Path) -> None:
        facts = read_facts(Workspace(root), root / "PAYDRV.pli")
        assert facts.language == "PL/I"
        assert facts.program_id == "PAYDRV"
        rows = {r["program"]: r for r in facts.calls}
        # LOGIT is a local alias of PAYLOG; the internal SUMMARY is no call.
        assert set(rows) == {"PAYCALC", "PAYLOG", "DATERTN"}
        assert rows["PAYLOG"]["local_name"] == "LOGIT"
        assert rows["PAYCALC"]["sites"] == [
            {"location": {"file": "PAYDRV.pli", "line": 7}}
        ]
        assert facts.includes[0]["member"] == "PAYREC"
        assert [s["name"] for s in facts.sections] == ["PAYDRV", "SUMMARY"]

    def test_assembler_names_calls_and_services(self, root: Path) -> None:
        facts = read_facts(Workspace(root), root / "DATERTN.asm")
        assert facts.program_id == "DATERTN"
        assert facts.entries == ["DATECONV"]
        assert [(r["program"], r["via"]) for r in facts.calls] == [("AUDITLOG", "LINK")]
        assert facts.includes == [
            {"member": "DATEREGS", "location": {"file": "DATERTN.asm", "line": 5}}
        ]
        assert facts.services[0]["kind"] == "MQ"
        assert facts.services[0]["target"] == "MQPUT"

    def test_assembler_eploc_and_cics_link(self, tmp_path: Path) -> None:
        (tmp_path / "LNK.asm").write_text(
            "LNK      CSECT\n"
            "         XCTL  EPLOC=PGMNAME\n"
            "         EXEC  CICS LINK PROGRAM('CICSPGM')\n"
            "         EXEC  CICS XCTL PROGRAM(WSPGM)\n"
            "PGMNAME  DC    CL8'DYNPGM'\n"
            "         END\n"
        )
        facts = read_facts(Workspace(tmp_path), tmp_path / "LNK.asm")
        rows = {r["via"]: r for r in facts.calls}
        assert rows["XCTL"]["dynamic"] is True
        assert rows["XCTL"]["candidates"] == ["DYNPGM"]
        assert rows["XCTL"]["candidates_complete"] is True
        assert rows["EXEC CICS LINK"]["program"] == "CICSPGM"
        assert rows["EXEC CICS LINK"]["dynamic"] is False
        assert rows["EXEC CICS XCTL"]["dynamic"] is True
        assert rows["EXEC CICS XCTL"]["candidates_complete"] is False

    def test_index_reuses_unchanged_files(self, root: Path) -> None:
        workspace = Workspace(root)
        first = languages_index(workspace)
        (root / "PAYCALC.cbl").touch()  # not a PL/I / assembler source
        (root / "NEW.pli").write_text(" NEW: PROC OPTIONS(MAIN); END NEW;\n")
        second = languages_index(workspace)
        assert second is not first
        old = {s.path: s for s in first.sources}
        kept = [s for s in second.sources if s.path in old]
        assert all(s is old[s.path] for s in kept)
        assert any(s.program_id == "NEW" for s in second.sources)


class TestCallGraph:
    def test_overview_covers_every_language(self, tools: CobolTools) -> None:
        answer = tools.codebase_overview()["answer"]
        assert answer["index"]["program_units_by_language"] == {
            "COBOL": 1,
            "PL/I": 1,
            "assembler": 1,
        }
        rows = {r["program"]: r for r in answer["programs"]}
        assert rows["PAYDRV"]["language"] == "PL/I"
        assert "language" not in rows["PAYCALC"]
        # PAYDRV -> PAYCALC, PAYDRV -> DATERTN, PAYCALC -> DATECONV (an
        # ENTRY of DATERTN), so DATERTN is called by both.
        assert rows["DATERTN"]["called_by"] == 2
        assert rows["PAYDRV"]["calls"] == 3
        graph = answer["call_graph"]
        assert graph["entry_programs"] == ["PAYDRV"]
        missing = {r["program"] for r in graph["not_in_workspace"]}
        assert missing == {"AUDITLOG", "PAYLOG"}
        assert graph["in_workspace_not_analyzed"] == []

    def test_cycles_cross_languages(self, root: Path) -> None:
        (root / "DATERTN.asm").write_text(
            "DATERTN  CSECT\n         CALL  PAYDRV\n         END\n"
        )
        answer = CobolTools(Workspace(root)).codebase_overview()["answer"]
        assert ["DATERTN", "PAYDRV"] in answer["call_graph"]["cycles"]

    def test_callers_of_an_assembler_routine(self, tools: CobolTools) -> None:
        answer = tools.callers_of(None, "DATERTN")["answer"]
        assert answer["declared_in"] == [
            {"file": "DATERTN.asm", "language": "assembler"}
        ]
        callers = {c["program"]: c for c in answer["callers"]}
        assert callers["PAYDRV"]["language"] == "PL/I"
        assert callers["PAYDRV"]["location"] == {"file": "PAYDRV.pli", "line": 9}
        assert callers["PAYCALC"]["entry"] == "DATECONV"
        assert "note" not in answer

    def test_callers_of_a_cobol_program_from_pli(self, tools: CobolTools) -> None:
        answer = tools.callers_of(None, "PAYCALC")["answer"]
        assert answer["calling_programs"] == ["PAYDRV"]

    def test_callers_of_with_a_pli_file(self, tools: CobolTools) -> None:
        answer = tools.callers_of("PAYDRV.pli", "PAYCALC")["answer"]
        assert answer["kind"] == "program"
        assert answer["calling_programs"] == ["PAYDRV"]

    def test_claims(self, tools: CobolTools) -> None:
        results = tools.check_claims(
            [
                {"kind": "calls", "subject": "PAYDRV", "object": "PAYCALC"},
                {"kind": "calls", "subject": "PAYCALC", "object": "DATERTN"},
                {"kind": "copies", "subject": "DATERTN", "object": "DATEREGS"},
                {"kind": "calls", "subject": "DATERTN", "object": "PAYDRV"},
            ]
        )["answer"]["results"]
        verdicts = [r["verdict"] for r in results]
        assert verdicts == ["confirmed", "confirmed", "confirmed", "contradicted"]
        assert results[2]["evidence"] == [{"file": "DATERTN.asm", "line": 5}]

    def test_an_included_member(self, root: Path) -> None:
        # The PL/I member, and a COBOL copybook of the same name that a PL/I
        # %INCLUDE never reads.
        (root / "include").mkdir()
        (root / "include" / "PAYREC.inc").write_text(" DCL 1 PAYREC;\n")
        (root / "PAYREC.cpy").write_text("       01 PAYREC PIC X.\n")
        answer = CobolTools(Workspace(root)).impact_of_change("PAYREC")["answer"]
        assert answer["found"] is True
        assert answer["included_by_other_languages"] == [
            {
                "program": "PAYDRV",
                "file": "PAYDRV.pli",
                "language": "PL/I",
                "member_files": ["include/PAYREC.inc"],
                "include_sites": [{"file": "PAYDRV.pli", "line": 3}],
            }
        ]
        assert answer["coverage"]["files_read"] == {
            "COBOL": 1,
            "PL/I": 1,
            "assembler": 1,
        }


class TestBrief:
    def test_pli_brief(self, tools: CobolTools) -> None:
        result = tools.program_brief("PAYDRV.pli")
        answer = result["answer"]
        assert answer["language"] == "PL/I"
        assert answer["program_id"] == "PAYDRV"
        assert [p["name"] for p in answer["procedures"]] == ["PAYDRV", "SUMMARY"]
        assert answer["called_by"] == []
        # Not CALLed, but run: the brief names the step, not a guess.
        pytest.importorskip("jclparser")
        assert answer["run_by"] == [
            {
                "job": "PAYJOB",
                "step": "STEP1",
                "file": "PAYJOB.jcl",
                "location": {"file": "PAYJOB.jcl", "line": 2},
            }
        ]
        assert "note" not in answer
        assert any("DECLARE FILE" in c["detail"] for c in result["caveats"])

    def test_assembler_brief(self, tools: CobolTools) -> None:
        answer = tools.program_brief("DATERTN.asm")["answer"]
        assert answer["also_called_as"] == ["DATECONV"]
        assert answer["sections"] == [{"name": "DATERTN", "kind": "CSECT"}]
        assert answer["services"] == {"MQ": {"MQPUT": 1}}
        assert answer["called_by"] == ["PAYCALC", "PAYDRV"]

    def test_cobol_only_tools_say_so(self, tools: CobolTools) -> None:
        with pytest.raises(ToolError, match="PL/I source, not COBOL"):
            tools.explain_symbol("PAYDRV.pli", "EMP_COUNT")
        with pytest.raises(ToolError, match="assembler source, not COBOL"):
            tools.lint("DATERTN.asm")

    def test_read_source_reads_them(self, tools: CobolTools) -> None:
        answer = tools.read_source("DATERTN.asm", 3, 0, 0)["answer"]
        assert answer["lines"] == [{"line": 3, "text": "         ENTRY DATECONV"}]


class TestJcl:
    @pytest.fixture(autouse=True)
    def _needs_jcl(self) -> None:
        pytest.importorskip("jclparser")

    def test_jobs_running_names_the_source(self, tools: CobolTools) -> None:
        result = tools.jobs_running("DATERTN")
        assert result["answer"]["source"] == {
            "program_id": "DATERTN",
            "file": "DATERTN.asm",
            "language": "assembler",
        }
        assert any("DISP alone" in c["effect"] for c in result["caveats"])

    def test_jcl_job_program_sources(self, tools: CobolTools) -> None:
        answer = tools.jcl_job("PAYJOB.jcl")["answer"]
        assert answer["program_sources"] == {
            "PAYDRV": "PAYDRV.pli",
            "DATERTN": "DATERTN.asm",
        }


class TestWithoutTheParsers:
    @pytest.fixture(autouse=True)
    def _missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(languages, "parser_available", lambda language: False)

    def test_overview_names_the_install_commands(self, tools: CobolTools) -> None:
        result = tools.codebase_overview()
        details = " ".join(c["detail"] for c in result["caveats"])
        assert "cobol-parser[pl1]" in details
        assert "cobol-parser[hlasm]" in details
        graph = result["answer"]["call_graph"]
        # PAYCALC's CALL 'DATECONV': an ENTRY of the unread DATERTN.asm.
        assert {r["program"] for r in graph["in_workspace_not_analyzed"]} == {
            "DATECONV"
        }

    def test_brief_names_the_install_command(self, tools: CobolTools) -> None:
        with pytest.raises(ToolError, match=r"cobol-parser\[hlasm\]"):
            tools.program_brief("DATERTN.asm")


class TestFailures:
    def test_a_source_that_cannot_be_parsed_is_named(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hlasmparser

        def broken(*args: object, **kwargs: object) -> None:
            raise ValueError("bad source")

        monkeypatch.setattr(hlasmparser, "parse_hlasm", broken)
        tools = CobolTools(Workspace(root))
        result = tools.codebase_overview()
        assert "DATERTN" not in {r["program"] for r in result["answer"]["programs"]}
        assert any(
            "DATERTN.asm: ValueError: bad source" in c["detail"]
            for c in result["caveats"]
        )
        with pytest.raises(ToolError, match="cannot read DATERTN.asm as assembler"):
            tools.program_brief("DATERTN.asm")
