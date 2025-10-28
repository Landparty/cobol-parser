"""
Core copybook expansion engine.

This module implements the main copybook expansion logic, including
recursive resolution of nested copybooks, encoding detection,
and source location tracking.
"""

import time
from typing import Optional
from pathlib import Path
from .models import (
    CopybookExpansion,
    CopybookSearchPath,
    ExpansionContext,
    ExpansionStatistics,
)
from .copy_statement_parser import extract_copy_statements, parse_replacing_clause
from .path_resolver import PathResolver
from . import (
    CircularReferenceError,
    NestingDepthError,
    EncodingError,
)


def detect_encoding(file_path: str) -> str:
    """
    Detect character encoding of a file using pure-Python heuristics.
    
    Detection algorithm (no external dependencies per constitution):
    1. Check for UTF-8 BOM (\\xef\\xbb\\xbf)
    2. Try UTF-8 decode with strict error handling
    3. Check for EBCDIC indicators (0x40 for space vs 0x20 in ASCII)
    4. Fallback to ASCII with error replacement
    
    Args:
        file_path: Path to file to detect encoding
        
    Returns:
        Encoding name string ('utf-8', 'cp037' for EBCDIC, or 'ascii')
        
    Raises:
        EncodingError: If file cannot be read
        
    Example:
        >>> detect_encoding("employee.cpy")
        'utf-8'
    """
    try:
        with open(file_path, 'rb') as f:
            raw_bytes = f.read()
        
        # Check for UTF-8 BOM
        if raw_bytes.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        
        # Try UTF-8 decode
        try:
            raw_bytes.decode('utf-8', errors='strict')
            return 'utf-8'
        except UnicodeDecodeError:
            pass
        
        # Check for EBCDIC indicators
        # EBCDIC uses 0x40 for space, while ASCII uses 0x20
        # Count occurrences to detect EBCDIC
        space_ebcdic = raw_bytes.count(b'\x40')
        space_ascii = raw_bytes.count(b'\x20')
        
        if space_ebcdic > space_ascii and space_ebcdic > len(raw_bytes) * 0.05:
            # Likely EBCDIC (CP037 is common IBM mainframe encoding)
            return 'cp037'
        
        # Fallback to ASCII
        return 'ascii'
        
    except Exception as e:
        raise EncodingError(file_path, f"Failed to detect encoding: {str(e)}")


def convert_to_utf8(content: bytes, detected_encoding: str) -> str:
    """
    Convert file content to UTF-8 string with fallback handling.
    
    Args:
        content: Raw bytes from file
        detected_encoding: Encoding name from detect_encoding()
        
    Returns:
        UTF-8 string content
        
    Raises:
        EncodingError: If conversion fails
    """
    try:
        # Decode using detected encoding
        text = content.decode(detected_encoding, errors='replace')
        return text
    except Exception as e:
        # Fallback to ASCII with replacement
        try:
            return content.decode('ascii', errors='replace')
        except Exception:
            raise EncodingError(
                "<content>",
                f"Failed to convert from {detected_encoding}: {str(e)}"
            )


def read_file_with_encoding(file_path: str) -> str:
    """
    Read a file with automatic encoding detection and UTF-8 conversion.
    
    Args:
        file_path: Path to file to read
        
    Returns:
        File content as UTF-8 string
        
    Raises:
        EncodingError: If file cannot be read or converted
        
    Example:
        >>> content = read_file_with_encoding("employee.cpy")
        >>> print(content)
        01 EMPLOYEE-RECORD.
           05 EMPLOYEE-ID PIC 9(6).
    """
    encoding = detect_encoding(file_path)
    
    try:
        with open(file_path, 'rb') as f:
            raw_content = f.read()
        
        return convert_to_utf8(raw_content, encoding)
        
    except EncodingError:
        raise
    except Exception as e:
        raise EncodingError(file_path, f"Failed to read file: {str(e)}")


def expand_copybooks(
    source_code: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    preserve_source_locations: bool = False,
) -> CopybookExpansion:
    """
    Expand all COPY statements in COBOL source code by inlining copybook content.
    
    This is the main entry point for copybook expansion. It recursively resolves
    nested COPY statements, detects circular references, and optionally preserves
    source location metadata for error tracing.
    
    Args:
        source_code: COBOL source code containing COPY statements
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        preserve_source_locations: Whether to track source locations (default: False)
        
    Returns:
        CopybookExpansion object containing expanded source and metadata
        
    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        PathTraversalError: If path validation fails
        NestingDepthError: If nesting depth exceeds maximum
        EncodingError: If file encoding cannot be detected or converted
        
    Example:
        >>> result = expand_copybooks(
        ...     source_code="COPY EMPLOYEE.",
        ...     copybook_paths=["/copybooks"]
        ... )
        >>> print(result.expanded_source)
        01 EMPLOYEE-RECORD.
           05 EMPLOYEE-ID PIC 9(6).
    """
    start_time = time.time()
    
    # Create search configuration
    search_config = CopybookSearchPath(
        directories=copybook_paths,
        max_nesting_depth=max_nesting_depth
    )
    
    # Create path resolver
    path_resolver = PathResolver(search_config)
    
    # Create expansion context
    context = ExpansionContext(
        current_file="<main>",
        expansion_stack=[],
        current_depth=0
    )
    
    # Initialize statistics
    stats = ExpansionStatistics()
    stats.file_count = 1  # Count main program
    
    # Track included copybooks
    included_copybooks: list[str] = []
    
    # Perform recursive expansion
    expanded_source, max_depth = _expand_source_recursive(
        source_code,
        "<main>",
        path_resolver,
        context,
        preserve_source_locations,
        included_copybooks
    )
    
    # Calculate statistics
    elapsed_ms = (time.time() - start_time) * 1000
    stats.parse_time_ms = elapsed_ms
    stats.total_lines = len(expanded_source.splitlines())
    stats.file_count = 1 + len(included_copybooks)  # Main + copybooks
    
    return CopybookExpansion(
        expanded_source=expanded_source,
        included_copybooks=included_copybooks,
        max_depth_reached=max_depth,
        source_location_map=context.source_maps if preserve_source_locations else None,
        statistics=stats
    )


def _expand_source_recursive(
    source_code: str,
    source_file: str,
    path_resolver: PathResolver,
    context: ExpansionContext,
    preserve_locations: bool,
    included_copybooks: list[str],
) -> tuple[str, int]:
    """
    Recursively expand COPY statements in source code.
    
    Args:
        source_code: Source code to expand
        source_file: Name of current file (for location tracking)
        path_resolver: Path resolver for finding copybooks
        context: Expansion context for tracking state
        preserve_locations: Whether to preserve source locations
        included_copybooks: Accumulated list of included copybook paths
        
    Returns:
        Tuple of (expanded_source, max_depth_reached)
        
    Raises:
        CircularReferenceError: If circular dependency detected
        NestingDepthError: If max nesting depth exceeded
    """
    # Check nesting depth
    if context.current_depth > path_resolver.search_config.max_nesting_depth:
        raise NestingDepthError(
            context.current_depth,
            path_resolver.search_config.max_nesting_depth
        )
    
    # Check for circular reference
    if source_file in context.expansion_stack:
        # Build dependency chain for error message
        chain = context.expansion_stack + [source_file]
        raise CircularReferenceError(chain)
    
    # Extract COPY statements
    copy_statements = extract_copy_statements(source_code, source_file)
    
    # If no COPY statements, return source unchanged
    if not copy_statements:
        return source_code, context.current_depth
    
    # Push current file onto stack
    context.expansion_stack.append(source_file)
    max_depth = context.current_depth
    
    # Process COPY statements in reverse order to maintain positions
    expanded_source = source_code
    for statement in reversed(copy_statements):
        # Find copybook file
        copybook_path = path_resolver.resolve(
            statement.member_name,
            statement.library_qualifier
        )
        
        # Read copybook content with encoding detection
        copybook_content = read_file_with_encoding(copybook_path)
        
        # Track this copybook
        if copybook_path not in included_copybooks:
            included_copybooks.append(copybook_path)
        
        # Apply REPLACING clause if present
        if statement.replacing_clauses:
            for find_text, replace_text in statement.replacing_clauses:
                copybook_content = copybook_content.replace(find_text, replace_text)
        
        # Recursively expand nested COPY statements
        context.current_depth += 1
        context.current_file = copybook_path
        
        expanded_copybook, nested_depth = _expand_source_recursive(
            copybook_content,
            copybook_path,
            path_resolver,
            context,
            preserve_locations,
            included_copybooks
        )
        
        max_depth = max(max_depth, nested_depth)
        context.current_depth -= 1
        context.current_file = source_file
        
        # Replace COPY statement with expanded content
        # Find statement in source
        statement_start = expanded_source.find(statement.original_text)
        if statement_start != -1:
            statement_end = statement_start + len(statement.original_text)
            
            # Track source locations if requested
            if preserve_locations and statement.source_location:
                _, line_num, _ = statement.source_location
                copybook_lines = expanded_copybook.splitlines()
                expanded_line_num = len(expanded_source[:statement_start].splitlines())
                
                for i, _ in enumerate(copybook_lines):
                    context.source_maps[expanded_line_num + i] = (copybook_path, i + 1)
            
            # Perform replacement
            expanded_source = (
                expanded_source[:statement_start] +
                expanded_copybook +
                expanded_source[statement_end:]
            )
    
    # Pop current file from stack
    context.expansion_stack.pop()
    
    return expanded_source, max_depth


__all__ = [
    'detect_encoding',
    'convert_to_utf8',
    'read_file_with_encoding',
    'expand_copybooks',
    'parse_cobol_with_expansion',
]


def parse_cobol_with_expansion(
    source_code: str,
    filename: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    **parser_kwargs,
):
    """
    Convenience function that expands copybooks and parses in one step.
    
    This function combines copybook expansion with COBOL parsing, providing
    a seamless workflow for parsing COBOL programs with copybook dependencies.
    
    Args:
        source_code: COBOL source code containing COPY statements
        filename: Source filename for error reporting
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        **parser_kwargs: Additional arguments passed to parse_cobol()
        
    Returns:
        ParseResult from the COBOL parser with expanded source
        
    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        ParseError: If parsing fails after expansion
        
    Example:
        >>> from cobolparser.preprocess import parse_cobol_with_expansion
        >>> result = parse_cobol_with_expansion(
        ...     source_code="COPY EMPLOYEE.",
        ...     filename="payroll.cbl",
        ...     copybook_paths=["/copybooks"]
        ... )
        >>> print(result.ast.program_name)
    """
    # Import here to avoid circular dependency
    from ..parser import parse_cobol
    
    # Expand copybooks first
    expansion = expand_copybooks(
        source_code=source_code,
        copybook_paths=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        preserve_source_locations=False  # Parser will track its own locations
    )
    
    # Parse the expanded source
    parse_result = parse_cobol(
        source=expansion.expanded_source,
        filename=filename,
        **parser_kwargs
    )
    
    return parse_result
