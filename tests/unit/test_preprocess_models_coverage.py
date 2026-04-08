"""
Comprehensive unit tests for cobolparser.preprocess.models module.
Targets all uncovered lines for 100% coverage.

This test module covers:
- ReplacingClause: COBOL REPLACING clause representation
- SuppressClause: COBOL SUPPRESS clause with line ranges
- ExpansionStatistics: Performance metrics for expansion operations
- CopybookExpansion: Results of copybook expansion
- CopyStatement: Parsed COPY statement representation
- CopybookSearchPath: Configuration for copybook file location
- ExpansionContext: Internal state during recursive expansion
- get_default_case_sensitivity: Platform detection
"""

import sys
from unittest.mock import patch

import pytest

from cobolparser.preprocess.models import (
    MAX_COPYBOOK_SIZE_BYTES,
    MAX_TOTAL_EXPANSION_BYTES,
    CopybookExpansion,
    CopybookSearchPath,
    CopyStatement,
    ExpansionContext,
    ExpansionStatistics,
    ReplacingClause,
    SuppressClause,
    get_default_case_sensitivity,
)


class TestGetDefaultCaseSensitivity:
    """Tests for get_default_case_sensitivity function."""

    def test_windows_returns_false(self):
        """Test Windows platform returns case-insensitive (False)."""
        with patch.object(sys, "platform", "win32"):
            result = get_default_case_sensitivity()
            assert result is False

    def test_darwin_returns_false(self):
        """Test macOS platform returns case-insensitive (False)."""
        with patch.object(sys, "platform", "darwin"):
            result = get_default_case_sensitivity()
            assert result is False

    def test_linux_returns_true(self):
        """Test Linux platform returns case-sensitive (True)."""
        with patch.object(sys, "platform", "linux"):
            result = get_default_case_sensitivity()
            assert result is True

    def test_other_unix_returns_true(self):
        """Test other Unix platforms return case-sensitive (True)."""
        with patch.object(sys, "platform", "freebsd"):
            result = get_default_case_sensitivity()
            assert result is True


class TestReplacingClause:
    """Tests for ReplacingClause dataclass."""

    def test_creation_with_defaults(self):
        """Test ReplacingClause creation with default mode."""
        clause = ReplacingClause(find_text="OLD", replace_text="NEW")

        assert clause.find_text == "OLD"
        assert clause.replace_text == "NEW"
        assert clause.mode == "ALL"

    def test_creation_with_leading_mode(self):
        """Test ReplacingClause with LEADING mode."""
        clause = ReplacingClause(
            find_text="PREFIX", replace_text="NEWPFX", mode="LEADING"
        )

        assert clause.find_text == "PREFIX"
        assert clause.replace_text == "NEWPFX"
        assert clause.mode == "LEADING"

    def test_creation_with_trailing_mode(self):
        """Test ReplacingClause with TRAILING mode."""
        clause = ReplacingClause(
            find_text="SUFFIX", replace_text="NEWSUF", mode="TRAILING"
        )

        assert clause.mode == "TRAILING"

    def test_to_dict(self):
        """Test to_dict serialization."""
        clause = ReplacingClause(
            find_text="OLD-VALUE", replace_text="NEW-VALUE", mode="LEADING"
        )

        result = clause.to_dict()

        assert result == {
            "find": "OLD-VALUE",
            "replace": "NEW-VALUE",
            "mode": "LEADING",
        }

    def test_to_dict_all_mode(self):
        """Test to_dict with default ALL mode."""
        clause = ReplacingClause(find_text="X", replace_text="Y")
        result = clause.to_dict()

        assert result["mode"] == "ALL"


class TestSuppressClause:
    """Tests for SuppressClause dataclass."""

    def test_creation_defaults(self):
        """Test SuppressClause creation with defaults."""
        clause = SuppressClause()

        assert clause.suppress_all is False
        assert clause.line_ranges == []
        assert clause.single_lines == []

    def test_suppress_all(self):
        """Test SuppressClause with suppress_all=True."""
        clause = SuppressClause(suppress_all=True)

        assert clause.suppress_all is True

    def test_with_line_ranges(self):
        """Test SuppressClause with line ranges."""
        clause = SuppressClause(line_ranges=[(10, 20), (30, 40)])

        assert clause.line_ranges == [(10, 20), (30, 40)]

    def test_with_single_lines(self):
        """Test SuppressClause with single lines."""
        clause = SuppressClause(single_lines=[5, 15, 25])

        assert clause.single_lines == [5, 15, 25]

    def test_to_dict_suppress_all(self):
        """Test to_dict when suppress_all is True."""
        clause = SuppressClause(suppress_all=True)
        result = clause.to_dict()

        assert result == {"type": "ALL"}

    def test_to_dict_with_ranges(self):
        """Test to_dict with line ranges."""
        clause = SuppressClause(line_ranges=[(10, 20), (50, 60)])
        result = clause.to_dict()

        assert "ranges" in result
        assert result["ranges"] == [{"start": 10, "end": 20}, {"start": 50, "end": 60}]

    def test_to_dict_with_single_lines(self):
        """Test to_dict with single lines."""
        clause = SuppressClause(single_lines=[5, 10, 15])
        result = clause.to_dict()

        assert "lines" in result
        assert result["lines"] == [5, 10, 15]

    def test_to_dict_empty(self):
        """Test to_dict with no suppression."""
        clause = SuppressClause()
        result = clause.to_dict()

        assert result == {}

    def test_to_dict_combined(self):
        """Test to_dict with both ranges and single lines."""
        clause = SuppressClause(line_ranges=[(10, 15)], single_lines=[20, 25])
        result = clause.to_dict()

        assert "ranges" in result
        assert "lines" in result

    def test_get_suppressed_lines_all(self):
        """Test get_suppressed_lines when suppress_all is True."""
        clause = SuppressClause(suppress_all=True)
        lines = clause.get_suppressed_lines()

        # suppress_all returns empty set (handled separately)
        assert lines == set()

    def test_get_suppressed_lines_single(self):
        """Test get_suppressed_lines with single lines."""
        clause = SuppressClause(single_lines=[5, 10, 15])
        lines = clause.get_suppressed_lines()

        assert lines == {5, 10, 15}

    def test_get_suppressed_lines_ranges(self):
        """Test get_suppressed_lines with line ranges."""
        clause = SuppressClause(line_ranges=[(10, 12), (20, 22)])
        lines = clause.get_suppressed_lines()

        assert lines == {10, 11, 12, 20, 21, 22}

    def test_get_suppressed_lines_combined(self):
        """Test get_suppressed_lines with both ranges and singles."""
        clause = SuppressClause(line_ranges=[(1, 3)], single_lines=[5, 7])
        lines = clause.get_suppressed_lines()

        assert lines == {1, 2, 3, 5, 7}


class TestExpansionStatistics:
    """Tests for ExpansionStatistics dataclass."""

    def test_creation_defaults(self):
        """Test ExpansionStatistics creation with defaults."""
        stats = ExpansionStatistics()

        assert stats.parse_time_ms == 0.0
        assert stats.file_count == 0
        assert stats.total_lines == 0
        assert stats.peak_memory_bytes == 0
        assert stats.warnings == []
        assert stats.total_bytes_processed == 0

    def test_creation_custom_values(self):
        """Test ExpansionStatistics with custom values."""
        stats = ExpansionStatistics(
            parse_time_ms=150.5,
            file_count=10,
            total_lines=5000,
            peak_memory_bytes=1048576,
            warnings=["Warning 1", "Warning 2"],
            total_bytes_processed=500000,
        )

        assert stats.parse_time_ms == 150.5
        assert stats.file_count == 10
        assert stats.total_lines == 5000
        assert stats.peak_memory_bytes == 1048576
        assert len(stats.warnings) == 2
        assert stats.total_bytes_processed == 500000

    def test_to_dict_without_warnings(self):
        """Test to_dict when no warnings."""
        stats = ExpansionStatistics(parse_time_ms=100.0, file_count=5, total_lines=1000)
        result = stats.to_dict()

        assert result["parse_time_ms"] == 100.0
        assert result["file_count"] == 5
        assert result["total_lines"] == 1000
        assert "warnings" not in result

    def test_to_dict_with_warnings(self):
        """Test to_dict when warnings present."""
        stats = ExpansionStatistics(warnings=["Missing period", "Unbalanced quotes"])
        result = stats.to_dict()

        assert "warnings" in result
        assert result["warnings"] == ["Missing period", "Unbalanced quotes"]


class TestCopybookExpansion:
    """Tests for CopybookExpansion dataclass."""

    def test_creation_minimal(self):
        """Test CopybookExpansion with minimal required fields."""
        expansion = CopybookExpansion(expanded_source="01 EMPLOYEE-ID PIC X(10).")

        assert expansion.expanded_source == "01 EMPLOYEE-ID PIC X(10)."
        assert expansion.included_copybooks == []
        assert expansion.max_depth_reached == 0
        assert expansion.source_location_map is None
        assert isinstance(expansion.statistics, ExpansionStatistics)

    def test_creation_full(self):
        """Test CopybookExpansion with all fields."""
        stats = ExpansionStatistics(parse_time_ms=50.0, file_count=3)
        source_map = {1: ("file1.cpy", 1), 2: ("file1.cpy", 2)}

        expansion = CopybookExpansion(
            expanded_source="EXPANDED CONTENT",
            included_copybooks=["file1.cpy", "file2.cpy"],
            max_depth_reached=2,
            source_location_map=source_map,
            statistics=stats,
        )

        assert expansion.expanded_source == "EXPANDED CONTENT"
        assert len(expansion.included_copybooks) == 2
        assert expansion.max_depth_reached == 2
        assert expansion.source_location_map is not None
        assert expansion.statistics.parse_time_ms == 50.0

    def test_to_dict_without_source_map(self):
        """Test to_dict when source_location_map is None."""
        expansion = CopybookExpansion(
            expanded_source="CONTENT",
            included_copybooks=["test.cpy"],
            max_depth_reached=1,
        )
        result = expansion.to_dict()

        assert result["expanded_source"] == "CONTENT"
        assert result["included_copybooks"] == ["test.cpy"]
        assert result["max_depth_reached"] == 1
        assert "source_location_map" not in result
        assert "statistics" in result

    def test_to_dict_with_source_map(self):
        """Test to_dict when source_location_map is present."""
        source_map = {1: ("main.cpy", 10), 2: ("main.cpy", 11), 5: ("nested.cpy", 1)}
        expansion = CopybookExpansion(
            expanded_source="CONTENT", source_location_map=source_map
        )
        result = expansion.to_dict()

        assert "source_location_map" in result
        assert result["source_location_map"]["1"] == {"file": "main.cpy", "line": 10}
        assert result["source_location_map"]["5"] == {"file": "nested.cpy", "line": 1}


class TestCopyStatement:
    """Tests for CopyStatement dataclass."""

    def test_creation_minimal(self):
        """Test CopyStatement with minimal fields."""
        stmt = CopyStatement(member_name="EMPLOYEE")

        assert stmt.member_name == "EMPLOYEE"
        assert stmt.library_qualifier is None
        assert stmt.replacing_clauses is None
        assert stmt.suppress_clause is None
        assert stmt.source_location is None
        assert stmt.original_text == ""

    def test_creation_full(self):
        """Test CopyStatement with all fields."""
        replacing = [ReplacingClause("OLD", "NEW")]
        suppress = SuppressClause(suppress_all=True)

        stmt = CopyStatement(
            member_name="EMPLOYEE",
            library_qualifier="MYLIB",
            replacing_clauses=replacing,
            suppress_clause=suppress,
            source_location=("main.cbl", 100, 8),
            original_text="COPY EMPLOYEE IN MYLIB SUPPRESS.",
        )

        assert stmt.member_name == "EMPLOYEE"
        assert stmt.library_qualifier == "MYLIB"
        assert len(stmt.replacing_clauses) == 1
        assert stmt.suppress_clause.suppress_all is True
        assert stmt.source_location == ("main.cbl", 100, 8)

    def test_is_suppressed_property_true(self):
        """Test is_suppressed property when suppress_clause present."""
        stmt = CopyStatement(
            member_name="TEST", suppress_clause=SuppressClause(suppress_all=True)
        )

        assert stmt.is_suppressed is True

    def test_is_suppressed_property_false(self):
        """Test is_suppressed property when no suppress_clause."""
        stmt = CopyStatement(member_name="TEST")

        assert stmt.is_suppressed is False

    def test_has_replacements_property_true(self):
        """Test has_replacements property when replacing_clauses present."""
        stmt = CopyStatement(
            member_name="TEST", replacing_clauses=[ReplacingClause("X", "Y")]
        )

        assert stmt.has_replacements is True

    def test_has_replacements_property_false(self):
        """Test has_replacements property when no replacing_clauses."""
        stmt = CopyStatement(member_name="TEST")

        assert stmt.has_replacements is False

    def test_has_replacements_empty_list(self):
        """Test has_replacements with empty list."""
        stmt = CopyStatement(member_name="TEST", replacing_clauses=[])

        assert stmt.has_replacements is False

    def test_to_dict_minimal(self):
        """Test to_dict with minimal data."""
        stmt = CopyStatement(member_name="EMPLOYEE", original_text="COPY EMPLOYEE.")
        result = stmt.to_dict()

        assert result["member_name"] == "EMPLOYEE"
        assert result["original_text"] == "COPY EMPLOYEE."
        assert "library_qualifier" not in result
        assert "replacing_clauses" not in result
        assert "suppress_clause" not in result
        assert "source_location" not in result

    def test_to_dict_with_library(self):
        """Test to_dict with library qualifier."""
        stmt = CopyStatement(
            member_name="EMPLOYEE",
            library_qualifier="PAYLIB",
            original_text="COPY EMPLOYEE IN PAYLIB.",
        )
        result = stmt.to_dict()

        assert result["library_qualifier"] == "PAYLIB"

    def test_to_dict_with_replacing(self):
        """Test to_dict with replacing clauses."""
        stmt = CopyStatement(
            member_name="TEST",
            replacing_clauses=[
                ReplacingClause("OLD1", "NEW1"),
                ReplacingClause("OLD2", "NEW2", "LEADING"),
            ],
            original_text="COPY TEST REPLACING OLD1 BY NEW1 LEADING OLD2 BY NEW2.",
        )
        result = stmt.to_dict()

        assert "replacing_clauses" in result
        assert len(result["replacing_clauses"]) == 2
        assert result["replacing_clauses"][0]["find"] == "OLD1"
        assert result["replacing_clauses"][1]["mode"] == "LEADING"

    def test_to_dict_with_suppress(self):
        """Test to_dict with suppress clause."""
        stmt = CopyStatement(
            member_name="TEST",
            suppress_clause=SuppressClause(suppress_all=True),
            original_text="COPY TEST SUPPRESS.",
        )
        result = stmt.to_dict()

        assert "suppress_clause" in result
        assert result["suppress_clause"]["type"] == "ALL"

    def test_to_dict_with_source_location(self):
        """Test to_dict with source location."""
        stmt = CopyStatement(
            member_name="TEST",
            source_location=("program.cbl", 50, 12),
            original_text="COPY TEST.",
        )
        result = stmt.to_dict()

        assert "source_location" in result
        assert result["source_location"]["file"] == "program.cbl"
        assert result["source_location"]["line"] == 50
        assert result["source_location"]["column"] == 12


class TestCopybookSearchPath:
    """Tests for CopybookSearchPath dataclass."""

    def test_creation_defaults(self):
        """Test CopybookSearchPath with default values."""
        search_path = CopybookSearchPath()

        assert search_path.directories == []
        assert ".cpy" in search_path.extensions
        assert ".CPY" in search_path.extensions
        assert "" in search_path.extensions
        assert search_path.max_nesting_depth == 100
        assert search_path.max_file_size == MAX_COPYBOOK_SIZE_BYTES
        assert search_path.max_total_size == MAX_TOTAL_EXPANSION_BYTES

    def test_creation_custom(self):
        """Test CopybookSearchPath with custom values."""
        search_path = CopybookSearchPath(
            directories=["/path/one", "/path/two"],
            extensions=[".txt"],
            case_sensitive=True,
            max_nesting_depth=50,
            max_file_size=5000,
            max_total_size=50000,
        )

        assert search_path.directories == ["/path/one", "/path/two"]
        assert search_path.extensions == [".txt"]
        assert search_path.case_sensitive is True
        assert search_path.max_nesting_depth == 50
        assert search_path.max_file_size == 5000
        assert search_path.max_total_size == 50000

    def test_to_dict(self):
        """Test to_dict serialization."""
        search_path = CopybookSearchPath(
            directories=["/copybooks"], max_nesting_depth=25
        )
        result = search_path.to_dict()

        assert result["directories"] == ["/copybooks"]
        assert result["max_nesting_depth"] == 25
        assert "extensions" in result
        assert "case_sensitive" in result
        assert "max_file_size" in result
        assert "max_total_size" in result


class TestExpansionContext:
    """Tests for ExpansionContext dataclass."""

    def test_creation_defaults(self):
        """Test ExpansionContext with default values."""
        ctx = ExpansionContext()

        assert ctx.current_file == ""
        assert ctx.expansion_stack == []
        assert ctx.source_maps == {}
        assert ctx.current_depth == 0
        assert ctx.content_cache == {}
        assert ctx.total_bytes == 0
        assert ctx.defined_symbols == {}

    def test_creation_custom(self):
        """Test ExpansionContext with custom values."""
        ctx = ExpansionContext(
            current_file="main.cbl",
            expansion_stack=["level1.cpy"],
            current_depth=1,
            defined_symbols={"DEBUG": "TRUE"},
        )

        assert ctx.current_file == "main.cbl"
        assert ctx.expansion_stack == ["level1.cpy"]
        assert ctx.current_depth == 1
        assert ctx.defined_symbols == {"DEBUG": "TRUE"}

    def test_get_cache_key_without_replacing(self):
        """Test get_cache_key without replacing clauses."""
        ctx = ExpansionContext()
        key = ctx.get_cache_key("/path/to/copy.cpy")

        assert key == "/path/to/copy.cpy"

    def test_get_cache_key_with_replacing(self):
        """Test get_cache_key with replacing clauses."""
        ctx = ExpansionContext()
        replacing = [
            ReplacingClause("OLD", "NEW", "ALL"),
            ReplacingClause("X", "Y", "LEADING"),
        ]
        key = ctx.get_cache_key("/path/to/copy.cpy", replacing)

        assert "/path/to/copy.cpy" in key
        assert "::" in key
        # Key should include replacement info in sorted order
        assert "OLD" in key or "NEW" in key

    def test_get_cache_key_with_empty_replacing(self):
        """Test get_cache_key with empty replacing list."""
        ctx = ExpansionContext()
        key = ctx.get_cache_key("/path/to/copy.cpy", [])

        # Empty list should be treated like None
        assert key == "/path/to/copy.cpy"

    def test_to_dict(self):
        """Test to_dict serialization."""
        ctx = ExpansionContext(
            current_file="program.cbl",
            expansion_stack=["a.cpy", "b.cpy"],
            current_depth=2,
            total_bytes=50000,
            defined_symbols={"VERSION": "1.0"},
        )
        ctx.source_maps = {1: ("a.cpy", 1), 2: ("a.cpy", 2)}
        ctx.content_cache = {"key1": "content1"}

        result = ctx.to_dict()

        assert result["current_file"] == "program.cbl"
        assert result["expansion_stack"] == ["a.cpy", "b.cpy"]
        assert result["current_depth"] == 2
        assert result["source_maps_count"] == 2
        assert result["cache_size"] == 1
        assert result["total_bytes"] == 50000
        assert result["defined_symbols"] == {"VERSION": "1.0"}


class TestConstants:
    """Tests for module constants."""

    def test_max_copybook_size(self):
        """Test MAX_COPYBOOK_SIZE_BYTES constant."""
        assert MAX_COPYBOOK_SIZE_BYTES == 10 * 1024 * 1024  # 10MB

    def test_max_total_expansion_size(self):
        """Test MAX_TOTAL_EXPANSION_BYTES constant."""
        assert MAX_TOTAL_EXPANSION_BYTES == 100 * 1024 * 1024  # 100MB


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
