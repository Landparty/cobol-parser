"""What the eighth benchmark round asked of the server: a SORT step's
positions said in field names, each job's run order with its conditions,
a utility's DD access in jcl_job, and COPY told from EXEC SQL INCLUDE."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.sort_layout import map_sort, parse_sort_control, read_back

#: TRAN-ID 1-8, TRAN-AMT 9-13, TRAN-CARD 14-21, FILLER 22-25.
FIELDS = [
    ("TRAN-ID", 0, 8),
    ("TRAN-AMT", 8, 5),
    ("TRAN-CARD", 13, 8),
    ("FILLER", 21, 4),
]


class TestSortControl:
    def test_keys_outrec_and_what_is_left_out(self) -> None:
        control = parse_sort_control(
            [
                "SORT FIELDS=(14,8,CH,A,",
                "             1,8,CH,D)",
                "OUTREC FIELDS=(1:14,8,9:1,13)",
            ]
        )
        answer = map_sort(control, FIELDS, 25)
        assert answer["sort_keys"] == [
            {
                "positions": "14-21",
                "fields": "TRAN-CARD",
                "format": "CH",
                "order": "ascending",
            },
            {
                "positions": "1-8",
                "fields": "TRAN-ID",
                "format": "CH",
                "order": "descending",
            },
        ]
        assert answer["outrec_layout"] == [
            {"positions": "1-8", "from": "14-21", "fields": "TRAN-CARD"},
            {"positions": "9-21", "from": "1-13", "fields": "TRAN-ID, TRAN-AMT"},
        ]
        assert answer["outrec_length"] == 21
        assert answer["input_not_copied"] == [
            {"positions": "22-25", "fields": "FILLER"}
        ]

    def test_a_partial_field_and_a_literal(self) -> None:
        control = parse_sort_control(["OUTREC FIELDS=(1,10,C'XY',3X)"])
        answer = map_sort(control, FIELDS, 25)
        first, literal, spaces = answer["outrec_layout"]
        assert first["fields"] == "TRAN-ID, part of TRAN-AMT (its bytes 1-2 of 5)"
        assert literal == {"positions": "11-12", "literal": "C'XY'"}
        assert spaces == {"positions": "13-15", "literal": "3X"}

    def test_include_and_sort_keys_through_inrec(self) -> None:
        control = parse_sort_control(
            [
                "INCLUDE COND=(9,5,ZD,GT,+100)",
                "INREC FIELDS=(14,8,1,8)",
                "SORT FIELDS=(1,8,CH,A)",
            ]
        )
        answer = map_sort(control, FIELDS, 25)
        # INCLUDE runs before INREC: its positions are the input's.
        assert answer["record_tests"][0]["fields"] == "TRAN-AMT"
        assert answer["sort_keys"][0]["fields"] == "input 14-21: TRAN-CARD"
        assert answer["sort_keys_note"]

    def test_an_edit_mask_is_not_guessed(self) -> None:
        control = parse_sort_control(["OUTREC FIELDS=(1,8,9,5,ZD,EDIT=(TTT.TT))"])
        answer = map_sort(control, FIELDS, 25)
        assert "outrec_layout" not in answer
        assert answer["not_mapped"]

    def test_the_layout_the_output_is_read_through(self) -> None:
        control = parse_sort_control(["OUTREC FIELDS=(1:14,8,9:1,13)"])
        rows = read_back(control, FIELDS, [("OUT-KEY", 0, 8), ("OUT-REST", 8, 17)])
        assert rows == [
            {"field": "OUT-KEY", "positions": "1-8", "gets": "TRAN-CARD"},
            {
                "field": "OUT-REST",
                "positions": "9-25",
                "gets": "TRAN-ID, TRAN-AMT; bytes 22-25 past the output's end",
            },
        ]


TRANREC = """\
       01  TRAN-RECORD.
           05  TRAN-ID            PIC X(8).
           05  TRAN-AMT           PIC 9(5).
           05  TRAN-CARD          PIC X(8).
           05  FILLER             PIC X(4).
"""

#: Reads the transaction file INTO the copybook's record.
TRANRPT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANRPT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRAN-FILE ASSIGN TO TRANIN.
       DATA DIVISION.
       FILE SECTION.
       FD  TRAN-FILE.
       01  FD-TRAN-REC            PIC X(25).
       WORKING-STORAGE SECTION.
       COPY TRANREC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TRAN-FILE
           READ TRAN-FILE INTO TRAN-RECORD
           CLOSE TRAN-FILE
           GOBACK.
"""

#: Reads the sorted, reloaded file through its own FD.
CARDRPT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CARDRPT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CARD-FILE ASSIGN TO CARDIN.
       DATA DIVISION.
       FILE SECTION.
       FD  CARD-FILE.
       01  FD-CARD-REC.
           05  FD-CARD-KEY        PIC X(8).
           05  FD-CARD-REST       PIC X(17).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CARD-FILE
           READ CARD-FILE
           CLOSE CARD-FILE
           GOBACK.
"""

DAILY = """\
//DAILY    JOB (ACCT),'BANK',CLASS=A
//REPORT   EXEC PGM=TRANRPT
//TRANIN   DD DSN=BANK.TRAN.MASTER,DISP=SHR
"""

SORTJOB = """\
//SORTJOB  JOB (ACCT),'BANK',CLASS=A
//SORTIT   EXEC PGM=SORT
//SORTIN   DD DSN=BANK.TRAN.MASTER,DISP=SHR
//SORTOUT  DD DSN=BANK.TRAN.SORTED,DISP=(NEW,CATLG,DELETE)
//SYSIN    DD *
  SORT FIELDS=(14,8,CH,A)
  OUTREC FIELDS=(1:14,8,9:1,13)
/*
//LOAD     EXEC PGM=IDCAMS,COND=(0,NE)
//SYSPRINT DD SYSOUT=*
//INFILE   DD DSN=BANK.TRAN.SORTED,DISP=SHR
//OUTFILE  DD DSN=BANK.CARD.KSDS,DISP=SHR
//SYSIN    DD *
  REPRO INFILE(INFILE) OUTFILE(OUTFILE)
/*
//CLEAN    EXEC PGM=IEFBR14,COND=(4,LT)
//OLDRPT   DD DSN=BANK.CARD.REPORT,DISP=(MOD,DELETE,DELETE)
//CARDS    EXEC PGM=CARDRPT
//CARDIN   DD DSN=BANK.CARD.KSDS,DISP=SHR
"""


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    pytest.importorskip("jclparser")
    root = tmp_path / "shop"
    write(root, "cpy/TRANREC.cpy", TRANREC)
    write(root, "cbl/TRANRPT.cbl", TRANRPT)
    write(root, "cbl/CARDRPT.cbl", CARDRPT)
    write(root, "jcl/DAILY.jcl", DAILY)
    write(root, "jcl/SORTJOB.jcl", SORTJOB)
    return root


def tools_for(root: Path) -> CobolTools:
    config = ProjectConfig(copybook_path=(str(root / "cpy"),))
    return CobolTools(Workspace(root, config))


class TestJclJobSortLayout:
    def test_a_sort_step_in_field_names(self, shop: Path) -> None:
        (job,) = tools_for(shop).jcl_job("jcl/SORTJOB.jcl")["answer"]["jobs"]
        laid = job["steps"][0]["sort_layout"]
        assert laid["input"] == "BANK.TRAN.MASTER"
        assert laid["input_layout"]["record"] == "TRAN-RECORD"
        assert laid["input_layout"]["how"].startswith(
            "READ TRAN-FILE INTO TRAN-RECORD in TRANRPT"
        )
        assert laid["sort_keys"][0]["fields"] == "TRAN-CARD"
        assert [r["fields"] for r in laid["outrec_layout"]] == [
            "TRAN-CARD",
            "TRAN-ID, TRAN-AMT",
        ]
        assert laid["input_not_copied"] == [{"positions": "22-25", "fields": "FILLER"}]
        # The sorted file is REPROed into the KSDS CARDRPT reads.
        read_as = laid["output_read_as"]
        assert (read_as["dataset"], read_as["record"]) == (
            "BANK.CARD.KSDS",
            "FD-CARD-REC",
        )
        assert read_as["fields"][0] == {
            "field": "FD-CARD-KEY",
            "positions": "1-8",
            "gets": "TRAN-CARD",
        }

    def test_run_order_and_utility_access(self, shop: Path) -> None:
        (job,) = tools_for(shop).jcl_job("jcl/SORTJOB.jcl")["answer"]["jobs"]
        assert job["run_order"] == (
            "SORTIT (SORT) -> LOAD (IDCAMS, runs only if every earlier step's "
            "return code is 0) -> CLEAN (IEFBR14, runs only if every earlier "
            "step's return code is at most 4) -> CARDS (CARDRPT)"
        )
        load, clean = job["steps"][1], job["steps"][2]
        outfile = next(d for d in load["dds"] if d["ddname"] == "OUTFILE")
        assert (outfile["access"], outfile["access_from"]) == ("write", "utility")
        (oldrpt,) = clean["dds"]
        assert oldrpt["access"] == "delete"

    def test_the_job_flow_of_a_program_has_it_too(self, shop: Path) -> None:
        answer = tools_for(shop).jobs_running("CARDRPT")["answer"]
        (flow,) = answer["jobs"]
        assert flow["steps"][0]["sort_layout"]["sort_keys"][0]["fields"] == "TRAN-CARD"
        assert "OLDRPT=BANK.CARD.REPORT (delete)" in flow["steps"][2]["writes"]

    def test_a_utility_query_still_parses_no_program(self, shop: Path) -> None:
        answer = tools_for(shop).jobs_running("SORT")["answer"]
        assert "sort_layout" not in answer["jobs"][0]["steps"][0]

    def test_no_reader_no_layout(self, shop: Path) -> None:
        (shop / "jcl/DAILY.jcl").unlink()
        (job,) = tools_for(shop).jcl_job("jcl/SORTJOB.jcl")["answer"]["jobs"]
        laid = job["steps"][0]["sort_layout"]
        assert "sort_keys" not in laid and laid["note"]


DB2PROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
             INCLUDE TRANREC
           END-EXEC.
       PROCEDURE DIVISION.
           GOBACK.
"""


class TestIncludeStatement:
    def test_copy_told_from_exec_sql_include(self, shop: Path) -> None:
        write(shop, "cbl/DB2PROG.cbl", DB2PROG)
        answer = tools_for(shop).impact_of_change("TRANREC")["answer"]
        kinds = {
            row["program"]: [s.get("statement") for s in row["copy_sites"]]
            for row in answer["copied_by"]
        }
        assert kinds == {"DB2PROG": ["EXEC SQL INCLUDE"], "TRANRPT": ["COPY"]}
        assert answer["brought_in_by"] == {
            "EXEC SQL INCLUDE": {"count": 1, "programs": ["DB2PROG"]},
            "COPY": {"count": 1, "programs": ["TRANRPT"]},
        }

    def test_one_kind_needs_no_summary(self, shop: Path) -> None:
        answer = tools_for(shop).impact_of_change("TRANREC")["answer"]
        assert "brought_in_by" not in answer
