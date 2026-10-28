"""``check_claims`` (``cobolparser.mcp.claims``): each claim confirmed,
contradicted with evidence, or not checkable with the reason."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.claims import MAX_CLAIMS

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> CobolTools:
    root = tmp_path_factory.mktemp("claims")
    shutil.copytree(SAMPLES / "enterprise", root / "enterprise")
    shutil.copytree(SAMPLES / "lineage", root / "fees")
    config = ProjectConfig(copybook_path=(str(root / "enterprise" / "copybooks"),))
    return CobolTools(Workspace(root, config))


def verdict(tools: CobolTools, **claim: Any) -> dict[str, Any]:
    (result,) = tools.check_claims([claim])["answer"]["results"]
    return result


BATCHSEQ = "enterprise/BATCHSEQ.cbl"


class TestPrograms:
    def test_calls(self, tools: CobolTools) -> None:
        result = verdict(tools, kind="calls", subject="CICSONLN", object="CUSTAUDT")
        assert result["verdict"] == "confirmed"
        assert result["evidence"][0]["line"] > 0
        wrong = verdict(tools, kind="calls", subject="CICSONLN", object="NOPE")
        assert wrong["verdict"] == "contradicted"
        assert "CUSTAUDT" in wrong["why"]

    def test_unknown_program_is_not_checkable(self, tools: CobolTools) -> None:
        result = verdict(tools, kind="calls", subject="GHOST", object="X")
        assert result["verdict"] == "not_checkable"

    def test_copies(self, tools: CobolTools) -> None:
        good = verdict(tools, kind="copies", subject="DB2BATCH", object="SQLCA")
        assert good["verdict"] == "confirmed"
        bad = verdict(tools, kind="copies", subject="BATCHSEQ", object="SQLCA")
        assert bad["verdict"] == "contradicted"


class TestProcedures:
    def test_reachability(self, tools: CobolTools) -> None:
        claim = {"subject": "3100-PRINT-LINE", "file": BATCHSEQ}
        assert verdict(tools, kind="unreachable", **claim)["verdict"] == "contradicted"
        assert verdict(tools, kind="reachable", **claim)["verdict"] == "confirmed"

    def test_performs(self, tools: CobolTools) -> None:
        good = verdict(
            tools,
            kind="performs",
            subject="3000-WRITE-REPORT",
            object="3100-PRINT-LINE",
            file=BATCHSEQ,
        )
        assert good["verdict"] == "confirmed"
        bad = verdict(
            tools,
            kind="performs",
            subject="1000-INIT",
            object="3100-PRINT-LINE",
            file=BATCHSEQ,
        )
        assert bad["verdict"] == "contradicted"
        assert "3000-WRITE-REPORT" in bad["why"]


class TestFields:
    def test_sets_only_in(self, tools: CobolTools) -> None:
        good = verdict(
            tools,
            kind="sets_only_in",
            subject="3100-PRINT-LINE",
            object="WS-DEBIT-TOTAL",
            file=BATCHSEQ,
        )
        assert good["verdict"] == "confirmed"
        bad = verdict(
            tools,
            kind="sets_only_in",
            subject="1000-INIT",
            object="WS-DEBIT-TOTAL",
            file=BATCHSEQ,
        )
        assert bad["verdict"] == "contradicted"
        assert bad["evidence"] == [{"file": BATCHSEQ, "line": 142}]

    def test_writes_field(self, tools: CobolTools) -> None:
        claim = {"kind": "writes_field", "object": "HL-DATE", "file": BATCHSEQ}
        assert verdict(tools, subject="1000-INIT", **claim)["verdict"] == "confirmed"
        assert (
            verdict(tools, subject="9000-FINISH", **claim)["verdict"] == "contradicted"
        )

    def test_flows_to_through_an_overwrite(self, tools: CobolTools) -> None:
        # MOVE FEE-FEE TO WS-FEE, then SELECT ... INTO :WS-FEE, then DISPLAY:
        # a SELECT finding no row would leave FEE-FEE there, so unsettled.
        result = verdict(
            tools,
            kind="flows_to",
            subject="FEE-FEE",
            object="SYSOUT",
            file="fees/READER.cbl",
        )
        assert result["verdict"] == "not_checkable"
        assert "EXEC SQL" in result["why"]

    def test_flows_to_confirmed(self, tools: CobolTools) -> None:
        result = verdict(
            tools,
            kind="flows_to",
            subject="FEE-FEE",
            object="WS-FEE",
            file="fees/READER.cbl",
        )
        assert result["verdict"] == "confirmed"


class TestDatasets:
    def test_dataset_access(self, tools: CobolTools) -> None:
        pytest.importorskip("jclparser")
        good = verdict(
            tools, kind="reads_dataset", subject="READER", object="PROD.ACCT.MASTER"
        )
        assert good["verdict"] == "confirmed"
        bad = verdict(
            tools, kind="writes_dataset", subject="READER", object="PROD.ACCT.MASTER"
        )
        assert bad["verdict"] == "contradicted"


class TestShape:
    def test_unknown_kind_and_missing_fields(self, tools: CobolTools) -> None:
        assert verdict(tools, kind="bogus")["verdict"] == "not_checkable"
        missing = verdict(tools, kind="calls", subject="CICSONLN")
        assert missing["verdict"] == "not_checkable"
        assert "object" in missing["why"]

    def test_summary_and_cap(self, tools: CobolTools) -> None:
        claims = [{"kind": "bogus"}] * (MAX_CLAIMS + 2)
        result = tools.check_claims(claims)
        assert result["answer"]["summary"] == {"not_checkable": MAX_CLAIMS}
        assert result["truncated"][0]["field"] == "claims"

    def test_no_claims(self, tools: CobolTools) -> None:
        with pytest.raises(ToolError):
            tools.check_claims([])
