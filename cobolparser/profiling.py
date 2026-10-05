"""Performance profiling support for cobolparser.

ProfilerContext wraps any parse call with cProfile, tracemalloc, and
optional psutil CPU accounting. Import psutil lazily so the package remains
usable without it.
"""

from __future__ import annotations

import cProfile
import json
import os
import pstats
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil as _psutil  # type: ignore[import-untyped]

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _psutil: Any = None  # type: ignore[no-redef]
    _PSUTIL_AVAILABLE = False


@dataclass
class FunctionProfile:
    function: str  # "filename:lineno(funcname)"
    calls: int
    total_time_s: float  # time in body only (excluding callees)
    cumul_time_s: float  # cumulative time including callees
    per_call_total_s: float
    per_call_cumul_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "calls": self.calls,
            "total_time_s": self.total_time_s,
            "cumul_time_s": self.cumul_time_s,
            "per_call_total_s": self.per_call_total_s,
            "per_call_cumul_s": self.per_call_cumul_s,
        }


@dataclass
class ProfilingResult:
    wall_clock_s: float
    cpu_user_s: float | None  # None when psutil is not installed
    cpu_system_s: float | None  # None when psutil is not installed
    peak_memory_mb: float  # tracemalloc peak allocation within the profiled call
    top_functions: list[FunctionProfile]
    prof_file: str | None  # path to .prof binary, or None
    # False only when an outer tracemalloc session was already running and
    # the profiled call never rose above that session's earlier peak: the
    # call's own peak is then unknowable without resetting the outer
    # session's peak, so peak_memory_mb is an upper bound (see __exit__).
    peak_memory_exact: bool = True
    # False when cProfile could not run because another profiler (an outer
    # ProfilerContext, a bare cProfile, or any other sys.setprofile /
    # sys.monitoring PROFILER_ID tool) was already active: top_functions is
    # then empty and no .prof file is written, while wall-clock, CPU and
    # memory are still measured. ``caveats`` says why.
    function_profile_available: bool = True
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_clock_s": self.wall_clock_s,
            "cpu_user_s": self.cpu_user_s,
            "cpu_system_s": self.cpu_system_s,
            "peak_memory_mb": self.peak_memory_mb,
            "peak_memory_exact": self.peak_memory_exact,
            "function_profile_available": self.function_profile_available,
            "caveats": list(self.caveats),
            "prof_file": self.prof_file,
            "top_functions": [f.to_dict() for f in self.top_functions],
        }

    def to_json(self, compact: bool = False) -> str:
        if compact:
            return json.dumps(self.to_dict(), separators=(",", ":"))
        return json.dumps(self.to_dict(), indent=2)


_PROFILER_BUSY_CAVEAT = (
    "another profiler was already active (a nested ProfilerContext, cProfile, "
    "or another profiling tool), so per-function profiling was skipped; "
    "wall-clock, CPU and memory figures are still this call's own"
)


def _profiler_already_active() -> bool:
    """Whether a profiling hook is already installed in this thread.

    On 3.11 cProfile installs itself with ``sys.setprofile``; from 3.12 it
    claims ``sys.monitoring``'s PROFILER_ID instead, and a second
    ``Profile.enable()`` raises ``ValueError``.  Either way a second profiler
    cannot run: on 3.11 it silently *replaces* the first, which leaves the
    outer profile holding nothing but its own ``__enter__``.
    """
    if sys.getprofile() is not None:
        return True
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is not None:
        return monitoring.get_tool(monitoring.PROFILER_ID) is not None
    return False


class ProfilerContext:
    def __init__(self, top_n: int = 50, prof_output: str | None = None) -> None:
        self._top_n = top_n
        self._prof_output = prof_output
        self._profiler = cProfile.Profile()
        self._wall_start: float = 0.0
        self._cpu_before: Any = None
        self._was_tracing: bool = False
        self._traced_before: tuple[int, int] = (0, 0)
        self._profiling: bool = False
        self.result: ProfilingResult | None = None

    def __enter__(self) -> ProfilerContext:
        # Memory: start tracemalloc only if not already running
        self._was_tracing = tracemalloc.is_tracing()
        if not self._was_tracing:
            tracemalloc.start()
        # (current, peak) at entry. A fresh session starts at (0, 0); an
        # outer one already holds memory and a peak that are not this call's.
        self._traced_before = tracemalloc.get_traced_memory()

        self._wall_start = time.perf_counter()

        if _PSUTIL_AVAILABLE:
            self._cpu_before = _psutil.Process().cpu_times()

        self._profiling = False
        if not _profiler_already_active():
            try:
                self._profiler.enable()
                self._profiling = True
            except ValueError:
                # 3.12+: "Another profiling tool is already active" -- a tool
                # the check above could not see. Degrade rather than fail.
                pass
            except BaseException:
                # __exit__ never runs when __enter__ raises: do not leak the
                # tracemalloc session this call started.
                if not self._was_tracing:
                    tracemalloc.stop()
                raise
        return self

    def __exit__(self, *_: Any) -> None:
        if self._profiling:
            self._profiler.disable()
        wall_clock_s = time.perf_counter() - self._wall_start

        # Memory peak within this call, above what was traced at entry.
        # tracemalloc's peak is process-wide since the session started (or
        # was last reset); under an outer session it is that session's
        # all-time peak, which is not this call's. reset_peak() would make
        # it exact but destroy the outer session's peak, so it is not used:
        # a peak that rose during the call was set by the call (exact);
        # one that did not means the call stayed at or under the earlier
        # peak, which is then reported as an upper bound.
        _current, peak_bytes = tracemalloc.get_traced_memory()
        if not self._was_tracing:
            tracemalloc.stop()
        current_before, peak_before = self._traced_before
        peak_memory_exact = peak_bytes > peak_before or not self._was_tracing
        peak_memory_mb = max(0, peak_bytes - current_before) / (1024 * 1024)

        # CPU user + system delta via psutil
        cpu_user_s: float | None = None
        cpu_system_s: float | None = None
        if _PSUTIL_AVAILABLE and self._cpu_before is not None:
            cpu_after = _psutil.Process().cpu_times()
            cpu_user_s = max(0.0, cpu_after.user - self._cpu_before.user)
            cpu_system_s = max(0.0, cpu_after.system - self._cpu_before.system)

        # Write .prof binary if requested. dump_stats() raises FileNotFoundError
        # uncaught if its parent directory doesn't exist yet -- create it first,
        # matching the batch-parsing path's os.makedirs(..., exist_ok=True).
        if self._prof_output and self._profiling:
            parent = os.path.dirname(self._prof_output)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._profiler.dump_stats(self._prof_output)

        # Extract top-N functions by cumulative time from cProfile stats
        top_functions: list[FunctionProfile] = []
        if self._top_n > 0 and self._profiling:
            stats = pstats.Stats(self._profiler)
            # stats.stats: {(file, lineno, name): (cc, nc, tt, ct, callers)}
            sorted_entries = sorted(
                stats.stats.items(),  # type: ignore[attr-defined]
                key=lambda kv: kv[1][3],  # ct = cumulative time
                reverse=True,
            )[: self._top_n]
            for (filename, lineno, funcname), (cc, nc, tt, ct, _) in sorted_entries:
                top_functions.append(
                    FunctionProfile(
                        function=f"{filename}:{lineno}({funcname})",
                        calls=nc,
                        total_time_s=tt,
                        cumul_time_s=ct,
                        per_call_total_s=tt / nc if nc else 0.0,
                        per_call_cumul_s=ct / cc if cc else 0.0,
                    )
                )

        self.result = ProfilingResult(
            wall_clock_s=wall_clock_s,
            cpu_user_s=cpu_user_s,
            cpu_system_s=cpu_system_s,
            peak_memory_mb=peak_memory_mb,
            top_functions=top_functions,
            prof_file=self._prof_output if self._profiling else None,
            peak_memory_exact=peak_memory_exact,
            function_profile_available=self._profiling,
            caveats=[] if self._profiling else [_PROFILER_BUSY_CAVEAT],
        )
