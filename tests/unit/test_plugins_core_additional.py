"""
Additional unit tests for cobolparser.plugins.core module.
Targets remaining uncovered lines for 100% coverage.

This test module specifically targets:
- Line 13: TYPE_CHECKING import (conditional import)
- Lines 101-104: ParseError with SourceLocation parameter
- Line 124: ParseError __str__ with ValueError in conversion
- Lines 134-136: ParseError __str__ with TypeError
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import TYPE_CHECKING

from cobolparser.plugins.core import (
    ParseError,
    LexerError,
    MemoryConfiguration,
    ParseStatistics,
)


class TestParseErrorWithSourceLocation:
    """Tests for ParseError with SourceLocation parameter (lines 101-104)."""
    
    def test_parse_error_with_source_location_object(self):
        """Test ParseError initialized with SourceLocation object."""
        # Create a mock SourceLocation
        location = Mock()
        location.line = 15
        location.column = 25
        
        error = ParseError("Test error", location=location)
        
        assert error.message == "Test error"
        assert error.line == 15
        assert error.column == 25
    
    def test_parse_error_location_without_line_attr(self):
        """Test ParseError with location missing line attribute."""
        location = Mock(spec=[])  # No attributes
        
        error = ParseError("Test error", location=location)
        
        # Should fallback to default
        assert error.line == 0
    
    def test_parse_error_location_without_column_attr(self):
        """Test ParseError with location missing column attribute."""
        location = Mock()
        location.line = 10
        del location.column  # Remove column attribute
        
        error = ParseError("Test error", location=location)
        
        assert error.line == 10
        # Column should be default
    
    def test_parse_error_location_overrides_line_column(self):
        """Test that location parameter overrides line/column parameters."""
        location = Mock()
        location.line = 100
        location.column = 50
        
        # Pass both location and explicit line/column
        # Location should take precedence
        error = ParseError("Test error", line=5, column=10, location=location)
        
        assert error.line == 100
        assert error.column == 50


class TestParseErrorSetLine:
    """Tests for ParseError _set_line method."""
    
    def test_set_line_with_int(self):
        """Test _set_line with integer."""
        error = ParseError("Test")
        error._set_line(42)
        
        assert error.line == 42
    
    def test_set_line_with_string(self):
        """Test _set_line with string that can be converted to int."""
        error = ParseError("Test")
        error._set_line("123")
        
        assert error.line == 123
    
    def test_set_line_with_invalid_string(self):
        """Test _set_line with string that cannot be converted."""
        error = ParseError("Test")
        error._set_line("not_a_number")
        
        assert error.line == 0
    
    def test_set_line_with_none(self):
        """Test _set_line with None."""
        error = ParseError("Test", line=10)
        error._set_line(None)
        
        assert error.line == 0
    
    def test_set_line_via_property(self):
        """Test setting line via property setter."""
        error = ParseError("Test")
        error.line = 50
        
        assert error.line == 50
    
    def test_set_line_via_property_with_string(self):
        """Test setting line via property with string."""
        error = ParseError("Test")
        error.line = "75"
        
        assert error.line == 75


class TestParseErrorSetColumn:
    """Tests for ParseError _set_column method."""
    
    def test_set_column_with_int(self):
        """Test _set_column with integer."""
        error = ParseError("Test")
        error._set_column(15)
        
        assert error.column == 15
    
    def test_set_column_with_string(self):
        """Test _set_column with string that can be converted."""
        error = ParseError("Test")
        error._set_column("25")
        
        assert error.column == 25
    
    def test_set_column_with_invalid_string(self):
        """Test _set_column with invalid string."""
        error = ParseError("Test")
        error._set_column("invalid")
        
        assert error.column == 0
    
    def test_set_column_with_none(self):
        """Test _set_column with None."""
        error = ParseError("Test", column=20)
        error._set_column(None)
        
        assert error.column == 0
    
    def test_set_column_via_property(self):
        """Test setting column via property setter."""
        error = ParseError("Test")
        error.column = 30
        
        assert error.column == 30


class TestParseErrorStr:
    """Tests for ParseError __str__ method error handling."""
    
    def test_str_with_valid_values(self):
        """Test __str__ with valid line and column."""
        error = ParseError("Syntax error", line=10, column=5)
        result = str(error)
        
        assert result == "Line 10, Column 5: Syntax error"
    
    def test_str_with_zero_line(self):
        """Test __str__ with zero line (should show message only)."""
        error = ParseError("Error message", line=0)
        result = str(error)
        
        assert result == "Error message"
    
    def test_str_with_negative_line(self):
        """Test __str__ with negative line."""
        error = ParseError("Error message")
        error._line = -1
        result = str(error)
        
        # Negative line treated as no line info
        assert result == "Error message"
    
    def test_str_handles_value_error(self):
        """Test __str__ handles ValueError in int conversion (line 124)."""
        error = ParseError("Error message")
        # Manually set to a value that would cause int() to fail
        error._line = "not_convertible"
        
        result = str(error)
        
        # Should fallback to just message
        assert result == "Error message"
    
    def test_str_handles_type_error(self):
        """Test __str__ handles TypeError (lines 134-136)."""
        error = ParseError("Error message")
        # Set to an object that would cause TypeError in int()
        error._line = Mock()  # Mock object can't be converted to int
        
        result = str(error)
        
        # Should fallback to just message
        assert result == "Error message"
    
    def test_str_with_none_line(self):
        """Test __str__ when line is None."""
        error = ParseError("Error message")
        error._line = None
        
        result = str(error)
        
        # None line should show message only
        assert result == "Error message"
    
    def test_str_with_none_column(self):
        """Test __str__ when column is None but line is valid."""
        error = ParseError("Error message", line=5)
        error._column = None
        
        result = str(error)
        
        # Should handle None column gracefully
        # Could either show "Line 5, Column 0:" or just the message
        assert "Error message" in result


class TestLexerErrorInheritance:
    """Tests for LexerError inheriting ParseError behavior."""
    
    def test_lexer_error_with_location(self):
        """Test LexerError with SourceLocation."""
        location = Mock()
        location.line = 20
        location.column = 15
        
        error = LexerError("Invalid token", location=location)
        
        assert error.line == 20
        assert error.column == 15
        assert str(error) == "Line 20, Column 15: Invalid token"


class TestMemoryConfigurationEdgeCases:
    """Additional edge case tests for MemoryConfiguration."""
    
    def test_memory_config_at_minimum_boundary(self):
        """Test configuration exactly at minimum boundary."""
        config = MemoryConfiguration(max_memory_mb=64)
        assert config.max_memory_mb == 64
    
    def test_memory_config_at_maximum_boundary(self):
        """Test configuration exactly at maximum boundary."""
        config = MemoryConfiguration(max_memory_mb=8192)
        assert config.max_memory_mb == 8192
    
    def test_chunk_size_minimum(self):
        """Test minimum valid chunk size."""
        config = MemoryConfiguration(chunk_size_kb=1)
        assert config.chunk_size_kb == 1


class TestParseStatisticsEdgeCases:
    """Additional edge case tests for ParseStatistics."""
    
    def test_stats_timing_very_short_duration(self):
        """Test timing with very short duration."""
        stats = ParseStatistics()
        
        with patch('time.time', side_effect=[1000.0, 1000.001]):
            stats.start_timing()
            stats.end_timing()
        
        assert stats.parse_time_seconds == pytest.approx(0.001, abs=0.0001)
        assert stats.total_time_ms == pytest.approx(1.0, abs=0.1)
    
    def test_stats_all_fields_set(self):
        """Test setting all statistics fields."""
        stats = ParseStatistics()
        
        stats.lines_processed = 1000
        stats.lines_parsed = 950
        stats.tokens_processed = 5000
        stats.memory_peak_mb = 256.5
        stats.parse_time_seconds = 2.5
        stats.total_time_ms = 2500.0
        stats.error_count = 5
        stats.warning_count = 10
        
        result = stats.to_dict()
        
        assert result["lines_processed"] == 1000
        assert result["lines_parsed"] == 950
        assert result["tokens_processed"] == 5000
        assert result["memory_peak_mb"] == 256.5
        assert result["parse_time_seconds"] == 2.5
        assert result["total_time_ms"] == 2500.0
        assert result["error_count"] == 5
        assert result["warning_count"] == 10


class TestTypeCheckingImport:
    """Tests verifying TYPE_CHECKING usage."""
    
    def test_source_location_type_hint_works(self):
        """Test that SourceLocation type hint is properly used."""
        # This test verifies that the TYPE_CHECKING import (line 13)
        # is used correctly for type hints
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1)
        error = ParseError("Test", location=location)
        
        assert error.line == 1
        assert error.column == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
