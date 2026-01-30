"""Integration tests for fixed-format COBOL auto-detection."""

import pytest
from pathlib import Path
from cobolparser import parse_cobol


class TestFixedFormatAutoDetection:
    """Test suite for automatic detection of fixed-format COBOL."""
    
    def test_ix103a_with_auto_detection(self):
        """Test that IX103A.CBL parses successfully with auto-detection."""
        filepath = Path(__file__).parent.parent.parent / "examples" / "cobol" / "IX103A.CBL"
        
        if not filepath.exists():
            pytest.skip(f"Test file not found: {filepath}")
        
        # Parse with auto-detection (default behavior)
        result = parse_cobol(str(filepath))
        
        # Should succeed
        assert result.success, f"Parsing failed with errors: {result.errors}"
        assert result.ast is not None, "AST should not be None"
        assert result.ast.program_name == "IX103A", f"Expected program name 'IX103A', got '{result.ast.program_name}'"
        
        # Should have parsed significant content
        assert result.statistics.lines_parsed > 0, "Should have parsed some lines"
        assert result.statistics.tokens_processed > 0, "Should have processed some tokens"
    
    def test_ix103a_with_explicit_preprocessing(self):
        """Test that IX103A.CBL parses with explicit preprocess_fixed=True."""
        filepath = Path(__file__).parent.parent.parent / "examples" / "cobol" / "IX103A.CBL"
        
        if not filepath.exists():
            pytest.skip(f"Test file not found: {filepath}")
        
        # Read the file content
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse with explicit preprocessing
        result = parse_cobol(content, filename=str(filepath), preprocess_fixed=True)
        
        # Should succeed
        assert result.success, f"Parsing failed with errors: {result.errors}"
        assert result.ast is not None, "AST should not be None"
    
    def test_ix103a_without_preprocessing_fails(self):
        """Test that IX103A.CBL fails without preprocessing (as expected)."""
        filepath = Path(__file__).parent.parent.parent / "examples" / "cobol" / "IX103A.CBL"
        
        if not filepath.exists():
            pytest.skip(f"Test file not found: {filepath}")
        
        # Read the file content
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse without preprocessing (should fail)
        result = parse_cobol(content, filename=str(filepath), preprocess_fixed=False)
        
        # Should fail
        assert not result.success, "Parsing should fail without preprocessing"
        assert result.ast is None, "AST should be None when parsing fails"
        assert len(result.errors) > 0, "Should have errors"
        
        # Should have the expected error about IDENTIFICATION DIVISION
        error_messages = [str(e) for e in result.errors]
        assert any("IDENTIFICATION DIVISION" in msg for msg in error_messages), \
            f"Expected error about IDENTIFICATION DIVISION, got: {error_messages}"
    
    def test_fixed_format_detection_with_sequence_numbers(self):
        """Test detection of fixed-format COBOL with sequence numbers."""
        # Sample fixed-format COBOL with sequence numbers
        fixed_format_code = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTPROG.
000300 PROCEDURE DIVISION.
000400     DISPLAY 'HELLO'.
000500     STOP RUN.
"""
        result = parse_cobol(fixed_format_code, filename="test.cbl")
        
        # Should succeed with auto-detection
        assert result.success, f"Auto-detection should work for fixed-format: {result.errors}"
        assert result.ast is not None
        assert result.ast.program_name == "TESTPROG"
    
    def test_fixed_format_detection_with_spaces(self):
        """Test detection of fixed-format COBOL with spaces in sequence area."""
        # Sample fixed-format COBOL with spaces instead of sequence numbers
        fixed_format_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           DISPLAY 'HELLO'.
           STOP RUN.
"""
        result = parse_cobol(fixed_format_code, filename="test.cbl")
        
        # Should succeed with auto-detection
        assert result.success, f"Auto-detection should work for fixed-format with spaces: {result.errors}"
        assert result.ast is not None
        assert result.ast.program_name == "TESTPROG"
    
    def test_free_format_not_detected_as_fixed(self):
        """Test that free-format COBOL is not incorrectly detected as fixed-format."""
        # Free-format COBOL (no sequence area)
        free_format_code = """IDENTIFICATION DIVISION.
PROGRAM-ID. TESTPROG.
PROCEDURE DIVISION.
    DISPLAY 'HELLO'.
    STOP RUN.
"""
        result = parse_cobol(free_format_code, filename="test.cbl")
        
        # Should succeed (either detected as free-format or parsed correctly anyway)
        assert result.success, f"Free-format should parse correctly: {result.errors}"
        assert result.ast is not None
        assert result.ast.program_name == "TESTPROG"
    
    def test_mixed_format_detection(self):
        """Test detection with mixed format (some lines with sequence, some without)."""
        # This is a tricky case - some lines have sequence numbers, some don't
        mixed_format_code = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
000400     DISPLAY 'HELLO'.
           STOP RUN.
"""
        result = parse_cobol(mixed_format_code, filename="test.cbl")
        
        # Should handle this gracefully (detection should work based on majority)
        # We don't assert success here because mixed format is ambiguous
        # Just ensure it doesn't crash
        assert result is not None


class TestOtherFixedFormatFiles:
    """Test other fixed-format COBOL files in the examples directory."""
    
    def test_ix108a_parsing(self):
        """Test that IX108A.CBL (another fixed-format file) parses correctly."""
        filepath = Path(__file__).parent.parent.parent / "examples" / "cobol" / "IX108A.CBL"
        
        if not filepath.exists():
            pytest.skip(f"Test file not found: {filepath}")
        
        result = parse_cobol(str(filepath))
        
        # Should succeed with auto-detection
        assert result.success, f"IX108A parsing failed: {result.errors}"
        assert result.ast is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
