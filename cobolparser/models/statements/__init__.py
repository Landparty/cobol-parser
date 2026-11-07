"""
COBOL statement and expression AST nodes.

This package implements AST nodes for COBOL statements, expressions,
and control flow constructs with full functionality.

Family modules:
    base        — CobolStatement, CobolExpression, and expression subclasses;
                  the nested-body attribute lists and walk_statements()
    arithmetic  — ArithmeticStatement, AddStatement, SubtractStatement,
                  MultiplyStatement, DivideStatement, ComputeStatement
    control     — IfStatement, EvaluateStatement, WhenClause, PerformStatement,
                  GoStatement, StopStatement, SearchStatement
    data        — MoveStatement, DisplayStatement, StringStatement, UnstringStatement
    io          — IO* statement classes (IOReadStatement, IOWriteStatement, etc.)
    call        — CallStatement, EntryStatement, CallParameter
    misc        — SelectStatement, CopyStatement, InvokeStatement,
                  AllocateStatement, FreeStatement
"""

from .arithmetic import (
    AddStatement,
    ArithmeticStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from .base import (
    BRANCH_BODY_ATTRS,
    HANDLER_CLAUSE_ATTRS,
    HANDLER_CLAUSE_PAIRS,
    HANDLER_CLAUSE_PHRASES,
    LOOP_BODY_ATTRS,
    NESTED_BODY_ATTRS,
    STATEMENT_LIST_ATTRS,
    WHEN_ARM_ATTRS,
    ArithmeticExpression,
    ClauseBody,
    CobolExpression,
    CobolStatement,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
    iter_clause_bodies,
    walk_statements,
)
from .call import (
    CallParameter,
    CallStatement,
    EntryStatement,
)
from .communication import (
    DisableStatement,
    EnableStatement,
    PurgeStatement,
    ReceiveStatement,
    SendStatement,
)
from .control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    RaiseStatement,
    ResumeStatement,
    SearchStatement,
    StopStatement,
    WhenClause,
)
from .data import (
    DisplayStatement,
    InitializeStatement,
    InspectStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
    ValidateStatement,
)
from .io import (
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)
from .legacy import (
    ChainStatement,
    EnterStatement,
    ExamineStatement,
    ExhibitStatement,
    NoteStatement,
    ServiceStatement,
    TitleStatement,
    TraceStatement,
    TransformStatement,
)
from .misc import (
    AllocateStatement,
    AlterStatement,
    CancelStatement,
    CommitStatement,
    ContinueStatement,
    CopyStatement,
    EjectStatement,
    ExitStatement,
    FreeStatement,
    GenerateStatement,
    GobackStatement,
    InvokeStatement,
    MergeStatement,
    NextSentenceStatement,
    ReleaseStatement,
    ReturnStatement,
    RollbackStatement,
    SelectStatement,
    SkipStatement,
    SortStatement,
    UseStatement,
    XmlJsonStatement,
)
from .report_writer import (
    InitiateStatement,
    SuppressStatement,
    TerminateStatement,
)

# Module exports — preserved from original statements.py
__all__ = [
    "CobolStatement",
    "ClauseBody",
    "iter_clause_bodies",
    "walk_statements",
    "BRANCH_BODY_ATTRS",
    "LOOP_BODY_ATTRS",
    "HANDLER_CLAUSE_PAIRS",
    "HANDLER_CLAUSE_ATTRS",
    "HANDLER_CLAUSE_PHRASES",
    "WHEN_ARM_ATTRS",
    "STATEMENT_LIST_ATTRS",
    "NESTED_BODY_ATTRS",
    "MoveStatement",
    "DisplayStatement",
    "PerformStatement",
    "IfStatement",
    "CallStatement",
    "EntryStatement",
    "GoStatement",
    "ComputeStatement",
    "CopyStatement",
    "SelectStatement",
    # IO Statement Classes (Contract-based names)
    "IOReadStatement",
    "IOWriteStatement",
    "IOOpenStatement",
    "IOCloseStatement",
    "IOAcceptStatement",
    "IORewriteStatement",
    "IODeleteStatement",
    "IOStartStatement",
    "IOUnlockStatement",
    # New statement types
    "ContinueStatement",
    "NextSentenceStatement",
    "EjectStatement",
    "SkipStatement",
    "ExitStatement",
    "GobackStatement",
    "CancelStatement",
    "AlterStatement",
    "GenerateStatement",
    "ReleaseStatement",
    "ReturnStatement",
    "UseStatement",
    "CommitStatement",
    "RollbackStatement",
    "InitializeStatement",
    "SetStatement",
    "InspectStatement",
    "SortStatement",
    "XmlJsonStatement",
    "MergeStatement",
    "InvokeStatement",
    "AllocateStatement",
    "FreeStatement",
    # Report Writer
    "InitiateStatement",
    "TerminateStatement",
    "SuppressStatement",
    # Communication Module
    "SendStatement",
    "ReceiveStatement",
    "EnableStatement",
    "DisableStatement",
    "PurgeStatement",
    # Legacy / compiler-directing
    "ExhibitStatement",
    "ExamineStatement",
    "TransformStatement",
    "EnterStatement",
    "NoteStatement",
    "ChainStatement",
    "TraceStatement",
    "ServiceStatement",
    "TitleStatement",
    # COBOL 2002
    "RaiseStatement",
    "ResumeStatement",
    "ValidateStatement",
    # Other exports
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
]
