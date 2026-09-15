"""The ProgramFlowAnalyzer orchestrator.

Coordinates the collaborators — :class:`~.scanner.ProcedureScanner` and
:class:`~.edges.EdgeCollector` for statement scanning / edge collection,
:mod:`~.cycles` for cycle detection and classification, and :mod:`~.graph`
for the whole-graph post-passes — and assembles the final
:class:`~.models.ProgramFlowReport`.
"""

from typing import Any

from ...models.program import CobolDivision, CobolProgram, CobolSection
from .cycles import classify_cycles, detect_cycles
from .edges import (
    GOTO_EDGE_TYPES,
    INTERNAL_EDGE_TYPES,
    PERFORM_EDGE_TYPES,
    EdgeCollector,
)
from .graph import (
    build_fall_through_edges,
    compute_convergence_nodes,
    find_unreachable_nodes,
)
from .models import (
    BranchNode,
    FlowEdge,
    FlowEdgeType,
    FlowNode,
    ProgramFlowReport,
)
from .scanner import ProcedureScanner


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

    # Edge-type categories, kept as class attributes for backwards
    # compatibility; the canonical definitions live in ``edges.py``.
    _INTERNAL_EDGE_TYPES: frozenset[FlowEdgeType] = INTERNAL_EDGE_TYPES
    _PERFORM_EDGE_TYPES: frozenset[FlowEdgeType] = PERFORM_EDGE_TYPES
    _GOTO_EDGE_TYPES: frozenset[FlowEdgeType] = GOTO_EDGE_TYPES

    def __init__(self) -> None:
        self._nodes: dict[str, FlowNode] = {}
        self._edges: list[FlowEdge] = []
        self._ordered_procedures: list[str] = []
        self._entry_points: list[str] = []
        self._exit_points: set[str] = set()
        self._external_calls: list[dict[str, Any]] = []
        self._program_cancellations: list[dict[str, Any]] = []
        self._cycles: list[list[str]] = []
        self._cycle_details: list[dict[str, Any]] = []
        self._unreachable_nodes: list[str] = []
        self._branch_nodes: list[BranchNode] = []
        self._terminating_paragraphs: set[str] = set()

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
        self._cycle_details = []
        self._unreachable_nodes = []
        self._branch_nodes = []
        self._terminating_paragraphs = set()

        proc_division = ast.procedure_division
        if proc_division is None:
            return ProgramFlowReport(program_name=ast.program_name)

        collector = EdgeCollector(
            edges=self._edges,
            ordered_procedures=self._ordered_procedures,
            external_calls=self._external_calls,
            program_cancellations=self._program_cancellations,
        )
        scanner = ProcedureScanner(
            nodes=self._nodes,
            ordered_procedures=self._ordered_procedures,
            edges=self._edges,
            entry_points=self._entry_points,
            exit_points=self._exit_points,
            branch_nodes=self._branch_nodes,
            collector=collector,
            terminating_paragraphs=self._terminating_paragraphs,
        )

        # Pass 1: Collect all procedures as nodes
        scanner.collect_procedures(proc_division)
        declaratives = self._declarative_procedures(proc_division)
        for name in declaratives:
            if name in self._nodes:
                self._nodes[name].is_declarative = True

        # Pass 2: Scan statements to build edges and node metrics
        scanner.scan_statements(proc_division)

        # Pass 3: Collect ENTRY statements for alternate entry points
        scanner.collect_entry_points(ast)

        # Pass 4: Determine fall-through edges
        build_fall_through_edges(
            self._nodes,
            self._edges,
            self._ordered_procedures,
            self._terminating_paragraphs,
        )

        # Mark the first procedure as entry point before cycle/reachability analysis
        # so that the entry point set is complete when those passes run.
        # DECLARATIVES precede the main code in source order but control
        # never enters there: the entry point is the first procedure after
        # END DECLARATIVES. Each declarative *section* is itself an entry
        # the runtime uses (a USE procedure runs on an I/O error), so it is
        # registered as one too -- after the real entry -- rather than being
        # reported unreachable.
        first = next(
            (p for p in self._ordered_procedures if p not in declaratives), None
        )
        if first is not None and first in self._nodes:
            self._nodes[first].is_entry_point = True
            if first not in self._entry_points:
                self._entry_points.insert(0, first)
        for name in self._ordered_procedures:
            node = self._nodes.get(name)
            if (
                node is not None
                and node.is_declarative
                and node.procedure_type == "SECTION"
                and name not in self._entry_points
            ):
                node.is_entry_point = True
                self._entry_points.append(name)

        # Pass 4a: Compute convergence nodes for branch decisions
        compute_convergence_nodes(self._edges, self._branch_nodes)

        # Pass 5: Detect and classify cycles in internal flow graph
        self._cycles = detect_cycles(self._nodes, self._edges, self._ordered_procedures)
        self._cycle_details = classify_cycles(self._cycles, self._edges)

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
        report.cycle_details = self._cycle_details
        report.unreachable_nodes = self._unreachable_nodes
        report.branch_nodes = self._branch_nodes
        return report

    @staticmethod
    def _declarative_procedures(proc_division: CobolDivision) -> set[str]:
        """Every DECLARATIVES section name and paragraph name, upper-cased."""
        names: set[str] = set()
        for section in proc_division._sections.values():
            if not isinstance(section, CobolSection) or not section.is_declarative:
                continue
            if section.section_name:
                names.add(section.section_name.upper())
            for para in section.paragraphs:
                if para.paragraph_name:
                    names.add(para.paragraph_name.upper())
        return names

    def _detect_unreachable_nodes(self) -> None:
        """Find nodes not reachable from any entry point via internal edges."""
        self._unreachable_nodes = find_unreachable_nodes(
            self._nodes,
            self._edges,
            self._ordered_procedures,
            self._entry_points,
        )
