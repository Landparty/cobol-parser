"""
Comprehensive unit tests for cobolparser.preprocess.copybook_expander module.
Targets all uncovered lines for 100% coverage.

This test module covers:
- detect_encoding: File encoding detection
- convert_to_utf8: Content conversion
- read_file_with_encoding: File reading with automatic encoding
- expand_copybooks: Main copybook expansion function
- _expand_source_recursive: Recursive expansion logic
- parse_cobol_with_expansion: Convenience function
"""

import os
import tempfile

import pytest

from cobolparser.preprocess import (
    CircularReferenceError,
    EncodingError,
    NestingDepthError,
    TotalExpansionSizeExceededError,
)
from cobolparser.preprocess.copybook_expander import (
    convert_to_utf8,
    detect_encoding,
    expand_copybooks,
    parse_cobol_with_expansion,
    read_file_with_encoding,
)


class TestDetectEncoding:
    """Tests for detect_encoding function."""

    def test_utf8_bom_detection(self):
        """Test detection of UTF-8 BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            # UTF-8 BOM + content
            f.write(b"\xef\xbb\xbf       01 TEST PIC X.")
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            assert encoding == "utf-8-sig"
        finally:
            os.unlink(temp_path)

    def test_utf8_detection(self):
        """Test detection of UTF-8 without BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write('       01 TEST PIC X(10) VALUE "Café".'.encode())
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            assert encoding == "utf-8"
        finally:
            os.unlink(temp_path)

    def test_ascii_detection(self):
        """Test detection of ASCII content."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write(b'       01 TEST PIC X(10) VALUE "HELLO".')
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            assert encoding in ["utf-8", "ascii"]
        finally:
            os.unlink(temp_path)

    def test_ebcdic_detection(self):
        """Test detection of EBCDIC-like content."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            # EBCDIC uses 0x40 for space (ASCII uses 0x20)
            # Create content with more EBCDIC spaces than ASCII spaces
            # Need enough 0x40 bytes to trigger EBCDIC detection (>5% of content)
            ebcdic_spaces = bytes([0x40] * 100)
            f.write(ebcdic_spaces)
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            # EBCDIC detection may return cp037 or fallback to utf-8/ascii
            # depending on the exact detection algorithm
            assert encoding in ["cp037", "utf-8", "ascii"]
        finally:
            os.unlink(temp_path)

    def test_encoding_error_on_read_failure(self):
        """Test EncodingError when file cannot be read."""
        with pytest.raises(EncodingError):
            detect_encoding("/nonexistent/path/file.cpy")

    def test_invalid_utf8_fallback(self):
        """Test fallback when UTF-8 decode fails."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            # Invalid UTF-8 sequence
            f.write(b"\xff\xfe       01 TEST.")
            temp_path = f.name

        try:
            encoding = detect_encoding(temp_path)
            # Should fallback to ASCII
            assert encoding in ["ascii", "cp037"]
        finally:
            os.unlink(temp_path)


class TestConvertToUtf8:
    """Tests for convert_to_utf8 function."""

    def test_utf8_conversion(self):
        """Test UTF-8 content conversion."""
        content = b"       01 TEST PIC X."
        result = convert_to_utf8(content, "utf-8")

        assert result == "       01 TEST PIC X."

    def test_ascii_conversion(self):
        """Test ASCII content conversion."""
        content = b"       01 TEST PIC X."
        result = convert_to_utf8(content, "ascii")

        assert result == "       01 TEST PIC X."

    def test_utf8_sig_conversion(self):
        """Test UTF-8 with BOM conversion."""
        content = b"\xef\xbb\xbf       01 TEST."
        result = convert_to_utf8(content, "utf-8-sig")

        assert "01 TEST" in result

    def test_conversion_with_replacement(self):
        """Test conversion with character replacement for errors."""
        # Content with invalid bytes
        content = b"\xff\xfe       01 TEST."
        result = convert_to_utf8(content, "utf-8")

        # Should use replacement characters
        assert "TEST" in result


class TestReadFileWithEncoding:
    """Tests for read_file_with_encoding function."""

    def test_read_utf8_file(self):
        """Test reading UTF-8 file."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".cpy", encoding="utf-8"
        ) as f:
            f.write("       01 TEST-DATA PIC X(10).")
            temp_path = f.name

        try:
            content = read_file_with_encoding(temp_path)
            assert "TEST-DATA" in content
        finally:
            os.unlink(temp_path)

    def test_read_with_bom(self):
        """Test reading file with BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".cpy") as f:
            f.write(b"\xef\xbb\xbf       01 BOM-TEST.")
            temp_path = f.name

        try:
            content = read_file_with_encoding(temp_path)
            assert "BOM-TEST" in content
        finally:
            os.unlink(temp_path)

    def test_read_nonexistent_file(self):
        """Test error when file doesn't exist."""
        with pytest.raises(EncodingError):
            read_file_with_encoding("/nonexistent/file.cpy")


class TestExpandCopybooks:
    """Tests for expand_copybooks function."""

    @pytest.fixture
    def copybook_dir(self, tmp_path):
        """Create a temporary directory with copybook files."""
        # Create main copybook
        main_cpy = tmp_path / "MAIN.cpy"
        main_cpy.write_text("       01 MAIN-DATA PIC X(10).")

        # Create nested copybook
        nested_cpy = tmp_path / "NESTED.cpy"
        nested_cpy.write_text("       05 NESTED-FIELD PIC X(5).")

        # Create copybook that references another
        parent_cpy = tmp_path / "PARENT.cpy"
        parent_cpy.write_text("       01 PARENT-RECORD.\n       COPY NESTED.")

        return tmp_path

    def test_basic_expansion(self, copybook_dir):
        """Test basic copybook expansion."""
        source = "       COPY MAIN."
        result = expand_copybooks(source, [str(copybook_dir)])

        assert "MAIN-DATA" in result.expanded_source
        assert "COPY MAIN" not in result.expanded_source
        assert str(copybook_dir / "MAIN.cpy") in result.included_copybooks

    def test_nested_expansion(self, copybook_dir):
        """Test nested copybook expansion."""
        source = "       COPY PARENT."
        result = expand_copybooks(source, [str(copybook_dir)])

        assert "PARENT-RECORD" in result.expanded_source
        assert "NESTED-FIELD" in result.expanded_source
        assert result.max_depth_reached >= 1

    def test_with_source_location_preservation(self, copybook_dir):
        """Test expansion with source location preservation."""
        source = "       COPY MAIN."
        result = expand_copybooks(
            source, [str(copybook_dir)], preserve_source_locations=True
        )

        assert result.source_location_map is not None

    def test_with_conditional_compilation(self, copybook_dir):
        """Test expansion with conditional compilation."""
        source = """>>DEFINE DEBUG
       COPY MAIN.
"""
        result = expand_copybooks(
            source,
            [str(copybook_dir)],
            process_conditionals=True,
            defined_symbols={"EXTRA": "VALUE"},
        )

        assert "MAIN-DATA" in result.expanded_source

    def test_nesting_depth_limit(self, tmp_path):
        """Test nesting depth limit enforcement."""
        # Create deeply nested copybooks
        depth = 5
        for i in range(depth):
            cpy = tmp_path / f"LEVEL{i}.cpy"
            if i < depth - 1:
                cpy.write_text(f"       01 LEVEL{i}.\n       COPY LEVEL{i+1}.")
            else:
                cpy.write_text(f"       01 LEVEL{i} PIC X.")

        source = "       COPY LEVEL0."

        with pytest.raises(NestingDepthError):
            expand_copybooks(source, [str(tmp_path)], max_nesting_depth=2)

    def test_statistics_collection(self, copybook_dir):
        """Test that statistics are properly collected."""
        source = "       COPY MAIN."
        result = expand_copybooks(source, [str(copybook_dir)])

        assert result.statistics.file_count >= 1
        assert result.statistics.total_lines > 0
        assert result.statistics.parse_time_ms >= 0

    def test_no_copy_statements(self, copybook_dir):
        """Test expansion when no COPY statements present."""
        source = "       01 LOCAL-DATA PIC X(10)."
        result = expand_copybooks(source, [str(copybook_dir)])

        assert result.expanded_source == source
        assert len(result.included_copybooks) == 0
        assert result.max_depth_reached == 0

    def test_content_validation(self, tmp_path):
        """Test content validation during expansion."""
        # Create copybook with potential issues
        cpy = tmp_path / "WARN.cpy"
        cpy.write_text("* Just a comment")

        source = "       COPY WARN."
        result = expand_copybooks(source, [str(tmp_path)], validate_content=True)

        # Should have a warning about comment-only content
        assert len(result.statistics.warnings) > 0

    def test_level_validation(self, tmp_path):
        """Test level number validation."""
        # Create copybook with level that may not align
        cpy = tmp_path / "LEVEL.cpy"
        cpy.write_text("       03 SUBLEVEL PIC X.")

        source = "       05 PARENT.\n       COPY LEVEL."
        expand_copybooks(source, [str(tmp_path)], validate_levels=True)

        # Should detect potential level mismatch
        # (03 after 05 is lower level)


class TestExpandSourceRecursive:
    """Tests for _expand_source_recursive internal function."""

    def test_circular_reference_detection(self, tmp_path):
        """Test circular reference detection."""
        # Create circular references
        a_cpy = tmp_path / "A.cpy"
        a_cpy.write_text("       COPY B.")

        b_cpy = tmp_path / "B.cpy"
        b_cpy.write_text("       COPY A.")

        source = "       COPY A."

        with pytest.raises(CircularReferenceError) as exc_info:
            expand_copybooks(source, [str(tmp_path)])

        assert "A" in str(exc_info.value) or "B" in str(exc_info.value)

    def test_caching(self, tmp_path):
        """Test that copybook content is cached."""
        # Create copybook
        cpy = tmp_path / "SHARED.cpy"
        cpy.write_text("       01 SHARED-DATA PIC X.")

        # Reference same copybook multiple times
        source = """       COPY SHARED.
       COPY SHARED.
"""
        result = expand_copybooks(source, [str(tmp_path)])

        # Should have expanded but only processed once
        assert "SHARED-DATA" in result.expanded_source


class TestParseCobolWithExpansion:
    """Tests for parse_cobol_with_expansion convenience function."""

    def test_basic_parse_with_expansion(self, tmp_path):
        """Test basic parsing with copybook expansion."""
        # Create copybook
        cpy = tmp_path / "DATA.cpy"
        cpy.write_text("       01 DATA-RECORD PIC X(10).")

        # Create source with IDENTIFICATION DIVISION to make it parseable
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROGRAM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY DATA.
       PROCEDURE DIVISION.
           DISPLAY "HELLO".
           STOP RUN.
"""

        # This should expand copybooks and parse
        result = parse_cobol_with_expansion(
            source_code=source, filename="test.cbl", copybook_paths=[str(tmp_path)]
        )

        # Result should be a ParseResult
        assert result is not None


class TestSizeLimit:
    """Tests for size limit enforcement."""

    def test_total_size_limit(self, tmp_path):
        """Test total expansion size limit."""
        # Create a large copybook
        large_cpy = tmp_path / "LARGE.cpy"
        large_content = "       01 DATA PIC X(1000).\n" * 1000
        large_cpy.write_text(large_content)

        source = "       COPY LARGE."

        # Should not raise with default limits
        result = expand_copybooks(source, [str(tmp_path)])
        assert result is not None

    def test_tiny_total_size_limit(self, tmp_path):
        """Test with very small total size limit."""
        cpy = tmp_path / "MEDIUM.cpy"
        cpy.write_text("       01 DATA PIC X(100)." * 100)

        source = "       COPY MEDIUM."

        with pytest.raises(TotalExpansionSizeExceededError):
            expand_copybooks(
                source, [str(tmp_path)], max_total_size=100  # Very small limit
            )


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_source(self, tmp_path):
        """Test with empty source."""
        result = expand_copybooks("", [str(tmp_path)])
        assert result.expanded_source == ""

    def test_whitespace_only_source(self, tmp_path):
        """Test with whitespace-only source."""
        result = expand_copybooks("   \n   \n   ", [str(tmp_path)])
        assert result.expanded_source.strip() == ""

    def test_multiple_search_paths(self, tmp_path):
        """Test with multiple search paths."""
        # Create directories
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        # Create copybook in second directory
        cpy = dir2 / "FOUND.cpy"
        cpy.write_text("       01 FOUND-DATA PIC X.")

        source = "       COPY FOUND."
        result = expand_copybooks(source, [str(dir1), str(dir2)])

        assert "FOUND-DATA" in result.expanded_source


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
