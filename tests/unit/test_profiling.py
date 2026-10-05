"""Unit tests for cobolparser.profiling module."""

from __future__ import annotations

import json
import os
import time

import pytest

from cobolparser.profiling import FunctionProfile, ProfilerContext, ProfilingResult


def test_function_profile_to_dict():
    fp = FunctionProfile(
        function="parser.py:100(parse)",
        calls=3,
        total_time_s=0.01,
        cumul_time_s=0.05,
        per_call_total_s=0.003_333,
        per_call_cumul_s=0.016_667,
    )
    d = fp.to_dict()
    assert d["function"] == "parser.py:100(parse)"
    assert d["calls"] == 3
    assert d["total_time_s"] == pytest.approx(0.01)
    assert d["cumul_time_s"] == pytest.approx(0.05)
    assert d["per_call_total_s"] == pytest.approx(0.003_333)
    assert d["per_call_cumul_s"] == pytest.approx(0.016_667)


def test_profiling_result_to_dict_with_psutil_values():
    fp = FunctionProfile("f.py:1(fn)", 1, 0.01, 0.05, 0.01, 0.05)
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=0.08,
        cpu_system_s=0.02,
        peak_memory_mb=5.0,
        top_functions=[fp],
        prof_file=None,
    )
    d = result.to_dict()
    assert d["wall_clock_s"] == pytest.approx(0.1)
    assert d["cpu_user_s"] == pytest.approx(0.08)
    assert d["cpu_system_s"] == pytest.approx(0.02)
    assert d["peak_memory_mb"] == pytest.approx(5.0)
    assert d["prof_file"] is None
    assert len(d["top_functions"]) == 1
    assert d["top_functions"][0]["function"] == "f.py:1(fn)"


def test_profiling_result_to_dict_none_cpu():
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=None,
        cpu_system_s=None,
        peak_memory_mb=3.0,
        top_functions=[],
        prof_file=None,
    )
    d = result.to_dict()
    assert d["cpu_user_s"] is None
    assert d["cpu_system_s"] is None


def test_profiling_result_to_json_valid():
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=None,
        cpu_system_s=None,
        peak_memory_mb=3.0,
        top_functions=[],
        prof_file=None,
    )
    parsed = json.loads(result.to_json())
    assert parsed["wall_clock_s"] == pytest.approx(0.1)
    assert parsed["cpu_user_s"] is None


def test_profiling_result_to_json_compact():
    result = ProfilingResult(0.1, None, None, 1.0, [], None)
    compact = result.to_json(compact=True)
    pretty = result.to_json(compact=False)
    assert "\n" not in compact
    assert len(compact) < len(pretty)


def test_profiling_result_prof_file_in_dict(tmp_path):
    prof_path = str(tmp_path / "out.prof")
    result = ProfilingResult(0.1, None, None, 1.0, [], prof_file=prof_path)
    assert result.to_dict()["prof_file"] == prof_path


def test_profiler_context_produces_result():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        _ = sum(range(10_000))
    assert ctx.result is not None


def test_profiler_context_wall_clock_positive():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        time.sleep(0.01)
    assert ctx.result.wall_clock_s >= 0.005


def test_profiler_context_peak_memory_non_negative():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        _ = list(range(1_000))
    assert ctx.result.peak_memory_mb >= 0.0


def test_profiler_context_top_n_respected():
    ctx = ProfilerContext(top_n=3)
    with ctx:
        _ = sum(range(100_000))
    assert len(ctx.result.top_functions) <= 3


def test_profiler_context_top_n_zero_gives_empty():
    ctx = ProfilerContext(top_n=0)
    with ctx:
        _ = sum(range(1_000))
    assert ctx.result.top_functions == []


def test_profiler_context_function_profile_fields():
    ctx = ProfilerContext(top_n=50)
    with ctx:
        _ = [x * 2 for x in range(5_000)]
    assert ctx.result.top_functions, "expected at least one profiled function"
    fp = ctx.result.top_functions[0]
    assert fp.calls >= 1
    assert fp.cumul_time_s >= 0.0
    assert fp.total_time_s >= 0.0
    assert "(" in fp.function and ")" in fp.function


def test_profiler_context_writes_prof_file(tmp_path):
    prof_path = str(tmp_path / "test.prof")
    ctx = ProfilerContext(top_n=5, prof_output=prof_path)
    with ctx:
        _ = sum(range(1_000))
    assert os.path.exists(prof_path)
    assert ctx.result.prof_file == prof_path


def test_profiler_context_no_prof_file_by_default():
    ctx = ProfilerContext(top_n=5)
    with ctx:
        pass
    assert ctx.result.prof_file is None


def test_profiler_context_nested_tracemalloc_safe():
    """ProfilerContext must not stop an outer tracemalloc session."""
    import tracemalloc

    tracemalloc.start()
    try:
        ctx = ProfilerContext(top_n=5)
        with ctx:
            _ = list(range(100))
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


# -- Nested profilers (issue #274 item 5) ---------------------------------------


def _work() -> int:
    return sum(i * i for i in range(20000))


def test_nested_profiler_context_keeps_outer_profile_intact():
    """An inner context must not replace (3.11) or crash on (3.12+) the outer."""
    import tracemalloc

    with ProfilerContext(top_n=50) as outer:
        with ProfilerContext(top_n=50) as inner:
            _work()
        # The inner context must not stop the session the outer started.
        assert tracemalloc.is_tracing()
        _work()
    assert not tracemalloc.is_tracing()

    names = [f.function for f in outer.result.top_functions]
    assert any("(_work)" in n for n in names)
    assert outer.result.function_profile_available is True
    assert outer.result.caveats == []

    # The inner one is degraded, and says so, but still measures the call.
    assert inner.result.function_profile_available is False
    assert inner.result.top_functions == []
    assert inner.result.prof_file is None
    assert inner.result.wall_clock_s > 0
    assert inner.result.peak_memory_mb >= 0
    assert "another profiler was already active" in inner.result.caveats[0]
    d = inner.result.to_dict()
    assert d["function_profile_available"] is False
    assert d["caveats"] == inner.result.caveats


def test_profiler_context_under_bare_cprofile_is_degraded(tmp_path):
    import cProfile
    import tracemalloc

    prof_path = str(tmp_path / "inner.prof")
    outer = cProfile.Profile()
    outer.enable()
    try:
        with ProfilerContext(top_n=5, prof_output=prof_path) as ctx:
            _work()
    finally:
        outer.disable()
    assert ctx.result.function_profile_available is False
    assert not (tmp_path / "inner.prof").exists()
    assert not tracemalloc.is_tracing()


def test_enable_value_error_degrades_instead_of_raising(monkeypatch):
    import tracemalloc

    from cobolparser import profiling

    monkeypatch.setattr(profiling, "_profiler_already_active", lambda: False)
    ctx = ProfilerContext(top_n=5)

    class _Busy:
        def enable(self):
            raise ValueError("Another profiling tool is already active")

        def disable(self):  # pragma: no cover - must not be called
            raise AssertionError("disable() on a profiler never enabled")

    ctx._profiler = _Busy()  # type: ignore[assignment]
    with ctx:
        _work()
    assert ctx.result.function_profile_available is False
    assert not tracemalloc.is_tracing()


def test_enter_failure_does_not_leak_tracemalloc(monkeypatch):
    import tracemalloc

    from cobolparser import profiling

    monkeypatch.setattr(profiling, "_profiler_already_active", lambda: False)
    ctx = ProfilerContext(top_n=5)

    class _Broken:
        def enable(self):
            raise RuntimeError("boom")

    ctx._profiler = _Broken()  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        ctx.__enter__()
    assert not tracemalloc.is_tracing()
