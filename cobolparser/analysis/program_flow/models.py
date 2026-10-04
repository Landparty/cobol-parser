"""Data model for program flow analysis reports.

Defines the node/edge/branch dataclasses and the top-level
:class:`ProgramFlowReport` produced by
:class:`~cobolparser.analysis.program_flow.ProgramFlowAnalyzer`. All classes
serialize via ``to_dict()`` with a stable shape consumed by the flowchart
generators and the backend adapter.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ...models.ast_base import SourceLocation


class FlowEdgeType(Enum):
    """Types of control flow edges between procedures."""

    PERFORM = "PERFORM"
    PERFORM_THRU = "PERFORM_THRU"
    GOTO = "GOTO"
    GOTO_DEPENDING = "GOTO_DEPENDING"
    CALL = "CALL"
    CALL_DYNAMIC = "CALL_DYNAMIC"
    SORT_INPUT_PROCEDURE = "SORT_INPUT_PROCEDURE"
    SORT_INPUT_PROCEDURE_THRU = "SORT_INPUT_PROCEDURE_THRU"
    SORT_OUTPUT_PROCEDURE = "SORT_OUTPUT_PROCEDURE"
    SORT_OUTPUT_PROCEDURE_THRU = "SORT_OUTPUT_PROCEDURE_THRU"
    MERGE_OUTPUT_PROCEDURE = "MERGE_OUTPUT_PROCEDURE"
    MERGE_OUTPUT_PROCEDURE_THRU = "MERGE_OUTPUT_PROCEDURE_THRU"
    # XML PARSE ... PROCESSING PROCEDURE p [THRU q]: the parser PERFORMs the
    # handler once per XML event.
    XML_PROCESSING_PROCEDURE = "XML_PROCESSING_PROCEDURE"
    XML_PROCESSING_PROCEDURE_THRU = "XML_PROCESSING_PROCEDURE_THRU"
    # EXEC CICS HANDLE AID/CONDITION/ABEND option(paragraph): CICS branches
    # there (a GO TO the runtime performs) when the AID/condition occurs.
    CICS_HANDLE = "CICS_HANDLE"
    ALTER = "ALTER"
    FALL_THROUGH = "FALL_THROUGH"
    IF_BRANCH = "IF_BRANCH"
    IF_THEN = "IF_THEN"
    IF_ELSE = "IF_ELSE"
    EVALUATE_BRANCH = "EVALUATE_BRANCH"
    EVALUATE_WHEN = "EVALUATE_WHEN"
    EVALUATE_WHEN_OTHER = "EVALUATE_WHEN_OTHER"


@dataclass
class FlowNode:
    """A paragraph or section in the program flow graph.

    ``name`` is the bare procedure name. When two paragraphs share a name
    (legal COBOL when they sit in different sections), each also carries a
    ``qualified_name`` (``"X1 OF S2"``), and that is the string every edge,
    entry/exit point, cycle and ``unreachable_nodes`` entry uses for it:
    :attr:`key` is the one to match those against.
    """

    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    location: SourceLocation
    is_entry_point: bool = False
    is_exit_point: bool = False
    #: A DECLARATIVES (USE procedure) section or one of its paragraphs:
    #: invoked by the runtime, never by the program's own control flow.
    is_declarative: bool = False
    statement_count: int = 0
    has_stop_run: bool = False
    has_goback: bool = False
    has_exit_program: bool = False
    has_return: bool = False
    has_exit_section: bool = False
    has_exit_paragraph: bool = False
    has_exit_perform: bool = False
    exit_statement_kind: str | None = None
    exit_statement_location: SourceLocation | None = None
    if_count: int = 0
    evaluate_count: int = 0
    search_count: int = 0
    perform_count: int = 0
    goto_count: int = 0
    call_count: int = 0
    statement_types: dict[str, int] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    qualified_name: str | None = None

    @property
    def key(self) -> str:
        """The node's identity in the graph: ``qualified_name`` when the
        bare name is shared, else ``name``."""
        return self.qualified_name or self.name

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.procedure_type,
            "location": self.location.to_dict(),
        }
        if self.qualified_name:
            result["qualified_name"] = self.qualified_name
        if self.is_entry_point:
            result["is_entry_point"] = True
        if self.is_exit_point:
            result["is_exit_point"] = True
        if self.is_declarative:
            result["is_declarative"] = True
        result["statement_count"] = self.statement_count
        if self.has_stop_run:
            result["has_stop_run"] = True
        if self.has_goback:
            result["has_goback"] = True
        if self.has_exit_program:
            result["has_exit_program"] = True
        if self.has_return:
            result["has_return"] = True
        if self.has_exit_section:
            result["has_exit_section"] = True
        if self.has_exit_paragraph:
            result["has_exit_paragraph"] = True
        if self.has_exit_perform:
            result["has_exit_perform"] = True
        if self.exit_statement_kind and self.exit_statement_location:
            result["exit_statement_kind"] = self.exit_statement_kind
            result["exit_statement_location"] = self.exit_statement_location.to_dict()
        result["branching"] = {
            "if_count": self.if_count,
            "evaluate_count": self.evaluate_count,
            "search_count": self.search_count,
        }
        result["calls"] = {
            "perform_count": self.perform_count,
            "goto_count": self.goto_count,
            "call_count": self.call_count,
        }
        result["statement_types"] = self.statement_types
        result["decisions"] = self.decisions
        return result


@dataclass
class FlowEdge:
    """A control flow edge between two procedures or to an external program."""

    source: str
    target: str
    edge_type: FlowEdgeType
    location: SourceLocation
    condition: str | None = None
    is_loop: bool = False
    perform_type: str | None = None  # SIMPLE, TIMES, UNTIL, VARYING
    # For THRU ranges (PERFORM/SORT/MERGE ... THRU): the closing paragraph of
    # the range and the ordered list of every paragraph the range spans
    # (inclusive of both endpoints). ``range_members`` makes the implicit
    # paragraphs between the two endpoints explicit so consumers see the range
    # as a single unit rather than two disconnected edges.
    thru_target: str | None = None
    range_members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "type": self.edge_type.value,
            "location": self.location.to_dict(),
        }
        if self.condition:
            result["condition"] = self.condition
        if self.is_loop:
            result["is_loop"] = True
        if self.perform_type:
            result["perform_type"] = self.perform_type
        if self.thru_target:
            result["thru_target"] = self.thru_target
        if self.range_members:
            result["range_members"] = self.range_members
        return result


@dataclass
class BranchArm:
    """One arm of a branch node (THEN/ELSE/WHEN/WHEN OTHER)."""

    arm_id: str
    arm_type: str  # "THEN", "ELSE", "WHEN", "WHEN_OTHER"
    label: str
    statement_count: int
    nested_call_targets: list[str] = field(default_factory=list)
    # Compact one-line summary of the arm's first statement (see
    # analysis/program_flow/statement_text.py); None when the arm is empty.
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "arm_id": self.arm_id,
            "arm_type": self.arm_type,
            "label": self.label,
            "statement_count": self.statement_count,
            "nested_call_targets": self.nested_call_targets,
        }
        if self.summary is not None:
            result["summary"] = self.summary
        return result


@dataclass
class BranchNode:
    """A decision node (IF or EVALUATE) in the flow graph."""

    node_id: str
    branch_type: str  # "IF" or "EVALUATE"
    parent_proc: str
    location: SourceLocation
    condition_text: str
    arms: list[BranchArm] = field(default_factory=list)
    convergence_node: str | None = None  # paragraph where all arms rejoin

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_id": self.node_id,
            "branch_type": self.branch_type,
            "parent_proc": self.parent_proc,
            "location": self.location.to_dict(),
            "condition_text": self.condition_text,
            "arms": [a.to_dict() for a in self.arms],
        }
        if self.convergence_node is not None:
            result["convergence_node"] = self.convergence_node
        return result


@dataclass
class ProgramFlowReport:
    """Complete program flow analysis report."""

    program_name: str = ""
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    exit_points: list[str] = field(default_factory=list)
    external_calls: list[dict[str, Any]] = field(default_factory=list)
    program_cancellations: list[dict[str, Any]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    cycle_details: list[dict[str, Any]] = field(default_factory=list)
    unreachable_nodes: list[str] = field(default_factory=list)
    branch_nodes: list["BranchNode"] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "entry_points": self.entry_points,
            "exit_points": self.exit_points,
            "external_calls": self.external_calls,
            "program_cancellations": self.program_cancellations,
            "cycles": self.cycles,
            "cycle_details": self.cycle_details,
            "unreachable_nodes": self.unreachable_nodes,
            "branch_nodes": [b.to_dict() for b in self.branch_nodes],
            "summary": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "entry_point_count": len(self.entry_points),
                "exit_point_count": len(self.exit_points),
                "external_call_count": len(self.external_calls),
                "cancellation_count": len(self.program_cancellations),
                "cycle_count": len(self.cycles),
                "recursion_cycle_count": sum(
                    1
                    for c in self.cycle_details
                    if c.get("kind") == "PERFORM_RECURSION"
                ),
                "unreachable_node_count": len(self.unreachable_nodes),
            },
        }
