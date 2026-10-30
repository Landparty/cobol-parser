"""What the tenth benchmark round asked of the server: whether a program
runs online or in batch, said with its evidence; how a CALL links (static,
dynamic, a PL/I FETCHABLE entry); and the programs whose only COPY of a
member is commented out."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace


def program(name: str, body: str, linkage: str = "") -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {name}.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  WS-PGM               PIC X(8).",
        *(["       LINKAGE SECTION.", f"       {linkage}"] if linkage else []),
        "       PROCEDURE DIVISION.",
        *[f"           {line}" for line in body.splitlines() if line],
        "           GOBACK.",
    ]
    return "\n".join(lines) + "\n"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    # SCREEN issues EXEC CICS and CALLs DATES through a data item; LOGIC has
    # no EXEC CICS but takes DFHCOMMAREA; REPORT is run by JCL and CALLs
    # DATES by literal; DATES is a subroutine of both.
    write(
        root,
        "cbl/SCREEN.cbl",
        program(
            "SCREEN",
            "MOVE 'DATES' TO WS-PGM\nCALL WS-PGM\nEXEC CICS RETURN END-EXEC",
        ),
    )
    write(
        root,
        "cbl/LOGIC.cbl",
        program("LOGIC", "CALL 'DATES'", "01  DFHCOMMAREA PIC X(100)."),
    )
    write(root, "cbl/REPORT.cbl", program("REPORT", "CALL 'DATES'"))
    write(root, "cbl/DATES.cbl", program("DATES", "CONTINUE"))
    write(root, "cbl/LONELY.cbl", program("LONELY", "CONTINUE"))
    return root


def tools_for(root: Path) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig()))


class TestCallType:
    def test_literal_and_dynamic_calls_say_how_they_link(self, shop: Path) -> None:
        answer = tools_for(shop).callers_of(None, name="DATES")["answer"]
        by = {c["program"]: c for c in answer["callers"]}
        assert by["SCREEN"]["call_type"].startswith("dynamic: CALL of a data item")
        assert by["LOGIC"]["call_type"].startswith("CALL literal: static, unless")


class TestRunsAs:
    def test_without_jcl(self, shop: Path) -> None:
        answer = tools_for(shop).callers_of(None, name="DATES")["answer"]
        by = {c["program"]: c.get("runs_as") for c in answer["callers"]}
        assert by == {
            "SCREEN": "online (CICS)",
            "LOGIC": "online (CICS)",
            "REPORT": None,
        }
        because = answer["runs_as_because"]
        assert because["SCREEN"] == "it issues EXEC CICS"
        assert "DFHCOMMAREA" in because["LOGIC"]
        assert "REPORT" not in because

    def test_a_jcl_step_makes_it_batch(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        write(
            shop,
            "jcl/NIGHTLY.jcl",
            "//NIGHTLY  JOB (A),'X'\n//RUN      EXEC PGM=REPORT\n",
        )
        tools = tools_for(shop)
        answer = tools.callers_of(None, name="DATES")["answer"]
        by = {c["program"]: c.get("runs_as") for c in answer["callers"]}
        assert by["REPORT"] == "batch"
        brief = tools.program_brief("cbl/DATES.cbl")["answer"]
        assert brief["runs_as"]["runs_as"] == "batch and online (CICS)"
        assert brief["runs_as"]["because"].startswith("a subroutine; its callers run")

    def test_nothing_says_so_nothing_is_said(self, shop: Path) -> None:
        brief = tools_for(shop).program_brief("cbl/LONELY.cbl")["answer"]
        assert "runs_as" not in brief

    def test_the_call_tree_is_labelled(self, shop: Path) -> None:
        brief = tools_for(shop).program_brief("cbl/SCREEN.cbl", follow_calls=True)[
            "answer"
        ]
        assert brief["runs_as"] == {
            "runs_as": "online (CICS)",
            "because": "it issues EXEC CICS",
        }
        (row,) = brief["call_tree"]
        assert row["program"] == "DATES" and row["runs_as"] == "online (CICS)"


PLI = """\
 SHOWDT: PROC OPTIONS(MAIN);
   DCL 1 DATES EXTERNAL ENTRY OPTIONS(FETCHABLE,COBOL);
   DCL LINKED EXTERNAL ENTRY;
   CALL DATES;
   CALL LINKED;
 END SHOWDT;
"""


class TestPliFetchable:
    def test_a_fetchable_entry_is_a_dynamic_call(self, shop: Path) -> None:
        pytest.importorskip("pl1_parser")
        write(shop, "pli/SHOWDT.pli", PLI)
        tools = tools_for(shop)
        (row,) = [
            c
            for c in tools.callers_of(None, name="DATES")["answer"]["callers"]
            if c.get("language") == "PL/I"
        ]
        assert "OPTIONS(FETCHABLE)" in row["call_type"]
        (linked,) = tools.callers_of(None, name="LINKED")["answer"]["callers"]
        assert linked["call_type"].startswith("static")


class TestCommentedOut:
    def test_a_commented_copy_is_named_and_not_counted(self, shop: Path) -> None:
        write(shop, "cpy/AREA.cpy", "       01  AREA-REC PIC X(10).\n")
        write(
            shop,
            "cbl/USER.cbl",
            program("USER", "CONTINUE").replace(
                "       PROCEDURE DIVISION.",
                "       COPY AREA.\n       PROCEDURE DIVISION.",
            ),
        )
        write(
            shop,
            "cbl/OLD.cbl",
            program("OLD", "CONTINUE").replace(
                "       PROCEDURE DIVISION.",
                "      *    COPY AREA.\n       PROCEDURE DIVISION.",
            ),
        )
        tools = CobolTools(
            Workspace(shop, ProjectConfig(copybook_path=(str(shop / "cpy"),)))
        )
        answer = tools.impact_of_change("AREA")["answer"]
        assert [r["program"] for r in answer["copied_by"]] == ["USER"]
        assert answer["commented_out"] == [
            {"file": "cbl/OLD.cbl", "line": 6, "text": "*    COPY AREA."}
        ]
        assert answer["commented_out_note"]
