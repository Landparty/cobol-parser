"""Per-file resource limits for ``batch.py`` and ``scan.py``.

Both modules isolate *faults* per file -- an exception costs one entry --
but without a cap one pathological or hostile input can still stall a whole
portfolio run: a file that takes an hour to parse holds its worker (or the
only process) for that hour. Two opt-in limits close that:

* ``max_file_bytes`` -- a file larger than this on disk is never read; it
  becomes that file's failure (:func:`oversize_reason`).
* ``timeout_seconds`` -- a file whose work runs longer than this is
  abandoned and becomes that file's failure (:func:`run_with_timeouts`).

WHY A PROCESS, EVEN FOR ONE WORKER. A Python thread cannot be killed, and
neither can a ``ProcessPoolExecutor`` worker without breaking the pool, so
the only way to *stop* a runaway parse is to run it in a process this
module owns and terminate that process. :func:`run_with_timeouts` keeps a
small pool of long-lived worker processes (one per ``workers``), hands each
one file at a time, and when a file overruns its deadline terminates that
worker (``terminate()``, then ``kill()`` if it is still alive, then
``join()`` -- it is reaped, never leaked) and starts a replacement. It uses
the platform's default start method, so it works under Windows (and macOS)
spawn as well as Linux fork; everything sent to a worker is a module-level
function plus picklable arguments, the same rule both callers already obey.

The clock for a file starts when it is handed to a worker that has
already started up and run its warm-up, so interpreter start-up and the
first imports (seconds under spawn) never count against the first file.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from collections import deque
from collections.abc import Callable, Sequence
from multiprocessing.connection import Connection, wait
from typing import Any, TypeVar

R = TypeVar("R")

#: How long a worker gets to exit after being asked to, or after
#: ``terminate()``, before it is killed outright.
_EXIT_GRACE_SECONDS = 2.0


def validate_limits(timeout_seconds: float | None, max_file_bytes: int | None) -> None:
    """Raise ``ValueError`` for a limit that cannot mean anything."""
    if timeout_seconds is not None:
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be a number of seconds or None")
        if not timeout_seconds > 0:
            raise ValueError("timeout_seconds must be > 0 or None")
    if max_file_bytes is not None:
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int):
            raise ValueError("max_file_bytes must be an integer or None")
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be >= 1 or None")


def oversize_reason(path: str, max_file_bytes: int | None) -> str | None:
    """Why *path* is skipped under *max_file_bytes*, or ``None`` to go ahead.

    Checked with ``os.stat`` before the file is opened, so an oversize file
    is never read into memory. A file that cannot be stat'ed is not judged
    here: the read that follows reports it the usual way.
    """
    if max_file_bytes is None:
        return None
    try:
        size = os.stat(path).st_size
    except OSError:
        return None
    if size <= max_file_bytes:
        return None
    return (
        f"skipped: file is {size} bytes, over the max_file_bytes limit "
        f"of {max_file_bytes}"
    )


def timeout_reason(timeout_seconds: float) -> str:
    """The per-file failure text for a file that overran its deadline."""
    return (
        f"timed out after {timeout_seconds:g} s " "(the worker process was terminated)"
    )


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _worker_main(
    conn: Connection,
    func: Callable[..., Any],
    warmup: Callable[..., Any] | None,
    warmup_args: tuple[Any, ...],
) -> None:
    """A worker's loop: warm up, say ready, then run one task at a time.

    Module-level so it pickles under spawn. *func* arrives with the process
    arguments, so its module is imported before ``ready`` (unpickled with
    the first task, that import was charged to the first file's deadline).
    Each task message is just the argument tuple. Every message back is a
    tuple: ``("ready",)``, ``("ok", value)`` or ``("error", "<ExcType>:
    <msg>")``.
    """
    if warmup is not None:
        try:
            warmup(*warmup_args)
        except Exception:  # noqa: BLE001 -- warm-up is best effort
            pass
    conn.send(("ready",))
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            return
        if message is None:
            return
        args = message
        try:
            reply: tuple[Any, ...] = ("ok", func(*args))
        except Exception as exc:  # noqa: BLE001 -- reported per file
            reply = ("error", f"{type(exc).__name__}: {exc}")
        try:
            conn.send(reply)
        except Exception as exc:  # noqa: BLE001 -- e.g. a result that won't pickle
            # pickle runs before anything is written, so the pipe is clean.
            conn.send(
                (
                    "error",
                    f"result could not be sent back: {type(exc).__name__}: {exc}",
                )
            )


# ---------------------------------------------------------------------------
# Parent side
# ---------------------------------------------------------------------------


class _Worker:
    """One worker process and the task it is running, if any."""

    def __init__(
        self,
        ctx: Any,
        func: Callable[..., Any],
        warmup: Callable[..., Any] | None,
        warmup_args: tuple[Any, ...],
    ) -> None:
        parent_conn, child_conn = ctx.Pipe(duplex=True)
        self.conn: Connection = parent_conn
        self.process = ctx.Process(
            target=_worker_main,
            args=(child_conn, func, warmup, warmup_args),
            daemon=True,
        )
        self.process.start()
        child_conn.close()
        self.ready = False
        self.task: int | None = None
        self.deadline = 0.0

    def stop(self, *, graceful: bool) -> None:
        """End the process and reap it; never leaves it running."""
        if graceful and self.process.is_alive():
            try:
                self.conn.send(None)
            except (OSError, ValueError):
                pass
            self.process.join(_EXIT_GRACE_SECONDS)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(_EXIT_GRACE_SECONDS)
        if self.process.is_alive():  # pragma: no cover -- terminate() ignored
            self.process.kill()
            self.process.join()
        self.conn.close()
        self.process.close()


def run_with_timeouts(
    func: Callable[..., R],
    tasks: Sequence[tuple[Any, ...]],
    *,
    timeout_seconds: float,
    workers: int,
    failure: Callable[[int, str], R],
    warmup: Callable[..., Any] | None = None,
    warmup_args: tuple[Any, ...] = (),
) -> list[R]:
    """``[func(*t) for t in tasks]``, each in a worker process under a deadline.

    Args:
        func: A module-level function (it is pickled by reference).
        tasks: One argument tuple per file; results come back in this order.
        timeout_seconds: Wall-clock budget per task, from hand-off.
        workers: Worker processes to run (capped at ``len(tasks)``).
        failure: Builds the result for task ``i`` that did not produce one,
            from a reason string: a timeout, an exception that escaped
            *func*, or a worker that died. Runs in the calling process.
        warmup: Optional module-level function each worker runs once before
            taking work, so lazy imports are not charged to the first file.
        warmup_args: Its arguments.

    Raises:
        RuntimeError: A worker process died before it finished starting up
            (an environment problem, not a per-file one).
    """
    results: list[Any] = [None] * len(tasks)
    if not tasks:
        return []
    ctx = multiprocessing.get_context()
    pending: deque[int] = deque(range(len(tasks)))
    remaining = len(tasks)
    pool: list[_Worker] = []

    def replace(worker: _Worker) -> None:
        """Reap a dead or overrunning worker; start another only if there
        is still work to hand out (the others hold the rest)."""
        worker.stop(graceful=False)
        if pending:
            pool[pool.index(worker)] = _Worker(ctx, func, warmup, warmup_args)
        else:
            pool.remove(worker)

    def finish(worker: _Worker, value: Any) -> None:
        nonlocal remaining
        assert worker.task is not None
        results[worker.task] = value
        worker.task = None
        remaining -= 1

    try:
        for _ in range(max(1, min(workers, len(tasks)))):
            pool.append(_Worker(ctx, func, warmup, warmup_args))

        while remaining:
            for worker in pool:
                if worker.ready and worker.task is None and pending:
                    index = pending.popleft()
                    worker.conn.send(tasks[index])
                    worker.task = index
                    worker.deadline = time.monotonic() + timeout_seconds

            busy = [w.deadline for w in pool if w.task is not None]
            wait_for = max(0.0, min(busy) - time.monotonic()) if busy else None
            handles: list[Any] = [w.conn for w in pool]
            handles += [w.process.sentinel for w in pool]
            ready = set(wait(handles, timeout=wait_for))

            for worker in list(pool):
                exited = worker.process.sentinel in ready
                if worker.conn in ready or (exited and worker.conn.poll()):
                    try:
                        message = worker.conn.recv()
                    except (EOFError, OSError):
                        message = None
                    if message is not None:
                        if message[0] == "ready":
                            worker.ready = True
                        elif worker.task is not None:
                            if message[0] == "ok":
                                finish(worker, message[1])
                            else:
                                finish(worker, failure(worker.task, message[1]))
                        continue
                    exited = True
                if exited:
                    worker.process.join(_EXIT_GRACE_SECONDS)
                    code = worker.process.exitcode
                    if not worker.ready:
                        raise RuntimeError(
                            "a worker process for the per-file timeout exited "
                            f"while starting up (exit code {code})"
                        )
                    if worker.task is not None:
                        finish(
                            worker,
                            failure(
                                worker.task,
                                "the worker process exited unexpectedly "
                                f"(exit code {code})",
                            ),
                        )
                    replace(worker)

            now = time.monotonic()
            for worker in list(pool):
                if worker.task is not None and worker.deadline <= now:
                    finish(
                        worker, failure(worker.task, timeout_reason(timeout_seconds))
                    )
                    replace(worker)
    finally:
        for worker in pool:
            worker.stop(graceful=True)
    return results
