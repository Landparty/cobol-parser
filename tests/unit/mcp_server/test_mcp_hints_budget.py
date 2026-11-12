"""The answer budget (``envelope.fit_budget``) and next-step hints
(``hints.add_hints``)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.envelope import fit_budget, wire_size
from cobolparser.mcp.hints import MAX_HINTS, add_hints

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"
EVERY_TOOL = {
    "read_source",
    "read_procedure",
    "callers_of",
    "where_from",
    "program_brief",
    "lint",
    "jcl_job",
    "jobs_running",
    "dataset_users",
}


def _tools() -> CobolTools:
    return CobolTools(
        Workspace(
            ENTERPRISE,
            ProjectConfig(copybook_path=(str(ENTERPRISE / "copybooks"),)),
        )
    )


class TestFitBudget:
    def test_longest_list_is_halved_until_it_fits(self) -> None:
        result: dict[str, Any] = {
            "answer": {"small": [1, 2], "big": {"rows": ["x" * 40] * 200}},
            "truncated": [],
        }
        fit_budget(result, 2000)
        assert wire_size(result) <= 2000
        assert result["answer"]["small"] == [1, 2]
        (cut,) = result["truncated"]
        assert cut["field"] == "big.rows"
        assert cut["total"] == 200
        assert cut["shown"] == len(result["answer"]["big"]["rows"])
        assert cut["reason"] == "answer budget"

    def test_an_earlier_limit_cut_keeps_its_true_total(self) -> None:
        result: dict[str, Any] = {
            "answer": {"hits": ["y" * 100] * 50},
            "truncated": [{"field": "hits", "shown": 50, "total": 900}],
        }
        fit_budget(result, 1000)
        assert result["truncated"] == [
            {
                "field": "hits",
                "shown": len(result["answer"]["hits"]),
                "total": 900,
                "reason": "answer budget",
            }
        ]

    def test_cuts_keep_the_head_and_one_item(self) -> None:
        result: dict[str, Any] = {"answer": {"a": ["z" * 50, "z" * 50]}}
        fit_budget(result, 10)
        assert result["answer"]["a"] == ["z" * 50]

    def test_long_strings_are_halved_once_lists_are_at_one_item(self) -> None:
        result: dict[str, Any] = {"answer": {"a": ["z" * 5000, "z" * 5000]}}
        fit_budget(result, 2000)
        assert wire_size(result) <= 2000
        (text,) = result["answer"]["a"]
        assert set(text) == {"z"}
        cut = result["truncated"][-1]
        assert cut["field"] == "a[0]"
        assert cut["total_chars"] == 5000
        assert cut["shown_chars"] == len(text)

    def test_no_budget_or_small_answer_is_untouched(self) -> None:
        result: dict[str, Any] = {"answer": {"a": [1, 2, 3]}, "truncated": []}
        assert fit_budget(result, None) == {"answer": {"a": [1, 2, 3]}, "truncated": []}
        assert fit_budget(result, 10_000)["truncated"] == []


class TestHints:
    def test_brief_suggests_entry_paragraph_and_callers(self) -> None:
        result = add_hints(
            "program_brief", _tools().program_brief("BATCHSEQ.cbl"), EVERY_TOOL
        )
        assert result["next"][0].startswith('read_procedure(file="BATCHSEQ.cbl"')
        assert any(h.startswith("callers_of(") for h in result["next"])
        assert len(result["next"]) <= MAX_HINTS

    def test_only_offered_tools_are_named(self) -> None:
        result = add_hints(
            "program_brief", _tools().program_brief("BATCHSEQ.cbl"), {"lint"}
        )
        assert "next" not in result

    def test_symbol_suggests_where_from(self) -> None:
        tools = _tools()
        brief = tools.program_brief("BATCHSEQ.cbl")["answer"]
        name = brief["files"][0]["records"][0]
        result = add_hints(
            "explain_symbol", tools.explain_symbol("BATCHSEQ.cbl", name), EVERY_TOOL
        )
        assert result["next"][0] == f'where_from(field="{name}", file="BATCHSEQ.cbl")'

    def test_a_shape_it_does_not_know_never_fails(self) -> None:
        odd = {"answer": {"symbols": [{"kind": "data-item", "references": 3}]}}
        assert add_hints("explain_symbol", odd, EVERY_TOOL) is odd
        assert add_hints("no_such_tool", {"answer": {}}, EVERY_TOOL) == {"answer": {}}


class TestOverTheSession:
    def test_hints_and_budget_reach_the_client(self) -> None:
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.server import build_server

        workspace = Workspace(
            ENTERPRISE,
            ProjectConfig(copybook_path=(str(ENTERPRISE / "copybooks"),)),
        )
        server = build_server(workspace, "all", max_answer_bytes=3000)

        async def run() -> list[Any]:
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:
                return [
                    await client.call_tool("codebase_overview", {}),
                    await client.call_tool("program_brief", {"file": "BATCHSEQ.cbl"}),
                ]

        overview, brief = asyncio.run(run())
        content = overview.structuredContent
        assert len(json.dumps(content, separators=(",", ":"))) <= 3000
        assert any(t.get("reason") == "answer budget" for t in content["truncated"])
        assert brief.structuredContent["next"]
