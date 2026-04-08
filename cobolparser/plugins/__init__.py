"""
Plugins module - Enhanced features and configuration support.

This module provides the enhanced functionality including memory management,
serialization configuration, error recovery modes, and plugin architecture.
"""

from .core import (
    DialectType,
    ErrorRecoveryMode,
    LexerError,
    MemoryConfiguration,
    MemoryLimitExceededError,
    ParseError,
    ParseStatistics,
    PluginManager,
    SerializationConfig,
    UnterminatedStringError,
)

__all__ = [
    "ErrorRecoveryMode",
    "DialectType",
    "MemoryConfiguration",
    "SerializationConfig",
    "ParseError",
    "LexerError",
    "UnterminatedStringError",
    "MemoryLimitExceededError",
    "ParseStatistics",
    "PluginManager",
]
