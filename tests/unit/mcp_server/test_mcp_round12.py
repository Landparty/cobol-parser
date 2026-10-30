"""What benchmark rounds 12 to 14 asked of the server: a recompile answer
that names the programs next door that need no recompile, and every file
of the member to edit; a job flow that says how many steps run, in what
order and under what condition; and writers and readers counted, for a
field and for a dataset."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace


def program(name: str, copy: str = "") -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {name}.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        *([f"       COPY {copy}."] if copy else []),
        "       PROCEDURE DIVISION.",
        "           GOBACK.",
    ]
    return "\n".join(lines) + "\n"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestNotAffected:
    def test_the_neighbours_that_do_not_copy_it_are_named(self, tmp_path: Path) -> None:
        write(tmp_path, "cpy/AREA.cpy", "       01  AREA-REC PIC X(10).\n")
        write(tmp_path, "app/USER.cbl", program("USER", "AREA"))
        write(tmp_path, "app/OTHER.cbl", program("OTHER"))
        write(tmp_path, "far/AWAY.cbl", program("AWAY"))
        tools = CobolTools(
            Workspace(tmp_path, ProjectConfig(copybook_path=(str(tmp_path / "cpy"),)))
        )
        answer = tools.impact_of_change("AREA")["answer"]
        assert [r["program"] for r in answer["copied_by"]] == ["USER"]
        assert answer["not_affected"]["programs"] == ["OTHER"]
        assert answer["not_affected"]["count"] == 1
        assert answer["not_affected"]["folders"] == ["app"]

    def test_absent_when_every_neighbour_copies_it(self, tmp_path: Path) -> None:
        write(tmp_path, "cpy/AREA.cpy", "       01  AREA-REC PIC X(10).\n")
        write(tmp_path, "app/USER.cbl", program("USER", "AREA"))
        tools = CobolTools(
            Workspace(tmp_path, ProjectConfig(copybook_path=(str(tmp_path / "cpy"),)))
        )
        assert "not_affected" not in tools.impact_of_change("AREA")["answer"]


JOB = """\
//NIGHTLY  JOB (A),'X'
//FIRST    EXEC PGM=IEFBR14
//SECOND   EXEC PGM=REPORT,COND=(0,NE)
"""


class TestJobFlowRunOrder:
    def test_the_flow_counts_and_orders_its_steps(self, tmp_path: Path) -> None:
        pytest.importorskip("jclparser")
        write(tmp_path, "cbl/REPORT.cbl", program("REPORT"))
        write(tmp_path, "jcl/NIGHTLY.jcl", JOB)
        tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
        (flow,) = tools.jobs_running("REPORT")["answer"]["jobs"]
        assert flow["step_count"] == 2
        assert flow["run_order"] == (
            "FIRST (IEFBR14) -> SECOND (REPORT, runs only if every earlier "
            "step's return code is 0)"
        )


ACCOUNTS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  BAL      PIC 9(5).
       01  OUT      PIC 9(5).
       PROCEDURE DIVISION.
           {body}
           GOBACK.
"""


class TestProgramsByRole:
    def test_writers_and_readers_counted(self, tmp_path: Path) -> None:
        write(tmp_path, "POST.cbl", ACCOUNTS.format(name="POST", body="ADD 1 TO BAL"))
        write(
            tmp_path, "SHOW.cbl", ACCOUNTS.format(name="SHOW", body="MOVE BAL TO OUT")
        )
        tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
        roles = tools.find_statements(operand="BAL")["answer"]["programs_by_role"]
        assert roles["changed_by"] == {
            "count": 1,
            "programs": {"POST": ["ADD at POST.cbl:8"]},
        }
        assert roles["only_read_by"] == {"count": 1, "programs": ["SHOW"]}


LOAD = """\
//LOAD     JOB (A),'X'
//DEL      EXEC PGM=IDCAMS
//SYSIN    DD  *
  DELETE PROD.MASTER CLUSTER
/*
//COPY     EXEC PGM=IEBGENER
//SYSUT1   DD  DSN=PROD.IN,DISP=SHR
//SYSUT2   DD  DSN=PROD.MASTER,DISP=OLD
"""

REPORT = """\
//REPORT   JOB (A),'X'
//COPY     EXEC PGM=IEBGENER
//SYSUT1   DD  DSN=PROD.MASTER,DISP=SHR
//SYSUT2   DD  SYSOUT=*
"""


class TestJobsByEffect:
    def test_changing_and_reading_jobs_counted(self, tmp_path: Path) -> None:
        pytest.importorskip("jclparser")
        write(tmp_path, "LOAD.jcl", LOAD)
        write(tmp_path, "REPORT.jcl", REPORT)
        tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
        effect = tools.dataset_users("PROD.MASTER")["answer"]["jobs_by_effect"]
        assert effect == {
            "change_it": {
                "count": 1,
                "jobs": {"LOAD": ["COPY: write", "DEL: DELETE"]},
            },
            "only_read_it": {"count": 1, "jobs": ["REPORT"]},
        }


class TestMemberFilesToChange:
    def test_a_copybook_and_a_pli_include_of_one_member(self, tmp_path: Path) -> None:
        pytest.importorskip("pl1_parser")
        write(tmp_path, "cpy/PAYREC.cpy", "       01  PAYREC PIC X(10).\n")
        write(tmp_path, "include/PAYREC.inc", " DCL 1 PAYREC CHAR(10);\n")
        write(tmp_path, "cbl/PAYCBL.cbl", program("PAYCBL", "PAYREC"))
        write(
            tmp_path,
            "pli/PAYPLI.pli",
            " PAYPLI: PROC OPTIONS(MAIN);\n   %INCLUDE PAYREC;\n END PAYPLI;\n",
        )
        tools = CobolTools(
            Workspace(tmp_path, ProjectConfig(copybook_path=(str(tmp_path / "cpy"),)))
        )
        answer = tools.impact_of_change("PAYREC")["answer"]
        assert answer["member_files_to_change"]["files"] == [
            "cpy/PAYREC.cpy",
            "include/PAYREC.inc",
        ]
