"""What the seventh benchmark round asked of the server: the reason a
paragraph is unreachable, the COPY line that brings a CALL into a program,
a COND parameter in words, and IDCAMS commands counted as dataset uses."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

DEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEAD.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA
           GOBACK.
       ORPHAN-PARA.
           GO TO LOST-PARA.
       LOST-PARA.
           DISPLAY 'X'.
       WORK-PARA.
           DISPLAY 'W'.
       AFTER-WORK.
           DISPLAY 'A'.
"""

USER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY CALLIT.
           GOBACK.
"""


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    write(root, "cbl/DEAD.cbl", DEAD)
    write(root, "cbl/USER.cbl", USER)
    write(root, "cpy/CALLIT.cpy", "           CALL 'TARGET'.\n")
    return root


def tools_for(root: Path) -> CobolTools:
    config = ProjectConfig(copybook_path=(str(root / "cpy"),))
    return CobolTools(Workspace(root, config))


class TestUnreachableReasons:
    def test_each_dead_paragraph_says_why(self, shop: Path) -> None:
        answer = tools_for(shop).program_brief("cbl/DEAD.cbl")["answer"]
        reasons = {r["procedure"]: r for r in answer["unreachable_reasons"]}
        assert list(reasons) == ["ORPHAN-PARA", "LOST-PARA", "AFTER-WORK"]
        orphan = reasons["ORPHAN-PARA"]["reason"]
        assert "no PERFORM, GO TO or other statement names it" in orphan
        assert "MAIN-PARA, ends with GOBACK (cbl/DEAD.cbl:6)" in orphan
        lost = reasons["LOST-PARA"]["reason"]
        assert "named only from unreachable code: GOTO from ORPHAN-PARA" in lost
        assert "cbl/DEAD.cbl:8" in lost
        assert "ORPHAN-PARA, is unreachable too" in lost
        assert "WORK-PARA, is only PERFORMed" in reasons["AFTER-WORK"]["reason"]
        assert reasons["AFTER-WORK"]["location"]["line"] == 13

    def test_a_program_with_no_dead_code_has_no_reasons(self, shop: Path) -> None:
        answer = tools_for(shop).program_brief("cbl/USER.cbl")["answer"]
        assert "unreachable_reasons" not in answer


class TestCopiedAt:
    def test_a_call_in_a_copybook_names_the_copy_line(self, shop: Path) -> None:
        answer = tools_for(shop).callers_of(None, name="TARGET")["answer"]
        (caller,) = answer["callers"]
        assert caller["location"]["file"] == "cpy/CALLIT.cpy"
        assert caller["copied_at"] == {"file": "cbl/USER.cbl", "line": 5}


class TestExplainCondition:
    @pytest.mark.parametrize(
        ("condition", "words"),
        [
            ("(0,NE)", "runs only if every earlier step's return code is 0"),
            ("(4,LT,STEP1)", "runs only if step STEP1's return code is at most 4"),
            ("EVEN", "runs even after an earlier step abends"),
            ("ONLY", "runs only after an earlier step abends"),
        ],
    )
    def test_cond_in_words(self, condition: str, words: str) -> None:
        pytest.importorskip("jclparser")
        from cobolparser.mcp.jcl_tools import explain_condition

        assert words in (explain_condition(condition) or "")

    def test_both_parts_of_a_compound_cond(self) -> None:
        pytest.importorskip("jclparser")
        from cobolparser.mcp.jcl_tools import explain_condition

        words = explain_condition("((0,NE),EVEN)") or ""
        assert "every earlier step's return code is 0" in words
        assert "even after an earlier step abends" in words


IDCAMS_JOB = """\
//REORG    JOB (ACCT),'BANK',CLASS=A
//DROP     EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DELETE BANK.MASTER.KSDS CLUSTER PURGE
  DEFINE CLUSTER (NAME(BANK.MASTER.KSDS) INDEXED KEYS(8 0))
/*
//LOAD     EXEC PGM=IDCAMS,COND=(0,NE)
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  REPRO INDATASET(BANK.MASTER.SEQ) OUTDATASET(BANK.MASTER.KSDS)
/*
"""


class TestIdcamsCommands:
    @pytest.fixture
    def jobs(self, shop: Path) -> Path:
        pytest.importorskip("jclparser")
        write(shop, "jcl/REORG.jcl", IDCAMS_JOB)
        return shop

    def test_sysin_commands_are_dataset_uses(self, jobs: Path) -> None:
        answer = tools_for(jobs).dataset_users("BANK.MASTER.KSDS")["answer"]
        uses = [(u["step"], u["command"], u["access"]) for u in answer["uses"]]
        assert uses == [
            ("DROP", "DELETE", "delete"),
            ("DROP", "DEFINE", "define"),
            ("LOAD", "REPRO/BLDINDEX OUTDATASET", "write"),
        ]
        assert {u["access_from"] for u in answer["uses"]} == {"idcams command"}
        assert answer["uses"][2]["location"] == {"file": "jcl/REORG.jcl", "line": 8}

    def test_the_job_flow_shows_them_and_explains_cond(self, jobs: Path) -> None:
        answer = tools_for(jobs).jobs_running("IDCAMS")["answer"]
        (flow,) = answer["jobs"]
        drop, load = flow["steps"]
        assert any(w.startswith("DELETE BANK.MASTER.KSDS") for w in drop["writes"])
        assert any("BANK.MASTER.SEQ" in r for r in load["reads"])
        assert "every earlier step's return code is 0" in load["condition_means"]
