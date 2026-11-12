"""MCP server findings from a run over a private mainframe checkout (2026-11-11).

* A10 -- ``check_claims`` ``flows_to`` called a group-to-group MOVE
  contradicted: the lineage reaches the group's children, never the group
  node, and only the last name of each hit was compared.
* A11 -- answers ran past ``--max-answer-bytes``: the budget measured
  compact JSON while the server sent a pretty-printed text copy beside the
  structured one, and an answer whose lists were down to one item stayed
  over. The budget now measures what is sent, the text copy is compact,
  and the longest strings are halved last.
* A12 -- a COPY member read badly (in the wrong source format) left wrong
  answers with no caveat: ``record_layout`` not found, ``explain_symbol``
  undeclared, false undefined-name errors, a ``decode_record`` short of
  fields, and parse errors cited at a line of the expanded text.
* A15 -- ``serverInfo.version`` was the MCP SDK's, ``mcp --help`` named 3
  of the tools, no progress notification was ever sent, and
  ``find_statements`` kept the sequence area of a fixed-format line.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cobolparser._version import __version__
from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.envelope import wire_size, wire_text
from cobolparser.mcp.tool_groups import ALL_TOOLS
from cobolparser.mcp.workspace import _cite_expanded_lines, _describe_error

ENTERPRISE = Path(__file__).resolve().parents[1] / "samples" / "enterprise"


def _rec(text: str, indicator: str = " ", seq: str = "      ") -> str:
    return (seq + indicator + text).ljust(72)[:72]


def _write(path: Path, records: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8", newline="")


def _tools(root: Path, copybooks: Path | None = None) -> CobolTools:
    config = ProjectConfig(copybook_path=(str(copybooks),) if copybooks else ())
    return CobolTools(Workspace(root, config))


class TestA10GroupFlows:
    def test_group_move_reaches_the_group(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "AEMCPRI2.cbl",
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. AEMCPRI2."),
                _rec("DATA DIVISION."),
                _rec("WORKING-STORAGE SECTION."),
                _rec("01  WSBNC-DATE-HUIT-RED."),
                _rec("    05  WSBNC-AA   PIC 9(4)."),
                _rec("    05  WSBNC-MM   PIC 99."),
                _rec("01  WS010-DATE-SYSTEME."),
                _rec("    05  WS010-AA   PIC 9(4)."),
                _rec("    05  WS010-MM   PIC 99."),
                _rec("PROCEDURE DIVISION."),
                _rec("MAIN-PARA."),
                _rec("    ACCEPT WSBNC-DATE-HUIT-RED FROM DATE YYYYMMDD"),
                _rec("    MOVE WSBNC-DATE-HUIT-RED TO WS010-DATE-SYSTEME"),
                _rec("    DISPLAY WS010-AA"),
                _rec("    GOBACK."),
            ],
        )
        result = _tools(tmp_path).check_claims(
            [
                {
                    "kind": "flows_to",
                    "subject": "WSBNC-DATE-HUIT-RED",
                    "object": "WS010-DATE-SYSTEME",
                    "file": "AEMCPRI2.cbl",
                }
            ]
        )
        (verdict,) = result["answer"]["results"]
        assert verdict["verdict"] == "confirmed", verdict


def _session(
    workspace: Workspace, calls: list[tuple[str, dict[str, Any]]], **kwargs: Any
) -> list[Any]:
    pytest.importorskip("mcp")
    from mcp.shared.memory import create_connected_server_and_client_session

    from cobolparser.mcp.server import build_server

    server = build_server(workspace, "all", **kwargs)

    async def run() -> list[Any]:
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(run())


class TestA11WireBudget:
    def test_what_is_sent_fits_the_budget(self) -> None:
        workspace = Workspace(
            ENTERPRISE, ProjectConfig(copybook_path=(str(ENTERPRISE / "copybooks"),))
        )
        (overview,) = _session(
            workspace, [("codebase_overview", {})], max_answer_bytes=6000
        )
        structured = overview.structuredContent
        (text,) = overview.content
        # The text copy is the compact JSON of the structured one ...
        assert text.text == wire_text(structured)
        assert json.loads(text.text) == structured
        # ... and both together, as sent, are what the budget measured.
        assert len(text.text) + len(wire_text(structured)) <= wire_size(structured)
        assert wire_size(structured) <= 6000
        assert any(t.get("reason") == "answer budget" for t in structured["truncated"])


def _degraded_workspace(root: Path) -> CobolTools:
    """A fixed-format program COPYing a member whose banner carries a ``"``
    in column 3: the member is read as free-form and its fields are lost."""
    copybooks = root / "copy"
    banner = [
        _rec("* MOVE THE TOTAL TO THE REPORT", "*", '  "   '),
        _rec("* COMPUTE THE NET AMOUNT", "*", '  "   '),
        _rec("01  SGP-REC.", " ", '  "   '),
        *[_rec(f"    05  SGP-{c}  PIC X(3).", " ", '  "   ') for c in "ABCDEFG"],
        _rec("* MULTIPLY THE RATE BY THE BASE", "*"),
        _rec("    05  SGP-H  PIC X(3)."),
    ]
    _write(copybooks / "SGPCBDET.cpy", banner)
    _write(
        root / "CKMACK02.cbl",
        [
            _rec("IDENTIFICATION DIVISION."),
            _rec("PROGRAM-ID. CKMACK02."),
            _rec("DATA DIVISION."),
            _rec("WORKING-STORAGE SECTION."),
            _rec("01  WS-X PIC X."),
            _rec("    COPY SGPCBDET."),
            _rec("PROCEDURE DIVISION."),
            _rec("MAIN-PARA."),
            _rec("    MOVE SGP-A TO SGP-B."),
            _rec("    DISPLAY SGP-H."),
            _rec("    GOBACK."),
        ],
    )
    return _tools(root, copybooks)


def _caveat_text(result: dict[str, Any]) -> str:
    return " | ".join(c["detail"] for c in result["caveats"])


class TestA12DegradedMembers:
    """Each answer either sees the member's declarations, or says why not.
    Once the member detector reads the banner right (the source-format fix),
    the answers are right and these caveats are simply not raised."""

    def _degraded(self, result: dict[str, Any]) -> bool:
        return "copy/SGPCBDET.cpy was read with" in _caveat_text(result)

    def test_lint_withholds_undefined_names_the_member_declares(
        self, tmp_path: Path
    ) -> None:
        result = _degraded_workspace(tmp_path).lint("CKMACK02.cbl")
        undefined = [
            f for f in result["answer"]["findings"] if f["rule"] == "undefined-name"
        ]
        assert undefined == []
        if self._degraded(result):
            assert "undefined-name finding(s) withheld" in _caveat_text(result)

    def test_record_layout_names_the_member(self, tmp_path: Path) -> None:
        result = _degraded_workspace(tmp_path).record_layout("CKMACK02.cbl", "SGP-REC")
        answer = result["answer"]
        if not answer.get("found", True):
            assert self._degraded(result)
            assert answer["declared_in_degraded_copybook"] == "copy/SGPCBDET.cpy"

    def test_explain_symbol_names_the_member(self, tmp_path: Path) -> None:
        result = _degraded_workspace(tmp_path).explain_symbol("CKMACK02.cbl", "SGP-A")
        (symbol,) = result["answer"]["symbols"]
        if not symbol["declared"]:
            assert self._degraded(result)
            assert symbol["declared_in_degraded_copybook"] == "copy/SGPCBDET.cpy"

    def test_decode_record_says_fields_are_missing(self, tmp_path: Path) -> None:
        result = _degraded_workspace(tmp_path).decode_record("copy/SGPCBDET.cpy")
        names = {f["name"] for f in result["answer"]["fields"]}
        expected = {f"SGP-{c}" for c in "ABCDEFGH"}
        if names != expected:
            assert "declares 7 field(s) the layout does not hold" in _caveat_text(
                result
            )

    def test_a_healthy_member_draws_no_caveat(self, tmp_path: Path) -> None:
        copybooks = tmp_path / "copy"
        _write(
            copybooks / "GOOD.cpy", [_rec("01  GOOD-REC."), _rec("    05  G-A PIC X.")]
        )
        _write(
            tmp_path / "P.cbl",
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. P."),
                _rec("DATA DIVISION."),
                _rec("WORKING-STORAGE SECTION."),
                _rec("    COPY GOOD."),
                _rec("PROCEDURE DIVISION."),
                _rec("    DISPLAY G-A GOBACK."),
            ],
        )
        tools = _tools(tmp_path, copybooks)
        assert "read with" not in _caveat_text(tools.lint("P.cbl"))
        assert _caveat_text(tools.decode_record("copy/GOOD.cpy")) == ""

    def test_expanded_lines_are_cited_on_disk(self) -> None:
        from cobolparser._errors import ParseError

        source_map = {3039: ("/w/copy/SGSSADET.cpy", 27)}
        assert (
            _cite_expanded_lines(
                "bad at line 3039, column 3", source_map, lambda f: f.split("/w/")[1]
            )
            == "bad at copy/SGSSADET.cpy:27, column 3"
        )
        error = ParseError("unexpected token", file_path="/w/P.cbl", line_number=3039)
        assert (
            _describe_error(error, source_map, lambda f: f.split("/w/")[1])
            == "copy/SGSSADET.cpy:27: unexpected token"
        )
        # A line the map does not hold is left as it was.
        assert _cite_expanded_lines("line 7", source_map, str) == "line 7"


class TestA15Polish:
    def test_server_version_is_the_package_version(self) -> None:
        pytest.importorskip("mcp")
        from cobolparser.mcp.server import build_server

        server = build_server(Workspace(ENTERPRISE), "all")
        options = server._mcp_server.create_initialization_options()
        assert options.server_version == __version__

    def test_mcp_help_lists_every_tool_and_the_config_flags(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cobolparser.cli import main

        with patch("sys.argv", ["cobol-parser", "mcp", "--help"]):
            with pytest.raises(SystemExit):
                main()
        out = " ".join(capsys.readouterr().out.split())
        for tool in ALL_TOOLS:
            assert tool in out, tool
        assert "--config" in out and "--no-config" in out

    def test_a_subcommand_help_is_its_own(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cobolparser.cli import main

        with patch("sys.argv", ["cobol-parser", "lint", "--help"]):
            with pytest.raises(SystemExit):
                main()
        assert "usage: cobol-parser lint" in capsys.readouterr().out

    def test_progress_is_reported_while_facts_are_read(self) -> None:
        pytest.importorskip("mcp")
        from mcp.shared.memory import create_connected_server_and_client_session

        from cobolparser.mcp.server import build_server

        workspace = Workspace(
            ENTERPRISE, ProjectConfig(copybook_path=(str(ENTERPRISE / "copybooks"),))
        )
        server = build_server(workspace, "all")
        seen: list[tuple[float, float | None, str | None]] = []

        async def on_progress(
            progress: float, total: float | None, message: str | None
        ) -> None:
            seen.append((progress, total, message))

        async def run() -> None:
            async with create_connected_server_and_client_session(
                server._mcp_server
            ) as client:
                await client.call_tool(
                    "codebase_overview", {}, progress_callback=on_progress
                )

        asyncio.run(run())
        assert seen
        assert any("reading" in (message or "") for _, _, message in seen)

    def test_find_statements_drops_the_sequence_area(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "SEQ.cbl",
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. SEQ."),
                _rec("PROCEDURE DIVISION."),
                _rec("MAIN-PARA."),
                _rec("    CALL 'SUBPGM'", seq="Y2K   "),
                _rec("    GOBACK."),
            ],
        )
        result = _tools(tmp_path).find_statements(verb="CALL", file="SEQ.cbl")
        (hit,) = result["answer"]["statements"]
        assert "Y2K" not in json.dumps(hit)
        assert "CALL 'SUBPGM'" in json.dumps(hit)
