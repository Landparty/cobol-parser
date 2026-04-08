"""Tests for PathResolver and path resolution utility coverage.

Targets uncovered lines in preprocess/path_resolver.py (73.13%):
  - PathResolver class wrapper methods (resolve, normalize, validate,
    get_suggestions, list_available)
  - get_available_copybooks() directory enumeration
  - find_copybook_file() case-insensitive matching
"""

import os

import pytest

from cobolparser.preprocess import (
    PathTraversalError,
)
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import (
    PathResolver,
    find_copybook_file,
    get_available_copybooks,
    validate_path_within_directory,
)


class TestGetAvailableCopybooks:
    """Cover get_available_copybooks enumeration."""

    def test_lists_copybooks_with_extensions(self, tmp_path):
        d = tmp_path / "copybooks"
        d.mkdir()
        (d / "EMPLOYEE.cpy").write_text("01 EMP-REC.")
        (d / "CUSTOMER.cpy").write_text("01 CUST-REC.")
        (d / "ADDRESS.CBL").write_text("01 ADDR-REC.")

        config = CopybookSearchPath(directories=[str(d)])
        result = get_available_copybooks(config)
        assert "EMPLOYEE" in result
        assert "CUSTOMER" in result

    def test_lists_copybooks_without_extension(self, tmp_path):
        d = tmp_path / "copybooks"
        d.mkdir()
        (d / "MYMEMBER").write_text("01 MY-REC.")

        config = CopybookSearchPath(
            directories=[str(d)], extensions=[""]
        )
        result = get_available_copybooks(config)
        assert "MYMEMBER" in result

    def test_nonexistent_directory_skipped(self, tmp_path):
        config = CopybookSearchPath(directories=[str(tmp_path / "nope")])
        result = get_available_copybooks(config)
        assert result == []


class TestFindCopybookFileCaseInsensitive:
    """Cover case-insensitive copybook search paths."""

    def test_finds_uppercase_variant(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "EMPLOYEE.cpy").write_text("01 EMP.")

        config = CopybookSearchPath(
            directories=[str(d)], case_sensitive=False
        )
        path = find_copybook_file("employee", config)
        assert os.path.isfile(path)

    def test_finds_lowercase_variant(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "employee.cpy").write_text("01 EMP.")

        config = CopybookSearchPath(
            directories=[str(d)], case_sensitive=False
        )
        path = find_copybook_file("EMPLOYEE", config)
        assert os.path.isfile(path)

    def test_with_library_qualifier(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        lib_dir = d / "MYLIB"
        lib_dir.mkdir()
        (lib_dir / "MEMBER.cpy").write_text("01 M.")

        config = CopybookSearchPath(directories=[str(d)])
        path = find_copybook_file("MEMBER", config, library_qualifier="MYLIB")
        assert os.path.isfile(path)


class TestPathResolverClass:
    """Cover PathResolver wrapper class methods."""

    def test_resolve(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "TEST.cpy").write_text("01 T.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        path = resolver.resolve("TEST")
        assert os.path.isfile(path)

    def test_normalize(self):
        config = CopybookSearchPath(directories=[])
        resolver = PathResolver(config)
        result = resolver.normalize("some/path/file.cpy")
        assert isinstance(result, str)

    def test_validate_within_directory(self, tmp_path):
        d = tmp_path / "base"
        d.mkdir()
        f = d / "test.cpy"
        f.write_text("01 T.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        assert resolver.validate(str(f), str(d)) is True

    def test_validate_path_traversal(self, tmp_path):
        config = CopybookSearchPath(directories=[])
        resolver = PathResolver(config)
        with pytest.raises(PathTraversalError):
            resolver.validate("../../../etc/passwd", str(tmp_path))

    def test_get_suggestions(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "EMPLOYEE.cpy").write_text("01 E.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        suggestions = resolver.get_suggestions("EMPLOYE")
        assert isinstance(suggestions, list)

    def test_list_available(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "A.cpy").write_text("01 A.")
        (d / "B.cpy").write_text("01 B.")

        config = CopybookSearchPath(directories=[str(d)])
        resolver = PathResolver(config)
        available = resolver.list_available()
        assert "A" in available
        assert "B" in available


class TestValidatePathEdgeCases:
    """Cover edge cases in validate_path_within_directory."""

    def test_non_path_traversal_exception(self, tmp_path):
        """Path validation that fails for non-traversal reasons."""
        # A file outside the base that doesn't contain ".." but resolves outside
        other = tmp_path / "other"
        other.mkdir()
        f = other / "test.txt"
        f.write_text("hi")
        base = tmp_path / "base"
        base.mkdir()

        with pytest.raises(PathTraversalError):
            validate_path_within_directory(str(f), str(base))
