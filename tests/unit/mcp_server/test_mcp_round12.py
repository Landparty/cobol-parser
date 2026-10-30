"""What the twelfth benchmark round asked of the server: a recompile answer
that names the programs next door that need no recompile, and a job flow
that says how many steps run, in what order and under what condition."""

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
