"""
COBOL statement and expression AST nodes.

This package implements AST nodes for COBOL statements, expressions,
and control flow constructs with full functionality.

Family modules:
    base        — CobolStatement, CobolExpression, and expression subclasses
    arithmetic  — ArithmeticStatement, AddStatement, SubtractStatement,
                  MultiplyStatement, DivideStatement, ComputeStatement
    control     — IfStatement, EvaluateStatement, WhenClause, PerformStatement,
                  GoStatement, StopStatement, SearchStatement
    data        — MoveStatement, DisplayStatement, StringStatement, UnstringStatement
    io          — IO* statement classes (IOReadStatement, IOWriteStatement, etc.)
    call        — CallStatement, EntryStatement, CallParameter
    misc        — SelectStatement, CopyStatement
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
    ArithmeticExpression,
    CobolExpression,
    CobolStatement,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)
from .call import (
    CallParameter,
    CallStatement,
    EntryStatement,
)
from .control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
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
from .misc import (
    AlterStatement,
    CancelStatement,
    CommitStatement,
    ContinueStatement,
    CopyStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    RollbackStatement,
    SelectStatement,
    SortStatement,
    UseStatement,
    XmlJsonStatement,
)

# Module exports — preserved from original statements.py
__all__ = [
    "CobolStatement",
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
    # Other exports
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
]
