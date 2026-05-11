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
- SUPPRESS clause support for listing control
- REPLACING clause with LEADING/TRAILING modifiers
- Conditional compilation directive processing (>>IF/>>DEFINE)
- Copybook content validation and size limits
- Fuzzy matching for misspelled copybook names

Main Functions:
    expand_copybooks: Expand all COPY statements in COBOL source code
    parse_cobol_with_expansion: Convenience function combining expansion + parsing
    normalize_fixed_format: Normalize fixed-format COBOL lines into pseudo free-form
    preprocess_conditional_compilation: Process >>IF/>>DEFINE directives
    validate_copybook_content: Validate copybook content before expansion

Exception Types:
    CircularReferenceError: Circular copybook dependency detected
    CopybookNotFoundError: Copybook file not found in search paths
    PathTraversalError: Attempted path traversal outside search directories
    EncodingError: Failed to detect or convert file encoding
    NestingDepthError: Exceeded maximum nesting depth limit
    CopybookSizeExceededError: Copybook exceeds configured size limits
    CopybookSyntaxError: Copybook contains invalid or malformed content

Usage Example:
    from cobolparser.preprocess import expand_copybooks, normalize_fixed_format

    result = expand_copybooks(
        source_code=cobol_program,
        copybook_paths=["/path/to/copybooks"],
        max_nesting_depth=100
    )
    print(result.expanded_source)
"""

import re
from collections.abc import Iterable
from typing import Optional

# Pre-compiled regex patterns for preprocessing (avoids re-compilation per call)
_DEFINE_RE = re.compile(r">>DEFINE\s+(\w+)(?:\s+AS\s+(.+))?")
_IS_DEFINED_RE = re.compile(r"(\w+)\s+IS\s+(NOT\s+)?DEFINED")
_DATA_DEF_RE = re.compile(
    r"^\s*\d{2}\s+[A-Za-z][A-Za-z0-9-]*\s+PIC\s+[^\s]+\s*$", re.MULTILINE
)
_LEVEL_NUMBER_RE = re.compile(r"^\s*(\d{2})\s+[A-Za-z]", re.MULTILINE)


class PreprocessingError(Exception):
    """Base class for all preprocessing exceptions.

    Catch this to handle any failure that occurs during copybook expansion
    or source normalization, without needing to enumerate every subtype.
    """

    pass


class CircularReferenceError(PreprocessingError):
    """
    Raised when a circular dependency is detected in copybook includes.

    Attributes:
        dependency_chain: List of copybook names showing the circular path
        message: Human-readable error message with dependency chain
    """

    def __init__(self, dependency_chain: list[str], message: str | None = None):
        self.dependency_chain = dependency_chain
        if message is None:
            chain_str = " → ".join(dependency_chain)
            message = f"Circular copybook dependency detected: {chain_str}"
        super().__init__(message)


class CopybookNotFoundError(PreprocessingError):
    """
    Raised when a referenced copybook file cannot be found.

    Attributes:
        copybook_name: Name of the copybook that was not found
        search_paths: List of directories that were searched
        suggestions: List of similar copybook names (for typo detection)
        message: Human-readable error message
    """

    def __init__(
        self,
        copybook_name: str,
        search_paths: list[str],
        suggestions: list[str] | None = None,
        message: str | None = None,
    ):
        self.copybook_name = copybook_name
        self.search_paths = search_paths
        self.suggestions = suggestions or []
        if message is None:
            paths_str = (
                ", ".join(search_paths) if search_paths else "(no paths configured)"
            )
            message = (
                f"Copybook '{copybook_name}' not found in search paths: {paths_str}"
            )
            if self.suggestions:
                message += f". Did you mean: {', '.join(self.suggestions)}?"
        super().__init__(message)


class PathTraversalError(PreprocessingError):
    """
    Raised when a path traversal attempt is detected (security violation).

    Attributes:
        attempted_path: The path that triggered the security violation
        message: Human-readable error message
    """

    def __init__(self, attempted_path: str, message: str | None = None):
        self.attempted_path = attempted_path
        if message is None:
            message = f"Path traversal attempt detected: '{attempted_path}' attempts to escape search directories"
        super().__init__(message)


class EncodingError(PreprocessingError):
    """
    Raised when file encoding cannot be detected or conversion fails.

    Attributes:
        file_path: Path to the file with encoding issues
        details: Additional details about the encoding problem
        message: Human-readable error message
    """

    def __init__(
        self, file_path: str, details: str | None = None, message: str | None = None
    ):
        self.file_path = file_path
        self.details = details
        if message is None:
            message = f"Encoding error for file '{file_path}'"
            if details:
                message += f": {details}"
        super().__init__(message)


class NestingDepthError(PreprocessingError):
    """
    Raised when copybook nesting exceeds the configured maximum depth.

    Attributes:
        current_depth: The nesting depth that was reached
        max_depth: The configured maximum depth limit
        message: Human-readable error message
    """

    def __init__(self, current_depth: int, max_depth: int, message: str | None = None):
        self.current_depth = current_depth
        self.max_depth = max_depth
        if message is None:
            message = f"Nesting depth exceeded: reached {current_depth} levels (max: {max_depth})"
        super().__init__(message)


class CopybookSizeExceededError(PreprocessingError):
    """
    Raised when a copybook file exceeds the configured size limit.

    Attributes:
        copybook_path: Path to the oversized copybook
        size: Actual size in bytes
        limit: Configured size limit in bytes
        message: Human-readable error message
    """

    def __init__(
        self, copybook_path: str, size: int, limit: int, message: str | None = None
    ):
        self.copybook_path = copybook_path
        self.size = size
        self.limit = limit
        if message is None:
            message = (
                f"Copybook '{copybook_path}' size ({size:,} bytes) "
                f"exceeds limit ({limit:,} bytes)"
            )
        super().__init__(message)


class CopybookSyntaxError(PreprocessingError):
    """
    Raised when copybook contains invalid or malformed content.

    Attributes:
        copybook_path: Path to the copybook with syntax issues
        line: Line number where issue was detected (if applicable)
        details: Description of the syntax problem
        message: Human-readable error message
    """

    def __init__(
        self,
        copybook_path: str,
        details: str,
        line: int | None = None,
        message: str | None = None,
    ):
        self.copybook_path = copybook_path
        self.line = line
        self.details = details
        if message is None:
            if line:
                message = f"Syntax error in '{copybook_path}' at line {line}: {details}"
            else:
                message = f"Syntax error in '{copybook_path}': {details}"
        super().__init__(message)


class LevelNumberMismatchWarning(UserWarning):
    """
    Warning issued when level numbers may not align correctly after expansion.

    This is a warning rather than an error because some level mismatches
    may be intentional (e.g., copybook designed for specific contexts).
    """

    pass


class TotalExpansionSizeExceededError(PreprocessingError):
    """
    Raised when total expanded content exceeds the configured limit.

    Attributes:
        total_size: Total size reached in bytes
        limit: Configured limit in bytes
        message: Human-readable error message
    """

    def __init__(self, total_size: int, limit: int, message: str | None = None):
        self.total_size = total_size
        self.limit = limit
        if message is None:
            message = (
                f"Total expansion size ({total_size:,} bytes) "
                f"exceeds limit ({limit:,} bytes)"
            )
        super().__init__(message)


# Fixed-format COBOL normalization constants
DEFAULT_SEQ_COL_END = 6  # 1-6 sequence numbers
INDICATOR_COL = 7  # column 7 indicator position (1-based)
TEXT_START_COL = 8  # program text begins (1-based)
TEXT_END_COL = 72  # program text end (inclusive, 1-based)


def strip_compiler_directives(
    source: str, *, preserve_line_numbers: bool = True
) -> str:
    """Remove PROCESS and CBL compiler directives from fixed-format COBOL source.

    This function processes raw fixed-format COBOL lines and removes any
    PROCESS or CBL compiler directives that appear before the IDENTIFICATION
    DIVISION. It handles continuation lines and preserves line numbers for
    accurate error reporting.

    Compiler directives are identified by:
    - Lines starting with "PROCESS" or "CBL" in columns 8-72 (or at start if no sequence area)
    - Continuation lines (indicator '-' in column 7)
    - Must appear before IDENTIFICATION DIVISION

    Args:
        source: Fixed-format COBOL source code (may or may not have sequence area)
        preserve_line_numbers: Replace removed lines with blank lines (default: True)

    Returns:
        Cleaned source code with PROCESS/CBL directives removed

    Note:
        This should be called BEFORE normalize_fixed_format().

    Example:
        >>> source = '''PROCESS APOST
        ...        IDENTIFICATION DIVISION.'''
        >>> result = strip_compiler_directives(source)
        >>> 'PROCESS' in result
        False
        >>> 'IDENTIFICATION' in result
        True
    """
    lines = source.splitlines(keepends=True)
    result_lines = []
    in_directive_section = True  # We start in the directive section
    in_continuation = False

    for line in lines:
        # Preserve the original line ending
        line_content = line.rstrip("\r\n")
        line_ending = line[len(line_content) :]

        # Determine where program text starts
        # Check if line has sequence area (columns 1-7 are typically spaces or sequence numbers)
        # If line starts with non-space in first 7 positions, it's likely without sequence area
        has_sequence_area = False
        if len(line_content) >= TEXT_START_COL:
            # Check if first 7 chars look like sequence area (spaces or digits)
            first_seven = line_content[: TEXT_START_COL - 1]
            # If first 7 chars are all spaces or digits, it's likely a sequence area
            if first_seven.strip() == "" or first_seven.replace(" ", "").isdigit():
                has_sequence_area = True

        if has_sequence_area:
            text_start = TEXT_START_COL - 1
            indicator_pos = INDICATOR_COL - 1
        else:
            # No sequence area - text starts at beginning
            text_start = 0
            indicator_pos = 6 if len(line_content) > 6 else 0

        # Extract program text area
        text_area = (
            line_content[text_start:].strip() if len(line_content) > text_start else ""
        )

        # Check if we've reached IDENTIFICATION DIVISION
        # This marks the end of the directive section
        if in_directive_section and text_area:
            text_upper = text_area.upper()
            if text_upper.startswith("IDENTIFICATION") or text_upper.startswith("ID "):
                in_directive_section = False
                in_continuation = False
                result_lines.append(line)
                continue

        # If we're past the directive section, keep all lines
        if not in_directive_section:
            result_lines.append(line)
            continue

        # We're in the directive section - check for PROCESS/CBL
        # Get the indicator column (column 7, or position 6 for short lines)
        indicator = (
            line_content[indicator_pos] if len(line_content) > indicator_pos else " "
        )

        # Check for continuation line
        if indicator == "-":
            if in_continuation:
                # This is a continuation of a PROCESS/CBL directive
                if preserve_line_numbers:
                    result_lines.append(line_ending)  # Blank line
                # else: skip entirely
                continue
            else:
                # Continuation of something else (shouldn't happen before IDENTIFICATION)
                result_lines.append(line)
                continue

        # Not a continuation line - check if it's a PROCESS/CBL directive
        if text_area:
            text_upper = text_area.upper()

            # Check if line starts with PROCESS or CBL
            # Handle various formats: "PROCESS ", "PROCESS\t", "PROCESS", "CBL ", etc.
            is_directive = False
            if text_upper == "PROCESS" or text_upper == "CBL":
                is_directive = True
            elif text_upper.startswith("PROCESS ") or text_upper.startswith(
                "PROCESS\t"
            ):
                is_directive = True
            elif text_upper.startswith("CBL ") or text_upper.startswith("CBL\t"):
                is_directive = True

            if is_directive:
                # This is a PROCESS/CBL directive
                in_continuation = True
                if preserve_line_numbers:
                    result_lines.append(line_ending)  # Blank line
                # else: skip entirely
                continue

        # Not a directive - keep the line
        in_continuation = False
        result_lines.append(line)

    return "".join(result_lines)


def normalize_fixed_format(
    lines: Iterable[str], *, merge_continued_literals: bool = True
) -> str:
    """Normalize fixed-format COBOL lines into a pseudo free-form block.

    Steps:
    - Strip sequence area (cols 1-6).
    - Capture indicator column; treat '*' and '/' lines as comments (preserve as-is).
    - Extract program text cols 8-72.
    - If a continuation line (indicator '-') occurs and previous line ended inside a literal,
      merge without inserting a newline.
    - Otherwise join with newlines.

    This does NOT attempt full column-sensitive semantics (debugging helper).
    """
    result: list[str] = []
    pending_literal = False
    quote_char: str | None = None
    parts: list[str] = []  # accumulates chunks for the current logical line
    # Track quote state incrementally to avoid O(n²) rescanning
    _quote_open = False
    _quote_ch: str | None = None

    def _update_quote_state(text: str) -> None:
        """Incrementally update quote state for new text chunk."""
        nonlocal _quote_open, _quote_ch, pending_literal, quote_char
        if not text:
            pending_literal = _quote_open
            quote_char = _quote_ch
            return

        if not _quote_open:
            first_single = text.find("'")
            first_double = text.find('"')

            if first_single == -1 and first_double == -1:
                pending_literal = False
                quote_char = None
                return

            if first_single == -1:
                i = first_double
            elif first_double == -1:
                i = first_single
            else:
                i = min(first_single, first_double)
        else:
            i = 0

        while i < len(text):
            ch = text[i]
            if _quote_open:
                if ch == _quote_ch:
                    if i + 1 < len(text) and text[i + 1] == _quote_ch:
                        i += 2  # escaped quote
                        continue
                    _quote_open = False
                    _quote_ch = None
                i += 1
            else:
                if ch in ("'", '"'):
                    _quote_open = True
                    _quote_ch = ch
                    i += 1
                else:
                    i += 1
        pending_literal = _quote_open
        quote_char = _quote_ch

    def flush_parts() -> None:
        nonlocal parts, _quote_open, _quote_ch, pending_literal, quote_char
        combined = "".join(parts)
        if combined:
            result.append(combined)
        parts = []
        # Reset quote state for new logical line
        _quote_open = False
        _quote_ch = None
        pending_literal = False
        quote_char = None

    for raw in lines:
        line = raw.rstrip("\n")
        if len(line) < TEXT_START_COL - 1:
            flush_parts()
            continue
        indicator = line[INDICATOR_COL - 1] if len(line) >= INDICATOR_COL else " "
        text_slice = line[TEXT_START_COL - 1 : TEXT_END_COL]
        if indicator in ("*", "/"):  # comment (including page eject)
            # Comment lines: flush pending buffer but do not emit comment text.
            # Emitting comment text causes the free-form lexer to tokenize it as code.
            flush_parts()
            pending_literal = False
            continue
        is_cont = indicator == "-"

        # Handle continuation lines
        if is_cont:
            # This is a continuation line - merge with previous buffer
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and chunk[0] == quote_char:
                    chunk = chunk[1:]
                stripped = chunk.rstrip()
                parts.append(stripped)
                if merge_continued_literals:
                    _update_quote_state(stripped)
            else:
                stripped = " " + text_slice.lstrip()
                parts.append(stripped)
                if merge_continued_literals:
                    _update_quote_state(stripped)
        else:
            # Non-continuation line - start new logical line
            flush_parts()
            stripped = text_slice.rstrip()
            parts.append(stripped)
            if merge_continued_literals:
                _update_quote_state(stripped)

    # Save state before final flush
    final_pending_literal = pending_literal
    final_quote_char = quote_char
    flush_parts()

    # If pending_literal is True at EOF there is no subsequent continuation line,
    # so the string is genuinely unterminated.
    if final_pending_literal and merge_continued_literals:
        raise ValueError(
            f"Unterminated string literal at end of input "
            f"(opened with quote character '{final_quote_char or '?'}')"
        )

    return "\n".join(result) + "\n"


def preprocess_conditional_compilation(
    source: str, defined_symbols: dict[str, str] | None = None
) -> str:
    """
    Process IBM >>IF/>>DEFINE conditional compilation directives.

    Supports:
    - >>DEFINE symbol [AS value]
    - >>IF symbol IS DEFINED / IS NOT DEFINED
    - >>ELSE
    - >>END-IF
    - >>EVALUATE (basic support)

    Args:
        source: COBOL source code containing directives
        defined_symbols: Pre-defined symbols (optional)

    Returns:
        Source code with conditional sections processed

    Example:
        >>> source = '''
        ... >>DEFINE DEBUG
        ... >>IF DEBUG IS DEFINED
        ...        DISPLAY "Debug mode".
        ... >>END-IF
        ... '''
        >>> preprocess_conditional_compilation(source)
        '       DISPLAY "Debug mode".\\n'
    """
    defined = dict(defined_symbols) if defined_symbols else {}
    result_lines = []
    skip_stack = [False]  # Stack of skip states (False = include lines)

    for line in source.splitlines():
        stripped = line.strip().upper()

        # >>DEFINE symbol [AS value]
        if stripped.startswith(">>DEFINE"):
            match = _DEFINE_RE.match(stripped)
            if match:
                symbol = match.group(1)
                value = match.group(2).strip() if match.group(2) else "TRUE"
                defined[symbol] = value
            continue

        # >>IF condition
        elif stripped.startswith(">>IF"):
            condition_text = stripped[4:].strip()

            # Parse condition
            is_defined_match = _IS_DEFINED_RE.match(condition_text)
            if is_defined_match:
                symbol = is_defined_match.group(1)
                is_not = is_defined_match.group(2) is not None

                symbol_exists = symbol in defined
                condition_met = (not symbol_exists) if is_not else symbol_exists

                # If currently skipping, continue skipping
                if any(skip_stack):
                    skip_stack.append(True)
                else:
                    skip_stack.append(not condition_met)
            else:
                # Unknown condition - default to skipping
                skip_stack.append(True)
            continue

        # >>ELSE
        elif stripped.startswith(">>ELSE"):
            if len(skip_stack) > 1:
                # Only toggle if parent is not skipping
                parent_skip = any(skip_stack[:-1])
                if not parent_skip:
                    skip_stack[-1] = not skip_stack[-1]
            continue

        # >>END-IF
        elif stripped.startswith(">>END-IF"):
            if len(skip_stack) > 1:
                skip_stack.pop()
            continue

        # Regular line - include if not skipping
        if not any(skip_stack):
            result_lines.append(line)

    return "\n".join(result_lines)


def validate_copybook_content(content: str, copybook_path: str) -> list[str]:
    """
    Validate copybook content before expansion.

    Checks for:
    - Empty content
    - Binary/corrupted content
    - Unbalanced quotes
    - Missing terminating periods
    - Other potential issues

    Args:
        content: Copybook content to validate
        copybook_path: Path to copybook (for error messages)

    Returns:
        List of warning messages (empty if no issues)

    Raises:
        CopybookSyntaxError: For fatal syntax issues like binary content
    """
    warnings = []

    # Check for empty content
    stripped = content.strip()
    if not stripped:
        warnings.append(f"Copybook '{copybook_path}' is empty")
        return warnings

    # Check for comment-only content
    lines = [
        line
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("*")
    ]
    if not lines:
        warnings.append(f"Copybook '{copybook_path}' contains only comments")

    # Check for binary content indicators
    if "\x00" in content:
        raise CopybookSyntaxError(
            copybook_path, "Binary content detected (null bytes found)"
        )

    # Check for unbalanced quotes (simple check)
    single_quotes = content.count("'")
    double_quotes = content.count('"')

    # Account for escaped quotes (doubled quotes)
    single_escaped = content.count("''")
    double_escaped = content.count('""')

    effective_singles = single_quotes - (single_escaped * 2)
    effective_doubles = double_quotes - (double_escaped * 2)

    if effective_singles % 2 != 0:
        warnings.append(f"Possible unbalanced single quotes in '{copybook_path}'")
    if effective_doubles % 2 != 0:
        warnings.append(f"Possible unbalanced double quotes in '{copybook_path}'")

    # Check for potential missing terminating period on data definitions
    for match in _DATA_DEF_RE.finditer(content):
        line_num = content[: match.start()].count("\n") + 1
        warnings.append(
            f"Line {line_num} in '{copybook_path}' may be missing terminating period"
        )

    return warnings


def validate_level_numbers(
    pre_context: str, copybook_content: str, copybook_path: str
) -> list[str]:
    """
    Validate level number continuity between main program and copybook.

    Args:
        pre_context: Source code before the COPY statement
        copybook_content: Content of the copybook being included
        copybook_path: Path to copybook (for messages)

    Returns:
        List of warning messages about potential level mismatches
    """
    import warnings as warn_module

    warnings: list[str] = []

    # Extract last level number before COPY statement
    pre_levels = list(_LEVEL_NUMBER_RE.finditer(pre_context))
    if not pre_levels:
        return warnings  # No prior data definitions

    last_level = int(pre_levels[-1].group(1))

    # Extract first level number in copybook
    copy_levels = list(_LEVEL_NUMBER_RE.finditer(copybook_content))
    if not copy_levels:
        return warnings  # No data definitions in copybook

    first_copy_level = int(copy_levels[0].group(1))

    # Check for potential issues
    if first_copy_level not in (1, 77, 88):  # 01, 77, 88 can start anywhere
        if first_copy_level <= last_level:
            msg = (
                f"Level number mismatch: copybook '{copybook_path}' starts with "
                f"level {first_copy_level:02d} after level {last_level:02d} in main program. "
                f"This may cause data hierarchy issues."
            )
            warnings.append(msg)
            warn_module.warn(msg, LevelNumberMismatchWarning, stacklevel=2)

    return warnings


__all__ = [
    "CircularReferenceError",
    "CopybookNotFoundError",
    "PathTraversalError",
    "EncodingError",
    "NestingDepthError",
    "CopybookSizeExceededError",
    "CopybookSyntaxError",
    "LevelNumberMismatchWarning",
    "TotalExpansionSizeExceededError",
    "strip_compiler_directives",
    "normalize_fixed_format",
    "preprocess_conditional_compilation",
    "validate_copybook_content",
    "validate_level_numbers",
    "expand_copybooks",
    "parse_cobol_with_expansion",
]


# Import functions from submodules for convenience
from .copybook_expander import (  # noqa: E402
    expand_copybooks,
    parse_cobol_with_expansion,
)

# ---------------------------------------------------------------------------
# Optional Cython fast path for normalize_fixed_format.
# Falls back to the pure-Python implementation silently when not compiled.
# ---------------------------------------------------------------------------
try:
    from cobolparser._preprocess_fast import (  # type: ignore[import-not-found,no-redef]
        normalize_fixed_format,
    )
except ImportError:
    pass  # pure-Python normalize_fixed_format defined above is used
