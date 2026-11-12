"""Issue #896: a step inside ``// IF`` that also codes ``COND=`` kept only
the COND in ``JobStep.condition``. ``if_condition`` and ``cond`` now keep
the two apart, and the MCP job tools show both."""

from __future__ import annotations

import pytest

pytest.importorskip("jclparser")

from cobolparser.jcl import parse_jcl  # noqa: E402
from cobolparser.mcp import CobolTools, Workspace  # noqa: E402

JCL = """\
//TJOB     JOB (ACCT),'T',CLASS=A
//S1       EXEC PGM=IEFBR14
//         IF (S1.RC = 4) THEN
//S2       EXEC PGM=IEFBR14,COND=(16,LT)
//         ELSE
//S2B      EXEC PGM=IEFBR14
//         ENDIF
//S3       EXEC PGM=IEFBR14,COND=(0,NE)
"""


def _steps():
    return {s.name: s for s in parse_jcl(JCL).jobs[0].steps}


def test_step_keeps_both_conditions():
    s2 = _steps()["S2"]
    assert s2.condition == "(16,LT)"  # unchanged, for existing readers
    assert s2.cond == "(16,LT)"
    assert s2.if_condition == "(S1.RC = 4)"
    assert s2.to_dict()["if_condition"] == "(S1.RC = 4)"
    assert s2.to_dict()["cond"] == "(16,LT)"


def test_if_only_cond_only_and_neither():
    steps = _steps()
    assert (steps["S2B"].condition, steps["S2B"].if_condition, steps["S2B"].cond) == (
        "NOT (S1.RC = 4)",
        "NOT (S1.RC = 4)",
        None,
    )
    assert (steps["S3"].if_condition, steps["S3"].cond) == (None, "(0,NE)")
    assert (steps["S1"].condition, steps["S1"].if_condition, steps["S1"].cond) == (
        None,
        None,
        None,
    )


def test_mcp_job_shows_the_if_beside_the_cond(tmp_path):
    (tmp_path / "T.jcl").write_text(JCL)
    job = CobolTools(Workspace(tmp_path)).jcl_job("T.jcl")["answer"]["jobs"][0]
    rows = {row["name"]: row for row in job["steps"]}
    assert rows["S2"]["condition"] == "(16,LT)"
    assert rows["S2"]["if_condition"] == "(S1.RC = 4)"
    assert "if_condition" not in rows["S2B"]
    assert "if_condition" not in rows["S3"]
    assert "S2 (IEFBR14, only if IF (S1.RC = 4) holds and every" in job["run_order"]
