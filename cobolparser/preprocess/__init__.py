"""
Copybook Expansion Module for COBOL Parser

This module provides preprocessing capabilities for expanding COPY statements
in COBOL programs by inlining copybook content from the filesystem.

Key Features:
- Basic copybook expansion with COPY statement resolution
- Nested copybook support with configurable depth limits
- Circular reference detection with dependency chain reporting
- Source location preservation for accurate error tracing
- Path traversal prevention for security
- Cross-platform path normalization
- Automatic encoding detection and UTF-8 conversion

Main Functions:
    expand_copybooks: Expand all COPY statements in COBOL source code
    parse_cobol_with_expansion: Convenience function combining expansion + parsing

Exception Types:
    CircularReferenceError: Circular copybook dependency detected
    CopybookNotFoundError: Copybook file not found in search paths
    PathTraversalError: Attempted path traversal outside search directories
    EncodingError: Failed to detect or convert file encoding
    NestingDepthError: Exceeded maximum nesting depth limit

Usage Example:
    from cobolparser.preprocess import expand_copybooks
    
    result = expand_copybooks(
        source_code=cobol_program,
        copybook_paths=["/path/to/copybooks"],
        max_nesting_depth=100
    )
    print(result.expanded_source)
"""

from typing import Optional


class CircularReferenceError(Exception):
    """
    Raised when a circular dependency is detected in copybook includes.
    
    Attributes:
        dependency_chain: List of copybook names showing the circular path
        message: Human-readable error message with dependency chain
    """
    
    def __init__(self, dependency_chain: list[str], message: Optional[str] = None):
        self.dependency_chain = dependency_chain
        if message is None:
            chain_str = " → ".join(dependency_chain)
            message = f"Circular copybook dependency detected: {chain_str}"
        super().__init__(message)


class CopybookNotFoundError(Exception):
    """
    Raised when a referenced copybook file cannot be found.
    
    Attributes:
        copybook_name: Name of the copybook that was not found
        search_paths: List of directories that were searched
        message: Human-readable error message
    """
    
    def __init__(self, copybook_name: str, search_paths: list[str], message: Optional[str] = None):
        self.copybook_name = copybook_name
        self.search_paths = search_paths
        if message is None:
            paths_str = ", ".join(search_paths)
            message = f"Copybook '{copybook_name}' not found in search paths: {paths_str}"
        super().__init__(message)


class PathTraversalError(Exception):
    """
    Raised when a path traversal attempt is detected (security violation).
    
    Attributes:
        attempted_path: The path that triggered the security violation
        message: Human-readable error message
    """
    
    def __init__(self, attempted_path: str, message: Optional[str] = None):
        self.attempted_path = attempted_path
        if message is None:
            message = f"Path traversal attempt detected: '{attempted_path}' attempts to escape search directories"
        super().__init__(message)


class EncodingError(Exception):
    """
    Raised when file encoding cannot be detected or conversion fails.
    
    Attributes:
        file_path: Path to the file with encoding issues
        details: Additional details about the encoding problem
        message: Human-readable error message
    """
    
    def __init__(self, file_path: str, details: Optional[str] = None, message: Optional[str] = None):
        self.file_path = file_path
        self.details = details
        if message is None:
            message = f"Encoding error for file '{file_path}'"
            if details:
                message += f": {details}"
        super().__init__(message)


class NestingDepthError(Exception):
    """
    Raised when copybook nesting exceeds the configured maximum depth.
    
    Attributes:
        current_depth: The nesting depth that was reached
        max_depth: The configured maximum depth limit
        message: Human-readable error message
    """
    
    def __init__(self, current_depth: int, max_depth: int, message: Optional[str] = None):
        self.current_depth = current_depth
        self.max_depth = max_depth
        if message is None:
            message = f"Nesting depth exceeded: reached {current_depth} levels (max: {max_depth})"
        super().__init__(message)


__all__ = [
    'CircularReferenceError',
    'CopybookNotFoundError',
    'PathTraversalError',
    'EncodingError',
    'NestingDepthError',
    'expand_copybooks',
    'parse_cobol_with_expansion',
]


# Import functions from submodules for convenience
from .copybook_expander import expand_copybooks, parse_cobol_with_expansion
