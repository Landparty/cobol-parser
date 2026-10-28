"""``mcp --cache-dir``: the root-wide indexes kept on disk between sessions.

A fresh server over an unchanged root must answer exactly as one that
parsed every program, without parsing any; a program edited since must be
parsed again, and only that one.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.codebase_index import (
    health_index,
    lineage_index,
    programs_index,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _scrub(value: Any) -> Any:
    """*value* without timings, which differ between any two builds."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k != "built_in_seconds"}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _workspace(root: Path, cache: Path | None, **config: object) -> Workspace:
    return Workspace(
        root, ProjectConfig(**config), cache_dir=cache  # type: ignore[arg-type]
    )


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    parsed: list[str] = []
    original = Workspace._parse

    def counting(self: Workspace, path: Path) -> Any:
        parsed.append(path.name)
        return original(self, path)

    monkeypatch.setattr(Workspace, "_parse", counting)
    return parsed


def _answers(tools: CobolTools) -> list[Any]:
    return [
        _scrub(tools.codebase_overview(limit=200)),
        _scrub(tools.callers_of(None, "SUBPROG")),
        _scrub(tools.impact_of_change("CUSTREC")),
        _scrub(tools.impact_of_change("WS-EOF-FLAG")),
        _scrub(tools.where_from("WS-EOF-FLAG")),
    ]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "src"
    shutil.copytree(SAMPLES / "enterprise", target)
    return target


def _config(root: Path) -> dict[str, object]:
    return {"copybook_path": (str(root / "copybooks"),)}


class TestIndexCache:
    def test_a_warm_cache_answers_the_same_without_parsing(
        self, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "cache"
        uncached = _answers(CobolTools(_workspace(root, None, **_config(root))))
        cold = _answers(CobolTools(_workspace(root, cache, **_config(root))))
        parsed = _count_parses(monkeypatch)
        warm_workspace = _workspace(root, cache, **_config(root))
        for build in (programs_index, lineage_index, health_index):
            build(warm_workspace)
        assert parsed == []
        warm = _answers(CobolTools(warm_workspace))
        assert cold == uncached
        assert warm == uncached

    def test_an_edited_program_alone_is_parsed_again(
        self, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "cache"
        programs_index(_workspace(root, cache, **_config(root)))
        program = root / "SUBPROG.cbl"
        before = program.stat().st_mtime_ns
        program.write_text(program.read_text().replace("SUBPROG", "SUBPRG2"))
        os.utime(program, ns=(before + 10**9, before + 10**9))
        parsed = _count_parses(monkeypatch)
        index = programs_index(_workspace(root, cache, **_config(root)))
        assert parsed == ["SUBPROG.cbl"]
        assert "SUBPRG2" in index.graph.program_ids

    def test_an_edited_copybook_reparses_its_users(
        self, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "cache"
        programs_index(_workspace(root, cache, **_config(root)))
        member = next((root / "copybooks").iterdir())
        before = member.stat().st_mtime_ns
        member.write_text(member.read_text() + "\n")
        os.utime(member, ns=(before + 10**9, before + 10**9))
        parsed = _count_parses(monkeypatch)
        programs_index(_workspace(root, cache, **_config(root)))
        assert parsed  # the programs that expanded it
        assert len(parsed) < len(list(root.glob("*.cbl")))

    def test_a_different_config_does_not_share_entries(
        self, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "cache"
        programs_index(_workspace(root, cache, **_config(root)))
        parsed = _count_parses(monkeypatch)
        programs_index(_workspace(root, cache))  # no copybook path
        assert len(parsed) == len(list(root.glob("*.cbl")))

    def test_caveats_survive_the_cache(self, root: Path, tmp_path: Path) -> None:
        # Without the copybook path every COPY is left unexpanded: a caveat
        # noted on the parse, which a cached file must still carry.
        cache = tmp_path / "cache"
        cold = programs_index(_workspace(root, cache))
        warm = programs_index(_workspace(root, cache))
        assert cold.file_caveats and warm.file_caveats == cold.file_caveats
        assert warm.failed == cold.failed

    def test_lineage_through_jcl(self, tmp_path: Path) -> None:
        pytest.importorskip("jclparser")
        root = tmp_path / "lineage"
        shutil.copytree(SAMPLES / "lineage", root)
        cache = tmp_path / "cache"

        def answer(workspace: Workspace) -> Any:
            return _scrub(
                CobolTools(workspace).impact_of_change("WS-FEE", "WRITER.cbl")
            )

        uncached = answer(_workspace(root, None))
        answer(_workspace(root, cache))
        assert answer(_workspace(root, cache)) == uncached

    def test_cli_flag_reaches_the_workspace(self, monkeypatch, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        import sys

        from cobolparser.cli import parse as cli

        seen: dict[str, Any] = {}

        def fake_run(tools: Any, *args: Any, **kwargs: Any) -> None:
            seen["cache_dir"] = getattr(tools, "workspace", tools).cache_dir

        monkeypatch.setattr("cobolparser.mcp.server.run_stdio", fake_run)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cobol-parser",
                "--no-config",
                "mcp",
                "--root",
                str(tmp_path),
                "--cache-dir",
                str(tmp_path / "c"),
            ],
        )
        try:
            cli.main()
        except SystemExit as exc:
            assert not exc.code
        assert seen["cache_dir"] == str(tmp_path / "c")
