"""Performance regression gates for batch + parse-result cache.

These tests assert the headline speedup numbers from the optimization
plan:

* **Warm-batch on-disk hits** ≥ 3x over a cold parse.
* **Warm-batch in-memory hits** ≥ 20x over a cold parse.

The "20x on warm batches" figure relies on the in-memory tier — that's
the realistic operating mode for repeated batches in CI/IDE re-parse
scenarios. Lower thresholds are configured here than the raw measured
numbers (50-70x) to leave headroom for slower CI machines and avoid
flakiness.

Run with::

    python -m pytest tests/performance/test_batch_speedup.py -v --no-cov
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from cobolparser import ParseCache, parse_files

pytestmark = pytest.mark.slow

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def _largest_samples(n: int) -> list[Path]:
    samples = list(SAMPLES_DIR.glob("*.cbl"))
    samples.sort(key=lambda p: p.stat().st_size, reverse=True)
    return samples[:n]


def _time(fn, *, warmup: int = 1, repeat: int = 3) -> float:
    """Return the minimum elapsed time over ``repeat`` runs."""
    for _ in range(warmup):
        fn()
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


@pytest.mark.skipif(
    not list(SAMPLES_DIR.glob("*.cbl")),
    reason="no sample programs available",
)
class TestBatchCacheSpeedup:
    def test_in_memory_warm_speedup_at_least_20x(self, tmp_path):
        files = _largest_samples(20)
        if len(files) < 5:
            pytest.skip("not enough samples for a meaningful benchmark")

        cache = ParseCache(tmp_path / "cache")

        cold = _time(lambda: parse_files(files, workers=1))

        # Warm the cache once (writes happen here).
        parse_files(files, workers=1, cache=cache)

        # Subsequent calls hit the in-memory tier — the prepass returns
        # results without scheduling any worker.
        warm = _time(lambda: parse_files(files, workers=1, cache=cache))

        speedup = cold / warm
        # Allow a comfortable margin: measured ~50-70x; demand only 20x.
        assert speedup >= 20.0, (
            f"in-memory warm batch speedup was {speedup:.1f}x "
            f"(cold {cold * 1000:.1f}ms vs warm {warm * 1000:.1f}ms); "
            f"expected ≥20x"
        )

    def test_on_disk_warm_speedup_at_least_3x(self, tmp_path):
        files = _largest_samples(20)
        if len(files) < 5:
            pytest.skip("not enough samples for a meaningful benchmark")

        cache = ParseCache(tmp_path / "cache")
        cold = _time(lambda: parse_files(files, workers=1))

        # Populate the on-disk cache.
        parse_files(files, workers=1, cache=cache)

        def warm_disk_only():
            # Drop the in-memory tier each iteration so we exercise the
            # on-disk path. Min-of-N timing in _time() still captures
            # the true on-disk read cost.
            cache.clear_memory()
            parse_files(files, workers=1, cache=cache)

        warm = _time(warm_disk_only, warmup=0)

        speedup = cold / warm
        # Plain (uncompressed) pickle measured ~5x; demand 3x to stay
        # robust against slower CI disks.
        assert speedup >= 3.0, (
            f"on-disk warm batch speedup was {speedup:.1f}x "
            f"(cold {cold * 1000:.1f}ms vs warm {warm * 1000:.1f}ms); "
            f"expected ≥3x"
        )

    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="parallel timing too noisy on CI runners",
    )
    def test_parallel_in_memory_warm_speedup_at_least_20x(self, tmp_path):
        files = _largest_samples(20)
        if len(files) < 5:
            pytest.skip("not enough samples for a meaningful benchmark")

        workers = min(4, os.cpu_count() or 1)
        cache = ParseCache(tmp_path / "cache")

        cold = _time(lambda: parse_files(files, workers=workers))

        parse_files(files, workers=workers, cache=cache)
        warm = _time(lambda: parse_files(files, workers=workers, cache=cache))

        speedup = cold / warm
        assert speedup >= 20.0, (
            f"parallel in-memory warm speedup was {speedup:.1f}x "
            f"(cold {cold * 1000:.1f}ms vs warm {warm * 1000:.1f}ms); "
            f"expected ≥20x"
        )
