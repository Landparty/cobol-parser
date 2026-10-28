"""``slice``: the statements that can affect a field, or that it affects
(``cobolparser.mcp.slicing``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.hints import add_hints

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"


def _tools(root: Path = ENTERPRISE) -> CobolTools:
    return CobolTools(
        Workspace(root, ProjectConfig(copybook_path=(str(root / "copybooks"),)))
    )


def _rows(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for p in answer["paragraphs"] for s in p["statements"]]


def _lines(answer: dict[str, Any], role: str | None = None) -> list[int]:
    return [
        r["location"]["line"]
        for r in _rows(answer)
        if role is None or r["role"] == role
    ]


class TestBackward:
    def test_what_feeds_a_total(self) -> None:
        answer = _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL")["answer"]
        assert answer["found"] is True
        # READ -> MOVE TRAN-REC TO SORT-REC -> ADD SORT-AMOUNT TO the total,
        # and the IF / PERFORM / READ AT END they run under.
        assert _lines(answer, "data") == [120, 125, 142]
        assert set(_lines(answer, "control")) == {119, 124, 141}
        assert answer["ports"] == ["file:TRANIN@11+6"]
        assert "SORT-REC.SORT-AMOUNT" in answer["fields"]
        # The other fields of the record the total is not computed from.
        assert 138 not in _lines(answer)

    def test_every_row_is_cited_on_disk(self) -> None:
        answer = _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL")["answer"]
        source = (ENTERPRISE / "BATCHSEQ.cbl").read_text().splitlines()
        for row in _rows(answer):
            assert row["location"]["file"] == "BATCHSEQ.cbl"
            text = source[row["location"]["line"] - 1]
            assert row["text"].split()[0] in text

    def test_inexact_aliases_are_named_not_followed(self) -> None:
        tools = _tools()
        plain = tools.slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL")["answer"]
        assert any("redefines" in a for a in plain["aliases_not_followed"])
        wide = tools.slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL", aliases=True)["answer"]
        assert len(_rows(wide)) > len(_rows(plain))
        assert "aliases_not_followed" not in wide


class TestForward:
    def test_what_a_field_feeds_and_decides(self) -> None:
        answer = _tools().slice("BATCHSEQ.cbl", "SORT-TYPE", "forward")["answer"]
        assert _lines(answer, "decision") == [141]
        # The EVALUATE's arms run only on one outcome of the test.
        assert _lines(answer, "controlled") == [142, 143]
        assert 145 in _lines(answer, "data")
        assert answer["ports"] == ["file:RPTOUT@14+1"]

    def test_a_level_88_test_counts(self) -> None:
        answer = _tools().slice("BATCHSEQ.cbl", "TRAN-TYPE", "forward")["answer"]
        (row,) = [r for r in _rows(answer) if r["location"]["line"] == 124]
        assert "tests TRAN-REC.TRAN-TYPE" in row["flows"]


class TestErrors:
    def test_unknown_field_suggests(self) -> None:
        answer = _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTL")["answer"]
        assert answer["found"] is False
        assert "WS-DEBIT-TOTAL" in answer["suggestions"]

    def test_bad_direction(self) -> None:
        with pytest.raises(ToolError):
            _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL", "sideways")

    def test_limit_cuts_and_says_so(self) -> None:
        result = _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL", limit=2)
        assert len(_rows(result["answer"])) == 2
        assert result["truncated"]


class TestHints:
    def test_slice_points_across_the_boundary(self) -> None:
        result = _tools().slice("BATCHSEQ.cbl", "WS-DEBIT-TOTAL")
        hinted = add_hints("slice", result, {"where_from", "read_procedure"})
        assert (
            'where_from(field="WS-DEBIT-TOTAL", file="BATCHSEQ.cbl")' in hinted["next"]
        )
