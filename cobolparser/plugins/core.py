"""
Core parsing enums and configuration classes for COBOL parser.

This module implements the enhanced feature configurations including
memory management, error recovery modes, and serialization options.
"""

from enum import Enum
from typing import Optional, Union, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from cobolparser.models.ast_base import SourceLocation


class ErrorRecoveryMode(Enum):
    """Error recovery behavior modes for COBOL parsing."""
    
    FAIL_FAST = "fail_fast"     # Stop on first error
    COLLECT_ALL = "collect_all" # Collect all errors, continue parsing


class DialectType(Enum):
    """Supported COBOL dialect types with IBM Enterprise priority."""
    
    IBM_ENTERPRISE = "ibm_enterprise"  # Primary dialect (priority)
    ANSI_COBOL = "ansi_cobol" 
    MICRO_FOCUS = "micro_focus"


@dataclass
class MemoryConfiguration:
    """Configuration for memory management during parsing."""
    
    MINIMUM_MEMORY_MB = 64
    MAXIMUM_MEMORY_MB = 8192
    DEFAULT_MEMORY_MB = 256
    
    max_memory_mb: int = DEFAULT_MEMORY_MB
    enable_streaming: bool = False
    chunk_size_kb: int = 512
    
    def __post_init__(self):
        """Validate memory configuration parameters."""
        if not (self.MINIMUM_MEMORY_MB <= self.max_memory_mb <= self.MAXIMUM_MEMORY_MB):
            raise ValueError(
                f"Memory limit must be between {self.MINIMUM_MEMORY_MB}MB and "
                f"{self.MAXIMUM_MEMORY_MB}MB, got {self.max_memory_mb}MB"
            )
        
        if self.chunk_size_kb <= 0:
            raise ValueError(f"Chunk size must be positive, got {self.chunk_size_kb}KB")


@dataclass
class SerializationConfig:
    """Configuration for JSON serialization options."""
    
    include_metadata: bool = True
    include_source_locations: bool = True
    compact_format: bool = False
    
    def __post_init__(self):
        """Validate serialization configuration."""
        # All boolean options are always valid
        pass


class ParseError(Exception):
    """Base exception for COBOL parsing errors."""
    
    def __init__(self, message: str, line: Union[int, str] = 0, column: Union[int, str] = 0, location: Optional['SourceLocation'] = None):
        super().__init__(message)
        self.message = message
        self._line = 0
        self._column = 0
        
        # Support both direct line/column parameters and SourceLocation object
        if location is not None:
            self._set_line(location.line) if hasattr(location, 'line') else None
            self._set_column(location.column) if hasattr(location, 'column') else None
        else:
            self._set_line(line)
            self._set_column(column)
    
    def _set_line(self, value: Union[int, str, None]) -> None:
        """Set line attribute with type conversion."""
        if value is not None:
            try:
                self._line = int(value)
            except (ValueError, TypeError):
                self._line = 0
        else:
            self._line = 0
    
    def _set_column(self, value: Union[int, str, None]) -> None:
        """Set column attribute with type conversion."""
        if value is not None:
            try:
                self._column = int(value)
            except (ValueError, TypeError):
                self._column = 0
        else:
            self._column = 0
    
    @property
    def line(self) -> int:
        """Get line number."""
        return self._line
    
    @line.setter
    def line(self, value) -> None:
        """Set line number with type conversion."""
        self._set_line(value)
    
    @property
    def column(self) -> int:
        """Get column number."""
        return self._column
    
    @column.setter
    def column(self, value: Union[int, str, None]) -> None:
        """Set column number with type conversion."""
        self._set_column(value)
    
    def __str__(self) -> str:
        try:
            # Ensure line and column are integers
            line = int(self.line) if self.line is not None else 0
            column = int(self.column) if self.column is not None else 0
            
            if line > 0:
                return f"Line {line}, Column {column}: {self.message}"
        except (ValueError, TypeError):
            # If conversion fails, just return the message
            pass
        return self.message


class LexerError(ParseError):
    """Exception raised during lexical analysis."""
    pass


class UnterminatedStringError(LexerError):
    """Exception for unterminated string literals."""
    pass


class MemoryLimitExceededError(ParseError):
    """Exception when memory usage exceeds configured limits."""
    
    def __init__(self, current_mb: float, limit_mb: int):
        message = f"Memory usage {current_mb:.1f}MB exceeds limit of {limit_mb}MB"
        super().__init__(message)
        self.current_mb = current_mb
        self.limit_mb = limit_mb


@dataclass 
class ParseStatistics:
    """Comprehensive parsing statistics."""
    
    def __init__(self):
        self.lines_processed: int = 0
        self.lines_parsed: int = 0
        self.tokens_processed: int = 0
        self.memory_peak_mb: float = 0.0
        self.parse_time_seconds: float = 0.0
        self.total_time_ms: float = 0.0
        self.error_count: int = 0
        self.warning_count: int = 0
        self._start_time: Optional[float] = None
    
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
            "warning_count": self.warning_count
        }


class IOErrorCode(Enum):
    """IO statement error codes per contract io-statement-ast.md"""
    
    # READ statement errors
    IO_READ_INVALID_KEY_ORDER = "IO_READ_INVALID_KEY_ORDER"  # INVALID KEY clause appears before KEY clause
    IO_READ_LOCK_ON_SEQUENTIAL = "IO_READ_LOCK_ON_SEQUENTIAL"  # WITH LOCK on sequential file
    IO_READ_AT_END_WITHOUT_FILE = "IO_READ_AT_END_WITHOUT_FILE"  # AT END without file reference
    
    # WRITE statement errors
    IO_WRITE_ADVANCING_INVALID_UNIT = "IO_WRITE_ADVANCING_INVALID_UNIT"  # Invalid unit in ADVANCING clause
    IO_WRITE_DELETE_INVALID_ORG = "IO_WRITE_DELETE_INVALID_ORG"  # DELETE clause on non-VSAM file
    
    # OPEN statement errors
    IO_OPEN_INVALID_MODE = "IO_OPEN_INVALID_MODE"  # Invalid OPEN mode
    IO_OPEN_REEL_ON_DISK = "IO_OPEN_REEL_ON_DISK"  # REEL clause on disk file
    
    # CLOSE statement errors
    IO_CLOSE_NO_REWIND_INVALID = "IO_CLOSE_NO_REWIND_INVALID"  # NO REWIND on non-tape file
    IO_CLOSE_WITH_LOCK_INVALID = "IO_CLOSE_WITH_LOCK_INVALID"  # WITH LOCK on sequential file
    
    # REWRITE statement errors
    IO_REWRITE_INVALID_ORG = "IO_REWRITE_INVALID_ORG"  # REWRITE on sequential file
    IO_REWRITE_INVALID_KEY_ORDER = "IO_REWRITE_INVALID_KEY_ORDER"  # Invalid INVALID KEY clause
    
    # DELETE statement errors
    IO_DELETE_INVALID_ORG = "IO_DELETE_INVALID_ORG"  # DELETE on sequential file
    IO_DELETE_INVALID_KEY_ORDER = "IO_DELETE_INVALID_KEY_ORDER"  # Invalid INVALID KEY clause
    
    # START statement errors
    IO_START_INVALID_ORG = "IO_START_INVALID_ORG"  # START on sequential file
    IO_START_MISSING_KEY = "IO_START_MISSING_KEY"  # START without KEY condition
    IO_START_INVALID_KEY_CONDITION = "IO_START_INVALID_KEY_CONDITION"  # Invalid key condition
    
    # ACCEPT/DISPLAY statement errors
    IO_ACCEPT_INVALID_FROM = "IO_ACCEPT_INVALID_FROM"  # Invalid FROM device
    IO_DISPLAY_INVALID_UPON = "IO_DISPLAY_INVALID_UPON"  # Invalid UPON device
    
    # UNLOCK statement errors
    IO_UNLOCK_INVALID_ORG = "IO_UNLOCK_INVALID_ORG"  # UNLOCK on sequential file
    
    # Generic IO errors
    IO_INVALID_LOCK = "IO_INVALID_LOCK"  # WITH LOCK invalid for this statement
    IO_INVALID_FILE_ORG = "IO_INVALID_FILE_ORG"  # File organization not supported for this statement
    IO_MISSING_REQUIRED_CLAUSE = "IO_MISSING_REQUIRED_CLAUSE"  # Required IO clause missing


class IODiagnosticHelper:
    """Helper class for generating IO-related diagnostics and error messages."""
    
    # Mapping of error codes to user-friendly messages
    ERROR_MESSAGES = {
        IOErrorCode.IO_READ_INVALID_KEY_ORDER: 
            "INVALID KEY clause must appear after KEY clause in READ statement",
        IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL:
            "WITH LOCK is not valid on sequential files; use indexed or relative file",
        IOErrorCode.IO_READ_AT_END_WITHOUT_FILE:
            "AT END clause requires READ to be operating on a file",
        
        IOErrorCode.IO_WRITE_ADVANCING_INVALID_UNIT:
            "ADVANCING clause requires valid unit (LINES or CHANNEL)",
        IOErrorCode.IO_WRITE_DELETE_INVALID_ORG:
            "DELETE clause in WRITE is only valid for VSAM (indexed) files",
        
        IOErrorCode.IO_OPEN_INVALID_MODE:
            "OPEN statement requires valid mode: INPUT, OUTPUT, I-O, or EXTEND",
        IOErrorCode.IO_OPEN_REEL_ON_DISK:
            "REEL clause is only valid for tape files (ORGANIZATION IS SEQUENTIAL)",
        
        IOErrorCode.IO_CLOSE_NO_REWIND_INVALID:
            "NO REWIND clause is only valid for tape files",
        IOErrorCode.IO_CLOSE_WITH_LOCK_INVALID:
            "WITH LOCK on CLOSE is not valid for sequential files",
        
        IOErrorCode.IO_REWRITE_INVALID_ORG:
            "REWRITE is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_REWRITE_INVALID_KEY_ORDER:
            "INVALID KEY clause in REWRITE must follow proper syntax",
        
        IOErrorCode.IO_DELETE_INVALID_ORG:
            "DELETE is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_DELETE_INVALID_KEY_ORDER:
            "INVALID KEY clause in DELETE must follow proper syntax",
        
        IOErrorCode.IO_START_INVALID_ORG:
            "START is only valid for indexed or relative files, not sequential",
        IOErrorCode.IO_START_MISSING_KEY:
            "START statement requires KEY clause with condition",
        IOErrorCode.IO_START_INVALID_KEY_CONDITION:
            "START KEY requires valid condition: EQUAL, GREATER, LESS, GREATER THAN, LESS THAN, etc.",
        
        IOErrorCode.IO_ACCEPT_INVALID_FROM:
            "ACCEPT FROM specifies invalid source device or environment variable",
        IOErrorCode.IO_DISPLAY_INVALID_UPON:
            "DISPLAY UPON specifies invalid device (use CONSOLE, DISPLAY, STANDARD-OUTPUT, etc.)",
        
        IOErrorCode.IO_UNLOCK_INVALID_ORG:
            "UNLOCK is only valid for indexed files with record locking",
        
        IOErrorCode.IO_INVALID_LOCK:
            "WITH LOCK clause is not valid for this statement or file organization",
        IOErrorCode.IO_INVALID_FILE_ORG:
            "File organization does not support this IO statement",
        IOErrorCode.IO_MISSING_REQUIRED_CLAUSE:
            "Required clause is missing from this IO statement",
    }
    
    @staticmethod
    def get_error_message(code: IOErrorCode) -> str:
        """Get user-friendly error message for IO error code."""
        return IODiagnosticHelper.ERROR_MESSAGES.get(code, f"IO Error: {code.value}")
    
    @staticmethod
    def create_io_error(
        code: IOErrorCode,
        line: int = 0,
        column: int = 0,
        context: Optional[str] = None
    ) -> ParseError:
        """Create a ParseError for IO statement issues."""
        message = IODiagnosticHelper.get_error_message(code)
        if context:
            message = f"{message} ({context})"
        
        error = ParseError(message, line, column)
        error.code = code.value  # Add error code attribute
        return error
    
    @staticmethod
    def validate_io_statement_type(
        statement_type: str,
        file_organization: Optional[str] = None
    ) -> Optional[IOErrorCode]:
        """Validate IO statement against file organization.
        
        Returns error code if validation fails, None if valid.
        """
        if not file_organization:
            return None  # No organization info, skip validation
        
        org_upper = file_organization.upper()
        stmt_upper = statement_type.upper()
        
        # START, REWRITE, DELETE only valid on indexed/relative
        if stmt_upper in ("START", "REWRITE", "DELETE"):
            if org_upper not in ("INDEXED", "RELATIVE"):
                if stmt_upper == "START":
                    return IOErrorCode.IO_START_INVALID_ORG
                elif stmt_upper == "REWRITE":
                    return IOErrorCode.IO_REWRITE_INVALID_ORG
                elif stmt_upper == "DELETE":
                    return IOErrorCode.IO_DELETE_INVALID_ORG
        
        # UNLOCK only valid on indexed
        if stmt_upper == "UNLOCK":
            if org_upper != "INDEXED":
                return IOErrorCode.IO_UNLOCK_INVALID_ORG
        
        return None


class PluginManager:
    """Plugin management system for parser extensibility."""
    
    def __init__(self):
        self._plugins: dict[str, object] = {}
        self._active_plugins: list[str] = []
    
    def register_plugin(self, plugin: object) -> bool:
        """Register a new plugin with the parser."""
        plugin_name = getattr(plugin, 'name', plugin.__class__.__name__)
        
        if plugin_name in self._plugins:
            return False  # Plugin already registered
        
        self._plugins[plugin_name] = plugin
        self._active_plugins.append(plugin_name)
        return True
    
    def unregister_plugin(self, plugin_name: str) -> bool:
        """Unregister a plugin by name."""
        if plugin_name not in self._plugins:
            return False
        
        del self._plugins[plugin_name]
        if plugin_name in self._active_plugins:
            self._active_plugins.remove(plugin_name)
        return True
    
    def get_active_plugins(self) -> list[str]:
        """Get list of active plugin names."""
        return self._active_plugins.copy()
    
    def get_plugin(self, plugin_name: str) -> Optional[object]:
        """Get a specific plugin by name."""
        return self._plugins.get(plugin_name)


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
    "IOErrorCode",
    "IODiagnosticHelper",
    "PluginManager",
]