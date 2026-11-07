"""
Plugins module - Enhanced features and configuration support.

This module provides parser configuration (``MemoryConfiguration``, whose
memory fields are advisory and not enforced -- only ``max_error_count`` is),
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
