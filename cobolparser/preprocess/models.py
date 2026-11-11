"""
Data models for copybook expansion.

This module defines the data structures used throughout the copybook expansion
process, including expansion results, parsed COPY statements, search configuration,
and internal expansion state.
"""

import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def get_default_case_sensitivity() -> bool:
    """Determine case sensitivity based on platform.

    Returns:
        True for case-sensitive filesystems (Linux/Unix),
        False for case-insensitive filesystems (Windows, macOS)
    """
    if sys.platform == "win32":
        return False  # Windows is case-insensitive
    elif sys.platform == "darwin":
        return False  # macOS is case-insensitive by default
    else:
        return True  # Linux/Unix is case-sensitive


# Size limits for copybook processing
MAX_COPYBOOK_SIZE_BYTES = 10 * 1024 * 1024  # 10MB per copybook
MAX_TOTAL_EXPANSION_BYTES = 100 * 1024 * 1024  # 100MB total expansion

#: ``EXEC SQL INCLUDE`` members the DB2 precompiler supplies itself. An
#: INCLUDE of one of them is expected not to resolve on a copybook path; any
#: other member that does not resolve is reported as not expanded.
PRECOMPILER_MEMBERS: frozenset[str] = frozenset({"SQLCA", "SQLDA"})


@dataclass
class ReplacingClause:
    """
    Represents a single REPLACING clause entry.

    Attributes:
        find_text: Text pattern to find
        replace_text: Text to replace with
        mode: Replacement mode - 'ALL' (default), 'LEADING', or 'TRAILING'
    """

    find_text: str
    replace_text: str
    mode: str = "ALL"  # ALL, LEADING, TRAILING

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "find": self.find_text,
            "replace": self.replace_text,
            "mode": self.mode,
        }


@dataclass
class SuppressClause:
    """
    Represents a SUPPRESS clause in a COPY statement.

    Attributes:
        suppress_all: If True, suppress entire copybook listing
        line_ranges: List of (start, end) tuples for specific line suppression
        single_lines: List of individual lines to suppress
    """

    suppress_all: bool = False
    line_ranges: list[tuple[int, int]] = field(default_factory=list)
    single_lines: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        if self.suppress_all:
            return {"type": "ALL"}
        result: dict[str, Any] = {}
        if self.line_ranges:
            result["ranges"] = [{"start": s, "end": e} for s, e in self.line_ranges]
        if self.single_lines:
            result["lines"] = self.single_lines
        return result


@dataclass
class ExpansionStatistics:
    """
    Performance and diagnostic statistics for copybook expansion.

    Attributes:
        parse_time_ms: Total expansion time in milliseconds
        file_count: Number of copybooks processed (including main program)
        total_lines: Total lines in the expanded output
        peak_memory_bytes: Peak memory usage during expansion
        warnings: List of non-fatal warnings encountered during expansion
        total_bytes_processed: Total bytes processed across all copybooks
    """

    parse_time_ms: float = 0.0
    file_count: int = 0
    total_lines: int = 0
    peak_memory_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    total_bytes_processed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary for JSON serialization."""
        result = {
            "parse_time_ms": self.parse_time_ms,
            "file_count": self.file_count,
            "total_lines": self.total_lines,
            "peak_memory_bytes": self.peak_memory_bytes,
            "total_bytes_processed": self.total_bytes_processed,
        }
        if self.warnings:
            result["warnings"] = self.warnings  # type: ignore[assignment]
        return result


@dataclass
class CopybookExpansion:
    """
    Result of copybook expansion operation.

    Attributes:
        expanded_source: Complete expanded COBOL source code with all COPY statements resolved
        included_copybooks: List of all copybook file paths that were included (in order)
        max_depth_reached: Maximum nesting depth encountered during expansion
        source_location_map: Optional mapping of expanded line numbers to (source_file, original_line)
        statistics: Performance metrics for the expansion operation
    """

    expanded_source: str
    included_copybooks: list[str] = field(default_factory=list)
    max_depth_reached: int = 0
    source_location_map: dict[int, tuple[str, int]] | None = None
    statistics: ExpansionStatistics = field(default_factory=ExpansionStatistics)
    #: ``(file, original line)`` of every debugging line (``D`` in column 7)
    #: expansion blanked as a comment, in output order; empty when
    #: ``debug_lines=True`` kept them, or when nothing was expanded (the
    #: source then passes through untouched and the parser counts them).
    dropped_debug_lines: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert expansion result to dictionary for JSON serialization."""
        result = {
            "expanded_source": self.expanded_source,
            "included_copybooks": self.included_copybooks,
            "max_depth_reached": self.max_depth_reached,
            "statistics": self.statistics.to_dict(),
        }
        if self.source_location_map is not None:
            # Convert tuple keys and values to serializable format
            result["source_location_map"] = {
                str(line_num): {"file": file, "line": orig_line}
                for line_num, (file, orig_line) in self.source_location_map.items()
            }
        return result


@dataclass
class CopyStatement:
    """
    Parsed COPY statement from COBOL source.

    Attributes:
        member_name: Name of the copybook member to be included
        library_qualifier: Optional library name (from IN/OF clause)
        replacing_clauses: Optional list of ReplacingClause objects for text substitution
        suppress_clause: Optional SuppressClause for listing suppression
        source_location: Location in source where COPY statement appears (file, line, column)
        original_text: The original COPY statement text from source
    """

    member_name: str
    library_qualifier: str | None = None
    replacing_clauses: list[ReplacingClause] | None = None
    suppress_clause: SuppressClause | None = None
    source_location: tuple[str, int, int] | None = None
    original_text: str = ""
    start_index: int = 0
    end_index: int = 0
    #: True for an ``EXEC SQL INCLUDE member END-EXEC`` statement recognized
    #: by :class:`CopyStatementLexer` (``sql_include=True``): the DB2
    #: precompiler resolves it from the same library as ``COPY``, so the
    #: expander inlines a member it can find and leaves one it cannot
    #: (``SQLCA``, ``SQLDA`` -- supplied by the precompiler) as written.
    sql_include: bool = False

    @property
    def is_suppressed(self) -> bool:
        """Check if this COPY statement has SUPPRESS clause."""
        return self.suppress_clause is not None

    @property
    def has_replacements(self) -> bool:
        """Check if this COPY statement has REPLACING clauses."""
        return bool(self.replacing_clauses)

    def to_dict(self) -> dict[str, Any]:
        """Convert COPY statement to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "member_name": self.member_name,
            "original_text": self.original_text,
        }
        if self.library_qualifier:
            result["library_qualifier"] = self.library_qualifier
        if self.replacing_clauses:
            result["replacing_clauses"] = [
                rc.to_dict() for rc in self.replacing_clauses
            ]
        if self.suppress_clause:
            result["suppress_clause"] = self.suppress_clause.to_dict()
        if self.source_location:
            file, line, col = self.source_location
            result["source_location"] = {"file": file, "line": line, "column": col}
        return result


@dataclass
class CopybookSearchPath:
    """
    Configuration for locating copybook files.

    Attributes:
        directories: Ordered list of directory paths to search for copybooks
        extensions: File extensions to try when resolving copybook names
        case_sensitive: Whether file matching should be case-sensitive (auto-detected by default)
        max_nesting_depth: Maximum allowed nesting depth for copybooks
        max_file_size: Maximum size in bytes for a single copybook file
        max_total_size: Maximum total size in bytes for all expanded content
        encoding: Optional explicit encoding for all copybook files. When set, skips
            auto-detection and forces this encoding. Useful for selecting a specific
            EBCDIC variant (e.g. 'cp1047' for Open Systems, 'cp500' for International
            EBCDIC, 'cp273' for German) instead of the auto-detected default of cp037.
            When None, encoding is auto-detected per file.
        encoding_errors: Decode strictness for copybook files. ``"replace"``
            (default, backward compatible) substitutes undecodable bytes with
            U+FFFD and records a lossy-decode warning; ``"strict"`` raises
            ``EncodingError`` with file/offset context instead of silently
            mangling data.
    """

    directories: list[str] = field(default_factory=list)
    extensions: list[str] = field(
        default_factory=lambda: [".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ""]
    )
    case_sensitive: bool = field(default_factory=get_default_case_sensitivity)
    max_nesting_depth: int = 100
    max_file_size: int = MAX_COPYBOOK_SIZE_BYTES
    max_total_size: int = MAX_TOTAL_EXPANSION_BYTES
    max_cache_entries: int = 100
    encoding: str | None = None
    encoding_errors: str = "replace"

    def to_dict(self) -> dict[str, Any]:
        """Convert search configuration to dictionary for JSON serialization."""
        result = {
            "directories": self.directories,
            "extensions": self.extensions,
            "case_sensitive": self.case_sensitive,
            "max_nesting_depth": self.max_nesting_depth,
            "max_file_size": self.max_file_size,
            "max_total_size": self.max_total_size,
            "max_cache_entries": self.max_cache_entries,
            "encoding_errors": self.encoding_errors,
        }
        if self.encoding is not None:
            result["encoding"] = self.encoding
        return result


@dataclass
class ExpansionContext:
    """
    Internal state tracking during recursive copybook expansion.

    Attributes:
        current_file: Path to the file currently being processed
        expansion_stack: Stack of files being expanded (for circular reference detection)
        source_maps: Accumulated source location mappings (line_number -> (file, original_line))
        current_depth: Current nesting depth in the expansion recursion
        content_cache: Cache of already-expanded copybook content (for diamond dependencies)
        content_origins: Per-line ``(file, original line)`` origins of each
            cached content entry, keyed identically to ``content_cache`` so a
            cache hit contributes the same source map a miss would have
        total_bytes: Running total of bytes processed
        defined_symbols: Symbols defined via >>DEFINE for conditional compilation
    """

    current_file: str = ""
    expansion_stack: list[str] = field(default_factory=list)
    _expansion_stack_set: set[str] = field(default_factory=set)
    source_maps: dict[int, tuple[str, int]] = field(default_factory=dict)
    current_depth: int = 0
    content_cache: OrderedDict[str, str] = field(default_factory=OrderedDict)
    content_origins: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    total_bytes: int = 0
    defined_symbols: dict[str, str] = field(default_factory=dict)
    #: Keep debugging lines (``D`` in column 7) as code instead of blanking
    #: them with the comments (``expand_copybooks(debug_lines=True)``).
    debug_lines: bool = False
    #: Leave a COPY whose member cannot be found as written, with a warning,
    #: instead of failing the whole expansion
    #: (``expand_copybooks(skip_missing_copybooks=True)``).
    skip_missing: bool = False

    # LRU management (OrderedDict provides O(1) move_to_end/popitem)
    max_cache_size: int = 512

    def stack_push(self, file: str) -> None:
        """Push file onto expansion stack with O(1) membership check."""
        self.expansion_stack.append(file)
        self._expansion_stack_set.add(file)

    def stack_pop(self) -> str:
        """Pop file from expansion stack."""
        file = self.expansion_stack.pop()
        self._expansion_stack_set.discard(file)
        return file

    def stack_contains(self, file: str) -> bool:
        """O(1) circular reference check."""
        return file in self._expansion_stack_set

    def cache_get(self, key: str) -> str | None:
        """Get item from cache and update its position (LRU). O(1)."""
        if key in self.content_cache:
            self.content_cache.move_to_end(key)
            return self.content_cache[key]
        return None

    def cache_put(
        self,
        key: str,
        value: str,
        origins: list[tuple[str, int]] | None = None,
    ) -> None:
        """Put item in cache with LRU eviction if full. O(1).

        ``origins`` (one ``(file, original line)`` per line of *value*) rides
        along under the same key so a later cache hit can splice the same
        source map a miss would have produced.
        """
        if key in self.content_cache:
            self.content_cache.move_to_end(key)
            self.content_cache[key] = value
        else:
            if len(self.content_cache) >= self.max_cache_size:
                evicted, _ = self.content_cache.popitem(last=False)
                self.content_origins.pop(evicted, None)
            self.content_cache[key] = value
        if origins is not None:
            self.content_origins[key] = list(origins)

    def cache_get_origins(self, key: str) -> list[tuple[str, int]] | None:
        """Per-line origins stored beside a cached content entry, if any."""
        return self.content_origins.get(key)

    def get_cache_key(
        self, copybook_path: str, replacing_clauses: list | None = None
    ) -> str:
        """Generate cache key for a copybook with specific replacements."""
        if replacing_clauses:
            replace_str = str(
                sorted(
                    (rc.find_text, rc.replace_text, rc.mode) for rc in replacing_clauses
                )
            )
            return f"{copybook_path}::{replace_str}"
        return copybook_path

    def to_dict(self) -> dict[str, Any]:
        """Convert expansion context to dictionary for debugging/serialization."""
        return {
            "current_file": self.current_file,
            "expansion_stack": self.expansion_stack,
            "current_depth": self.current_depth,
            "source_maps_count": len(self.source_maps),
            "cache_size": len(self.content_cache),
            "total_bytes": self.total_bytes,
            "defined_symbols": self.defined_symbols,
        }


# Type alias for source location mapping
SourceLocationMap = dict[int, tuple[str, int]]


__all__ = [
    "CopybookExpansion",
    "CopyStatement",
    "CopybookSearchPath",
    "ExpansionContext",
    "ExpansionStatistics",
    "ReplacingClause",
    "SuppressClause",
    "SourceLocationMap",
    "get_default_case_sensitivity",
    "MAX_COPYBOOK_SIZE_BYTES",
    "MAX_TOTAL_EXPANSION_BYTES",
]
