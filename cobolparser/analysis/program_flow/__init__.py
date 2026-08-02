"""
Program flow analysis for COBOL programs.

Analyzes the PROCEDURE DIVISION to build a control flow graph showing how
paragraphs and sections relate to each other through PERFORM, GO TO, CALL,
and other control flow statements. Provides a complete picture of program
execution flow including entry points, exit points, branching, and loops.

The implementation is split into focused collaborators:

- :mod:`.models` — report dataclasses (``FlowNode``, ``FlowEdge``, ...)
- :mod:`.scanner` — procedure collection and statement scanning
- :mod:`.edges` — edge construction and edge-type categories
- :mod:`.cycles` — cycle detection and classification
- :mod:`.graph` — fall-through, convergence, and reachability post-passes
- :mod:`.analyzer` — the :class:`ProgramFlowAnalyzer` orchestrator

The public API is unchanged: import everything from
``cobolparser.analysis.program_flow`` (or ``cobolparser`` /
``cobolparser.analysis``) as before.
"""

from .analyzer import ProgramFlowAnalyzer
from .models import (
    BranchArm,
    BranchNode,
    FlowEdge,
    FlowEdgeType,
    FlowNode,
    ProgramFlowReport,
)
from .scanner import _CLAUSE_BODY_ATTRS  # noqa: F401  (compat re-export)

__all__ = [
    "BranchArm",
    "BranchNode",
    "FlowEdge",
    "FlowEdgeType",
    "FlowNode",
    "ProgramFlowAnalyzer",
    "ProgramFlowReport",
]
