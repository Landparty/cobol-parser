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
            "business_rules",
            "diff_programs",
            "decode_record",
            "gen_fixtures",
            "jcl_job",
            "jobs_running",
            "dataset_users",
        }
        for tool in listed:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.description
            assert tool.outputSchema is not None
        assert by_name["explain_symbol"].inputSchema["required"] == ["file", "name"]
        assert by_name["callers_of"].inputSchema["required"] == ["name"]
        assert by_name["where_from"].inputSchema["required"] == ["field"]
        assert by_name["diff_programs"].inputSchema["required"] == [
            "old_file",
            "new_file",
        ]
        assert by_name["decode_record"].inputSchema["required"] == ["copybook"]
        assert by_name["jcl_job"].inputSchema["required"] == ["file"]
        assert by_name["jobs_running"].inputSchema["required"] == ["program"]
        assert by_name["dataset_users"].inputSchema["required"] == ["dataset"]

    def test_v3_tools_answer_over_the_session(self) -> None:
        _, results = _session(
            [
                ("business_rules", {"file": "DB2BATCH.cbl"}),
                (
                    "diff_programs",
                    {"old_file": "BATCHSEQ.cbl", "new_file": "BATCHSEQ.cbl"},
                ),
                ("decode_record", {"copybook": "copybooks/DCLCUST.cpy"}),
                ("gen_fixtures", {"file": "BATCHSEQ.cbl", "limit": 1}),
                ("business_rules", {"file": "DB2BATCH.cbl", "kind": "bogus"}),
            ]
        )
        rules, diff, layout, fixtures, bad = results
        assert rules.structuredContent["answer"]["rules"]
        assert diff.structuredContent["answer"]["summary"]["total_changes"] == 0
        assert layout.structuredContent["answer"]["fields"]
        assert fixtures.structuredContent["answer"]["scenarios"]
        assert bad.isError is True

    def test_prompts_are_listed_and_rendered(self) -> None:
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.prompts import PROMPTS
        from cobolparser.mcp.server import build_server

        server = build_server(_workspace())

        async def run() -> tuple[Any, Any]:
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:
                listed = await client.list_prompts()
                got = await client.get_prompt(
                    "explain_program", {"file": "BATCHSEQ.cbl"}
                )
                return listed, got

        listed, got = asyncio.run(run())
        assert [p.name for p in listed.prompts] == [p.name for p in PROMPTS]
        assert all(p.description for p in listed.prompts)
        text = got.messages[0].content.text
        assert "BATCHSEQ.cbl" in text and "program_brief" in text

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

    def test_indexing_reports_progress(self) -> None:
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.server import build_server

        workspace = _workspace()
        server = build_server(workspace)
        seen: list[tuple[float, float | None, str | None]] = []

        async def on_progress(
            done: float, total: float | None, message: str | None
        ) -> None:
            seen.append((done, total, message))

        async def run() -> Any:
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:
                return await client.call_tool(
                    "codebase_overview", {}, progress_callback=on_progress
                )

        with patch("cobolparser.mcp.server.PROGRESS_INTERVAL", 0.0):
            result = asyncio.run(run())
        assert result.isError is False
        assert seen
        assert seen[0][1] == 22
        assert str(seen[0][2]).startswith("reading ")
        # The listener belongs to that one call.
        assert workspace.progress is None


def _recorder(served: list[Workspace]) -> Any:
    def record(
        workspace: Workspace, tools_spec: str | None = None, budget: int | None = None
    ) -> None:
        served.append(workspace)

    return record


class TestToolSelection:
    def test_auto_is_core_plus_jcl_only_with_jcl(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        from cobolparser.mcp.server import TOOL_GROUPS, select_tools

        (tmp_path / "A.cbl").write_text("")
        bare = select_tools("auto", Workspace(tmp_path, ProjectConfig()))
        assert bare == set(TOOL_GROUPS["core"])
        (tmp_path / "RUN.jcl").write_text("//RUN JOB\n")
        with_jcl = select_tools(None, Workspace(tmp_path, ProjectConfig()))
        assert with_jcl == set(TOOL_GROUPS["core"]) | set(TOOL_GROUPS["jcl"])

    def test_groups_and_names(self) -> None:
        pytest.importorskip("mcp")
        from cobolparser.mcp.server import ALL_TOOLS, select_tools

        ws = _workspace()
        assert select_tools("all", ws) == set(ALL_TOOLS)
        assert select_tools("data, read_source", ws) == {
            "decode_record",
            "gen_fixtures",
            "diff_programs",
            "read_source",
        }
        with pytest.raises(ValueError, match="unknown tool or group 'nope'"):
            select_tools("nope", ws)

    def test_only_selected_tools_are_listed(self) -> None:
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.server import build_server

        server = build_server(_workspace(), "read_source,lint")

        async def run() -> list[Any]:
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:
                return (await client.list_tools()).tools

        listed = asyncio.run(run())
        assert {t.name for t in listed} == {"read_source", "lint"}
        assert "codebase_overview" in (server.instructions or "")
        assert "--tools all" in (server.instructions or "")

    def test_schema_is_compacted(self) -> None:
        pytest.importorskip("mcp")
        from cobolparser.mcp.server import compact_schema

        schema = {
            "title": "fArguments",
            "type": "object",
            "properties": {
                "title": {"title": "Title", "type": "string"},
                "file": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "d",
                    "title": "File",
                },
                "rules": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ],
                    "default": None,
                },
                "seed": {"type": "integer", "default": 0},
            },
            "required": ["title"],
        }
        assert compact_schema(schema) == {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "file": {"type": "string", "description": "d"},
                "rules": {"type": "array", "items": {"type": "string"}},
                "seed": {"type": "integer", "default": 0},
            },
            "required": ["title"],
        }

    def test_optional_arguments_still_accept_null(self) -> None:
        _, (result,) = _session(
            [("program_brief", {"file": "BATCHSEQ.cbl", "program": None})]
        )
        assert result.isError is False


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
        with patch("cobolparser.mcp.server.run_stdio", _recorder(served)):
            self._main("mcp", "--root", str(tmp_path), "--cache-size", "3")
        (workspace,) = served
        assert workspace.root == tmp_path.resolve()
        assert workspace.cache_size == 3
        assert workspace.config.source == tmp_path / "cobol.yml"

    def test_no_config_wins_over_the_root(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        (tmp_path / "cobol.yml").write_text("version: 1\n")
        served: list[Workspace] = []
        with patch("cobolparser.mcp.server.run_stdio", _recorder(served)):
            self._main("--no-config", "mcp", "--root", str(tmp_path))
        assert served[0].config.source is None

    def test_refused_copybook_dir_is_warned_about(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pytest.importorskip("mcp")
        root = tmp_path / "repo"
        books = tmp_path / "books"
        root.mkdir()
        books.mkdir()
        (root / "cobol.yml").write_text(
            f'version: 1\nproject:\n  copybook_path: ["/", "{books}"]\n'
        )
        served: list[Workspace] = []
        with patch("cobolparser.mcp.server.run_stdio", _recorder(served)):
            self._main("mcp", "--root", str(root))
        (workspace,) = served
        assert workspace.config.copybook_path == (str(books),)
        err = capsys.readouterr().err
        assert err.count("is refused") == 1
        assert "the filesystem root" in err

    def test_tools_flag(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        specs: list[str | None] = []

        def record(
            workspace: Workspace,
            tools_spec: str | None = None,
            budget: int | None = None,
        ) -> None:
            specs.append(tools_spec)

        with patch("cobolparser.mcp.server.run_stdio", record):
            self._main("mcp", "--root", str(tmp_path))
            self._main("mcp", "--root", str(tmp_path), "--tools", "core,jcl")
        assert specs == ["auto", "core,jcl"]

    def test_bad_tools_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pytest.importorskip("mcp")
        with pytest.raises(SystemExit) as exc:
            self._main("mcp", "--root", str(tmp_path), "--tools", "bogus")
        assert exc.value.code == 1
        assert "unknown tool or group" in capsys.readouterr().err

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
