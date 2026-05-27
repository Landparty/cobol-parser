"""Unit tests for the persistent parse-result cache."""

from __future__ import annotations

import pickle
from pathlib import Path

from cobolparser import (
    DialectType,
    ErrorRecoveryMode,
    ParseCache,
    make_cache_key,
    make_config_fingerprint,
    parse_cobol,
)
from cobolparser.cache import default_cache_dir

SAMPLE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
       DISPLAY 'HELLO'.
       STOP RUN.
"""

SAMPLE_ALT = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOODBYE.
       PROCEDURE DIVISION.
       DISPLAY 'GOODBYE'.
       STOP RUN.
"""


def _fingerprint() -> str:
    return make_config_fingerprint(
        dialect=DialectType.IBM_ENTERPRISE,
        error_recovery=ErrorRecoveryMode.FAIL_FAST,
        free_form=False,
    )


class TestCacheKey:
    def test_key_is_deterministic(self):
        fp = _fingerprint()
        k1 = make_cache_key(source=SAMPLE, config_fingerprint=fp)
        k2 = make_cache_key(source=SAMPLE, config_fingerprint=fp)
        assert k1 == k2

    def test_source_edit_changes_key(self):
        fp = _fingerprint()
        k1 = make_cache_key(source=SAMPLE, config_fingerprint=fp)
        k2 = make_cache_key(source=SAMPLE_ALT, config_fingerprint=fp)
        assert k1 != k2

    def test_config_change_changes_key(self):
        k1 = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        k2 = make_cache_key(
            source=SAMPLE,
            config_fingerprint=make_config_fingerprint(
                dialect=DialectType.IBM_ENTERPRISE,
                error_recovery=ErrorRecoveryMode.COLLECT_ALL,
                free_form=False,
            ),
        )
        assert k1 != k2

    def test_copybook_hash_invalidation(self, tmp_path):
        cb = tmp_path / "FOO.cpy"
        cb.write_text("01 X PIC X.\n")
        fp = _fingerprint()
        k1 = make_cache_key(
            source=SAMPLE, config_fingerprint=fp, copybook_files=[str(cb)]
        )
        cb.write_text("01 X PIC XX.\n")
        k2 = make_cache_key(
            source=SAMPLE, config_fingerprint=fp, copybook_files=[str(cb)]
        )
        assert k1 != k2

    def test_missing_copybook_still_keys_stably(self, tmp_path):
        missing = tmp_path / "NOPE.cpy"
        fp = _fingerprint()
        k1 = make_cache_key(
            source=SAMPLE, config_fingerprint=fp, copybook_files=[str(missing)]
        )
        k2 = make_cache_key(
            source=SAMPLE, config_fingerprint=fp, copybook_files=[str(missing)]
        )
        assert k1 == k2


class TestParseCacheRoundTrip:
    def test_miss_then_hit(self, tmp_path):
        cache = ParseCache(tmp_path)
        result = parse_cobol(SAMPLE)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())

        assert cache.get(key) is None
        cache.put(key, result)

        cache.clear_memory()  # force on-disk path
        cached = cache.get(key)
        assert cached is not None
        assert cached.ast is not None
        assert cached.ast.program_name == result.ast.program_name

    def test_parent_relink_after_disk_hit(self, tmp_path):
        cache = ParseCache(tmp_path)
        result = parse_cobol(SAMPLE)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        cache.put(key, result)
        cache.clear_memory()

        cached = cache.get(key)
        assert cached is not None and cached.ast is not None
        # ASTNode.__getstate__ strips parent refs; ParseCache.get must
        # rebuild them via relink_parents so downstream walks work.
        first_child = cached.ast.children[0]
        assert first_child.parent is cached.ast

    def test_memory_tier_hit_skips_disk(self, tmp_path):
        cache = ParseCache(tmp_path)
        result = parse_cobol(SAMPLE)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        cache.put(key, result)

        # Same object should come back from the in-memory tier.
        hit = cache.get(key)
        assert hit is result

    def test_corrupt_disk_entry_is_miss_not_crash(self, tmp_path):
        cache = ParseCache(tmp_path)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        # Pre-create a malformed entry.
        shard = tmp_path / key[:2]
        shard.mkdir(parents=True)
        (shard / f"{key}.pkl").write_bytes(b"not a pickle stream")

        assert cache.get(key) is None  # graceful miss
        assert cache.misses == 1

    def test_disabled_cache_short_circuits(self, tmp_path):
        cache = ParseCache(tmp_path, enabled=False)
        result = parse_cobol(SAMPLE)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        cache.put(key, result)
        assert cache.get(key) is None
        # No file should have been written.
        assert not list(Path(tmp_path).rglob("*.pkl*"))

    def test_compressed_round_trip(self, tmp_path):
        cache = ParseCache(tmp_path, compress=True)
        result = parse_cobol(SAMPLE)
        key = make_cache_key(source=SAMPLE, config_fingerprint=_fingerprint())
        cache.put(key, result)
        cache.clear_memory()
        cached = cache.get(key)
        assert cached is not None
        assert cached.ast.program_name == result.ast.program_name
        # File should have the .pkl.gz suffix.
        files = list(Path(tmp_path).rglob("*.pkl.gz"))
        assert files, "compressed cache file not written"


class TestDefaultCacheDir:
    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("COBOLPARSER_CACHE_DIR", str(tmp_path))
        d = default_cache_dir()
        assert tmp_path in d.parents or d == tmp_path / d.name
        # Version segment is always present.
        assert d.name.startswith("v")

    def test_xdg_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("COBOLPARSER_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        d = default_cache_dir()
        assert str(tmp_path) in str(d)
        assert "cobolparser" in str(d)


class TestPickleStripsBackrefs:
    """ASTNode.__getstate__ must drop parent + _type_cache to avoid bloating
    cache entries and circular-reference traversal in pickle."""

    def test_pickle_drops_parent(self):
        result = parse_cobol(SAMPLE)
        # Pre-pickle: parents are wired up.
        assert result.ast.children[0].parent is result.ast

        data = pickle.dumps(result)
        restored = pickle.loads(data)

        # Post-unpickle (before relink): parents are None.
        assert restored.ast.children[0].parent is None

    def test_pickle_drops_type_cache(self):
        result = parse_cobol(SAMPLE)
        # Populate the cache.
        result.ast.find_all_by_type("CobolDivision")
        assert result.ast._type_cache is not None

        restored = pickle.loads(pickle.dumps(result))
        assert restored.ast._type_cache is None
