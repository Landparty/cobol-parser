"""Coverage for the copybook content cache observability/config API.

Targets the module-level file content cache helpers in
``cobolparser/preprocess/copybook_expander.py``:

  - clear_file_cache()
  - set_file_cache_size()
  - get_file_cache_stats()
  - _cached_read_file() hit/miss, LRU eviction and warning replay
  - convert_to_utf8() lossy-decode warning emission
  - read_file_with_encoding() error handling
"""

import pytest

from cobolparser.preprocess import EncodingError
from cobolparser.preprocess.copybook_expander import (
    _cached_read_file,
    clear_file_cache,
    convert_to_utf8,
    get_file_cache_stats,
    read_file_with_encoding,
    set_file_cache_size,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts and ends with a clean cache."""
    clear_file_cache()
    yield
    clear_file_cache()


class TestCacheStats:
    def test_stats_initially_empty(self):
        stats = get_file_cache_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["max_size"] >= 1

    def test_clear_resets_counters(self, tmp_path):
        f = tmp_path / "A.cpy"
        f.write_text("01 A.")
        _cached_read_file(str(f))  # one miss
        assert get_file_cache_stats()["misses"] == 1

        clear_file_cache()
        stats = get_file_cache_stats()
        assert stats["size"] == 0
        assert stats["misses"] == 0
        assert stats["hits"] == 0


class TestCachedRead:
    def test_miss_then_hit(self, tmp_path):
        f = tmp_path / "MEMBER.cpy"
        f.write_text("01 MEMBER-REC.")

        first = _cached_read_file(str(f))
        second = _cached_read_file(str(f))
        assert first == second == "01 MEMBER-REC."

        stats = get_file_cache_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 1
        assert stats["size"] == 1

    def test_lru_eviction(self, tmp_path):
        set_file_cache_size(2)
        try:
            for name in ("A", "B", "C"):
                p = tmp_path / f"{name}.cpy"
                p.write_text(f"01 {name}.")
                _cached_read_file(str(p))

            stats = get_file_cache_stats()
            # Capacity 2 with 3 distinct files forces at least one eviction.
            assert stats["size"] == 2
            assert stats["evictions"] >= 1
        finally:
            # Restore a generous default for subsequent tests.
            set_file_cache_size(2048)

    def test_warning_replay_on_cache_hit(self, tmp_path):
        """Lossy-decode diagnostics recorded on first read replay on hit."""
        # cp037 (EBCDIC) bytes that include an unmappable value -> replacement.
        f = tmp_path / "LOSSY.cpy"
        # 0xFF maps to a replacement char under several EBCDIC tables; using a
        # forced encoding override of 'ascii' guarantees a lossy decode of a
        # high byte regardless of platform codec tables.
        f.write_bytes(b"01 A.\xff")

        first_warnings: list[str] = []
        _cached_read_file(str(f), encoding_override="ascii", warnings=first_warnings)
        assert any("Lossy decode" in w for w in first_warnings)

        # Second read is a cache hit; recorded warnings must be replayed.
        replay_warnings: list[str] = []
        _cached_read_file(str(f), encoding_override="ascii", warnings=replay_warnings)
        assert any("Lossy decode" in w for w in replay_warnings)
        assert get_file_cache_stats()["hits"] == 1


class TestSetFileCacheSize:
    def test_rejects_non_positive(self):
        with pytest.raises(ValueError):
            set_file_cache_size(0)

    def test_shrinking_evicts_excess(self, tmp_path):
        set_file_cache_size(10)
        try:
            for name in ("A", "B", "C", "D"):
                p = tmp_path / f"{name}.cpy"
                p.write_text(f"01 {name}.")
                _cached_read_file(str(p))
            assert get_file_cache_stats()["size"] == 4

            # Shrinking below the current population evicts down to the limit.
            set_file_cache_size(2)
            stats = get_file_cache_stats()
            assert stats["max_size"] == 2
            assert stats["size"] == 2
            assert stats["evictions"] >= 2
        finally:
            set_file_cache_size(2048)


class TestConvertToUtf8Warnings:
    def test_lossy_decode_appends_warning(self):
        warnings: list[str] = []
        # 0x80 is unmappable under ascii -> U+FFFD replacement.
        result = convert_to_utf8(
            b"AB\x80", "ascii", source_label="x.cpy", warnings=warnings
        )
        assert "�" in result
        assert len(warnings) == 1
        assert "x.cpy" in warnings[0]
        assert "Lossy decode" in warnings[0]

    def test_clean_decode_no_warning(self):
        warnings: list[str] = []
        result = convert_to_utf8(b"CLEAN", "ascii", warnings=warnings)
        assert result == "CLEAN"
        assert warnings == []


class TestReadFileWithEncodingErrors:
    def test_missing_file_raises_encoding_error(self):
        with pytest.raises(EncodingError):
            read_file_with_encoding("/nonexistent/dir/missing.cpy")
