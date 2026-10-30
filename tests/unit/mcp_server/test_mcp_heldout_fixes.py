"""What the first held-out benchmark round found missing: how a second
declaration of a PROGRAM-ID differs from this one; control-flow facts a
reader would otherwise reconstruct by hand (no GOBACK, fall-through,
files never OPENed or CLOSEd); DB2 tables read and changed through EXEC
SQL and through DSNTEP4 / DSNTIAD / DSNTIAUL steps; and link-edit decks
that bind one program into another's load module."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.jcl_tools import _sql_statements, _sql_tables
from cobolparser.mcp.link_decks import parse_deck
from cobolparser.mcp.tools import compare_sources


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def tools_for(root: Path) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig()))


FALLS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLS.
      * one
      * two
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT OUT-FILE ASSIGN TO OUTFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC PIC X(10).
       PROCEDURE DIVISION.
       A-OPEN.
           OPEN INPUT IN-FILE.
       B-READ.
           READ IN-FILE.
       C-END.
           DISPLAY 'DONE'.
"""


class TestControlFlowNotes:
    def test_falling_off_the_end_and_through_every_paragraph(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, "FALLS.cbl", FALLS)
        notes = tools_for(tmp_path).program_brief("FALLS.cbl")["answer"][
            "control_flow_notes"
        ]
        assert notes == [
            "no GOBACK, STOP RUN, EXIT PROGRAM or EXEC CICS RETURN: control "
            "falls off the end of the last procedure, C-END",
            "nothing is PERFORMed or GONE TO: the paragraphs run once each, "
            "in order, by falling through: A-OPEN -> B-READ -> C-END",
            "declared but never OPENed: OUT-FILE",
            "OPENed but never CLOSEd: IN-FILE",
        ]

    def test_absent_for_a_program_that_performs_and_ends(self, tmp_path: Path) -> None:
        text = (
            FALLS.replace(
                "       A-OPEN.\n", "       A-OPEN.\n           PERFORM B-READ.\n"
            )
            .replace("DISPLAY 'DONE'.", "CLOSE IN-FILE.\n           GOBACK.")
            .replace("OPEN INPUT IN-FILE.", "OPEN INPUT IN-FILE OUTPUT OUT-FILE.")
            .replace("CLOSE IN-FILE.", "CLOSE IN-FILE OUT-FILE.")
        )
        write(tmp_path, "FALLS.cbl", text)
        answer = tools_for(tmp_path).program_brief("FALLS.cbl")["answer"]
        assert "control_flow_notes" not in answer

    def test_a_sort_work_file_is_never_said_unopened(self, tmp_path: Path) -> None:
        text = FALLS.replace("       FD  OUT-FILE.", "       SD  OUT-FILE.")
        write(tmp_path, "FALLS.cbl", text)
        notes = tools_for(tmp_path).program_brief("FALLS.cbl")["answer"][
            "control_flow_notes"
        ]
        assert not any("never OPENed" in n for n in notes)


class TestAlsoDeclared:
    def test_a_twin_that_differs_only_in_comments(self, tmp_path: Path) -> None:
        write(tmp_path, "a/FALLS.cbl", FALLS)
        write(tmp_path, "b/COPYOF.cbl", FALLS.replace("* two", "* 2026"))
        answer = tools_for(tmp_path).program_brief("a/FALLS.cbl")["answer"]
        (twin,) = answer["also_declared_in"]
        assert twin["file"] == "b/COPYOF.cbl"
        assert twin["comments_only"] is True
        assert twin["comparison"] == "only comment lines differ: 1 line(s), at 4"

    def test_identical_and_code_differences(self) -> None:
        assert compare_sources(FALLS, FALLS) == {
            "identical": True,
            "comparison": "identical, line for line",
        }
        changed = compare_sources(FALLS, FALLS.replace("'DONE'", "'OVER'"))
        assert changed["identical"] is False
        assert changed["comments_only"] is False
        assert changed["differing_lines"] == [22]


SQL_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT CODE FROM APP.TYPES
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           {sql}
           GOBACK.
"""


class TestTableUsers:
    def test_programs_that_change_and_only_read_a_table(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "cbl/WRITER.cbl",
            SQL_PROGRAM.format(
                name="WRITER",
                sql="EXEC SQL DELETE FROM APP.TYPES WHERE CODE = 1 END-EXEC.",
            ),
        )
        write(
            tmp_path,
            "cbl/READER.cbl",
            SQL_PROGRAM.format(name="READER", sql="EXEC SQL OPEN C1 END-EXEC."),
        )
        tools = tools_for(tmp_path)
        found = tools.find_statements(operand="APP.TYPES")["answer"]
        assert found["programs_by_role"]["changed_by"]["programs"] == {
            "WRITER": ["EXEC SQL DELETE at cbl/WRITER.cbl:10"]
        }
        assert found["programs_by_role"]["only_read_by"]["programs"] == ["READER"]
        # The unqualified name finds the same statements.
        assert tools.find_statements(operand="TYPES")["answer"]["match_count"] == 2
        sql = tools.dataset_users("TYPES")["answer"]["sql_programs"]
        assert sql["change_it"]["programs"] == {
            "WRITER": ["DELETE in MAIN-PARA at cbl/WRITER.cbl:10"]
        }
        assert sql["only_read_it"]["programs"] == {
            "READER": ["OPEN cursor C1 in MAIN-PARA at cbl/READER.cbl:10"]
        }


LOAD_JOB = """\
//LOADJOB  JOB (A),'X'
//CREATE   EXEC PGM=IKJEFT01
//SYSTSIN  DD DSN=APP.CNTL(TIAD),DISP=SHR
//SYSIN    DD DSN=APP.CNTL(DDL),DISP=SHR
//UNLOAD   EXEC PGM=IKJEFT01
//SYSREC00 DD DSN=APP.TYPES.UNLOAD,DISP=(NEW,CATLG)
//SYSIN    DD *
  SELECT CODE, 'A;B' FROM APP.TYPES -- every row
   ORDER BY CODE;
/*
//SYSTSIN  DD *
  DSN SYSTEM(DB2P)
  RUN PROGRAM(DSNTIAUL) PLAN(DSNTIAUL) PARMS('SQL')
/*
"""


class TestDb2UtilitySteps:
    def test_dsntiad_ddl_and_a_dsntiaul_unload(self, tmp_path: Path) -> None:
        pytest.importorskip("jclparser")
        write(tmp_path, "jcl/LOADJOB.jcl", LOAD_JOB)
        write(tmp_path, "ctl/TIAD.ctl", "  DSN SYSTEM(DB2P)\n  RUN PROGRAM(DSNTIAD)\n")
        write(
            tmp_path,
            "ctl/DDL.ctl",
            "/* the table */\n"
            "  CREATE TABLE APP.TYPES (CODE CHAR(2) NOT NULL);\n"
            "  INSERT INTO APP.TYPES VALUES ('01');\n",
        )
        answer = tools_for(tmp_path).dataset_users("APP.TYPES")["answer"]
        assert answer["jobs_by_effect"]["change_it"]["jobs"] == {
            "LOADJOB": [
                "CREATE: DSNTIAD CREATE TABLE",
                "CREATE: DSNTIAD INSERT",
                "UNLOAD: DSNTIAUL SELECT (read) to APP.TYPES.UNLOAD",
            ]
        }
        (unload,) = [u for u in answer["uses"] if u["step"] == "UNLOAD"]
        assert unload["access"] == "read"
        assert unload["copied_to"] == ["APP.TYPES.UNLOAD"]
        assert unload["sql"] == "SELECT CODE, 'A;B' FROM APP.TYPES ORDER BY CODE"
        (create,) = [u for u in answer["uses"] if u["access"] == "create table"]
        assert create["sql_location"] == {"file": "ctl/DDL.ctl", "line": 2}
        assert create["runs_as"] == (
            "IKJEFT01 RUN PROGRAM(DSNTIAD) (SYSTSIN member TIAD)"
        )

    def test_sql_statement_tables(self) -> None:
        cards = [(1, "INSERT INTO A.T SELECT X FROM B.S JOIN C.U ON 1=1;")]
        ((line, _, blanked),) = _sql_statements(cards)
        assert line == 1
        assert _sql_tables(blanked) == [
            ("A.T", "insert"),
            ("B.S", "read"),
            ("C.U", "read"),
        ]
        assert _sql_tables("CREATE UNIQUE INDEX A.X ON A.T (C)") == [
            ("A.T", "create index")
        ]
        assert _sql_tables("DELETE FROM A.T WHERE 1=1") == [("A.T", "delete")]


DECK = """\
 INCLUDE  SYSLMOD(SUBPGM)
 INCLUDE SYSLIB(MAINPGM,HELPER)
 ENTRY MAINPGM
 NAME MAINPGM(R)
"""


class TestLinkDecks:
    def test_parse_deck(self) -> None:
        deck = parse_deck(DECK, "link/main.lnk")
        assert deck.load_module == "MAINPGM"
        assert deck.entry == "MAINPGM"
        assert [i["member"] for i in deck.includes] == ["SUBPGM", "MAINPGM", "HELPER"]

    def test_callers_and_brief_name_the_binding(self, tmp_path: Path) -> None:
        sub = SQL_PROGRAM.format(name="SUBPGM", sql="CONTINUE.")
        main = SQL_PROGRAM.format(name="MAINPGM", sql="CONTINUE.")
        write(tmp_path, "cbl/SUBPGM.cbl", sub)
        write(tmp_path, "cbl/MAINPGM.cbl", main)
        write(tmp_path, "link/main.lnk", DECK)
        tools = tools_for(tmp_path)
        callers = tools.callers_of(None, "SUBPGM")["answer"]
        assert callers["link_edited_into"] == [
            {"load_module": "MAINPGM", "deck": "link/main.lnk", "line": 1}
        ]
        assert "link-edit deck binds it into MAINPGM" in callers["note"]
        brief = tools.program_brief("cbl/MAINPGM.cbl")["answer"]
        assert brief["link_edit"] == [
            {
                "deck": "link/main.lnk",
                "load_module": "MAINPGM",
                "entry": "MAINPGM",
                "includes": [
                    "SUBPGM (from SYSLMOD) at line 1",
                    "MAINPGM (from SYSLIB) at line 2",
                    "HELPER (from SYSLIB) at line 2",
                ],
            }
        ]
