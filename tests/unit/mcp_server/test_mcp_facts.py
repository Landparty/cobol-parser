"""Per-file facts behind the root-wide indexes: one parse per file, kept on
disk, recomputed only for what changed, built in parallel and warmed up."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp import facts as facts_module
from cobolparser.mcp.facts import FactsStore, default_cache_dir, store_for

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "src"
    shutil.copytree(ENTERPRISE, target)
    return target


def make_tools(root: Path, **store: Any) -> CobolTools:
    workspace = Workspace(root, ProjectConfig(copybook_path=(str(root / "copybooks"),)))
    workspace.facts_store = FactsStore(workspace, **store)
    return CobolTools(workspace)


def timeless(value: Any) -> Any:
    """*value* without the build timings, which differ run to run."""
    if isinstance(value, dict):
        return {k: timeless(v) for k, v in value.items() if "seconds" not in k}
    if isinstance(value, list):
        return [timeless(v) for v in value]
    return value


def answers(tools: CobolTools) -> list[Any]:
    return [
        timeless(tools.codebase_overview()["answer"]),
        timeless(tools.callers_of(None, "SUBPROG")["answer"]),
        timeless(tools.find_statements(verb="CALL")["answer"]),
    ]


class TestOneParse:
    def test_every_index_shares_one_parse_per_file(self, root: Path) -> None:
        tools = make_tools(root, workers=1)
        workspace = tools.workspace
        files = len(workspace.program_files())
        with patch.object(
            Workspace,
            "cached_or_parse",
            autospec=True,
            side_effect=Workspace.cached_or_parse,
        ) as parse:
            answers(tools)
        assert parse.call_count == files

    def test_store_is_made_on_first_use(self, root: Path) -> None:
        workspace = Workspace(root, ProjectConfig())
        assert workspace.facts_store is None
        store = store_for(workspace)
        assert store_for(workspace) is store
        assert store.cache_dir is None


class TestIncremental:
    def test_only_a_changed_file_is_parsed_again(self, root: Path) -> None:
        tools = make_tools(root, workers=1)
        tools.codebase_overview()
        store = tools.workspace.facts_store
        assert store.last_compute[1] == len(tools.workspace.program_files())
        target = sorted(root.glob("*.cbl"))[0]
        target.write_text(target.read_text() + "\n")
        tools.codebase_overview()
        assert store.last_compute[1] == 1

    def test_removed_file_is_dropped(self, root: Path) -> None:
        tools = make_tools(root, workers=1)
        before = tools.codebase_overview()["answer"]
        victim = sorted(root.glob("*.cbl"))[0]
        victim.unlink()
        after = tools.codebase_overview()["answer"]
        assert len(tools.workspace.facts_store._facts) == len(
            tools.workspace.program_files()
        )
        assert after != before


class TestDiskCache:
    def test_restart_answers_without_a_parse(self, root: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        first = answers(make_tools(root, workers=1, cache_dir=cache))
        assert list(cache.glob("facts-*.pickle"))
        again = make_tools(root, workers=1, cache_dir=cache)
        with patch.object(Workspace, "cached_or_parse", side_effect=AssertionError):
            assert answers(again) == first
        assert again.workspace.facts_store.last_compute == (0.0, 0)

    def test_config_change_starts_afresh(self, root: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        answers(make_tools(root, workers=1, cache_dir=cache))
        workspace = Workspace(root, ProjectConfig())  # no copybook path now
        workspace.facts_store = FactsStore(workspace, workers=1, cache_dir=cache)
        CobolTools(workspace).codebase_overview()
        assert workspace.facts_store.last_compute[1] == len(workspace.program_files())

    def test_a_bad_cache_file_is_no_cache(self, root: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        tools = make_tools(root, workers=1, cache_dir=cache)
        (path,) = [tools.workspace.facts_store._cache_file()]
        assert path is not None
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a pickle")
        expected = answers(make_tools(root, workers=1))
        assert answers(tools) == expected

    def test_default_cache_dir_is_never_under_the_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert default_cache_dir() == tmp_path / "xdg" / "cobol-parser" / "mcp"
        monkeypatch.delenv("XDG_CACHE_HOME")
        assert default_cache_dir() == Path.home() / ".cache" / "cobol-parser" / "mcp"


class TestParallel:
    def test_pool_answers_like_one_process(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sequential = answers(make_tools(root, workers=1))
        monkeypatch.setattr(facts_module, "PARALLEL_THRESHOLD", 2)
        pooled = make_tools(root, workers=2)
        with patch.object(Workspace, "cached_or_parse", side_effect=AssertionError):
            # Every parse happens in a worker process, none in this one.
            assert answers(pooled) == sequential

    def test_a_dead_worker_costs_only_its_file(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from concurrent.futures import Future

        victim = str(sorted(root.glob("*.cbl"))[0])

        class Pool:
            """In-process stand-in for the process pool; one file's worker dies."""

            def __init__(self, *args: Any, initargs: Any = (), **kwargs: Any) -> None:
                self.workspace = Workspace(root, initargs[1])

            def __enter__(self) -> Pool:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def submit(self, _call: Any, path: str) -> Future[Any]:
                future: Future[Any] = Future()
                if path == victim:
                    future.set_exception(RuntimeError("worker died"))
                else:
                    future.set_result(
                        facts_module.compute_facts(
                            self.workspace, Path(path), _builder(self.workspace)
                        )
                    )
                return future

        monkeypatch.setattr(facts_module, "PARALLEL_THRESHOLD", 2)
        monkeypatch.setattr(facts_module, "ProcessPoolExecutor", Pool)
        tools = make_tools(root, workers=2)
        overview = tools.codebase_overview()["answer"]
        assert overview["index"]["program_files"] == len(
            tools.workspace.program_files()
        )
        held = tools.workspace.facts_store._facts[victim]
        assert held.failed == "RuntimeError: worker died"
        assert (
            sum(1 for f in tools.workspace.facts_store._facts.values() if f.failed) == 1
        )


def _builder(workspace: Workspace) -> Any:
    from cobolparser.analysis.codebase import CodebaseGraphBuilder

    builder = CodebaseGraphBuilder(copybook_paths=list(workspace.config.copybook_path))
    builder.begin_build()
    return builder


class TestWarmUp:
    def test_warm_up_leaves_nothing_to_parse(self, root: Path) -> None:
        tools = make_tools(root, workers=1)
        thread = tools.workspace.facts_store.warm()
        assert thread is not None
        thread.join(timeout=120)
        with patch.object(Workspace, "cached_or_parse", side_effect=AssertionError):
            tools.codebase_overview()

    def test_pooled_warm_up(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(facts_module, "PARALLEL_THRESHOLD", 2)
        tools = make_tools(root, workers=2)
        thread = tools.workspace.facts_store.warm()
        assert thread is not None
        # A call made meanwhile waits for the warm-up instead of redoing it.
        overview = tools.codebase_overview()["answer"]
        thread.join(timeout=120)
        assert overview["index"]["program_files"] == len(
            tools.workspace.program_files()
        )

    def test_nothing_to_warm(self, root: Path) -> None:
        tools = make_tools(root, workers=1)
        tools.codebase_overview()
        thread = tools.workspace.facts_store.warm()
        assert thread is not None
        thread.join(timeout=60)
        assert tools.workspace.facts_store.last_compute[1] == len(
            tools.workspace.program_files()
        )


def test_edited_wrapper_copybook_is_reparsed(tmp_path: Path) -> None:
    """#763: a member that only COPYs another adds no line to the source map,
    so the parse must stamp it from the members the expander opened."""
    import os

    books = tmp_path / "copybooks"
    books.mkdir()
    (books / "OUTER.cpy").write_text("           COPY INNERA.\n")
    (books / "INNERA.cpy").write_text("       01 FIELD-A PIC X(5).\n")
    (books / "INNERB.cpy").write_text("       01 FIELD-B PIC X(5).\n")
    (tmp_path / "P.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY OUTER.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )
    workspace = Workspace(tmp_path, ProjectConfig(copybook_path=(str(books),)))

    def names() -> list[str]:
        return [item.name for item in workspace.program("P.cbl").ast.get_data_items()]

    assert names() == ["FIELD-A"]
    outer = books / "OUTER.cpy"
    outer.write_text("           COPY INNERB.\n")
    info = outer.stat()
    os.utime(outer, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
    assert names() == ["FIELD-B"]
