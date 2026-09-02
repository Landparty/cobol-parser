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
    AllocateStatementParser,
    AlterStatementParser,
    CallStatementParser,
    CancelStatementParser,
    ChainStatementParser,
    CloseStatementParser,
    CommitStatementParser,
    ComputeStatementParser,
    ContinueStatementParser,
    DeleteStatementParser,
    DisableStatementParser,
    DisplayStatementParser,
    DivideStatementParser,
    EjectStatementParser,
    EnableStatementParser,
    EnterStatementParser,
    EntryStatementParser,
    EvaluateStatementParser,
    ExamineStatementParser,
    ExecCicsStatementParser,
    ExecImsStatementParser,
    ExecSqlStatementParser,
    ExhibitStatementParser,
    ExitStatementParser,
    FreeStatementParser,
    GenerateStatementParser,
    GobackStatementParser,
    GoStatementParser,
    IfStatementParser,
    InitializeStatementParser,
    InitiateStatementParser,
    InspectStatementParser,
    InvokeStatementParser,
    MergeStatementParser,
    MoveStatementParser,
    MultiplyStatementParser,
    NextSentenceStatementParser,
    NoteStatementParser,
    OpenStatementParser,
    PerformStatementParser,
    PurgeStatementParser,
    RaiseStatementParser,
    ReadStatementParser,
    ReceiveStatementParser,
    ReleaseStatementParser,
    ResumeStatementParser,
    ReturnStatementParser,
    RewriteStatementParser,
    RollbackStatementParser,
    SearchStatementParser,
    SendStatementParser,
    ServiceStatementParser,
    SetStatementParser,
    SkipStatementParser,
    SortStatementParser,
    StartStatementParser,
    StringStatementParser,
    SubtractStatementParser,
    SuppressStatementParser,
    TerminateStatementParser,
    TitleStatementParser,
    TraceStatementParser,
    TransformStatementParser,
    UnlockStatementParser,
    UnstringStatementParser,
    UseStatementParser,
    ValidateStatementParser,
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
    registry.register(InvokeStatementParser())
    registry.register(GoStatementParser())
    registry.register(ExitStatementParser())
    registry.register(ContinueStatementParser())
    registry.register(NextSentenceStatementParser())
    registry.register(EjectStatementParser())
    registry.register(SkipStatementParser())
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
    registry.register(AllocateStatementParser())
    registry.register(FreeStatementParser())

    # Transaction control
    registry.register(CommitStatementParser())
    registry.register(RollbackStatementParser())

    # Report Writer control verbs (GENERATE is registered above)
    registry.register(InitiateStatementParser())
    registry.register(TerminateStatementParser())
    registry.register(SuppressStatementParser())

    # COBOL-85 Communication Module
    registry.register(SendStatementParser())
    registry.register(ReceiveStatementParser())
    registry.register(EnableStatementParser())
    registry.register(DisableStatementParser())
    registry.register(PurgeStatementParser())

    # OS/VS legacy verbs, IBM compiler-directing / debugging statements,
    # COBOL-74 NOTE, Micro Focus CHAIN. TRACE/SERVICE/TITLE match on a
    # two-word lookahead (READY TRACE, SERVICE LABEL, TITLE "...").
    registry.register(ExhibitStatementParser())
    registry.register(ExamineStatementParser())
    registry.register(TransformStatementParser())
    registry.register(EnterStatementParser())
    registry.register(NoteStatementParser())
    registry.register(ChainStatementParser())
    registry.register(TraceStatementParser())
    registry.register(ServiceStatementParser())
    registry.register(TitleStatementParser())

    # COBOL 2002 exception handling / validation
    registry.register(RaiseStatementParser())
    registry.register(ResumeStatementParser())
    registry.register(ValidateStatementParser())

    return registry
