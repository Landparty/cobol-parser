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
- Conditional compilation directive processing (>>DEFINE/>>IF/>>EVALUATE)
- Copybook content validation and size limits
- Fuzzy matching for misspelled copybook names

Main Functions:
    expand_copybooks: Expand all COPY statements in COBOL source code
    parse_cobol_with_expansion: Convenience function combining expansion + parsing
    normalize_fixed_format: Normalize fixed-format COBOL lines into pseudo free-form
    preprocess_conditional_compilation: Process >>DEFINE/>>IF/>>EVALUATE directives
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

# NOTE: keep this file a thin re-export stub. Implementation belongs in
# _normalize.py (or another private sibling), not here.
from ._normalize import (
    ALL_COMMENT_INDICATORS,
    COMMENT_INDICATORS,
    DEBUG_INDICATORS,
    DEFAULT_SEQ_COL_END,
    IDENTIFICATION_END_COL,
    INDICATOR_COL,
    TEXT_END_COL,
    TEXT_START_COL,
    VERSION_TAG_INDICATORS,
    CircularReferenceError,
    CopybookNotFoundError,
    CopybookSizeExceededError,
    CopybookSyntaxError,
    EncodingError,
    LevelNumberMismatchWarning,
    NestingDepthError,
    PathTraversalError,
    PreprocessingError,
    TotalExpansionSizeExceededError,
    normalize_fixed_format,
    preprocess_conditional_compilation,
    strip_compiler_directives,
    validate_copybook_content,
    validate_level_numbers,
)

__all__ = [
    "ALL_COMMENT_INDICATORS",
    "COMMENT_INDICATORS",
    "DEBUG_INDICATORS",
    "VERSION_TAG_INDICATORS",
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
    "clear_file_cache",
    "set_file_cache_size",
    "get_file_cache_stats",
]


# Import functions from submodules for convenience
from .copybook_expander import (  # noqa: E402
    clear_file_cache,
    expand_copybooks,
    get_file_cache_stats,
    parse_cobol_with_expansion,
    set_file_cache_size,
)

# ---------------------------------------------------------------------------
# Optional Cython fast path for normalize_fixed_format.
# Falls back to the pure-Python implementation silently when not compiled.
# ---------------------------------------------------------------------------
# Keep the pure-Python implementation reachable under a private name even when
# the Cython extension overrides the public one (mirrors lexer._CobolLexerPure),
# so both code paths can be exercised by the test suite.
_normalize_fixed_format_pure = normalize_fixed_format

try:
    from cobolparser._preprocess_fast import (  # type: ignore[import-not-found,no-redef]
        normalize_fixed_format,
    )
except ImportError:
    pass  # pure-Python normalize_fixed_format defined above is used
