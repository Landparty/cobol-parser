"""Per-file resource limits for batch and scan (``cobolparser._file_limits``).

``timeout_seconds`` and ``max_file_bytes`` on ``parse_files``,
``parse_files_with_copybooks`` and ``ScanOptions``, plus the ``limits:``
section of ``cobol.yml``. The tests that start worker processes are marked
``slow`` (a spawn start costs about a second on Windows); each keeps its
timeout at 0.5 s.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from cobolparser import _file_limits
from cobolparser._file_limits import (
    oversize_reason,
    run_with_timeouts,
    timeout_reason,
    validate_limits,
)
from cobolparser.batch import BatchResult, parse_files, parse_files_with_copybooks
from cobolparser.config import ConfigError, LimitDefaults, build_config
from cobolparser.scan import ScanOptions, scan_files, scan_one

SMALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(10).
       01 WS-B PIC X(10).
       PROCEDURE DIVISION.
           MOVE WS-A TO WS-B.
           STOP RUN.
"""


def _write_small(directory: Path, name: str) -> Path:
    path = directory / f"{name}.cbl"
    path.write_text(SMALL.format(name=name), encoding="ascii")
    return path


def _write_slow(directory: Path, statements: int = 200_000) -> Path:
    """A real program that takes seconds to parse (about 6 MB, ~45 us per
    statement here), far past the 0.5 s timeouts below."""
    head = SMALL.format(name="SLOWPROG").split("           MOVE")[0]
    body = "           MOVE WS-A TO WS-B.\n" * statements
    path = directory / "SLOWPROG.cbl"
    path.write_text(head + body + "           STOP RUN.\n", encoding="ascii")
    return path


def _no_leaked_children() -> bool:
    return multiprocessing.active_children() == []


def _read_beat(beat_file: str) -> str:
    return Path(beat_file).read_text(encoding="ascii")


# Module-level so they pickle under spawn (the worker re-imports this module).


def _echo_or_sleep(value: str, beat_file: str) -> str:
    """The slow task writes a heartbeat every 50 ms for a minute: if it stops
    changing, the process running it is gone (a pid check is fooled by pid
    reuse on a busy machine)."""
    if value == "slow":
        tmp = beat_file + ".tmp"
        for beat in range(1200):
            Path(tmp).write_text(str(beat), encoding="ascii")
            os.replace(tmp, beat_file)
            time.sleep(0.05)
    return value.upper()


def _raise_on_bad(value: str) -> str:
    if value == "bad":
        raise RuntimeError("boom")
    return value.upper()


def _die_on_fatal(value: str) -> str:
    if value == "fatal":
        os._exit(3)
    return value.upper()


def _failure(index: int, reason: str) -> str:
    return f"FAILED[{index}]: {reason}"


# ---------------------------------------------------------------------------
# Validation and the size check (no processes)
# ---------------------------------------------------------------------------


class TestValidateLimits:
    def test_none_is_fine(self) -> None:
        validate_limits(None, None)
        validate_limits(0.5, 1)

    @pytest.mark.parametrize(
        "bad", [0, -1, True, "5", float("nan"), float("inf"), 1e308, 7 * 86400 + 1]
    )
    def test_bad_timeout(self, bad: object) -> None:
        with pytest.raises(ValueError, match="timeout_seconds"):
            validate_limits(bad, None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [0, -5, 1.5, True])
    def test_bad_max_bytes(self, bad: object) -> None:
        with pytest.raises(ValueError, match="max_file_bytes"):
            validate_limits(None, bad)  # type: ignore[arg-type]

    def test_public_functions_validate(self, tmp_path: Path) -> None:
        path = _write_small(tmp_path, "PROGA")
        with pytest.raises(ValueError, match="timeout_seconds"):
            parse_files([path], timeout_seconds=0)
        with pytest.raises(ValueError, match="max_file_bytes"):
            parse_files_with_copybooks([path], [], max_file_bytes=0)
        with pytest.raises(ValueError, match="max_file_bytes"):
            scan_files([path], ScanOptions(max_file_bytes=-1))

    def test_timeout_with_executor_is_refused(self, tmp_path: Path) -> None:
        path = _write_small(tmp_path, "PROGA")
        executor = ProcessPoolExecutor(max_workers=1)
        try:
            with pytest.raises(ValueError, match="executor"):
                parse_files([path], executor=executor, timeout_seconds=1)
            with pytest.raises(ValueError, match="executor"):
                scan_files([path], ScanOptions(timeout_seconds=1), executor=executor)
        finally:
            executor.shutdown()


class TestOversize:
    def test_reason_text(self, tmp_path: Path) -> None:
        path = tmp_path / "f.cbl"
        path.write_bytes(b"x" * 100)
        assert oversize_reason(str(path), None) is None
        assert oversize_reason(str(path), 100) is None
        assert oversize_reason(str(path), 99) == (
            "skipped: file is 100 bytes, over the max_file_bytes limit of 99"
        )

    def test_missing_file_is_left_to_the_read(self, tmp_path: Path) -> None:
        assert oversize_reason(str(tmp_path / "nope.cbl"), 1) is None

    def test_timeout_reason_text(self) -> None:
        assert timeout_reason(0.5).startswith("timed out after 0.5 s")

    def test_parse_files_skips_oversize(self, tmp_path: Path) -> None:
        small = _write_small(tmp_path, "PROGA")
        big = _write_slow(tmp_path, statements=50)
        limit = small.stat().st_size
        results = parse_files([big, small], workers=1, max_file_bytes=limit)
        assert results[0].result is None
        assert results[0].read_error is not None
        assert results[0].read_error.startswith("skipped: file is ")
        assert f"limit of {limit}" in results[0].read_error
        assert results[1].read_error is None and results[1].result is not None

    def test_parse_files_with_copybooks_skips_oversize(self, tmp_path: Path) -> None:
        small = _write_small(tmp_path, "PROGA")
        big = _write_slow(tmp_path, statements=50)
        results = parse_files_with_copybooks(
            [small, big], [str(tmp_path)], max_file_bytes=small.stat().st_size
        )
        assert results[0].result is not None
        assert results[1].result is None
        assert (results[1].read_error or "").startswith("skipped:")

    def test_scan_skips_oversize_even_from_cache(self, tmp_path: Path) -> None:
        small = _write_small(tmp_path, "PROGA")
        big = _write_slow(tmp_path, statements=50)
        cache = str(tmp_path / "cache")
        # Warm the cache with no limit: the big file's report is stored.
        first = scan_files([big, small], ScanOptions(cache_dir=cache), workers=1)
        assert not first.failed_files
        limited = ScanOptions(cache_dir=cache, max_file_bytes=small.stat().st_size)
        assert limited.cache_settings() == ScanOptions(cache_dir=cache).cache_settings()
        report = scan_files([big, small], limited, workers=1)
        assert [f.path for f in report.failed_files] == [str(big)]
        assert (report.failed_files[0].error or "").startswith("skipped:")
        assert report.ok_files[0].from_cache
        assert report.to_dict()["summary"]["file_count"] == 2
        assert scan_one(str(big), limited).error == report.failed_files[0].error


class TestDefaultsUnchanged:
    def test_no_limit_never_starts_a_timeout_pool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("run_with_timeouts used without a timeout")

        monkeypatch.setattr("cobolparser.batch.run_with_timeouts", refuse)
        monkeypatch.setattr(_file_limits, "run_with_timeouts", refuse)
        paths = [_write_small(tmp_path, n) for n in ("PROGA", "PROGB")]
        batch = parse_files(paths, workers=1)
        assert [r.result.ast.program_name for r in batch if r.result] == [
            "PROGA",
            "PROGB",
        ]
        with_cpy = parse_files_with_copybooks(paths, [str(tmp_path)])
        assert all(r.result is not None for r in with_cpy)
        report = scan_files(paths, workers=1)
        assert len(report.ok_files) == 2
        assert _no_leaked_children()

    def test_options_default_to_none(self) -> None:
        options = ScanOptions()
        assert options.timeout_seconds is None
        assert options.max_file_bytes is None


# ---------------------------------------------------------------------------
# The timeout pool itself
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRunWithTimeouts:
    def test_overrun_is_terminated_and_the_rest_complete(self, tmp_path: Path) -> None:
        beat_file = str(tmp_path / "slow.beat")
        tasks = [(v, beat_file) for v in ("a", "slow", "b", "c")]
        started = time.monotonic()
        results = run_with_timeouts(
            _echo_or_sleep,
            tasks,
            timeout_seconds=0.5,
            workers=2,
            failure=_failure,
        )
        assert time.monotonic() - started < 30
        assert results[0] == "A"
        assert results[1] == f"FAILED[1]: {timeout_reason(0.5)}"
        assert results[2:] == ["B", "C"]
        # The worker that overran was terminated and reaped, not leaked: its
        # heartbeat has stopped, and no child process is left.
        assert _no_leaked_children()
        beat = _read_beat(beat_file)
        time.sleep(0.5)
        assert _read_beat(beat_file) == beat

    def test_one_worker_carries_on_after_a_timeout(self, tmp_path: Path) -> None:
        beat_file = str(tmp_path / "slow.beat")
        results = run_with_timeouts(
            _echo_or_sleep,
            [("slow", beat_file), ("a", beat_file)],
            timeout_seconds=0.5,
            workers=1,
            failure=_failure,
        )
        assert results[0].startswith("FAILED[0]: timed out after 0.5 s")
        assert results[1] == "A"
        assert _no_leaked_children()

    def test_exception_and_dead_worker_are_per_task(self) -> None:
        raised = run_with_timeouts(
            _raise_on_bad,
            [("a",), ("bad",), ("b",)],
            timeout_seconds=30,
            workers=1,
            failure=_failure,
        )
        assert raised == ["A", "FAILED[1]: RuntimeError: boom", "B"]
        died = run_with_timeouts(
            _die_on_fatal,
            [("fatal",), ("a",)],
            timeout_seconds=30,
            workers=1,
            failure=_failure,
        )
        assert died[0].startswith("FAILED[0]: the worker process exited unexpectedly")
        assert died[1] == "A"
        assert _no_leaked_children()

    def test_worker_that_replies_then_dies_is_replaced(self, monkeypatch) -> None:
        # Kill the worker right after it sends its first result, before the
        # parent sees its sentinel: the parent must reap it rather than hand
        # the next file to a dead process (a BrokenPipeError used to abort
        # the whole run).
        real_wait = _file_limits.wait
        killed: list[int] = []

        def wait_then_kill(handles, timeout=None):
            got = real_wait(handles, timeout=timeout)
            for handle in got:
                if isinstance(handle, int) or not hasattr(handle, "poll"):
                    continue
                for worker in created:
                    if worker.conn is handle and worker.task is not None:
                        if not killed:
                            worker.process.kill()
                            worker.process.join()
                            killed.append(worker.process.pid)
                        return [h for h in got if h is handle]
            return got

        created: list[_file_limits._Worker] = []
        real_init = _file_limits._Worker.__init__

        def recording_init(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            created.append(self)

        monkeypatch.setattr(_file_limits, "wait", wait_then_kill)
        monkeypatch.setattr(_file_limits._Worker, "__init__", recording_init)
        results = run_with_timeouts(
            _raise_on_bad,
            [("a",), ("b",), ("c",)],
            timeout_seconds=30,
            workers=1,
            failure=_failure,
        )
        assert results == ["A", "B", "C"]
        assert killed and len(created) == 2
        assert _no_leaked_children()

    def test_idle_worker_that_died_gets_no_task(self, monkeypatch) -> None:
        # The hand-out finds a dead idle worker (the send fails): the file
        # goes back in line and runs in a replacement.
        created: list[_file_limits._Worker] = []
        real_init = _file_limits._Worker.__init__

        def recording_init(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            if not created:

                def broken_send(_obj: object) -> None:
                    raise BrokenPipeError("worker is gone")

                self.conn.send = broken_send  # type: ignore[method-assign]
            created.append(self)

        monkeypatch.setattr(_file_limits._Worker, "__init__", recording_init)
        results = run_with_timeouts(
            _raise_on_bad,
            [("a",), ("b",)],
            timeout_seconds=30,
            workers=1,
            failure=_failure,
        )
        assert results == ["A", "B"]
        assert len(created) == 2
        assert _no_leaked_children()

    def test_no_tasks(self) -> None:
        assert (
            run_with_timeouts(
                _raise_on_bad, [], timeout_seconds=1, workers=1, failure=_failure
            )
            == []
        )


# ---------------------------------------------------------------------------
# End to end: a genuinely slow input through every public entry point
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestTimeoutEndToEnd:
    def test_parse_files(self, tmp_path: Path) -> None:
        fast_a = _write_small(tmp_path, "PROGA")
        slow = _write_slow(tmp_path)
        fast_b = _write_small(tmp_path, "PROGB")
        results = parse_files([fast_a, slow, fast_b], workers=2, timeout_seconds=0.5)
        assert [r.path for r in results] == [fast_a, slow, fast_b]
        assert results[1].result is None
        assert results[1].read_error == timeout_reason(0.5)
        for ok in (results[0], results[2]):
            assert isinstance(ok, BatchResult)
            assert ok.read_error is None
            assert ok.result is not None and ok.result.ast is not None
        assert results[2].result.ast.program_name == "PROGB"
        assert _no_leaked_children()

    def test_parse_files_with_copybooks(self, tmp_path: Path) -> None:
        slow = _write_slow(tmp_path)
        fast = _write_small(tmp_path, "PROGA")
        results = parse_files_with_copybooks(
            [slow, fast], [str(tmp_path)], timeout_seconds=0.5
        )
        assert results[0].read_error == timeout_reason(0.5)
        assert results[1].result is not None
        assert results[1].result.expansion_source_map is not None
        assert _no_leaked_children()

    def test_scan_files(self, tmp_path: Path) -> None:
        fast_a = _write_small(tmp_path, "PROGA")
        slow = _write_slow(tmp_path)
        fast_b = _write_small(tmp_path, "PROGB")
        report = scan_files(
            [fast_a, slow, fast_b],
            ScanOptions(timeout_seconds=0.5, analyzers=("health", "lint")),
            workers=1,
        )
        assert [f.path for f in report.failed_files] == [str(slow)]
        assert report.failed_files[0].error == timeout_reason(0.5)
        assert [f.units[0].program_name for f in report.ok_files] == [
            "PROGA",
            "PROGB",
        ]
        assert "health" in report.ok_files[0].units[0].reports
        summary = report.to_dict()["summary"]
        assert summary["file_count"] == 3 and summary["failed_file_count"] == 1
        assert _no_leaked_children()


# ---------------------------------------------------------------------------
# The worker-side code, run in this process (coverage cannot see a child)
# ---------------------------------------------------------------------------


def _unpicklable(value: str) -> object:
    return lambda: value


def _failing_warmup() -> None:
    raise RuntimeError("warm-up trouble is ignored")


class TestWorkerSideInProcess:
    def test_worker_loop(self) -> None:
        parent, child = multiprocessing.Pipe(duplex=True)
        for message in (("a",), ("bad",), None):
            parent.send(message)
        _file_limits._worker_main(child, _raise_on_bad, _failing_warmup, ())
        replies = [parent.recv() for _ in range(3)]
        assert replies == [
            ("ready",),
            ("ok", "A"),
            ("error", "RuntimeError: boom"),
        ]
        parent.close()
        child.close()

    def test_unpicklable_result_reply(self) -> None:
        parent, child = multiprocessing.Pipe(duplex=True)
        parent.send(("x",))
        parent.send(None)
        _file_limits._worker_main(child, _unpicklable, None, ())
        assert parent.recv() == ("ready",)
        kind, text = parent.recv()
        assert kind == "error" and text.startswith("result could not be sent back")

    def test_warmups_and_worker_state(self, tmp_path: Path) -> None:
        from cobolparser import batch
        from cobolparser.plugins.core import DialectType, ErrorRecoveryMode
        from cobolparser.scan import _warm_scan_worker

        batch._warm_parser(
            ErrorRecoveryMode.COLLECT_ALL, DialectType.IBM_ENTERPRISE, False, True
        )
        job = batch._CopybookJob(
            copybook_paths=(str(tmp_path),),
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            dialect=DialectType.IBM_ENTERPRISE,
            encoding=None,
            errors="replace",
            max_nesting_depth=100,
            copybook_cache_size=16,
            enable_profiling=False,
            top_n=5,
            prof_output=None,
            debug_lines=False,
            max_file_bytes=None,
        )
        batch._warm_copybook_worker(job)
        state = batch._worker_copybook_state(job)
        assert batch._worker_copybook_state(job) is state
        path = _write_small(tmp_path, "PROGA")
        result = batch._parse_one_with_copybooks(str(path), "PROGA.prof", job)
        assert result.result is not None and result.read_error is None
        _warm_scan_worker(ScanOptions(analyzers=("health", "lint")))
        _warm_scan_worker(ScanOptions(error_recovery=ErrorRecoveryMode.FAIL_FAST))


# ---------------------------------------------------------------------------
# cobol.yml `limits:`
# ---------------------------------------------------------------------------


class TestConfigLimits:
    def test_absent_is_none(self, tmp_path: Path) -> None:
        config = build_config({}, tmp_path / "cobol.yml")
        assert config.limits == LimitDefaults()

    def test_values(self, tmp_path: Path) -> None:
        config = build_config(
            {"limits": {"timeout_seconds": 30, "max_file_bytes": 1000}},
            tmp_path / "cobol.yml",
        )
        assert config.limits.timeout_seconds == 30.0
        assert config.limits.max_file_bytes == 1000

    @pytest.mark.parametrize(
        "section",
        [
            {"timeout_seconds": 0},
            {"timeout_seconds": "10"},
            {"timeout_seconds": True},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": 1e308},
            {"max_file_bytes": 0},
            {"max_file_bytes": 1.5},
            {"max_bytes": 10},
        ],
    )
    def test_rejected(self, tmp_path: Path, section: dict[str, object]) -> None:
        with pytest.raises(ConfigError, match="limits"):
            build_config({"limits": section}, tmp_path / "cobol.yml")
