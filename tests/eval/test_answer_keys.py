"""The benchmark's answer keys, checked against the tools themselves.

``tasks.json`` holds the questions the MCP benchmark asks a model about the
shop, each with the verified facts a correct answer states. ``run_eval.py``
measures a model; this file pins the half that needs no model: that the
tool a model would call for each task returns those facts. A change that
makes a tool stop saying one fails here, before any benchmark run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from build_shop import build_shop

from cobolparser.mcp import CobolTools, Workspace

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
TASKS = {t["id"]: t for t in json.loads((HERE / "tasks.json").read_text())}


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> CobolTools:
    root = build_shop(tmp_path_factory.mktemp("eval") / "shop")
    return CobolTools(Workspace(root))


def answer(result: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = result["answer"]
    return body


def test_every_task_is_pinned() -> None:
    pinned = {
        name[5:].split("_")[0].upper() for name in globals() if name[:5] == "test_"
    }
    for task_id in TASKS:
        assert task_id.split("-")[0] in pinned, task_id


def test_t01_layout(tools: CobolTools) -> None:
    (record,) = answer(tools.record_layout("orders/ORDEDIT.cbl", "ORD-REC"))["records"]
    assert record["byte_length"] == 110
    (field,) = [f for f in record["fields"] if f["name"] == "ORD-DISC-PCT"]
    assert (field["byte_offset"], field["byte_length"]) == (98, 2)


def test_t02_deadcode(tools: CobolTools) -> None:
    findings = answer(tools.lint("orders/ORDPOST.cbl", ["dead-code"]))["findings"]
    assert {f["symbol"] for f in findings} == {"9000-OLD-RECALC", "9100-OLD-AUDIT"}


def test_t03_callers(tools: CobolTools) -> None:
    body = answer(tools.callers_of(None, "POSTINTL"))
    assert body["calling_programs"] == ["ORDPOST"]
    (caller,) = body["callers"]
    assert caller["dynamic"] is True
    assert caller["target_from"] == "WS-POST-PGM"
    assert caller["from"] == "2000-POST"
    assert caller["location"] == {"file": "orders/ORDPOST.cbl", "line": 42}


def test_t04_copyimpact(tools: CobolTools) -> None:
    body = answer(tools.impact_of_change("ADDRREC"))
    assert body["copied_by"] == []
    through = {
        row["program"]: row["chains"] for row in body["copied_through_other_members"]
    }
    assert set(through) == {"ORDEDIT", "ORDVAL", "ORDPOST", "POSTDOM", "POSTINTL"}
    assert all(chain[0][1] == "ORDREC" for chain in through.values())


def test_t05_jobsrunning(tools: CobolTools) -> None:
    steps = {
        (s["job"], s["name"]): {d["ddname"]: d for d in s["dds"]}
        for s in answer(tools.jobs_running("ORDRPT"))["steps"]
    }
    assert set(steps) == {("ORDNIGHT", "STEP040.RPT"), ("ORDMONTH", "STEP010.RPT")}
    night, month = (
        steps[("ORDNIGHT", "STEP040.RPT")],
        steps[("ORDMONTH", "STEP010.RPT")],
    )
    assert night["ORDHIST"]["dataset"] == "PROD.ORD.HISTORY(+1)"
    assert night["RPTOUT"]["dataset"] == "PROD.ORD.DAILY.REPORT(+1)"
    assert month["ORDHIST"]["dataset"] == "PROD.ORD.HISTORY(0)"
    assert month["RPTOUT"]["kind"] == "sysout"


def test_t06_datasetusers(tools: CobolTools) -> None:
    uses = {
        (u["job"], u["step"]): u
        for u in answer(tools.dataset_users("PROD.ORD.REJECTS"))["uses"]
    }
    assert set(uses) == {("ORDNIGHT", "STEP010.EDIT"), ("ORDMONTH", "STEP020")}
    edit = uses[("ORDNIGHT", "STEP010.EDIT")]
    assert (edit["programs"], edit["access"]) == (["ORDEDIT"], "extend")
    delete = uses[("ORDMONTH", "STEP020")]
    assert delete["programs"] == ["IEFBR14"]
    assert delete["disposition"] == "(OLD,DELETE,KEEP)"


def test_t07_lineage(tools: CobolTools) -> None:
    body = answer(tools.where_from("RPT-TOTAL", "orders/ORDRPT.cbl"))
    assert set(body["datasets"]) >= {
        "PROD.ORD.DAILY",
        "PROD.ORD.GOOD",
        "PROD.ORD.GOOD.SORTED",
        "PROD.ORD.HISTORY",
    }
    assert {"ORDEDIT", "ORDPOST", "ORDRPT"} <= set(body["programs"])
    assert any(end.startswith("PROD.ORD.DAILY@") for end in body["trail_ends"])


def test_t08_rules(tools: CobolTools) -> None:
    rules = answer(tools.business_rules("orders/ORDEDIT.cbl"))["rules"]
    conditions = " | ".join(str(r.get("condition")) for r in rules)
    assert "ORD-QTY <= 0 OR ORD-CUST-ID = ZERO" in conditions
    assert "WS-VAL-RC <> 0" in conditions
    assert "WS-HOLD-LIMIT" in conditions


def test_t09_symbol(tools: CobolTools) -> None:
    (symbol,) = answer(tools.explain_symbol("enterprise/COPYREPL.cbl", "OUT-CITY"))[
        "symbols"
    ]
    assert symbol["declared_at"]["file"] == "enterprise/copybooks/CUSTREC.cpy"
    assert symbol["declared_at"]["line"] == 10
    layout = symbol["layout"]
    assert (layout["picture"], layout["byte_offset"], layout["byte_length"]) == (
        "X(20)",
        75,
        20,
    )
    assert symbol["references"][0]["location"] == {
        "file": "enterprise/COPYREPL.cbl",
        "line": 44,
    }


def test_t10_procoverride(tools: CobolTools) -> None:
    pytest.importorskip("jclparser")
    datasets: dict[str, str | None] = {}
    for job in answer(tools.jcl_job("jcl/payproc.jcl"))["jobs"]:
        assert job["name"] == "PAYROLL1"
        for step in job["steps"]:
            for dd in step["dds"]:
                if dd["ddname"] in ("PAYMAST", "PAYRPT") and step.get("program") in (
                    "PAYEXTR",
                    "PAYRPT",
                ):
                    datasets[f"{step['program']}.{dd['ddname']}"] = dd.get("dataset")
    assert datasets["PAYEXTR.PAYMAST"] == "PROD.PAY.MASTER.WEEKLY"
    assert datasets["PAYRPT.PAYRPT"] == "PROD.PAY.REPORT(+1)"


def test_h01_external(tools: CobolTools) -> None:
    graph = answer(tools.codebase_overview())["call_graph"]
    missing = {row["program"] for row in graph["not_in_workspace"]}
    assert missing == {
        "CBLTDLI",
        *(f"CEE{s}" for s in ("3ABD", "DATE", "DAYS", "FRST", "GMT", "GTST")),
        *(f"CEEH{s}" for s in ("DLR", "DLU")),
        "CEEMOUT",
        *(f"MQ{s}" for s in ("BACK", "CLOSE", "CMIT", "CONN", "DISC", "GET", "OPEN")),
        "MQPUT1",
        "DSNTIAR",
        "CUSTAUDT",
        "CMENU",
        "FIC401M",
        "RATECALC",
        "SUBA",
        "XXXXXXXX",
    }


def test_h02_nestedcopy(tools: CobolTools) -> None:
    body = answer(tools.impact_of_change("WSFLAGS"))
    assert body["copied_by"] == []
    (row,) = body["copied_through_other_members"]
    assert row["program"] == "COPYREPL"
    assert row["chains"] == [["COPYREPL", "WSCOUNTS", "WSFLAGS"]]


def test_h03_feeimpact(tools: CobolTools) -> None:
    body = answer(tools.impact_of_change("OUT-FEE", "fees/WRITER.cbl"))
    assert body["programs"] == ["READER"]
    assert set(body["datasets"]) == {"FEEJOB/&&FEES", "PROD.FEE.SUMMARY"}
    # The fee READER displays is the SELECT INTO's, not the one it read.
    (display,) = [h for h in body["hits"] if "SYSOUT" in h["field"]]
    assert display["may_be_overwritten"] == ["WS-FEE by EXEC SQL at fees/READER.cbl:31"]
    assert any(h["derived"] for h in body["hits"] if h["field"] == "FEE-REC.FEE-FEE")
