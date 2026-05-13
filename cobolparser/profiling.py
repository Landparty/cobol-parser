"""Performance profiling support for cobolparser.

ProfilerContext wraps any parse call with cProfile, tracemalloc, and
optional psutil CPU accounting. Import psutil lazily so the package remains
usable without it.
"""

from __future__ import annotations

import cProfile
import json
import pstats
import time
import tracemalloc
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_clock_s": self.wall_clock_s,
            "cpu_user_s": self.cpu_user_s,
            "cpu_system_s": self.cpu_system_s,
            "peak_memory_mb": self.peak_memory_mb,
            "prof_file": self.prof_file,
            "top_functions": [f.to_dict() for f in self.top_functions],
        }

    def to_json(self, compact: bool = False) -> str:
        if compact:
            return json.dumps(self.to_dict(), separators=(",", ":"))
        return json.dumps(self.to_dict(), indent=2)


class ProfilerContext:
    def __init__(self, top_n: int = 50, prof_output: str | None = None) -> None:
        self._top_n = top_n
        self._prof_output = prof_output
        self._profiler = cProfile.Profile()
        self._wall_start: float = 0.0
        self._cpu_before: Any = None
        self._was_tracing: bool = False
        self.result: ProfilingResult | None = None

    def __enter__(self) -> ProfilerContext:
        # Memory: start tracemalloc only if not already running
        self._was_tracing = tracemalloc.is_tracing()
        if not self._was_tracing:
            tracemalloc.start()

        self._wall_start = time.perf_counter()

        if _PSUTIL_AVAILABLE:
            self._cpu_before = _psutil.Process().cpu_times()

        self._profiler.enable()
        return self

    def __exit__(self, *_: Any) -> None:
        self._profiler.disable()
        wall_clock_s = time.perf_counter() - self._wall_start

        # Memory peak within this call
        _current, peak_bytes = tracemalloc.get_traced_memory()
        if not self._was_tracing:
            tracemalloc.stop()
        peak_memory_mb = peak_bytes / (1024 * 1024)

        # CPU user + system delta via psutil
        cpu_user_s: float | None = None
        cpu_system_s: float | None = None
        if _PSUTIL_AVAILABLE and self._cpu_before is not None:
            cpu_after = _psutil.Process().cpu_times()
            cpu_user_s = max(0.0, cpu_after.user - self._cpu_before.user)
            cpu_system_s = max(0.0, cpu_after.system - self._cpu_before.system)

        # Write .prof binary if requested
        if self._prof_output:
            self._profiler.dump_stats(self._prof_output)

        # Extract top-N functions by cumulative time from cProfile stats
        top_functions: list[FunctionProfile] = []
        if self._top_n > 0:
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
            prof_file=self._prof_output,
        )
