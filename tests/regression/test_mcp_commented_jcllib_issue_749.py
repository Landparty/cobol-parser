"""#749: a commented-out ``//* JCLLIB`` card was used as a real one.

``_jcllib_names``' pattern ``^//\\S*`` also matched the ``//*`` of a comment
card, so the procedure library a job had commented out was searched first
and ``jobs_running`` reported a program the job does not run. A JCLLIB card
inside in-stream data (a job submitted through INTRDR) was counted as the
outer job's own too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("jclparser")

from cobolparser.mcp.tools import CobolTools  # noqa: E402
from cobolparser.mcp.tools.jcl_index import _jcllib_names  # noqa: E402
from cobolparser.mcp.workspace import Workspace  # noqa: E402


def _proc(program: str, dataset: str) -> str:
    return (
        "//RUNIT PROC\n"
        f"//S1 EXEC PGM={program}\n"
        f"//IN DD DSN={dataset},DISP=SHR\n"
        "// PEND\n"
    )


@pytest.fixture
def tools(tmp_path: Path) -> CobolTools:
    for library, program, dataset in [
        ("MY.PROCLIB", "PRODPGM", "PROD.IN"),
        ("TEST.PROCS", "TESTPGM", "TEST.IN"),
    ]:
        (tmp_path / library).mkdir()
        (tmp_path / library / "RUNIT").write_text(_proc(program, dataset))
    (tmp_path / "jcl").mkdir()
    (tmp_path / "jcl" / "JOBA.jcl").write_text(
        "//JOBA    JOB (ACCT),'A',CLASS=A\n"
        "//*       JCLLIB ORDER=(TEST.PROCS)\n"
        "//PROCS   JCLLIB ORDER=(MY.PROCLIB)\n"
        "//STEP1   EXEC RUNIT\n"
    )
    return CobolTools(Workspace(str(tmp_path)))


def test_jobs_running_uses_the_live_jcllib(tools: CobolTools) -> None:
    prod = tools.jobs_running("PRODPGM")["answer"]["steps"]
    assert [(s["job"], s["name"]) for s in prod] == [("JOBA", "STEP1.S1")]
    assert prod[0]["location"]["file"] == "MY.PROCLIB/RUNIT"
    assert tools.jobs_running("TESTPGM")["answer"]["steps"] == []


def test_dataset_users_follows_the_live_jcllib(tools: CobolTools) -> None:
    assert tools.dataset_users("PROD.IN")["answer"]["jobs"] == ["JOBA"]
    assert tools.dataset_users("TEST.IN")["answer"]["use_count"] == 0


def test_comment_card_is_not_a_jcllib() -> None:
    text = (
        "//JOBA JOB\n"
        "//*       JCLLIB ORDER=(TEST.PROCS)\n"
        "//PROCS   JCLLIB ORDER=(MY.PROCLIB)\n"
    )
    assert _jcllib_names(text) == ["MY.PROCLIB"]


def test_in_stream_job_jcllib_is_not_the_outer_jobs() -> None:
    text = (
        "//OUTER JOB\n"
        "//SUBMIT EXEC PGM=IEBGENER\n"
        "//SYSUT1 DD DATA,DLM=@@\n"
        "//INNER JOB\n"
        "//LIB   JCLLIB ORDER=(INNER.PROCS)\n"
        "@@\n"
        "//SYSUT2 DD SYSOUT=(A,INTRDR)\n"
        "//LIB   JCLLIB ORDER=(OUTER.PROCS)\n"
    )
    assert _jcllib_names(text) == ["OUTER.PROCS"]


def test_commented_out_dd_data_starts_no_in_stream_data() -> None:
    text = "//J JOB\n" "//*SYSUT1 DD DATA,DLM=@@\n" "//LIB JCLLIB ORDER=(A.PROCS)\n"
    assert _jcllib_names(text) == ["A.PROCS"]


def test_dd_star_data_ends_at_the_next_card() -> None:
    text = (
        "//J JOB\n"
        "//S EXEC PGM=X\n"
        "//SYSIN DD *\n"
        "  CONTROL CARD\n"
        "//LIB JCLLIB ORDER=(A.PROCS)\n"
        "//SYSIN2 DD *\n"
        "  JCLLIB ORDER=(B.PROCS)\n"
        "/*\n"
    )
    assert _jcllib_names(text) == ["A.PROCS"]
