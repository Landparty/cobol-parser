"""Statement-parser registry construction for the PROCEDURE DIVISION.

Collaborator module of
:class:`~cobolparser.parsers.divisions.procedure.ProcedureDivisionParser`:
builds the :class:`~cobolparser.core.registry.StatementParserRegistry` with
every available statement parser in priority order (first-match strategy).

To add a new statement parser, register it in
:func:`create_statement_registry` below (order matters — more specific
parsers must come before general ones).
"""

from cobolparser.core.registry import StatementParserRegistry
from cobolparser.parsers.statements import (
    AcceptStatementParser,
    AddStatementParser,
    AlterStatementParser,
    CallStatementParser,
    CancelStatementParser,
    CloseStatementParser,
    CommitStatementParser,
    ComputeStatementParser,
    ContinueStatementParser,
    DeleteStatementParser,
    DisplayStatementParser,
    DivideStatementParser,
    EntryStatementParser,
    EvaluateStatementParser,
    ExecCicsStatementParser,
    ExecImsStatementParser,
    ExecSqlStatementParser,
    ExitStatementParser,
    GenerateStatementParser,
    GobackStatementParser,
    GoStatementParser,
    IfStatementParser,
    InitializeStatementParser,
    InspectStatementParser,
    MergeStatementParser,
    MoveStatementParser,
    MultiplyStatementParser,
    OpenStatementParser,
    PerformStatementParser,
    ReadStatementParser,
    ReleaseStatementParser,
    ReturnStatementParser,
    RewriteStatementParser,
    RollbackStatementParser,
    SearchStatementParser,
    SetStatementParser,
    SortStatementParser,
    StartStatementParser,
    StringStatementParser,
    SubtractStatementParser,
    UnlockStatementParser,
    UnstringStatementParser,
    UseStatementParser,
    XmlJsonStatementParser,
)
from cobolparser.parsers.statements.stop_parser import StopStatementParser
from cobolparser.parsers.statements.write_parser import WriteStatementParser


def create_statement_registry() -> StatementParserRegistry:
    """Create and populate statement registry with all available parsers.

    Registers statement parsers in priority order (first-match strategy).
    Order matters - more specific parsers should come before general ones.

    IBM Enterprise COBOL extensions (EXEC SQL, EXEC CICS) are registered first
    since they require multi-token lookahead matching.

    Returns:
        StatementParserRegistry with all statement parsers registered
    """
    registry = StatementParserRegistry()

    # IBM Enterprise COBOL extensions first - more specific matching
    registry.register(ExecSqlStatementParser())
    registry.register(ExecCicsStatementParser())
    registry.register(ExecImsStatementParser())
    registry.register(XmlJsonStatementParser())

    # Core control flow statements - more specific first
    registry.register(IfStatementParser())
    registry.register(PerformStatementParser())
    registry.register(EvaluateStatementParser())

    # Statement types
    registry.register(DisplayStatementParser())
    registry.register(MoveStatementParser())
    registry.register(CallStatementParser())
    registry.register(StopStatementParser())
    registry.register(EntryStatementParser())
    registry.register(GoStatementParser())
    registry.register(ExitStatementParser())
    registry.register(ContinueStatementParser())
    registry.register(GobackStatementParser())

    # IO statements
    registry.register(AcceptStatementParser())
    registry.register(ReadStatementParser())
    registry.register(OpenStatementParser())
    registry.register(CloseStatementParser())
    registry.register(RewriteStatementParser())
    registry.register(DeleteStatementParser())
    registry.register(StartStatementParser())
    registry.register(WriteStatementParser())
    registry.register(UnlockStatementParser())

    # Data manipulation
    registry.register(InitializeStatementParser())
    registry.register(SetStatementParser())
    registry.register(StringStatementParser())
    registry.register(UnstringStatementParser())
    registry.register(InspectStatementParser())

    # Search
    registry.register(SearchStatementParser())

    # Sort/Merge family
    registry.register(SortStatementParser())
    registry.register(MergeStatementParser())
    registry.register(ReleaseStatementParser())
    registry.register(ReturnStatementParser())

    # Arithmetic statements
    registry.register(ComputeStatementParser())
    registry.register(AddStatementParser())
    registry.register(SubtractStatementParser())
    registry.register(MultiplyStatementParser())
    registry.register(DivideStatementParser())

    # Minimal/rare verbs
    registry.register(AlterStatementParser())
    registry.register(CancelStatementParser())
    registry.register(GenerateStatementParser())
    registry.register(UseStatementParser())

    # Transaction control
    registry.register(CommitStatementParser())
    registry.register(RollbackStatementParser())

    return registry
