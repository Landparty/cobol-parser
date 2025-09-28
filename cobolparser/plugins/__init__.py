"""
Plugins module - Enhanced features and configuration support.

This module provides the enhanced functionality including memory management,
serialization configuration, error recovery modes, and plugin architecture.
"""

from .core import (
    ErrorRecoveryMode,
    DialectType,
    MemoryConfiguration,
    SerializationConfig,
    ParseError,
    LexerError,
    UnterminatedStringError,
    MemoryLimitExceededError,
    ParseStatistics,
    PluginManager,
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