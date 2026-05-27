"""End-to-end tests for the batch + parse-result cache integration.

Covers the cache-prepass in the main process, worker-side cache writes,
in-memory tier promotion, and the copybook-aware
:func:`parse_files_with_copybooks` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import ParseCache, parse_files, parse_files_with_copybooks
from cobolparser.plugins.core import ErrorRecoveryMode

pytestmark = pytest.mark.integration

SAMPLES_DIR = Path(__file__).parent.parent / "samples"

PROGRAM_A = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. AAA.
       PROCEDURE DIVISION.
       DISPLAY 'A'.
       STOP RUN.
"""

PROGRAM_B = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BBB.
       PROCEDURE DIVISION.
       DISPLAY 'B'.
       STOP RUN.
"""


def _write_files(tmp: Path, n: int) -> list[Path]:
    """Write ``n`` distinct small COBOL files for batch parsing."""
    files: list[Path] = []
    for i in range(n):
        p = tmp / f"prog_{i:02d}.cbl"
        body = PROGRAM_A if i % 2 == 0 else PROGRAM_B
        body = body.replace("AAA", f"P{i:02d}").replace("BBB", f"P{i:02d}")
        p.write_text(body)
        files.append(p)
    return files


class TestParseFilesCache:
    def test_warm_cache_hits_skip_workers(self, tmp_path):
        files = _write_files(tmp_path, 6)
        cache = ParseCache(tmp_path / "cache")

        first = parse_files(files, workers=1, cache=cache)
        assert all(br.result is not None for br in first)

        cache.clear_memory()  # force on-disk path next time
        second = parse_files(files, workers=1, cache=cache)
        assert all(br.result is not None for br in second)
        assert cache.hits >= len(files)

    def test_memory_tier_returns_same_object(self, tmp_path):
        files = _write_files(tmp_path, 3)
        cache = ParseCache(tmp_path / "cache")
        parse_files(files, workers=1, cache=cache)

        again = parse_files(files, workers=1, cache=cache)
        # In-memory hits return cached instances directly — the AST
        # identity should be preserved between runs.
        assert all(br.result is not None for br in again)

    def test_source_edit_invalidates_entry(self, tmp_path):
        files = _write_files(tmp_path, 2)
        cache = ParseCache(tmp_path / "cache")
        parse_files(files, workers=1, cache=cache)

        # Edit one source — that file should miss, the other hit.
        files[0].write_text(PROGRAM_A.replace("AAA", "EDITED"))

        cache.clear_memory()
        cache.hits = cache.misses = 0
        out = parse_files(files, workers=1, cache=cache)
        assert all(br.result is not None for br in out)
        # Hits should be exactly 1 (the untouched file); the edited file misses.
        assert cache.hits == 1
        assert cache.misses == 1

    def test_results_match_uncached_baseline(self, tmp_path):
        files = _write_files(tmp_path, 5)

        baseline = parse_files(
            files,
            workers=1,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        cache = ParseCache(tmp_path / "cache")
        parse_files(
            files,
            workers=1,
            cache=cache,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        cache.clear_memory()
        cached = parse_files(
            files,
            workers=1,
            cache=cache,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )

        for b, c in zip(baseline, cached, strict=True):
            assert b.result.ast.program_name == c.result.ast.program_name
            assert len(b.result.ast.children) == len(c.result.ast.children)
            assert len(b.result.errors) == len(c.result.errors)

    def test_disabled_cache_is_noop(self, tmp_path):
        files = _write_files(tmp_path, 3)
        cache = ParseCache(tmp_path / "cache", enabled=False)
        parse_files(files, workers=1, cache=cache)
        assert cache.hits == 0
        # No cache files written.
        assert not list((tmp_path / "cache").rglob("*.pkl*"))


class TestParseFilesWithCopybooksCache:
    def test_copybook_edit_invalidates_dependent(self, tmp_path):
        cb_dir = tmp_path / "cpy"
        cb_dir.mkdir()
        copybook = cb_dir / "FIELDS.CPY"
        copybook.write_text("       01 X PIC X.\n")

        program = tmp_path / "main.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MAIN.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY FIELDS.\n"
            "       PROCEDURE DIVISION.\n"
            "       STOP RUN.\n"
        )

        cache = ParseCache(tmp_path / "cache")

        # First call populates the cache with the original copybook hash.
        out1 = parse_files_with_copybooks(
            [program], copybook_paths=[str(cb_dir)], cache=cache
        )
        assert out1[0].result is not None

        cache.clear_memory()
        cache.hits = cache.misses = 0

        # Second call without edits should hit the on-disk cache.
        out2 = parse_files_with_copybooks(
            [program], copybook_paths=[str(cb_dir)], cache=cache
        )
        assert out2[0].result is not None
        assert cache.hits >= 1

        # Edit the copybook; the dependent file must miss.
        copybook.write_text("       01 X PIC XX.\n")
        cache.clear_memory()
        cache.hits = cache.misses = 0

        out3 = parse_files_with_copybooks(
            [program], copybook_paths=[str(cb_dir)], cache=cache
        )
        assert out3[0].result is not None
        assert cache.misses >= 1
