"""What the sixth benchmark round asked of the server: an overview scoped to
the application a question names, a transaction's whole footprint in one
brief, and a job laid out step by step so its data can be traced without
reading the JCL."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.mcp import CobolTools, Workspace


def cobol(program: str, body: str = "", data: str = "", env: str = "") -> str:
    """A small fixed-format COBOL program."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {program}.",
        *(["       ENVIRONMENT DIVISION."] if env else []),
        *[f"       {line}" for line in env.splitlines() if line],
        "       DATA DIVISION.",
        *[f"       {line}" for line in data.splitlines() if line],
        "       WORKING-STORAGE SECTION.",
        "       01  WS-AMT               PIC 9(5).",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *[f"           {line}" for line in body.splitlines() if line],
        "           GOBACK.",
    ]
    return "\n".join(lines) + "\n"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


WRITER_ENV = """\
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT OUT-FILE ASSIGN TO OUTDD.
"""
WRITER_DATA = """\
FILE SECTION.
FD  OUT-FILE.
01  OUT-REC                PIC X(80).
"""

#: Four statements, repeated in every program: a clone group.
CLONE = """\
MOVE 1 TO WS-AMT
ADD 2 TO WS-AMT
MULTIPLY 3 BY WS-AMT
DISPLAY WS-AMT
"""


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    # bank: ADDPOL CALLs ADDDB (which writes a file and a table, then
    # CALLs AUDIT); ADDPOL CALLs AUDIT too.
    write(
        root,
        "bank/cbl/ADDPOL.cbl",
        cobol("ADDPOL", "CALL 'ADDDB' USING WS-AMT\nCALL 'AUDIT' USING WS-AMT"),
    )
    write(
        root,
        "bank/cbl/ADDDB.cbl",
        cobol(
            "ADDDB",
            "OPEN OUTPUT OUT-FILE\n"
            "WRITE OUT-REC\n"
            "CLOSE OUT-FILE\n"
            "EXEC SQL INSERT INTO POLICY (ID) VALUES (1) END-EXEC\n"
            "CALL 'AUDIT' USING WS-AMT",
            WRITER_DATA,
            WRITER_ENV,
        ),
    )
    write(root, "bank/cbl/AUDIT.cbl", cobol("AUDIT", "CALL 'VENDLOG'"))
    # cards: another application, with its own missing callee.
    write(root, "cards/cbl/CARDUPD.cbl", cobol("CARDUPD", "CALL 'CARDEXT'"))
    for name in ("CLONEA", "CLONEB", "CLONEC", "CLONED"):
        write(root, f"cards/cbl/{name}.cbl", cobol(name, CLONE))
    return root


def tools_for(root: Path) -> CobolTools:
    return CobolTools(Workspace(root))


class TestScopedOverview:
    def test_a_path_scopes_every_section(self, shop: Path) -> None:
        result = tools_for(shop).codebase_overview(path="bank")
        answer = result["answer"]
        assert {p["program"] for p in answer["programs"]} == {
            "ADDPOL",
            "ADDDB",
            "AUDIT",
        }
        assert answer["scope"]
        graph = answer["call_graph"]
        # VENDLOG is missing from bank; CARDEXT belongs to cards.
        assert [e["program"] for e in graph["not_in_workspace"]] == ["VENDLOG"]
        assert graph["entry_programs"] == ["ADDPOL"]
        assert {p["file"] for p in answer["health"]["worst"]} <= {
            "bank/cbl/ADDPOL.cbl",
            "bank/cbl/ADDDB.cbl",
            "bank/cbl/AUDIT.cbl",
        }
        assert sum(answer["health"]["grades"].values()) == 3
        # The clones are all in cards.
        assert answer["duplicated_code"]["groups"] == []

    def test_the_whole_root_is_unchanged_without_a_filter(self, shop: Path) -> None:
        answer = tools_for(shop).codebase_overview()["answer"]
        assert "scope" not in answer
        external = {e["program"] for e in answer["call_graph"]["not_in_workspace"]}
        assert external == {"VENDLOG", "CARDEXT"}

    def test_clone_members_are_few_with_one_truncation_note(self, shop: Path) -> None:
        result = tools_for(shop).codebase_overview()
        (group,) = result["answer"]["duplicated_code"]["groups"]
        assert group["member_count"] == 4
        assert len(group["members"]) == 3
        cuts = [
            t for t in result["truncated"] if t["field"].startswith("duplicated_code")
        ]
        assert cuts == [
            {
                "field": "duplicated_code.groups[].members",
                "shown": 3,
                "groups_cut": 1,
                "note": cuts[0]["note"],
            }
        ]

    def test_a_path_glob_keeps_the_members_it_matches(self, shop: Path) -> None:
        answer = tools_for(shop).codebase_overview(path="cards/cbl/CLONE[AB]*")[
            "answer"
        ]
        (group,) = answer["duplicated_code"]["groups"]
        assert group["member_count"] == 4
        assert {m["program"] for m in group["members"]} == {"CLONEA", "CLONEB"}


class TestBriefFollowCalls:
    def test_every_program_run_with_what_it_touches(self, shop: Path) -> None:
        answer = tools_for(shop).program_brief(
            "bank/cbl/ADDPOL.cbl", follow_calls=True
        )["answer"]
        tree = {row["program"]: row for row in answer["call_tree"]}
        assert list(tree) == ["ADDDB", "AUDIT", "VENDLOG"]
        adddb = tree["ADDDB"]
        assert adddb["depth"] == 1
        assert adddb["at"] == "bank/cbl/ADDPOL.cbl:8"
        assert adddb["files"] == [{"name": "OUT-FILE", "access": "C---"}]
        assert adddb["sql_tables"] == [{"name": "POLICY", "access": "C---"}]
        assert tree["AUDIT"]["also_called_by"] == ["ADDDB"]
        assert tree["VENDLOG"]["in_workspace"] is False
        assert answer["access_legend"]

    def test_without_follow_calls_there_is_no_tree(self, shop: Path) -> None:
        answer = tools_for(shop).program_brief("bank/cbl/ADDPOL.cbl")["answer"]
        assert "call_tree" not in answer


@pytest.fixture
def jobs(shop: Path) -> Path:
    pytest.importorskip("jclparser")
    write(
        shop,
        "bank/jcl/REPORT.jcl",
        "//REPORT   JOB (ACCT),'BANK',CLASS=A\n"
        "//UNLOAD   EXEC PGM=IDCAMS\n"
        "//FILEIN   DD DSN=BANK.MASTER.KSDS,DISP=SHR\n"
        "//FILEOUT  DD DSN=BANK.MASTER.BKUP(+1),DISP=(NEW,CATLG,DELETE)\n"
        "//SYSIN    DD DSN=BANK.CNTL(REPRO1),DISP=SHR\n"
        "//SORTIT   EXEC PGM=SORT\n"
        "//SORTIN   DD DSN=BANK.MASTER.BKUP(+1),DISP=SHR\n"
        "//SORTOUT  DD DSN=BANK.DAILY,DISP=(NEW,CATLG,DELETE)\n"
        "//SYSOUT   DD SYSOUT=*\n"
        "//SYSIN    DD *\n"
        " SORT FIELDS=(1,8,CH,A)\n"
        " INCLUDE COND=(9,2,CH,EQ,C'AA')\n"
        "/*\n"
        "//PRINT    EXEC PGM=ADDDB,COND=(0,NE)\n"
        "//STEPLIB  DD DSN=BANK.LOADLIB,DISP=SHR\n"
        "//OUTDD    DD DSN=BANK.DAILY,DISP=SHR\n",
    )
    write(
        shop,
        "bank/ctl/REPRO1.ctl",
        "/* unload the master */\n    REPRO INFILE(FILEIN) OUTFILE(FILEOUT)\n",
    )
    write(shop, "cards/ctl/REPRO1.ctl", "    REPRO INFILE(OTHER) OUTFILE(OTHER)\n")
    return shop


class TestJobFlow:
    def test_the_job_step_by_step(self, jobs: Path) -> None:
        answer = tools_for(jobs).jobs_running("ADDDB")["answer"]
        (flow,) = answer["jobs"]
        assert (flow["file"], flow["job"]) == ("bank/jcl/REPORT.jcl", "REPORT")
        unload, sort, report = flow["steps"]
        assert unload["program"] == "IDCAMS"
        assert unload["reads"] == ["FILEIN=BANK.MASTER.KSDS"]
        assert unload["writes"] == ["FILEOUT=BANK.MASTER.BKUP(+1) (create)"]
        # The SYSIN member, from the folder beside the job's own.
        assert unload["control"] == [
            {
                "dd": "SYSIN",
                "member": "BANK.CNTL(REPRO1)",
                "file": "bank/ctl/REPRO1.ctl",
                "lines": ["REPRO INFILE(FILEIN) OUTFILE(FILEOUT)"],
            }
        ]
        assert sort["fed_by"] == {"BANK.MASTER.BKUP(+1)": "UNLOAD"}
        assert sort["control"] == [
            {
                "dd": "SYSIN",
                "lines": ["SORT FIELDS=(1,8,CH,A)", "INCLUDE COND=(9,2,CH,EQ,C'AA')"],
            }
        ]
        assert "reads" not in report
        # The program opens OUTDD OUTPUT, though DISP says SHR.
        assert report["writes"] == ["OUTDD=BANK.DAILY (write)"]
        assert report["runs_the_program"] is True
        assert report["condition"]
        assert "STEPLIB" not in str(report)

    def test_a_program_read_feeds_back_to_its_writer(self, jobs: Path) -> None:
        write(
            jobs,
            "bank/jcl/REPORT.jcl",
            (jobs / "bank/jcl/REPORT.jcl")
            .read_text()
            .replace("//OUTDD    DD DSN=BANK.DAILY,DISP=SHR\n", "")
            + "//NEXT     EXEC PGM=AUDIT\n//INDD     DD DSN=BANK.DAILY,DISP=SHR\n",
        )
        answer = tools_for(jobs).jobs_running("AUDIT")["answer"]
        (flow,) = answer["jobs"]
        assert flow["steps"][-1]["fed_by"] == {"BANK.DAILY": "SORTIT"}
