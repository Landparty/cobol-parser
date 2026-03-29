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
    io          — IO* classes and backward-compat aliases
    call        — CallStatement, EntryStatement, CallParameter
    misc        — SelectStatement, CopyStatement
"""

from .base import (
    CobolStatement,
    CobolExpression,
    ArithmeticExpression,
    ConditionalExpression,
    LogicalExpression,
    FunctionCall,
)

from .arithmetic import (
    ArithmeticStatement,
    AddStatement,
    SubtractStatement,
    MultiplyStatement,
    DivideStatement,
    ComputeStatement,
)

from .control import (
    WhenClause,
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    GoStatement,
    StopStatement,
    SearchStatement,
)

from .data import (
    MoveStatement,
    DisplayStatement,
    StringStatement,
    UnstringStatement,
)

from .io import (
    IOReadStatement,
    IOWriteStatement,
    IOOpenStatement,
    IOCloseStatement,
    IOAcceptStatement,
    IORewriteStatement,
    IODeleteStatement,
    IOStartStatement,
    IOUnlockStatement,
)

from .call import (
    CallParameter,
    CallStatement,
    EntryStatement,
)

from .misc import (
    SelectStatement,
    CopyStatement,
)

# Import the base classes for procedure elements
from ..program import CobolParagraph, CobolSection

# Aliases for procedure-specific elements
ProcedureParagraph = CobolParagraph
ProcedureSection = CobolSection

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
    # Other exports
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
    "ProcedureParagraph",
    "ProcedureSection",
]
