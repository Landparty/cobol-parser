"""
Statement Parsers - Individual parsers for COBOL statement types.

This package contains all statement-specific parsers, organized and
registered through the StatementParserRegistry for dynamic dispatch.

Statement parsers are extracted from procedure division parsing to:
- Reduce parser.py line count and complexity
- Support extensible statement type recognition
- Enable custom statement parser registration
- Implement SOLID principles (Single Responsibility)

Each statement parser implements the IStatementParser interface from
cobolparser.core.interfaces.

Parsers can be registered with the StatementParserRegistry using keyword
patterns for matching statement starts.

Example:
    from cobolparser.core.statement_registry import StatementParserRegistry
    from cobolparser.parsers.statements.display_parser import DisplayStatementParser
    
    registry = StatementParserRegistry()
    registry.register(DisplayStatementParser())
    parser = registry.find_parser(token_stream)  # Finds matching parser
"""

from .display_parser import DisplayStatementParser
from .move_parser import MoveStatementParser
from .if_parser import IfStatementParser
from .perform_parser import PerformStatementParser
from .evaluate_parser import EvaluateStatementParser
from .call_parser import CallStatementParser
from .arithmetic_parsers import (
    AddStatementParser,
    SubtractStatementParser,
    MultiplyStatementParser,
    DivideStatementParser,
    ComputeStatementParser,
)
from .ibm_exec_statements import (
    ExecSqlStatementParser,
    ExecCicsStatementParser,
)
from .entry_parser import EntryStatementParser
from .go_parser import GoStatementParser

__all__ = [
    "DisplayStatementParser",
    "MoveStatementParser",
    "IfStatementParser",
    "PerformStatementParser",
    "EvaluateStatementParser",
    "CallStatementParser",
    "AddStatementParser",
    "SubtractStatementParser",
    "MultiplyStatementParser",
    "DivideStatementParser",
    "ComputeStatementParser",
    "ExecSqlStatementParser",
    "ExecCicsStatementParser",
    "EntryStatementParser",
    "GoStatementParser",
]
