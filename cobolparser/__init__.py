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
# Analysis utilities
from .analysis import (
    DeadCodeAnalyzer,
    DeadCodeItem,
    DeadCodeReport,
    DynamicCallAnalyzer,
    IOLogger,
    IOLogReport,
    IOOperation,
)
from .batch import (
    BatchResult,
    parse_files,
)
from .dialects import (
    IBMEnterpriseCobol,
)
from .lexer import (
    CobolLexer,
    LexerError,
    Token,
    TokenType,
    tokenize_cobol,
)
from .models.ast_base import (
    ASTNode,
    SourceLocation,
)
from .models.data_items import (
    CobolDataItem,
    OccursClause,
    PictureClause,
)
from .models.program import (
    CobolDivision,
    CobolProgram,
    CobolSection,
)
from .models.statements import (
    CobolExpression,
    CobolStatement,
    DisplayStatement,
    EvaluateStatement,
    MoveStatement,
    PerformStatement,
    WhenClause,
)
from .parser import (
    CobolParser,
    ParseResult,
    parse_cobol,
)
from .plugins.core import (
    DialectType,
    ErrorRecoveryMode,
    MemoryConfiguration,
    ParseError,
    ParseStatistics,
    PluginManager,
    SerializationConfig,
)

# Import normalize_fixed_format from the preprocess package
from .preprocess import (
    CircularReferenceError,
    CopybookNotFoundError,
    EncodingError,
    NestingDepthError,
    PathTraversalError,
    PreprocessingError,
    normalize_fixed_format,
)

# Copybook expansion (preprocessing)
from .preprocess.copybook_expander import (
    expand_copybooks,
    parse_cobol_with_expansion,
)
from .preprocess.models import (
    CopybookExpansion,
    CopybookSearchPath,
    CopyStatement,
    ExpansionStatistics,
)

# Other dialects will be added when implemented
# from .dialects import (
#     ANSICobol,
#     MicroFocusCobol,
# )

# Version info
__version__ = "1.0.0"
__author__ = "Samuel Dion"
__license__ = "Proprietary"

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
    "parse_cobol",
    # Batch parsing
    "parse_files",
    "BatchResult",
    # Preprocessing utilities
    "normalize_fixed_format",
    # Enhanced features
    "MemoryConfiguration",
    "SerializationConfig",
    "ErrorRecoveryMode",
    "DialectType",
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
    "PreprocessingError",
    "CircularReferenceError",
    "CopybookNotFoundError",
    "PathTraversalError",
    "EncodingError",
    "NestingDepthError",
    # Analysis utilities
    "DeadCodeAnalyzer",
    "DeadCodeReport",
    "DeadCodeItem",
    "DynamicCallAnalyzer",
    "IOLogger",
    "IOLogReport",
    "IOOperation",
    # Will be added when implemented:
    # "ANSICobol",
    # "MicroFocusCobol",
]

# Configure default logging for the package
import logging

_logger = logging.getLogger(__name__)
_logger.addHandler(logging.NullHandler())
