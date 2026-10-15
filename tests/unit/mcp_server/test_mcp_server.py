"""The SDK-facing server and the ``cobol-parser mcp`` subcommand."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import MCP_SURFACE_VERSION, Workspace

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"


def _workspace() -> Workspace:
    return Workspace(
        ENTERPRISE, ProjectConfig(copybook_path=(str(ENTERPRISE / "copybooks"),))
    )


def _session(calls: list[tuple[str, dict[str, Any]]]) -> tuple[list[Any], list[Any]]:
    """List the tools, then make each call, over an in-memory MCP session."""
    pytest.importorskip("mcp")
    from mcp.shared.memory import create_connected_server_and_client_session

    from cobolparser.mcp.server import build_server

    server = build_server(_workspace())

    async def run() -> tuple[list[Any], list[Any]]:
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as client:
            listed = (await client.list_tools()).tools
            results = [await client.call_tool(name, args) for name, args in calls]
            return listed, results

    return asyncio.run(run())


class TestServer:
    def test_tools_are_listed_read_only_with_schemas(self) -> None:
        listed, _ = _session([])
        by_name = {tool.name: tool for tool in listed}
        assert set(by_name) == {
            "codebase_overview",
            "program_brief",
            "explain_symbol",
            "callers_of",
            "impact_of_change",
            "where_from",
            "record_layout",
            "lint",
            "read_source",
        }
        for tool in listed:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.description
            assert tool.outputSchema is not None
        assert by_name["explain_symbol"].inputSchema["required"] == ["file", "name"]
        assert by_name["callers_of"].inputSchema["required"] == ["name"]
        assert by_name["where_from"].inputSchema["required"] == ["field"]

    def test_calls_return_the_envelope(self) -> None:
        _, results = _session(
            [
                ("explain_symbol", {"file": "COPYREPL.cbl", "name": "CUST-ID"}),
                ("lint", {"file": "BATCHSEQ.cbl", "limit": 2}),
                ("read_source", {"file": "BATCHSEQ.cbl", "line": 2, "after": 0}),
                ("program_brief", {"file": "VSAMKSDS.cbl"}),
                ("callers_of", {"file": "BATCHSEQ.cbl", "name": "1000-INIT"}),
                ("record_layout", {"file": "COPYREPL.cbl", "record": "WS-COUNTERS"}),
                ("callers_of", {"name": "LOGGER"}),
                ("impact_of_change", {"name": "CUSTREC"}),
                ("where_from", {"field": "WS-EOF-FLAG", "file": "BATCHSEQ.cbl"}),
                ("codebase_overview", {"limit": 2}),
            ]
        )
        for result in results:
            assert result.isError is False
            assert result.structuredContent["surface_version"] == MCP_SURFACE_VERSION
        assert results[3].structuredContent["answer"]["files"]
        assert results[4].structuredContent["answer"]["found"] is True
        assert results[5].structuredContent["answer"]["records"][0]["fields"]
        assert results[6].structuredContent["answer"]["calling_programs"] == [
            "POSTER",
            "VALIDATE",
        ]
        assert results[7].structuredContent["answer"]["kind"] == "copybook"
        assert results[8].structuredContent["answer"]["kind"] == "field"
        assert len(results[9].structuredContent["answer"]["programs"]) == 2
        symbol = results[0].structuredContent["answer"]["symbols"][0]
        assert symbol["declared_at"]["file"] == "copybooks/DCLCUST.cpy"

    def test_a_slow_tool_does_not_block_the_loop(self) -> None:
        # A parse runs on a worker thread: the session keeps answering while
        # it does, and concurrent calls are serialized, not interleaved.
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.server import build_server
        from cobolparser.mcp.tools import CobolTools

        events: list[str] = []
        real_lint = CobolTools.lint

        def slow_lint(self: CobolTools, *args: Any) -> dict[str, Any]:
            events.append("lint-start")
            time.sleep(0.3)
            events.append("lint-end")
            return real_lint(self, *args)

        async def run() -> list[Any]:
            server = build_server(_workspace())
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:

                async def listing() -> Any:
                    await asyncio.sleep(0.05)
                    tools = await client.list_tools()
                    events.append("listed")
                    return tools

                return list(
                    await asyncio.gather(
                        client.call_tool("lint", {"file": "BATCHSEQ.cbl"}),
                        client.call_tool("lint", {"file": "SUBPROG.cbl"}),
                        listing(),
                    )
                )

        with patch.object(CobolTools, "lint", slow_lint):
            first, second, _ = asyncio.run(run())
        assert first.isError is False and second.isError is False
        assert events.index("listed") < events.index("lint-end")
        assert events.count("lint-start") == 2
        # One call at a time: each lint ends before the next starts.
        assert events.index("lint-end") < events.index("lint-start", 1)

    def test_a_refused_path_is_an_error_result(self) -> None:
        _, (result,) = _session([("read_source", {"file": "../../../pyproject.toml"})])
        assert result.isError is True
        assert "outside the workspace" in result.content[0].text


class TestCli:
    def _main(self, *argv: str) -> None:
        from cobolparser.cli.parse import main

        with patch("sys.argv", ["cobol-parser", *argv]):
            main()

    def test_serves_the_root_with_its_config(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        (tmp_path / "cobol.yml").write_text(
            "version: 1\nproject:\n  dialect: ibm-enterprise\n"
        )
        served: list[Workspace] = []
        with patch("cobolparser.mcp.server.run_stdio", served.append):
            self._main("mcp", "--root", str(tmp_path), "--cache-size", "3")
        (workspace,) = served
        assert workspace.root == tmp_path.resolve()
        assert workspace.cache_size == 3
        assert workspace.config.source == tmp_path / "cobol.yml"

    def test_no_config_wins_over_the_root(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        (tmp_path / "cobol.yml").write_text("version: 1\n")
        served: list[Workspace] = []
        with patch("cobolparser.mcp.server.run_stdio", served.append):
            self._main("--no-config", "mcp", "--root", str(tmp_path))
        assert served[0].config.source is None

    def test_bad_root(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pytest.importorskip("mcp")
        with pytest.raises(SystemExit) as exc:
            self._main("mcp", "--root", str(tmp_path / "missing"))
        assert exc.value.code == 1
        assert "not a directory" in capsys.readouterr().err

    def test_without_the_extra(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delitem(sys.modules, "cobolparser.mcp.server", raising=False)
        # None in sys.modules makes an import raise ImportError; every name
        # server.py imports is blocked, since a submodule already imported by
        # an earlier test would otherwise be found without its parent.
        for name in ("mcp", "mcp.server", "mcp.server.fastmcp", "mcp.types"):
            monkeypatch.setitem(sys.modules, name, None)
        with pytest.raises(SystemExit) as exc:
            self._main("mcp")
        assert exc.value.code == 1
        assert "pip install 'cobol-parser[mcp]'" in capsys.readouterr().err
