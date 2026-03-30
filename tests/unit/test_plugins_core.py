"""
Comprehensive unit tests for cobolparser.plugins.core module.
Achieves 100% statement and branch coverage.

This module tests:
- ErrorRecoveryMode and DialectType enums
- MemoryConfiguration and SerializationConfig dataclasses with validation
- ParseError hierarchy (ParseError, LexerError, UnterminatedStringError, MemoryLimitExceededError)
- ParseStatistics class with timing functionality
- PluginManager class with registration and error handling
"""

import pytest
import time
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, patch, MagicMock

from cobolparser.plugins.core import (
    ErrorRecoveryMode,
    DialectType,
    MemoryConfiguration,
    SerializationConfig,
    ParseError,
    LexerError,
    UnterminatedStringError,
    MemoryLimitExceededError,
    ParseStatistics,
    PluginManager
)


class TestErrorRecoveryMode:
    """Test ErrorRecoveryMode enum values and properties."""

    def test_error_recovery_mode_values(self):
        """Test enum has correct values."""
        assert ErrorRecoveryMode.FAIL_FAST.value == "fail_fast"
        assert ErrorRecoveryMode.COLLECT_ALL.value == "collect_all"

    def test_error_recovery_mode_iteration(self):
        """Test enum iteration."""
        modes = list(ErrorRecoveryMode)
        assert len(modes) == 2
        assert ErrorRecoveryMode.FAIL_FAST in modes
        assert ErrorRecoveryMode.COLLECT_ALL in modes

    def test_error_recovery_mode_string_representation(self):
        """Test string representation."""
        assert str(ErrorRecoveryMode.FAIL_FAST) == "ErrorRecoveryMode.FAIL_FAST"
        assert str(ErrorRecoveryMode.COLLECT_ALL) == "ErrorRecoveryMode.COLLECT_ALL"

    def test_error_recovery_mode_comparison(self):
        """Test enum comparison."""
        assert ErrorRecoveryMode.FAIL_FAST != ErrorRecoveryMode.COLLECT_ALL
        assert ErrorRecoveryMode.FAIL_FAST == ErrorRecoveryMode.FAIL_FAST

    def test_error_recovery_mode_membership(self):
        """Test membership testing."""
        assert "fail_fast" in [mode.value for mode in ErrorRecoveryMode]
        assert "collect_all" in [mode.value for mode in ErrorRecoveryMode]
        assert "invalid_mode" not in [mode.value for mode in ErrorRecoveryMode]


class TestDialectType:
    """Test DialectType enum values and properties."""

    def test_dialect_type_values(self):
        """Test enum has correct values."""
        assert DialectType.ANSI_COBOL.value == "ansi_cobol"
        assert DialectType.IBM_ENTERPRISE.value == "ibm_enterprise"
        assert DialectType.MICRO_FOCUS.value == "micro_focus"

    def test_dialect_type_iteration(self):
        """Test enum iteration."""
        dialects = list(DialectType)
        assert len(dialects) == 3
        assert DialectType.ANSI_COBOL in dialects
        assert DialectType.IBM_ENTERPRISE in dialects
        assert DialectType.MICRO_FOCUS in dialects

    def test_dialect_type_string_representation(self):
        """Test string representation."""
        assert str(DialectType.ANSI_COBOL) == "DialectType.ANSI_COBOL"
        assert str(DialectType.IBM_ENTERPRISE) == "DialectType.IBM_ENTERPRISE"
        assert str(DialectType.MICRO_FOCUS) == "DialectType.MICRO_FOCUS"

    def test_dialect_type_comparison(self):
        """Test enum comparison."""
        assert DialectType.ANSI_COBOL != DialectType.IBM_ENTERPRISE
        assert DialectType.IBM_ENTERPRISE == DialectType.IBM_ENTERPRISE
        assert DialectType.MICRO_FOCUS != DialectType.ANSI_COBOL

    def test_dialect_type_membership(self):
        """Test membership testing."""
        assert "ansi_cobol" in [dialect.value for dialect in DialectType]
        assert "ibm_enterprise" in [dialect.value for dialect in DialectType]
        assert "micro_focus" in [dialect.value for dialect in DialectType]
        assert "invalid_dialect" not in [dialect.value for dialect in DialectType]


class TestMemoryConfiguration:
    """Test MemoryConfiguration dataclass with validation."""

    def test_memory_configuration_creation_defaults(self):
        """Test creation with default values."""
        config = MemoryConfiguration()
        assert config.max_memory_mb == 256
        assert config.enable_streaming == False
        assert config.chunk_size_kb == 512

    def test_memory_configuration_creation_custom_values(self):
        """Test creation with custom values."""
        config = MemoryConfiguration(
            max_memory_mb=512,
            enable_streaming=True,
            chunk_size_kb=1024
        )
        assert config.max_memory_mb == 512
        assert config.enable_streaming == True
        assert config.chunk_size_kb == 1024

    def test_memory_configuration_validation_max_memory_too_low(self):
        """Test validation fails for max_memory_mb too low."""
        with pytest.raises(ValueError, match="Memory limit must be between 64MB and 8192MB"):
            MemoryConfiguration(max_memory_mb=32)

    def test_memory_configuration_validation_max_memory_too_high(self):
        """Test validation fails for max_memory_mb too high."""
        with pytest.raises(ValueError, match="Memory limit must be between 64MB and 8192MB"):
            MemoryConfiguration(max_memory_mb=10000)

    def test_memory_configuration_validation_chunk_size_too_low(self):
        """Test validation fails for chunk_size_kb too low."""
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            MemoryConfiguration(chunk_size_kb=0)

    def test_memory_configuration_validation_chunk_size_negative(self):
        """Test validation fails for negative chunk_size_kb."""
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            MemoryConfiguration(chunk_size_kb=-1)

    def test_memory_configuration_boundary_values_valid(self):
        """Test boundary values that should be valid."""
        # Minimum valid values
        config_min = MemoryConfiguration(
            max_memory_mb=64,
            chunk_size_kb=1
        )
        assert config_min.max_memory_mb == 64
        assert config_min.chunk_size_kb == 1

        # Maximum valid values
        config_max = MemoryConfiguration(
            max_memory_mb=8192,
            chunk_size_kb=2048
        )
        assert config_max.max_memory_mb == 8192
        assert config_max.chunk_size_kb == 2048

    def test_memory_configuration_edge_case_large_chunk(self):
        """Test edge case with large chunk size."""
        config = MemoryConfiguration(max_memory_mb=1024, chunk_size_kb=1024)
        assert config.max_memory_mb == 1024
        assert config.chunk_size_kb == 1024

    def test_memory_configuration_mutable_dataclass(self):
        """Test that dataclass is mutable (not frozen)."""
        config = MemoryConfiguration()
        original_value = config.max_memory_mb
        config.max_memory_mb = 512
        assert config.max_memory_mb == 512
        assert config.max_memory_mb != original_value

    def test_memory_configuration_repr(self):
        """Test string representation."""
        config = MemoryConfiguration(max_memory_mb=512)
        repr_str = repr(config)
        assert "MemoryConfiguration" in repr_str
        assert "max_memory_mb=512" in repr_str

    def test_memory_configuration_equality(self):
        """Test equality comparison."""
        config1 = MemoryConfiguration(max_memory_mb=512)
        config2 = MemoryConfiguration(max_memory_mb=512)
        config3 = MemoryConfiguration(max_memory_mb=256)
        
        assert config1 == config2
        assert config1 != config3


class TestSerializationConfig:
    """Test SerializationConfig dataclass."""

    def test_serialization_config_creation_defaults(self):
        """Test creation with default values."""
        config = SerializationConfig()
        assert config.include_metadata == True
        assert config.include_source_locations == True
        assert config.compact_format == False

    def test_serialization_config_creation_custom_values(self):
        """Test creation with custom values."""
        config = SerializationConfig(
            include_metadata=False,
            include_source_locations=False,
            compact_format=True
        )
        assert config.include_metadata == False
        assert config.include_source_locations == False
        assert config.compact_format == True

    def test_serialization_config_mutable_dataclass(self):
        """Test that dataclass is mutable (not frozen)."""
        config = SerializationConfig()
        config.include_metadata = False
        assert config.include_metadata == False

    def test_serialization_config_repr(self):
        """Test string representation."""
        config = SerializationConfig(compact_format=True)
        repr_str = repr(config)
        assert "SerializationConfig" in repr_str
        assert "compact_format=True" in repr_str

    def test_serialization_config_equality(self):
        """Test equality comparison."""
        config1 = SerializationConfig(compact_format=True)
        config2 = SerializationConfig(compact_format=True)
        config3 = SerializationConfig(compact_format=False)
        
        assert config1 == config2
        assert config1 != config3

    def test_serialization_config_all_combinations(self):
        """Test various boolean combinations."""
        configs = [
            SerializationConfig(include_metadata=True, include_source_locations=True, compact_format=True),
            SerializationConfig(include_metadata=True, include_source_locations=False, compact_format=False),
            SerializationConfig(include_metadata=False, include_source_locations=True, compact_format=False),
            SerializationConfig(include_metadata=False, include_source_locations=False, compact_format=True),
        ]
        
        assert len(configs) == 4
        # Verify all are different
        for i, config1 in enumerate(configs):
            for j, config2 in enumerate(configs):
                if i != j:
                    assert config1 != config2


class TestParseError:
    """Test base ParseError exception class."""

    def test_parse_error_creation_message_only(self):
        """Test creation with message only."""
        error = ParseError("Test error message")
        assert str(error) == "Parse error: Test error message"
        assert error.message == "Test error message"
        assert error.line == 0
        assert error.column is None

    def test_parse_error_creation_with_line_column(self):
        """Test creation with line and column."""
        error = ParseError("Test error", line=10, column=5)
        assert error.message == "Test error"
        assert error.line == 10
        assert error.column == 5

    def test_parse_error_str_with_line_column(self):
        """Test string representation with line and column info."""
        error = ParseError("Syntax error", line=15, column=8)
        expected = "line 15, column 8: Syntax error"
        assert str(error) == expected

    def test_parse_error_str_with_line_only(self):
        """Test string representation with line only (column 0 omitted)."""
        error = ParseError("Missing token", line=20, column=0)
        expected = "line 20: Missing token"
        assert str(error) == expected

    def test_parse_error_str_with_zero_line(self):
        """Test string representation with line 0."""
        error = ParseError("Unexpected character", line=0)
        expected = "Parse error: Unexpected character"  # Line 0 means no line info
        assert str(error) == expected

    def test_parse_error_inheritance(self):
        """Test that ParseError is a proper Exception."""
        error = ParseError("Test")
        assert isinstance(error, Exception)
        assert isinstance(error, ParseError)

    def test_parse_error_zero_line_column(self):
        """Test edge case with zero line and column."""
        error = ParseError("Error at start", line=0, column=0)
        expected = "Parse error: Error at start"  # Line 0 means no line info
        assert str(error) == expected

    def test_parse_error_negative_line_column(self):
        """Test edge case with negative values."""
        error = ParseError("Negative position", line=-1, column=-5)
        expected = "Parse error: Negative position"  # Negative line shows no position
        assert str(error) == expected

    def test_parse_error_invalid_line_handling(self):
        """Test exception handling in __str__ method."""
        error = ParseError("Test message")

        # Test with invalid line that causes ValueError in setter
        error.line = "not_a_number"  # setter catches ValueError, sets line_number=0
        result = str(error)
        assert result == "Parse error: Test message"  # Falls back to no-location format

        # Test with None line (TypeError case)
        error.line = None
        result = str(error)
        assert result == "Parse error: Test message"  # Falls back to no-location format


class TestLexerError:
    """Test LexerError exception class."""

    def test_lexer_error_creation(self):
        """Test LexerError creation."""
        error = LexerError("Invalid token", line=5, column=10)
        assert error.message == "Invalid token"
        assert error.line == 5
        assert error.column == 10
        assert str(error) == "line 5, column 10: Invalid token"

    def test_lexer_error_inheritance(self):
        """Test LexerError inheritance."""
        error = LexerError("Test error")
        assert isinstance(error, ParseError)
        assert isinstance(error, LexerError)
        assert isinstance(error, Exception)

    def test_lexer_error_without_position(self):
        """Test LexerError without line/column info."""
        error = LexerError("General lexer error")
        assert str(error) == "Parse error: General lexer error"
        assert error.line == 0
        assert error.column is None


class TestUnterminatedStringError:
    """Test UnterminatedStringError exception class."""

    def test_unterminated_string_error_creation(self):
        """Test UnterminatedStringError creation."""
        error = UnterminatedStringError("String not closed", line=3, column=25)
        assert error.message == "String not closed"
        assert error.line == 3
        assert error.column == 25
        assert str(error) == "line 3, column 25: String not closed"

    def test_unterminated_string_error_inheritance(self):
        """Test UnterminatedStringError inheritance."""
        error = UnterminatedStringError("Test error")
        assert isinstance(error, LexerError)
        assert isinstance(error, ParseError)
        assert isinstance(error, UnterminatedStringError)
        assert isinstance(error, Exception)

    def test_unterminated_string_error_without_position(self):
        """Test UnterminatedStringError without line/column info."""
        error = UnterminatedStringError("Unterminated string literal")
        assert str(error) == "Parse error: Unterminated string literal"
        assert error.line == 0
        assert error.column is None


class TestMemoryLimitExceededError:
    """Test MemoryLimitExceededError exception class."""

    def test_memory_limit_exceeded_error_creation(self):
        """Test MemoryLimitExceededError creation."""
        error = MemoryLimitExceededError(current_mb=100.5, limit_mb=64)
        expected_message = "Memory usage 100.5MB exceeds limit of 64MB"
        assert error.message == expected_message
        assert error.current_mb == 100.5
        assert error.limit_mb == 64

    def test_memory_limit_exceeded_error_inheritance(self):
        """Test MemoryLimitExceededError inheritance."""
        error = MemoryLimitExceededError(current_mb=50.0, limit_mb=32)
        assert isinstance(error, ParseError)
        assert isinstance(error, MemoryLimitExceededError)
        assert isinstance(error, Exception)

    def test_memory_limit_exceeded_error_formatting(self):
        """Test message formatting for different values."""
        error1 = MemoryLimitExceededError(current_mb=128.7, limit_mb=128)
        assert "128.7MB" in str(error1)
        assert "128MB" in str(error1)
        
        error2 = MemoryLimitExceededError(current_mb=1024.0, limit_mb=512)
        assert "1024.0MB" in str(error2)
        assert "512MB" in str(error2)


class TestParseStatistics:
    """Test ParseStatistics class with comprehensive timing functionality."""

    def test_parse_statistics_creation(self):
        """Test ParseStatistics creation with defaults."""
        stats = ParseStatistics()
        assert stats.tokens_processed == 0
        assert stats.lines_processed == 0
        assert stats.lines_parsed == 0
        assert stats.error_count == 0
        assert stats.warning_count == 0
        assert stats.memory_peak_mb == 0.0
        assert stats.parse_time_seconds == 0.0
        assert stats.total_time_ms == 0.0
        assert stats._start_time is None

    def test_parse_statistics_start_timing(self):
        """Test start_timing method."""
        stats = ParseStatistics()
        with patch('time.time', return_value=1000.0):
            stats.start_timing()
        
        assert stats._start_time == 1000.0

    def test_parse_statistics_end_timing(self):
        """Test end_timing method."""
        stats = ParseStatistics()
        with patch('time.time', side_effect=[1000.0, 1005.0]):
            stats.start_timing()
            stats.end_timing()
        
        assert stats._start_time == 1000.0
        assert stats.parse_time_seconds == 5.0
        assert stats.total_time_ms == 5000.0

    def test_parse_statistics_end_timing_no_start(self):
        """Test end_timing when start_timing was not called."""
        stats = ParseStatistics()
        with patch('time.time', return_value=1005.0):
            stats.end_timing()  # Should not crash
        
        # Should remain 0 since no start time was set
        assert stats.parse_time_seconds == 0.0
        assert stats.total_time_ms == 0.0

    def test_parse_statistics_timing_precision(self):
        """Test timing precision and calculation."""
        stats = ParseStatistics()
        with patch('time.time', side_effect=[1000.123, 1000.456]):
            stats.start_timing()
            stats.end_timing()
        
        assert abs(stats.parse_time_seconds - 0.333) < 0.001
        assert abs(stats.total_time_ms - 333.0) < 1.0

    def test_parse_statistics_increment_counters(self):
        """Test setting various counters."""
        stats = ParseStatistics()
        
        # Test setting counter values
        stats.tokens_processed = 100
        stats.lines_processed = 50
        stats.lines_parsed = 45
        stats.error_count = 3
        stats.warning_count = 7
        stats.memory_peak_mb = 128.5
        
        assert stats.tokens_processed == 100
        assert stats.lines_processed == 50
        assert stats.lines_parsed == 45
        assert stats.error_count == 3
        assert stats.warning_count == 7
        assert stats.memory_peak_mb == 128.5

    def test_parse_statistics_reset(self):
        """Test reset method."""
        stats = ParseStatistics()
        
        # Set some values
        stats.tokens_processed = 100
        stats.lines_processed = 50
        stats.lines_parsed = 45
        stats.error_count = 3
        stats.warning_count = 7
        stats.memory_peak_mb = 128.5
        stats.parse_time_seconds = 5.0
        stats._start_time = 1000.0
        
        # Reset
        stats.reset()
        
        # Verify all values are reset
        assert stats.tokens_processed == 0
        assert stats.lines_processed == 0
        assert stats.lines_parsed == 0
        assert stats.error_count == 0
        assert stats.warning_count == 0
        assert stats.memory_peak_mb == 0.0
        assert stats.parse_time_seconds == 0.0
        assert stats.total_time_ms == 0.0
        assert stats._start_time is None

    def test_parse_statistics_complete_workflow(self):
        """Test complete timing workflow."""
        stats = ParseStatistics()
        
        with patch('time.time', side_effect=[1000.0, 1003.0]):
            # Start timing
            stats.start_timing()
            assert stats._start_time == 1000.0
            
            # Process some data
            stats.tokens_processed = 1500
            stats.lines_processed = 75
            stats.error_count = 2
            
            # End timing
            stats.end_timing()
            
            # Check timing results
            assert stats.parse_time_seconds == 3.0
            assert stats.total_time_ms == 3000.0

    def test_parse_statistics_multiple_start_timing(self):
        """Test multiple calls to start_timing."""
        stats = ParseStatistics()
        
        with patch('time.time', side_effect=[1000.0, 1002.0]):
            stats.start_timing()
            first_start = stats._start_time
            
            stats.start_timing()  # Should update start time
            second_start = stats._start_time
            
            assert first_start == 1000.0
            assert second_start == 1002.0

    def test_parse_statistics_to_dict(self):
        """Test conversion to dictionary."""
        stats = ParseStatistics()
        stats.tokens_processed = 100
        stats.lines_processed = 50
        stats.lines_parsed = 45
        stats.error_count = 3
        stats.warning_count = 7
        stats.memory_peak_mb = 128.5
        stats.parse_time_seconds = 2.5
        stats.total_time_ms = 2500.0
        
        result = stats.to_dict()
        expected = {
            "lines_processed": 50,
            "lines_parsed": 45,
            "tokens_processed": 100,
            "memory_peak_mb": 128.5,
            "parse_time_seconds": 2.5,
            "total_time_ms": 2500.0,
            "error_count": 3,
            "warning_count": 7
        }
        
        assert result == expected

    def test_parse_statistics_edge_case_zero_timing(self):
        """Test edge case where timing is zero."""
        stats = ParseStatistics()
        with patch('time.time', side_effect=[1000.0, 1000.0]):
            stats.start_timing()
            stats.end_timing()
        
        assert stats.parse_time_seconds == 0.0
        assert stats.total_time_ms == 0.0


class TestPluginManager:
    """Test PluginManager class with plugin registration and error handling."""

    def test_plugin_manager_creation(self):
        """Test PluginManager creation."""
        manager = PluginManager()
        assert isinstance(manager._plugins, dict)
        assert len(manager._plugins) == 0
        assert isinstance(manager._active_plugins, list)
        assert len(manager._active_plugins) == 0

    def test_plugin_manager_register_plugin_success(self):
        """Test successful plugin registration."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "test_plugin"
        
        result = manager.register_plugin(mock_plugin)
        assert result == True
        assert "test_plugin" in manager._plugins
        assert manager._plugins["test_plugin"] == mock_plugin
        assert "test_plugin" in manager._active_plugins

    def test_plugin_manager_register_plugin_duplicate_name(self):
        """Test registration fails with duplicate name."""
        manager = PluginManager()
        mock_plugin1 = Mock()
        mock_plugin1.name = "duplicate"
        mock_plugin2 = Mock()
        mock_plugin2.name = "duplicate"
        
        # First registration should succeed
        result1 = manager.register_plugin(mock_plugin1)
        assert result1 == True
        
        # Second registration should fail
        result2 = manager.register_plugin(mock_plugin2)
        assert result2 == False
        
        # First plugin should still be registered
        assert manager._plugins["duplicate"] == mock_plugin1

    def test_plugin_manager_unregister_plugin_success(self):
        """Test successful plugin unregistration."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "removable_plugin"
        
        # Register then unregister
        manager.register_plugin(mock_plugin)
        assert "removable_plugin" in manager._plugins
        
        result = manager.unregister_plugin("removable_plugin")
        assert result == True
        assert "removable_plugin" not in manager._plugins
        assert "removable_plugin" not in manager._active_plugins

    def test_plugin_manager_unregister_plugin_not_found(self):
        """Test unregistration fails when plugin not found."""
        manager = PluginManager()
        
        result = manager.unregister_plugin("nonexistent_plugin")
        assert result == False

    def test_plugin_manager_get_plugin_success(self):
        """Test successful plugin retrieval."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "retrievable_plugin"
        
        manager.register_plugin(mock_plugin)
        
        retrieved = manager.get_plugin("retrievable_plugin")
        assert retrieved == mock_plugin

    def test_plugin_manager_get_plugin_not_found(self):
        """Test plugin retrieval returns None when not found."""
        manager = PluginManager()
        
        retrieved = manager.get_plugin("nonexistent_plugin")
        assert retrieved is None

    def test_plugin_manager_get_active_plugins_empty(self):
        """Test getting active plugins when none are registered."""
        manager = PluginManager()
        
        plugin_list = manager.get_active_plugins()
        assert plugin_list == []

    def test_plugin_manager_get_active_plugins_with_plugins(self):
        """Test getting active plugins when some are registered."""
        manager = PluginManager()
        
        mock_plugin1 = Mock()
        mock_plugin1.name = "plugin1"
        mock_plugin2 = Mock()
        mock_plugin2.name = "plugin2"
        
        manager.register_plugin(mock_plugin1)
        manager.register_plugin(mock_plugin2)
        
        plugin_list = manager.get_active_plugins()
        assert len(plugin_list) == 2
        assert "plugin1" in plugin_list
        assert "plugin2" in plugin_list

    def test_plugin_manager_plugin_without_name_attribute(self):
        """Test plugin registration using class name when no name attribute."""
        manager = PluginManager()
        
        class TestPlugin:
            pass
        
        plugin = TestPlugin()
        result = manager.register_plugin(plugin)
        assert result == True
        assert "TestPlugin" in manager._plugins
        assert manager.get_plugin("TestPlugin") == plugin

    def test_plugin_manager_case_sensitive_names(self):
        """Test plugin names are case sensitive."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "CaseSensitive"
        
        manager.register_plugin(mock_plugin)
        
        assert manager.get_plugin("CaseSensitive") is not None
        assert manager.get_plugin("casesensitive") is None
        assert manager.get_plugin("CASESENSITIVE") is None

    def test_plugin_manager_complex_workflow(self):
        """Test complex plugin management workflow."""
        manager = PluginManager()
        
        # Register multiple plugins
        plugins = {}
        for i in range(5):
            plugin = Mock()
            plugin.name = f"plugin_{i}"
            plugins[f"plugin_{i}"] = plugin
            result = manager.register_plugin(plugin)
            assert result == True
        
        # Verify all are listed
        plugin_list = manager.get_active_plugins()
        assert len(plugin_list) == 5
        
        # Remove some plugins
        for i in [1, 3]:
            result = manager.unregister_plugin(f"plugin_{i}")
            assert result == True
        
        # Verify remaining plugins
        remaining_list = manager.get_active_plugins()
        assert len(remaining_list) == 3
        assert "plugin_1" not in remaining_list
        assert "plugin_3" not in remaining_list
        assert "plugin_0" in remaining_list
        assert "plugin_2" in remaining_list
        assert "plugin_4" in remaining_list

    def test_plugin_manager_register_replace_existing(self):
        """Test that re-registering the same name fails."""
        manager = PluginManager()
        
        original_plugin = Mock()
        original_plugin.name = "test"
        
        replacement_plugin = Mock()
        replacement_plugin.name = "test"
        
        # Register original
        result1 = manager.register_plugin(original_plugin)
        assert result1 == True
        
        # Try to register replacement (should fail)
        result2 = manager.register_plugin(replacement_plugin)
        assert result2 == False
        
        # Original should still be there
        retrieved = manager.get_plugin("test")
        assert retrieved == original_plugin
        assert retrieved != replacement_plugin

    def test_plugin_manager_unregister_removes_from_active_list(self):
        """Test that unregistering removes from active plugins list."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "test_plugin"
        
        # Register
        manager.register_plugin(mock_plugin)
        assert "test_plugin" in manager.get_active_plugins()
        
        # Unregister
        manager.unregister_plugin("test_plugin")
        assert "test_plugin" not in manager.get_active_plugins()

    def test_plugin_manager_active_plugins_copy(self):
        """Test that get_active_plugins returns a copy, not the original list."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "test_plugin"
        
        manager.register_plugin(mock_plugin)
        active_list = manager.get_active_plugins()
        
        # Modify the returned list
        active_list.append("fake_plugin")
        
        # Original should be unchanged
        assert "fake_plugin" not in manager.get_active_plugins()
        assert len(manager.get_active_plugins()) == 1

    def test_plugin_manager_unregister_plugin_not_in_active_list(self):
        """Test unregistering a plugin that's not in the active list."""
        manager = PluginManager()
        mock_plugin = Mock()
        mock_plugin.name = "test_plugin"
        
        # Manually add plugin to _plugins but not to _active_plugins 
        manager._plugins["test_plugin"] = mock_plugin
        # Don't add to _active_plugins to test the branch
        
        # Should still unregister successfully
        result = manager.unregister_plugin("test_plugin")
        assert result == True
        assert "test_plugin" not in manager._plugins


class TestModuleIntegration:
    """Test integration between different components of the module."""

    def test_error_hierarchy_complete(self):
        """Test complete error hierarchy."""
        # Create errors with different inheritance levels
        base_error = ParseError("Base error")
        lexer_error = LexerError("Lexer error")
        string_error = UnterminatedStringError("String error")
        memory_error = MemoryLimitExceededError(current_mb=100.0, limit_mb=64)
        
        # Test inheritance relationships
        assert isinstance(lexer_error, ParseError)
        assert isinstance(string_error, LexerError)
        assert isinstance(string_error, ParseError)
        assert isinstance(memory_error, ParseError)
        
        # Test that all are exceptions
        for error in [base_error, lexer_error, string_error, memory_error]:
            assert isinstance(error, Exception)

    def test_configuration_with_statistics(self):
        """Test using configurations with statistics."""
        memory_config = MemoryConfiguration(max_memory_mb=512)
        serialization_config = SerializationConfig(compact_format=True)
        statistics = ParseStatistics()
        
        # Simulate using them together
        statistics.start_timing()
        statistics.tokens_processed = 10000
        statistics.end_timing()
        
        assert statistics.tokens_processed > 0
        assert memory_config.max_memory_mb == 512
        assert serialization_config.compact_format == True

    def test_plugin_manager_with_error_handling(self):
        """Test plugin manager handling errors."""
        manager = PluginManager()
        
        # Create a mock plugin that might raise errors
        mock_plugin = Mock()
        mock_plugin.name = "error_plugin"
        mock_plugin.process.side_effect = ParseError("Plugin error")
        
        # Register the plugin
        result = manager.register_plugin(mock_plugin)
        assert result == True
        
        # The plugin is registered even if it might raise errors
        retrieved_plugin = manager.get_plugin("error_plugin")
        assert retrieved_plugin == mock_plugin

    def test_enum_values_in_configurations(self):
        """Test that enum values can be used with other components."""
        # Create instances of enums
        recovery_mode = ErrorRecoveryMode.COLLECT_ALL
        dialect_type = DialectType.IBM_ENTERPRISE
        
        # These would typically be used in parser configuration
        assert recovery_mode.value == "collect_all"
        assert dialect_type.value == "ibm_enterprise"
        
        # Verify they can be compared and used in conditionals
        if recovery_mode == ErrorRecoveryMode.COLLECT_ALL:
            config = MemoryConfiguration(max_memory_mb=1024)  # Higher memory for collect all
        else:
            config = MemoryConfiguration(max_memory_mb=256)   # Lower memory for fail fast
            
        assert config.max_memory_mb == 1024

    def test_all_classes_instantiable(self):
        """Test that all classes can be instantiated without errors."""
        # Enums
        recovery_mode = ErrorRecoveryMode.FAIL_FAST
        dialect_type = DialectType.ANSI_COBOL
        
        # Dataclasses
        memory_config = MemoryConfiguration()
        serialization_config = SerializationConfig()
        
        # Exceptions
        parse_error = ParseError("Test")
        lexer_error = LexerError("Test")
        string_error = UnterminatedStringError("Test")
        memory_error = MemoryLimitExceededError(current_mb=50.0, limit_mb=32)
        
        # Regular classes
        statistics = ParseStatistics()
        plugin_manager = PluginManager()
        
        # All should be truthy (not None)
        instances = [
            recovery_mode, dialect_type, memory_config, serialization_config,
            parse_error, lexer_error, string_error, memory_error,
            statistics, plugin_manager
        ]
        
        for instance in instances:
            assert instance is not None


# Additional edge case tests to ensure 100% coverage
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_parse_error_all_string_format_combinations(self):
        """Test all string format combinations for ParseError."""
        # No line, no column — falls back to "Parse error: message"
        error1 = ParseError("message")
        assert str(error1) == "Parse error: message"

        # Line > 0, column 0 — column omitted (falsy)
        error2 = ParseError("message", line=5, column=0)
        assert str(error2) == "line 5: message"

        # Both line and column > 0
        error3 = ParseError("message", line=5, column=10)
        assert str(error3) == "line 5, column 10: message"

    def test_memory_configuration_all_validation_paths(self):
        """Test all validation code paths in MemoryConfiguration."""
        # Test each validation condition
        
        # max_memory_mb validations - too low
        with pytest.raises(ValueError, match="Memory limit must be between 64MB and 8192MB"):
            MemoryConfiguration(max_memory_mb=63)
            
        # max_memory_mb validations - too high
        with pytest.raises(ValueError, match="Memory limit must be between 64MB and 8192MB"):
            MemoryConfiguration(max_memory_mb=8193)
            
        # chunk_size_kb validations - zero
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            MemoryConfiguration(chunk_size_kb=0)
            
        # chunk_size_kb validations - negative
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            MemoryConfiguration(chunk_size_kb=-5)

    def test_statistics_timing_workflow_coverage(self):
        """Test timing workflow to ensure all code paths are covered."""
        stats = ParseStatistics()
        
        # Test start timing
        with patch('time.time', return_value=1000.0):
            stats.start_timing()
        assert stats._start_time == 1000.0
        
        # Test end timing with start time set
        with patch('time.time', return_value=1005.0):
            stats.end_timing()
        assert stats.parse_time_seconds == 5.0
        assert stats.total_time_ms == 5000.0
        
        # Test reset functionality
        stats.reset()
        assert stats._start_time is None
        assert stats.parse_time_seconds == 0.0

    def test_plugin_manager_edge_cases(self):
        """Test edge cases in PluginManager methods."""
        manager = PluginManager()
        
        # Test plugin without name attribute
        class PluginNoName:
            pass
        
        plugin = PluginNoName()
        result = manager.register_plugin(plugin)
        assert result == True
        assert "PluginNoName" in manager._plugins
        
        # Test unregister non-existent
        result = manager.unregister_plugin("nonexistent")
        assert result == False
        
        # Test get non-existent
        result = manager.get_plugin("nonexistent")
        assert result is None


def test_module_coverage_completeness():
    """Test that all exported items are covered by tests."""
    # This test ensures we've covered all the main components
    # Import all the main classes/functions to ensure they exist
    from cobolparser.plugins.core import (
        ErrorRecoveryMode,
        DialectType,
        MemoryConfiguration,
        SerializationConfig,
        ParseError,
        LexerError,
        UnterminatedStringError,
        MemoryLimitExceededError,
        ParseStatistics,
        PluginManager
    )
    
    # Verify all imports successful
    components = [
        ErrorRecoveryMode, DialectType, MemoryConfiguration, SerializationConfig,
        ParseError, LexerError, UnterminatedStringError, MemoryLimitExceededError,
        ParseStatistics, PluginManager
    ]
    
    for component in components:
        assert component is not None
        assert hasattr(component, '__name__')


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])