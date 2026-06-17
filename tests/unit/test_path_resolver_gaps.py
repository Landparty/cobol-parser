"""Additional coverage for preprocess/path_resolver.py.

Targets branches not exercised by test_path_resolver_coverage.py:
  - find_copybook_file() size-limit enforcement
  - PathResolver._build_directory_index() non-file entries skipped
  - case-insensitive directory index construction
  - resolve() tier-2 size enforcement
  - resolve() tier-3 fallback via library qualifier
"""

import pytest

from cobolparser.preprocess import CopybookSizeExceededError
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file


class TestFindCopybookSizeLimit:
    def test_oversized_file_rejected(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "BIG.cpy").write_text("X" * 500)

        config = CopybookSearchPath(directories=[str(d)], max_file_size=10)
        with pytest.raises(CopybookSizeExceededError):
            find_copybook_file("BIG", config)


class TestDirectoryIndex:
    def test_subdirectories_skipped_in_index(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "REAL.cpy").write_text("01 R.")
        # A nested directory must not be indexed as a copybook file.
        (d / "NESTED").mkdir()

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        index = resolver._build_directory_index()
        # The index records both the exact filename and the bare stem.
        assert "REAL.cpy" in index
        assert "REAL" in index
        assert "NESTED" not in index

    def test_case_insensitive_index(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "Employee.cpy").write_text("01 E.")

        config = CopybookSearchPath(directories=[str(d)], case_sensitive=False)
        resolver = PathResolver(config)
        # Lower-case lookup succeeds against the upper-cased index keys.
        path = resolver.resolve("employee")
        assert path.lower().endswith("employee.cpy")

    def test_missing_directory_skipped(self, tmp_path):
        config = CopybookSearchPath(directories=[str(tmp_path / "does-not-exist")])
        resolver = PathResolver(config)
        assert resolver._build_directory_index() == {}


class TestResolveTiers:
    def test_resolution_cache_hit(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "CACHED.cpy").write_text("01 C.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        first = resolver.resolve("CACHED.cpy")
        second = resolver.resolve("CACHED.cpy")  # tier-1 cache hit
        assert first == second

    def test_tier2_size_enforcement(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "HUGE.cpy").write_text("Z" * 1000)

        config = CopybookSearchPath(directories=[str(d)], max_file_size=5)
        resolver = PathResolver(config)
        with pytest.raises(CopybookSizeExceededError):
            resolver.resolve("HUGE.cpy")

    def test_tier3_fallback_with_library_qualifier(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        lib = d / "MYLIB"
        lib.mkdir()
        (lib / "MEMBER.cpy").write_text("01 M.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        # library_qualifier forces the tier-3 full filesystem search.
        path = resolver.resolve("MEMBER", library_qualifier="MYLIB")
        assert path.endswith("MEMBER.cpy")
