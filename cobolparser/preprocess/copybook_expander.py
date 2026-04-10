"""
Core copybook expansion engine.

This module implements the main copybook expansion logic, including
recursive resolution of nested copybooks, encoding detection,
source location tracking, content validation, and caching.
"""

import time
from typing import Any

from . import (
    CircularReferenceError,
    EncodingError,
    NestingDepthError,
    TotalExpansionSizeExceededError,
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
)
from .copy_statement_parser import (
    CopyStatementLexer,
    apply_replacing_clauses,
    normalize_continuation_lines,
    remove_comment_lines,
    strip_sequence_area,
)
from .models import (
    MAX_COPYBOOK_SIZE_BYTES,
    MAX_TOTAL_EXPANSION_BYTES,
    CopybookExpansion,
    CopybookSearchPath,
    ExpansionContext,
    ExpansionStatistics,
)
from .path_resolver import PathResolver


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
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # Check for UTF-8 BOM
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        # Try UTF-8 decode
        try:
            raw_bytes.decode("utf-8", errors="strict")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # Check for EBCDIC indicators.
        # EBCDIC uses 0x40 for space, while ASCII uses 0x20.
        space_ebcdic = raw_bytes.count(b"\x40")
        space_ascii = raw_bytes.count(b"\x20")

        if space_ebcdic > space_ascii and space_ebcdic > len(raw_bytes) * 0.05:
            # Likely EBCDIC. Single-byte EBCDIC codecs (cp037, cp500, etc.) all
            # decode any byte sequence without error, so a strict-decode probe
            # cannot distinguish variants. Return cp037 (US/Canada, the most
            # common IBM mainframe encoding) as the safe default. Callers that
            # need a specific variant (e.g. cp1047 for Open Systems, cp500 for
            # International EBCDIC, cp273 for German) should set the
            # CopybookSearchPath.encoding field to override auto-detection.
            return "cp037"

        # Fallback to ASCII
        return "ascii"

    except (OSError, ValueError) as e:
        raise EncodingError(file_path, f"Failed to detect encoding: {str(e)}") from e


def convert_to_utf8(content: bytes, detected_encoding: str) -> str:
    """
    Convert file content to UTF-8 string with fallback handling.

    Decodes ``content`` using ``detected_encoding`` (errors replaced, not
    raised).  If the codec name is unknown a second attempt with ASCII
    replacement is made.  No multi-codec probe sequence is performed because
    single-byte EBCDIC codecs (cp037, cp500, cp1047, …) all decode every
    byte sequence without raising errors, making error-based probing useless.
    Use ``CopybookSearchPath.encoding`` to supply a specific EBCDIC variant
    rather than relying on auto-detection.

    Args:
        content: Raw bytes from file
        detected_encoding: Encoding name from detect_encoding() or caller override

    Returns:
        UTF-8 string content

    Raises:
        EncodingError: If conversion fails
    """
    try:
        # Decode using detected encoding
        text = content.decode(detected_encoding, errors="replace")
        return text
    except (UnicodeDecodeError, LookupError):
        # Fallback to ASCII with replacement
        try:
            return content.decode("ascii", errors="replace")
        except (UnicodeDecodeError, LookupError) as e2:
            raise EncodingError(
                "<content>", f"Failed to convert from {detected_encoding}: {str(e2)}"
            ) from e2


def read_file_with_encoding(
    file_path: str, encoding_override: str | None = None
) -> str:
    """
    Read a file with automatic encoding detection and UTF-8 conversion.

    Args:
        file_path: Path to file to read
        encoding_override: When provided, skip auto-detection and use this
            encoding directly.  Pass via ``CopybookSearchPath.encoding`` to
            force a specific EBCDIC variant for all copybooks in an expansion.

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
    encoding = encoding_override if encoding_override is not None else detect_encoding(file_path)

    try:
        with open(file_path, "rb") as f:
            raw_content = f.read()

        return convert_to_utf8(raw_content, encoding)

    except EncodingError:
        raise
    except Exception as e:
        raise EncodingError(file_path, f"Failed to read file: {str(e)}") from e


def expand_copybooks(
    source_code: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    preserve_source_locations: bool = False,
    validate_content: bool = True,
    validate_levels: bool = False,
    process_conditionals: bool = False,
    defined_symbols: dict[str, str] | None = None,
    max_file_size: int = MAX_COPYBOOK_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_EXPANSION_BYTES,
) -> CopybookExpansion:
    """
    Expand all COPY statements in COBOL source code by inlining copybook content.

    This is the main entry point for copybook expansion. It recursively resolves
    nested COPY statements, detects circular references, validates content,
    and optionally preserves source location metadata for error tracing.

    Args:
        source_code: COBOL source code containing COPY statements
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        preserve_source_locations: Whether to track source locations (default: False)
        validate_content: Whether to validate copybook content (default: True)
        validate_levels: Whether to validate level number alignment (default: False)
        process_conditionals: Whether to process >>IF/>>DEFINE directives (default: False)
        defined_symbols: Pre-defined symbols for conditional compilation
        max_file_size: Maximum size per copybook file in bytes
        max_total_size: Maximum total expanded content size in bytes

    Returns:
        CopybookExpansion object containing expanded source and metadata

    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        PathTraversalError: If path validation fails
        NestingDepthError: If nesting depth exceeds maximum
        EncodingError: If file encoding cannot be detected or converted
        CopybookSizeExceededError: If a copybook exceeds the size limit
        TotalExpansionSizeExceededError: If total expanded size exceeds limit
        CopybookSyntaxError: If copybook content validation fails

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

    # Pre-process conditional compilation if requested
    if process_conditionals:
        source_code = preprocess_conditional_compilation(
            source_code, defined_symbols or {}
        )

    # Create search configuration
    search_config = CopybookSearchPath(
        directories=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        max_file_size=max_file_size,
        max_total_size=max_total_size,
    )

    # Create path resolver
    path_resolver = PathResolver(search_config)

    # Create expansion context
    context = ExpansionContext(
        current_file="<main>",
        expansion_stack=[],
        current_depth=0,
        defined_symbols=dict(defined_symbols) if defined_symbols else {},
    )

    # Initialize LRU size from search config
    context.max_cache_size = search_config.max_cache_entries

    # Initialize statistics
    stats = ExpansionStatistics()
    stats.file_count = 1  # Count main program
    stats.total_bytes_processed = len(source_code.encode("utf-8"))

    # Track included copybooks
    included_copybooks: list[str] = []

    # Perform recursive expansion
    expanded_source, max_depth, is_normalized = _expand_source_recursive(
        source_code,
        "<main>",
        path_resolver,
        context,
        preserve_source_locations,
        included_copybooks,
        validate_content,
        validate_levels,
        process_conditionals,
        stats,
    )

    # Calculate statistics
    elapsed_ms = (time.time() - start_time) * 1000
    stats.parse_time_ms = elapsed_ms

    # Scan expanded lines to count them
    expanded_lines = expanded_source.splitlines()
    stats.total_lines = len(expanded_lines)
    stats.file_count = 1 + len(included_copybooks)  # Main + copybooks

    # If the result is normalized (stripped of sequence numbers), we must re-pad it
    # to ensure it is valid fixed-format COBOL for the parser/compiler.
    # If is_normalized is False, it means no changes were made (passthrough), so we return as-is.
    final_source = expanded_source
    if is_normalized:
        final_lines: list[str] = []
        for line in expanded_lines:
            if not line:
                final_lines.append(line)
            else:
                # Prepend 6 spaces for sequence area
                final_lines.append(" " * 6 + line)
        final_source = "\n".join(final_lines)
        if expanded_source.endswith("\n"):
            final_source += "\n"

    return CopybookExpansion(
        expanded_source=final_source,
        included_copybooks=included_copybooks,
        max_depth_reached=max_depth,
        source_location_map=context.source_maps if preserve_source_locations else None,
        statistics=stats,
    )


def _expand_source_recursive(
    source_code: str,
    source_file: str,
    path_resolver: PathResolver,
    context: ExpansionContext,
    preserve_locations: bool,
    included_copybooks: list[str],
    validate_content: bool = True,
    validate_levels: bool = False,
    process_conditionals: bool = False,
    stats: ExpansionStatistics | None = None,
) -> tuple[str, int, bool]:
    """
    Recursively expand COPY statements in source code.

    Args:
        source_code: Source code to expand
        source_file: Name of current file (for location tracking)
        path_resolver: Path resolver for finding copybooks
        context: Expansion context for tracking state
        preserve_locations: Whether to preserve source locations
        included_copybooks: Accumulated list of included copybook paths
        validate_content: Whether to validate copybook content
        validate_levels: Whether to validate level number alignment
        process_conditionals: Whether to process conditional directives
        stats: Statistics object to update

    Returns:
        Tuple of (expanded_source, max_depth_reached, is_normalized)
        is_normalized indicates if the returned source has had sequence numbers stripped.


    Raises:
        CircularReferenceError: If circular dependency detected
        NestingDepthError: If max nesting depth exceeded
        TotalExpansionSizeExceededError: If total size exceeds limit
    """
    # Check nesting depth
    if context.current_depth > path_resolver.search_config.max_nesting_depth:
        raise NestingDepthError(
            context.current_depth, path_resolver.search_config.max_nesting_depth
        )

    # Check for circular reference
    if source_file in context.expansion_stack:
        # Build dependency chain for error message
        chain = context.expansion_stack + [source_file]
        raise CircularReferenceError(chain)

    # Normalize source for robust matching and expansion
    # We strip sequence areas and comments to ensure the lexer works consistently
    source_no_comments = remove_comment_lines(source_code)
    source_stripped = strip_sequence_area(source_no_comments)
    # We must merge continuation lines to find statements split across lines
    normalized_source = normalize_continuation_lines(
        source_stripped, indicator_position=0
    )

    # Extract COPY statements using the robust lexer on normalized source
    lexer = CopyStatementLexer(normalized_source, source_file)
    copy_statements = lexer.tokenize_copy_statements()

    # If no COPY statements, return source unchanged to preserve full fidelity
    if not copy_statements:
        return source_code, context.current_depth, False

    # Push current file onto stack

    context.expansion_stack.append(source_file)
    max_depth = context.current_depth

    # Process COPY statements in reverse order to maintain positions
    # We use the NORMALIZED source as the base for expansion because we need valid indices
    expanded_source = normalized_source
    for statement in reversed(copy_statements):
        # Check cache first (for diamond dependency optimization)
        context.get_cache_key(statement.member_name, statement.replacing_clauses)

        # Find copybook file
        copybook_path = path_resolver.resolve(
            statement.member_name, statement.library_qualifier
        )

        # Check if we have a cached expansion (without nested COPY processing)
        # Note: We can only use cache for the same file + same replacements
        full_cache_key = context.get_cache_key(
            copybook_path, statement.replacing_clauses
        )

        expanded_copybook = context.cache_get(full_cache_key)
        if expanded_copybook is not None:
            nested_depth = context.current_depth + 1
        else:
            # Read copybook content with encoding detection (or forced override)
            copybook_content = read_file_with_encoding(
                copybook_path,
                encoding_override=path_resolver.search_config.encoding,
            )

            # Update total bytes and check limit
            content_size = len(copybook_content.encode("utf-8"))
            context.total_bytes += content_size
            if stats:
                stats.total_bytes_processed = context.total_bytes

            if context.total_bytes > path_resolver.search_config.max_total_size:
                raise TotalExpansionSizeExceededError(
                    context.total_bytes, path_resolver.search_config.max_total_size
                )

            # Validate copybook content if requested
            if validate_content:
                warnings = validate_copybook_content(copybook_content, copybook_path)
                if stats and warnings:
                    stats.warnings.extend(warnings)

            # Validate level number alignment if requested
            if validate_levels:
                # Get context before the COPY statement
                statement_start = expanded_source.find(statement.original_text)
                if statement_start != -1:
                    pre_context = expanded_source[:statement_start]
                    level_warnings = validate_level_numbers(
                        pre_context, copybook_content, copybook_path
                    )
                    if stats and level_warnings:
                        stats.warnings.extend(level_warnings)

            # Process conditional compilation directives if requested
            if process_conditionals:
                copybook_content = preprocess_conditional_compilation(
                    copybook_content, context.defined_symbols
                )

            # Track this copybook
            if copybook_path not in included_copybooks:
                included_copybooks.append(copybook_path)

            # Apply REPLACING clause if present (using enhanced function)
            if statement.replacing_clauses:
                copybook_content = apply_replacing_clauses(
                    copybook_content, statement.replacing_clauses
                )

            # Handle SUPPRESS clause (for listing control - we still include the content)
            # SUPPRESS is mainly for compiler listing output, not actual code inclusion
            # We note it in metadata but don't change the expansion behavior

            # Recursively expand nested COPY statements
            context.current_depth += 1
            context.current_file = copybook_path

            expanded_copybook, nested_depth, nested_normalized = (
                _expand_source_recursive(
                    copybook_content,
                    copybook_path,
                    path_resolver,
                    context,
                    preserve_locations,
                    included_copybooks,
                    validate_content,
                    validate_levels,
                    process_conditionals,
                    stats,
                )
            )

            # If the nested content is NOT normalized (i.e. it had no COPY statements and was returned as-is),
            # we MUST normalize it now because we are going to insert it into our 'expanded_source'
            # which IS normalized. Mixing padded and unpadded code breaks layout.
            if not nested_normalized:
                nested_no_comments = remove_comment_lines(expanded_copybook)
                nested_stripped = strip_sequence_area(nested_no_comments)
                expanded_copybook = normalize_continuation_lines(
                    nested_stripped, indicator_position=0
                )

            context.current_depth -= 1
            context.current_file = source_file

            # Cache the fully expanded result using LRU-aware method
            context.cache_put(full_cache_key, expanded_copybook)

        max_depth = max(max_depth, nested_depth)

        # Replace COPY statement with expanded content
        # Find statement in source
        # Replace COPY statement with expanded content
        # We use strict index-based replacement from the lexer tokens
        # Since we iterate in reverse, indices remain valid
        statement_start = statement.start_index
        statement_end = statement.end_index

        # Track source locations if requested
        if preserve_locations and statement.source_location:
            _, line_num, _ = statement.source_location
            # Note: With normalized source, line mapping is approximate or requires new logic
            # For now we skip or approximate logic if needed (disabled by default in expander)
            pass

        expanded_source = (
            expanded_source[:statement_start]
            + expanded_copybook
            + expanded_source[statement_end:]
        )

    # Pop current file from stack
    # Pop current file from stack
    context.expansion_stack.pop()

    # Return normalized source (we don't pad here to avoid double-padding during recursion)
    return expanded_source, max_depth, True


__all__ = [
    "detect_encoding",
    "convert_to_utf8",
    "read_file_with_encoding",
    "expand_copybooks",
    "parse_cobol_with_expansion",
]


def parse_cobol_with_expansion(
    source_code: str,
    filename: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    **parser_kwargs: Any,
) -> Any:
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
        preserve_source_locations=False,  # Parser will track its own locations
    )

    # Parse the expanded source
    parse_result = parse_cobol(
        source=expansion.expanded_source, filename=filename, **parser_kwargs
    )

    return parse_result
