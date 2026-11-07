"""The JCL MCP tools (jcl_job, jobs_running, dataset_users), which read the
JCL under the root through the optional [jcl] extra -- none needs the SDK."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.tools.jcl_common import MAX_INSTREAM_LINES
from cobolparser.mcp.tools.jcl_index import INSTALL_HINT, _jcllib_names

pytest.importorskip("jclparser")

SAMPLES = Path(__file__).resolve().parents[2] / "samples"

#: payproc.jcl's in-stream PROC, as a cataloged member of its own.
PAYPROC = """\
//PAYPROC  PROC HLQ=TEST.PAY,MEMBER=DEFAULT,SOUT=*
//EXTRACT  EXEC PGM=PAYEXTR,PARM='&MEMBER'
//PAYMAST  DD DSN=&HLQ..MASTER,DISP=SHR
//PAYEXT   DD DSN=&&PAYWORK,DISP=(NEW,PASS),
//            UNIT=SYSDA,SPACE=(CYL,(5,5)),
//            DCB=(RECFM=FB,LRECL=120,BLKSIZE=12000)
//SYSPRINT DD SYSOUT=&SOUT
//REPORT   EXEC PGM=PAYRPT
//PAYEXT   DD DSN=&&PAYWORK,DISP=(OLD,DELETE)
//PAYRPT   DD SYSOUT=&SOUT
//SYSPRINT DD SYSOUT=&SOUT
//         PEND
"""

#: Invokes PAYPROC from the library, overriding one DD in each step.
CATALOGED = """\
//PAYROLL2 JOB (99999),'PAYROLL',CLASS=B
//*
//RUNPAY   EXEC PAYPROC,HLQ=PROD.PAY,MEMBER=WEEKLY
//EXTRACT.PAYMAST DD DSN=PROD.PAY.MASTER.WEEKLY,DISP=SHR
//REPORT.PAYRPT DD DSN=PROD.PAY.REPORT(+1),DISP=(NEW,CATLG,DELETE),
//            DCB=(RECFM=FBA,LRECL=133)
//
"""

#: Runs MISC (SELECTs INFILE, OUTFILE and SD SORTWK01) without OUTFILE, and
#: READER through the TSO launcher.
MISCJOB = """\
//MISCJOB  JOB (ACCT),'MISC',CLASS=A
//STEP1    EXEC PGM=MISC
//INFILE   DD  DSN=PROD.TRAN.DAILY(0),DISP=SHR
//         DD  DSN=PROD.TRAN.EXTRA,DISP=SHR
//STEP2    EXEC PGM=IKJEFT01
//SYSTSPRT DD  SYSOUT=*
//SYSTSIN  DD  *
  DSN SYSTEM(DB2P)
  RUN PROGRAM(READER) PLAN(READPLAN)
  END
/*
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """The lineage programs and the sample JCL, with a procedure library."""
    target = tmp_path / "src"
    shutil.copytree(SAMPLES / "lineage", target)
    for jcl in (SAMPLES / "jcl").glob("*.jcl"):
        shutil.copy(jcl, target / jcl.name)
    (target / "procs").mkdir()
    (target / "procs" / "PAYPROC.prc").write_text(PAYPROC)
    (target / "jobs").mkdir()
    (target / "jobs" / "PAYROLL2.jcl").write_text(CATALOGED)
    (target / "jobs" / "MISCJOB.jcl").write_text(MISCJOB)
    return target


def tools_for(root: Path) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig()))


def card(root: Path, location: dict) -> str:
    """The JCL card a location cites."""
    lines = (root / location["file"]).read_text().splitlines()
    return lines[location["line"] - 1]


def kinds(result: dict) -> list[str]:
    return [c["kind"] for c in result["caveats"]]


# -- jcl_job -----------------------------------------------------------------


class TestJclJob:
    def test_steps_and_dds_are_cited_at_their_cards(self, root: Path) -> None:
        result = tools_for(root).jcl_job("invupdt.jcl")
        assert result["caveats"] == []
        (job,) = result["answer"]["jobs"]
        assert job["name"] == "INVUPD01"
        assert job["parameters"]["CLASS"] == "A"
        assert card(root, job["location"]).startswith("//INVUPD01 JOB")
        (joblib,) = job["dds"]
        assert joblib["ddname"] == "JOBLIB"
        assert [m["dataset"] for m in joblib["concatenated"]] == ["SYS1.COB2LIB"]
        assert [s["name"] for s in job["steps"]] == ["STEP010", "STEP020"]
        for step in job["steps"]:
            assert card(root, step["location"]).startswith(f"//{step['name']} ")
            for dd in step["dds"]:
                assert card(root, dd["location"]).startswith(f"//{dd['ddname']} ")
        update = job["steps"][1]
        assert update["program"] == "INVUPDT"
        assert update["condition"] == "(4,LT,STEP010)"
        dds = {dd["ddname"]: dd for dd in update["dds"]}
        # SET symbols are substituted; DISP says what the step does.
        assert dds["INVFILE"]["dataset"] == "PROD.INV.MASTER"
        assert dds["INVFILE"]["access"] == "read"
        assert dds["RPTFILE"]["access"] == "create"
        assert dds["RPTFILE"]["record_format"] == "FBA"
        assert dds["RPTFILE"]["record_length"] == 133
        assert dds["SYSPRINT"]["kind"] == "sysout"
        assert result["answer"]["symbols"] == {"CYCLE": "D", "HLQ": "PROD.INV"}

    def test_instream_data_is_shown(self, root: Path) -> None:
        result = tools_for(root).jcl_job("invupdt.jcl", step="STEP010")
        (step,) = result["answer"]["jobs"][0]["steps"]
        sysin = next(dd for dd in step["dds"] if dd["ddname"] == "SYSIN")
        assert sysin["kind"] == "instream"
        assert sysin["instream_line_count"] == 2
        assert sysin["instream_lines"][0].strip() == "EDIT MODE=STRICT"
        assert next(dd for dd in step["dds"] if dd["ddname"] == "SYSUDUMP")["kind"] == (
            "dummy"
        )

    def test_instream_data_is_capped(self, root: Path) -> None:
        lines = "\n".join(f"  CARD {n}" for n in range(MAX_INSTREAM_LINES + 5))
        (root / "big.jcl").write_text(
            f"//BIG JOB (A),'B'\n//S1 EXEC PGM=SORT\n//SYSIN DD *\n{lines}\n/*\n"
        )
        step = tools_for(root).jcl_job("big.jcl")["answer"]["jobs"][0]["steps"][0]
        (sysin,) = step["dds"]
        assert sysin["instream_line_count"] == MAX_INSTREAM_LINES + 5
        assert len(sysin["instream_lines"]) == MAX_INSTREAM_LINES

    def test_in_stream_procedure_is_cited_in_the_job_file(self, root: Path) -> None:
        answer = tools_for(root).jcl_job("payproc.jcl")["answer"]
        assert answer["procedures"] == [{"name": "PAYPROC", "source": "in-stream"}]
        steps = answer["jobs"][0]["steps"]
        assert steps[0]["invokes_procedure"] == "PAYPROC"
        extract = steps[1]
        assert extract["name"] == "RUNPAY.EXTRACT"
        assert extract["from_procedure"] == "PAYPROC"
        assert extract["parm"] == "WEEKLY"
        assert extract["location"]["file"] == "payproc.jcl"
        assert card(root, extract["location"]).startswith("//EXTRACT ")

    def test_cataloged_procedure_is_cited_in_its_member(self, root: Path) -> None:
        answer = tools_for(root).jcl_job("jobs/PAYROLL2.jcl")["answer"]
        assert answer["procedures"] == [
            {"name": "PAYPROC", "source": "procs/PAYPROC.prc"}
        ]
        steps = {s["name"]: s for s in answer["jobs"][0]["steps"]}
        extract = steps["RUNPAY.EXTRACT"]
        assert extract["location"]["file"] == "procs/PAYPROC.prc"
        assert card(root, extract["location"]).startswith("//EXTRACT ")
        dds = {dd["ddname"]: dd for dd in extract["dds"]}
        # The override is in the job file, the rest in the member -- even
        # where the two share a line number.
        assert dds["PAYMAST"]["dataset"] == "PROD.PAY.MASTER.WEEKLY"
        assert dds["PAYMAST"]["location"]["file"] == "jobs/PAYROLL2.jcl"
        assert card(root, dds["PAYMAST"]["location"]).startswith("//EXTRACT.PAYMAST")
        assert dds["PAYEXT"]["location"]["file"] == "procs/PAYPROC.prc"
        assert dds["PAYEXT"]["kind"] == "temporary"
        assert card(root, dds["PAYEXT"]["location"]).startswith("//PAYEXT ")
        assert answer["program_sources"] == {"PAYEXTR": None, "PAYRPT": None}

    def test_missing_procedure_is_a_caveat(self, root: Path) -> None:
        (root / "procs" / "PAYPROC.prc").unlink()
        (root / "procs" / "OTHER.prc").write_text("//OTHER PROC\n//S EXEC PGM=X\n")
        result = tools_for(root).jcl_job("jobs/PAYROLL2.jcl")
        assert "incomplete-analysis" in kinds(result)
        assert result["answer"]["procedures"] == [
            {"name": "PAYPROC", "source": None, "expanded": False}
        ]
        (step,) = result["answer"]["jobs"][0]["steps"]
        assert {dd.get("unapplied_override") for dd in step["dds"]} == {
            "EXTRACT.PAYMAST",
            "REPORT.PAYRPT",
        }

    def test_program_sources_are_matched_by_member_name(self, root: Path) -> None:
        answer = tools_for(root).jcl_job("FEEJOB.jcl")["answer"]
        assert answer["program_sources"] == {
            "WRITER": "WRITER.cbl",
            "SORT": None,
            "READER": "READER.cbl",
        }

    def test_launcher_step_names_what_it_runs(self, root: Path) -> None:
        answer = tools_for(root).jcl_job("jobs/MISCJOB.jcl", step="STEP2")["answer"]
        (step,) = answer["jobs"][0]["steps"]
        assert step["program"] == "IKJEFT01"
        assert step["runs"] == ["READER"]
        assert answer["program_sources"] == {"READER": "READER.cbl"}

    def test_filters(self, root: Path) -> None:
        tools = tools_for(root)
        answer = tools.jcl_job("payproc.jcl", job="payroll1", step="report")["answer"]
        assert [s["name"] for s in answer["jobs"][0]["steps"]] == ["RUNPAY.REPORT"]
        with pytest.raises(ToolError, match="no job named 'NOPE'.*PAYROLL1"):
            tools.jcl_job("payproc.jcl", job="NOPE")
        with pytest.raises(ToolError, match="no step named 'NOPE'.*RUNPAY"):
            tools.jcl_job("payproc.jcl", step="NOPE")

    def test_limit_cuts_steps(self, root: Path) -> None:
        result = tools_for(root).jcl_job("FEEJOB.jcl", limit=1)
        assert len(result["answer"]["jobs"][0]["steps"]) == 1
        assert result["answer"]["jobs"][0]["step_count"] == 3
        assert result["truncated"] == [
            {"field": "FEEJOB.steps", "shown": 1, "total": 3}
        ]

    def test_errors_are_cited_and_a_caveat(self, root: Path) -> None:
        (root / "bad.jcl").write_text(
            "//BADJOB JOB (A),'B'\n//S1 EXEC PGM=A\n//IN DD DSN=X,DISP=SHR\n"
            "//S2 EXEC PGM=B,COND=(4,LT\n//OUT DD SYSOUT=*\n"
        )
        result = tools_for(root).jcl_job("bad.jcl")
        assert "partial-parse" in kinds(result)
        errors = result["answer"]["errors"]
        assert errors and errors[0]["location"]["file"] == "bad.jcl"
        assert errors[0]["message"]

    def test_jcl_under_another_suffix(self, root: Path) -> None:
        shutil.copy(root / "FEEJOB.jcl", root / "FEEJOB.txt")
        answer = tools_for(root).jcl_job("FEEJOB.txt")["answer"]
        assert answer["file"] == "FEEJOB.txt"
        assert answer["jobs"][0]["steps"][0]["location"]["file"] == "FEEJOB.txt"

    def test_no_job_in_file(self, root: Path) -> None:
        (root / "empty.jcl").write_text("//* only a comment\n")
        answer = tools_for(root).jcl_job("empty.jcl")["answer"]
        assert answer["jobs"] == []
        assert "note" in answer

    def test_path_guard_still_applies(self, root: Path) -> None:
        with pytest.raises(ToolError, match="outside the workspace"):
            tools_for(root).jcl_job("../elsewhere.jcl")


# -- jobs_running ------------------------------------------------------------


class TestJobsRunning:
    def test_selects_are_bound_to_dds_and_datasets(self, root: Path) -> None:
        result = tools_for(root).jobs_running("reader")
        answer = result["answer"]
        assert answer["program"] == "READER"
        assert answer["source"] == {"file": "READER.cbl", "program_id": "READER"}
        assert {f["file_name"]: f["ddname"] for f in answer["files"]} == {
            "FEE-FILE": "FEEIN",
            "MAST-FILE": "MASTER",
        }
        for f in answer["files"]:
            assert "SELECT " + f["file_name"] in card(root, f["declared_at"])
        # FEEJOB's STEP030 by PGM=, MISCJOB's STEP2 through IKJEFT01.
        assert answer["step_count"] == 2
        by_job = {s["job"]: s for s in answer["steps"]}
        direct = by_job["FEEJOB"]
        assert card(root, direct["location"]).startswith("//STEP030 ")
        fee = next(dd for dd in direct["dds"] if dd["ddname"] == "FEEIN")
        assert fee["cobol_files"] == ["FEE-FILE"]
        assert fee["dataset"] == "PROD.FEE.SUMMARY(+1)"
        assert "dds_not_coded" not in direct
        launched = by_job["MISCJOB"]
        assert launched["runs"] == ["READER"]
        assert {d["ddname"] for d in launched["dds_not_coded"]} == {"FEEIN", "MASTER"}

    def test_an_ibm_procedure_not_under_the_root_is_expanded_from_its_template(
        self, root: Path
    ) -> None:
        # #744: EXEC DLIBATCH,MBR=prog is how an IMS batch program is run, and
        # IBM's PROCLIB is seldom copied next to the JCL.
        (root / "jobs" / "IMSJOB.jcl").write_text(
            "//IMSJOB   JOB (ACCT),'IMS',CLASS=A\n"
            "//*\n"
            "//STEP1    EXEC DLIBATCH,MBR=READER,PSB=READPSB\n"
            "//G.FEEIN  DD DSN=PROD.FEE.IMS,DISP=SHR\n"
        )
        tools = tools_for(root)
        result = tools.jobs_running("READER")
        answer = result["answer"]
        assert answer["step_count"] == 3
        (step,) = [s for s in answer["steps"] if s["job"] == "IMSJOB"]
        assert step["name"] == "STEP1.G"
        assert step["runs"] == ["READER"]
        assert step["location"] == {"file": "jobs/IMSJOB.jcl", "line": 3}
        dds = {dd["ddname"]: dd for dd in step["dds"]}
        assert dds["FEEIN"]["cobol_files"] == ["FEE-FILE"]
        assert dds["FEEIN"]["location"] == {"file": "jobs/IMSJOB.jcl", "line": 4}
        # The template's own cards are in no file under the root.
        assert dds["STEPLIB"].get("location") is None
        assert [d["ddname"] for d in step["dds_not_coded"]] == ["MASTER"]
        assert "incomplete-analysis" in kinds(result)
        assert any(
            "jobs/IMSJOB.jcl (DLIBATCH)" in c["detail"] and "templates" in c["detail"]
            for c in result["caveats"]
        )
        # A template is no unresolved procedure.
        assert not any(
            "IMSJOB" in c["detail"] and "unresolved procedures" in c["detail"]
            for c in result["caveats"]
        )
        job_result = tools.jcl_job("jobs/IMSJOB.jcl")
        assert any(
            "PROC DLIBATCH (line 3): expanded from jcl-parser's template" in c["detail"]
            and "not your PROCLIB" in c["effect"]
            for c in job_result["caveats"]
        )
        job = job_result["answer"]
        assert job["procedures"] == [
            {"name": "DLIBATCH", "source": "jcl-parser template"}
        ]
        users = tools.dataset_users("PROD.FEE.IMS")["answer"]
        assert users["by_access"] == {"read": ["READER"]}

    def test_dds_not_coded_skip_sort_work_files(self, root: Path) -> None:
        answer = tools_for(root).jobs_running("MISC")["answer"]
        files = {f["file_name"]: f for f in answer["files"]}
        assert files["IN-FILE"]["ddname"] == "INFILE"  # UT-S- stripped
        assert files["SRT-FILE"]["sort_work_file"] is True
        (step,) = answer["steps"]
        assert step["dds_not_coded"] == [{"file_name": "OUT-FILE", "ddname": "OUTFILE"}]
        (infile,) = step["dds"]
        assert [m["dataset"] for m in infile["concatenated"]] == ["PROD.TRAN.EXTRA"]

    def test_optional_and_dynamic_files(self, root: Path) -> None:
        (root / "OPTPGM.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. OPTPGM.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT OPTIONAL OPT-FILE ASSIGN TO OPTDD.\n"
            "           SELECT DYN-FILE ASSIGN USING WS-NAME.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD  OPT-FILE.\n"
            "       01  OPT-REC PIC X(10).\n"
            "       FD  DYN-FILE.\n"
            "       01  DYN-REC PIC X(10).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  WS-NAME PIC X(44).\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        (root / "OPTJOB.jcl").write_text("//OPTJOB JOB (A),'B'\n//S1 EXEC PGM=OPTPGM\n")
        answer = tools_for(root).jobs_running("OPTPGM")["answer"]
        files = {f["file_name"]: f for f in answer["files"]}
        assert files["OPT-FILE"]["optional"] is True
        assert files["DYN-FILE"]["ddname"] is None
        assert files["DYN-FILE"]["assign_using"] == "WS-NAME"
        assert "dds_not_coded" not in answer["steps"][0]

    def test_source_found_by_program_id_when_the_file_is_named_otherwise(
        self, root: Path
    ) -> None:
        (root / "READER.cbl").rename(root / "rdr0001.cbl")
        answer = tools_for(root).jobs_running("READER")["answer"]
        assert answer["source"]["file"] == "rdr0001.cbl"

    def test_program_without_source_or_jcl(self, root: Path) -> None:
        answer = tools_for(root).jobs_running("PAYEXTR")["answer"]
        assert "source" not in answer
        # The in-stream PROC of payproc.jcl and the cataloged one.
        assert {(s["file"], s["name"]) for s in answer["steps"]} == {
            ("payproc.jcl", "RUNPAY.EXTRACT"),
            ("jobs/PAYROLL2.jcl", "RUNPAY.EXTRACT"),
        }
        never = tools_for(root).jobs_running("SUBPGM")["answer"]
        assert never["steps"] == []
        assert "callers_of" in never["note"]

    def test_empty_root(self, tmp_path: Path) -> None:
        answer = tools_for(tmp_path).jobs_running("X")["answer"]
        assert answer["jcl_files"] == 0
        assert "no .jcl / .job file" in answer["note"]

    def test_no_program(self, root: Path) -> None:
        with pytest.raises(ToolError, match="no program"):
            tools_for(root).jobs_running("  ")

    def test_files_with_errors_are_summarized(self, root: Path) -> None:
        (root / "bad.jcl").write_text(
            "//BADJOB JOB (A),'B'\n//S1 EXEC PGM=READER,COND=(4,LT\n"
        )
        result = tools_for(root).jobs_running("READER")
        assert "partial-parse" in kinds(result)


# -- dataset_users -----------------------------------------------------------


class TestDatasetUsers:
    def test_generations_match_their_base(self, root: Path) -> None:
        answer = tools_for(root).dataset_users("prod.fee.summary")["answer"]
        assert answer["use_count"] == 2
        assert answer["by_access"] == {"create": ["SORT"], "read": ["READER"]}
        assert answer["jobs"] == ["FEEJOB"]
        for use in answer["uses"]:
            assert card(root, use["location"]).startswith(f"//{use['ddname']} ")

    def test_exact_generation(self, root: Path) -> None:
        tools = tools_for(root)
        assert tools.dataset_users("PROD.TRAN.DAILY(0)")["answer"]["use_count"] == 2
        assert tools.dataset_users("PROD.TRAN.DAILY(+1)")["answer"]["use_count"] == 0

    def test_wildcards_follow_zos_filters(self, root: Path) -> None:
        tools = tools_for(root)
        # '*' stays within one qualifier ...
        answer = tools.dataset_users("PROD.INV.*")["answer"]
        assert {u["dataset"] for u in answer["uses"]} == {
            "PROD.INV.TRANS(0)",
            "PROD.INV.MASTER",
        }
        # ... and '**' spans any number of them.
        answer = tools.dataset_users("PROD.INV.**")["answer"]
        assert {u["dataset"] for u in answer["uses"]} == {
            "PROD.INV.TRANS(0)",
            "PROD.INV.TRANS.GOOD",
            "PROD.INV.MASTER",
            "PROD.INV.REPORT.D",
        }
        assert {
            u["dataset"] for u in tools.dataset_users("**.MASTER")["answer"]["uses"]
        } == {"PROD.INV.MASTER", "PROD.ACCT.MASTER"}
        good = [u for u in answer["uses"] if u["dataset"] == "PROD.INV.TRANS.GOOD"]
        assert {u["access"] for u in good} == {"create", "exclusive"}
        percent = tools_for(root).dataset_users("PROD.INV.REPORT.%")["answer"]
        assert percent["use_count"] == 1

    def test_job_level_dd(self, root: Path) -> None:
        answer = tools_for(root).dataset_users("SYS1.COB2LIB")["answer"]
        (use,) = answer["uses"]
        assert use["step"] is None
        assert use["programs"] == []
        assert answer["by_access"] == {"read": ["INVUPD01.JOB"]}

    def test_temporary_dataset(self, root: Path) -> None:
        answer = tools_for(root).dataset_users("&&PAYWORK")["answer"]
        # Both steps of the procedure, in-stream (PAYROLL1) and cataloged.
        assert answer["use_count"] == 4
        assert answer["jobs"] == ["PAYROLL1", "PAYROLL2"]
        assert all(u["temporary"] for u in answer["uses"])
        assert "temporary_note" in answer

    def test_not_found(self, root: Path) -> None:
        answer = tools_for(root).dataset_users("NO.SUCH.DATA")["answer"]
        assert answer["uses"] == []
        assert "note" in answer
        with pytest.raises(ToolError, match="no dataset"):
            tools_for(root).dataset_users("''")

    def test_limit(self, root: Path) -> None:
        result = tools_for(root).dataset_users("PROD.**", limit=2)
        assert len(result["answer"]["uses"]) == 2
        assert result["truncated"][0]["field"] == "uses"


# -- the index and the extra -------------------------------------------------


class TestReviewFixes:
    def test_a_program_source_never_shadows_a_procedure_member(
        self, root: Path
    ) -> None:
        # A procedure named after the program it runs, in a mixed directory:
        # PAYPROC.cbl sorts before PAYPROC.prc.
        (root / "procs" / "PAYPROC.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYPROC.\n"
        )
        answer = tools_for(root).jcl_job("jobs/PAYROLL2.jcl")["answer"]
        assert answer["procedures"] == [
            {"name": "PAYPROC", "source": "procs/PAYPROC.prc"}
        ]
        assert "RUNPAY.EXTRACT" in [s["name"] for s in answer["jobs"][0]["steps"]]

    def test_concatenation_after_an_override_is_cited_card_by_card(
        self, root: Path
    ) -> None:
        (root / "procs" / "LIBPROC.prc").write_text(
            "//LIBPROC PROC\n"
            "//PS1     EXEC PGM=INVUPDT\n"
            "//STEPLIB  DD DSN=P.LIB1,DISP=SHR\n"
            "//         DD DSN=P.LIB2,DISP=SHR\n"
            "//         DD DSN=P.LIB3,DISP=SHR\n"
            "//         PEND\n"
        )
        (root / "jobs" / "LIBJOB.jcl").write_text(
            "//LIBJOB JOB (A),'B'\n"
            "//*\n"
            "//R1 EXEC LIBPROC\n"
            "//PS1.STEPLIB DD DSN=O.LIB1,DISP=SHR\n"
            "//        DD DSN=O.LIB2,DISP=SHR\n"
        )
        tools = tools_for(root)
        uses = tools.dataset_users("*.LIB%")["answer"]["uses"]
        located = {u["dataset"]: u["location"] for u in uses}
        assert located == {
            "O.LIB1": {"file": "jobs/LIBJOB.jcl", "line": 4},
            "O.LIB2": {"file": "jobs/LIBJOB.jcl", "line": 5},
            "P.LIB3": {"file": "procs/LIBPROC.prc", "line": 5},
        }
        for dataset, location in located.items():
            assert dataset in card(root, location)
        step = tools.jcl_job("jobs/LIBJOB.jcl", step="PS1")["answer"]["jobs"][0][
            "steps"
        ][0]
        (steplib,) = step["dds"]
        assert [m["location"] for m in steplib["concatenated"]] == [
            located["O.LIB2"],
            located["P.LIB3"],
        ]

    def test_a_source_that_does_not_parse_keeps_the_steps(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(self: Workspace, file: str) -> None:
            raise ToolError(f"{file} could not be parsed")

        monkeypatch.setattr(Workspace, "program", refuse)
        result = tools_for(root).jobs_running("READER")
        assert result["answer"]["step_count"] == 2
        assert "files" not in result["answer"]
        assert "analyzer-failed" in kinds(result)

    def test_a_utility_parses_no_program(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(self: Workspace, file: str) -> None:
            raise AssertionError(f"parsed {file}")

        monkeypatch.setattr(Workspace, "program", refuse)
        monkeypatch.setattr(Workspace, "cached_or_parse", refuse)
        answer = tools_for(root).jobs_running("SORT")["answer"]
        assert answer["step_count"] == 1
        assert "source" not in answer


class TestProcedureLibraries:
    """Where cataloged PROCs come from: JCLLIB, proc_path, PROCLIB folders."""

    def _move_payproc(self, root: Path, folder: str, name: str) -> Path:
        (root / "procs" / "PAYPROC.prc").unlink()
        target = root / folder
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(PAYPROC)
        return target / name

    def _extract(self, root: Path, config: ProjectConfig | None = None) -> dict:
        tools = CobolTools(Workspace(root, config or ProjectConfig()))
        result = tools.jcl_job("jobs/PAYROLL2.jcl")
        steps = {s["name"]: s for s in result["answer"]["jobs"][0]["steps"]}
        return {"result": result, "steps": steps}

    def test_jcllib_library_folder(self, root: Path) -> None:
        self._move_payproc(root, "lib/PROD.MY.PROCS", "PAYPROC")
        (root / "jobs" / "PAYROLL2.jcl").write_text(
            CATALOGED.replace("//*\n", "//PROCS    JCLLIB ORDER=(PROD.MY.PROCS)\n", 1)
        )
        got = self._extract(root)
        extract = got["steps"]["RUNPAY.EXTRACT"]
        assert extract["program"] == "PAYEXTR"
        assert extract["location"]["file"] == "lib/PROD.MY.PROCS/PAYPROC"
        answer = got["result"]["answer"]
        assert "lib/PROD.MY.PROCS" in answer["procedure_libraries"]

    def test_jcllib_order_continued_over_cards(self) -> None:
        text = (
            "//J        JOB (A)\n"
            "//PROCS    JCLLIB ORDER=(PROD.A,\n"
            "//             'PROD.B')   A COMMENT\n"
            "//         JCLLIB ORDER=PROD.C\n"
        )
        assert _jcllib_names(text) == ["PROD.A", "PROD.B", "PROD.C"]

    def test_missing_jcllib_library_is_a_caveat(self, root: Path) -> None:
        (root / "jobs" / "PAYROLL2.jcl").write_text(
            CATALOGED.replace("//*\n", "//PROCS    JCLLIB ORDER=NOT.THERE\n", 1)
        )
        caveats = self._extract(root)["result"]["caveats"]
        assert any("NOT.THERE" in c["detail"] for c in caveats)

    def test_proc_path_takes_suffix_less_members(self, root: Path) -> None:
        member = self._move_payproc(root, "cfg", "PAYPROC")
        assert "RUNPAY.EXTRACT" not in self._extract(root)["steps"]
        got = self._extract(root, ProjectConfig(proc_path=(str(member.parent),)))
        extract = got["steps"]["RUNPAY.EXTRACT"]
        assert extract["location"]["file"] == "cfg/PAYPROC"

    def test_proclib_named_folder(self, root: Path) -> None:
        self._move_payproc(root, "SYS1.PROCLIB", "PAYPROC.jcl")
        got = self._extract(root)
        extract = got["steps"]["RUNPAY.EXTRACT"]
        assert extract["location"]["file"] == "SYS1.PROCLIB/PAYPROC.jcl"
        # A .jcl member of a procedure library is not read as a job.
        overview = tools_for(root).jcl_job("SYS1.PROCLIB/PAYPROC.jcl")
        assert overview["answer"]["jobs"] == []


class TestIndex:
    def test_a_changed_file_is_reread(self, root: Path) -> None:
        tools = tools_for(root)
        assert tools.dataset_users("NEW.DATA")["answer"]["use_count"] == 0
        (root / "jobs" / "NEW.jcl").write_text(
            "//NEWJOB JOB (A),'B'\n//S1 EXEC PGM=X\n//D DD DSN=NEW.DATA,DISP=MOD\n"
        )
        answer = tools.dataset_users("NEW.DATA")["answer"]
        assert answer["by_access"] == {"extend": ["X"]}

    def test_a_file_that_fails_is_named(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cobolparser.jcl import parser as jcl_parser

        real = jcl_parser.JclParser.parse

        def parse(self: object, text: str, *, filename: str = "<jcl>") -> object:
            if filename.endswith("payproc.jcl"):
                raise RuntimeError("boom")
            return real(self, text, filename=filename)  # type: ignore[arg-type]

        monkeypatch.setattr(jcl_parser.JclParser, "parse", parse)
        tools = tools_for(root)
        result = tools.dataset_users("PROD.**")
        assert "incomplete-analysis" in kinds(result)
        assert any("payproc.jcl" in c["detail"] for c in result["caveats"])
        with pytest.raises(ToolError, match="cannot read payproc.jcl.*boom"):
            tools.jcl_job("payproc.jcl")

    def test_without_the_extra_every_tool_names_the_install(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "jclparser", None)
        tools = tools_for(root)
        for call in (
            lambda: tools.jcl_job("FEEJOB.jcl"),
            lambda: tools.jobs_running("READER"),
            lambda: tools.dataset_users("PROD.ACCT.MASTER"),
        ):
            with pytest.raises(ToolError) as raised:
                call()
            assert str(raised.value) == INSTALL_HINT


def test_tools_answer_over_an_mcp_session(root: Path) -> None:
    pytest.importorskip("mcp")
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    from cobolparser.mcp.server import build_server

    server = build_server(Workspace(root, ProjectConfig()))

    async def run() -> list:
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as client:
            return [
                await client.call_tool("jcl_job", {"file": "FEEJOB.jcl"}),
                await client.call_tool("jobs_running", {"program": "WRITER"}),
                await client.call_tool("dataset_users", {"dataset": "&&FEES"}),
            ]

    job, running, users = asyncio.run(run())
    assert job.structuredContent["answer"]["jobs"][0]["name"] == "FEEJOB"
    assert running.structuredContent["answer"]["step_count"] == 1
    assert users.structuredContent["answer"]["by_access"] == {
        "create": ["WRITER"],
        # SORTIN: what SORT does with it, not what DISP=OLD says.
        "read": ["SORT"],
    }


class TestAccessFromTheProgram:
    """dataset_users says what a step does with a dataset from the program's
    OPEN mode or the utility's control statements, not only from DISP."""

    @pytest.fixture
    def shop(self, tmp_path: Path) -> Path:
        (tmp_path / "LOADER.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. LOADER.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT IN-FILE ASSIGN TO INDD.\n"
            "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
            "           SELECT LOG-FILE ASSIGN TO LOGDD.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD  IN-FILE.\n"
            "       01  IN-REC  PIC X(80).\n"
            "       FD  OUT-FILE.\n"
            "       01  OUT-REC PIC X(80).\n"
            "       FD  LOG-FILE.\n"
            "       01  LOG-REC PIC X(80).\n"
            "       PROCEDURE DIVISION.\n"
            "           OPEN INPUT IN-FILE OUTPUT OUT-FILE EXTEND LOG-FILE\n"
            "           READ IN-FILE\n"
            "           WRITE OUT-REC FROM IN-REC\n"
            "           WRITE LOG-REC FROM IN-REC\n"
            "           CLOSE IN-FILE OUT-FILE LOG-FILE\n"
            "           GOBACK.\n"
        )
        (tmp_path / "LOAD.jcl").write_text(
            "//LOAD     JOB (ACCT),'LOAD',CLASS=A\n"
            "//STEP1    EXEC PGM=LOADER\n"
            "//INDD     DD  DSN=PROD.IN,DISP=SHR\n"
            "//OUTDD    DD  DSN=PROD.MASTER,DISP=SHR\n"
            "//LOGDD    DD  DSN=PROD.LOG,DISP=OLD\n"
            "//STEP2    EXEC PGM=IDCAMS\n"
            "//SYSPRINT DD  SYSOUT=*\n"
            "//SRC      DD  DSN=PROD.MASTER,DISP=SHR\n"
            "//DST      DD  DSN=PROD.VSAM,DISP=OLD\n"
            "//SYSIN    DD  *\n"
            "  REPRO INFILE(SRC) OUTFILE(DST)\n"
            "/*\n"
            "//STEP3    EXEC PGM=UNKNOWN\n"
            "//X        DD  DSN=PROD.MASTER,DISP=SHR\n"
            "//STEP4    EXEC PGM=SORT\n"
            "//SORTIN   DD  DSN=PROD.MASTER,DISP=SHR\n"
            "//OUT1     DD  DSN=PROD.SPLIT.A,DISP=OLD\n"
            "//SYSIN    DD  *\n"
            "  SORT FIELDS=COPY\n"
            "  OUTFIL FNAMES=(OUT1)\n"
            "/*\n"
            "//STEP5    EXEC PGM=ICETOOL\n"
            "//TOOLMSG  DD  SYSOUT=*\n"
            "//DFSMSG   DD  SYSOUT=*\n"
            "//FROMDD   DD  DSN=PROD.MASTER,DISP=SHR\n"
            "//TODD     DD  DSN=PROD.COPY,DISP=OLD\n"
            "//TOOLIN   DD  *\n"
            "  COPY FROM(FROMDD) TO(TODD)\n"
            "/*\n"
        )
        return tmp_path

    def test_open_modes_and_utility_roles(self, shop: Path) -> None:
        tools = CobolTools(Workspace(shop, ProjectConfig()))
        rows = {
            (u["dataset"], u["step"]): u
            for u in tools.dataset_users("PROD.**")["answer"]["uses"]
        }
        master = rows[("PROD.MASTER", "STEP1")]
        assert (master["access"], master["access_from"]) == ("write", "program")
        assert master["disposition_access"] == "read"
        assert master["access_because"] == (
            "LOADER opens OUT-FILE OUTPUT (LOADER.cbl:18); DISP=SHR only says "
            "how the dataset is shared, not whether it is read or written"
        )
        assert "access_because" not in rows[("PROD.MASTER", "STEP2")]
        assert rows[("PROD.IN", "STEP1")]["access"] == "read"
        assert rows[("PROD.LOG", "STEP1")]["access"] == "extend"
        assert (
            rows[("PROD.MASTER", "STEP2")]["access"],
            rows[("PROD.MASTER", "STEP2")]["access_from"],
        ) == ("read", "utility")
        assert rows[("PROD.VSAM", "STEP2")]["access"] == "write"
        unknown = rows[("PROD.MASTER", "STEP3")]
        assert (unknown["access"], unknown["access_from"]) == ("read", "disp")
        assert "disposition_access" not in unknown
        assert rows[("PROD.SPLIT.A", "STEP4")]["access"] == "write"
        assert rows[("PROD.MASTER", "STEP4")]["access"] == "read"
        assert rows[("PROD.COPY", "STEP5")]["access"] == "write"
        assert rows[("PROD.MASTER", "STEP5")]["access"] == "read"
