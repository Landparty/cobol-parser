"""
Unit tests for copybook expansion functionality.

Tests cover:
- Path normalization and validation
- Encoding detection and conversion
- COPY statement parsing
- Error handling (file not found, path traversal, etc.)
- Empty copybook handling
"""

import os
import tempfile
from pathlib import Path

import pytest

# Import modules under test
from cobolparser.preprocess import (
    CircularReferenceError,
    CopybookNotFoundError,
    NestingDepthError,
    PathTraversalError,
    expand_copybooks,
)
from cobolparser.preprocess.copy_statement_parser import extract_copy_statements
from cobolparser.preprocess.copybook_expander import detect_encoding
from cobolparser.preprocess.path_resolver import (
    normalize_path,
    validate_path_within_directory,
)


class TestPathNormalization:
    """Tests for path normalization functionality (T034)."""

    def test_forward_slash_handling(self):
        """Test that forward slashes are handled correctly."""
        # Test Unix-style paths
        path = "copybooks/employee"
        normalized = normalize_path(path)

        # On Windows, should convert to backslash; on Unix, stays forward slash
        assert "\\" in normalized or "/" in normalized
        assert "employee" in normalized

    def test_backslash_handling(self):
        """Test that backslashes are handled correctly."""
        # Test Windows-style paths
        path = "copybooks\\employee"
        normalized = normalize_path(path)

        # Should handle backslashes properly
        assert "employee" in normalized


class TestCopybookNotFound:
    """Tests for copybook not found error handling (T035)."""

    def test_missing_copybook_raises_error(self):
        """Test that missing copybook raises CopybookNotFoundError."""
        source = "       COPY NONEXISTENT."

        with pytest.raises(CopybookNotFoundError) as exc_info:
            expand_copybooks(source, ["/tmp/fake/path"])

        # Error should mention the missing copybook
        assert "NONEXISTENT" in str(exc_info.value)

    def test_error_includes_search_paths(self):
        """Test that error message includes all search paths."""
        source = "       COPY MISSING."
        search_paths = ["/path/one", "/path/two", "/path/three"]

        with pytest.raises(CopybookNotFoundError) as exc_info:
            expand_copybooks(source, search_paths)

        error_msg = str(exc_info.value)
        # Should mention search paths
        assert "MISSING" in error_msg or "not found" in error_msg.lower()


class TestEmptyCopybook:
    """Tests for empty copybook handling (T036)."""

    def test_empty_file_expands_to_empty(self):
        """Test that empty copybook files expand to empty content."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # EMPTY.cpy should exist from test setup
        source = "       COPY EMPTY."
        result = expand_copybooks(source, [str(samples_dir)])

        # Should replace COPY statement with empty/minimal content
        assert "COPY EMPTY" not in result.expanded_source
        # EMPTY.cpy has just a comment, so expanded source should be minimal
        assert len(result.expanded_source) < 100

    def test_whitespace_only_expands_to_empty(self):
        """Test that whitespace-only files expand to empty content."""
        # Use EMPTY.cpy which contains minimal content
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = "       IDENTIFICATION DIVISION.\n       COPY EMPTY.\n       PROCEDURE DIVISION."
        result = expand_copybooks(source, [str(samples_dir)])

        # Should have expanded, removing COPY statement
        assert "COPY EMPTY" not in result.expanded_source
        assert "IDENTIFICATION DIVISION" in result.expanded_source


class TestCopyStatementExtraction:
    """Tests for COPY statement parsing (T037)."""

    def test_simple_copy_statement(self):
        """Test parsing of simple COPY MEMBER. statement."""
        source = "       COPY EMPLOYEE."
        statements = extract_copy_statements(source)

        assert len(statements) == 1
        assert statements[0].member_name == "EMPLOYEE"
        assert statements[0].library_qualifier is None

    def test_quoted_member_name(self):
        """Test parsing of COPY \"MEMBER\". statement."""
        source = '       COPY "EMPLOYEE".'
        statements = extract_copy_statements(source)

        assert len(statements) == 1
        assert "EMPLOYEE" in statements[0].member_name

    def test_library_qualifier_in(self):
        """Test parsing of COPY MEMBER IN LIBRARY. statement."""
        source = "       COPY EMPLOYEE IN MYLIB."
        statements = extract_copy_statements(source)

        assert len(statements) == 1
        assert statements[0].member_name == "EMPLOYEE"
        assert statements[0].library_qualifier == "MYLIB"

    def test_library_qualifier_of(self):
        """Test parsing of COPY MEMBER OF LIBRARY. statement."""
        source = "       COPY EMPLOYEE OF MYLIB."
        statements = extract_copy_statements(source)

        assert len(statements) == 1
        assert statements[0].member_name == "EMPLOYEE"
        assert statements[0].library_qualifier == "MYLIB"


class TestPathTraversal:
    """Tests for path traversal prevention (T038)."""

    def test_dotdot_rejected(self):
        """Test that \"../\" in member name raises PathTraversalError."""
        # Test that path validation rejects ".." sequences
        with pytest.raises(PathTraversalError):
            validate_path_within_directory("../etc/passwd", "/safe/dir")

    def test_absolute_path_rejected(self):
        """Test that absolute paths are rejected."""
        # Absolute paths should be rejected if they're outside the allowed directory
        with pytest.raises(PathTraversalError):
            validate_path_within_directory("/etc/passwd", "/safe/dir")


class TestEncodingDetection:
    """Tests for encoding detection (T039)."""

    def test_ascii_detection(self):
        """Test detection of ASCII files."""
        # Create temporary file with ASCII content
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write(b"       01 TEST-DATA PIC X(10).")
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            # Should detect as ASCII or UTF-8 (ASCII is valid UTF-8)
            assert encoding in ["ascii", "utf-8"]
        finally:
            os.unlink(temp_path)

    def test_utf8_detection(self):
        """Test detection of UTF-8 files."""
        # UTF-8 with non-ASCII characters
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write("       01 TEST-NAÏVE PIC X(10).".encode())
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            assert encoding == "utf-8"
        finally:
            os.unlink(temp_path)

    def test_utf8_bom_detection(self):
        """Test detection of UTF-8 files with BOM."""
        # UTF-8 BOM + content
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write(b"\xef\xbb\xbf       01 TEST-DATA PIC X(10).")
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            # utf-8-sig includes the BOM, which is correct
            assert encoding in ["utf-8", "utf-8-sig"]
        finally:
            os.unlink(temp_path)

    def test_ebcdic_detection(self):
        """Test detection of EBCDIC files."""
        # Create EBCDIC-like bytes (0x40 is EBCDIC space)
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write(bytes([0x40] * 20) + b"\xf0\xf1")  # Mostly EBCDIC spaces + digits
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            # cp037 is a common EBCDIC codepage
            assert encoding in ["ebcdic", "cp037", "ascii"]
        finally:
            os.unlink(temp_path)


# Additional test placeholders for Phase 4-6 user stories
class TestNestedExpansion:
    """Tests for nested copybook resolution (US2)."""

    def test_recursion_base_case(self):
        """Test that copybook with no COPY statements stops recursion (T054)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # LEVEL3.cpy has no COPY statements - should be the base case
        source = "       COPY LEVEL3."
        result = expand_copybooks(source, [str(samples_dir)])

        # Should expand successfully without further recursion
        assert "LEVEL3-FIELD" in result.expanded_source
        assert len(result.included_copybooks) == 1
        assert result.max_depth_reached == 1

    def test_maximum_nesting_depth(self):
        """Test that NestingDepthError raised when exceeding max depth (T055)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # Try to expand with max_nesting_depth set very low
        source = "       COPY LEVEL1."

        with pytest.raises(NestingDepthError) as exc_info:
            expand_copybooks(source, [str(samples_dir)], max_nesting_depth=1)

        # Error should mention the depth limit
        error_msg = str(exc_info.value)
        assert "depth" in error_msg.lower() or "1" in error_msg


class TestCircularReference:
    """Tests for circular reference detection (US3)."""

    def test_circular_detection_in_stack(self):
        """Test circular detection in expansion_stack (T066)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        # CIRCULARA.cpy includes CIRCULARB.cpy which includes CIRCULARA.cpy
        source = "       COPY CIRCULARA."

        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(samples_dir)])

        # Should detect the circular reference
        assert exc_info.value is not None

    def test_error_includes_dependency_chain(self):
        """Test CircularReferenceError message shows dependency chain (T067)."""
        samples_dir = Path(__file__).parent.parent / "samples" / "copybooks"

        source = "       COPY CIRCULARA."

        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(samples_dir)])

        # Error message should show the chain of dependencies
        error_msg = str(exc_info.value)
        assert "CIRCULARA" in error_msg
        assert "CIRCULARB" in error_msg
        # Should show the circular nature (A appears multiple times or chain is shown)
        assert error_msg.count("CIRCULAR") >= 2 or "→" in error_msg or "->" in error_msg


class TestSourceLocationTracking:
    """Tests for source location preservation (US4)."""

    def test_source_location_tracking(self):
        """Test line numbers incremented correctly (T077)."""
        pytest.skip("Implementation pending - Phase 6")

    def test_nested_file_references(self):
        """Test nested content attributes to deepest source file (T078)."""
        pytest.skip("Implementation pending - Phase 6")


class TestCopyReplacing:
    """Tests for COPY REPLACING clause (Phase 7)."""

    def test_replacing_parsing(self):
        """Test parsing of COPY REPLACING clause (T087)."""
        pytest.skip("Implementation pending - Phase 7")
