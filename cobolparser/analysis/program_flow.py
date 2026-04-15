"""
Program flow analysis for COBOL programs.

Analyzes the PROCEDURE DIVISION to build a control flow graph showing how
paragraphs and sections relate to each other through PERFORM, GO TO, CALL,
and other control flow statements. Provides a complete picture of program
execution flow including entry points, exit points, branching, and loops.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
)
from ..models.statements.call import CallStatement, EntryStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.misc import (
    AlterStatement,
    CancelStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    ReturnStatement,
    SortStatement,
)


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
    ALTER = "ALTER"
    FALL_THROUGH = "FALL_THROUGH"


@dataclass
class FlowNode:
    """A paragraph or section in the program flow graph."""

    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    location: SourceLocation
    is_entry_point: bool = False
    is_exit_point: bool = False
    statement_count: int = 0
    has_stop_run: bool = False
    has_goback: bool = False
    has_exit_program: bool = False
    has_return: bool = False
    has_exit_section: bool = False
    has_exit_paragraph: bool = False
    has_exit_perform: bool = False
    if_count: int = 0
    evaluate_count: int = 0
    search_count: int = 0
    perform_count: int = 0
    goto_count: int = 0
    call_count: int = 0
    statement_types: dict[str, int] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.procedure_type,
            "location": self.location.to_dict(),
        }
        if self.is_entry_point:
            result["is_entry_point"] = True
        if self.is_exit_point:
            result["is_exit_point"] = True
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
    unreachable_nodes: list[str] = field(default_factory=list)

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
            "unreachable_nodes": self.unreachable_nodes,
            "summary": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "entry_point_count": len(self.entry_points),
                "exit_point_count": len(self.exit_points),
                "external_call_count": len(self.external_calls),
                "cancellation_count": len(self.program_cancellations),
                "cycle_count": len(self.cycles),
                "unreachable_node_count": len(self.unreachable_nodes),
            },
        }


class ProgramFlowAnalyzer:
    """Analyzer that builds a control flow graph of a COBOL program.

    Walks the AST to extract the program's execution flow, identifying:
    - Paragraph and section nodes with statement metrics
    - Control flow edges (PERFORM, GO TO, CALL, SORT/MERGE procedures, ALTER)
    - Entry points (first procedure + ENTRY statements)
    - Exit points (STOP RUN, GOBACK, EXIT PROGRAM)
    - External program calls (static and dynamic)
    - Fall-through edges between sequential paragraphs

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer

        result = parse_cobol(source)
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        for node in report.nodes:
            print(f"{node.procedure_type} {node.name} ({node.statement_count} stmts)")
        for edge in report.edges:
            print(f"  {edge.source} -> {edge.target} [{edge.edge_type.value}]")
        ```
    """

    # Edge types that represent internal flow within the program (not external calls).
    _INTERNAL_EDGE_TYPES: frozenset[FlowEdgeType] = frozenset(
        {
            FlowEdgeType.PERFORM,
            FlowEdgeType.PERFORM_THRU,
            FlowEdgeType.GOTO,
            FlowEdgeType.GOTO_DEPENDING,
            FlowEdgeType.FALL_THROUGH,
            FlowEdgeType.SORT_INPUT_PROCEDURE,
            FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
            FlowEdgeType.SORT_OUTPUT_PROCEDURE,
            FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
            FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
            FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
            FlowEdgeType.ALTER,
        }
    )

    def __init__(self) -> None:
        self._nodes: dict[str, FlowNode] = {}
        self._edges: list[FlowEdge] = []
        self._ordered_procedures: list[str] = []
        self._entry_points: list[str] = []
        self._exit_points: set[str] = set()
        self._external_calls: list[dict[str, Any]] = []
        self._program_cancellations: list[dict[str, Any]] = []
        self._cycles: list[list[str]] = []
        self._unreachable_nodes: list[str] = []
        # Current procedure context for statement scanning
        self._current_procedure: str | None = None

    def analyze(self, ast: CobolProgram) -> ProgramFlowReport:
        """Analyze a COBOL program and build its control flow graph.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            A ProgramFlowReport with the complete flow graph.
        """
        self._nodes = {}
        self._edges = []
        self._ordered_procedures = []
        self._entry_points = []
        self._exit_points = set()
        self._external_calls = []
        self._program_cancellations = []
        self._cycles = []
        self._unreachable_nodes = []
        self._current_procedure = None

        proc_division = ast.procedure_division
        if proc_division is None:
            return ProgramFlowReport(program_name=ast.program_name)

        # Pass 1: Collect all procedures as nodes
        self._collect_procedures(proc_division)

        # Pass 2: Scan statements to build edges and node metrics
        self._scan_statements(proc_division)

        # Pass 3: Collect ENTRY statements for alternate entry points
        self._collect_entry_points(ast)

        # Pass 4: Determine fall-through edges
        self._build_fall_through_edges()

        # Mark the first procedure as entry point before cycle/reachability analysis
        # so that the entry point set is complete when those passes run.
        if self._ordered_procedures:
            first = self._ordered_procedures[0]
            if first in self._nodes:
                self._nodes[first].is_entry_point = True
                if first not in self._entry_points:
                    self._entry_points.insert(0, first)

        # Pass 5: Detect cycles in internal flow graph
        self._detect_cycles()

        # Pass 6: Detect nodes unreachable from any entry point
        self._detect_unreachable_nodes()

        # Mark exit points on nodes
        for name in self._exit_points:
            if name in self._nodes:
                self._nodes[name].is_exit_point = True

        # Build report
        report = ProgramFlowReport(program_name=ast.program_name)
        report.nodes = [self._nodes[name] for name in self._ordered_procedures]
        report.edges = self._edges
        report.entry_points = self._entry_points
        report.exit_points = sorted(self._exit_points)
        report.external_calls = self._external_calls
        report.program_cancellations = self._program_cancellations
        report.cycles = self._cycles
        report.unreachable_nodes = self._unreachable_nodes
        return report

    def _collect_procedures(self, proc_division: CobolDivision) -> None:
        """Collect all paragraphs and sections as flow nodes."""
        # Collect sections and their paragraphs
        for section in proc_division._sections.values():
            name = section.section_name
            if name:
                upper_name = name.upper()
                self._nodes[upper_name] = FlowNode(
                    name=upper_name,
                    procedure_type="SECTION",
                    location=section.location,
                )
                self._ordered_procedures.append(upper_name)

            for para in section.paragraphs:
                pname = para.paragraph_name
                if pname and self._is_valid_procedure_name(pname):
                    upper_pname = pname.upper()
                    self._nodes[upper_pname] = FlowNode(
                        name=upper_pname,
                        procedure_type="PARAGRAPH",
                        location=para.location,
                    )
                    self._ordered_procedures.append(upper_pname)

        # Collect top-level paragraphs
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if pname and self._is_valid_procedure_name(pname):
                upper_pname = pname.upper()
                if upper_pname not in self._nodes:
                    self._nodes[upper_pname] = FlowNode(
                        name=upper_pname,
                        procedure_type="PARAGRAPH",
                        location=para.location,
                    )
                    self._ordered_procedures.append(upper_pname)

    def _scan_statements(self, proc_division: CobolDivision) -> None:
        """Scan all statements to build edges and compute node metrics."""
        # Scan sections
        for section in proc_division._sections.values():
            sec_name = section.section_name
            for para in section.paragraphs:
                pname = para.paragraph_name
                if pname and self._is_valid_procedure_name(pname):
                    self._current_procedure = pname.upper()
                    self._scan_paragraph_statements(para)

            # If section has no paragraphs, scan section-level
            if not section.paragraphs and sec_name:
                self._current_procedure = sec_name.upper()

        # Scan top-level paragraphs
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if pname and self._is_valid_procedure_name(pname):
                self._current_procedure = pname.upper()
                self._scan_paragraph_statements(para)

    def _scan_paragraph_statements(self, para: CobolParagraph) -> None:
        """Scan all statements within a paragraph, including nested ones."""
        proc_name = self._current_procedure
        if not proc_name or proc_name not in self._nodes:
            return

        node = self._nodes[proc_name]
        visited: set[int] = set()

        def _record_type(stmt: Any) -> None:
            stype = getattr(stmt, "statement_type", None)
            if stype:
                node.statement_types[stype] = node.statement_types.get(stype, 0) + 1

        def scan(stmt: Any) -> None:
            if not hasattr(stmt, "node_type"):
                return
            if id(stmt) in visited:
                return
            visited.add(id(stmt))

            node.statement_count += 1
            _record_type(stmt)

            if isinstance(stmt, PerformStatement):
                node.perform_count += 1
                self._process_perform(stmt, proc_name)
                # Recurse into inline PERFORM blocks
                for s in stmt.inline_statements:
                    scan(s)
            elif isinstance(stmt, GoStatement):
                node.goto_count += 1
                self._process_goto(stmt, proc_name)
            elif isinstance(stmt, CallStatement):
                node.call_count += 1
                self._process_call(stmt, proc_name)
                # Scan exception handler branches for nested flow
                for s in stmt.on_overflow or []:
                    scan(s)
                for s in stmt.on_exception or []:
                    scan(s)
                for s in stmt.not_on_exception or []:
                    scan(s)
            elif isinstance(stmt, IfStatement):
                node.if_count += 1
                decision: dict[str, Any] = {
                    "type": "IF",
                    "location": stmt.location.to_dict(),
                    "has_else": len(stmt.else_statements) > 0,
                }
                if stmt.condition:
                    cond_dict = stmt.condition.to_dict()
                    decision["condition"] = cond_dict.get(
                        "expression_type", str(cond_dict)
                    )
                node.decisions.append(decision)
                for s in stmt.then_statements:
                    scan(s)
                for s in stmt.else_statements:
                    scan(s)
            elif isinstance(stmt, EvaluateStatement):
                node.evaluate_count += 1
                subjects: list[Any] = []
                for subj in stmt.subjects:
                    if hasattr(subj, "to_dict"):
                        subjects.append(subj.to_dict())
                    else:
                        subjects.append(subj)
                decision = {
                    "type": "EVALUATE",
                    "location": stmt.location.to_dict(),
                    "subjects": subjects,
                    "when_count": len(stmt.when_clauses),
                    "has_default": stmt.default_when is not None,
                }
                node.decisions.append(decision)
                for wc in stmt.when_clauses:
                    for s in wc.statements:
                        scan(s)
                if stmt.default_when:
                    for s in stmt.default_when.statements:
                        scan(s)
            elif isinstance(stmt, SearchStatement):
                node.search_count += 1
                decision = {
                    "type": "SEARCH",
                    "location": stmt.location.to_dict(),
                    "table_name": stmt.table_name,
                    "when_count": len(stmt.when_clauses),
                    "has_at_end": stmt.at_end_clause is not None,
                }
                node.decisions.append(decision)
                for wc_dict in stmt.when_clauses:
                    for s in wc_dict.get("statements", []):
                        scan(s)
                if stmt.at_end_clause:
                    for s in stmt.at_end_clause:
                        scan(s)
            elif isinstance(stmt, SortStatement):
                self._process_sort(stmt, proc_name)
            elif isinstance(stmt, MergeStatement):
                self._process_merge(stmt, proc_name)
            elif isinstance(stmt, AlterStatement):
                self._process_alter(stmt, proc_name)
            elif isinstance(stmt, CancelStatement):
                self._process_cancel(stmt, proc_name)
            elif isinstance(stmt, ReturnStatement):
                node.has_return = True
                # Scan AT END / NOT AT END branches for nested flow
                for s in stmt.at_end_clause or []:
                    scan(s)
                for s in stmt.not_at_end_clause or []:
                    scan(s)
            elif isinstance(stmt, StopStatement):
                node.has_stop_run = True
                self._exit_points.add(proc_name)
            elif isinstance(stmt, GobackStatement):
                node.has_goback = True
                self._exit_points.add(proc_name)
            elif isinstance(stmt, ExitStatement):
                exit_type = stmt.exit_type or ""
                if exit_type == "PROGRAM":
                    node.has_exit_program = True
                    self._exit_points.add(proc_name)
                elif exit_type == "SECTION":
                    node.has_exit_section = True
                elif exit_type == "PARAGRAPH":
                    node.has_exit_paragraph = True
                elif exit_type == "PERFORM":
                    node.has_exit_perform = True

        for stmt in para.statements:
            scan(stmt)

    def _process_perform(self, stmt: PerformStatement, source: str) -> None:
        """Create edges for a PERFORM statement."""
        if stmt.target_paragraph:
            target = stmt.target_paragraph.upper()
            is_loop = stmt.perform_type in ("TIMES", "UNTIL", "VARYING")

            condition = None
            if stmt.until_condition:
                cond_dict = stmt.until_condition.to_dict()
                condition = cond_dict.get("expression_type", str(cond_dict))

            self._edges.append(
                FlowEdge(
                    source=source,
                    target=target,
                    edge_type=FlowEdgeType.PERFORM,
                    location=stmt.location,
                    is_loop=is_loop,
                    perform_type=stmt.perform_type,
                    condition=condition if is_loop else None,
                )
            )

            if stmt.thru_paragraph:
                thru_target = stmt.thru_paragraph.upper()
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=thru_target,
                        edge_type=FlowEdgeType.PERFORM_THRU,
                        location=stmt.location,
                        is_loop=is_loop,
                        perform_type=stmt.perform_type,
                    )
                )

    def _process_goto(self, stmt: GoStatement, source: str) -> None:
        """Create edges for a GO TO statement."""
        if stmt.depending_on_variable:
            # Computed GO TO: multiple targets
            for operand in stmt.operands:
                if operand != stmt.depending_on_variable:
                    self._edges.append(
                        FlowEdge(
                            source=source,
                            target=operand.upper(),
                            edge_type=FlowEdgeType.GOTO_DEPENDING,
                            location=stmt.location,
                            condition=f"DEPENDING ON {stmt.depending_on_variable}",
                        )
                    )
        elif stmt.target_paragraph:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.target_paragraph.upper(),
                    edge_type=FlowEdgeType.GOTO,
                    location=stmt.location,
                )
            )

    def _process_call(self, stmt: CallStatement, source: str) -> None:
        """Create edges for a CALL statement and record external calls."""
        if stmt.called_program:
            program_name = stmt.called_program.strip("'\"")
            if not program_name:
                return
            edge_type = (
                FlowEdgeType.CALL_DYNAMIC if stmt.is_dynamic else FlowEdgeType.CALL
            )
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=program_name.upper(),
                    edge_type=edge_type,
                    location=stmt.location,
                )
            )

            call_info: dict[str, Any] = {
                "program": program_name,
                "is_dynamic": stmt.is_dynamic,
                "called_from": source,
                "location": stmt.location.to_dict(),
            }
            if stmt.is_dynamic and stmt.possible_values:
                call_info["possible_values"] = stmt.possible_values
            self._external_calls.append(call_info)

    def _process_sort(self, stmt: SortStatement, source: str) -> None:
        """Create edges for SORT INPUT/OUTPUT PROCEDURE references."""
        if stmt.input_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.input_procedure.upper(),
                    edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.input_procedure_thru:
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=stmt.input_procedure_thru.upper(),
                        edge_type=FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
                        location=stmt.location,
                    )
                )
        if stmt.output_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.output_procedure.upper(),
                    edge_type=FlowEdgeType.SORT_OUTPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.output_procedure_thru:
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=stmt.output_procedure_thru.upper(),
                        edge_type=FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
                        location=stmt.location,
                    )
                )

    def _process_merge(self, stmt: MergeStatement, source: str) -> None:
        """Create edges for MERGE OUTPUT PROCEDURE references."""
        if stmt.output_procedure:
            self._edges.append(
                FlowEdge(
                    source=source,
                    target=stmt.output_procedure.upper(),
                    edge_type=FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
                    location=stmt.location,
                )
            )
            if stmt.output_procedure_thru:
                self._edges.append(
                    FlowEdge(
                        source=source,
                        target=stmt.output_procedure_thru.upper(),
                        edge_type=FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
                        location=stmt.location,
                    )
                )

    def _process_cancel(self, stmt: CancelStatement, source: str) -> None:
        """Record CANCEL statements as program cancellation events."""
        for name in stmt.program_names:
            program_name = name.strip("'\"")
            if program_name:
                self._program_cancellations.append(
                    {
                        "program": program_name,
                        "cancelled_from": source,
                        "location": stmt.location.to_dict(),
                    }
                )

    def _process_alter(self, stmt: AlterStatement, source: str) -> None:
        """Create edges for ALTER statement procedure redirections."""
        for alteration in stmt.alterations:
            self._edges.append(
                FlowEdge(
                    source=alteration["from_paragraph"].upper(),
                    target=alteration["to_paragraph"].upper(),
                    edge_type=FlowEdgeType.ALTER,
                    location=stmt.location,
                )
            )

    def _collect_entry_points(self, ast: CobolProgram) -> None:
        """Collect ENTRY statements as alternate entry points."""
        all_statements = ast.get_all_statements()
        for stmt in all_statements:
            if isinstance(stmt, EntryStatement) and stmt.entry_name:
                entry_name = stmt.entry_name.strip("'\"").strip().upper()
                if entry_name and entry_name not in self._entry_points:
                    self._entry_points.append(entry_name)

    def _detect_cycles(self) -> None:
        """Detect cycles in the internal control flow graph using DFS.

        A cycle exists when procedure A (directly or transitively) transfers
        control back to itself via PERFORM, GO TO, or fall-through edges.
        Each reported cycle is the list of node names that form the loop.
        """
        adj: dict[str, list[str]] = {name: [] for name in self._nodes}
        for edge in self._edges:
            if (
                edge.edge_type in self._INTERNAL_EDGE_TYPES
                and edge.source in adj
                and edge.target in self._nodes
            ):
                adj[edge.source].append(edge.target)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(self._nodes, WHITE)
        path: list[str] = []
        seen_keys: set[frozenset[str]] = set()

        def dfs(node: str) -> None:
            color[node] = GRAY
            path.append(node)
            for neighbor in adj.get(node, []):
                if color.get(neighbor, BLACK) == GRAY:
                    # Back edge found — extract the cycle portion
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:]
                    key = frozenset(cycle)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        self._cycles.append(list(cycle))
                elif color.get(neighbor, BLACK) == WHITE:
                    dfs(neighbor)
            path.pop()
            color[node] = BLACK

        for name in self._ordered_procedures:
            if color.get(name, BLACK) == WHITE:
                dfs(name)

    def _detect_unreachable_nodes(self) -> None:
        """Find nodes not reachable from any entry point via internal edges.

        Uses breadth-first search from all known entry points. Nodes that
        cannot be reached are recorded as unreachable.
        """
        adj: dict[str, list[str]] = {name: [] for name in self._nodes}
        for edge in self._edges:
            if (
                edge.edge_type in self._INTERNAL_EDGE_TYPES
                and edge.source in adj
                and edge.target in self._nodes
            ):
                adj[edge.source].append(edge.target)

        reachable: set[str] = set()
        queue: list[str] = list(self._entry_points)

        while queue:
            node = queue.pop(0)
            if node in reachable or node not in self._nodes:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in reachable:
                    queue.append(neighbor)

        self._unreachable_nodes = [
            name for name in self._ordered_procedures if name not in reachable
        ]

    def _build_fall_through_edges(self) -> None:
        """Build fall-through edges between sequential paragraphs.

        In COBOL, when a paragraph finishes without a GO TO or STOP RUN,
        execution falls through to the next paragraph. This adds those
        implicit edges unless the paragraph ends with a terminator.
        """
        for i in range(len(self._ordered_procedures) - 1):
            current = self._ordered_procedures[i]
            next_proc = self._ordered_procedures[i + 1]

            node = self._nodes.get(current)
            if not node:
                continue

            # Skip if procedure ends with a hard terminator
            if node.has_stop_run or node.has_goback or node.has_exit_program:
                continue

            # Skip if procedure has an unconditional GO TO as the last
            # flow-altering statement (heuristic: has GO TO and no PERFORM)
            has_unconditional_goto = False
            for edge in self._edges:
                if edge.source == current and edge.edge_type == FlowEdgeType.GOTO:
                    has_unconditional_goto = True
                    break

            if has_unconditional_goto and node.perform_count == 0:
                continue

            self._edges.append(
                FlowEdge(
                    source=current,
                    target=next_proc,
                    edge_type=FlowEdgeType.FALL_THROUGH,
                    location=node.location,
                )
            )

    @staticmethod
    def _is_valid_procedure_name(name: str) -> bool:
        """Check whether name looks like a real COBOL procedure name."""
        return bool(name) and name not in (".",)
