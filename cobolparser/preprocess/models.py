"""
Data models for copybook expansion.

This module defines the data structures used throughout the copybook expansion
process, including expansion results, parsed COPY statements, search configuration,
and internal expansion state.
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from pathlib import Path


@dataclass
class ExpansionStatistics:
    """
    Performance and diagnostic statistics for copybook expansion.
    
    Attributes:
        parse_time_ms: Total expansion time in milliseconds
        file_count: Number of copybooks processed (including main program)
        total_lines: Total lines in the expanded output
        peak_memory_bytes: Peak memory usage during expansion
    """
    parse_time_ms: float = 0.0
    file_count: int = 0
    total_lines: int = 0
    peak_memory_bytes: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary for JSON serialization."""
        return {
            "parse_time_ms": self.parse_time_ms,
            "file_count": self.file_count,
            "total_lines": self.total_lines,
            "peak_memory_bytes": self.peak_memory_bytes,
        }


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
    source_location_map: Optional[dict[int, tuple[str, int]]] = None
    statistics: ExpansionStatistics = field(default_factory=ExpansionStatistics)
    
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
        replacing_clauses: Optional list of (find, replace) text substitution pairs
        source_location: Location in source where COPY statement appears (file, line, column)
        original_text: The original COPY statement text from source
    """
    member_name: str
    library_qualifier: Optional[str] = None
    replacing_clauses: Optional[list[tuple[str, str]]] = None
    source_location: Optional[tuple[str, int, int]] = None
    original_text: str = ""
    
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
                {"find": find, "replace": replace}
                for find, replace in self.replacing_clauses
            ]
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
        case_sensitive: Whether file matching should be case-sensitive (platform-dependent)
        max_nesting_depth: Maximum allowed nesting depth for copybooks
    """
    directories: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=lambda: [".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB"])
    case_sensitive: bool = True  # Default to True, will be auto-detected per platform
    max_nesting_depth: int = 100
    
    def to_dict(self) -> dict[str, Any]:
        """Convert search configuration to dictionary for JSON serialization."""
        return {
            "directories": self.directories,
            "extensions": self.extensions,
            "case_sensitive": self.case_sensitive,
            "max_nesting_depth": self.max_nesting_depth,
        }


@dataclass
class ExpansionContext:
    """
    Internal state tracking during recursive copybook expansion.
    
    Attributes:
        current_file: Path to the file currently being processed
        expansion_stack: Stack of files being expanded (for circular reference detection)
        source_maps: Accumulated source location mappings (line_number -> (file, original_line))
        current_depth: Current nesting depth in the expansion recursion
    """
    current_file: str = ""
    expansion_stack: list[str] = field(default_factory=list)
    source_maps: dict[int, tuple[str, int]] = field(default_factory=dict)
    current_depth: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert expansion context to dictionary for debugging/serialization."""
        return {
            "current_file": self.current_file,
            "expansion_stack": self.expansion_stack,
            "current_depth": self.current_depth,
            "source_maps_count": len(self.source_maps),
        }


# Type alias for source location mapping
SourceLocationMap = dict[int, tuple[str, int]]


__all__ = [
    'CopybookExpansion',
    'CopyStatement',
    'CopybookSearchPath',
    'ExpansionContext',
    'ExpansionStatistics',
    'SourceLocationMap',
]
