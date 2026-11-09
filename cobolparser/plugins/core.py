"""
Core parsing enums and configuration classes for COBOL parser.

This module implements the enhanced feature configurations including
memory management, error recovery modes, and serialization options.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ErrorRecoveryMode(Enum):
    """Error recovery behavior modes for COBOL parsing."""

    FAIL_FAST = "fail_fast"  # Stop on first error
    COLLECT_ALL = "collect_all"  # Collect all errors, continue parsing


class DialectType(Enum):
    """Supported COBOL dialect types with IBM Enterprise priority."""

    IBM_ENTERPRISE = "ibm_enterprise"  # Primary dialect (priority)
    ANSI_COBOL = "ansi_cobol"
    MICRO_FOCUS = "micro_focus"


@dataclass
class MemoryConfiguration:
    """Parser limits: the recorded-error cap, plus advisory memory fields.

    .. warning::
        ``max_memory_mb``, ``enable_streaming`` and ``chunk_size_kb`` are
        currently **validated and stored but not enforced** (audit 2026-07-07
        M5): no parse path reads them, ``MemoryLimitExceededError`` is never
        raised, and ``ParseStatistics.memory_peak_mb`` stays ``0.0``. Do not
        rely on them to bound memory — use
        :class:`cobolparser.profiling.ProfilerContext` to measure real peak
        memory. ``max_error_count`` **is** honored (``CobolParser.add_error``
        stops recording once the limit is reached).
    """

    MINIMUM_MEMORY_MB = 64
    MAXIMUM_MEMORY_MB = 8192
    DEFAULT_MEMORY_MB = 256
    DEFAULT_MAX_ERRORS = 1000

    max_memory_mb: int = DEFAULT_MEMORY_MB
    enable_streaming: bool = False
    chunk_size_kb: int = 512
    max_error_count: int = DEFAULT_MAX_ERRORS

    def __post_init__(self) -> None:
        """Validate memory configuration parameters."""
        if not (self.MINIMUM_MEMORY_MB <= self.max_memory_mb <= self.MAXIMUM_MEMORY_MB):
            raise ValueError(
                f"Memory limit must be between {self.MINIMUM_MEMORY_MB}MB and "
                f"{self.MAXIMUM_MEMORY_MB}MB, got {self.max_memory_mb}MB"
            )

        if self.chunk_size_kb <= 0:
            raise ValueError(f"Chunk size must be positive, got {self.chunk_size_kb}KB")

        if self.max_error_count <= 0:
            raise ValueError(
                f"max_error_count must be positive, got {self.max_error_count}"
            )


@dataclass
class SerializationConfig:
    """Configuration for JSON serialization options."""

    include_metadata: bool = True
    include_source_locations: bool = True
    compact_format: bool = False

    def __post_init__(self) -> None:
        """Validate serialization configuration."""
        # All boolean options are always valid
        pass


# Re-export the single canonical ParseError from cobolparser._errors.
# Previously this module defined its own ParseError; it is now unified.
# The import uses an absolute path to avoid circular imports through core/__init__.py.
from cobolparser._errors import ParseError  # noqa: E402, F401


class LexerError(ParseError):
    """Exception raised during lexical analysis."""

    pass


class UnterminatedStringError(LexerError):
    """Exception for unterminated string literals."""

    pass


class MemoryLimitExceededError(ParseError):
    """Exception when memory usage exceeds configured limits.

    Never raised by the parser today: ``MemoryConfiguration.max_memory_mb`` is
    not enforced. Kept as public API.
    """

    def __init__(self, current_mb: float, limit_mb: int):
        message = f"Memory usage {current_mb:.1f}MB exceeds limit of {limit_mb}MB"
        super().__init__(message)
        self.current_mb = current_mb
        self.limit_mb = limit_mb


@dataclass
class ParseStatistics:
    """Comprehensive parsing statistics."""

    def __init__(self) -> None:
        self.lines_processed: int = 0
        self.lines_parsed: int = 0
        self.tokens_processed: int = 0
        self.memory_peak_mb: float = 0.0
        self.parse_time_seconds: float = 0.0
        self.total_time_ms: float = 0.0
        self.error_count: int = 0
        self.warning_count: int = 0
        self._start_time: float | None = None

    def reset(self) -> None:
        """Reset all statistics to initial values."""
        self.lines_processed = 0
        self.lines_parsed = 0
        self.tokens_processed = 0
        self.memory_peak_mb = 0.0
        self.parse_time_seconds = 0.0
        self.total_time_ms = 0.0
        self.error_count = 0
        self.warning_count = 0
        self._start_time = None

    def start_timing(self) -> None:
        """Start timing the parsing operation."""
        import time

        self._start_time = time.time()

    def end_timing(self) -> None:
        """End timing and calculate total time."""
        if self._start_time is not None:
            import time

            end_time = time.time()
            self.parse_time_seconds = end_time - self._start_time
            self.total_time_ms = self.parse_time_seconds * 1000.0

    def copy(self) -> "ParseStatistics":
        """Return an independent snapshot of these statistics.

        ``CobolParser`` hands each ``ParseResult`` a snapshot rather than
        its own live (and later ``reset()``) statistics object, so reusing
        one parser instance cannot clobber earlier results' statistics.
        """
        snapshot = ParseStatistics()
        snapshot.lines_processed = self.lines_processed
        snapshot.lines_parsed = self.lines_parsed
        snapshot.tokens_processed = self.tokens_processed
        snapshot.memory_peak_mb = self.memory_peak_mb
        snapshot.parse_time_seconds = self.parse_time_seconds
        snapshot.total_time_ms = self.total_time_ms
        snapshot.error_count = self.error_count
        snapshot.warning_count = self.warning_count
        snapshot._start_time = self._start_time
        return snapshot

    def to_dict(self) -> dict[str, int | float]:
        """Convert statistics to dictionary format."""
        return {
            "lines_processed": self.lines_processed,
            "lines_parsed": self.lines_parsed,
            "tokens_processed": self.tokens_processed,
            "memory_peak_mb": self.memory_peak_mb,
            "parse_time_seconds": self.parse_time_seconds,
            "total_time_ms": self.total_time_ms,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


# Module exports
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
]
