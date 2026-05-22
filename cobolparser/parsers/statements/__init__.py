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

from .accept_parser import AcceptStatementParser
from .arithmetic_parsers import (
    AddStatementParser,
    ComputeStatementParser,
    DivideStatementParser,
    MultiplyStatementParser,
    SubtractStatementParser,
)
from .call_parser import CallStatementParser
from .close_parser import CloseStatementParser
from .delete_parser import DeleteStatementParser
from .display_parser import DisplayStatementParser
from .entry_parser import EntryStatementParser
from .evaluate_parser import EvaluateStatementParser
from .go_parser import GoStatementParser
from .ibm_exec_statements import (
    ExecCicsStatementParser,
    ExecImsStatementParser,
    ExecSqlStatementParser,
)
from .if_parser import IfStatementParser
from .initialize_inspect_parsers import (
    InitializeStatementParser,
    InspectStatementParser,
)
from .move_parser import MoveStatementParser
from .open_parser import OpenStatementParser
from .perform_parser import PerformStatementParser
from .read_parser import ReadStatementParser
from .rewrite_parser import RewriteStatementParser
from .search_parser import SearchStatementParser
from .set_parser import SetStatementParser
from .simple_statement_parsers import (
    AlterStatementParser,
    CancelStatementParser,
    CommitStatementParser,
    ContinueStatementParser,
    ExitStatementParser,
    GenerateStatementParser,
    GobackStatementParser,
    ReleaseStatementParser,
    ReturnStatementParser,
    RollbackStatementParser,
    UseStatementParser,
)
from .sort_merge_parsers import MergeStatementParser, SortStatementParser
from .start_parser import StartStatementParser
from .string_unstring_parsers import (
    StringStatementParser,
    UnstringStatementParser,
)
from .unlock_parser import UnlockStatementParser

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
    "ExecImsStatementParser",
    "EntryStatementParser",
    "GoStatementParser",
    "ReadStatementParser",
    "OpenStatementParser",
    "CloseStatementParser",
    "RewriteStatementParser",
    "DeleteStatementParser",
    "StartStatementParser",
    # New parsers
    "AcceptStatementParser",
    "ContinueStatementParser",
    "ExitStatementParser",
    "GobackStatementParser",
    "CancelStatementParser",
    "AlterStatementParser",
    "GenerateStatementParser",
    "ReleaseStatementParser",
    "ReturnStatementParser",
    "UseStatementParser",
    "SearchStatementParser",
    "StringStatementParser",
    "UnstringStatementParser",
    "InitializeStatementParser",
    "InspectStatementParser",
    "SetStatementParser",
    "SortStatementParser",
    "MergeStatementParser",
    "UnlockStatementParser",
    "CommitStatementParser",
    "RollbackStatementParser",
]
