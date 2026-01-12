"""
COBOL Parser - A comprehensive COBOL parser for Python with IBM Enterprise COBOL focus.

This package provides modern Python tools for parsing, analyzing, and working with
COBOL source code, with special emphasis on IBM Enterprise COBOL dialects.

Key Features:
- Configurable memory management (64MB-8GB limits)
- JSON export for cross-platform interoperability
- Enhanced error recovery modes (fail-fast vs collect-all)
- IBM Enterprise COBOL dialect priority
- Test-driven development with 90%+ code coverage

Basic Usage:
    >>> from cobolparser import CobolParser, MemoryConfiguration, ErrorRecoveryMode
    >>>
    >>> # Configure parser with memory limits and error handling
    >>> config = MemoryConfiguration(max_memory_mb=256)
    >>> parser = CobolParser(
    ...     memory_config=config,
    ...     error_recovery=ErrorRecoveryMode.COLLECT_ALL
    ... )
    >>>
    >>> # Parse COBOL source
    >>> with open('program.cbl', 'r') as f:
    ...     ast = parser.parse(f.read())
    >>>
    >>> # Export to JSON for interoperability
    >>> json_output = ast.to_json()

Advanced Usage:
    >>> from cobolparser.dialects import IBMEnterpriseCobol
    >>> from cobolparser.plugins import SerializationConfig
    >>>
    >>> # Use IBM Enterprise COBOL dialect with custom serialization
    >>> dialect = IBMEnterpriseCobol()
    >>> serialization = SerializationConfig(include_metadata=True)
    >>> parser = CobolParser(dialect=dialect, serialization_config=serialization)

Memory Management:
    The parser includes sophisticated memory management to handle large COBOL programs:

    >>> # Configure for large programs (up to 8GB)
    >>> heavy_config = MemoryConfiguration(
    ...     max_memory_mb=8192,
    ...     enable_streaming=True,
    ...     chunk_size_kb=1024
    ... )
    >>> parser = CobolParser(memory_config=heavy_config)

Error Recovery:
    Choose between fail-fast and collect-all error recovery modes:

    >>> # Fail on first error (default)
    >>> strict_parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
    >>>
    >>> # Collect all errors for comprehensive reporting
    >>> lenient_parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
"""

# Import implemented modules
from .plugins.core import (
    MemoryConfiguration,
    SerializationConfig,
    ErrorRecoveryMode,
    DialectType,
    PluginManager,
    ParseError,
    ParseStatistics,
)
from .models.ast_base import (
    SourceLocation,
    ASTNode,
)
from .models.program import (
    CobolProgram,
    CobolDivision,
    CobolSection,
)
from .models.statements import (
    CobolStatement,
    CobolExpression,
    MoveStatement,
    DisplayStatement,
    PerformStatement,
    EvaluateStatement,
    WhenClause,
)
from .models.data_items import (
    CobolDataItem,
    PictureClause,
    OccursClause,
)
from .lexer import (
    CobolLexer,
    Token,
    TokenType,
    LexerError,
    tokenize_cobol,
)

from .parser import (
    CobolParser,
    ParseResult,
    ParseState,
    parse_cobol,
)

# Import normalize_fixed_format from the preprocess package
from .preprocess import normalize_fixed_format

from .dialects import (
    IBMEnterpriseCobol,
)

# Copybook expansion (preprocessing)
from .preprocess.copybook_expander import (
    expand_copybooks,
    parse_cobol_with_expansion,
)
from .preprocess.models import (
    CopybookExpansion,
    CopyStatement,
    CopybookSearchPath,
    ExpansionStatistics,
)
from .preprocess import (
    CircularReferenceError,
    CopybookNotFoundError,
    PathTraversalError,
    EncodingError,
    NestingDepthError,
)

# Analysis utilities
from .analysis import (
    DynamicCallAnalyzer,
)

# Other dialects will be added when implemented
# from .dialects import (
#     ANSICobol,
#     MicroFocusCobol,
# )

# Version info
__version__ = "1.0.0"
__author__ = "COBOL Parser Team"
__license__ = "MIT"

# Public API - controls what gets imported with "from cobolparser import *"
__all__ = [
    # Core parsing errors and configuration
    "ParseError",
    "ParseStatistics",
    # AST model classes
    "CobolProgram",
    "CobolDivision",
    "CobolSection",
    "CobolStatement",
    "CobolExpression",
    "EvaluateStatement",
    "WhenClause",
    "CobolDataItem",
    "SourceLocation",
    "ASTNode",
    "MoveStatement",
    "DisplayStatement",
    "PerformStatement",
    "PictureClause",
    "OccursClause",
    # Lexer components
    "CobolLexer",
    "Token",
    "TokenType",
    "LexerError",
    "tokenize_cobol",
    # Parser components
    "CobolParser",
    "ParseResult",
    "ParseState",
    "parse_cobol",
    # Preprocessing utilities
    "normalize_fixed_format",
    # Enhanced features
    "MemoryConfiguration",
    "SerializationConfig",
    "ErrorRecoveryMode",
    "DialectType",
    "PluginManager",
    # Package metadata
    "__version__",
    "__author__",
    "__license__",
    # Dialect support
    "IBMEnterpriseCobol",
    # Copybook expansion
    "expand_copybooks",
    "parse_cobol_with_expansion",
    "CopybookExpansion",
    "CopyStatement",
    "CopybookSearchPath",
    "ExpansionStatistics",
    "CircularReferenceError",
    "CopybookNotFoundError",
    "PathTraversalError",
    "EncodingError",
    "NestingDepthError",
    # Analysis utilities
    "DynamicCallAnalyzer",
    # Will be added when implemented:
    # "ANSICobol",
    # "MicroFocusCobol",
]

# Configure default logging for the package
import logging

_logger = logging.getLogger(__name__)
_logger.addHandler(logging.NullHandler())
