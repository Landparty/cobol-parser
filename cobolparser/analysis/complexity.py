"""
Cyclomatic complexity and maintainability metrics for COBOL programs.

Computes a McCabe-style cyclomatic complexity per paragraph/section by
walking each procedure's own statement tree (not the inter-paragraph control
flow graph -- most COBOL complexity lives *inside* a paragraph, in its
IF/EVALUATE/SEARCH/loop-PERFORM constructs and exception-handling clauses,
not in how paragraphs call each other). Fan-in/fan-out and GO TO counts are
pulled from :class:`~.program_flow.ProgramFlowAnalyzer`'s control flow graph,
which already tracks inter-paragraph edges accurately.

Two complexity numbers are reported per procedure:

- ``cyclomatic_complexity`` -- classic McCabe: 1 plus one decision point per
  IF, per WHEN arm (EVALUATE/SEARCH, excluding WHEN OTHER/the default), per
  loop-form PERFORM and per AFTER phrase of a PERFORM VARYING (TIMES/UNTIL/
  VARYING -- a bare ``PERFORM target`` is not
  a decision point, it always runs exactly once), per target of a computed
  ``GO TO ... DEPENDING ON`` (an N-target computed GO TO is an N-way branch
  plus the out-of-range fall-through, scored like an N-arm EVALUATE), and
  one per present exception-handling clause *pair* (AT END / NOT AT END,
  INVALID KEY / NOT INVALID KEY, AT EOP / NOT AT EOP, ON SIZE ERROR / NOT ON
  SIZE ERROR, ON OVERFLOW / NOT ON OVERFLOW, ON EXCEPTION / NOT ON
  EXCEPTION). A clause and its NOT- twin are the two outcomes of one binary
  test (EOF or not), exactly as IF ... ELSE is one decision, so writing
  both bodies adds 1, not 2 (#553). SEARCH's AT END adds nothing: a SEARCH
  already has its not-found path (it falls through) and is scored one per
  WHEN.
- ``extended_complexity`` -- the same base plus one per boolean AND/OR
  operator in every condition tree, since ``IF A AND B OR C`` has more
  distinct paths through it than a bare ``IF A``, even though both are "one
  IF" for classic McCabe.

A bare ``SECTION`` header holds no statements of its own (paragraphs are
always the real statement containers -- see ``dead_code.py`` and
``program_flow/scanner.py`` for the same observation), so every SECTION
procedure reports the trivial complexity of 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.base import CobolStatement, LogicalExpression
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ._procedures import ProcedureIndex
from .program_flow import ProgramFlowAnalyzer, ProgramFlowReport
from .program_flow.edges import GOTO_EDGE_TYPES, PERFORM_EDGE_TYPES
from .program_flow.scanner import LEADING_SENTENCES_NODE, leading_sentences

# Clause-list attributes that hold nested statements executed only when the
# clause's condition (an exception, an EOF, an overflow) actually fires or
# does not -- grouped in (positive, NOT-) pairs, because the two are the two
# outcomes of one test: a pair with either side present is one decision
# point, however many of its bodies are written (#553). A local
# re-derivation of the same attribute set ``program_flow/scanner.py``'s
# ``_CLAUSE_BODY_ATTRS`` and ``constraints.py``'s ``_NESTED_STATEMENT_ATTRS``
# already establish (this module's own convention per the OKF: re-derived per
# module rather than imported, so a change to one walker's needs never
# silently changes another's). Includes ``on_exception``/``not_on_exception``/
# ``on_overflow`` (CALL's exception handlers), which are the one clause shape
# *not* wired into ``.children`` by the AST models -- everything else here is
# already reachable via the generic child walk below, but checking the full
# set directly (rather than only the CALL-specific gap) is cheap and matches
# established precedent.
_CLAUSE_PAIRS: tuple[tuple[str, str], ...] = (
    ("at_end_clause", "not_at_end_clause"),
    ("invalid_key_clause", "not_invalid_key_clause"),
    ("at_eop_clause", "not_at_eop_clause"),
    ("on_size_error", "not_on_size_error"),
    ("on_overflow", "not_on_overflow"),
    ("on_exception", "not_on_exception"),
)

_LOOP_PERFORM_TYPES = frozenset({"TIMES", "UNTIL", "VARYING"})

_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
# The OR of ``GREATER THAN OR EQUAL TO`` belongs to the relational operator.
_BOOL_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:AND|OR(?!\s+EQUALS?(?![A-Za-z0-9_-])))(?![A-Za-z0-9_-])",
    re.I,
)


def _text_bool_ops(text: Any) -> int:
    """AND/OR operators in raw condition text, quoted literals skipped."""
    if not isinstance(text, str) or not text:
        return 0
    return len(_BOOL_WORD_RE.findall(_QUOTED_RE.sub(" ", text)))


@dataclass
class ComplexityThresholds:
    """Complexity bands used to grade a procedure's cyclomatic complexity.

    Standard McCabe bands: <= moderate is LOW risk, <= high is MODERATE
    risk, above high is HIGH risk. Overridable per analysis run rather than
    hard-coded, since "what counts as too complex" is a house-style choice.
    """

    moderate: int = 10
    high: int = 20

    def rating(self, complexity: int) -> str:
        if complexity > self.high:
            return "HIGH"
        if complexity > self.moderate:
            return "MODERATE"
        return "LOW"


@dataclass
class ProcedureComplexity:
    """Complexity metrics for a single paragraph or section."""

    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    location: SourceLocation
    cyclomatic_complexity: int
    extended_complexity: int
    max_nesting_depth: int
    statement_count: int
    goto_count: int
    fan_in: int
    fan_out: int
    rating: str
    #: ``"X1 OF S2"`` when another paragraph shares this one's name (see
    #: ``FlowNode.qualified_name``), else ``None``.
    qualified_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.procedure_type,
            "location": self.location.to_dict(),
        }
        if self.qualified_name:
            result["qualified_name"] = self.qualified_name
        result |= {
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "extended_complexity": self.extended_complexity,
            "max_nesting_depth": self.max_nesting_depth,
            "statement_count": self.statement_count,
            "goto_count": self.goto_count,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
            "rating": self.rating,
        }
        return result


@dataclass
class ComplexityReport:
    """Program-wide complexity report."""

    program_name: str = ""
    procedures: list[ProcedureComplexity] = field(default_factory=list)
    thresholds: ComplexityThresholds = field(default_factory=ComplexityThresholds)

    @property
    def total_complexity(self) -> int:
        return sum(p.cyclomatic_complexity for p in self.procedures)

    @property
    def max_complexity(self) -> int:
        return max((p.cyclomatic_complexity for p in self.procedures), default=0)

    @property
    def mean_complexity(self) -> float:
        if not self.procedures:
            return 0.0
        return self.total_complexity / len(self.procedures)

    @property
    def moderate_count(self) -> int:
        return sum(1 for p in self.procedures if p.rating == "MODERATE")

    @property
    def high_count(self) -> int:
        return sum(1 for p in self.procedures if p.rating == "HIGH")

    @property
    def goto_density(self) -> float:
        """GO TOs per 100 statements, across the whole program."""
        total_statements = sum(p.statement_count for p in self.procedures)
        if total_statements == 0:
            return 0.0
        total_gotos = sum(p.goto_count for p in self.procedures)
        return (total_gotos / total_statements) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "procedures": [p.to_dict() for p in self.procedures],
            "thresholds": {
                "moderate": self.thresholds.moderate,
                "high": self.thresholds.high,
            },
            "summary": {
                "procedure_count": len(self.procedures),
                "total_complexity": self.total_complexity,
                "max_complexity": self.max_complexity,
                "mean_complexity": round(self.mean_complexity, 2),
                "moderate_count": self.moderate_count,
                "high_count": self.high_count,
                "goto_density": round(self.goto_density, 2),
            },
        }


class ComplexityAnalyzer:
    """Computes cyclomatic complexity and maintainability metrics.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.complexity import ComplexityAnalyzer

        result = parse_cobol(source)
        report = ComplexityAnalyzer().analyze(result.ast)
        for proc in report.procedures:
            print(f"{proc.name}: {proc.cyclomatic_complexity} ({proc.rating})")
        ```
    """

    def __init__(self, thresholds: ComplexityThresholds | None = None) -> None:
        self._thresholds = thresholds or ComplexityThresholds()

    def analyze(
        self,
        ast: CobolProgram,
        flow_report: ProgramFlowReport | None = None,
    ) -> ComplexityReport:
        """Analyze a COBOL program for complexity.

        Args:
            ast: The parsed COBOL program AST.
            flow_report: An optional precomputed ``ProgramFlowReport`` (from
                ``ProgramFlowAnalyzer``) to avoid a second pass over the same
                AST when a caller already has one.

        Returns:
            A ComplexityReport with per-procedure and program-level metrics.
        """
        proc_division = ast.procedure_division
        if proc_division is None:
            return ComplexityReport(program_name=ast.program_name)

        if flow_report is None:
            flow_report = ProgramFlowAnalyzer().analyze(ast)

        paragraph_map = self._collect_paragraph_map(proc_division)
        fan_in, fan_out = self._collect_fan_counts(flow_report)

        procedures: list[ProcedureComplexity] = []
        for node in flow_report.nodes:
            decisions = extra_bool_ops = max_depth = 0
            # Same-named paragraphs in different sections are separate
            # nodes (keyed "X1 OF S2"), each measured on its own body. A
            # list only because a duplicate the compiler would reject still
            # merges into its namesake. A SECTION node's body is the
            # sentences before its first paragraph header (none for a bare
            # header: complexity 1).
            for para in paragraph_map.get(node.key, []):
                d, b, m = self._analyze_paragraph(para)
                decisions += d
                extra_bool_ops += b
                max_depth = max(max_depth, m)
            cyclomatic = 1 + decisions
            extended = 1 + decisions + extra_bool_ops

            procedures.append(
                ProcedureComplexity(
                    name=node.name,
                    procedure_type=node.procedure_type,
                    location=node.location,
                    cyclomatic_complexity=cyclomatic,
                    extended_complexity=extended,
                    max_nesting_depth=max_depth,
                    statement_count=node.statement_count,
                    goto_count=node.goto_count,
                    fan_in=len(fan_in.get(node.key, set())),
                    fan_out=len(fan_out.get(node.key, set())),
                    rating=self._thresholds.rating(cyclomatic),
                    qualified_name=node.qualified_name,
                )
            )

        return ComplexityReport(
            program_name=ast.program_name,
            procedures=procedures,
            thresholds=self._thresholds,
        )

    @staticmethod
    def _collect_paragraph_map(
        proc_division: CobolDivision,
    ) -> dict[str, list[CobolParagraph]]:
        """Map every flow node key to the paragraph bodies it stands for.

        Keys come from :class:`~._procedures.ProcedureIndex`, the identity
        the flow scanner gives each node, so two same-named paragraphs in
        different sections map to their own bodies. A section maps to the
        sentences between its header and its first paragraph (the flow
        scanner counts them there too).
        """
        index = ProcedureIndex.build(proc_division)
        keys = {id(entry.node): entry.key for entry in index.entries}
        result: dict[str, list[CobolParagraph]] = {}

        def add(body: Any, para: CobolParagraph, name: str | None) -> None:
            key = keys.get(id(body)) or (name.upper() if name else None)
            if key:
                result.setdefault(key, []).append(para)

        for section in proc_division._sections.values():
            for para in section.paragraphs:
                if para.paragraph_name:
                    add(para, para, para.paragraph_name)
                elif section.section_name:
                    add(section, para, section.section_name)
        for para in proc_division.paragraphs:
            if para.paragraph_name:
                add(para, para, para.paragraph_name)
        # The division's leading sentences are a flow node of their own.
        leading = leading_sentences(proc_division)
        if leading is not None:
            result[LEADING_SENTENCES_NODE] = [leading]
        return result

    @staticmethod
    def _collect_fan_counts(
        flow_report: ProgramFlowReport,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """Distinct in/out neighbors per procedure via real PERFORM/GO TO edges.

        Restricted to ``PERFORM_EDGE_TYPES | GOTO_EDGE_TYPES`` -- the
        synthetic IF/EVALUATE branch-node edges scanner.py also emits target
        non-procedure node IDs (``PROC__IF_1``, ...), and CALL edges target
        external program names, neither of which belong in an in-program
        fan-in/fan-out count.
        """
        edge_types = PERFORM_EDGE_TYPES | GOTO_EDGE_TYPES
        fan_out: dict[str, set[str]] = {}
        fan_in: dict[str, set[str]] = {}
        for edge in flow_report.edges:
            if edge.edge_type not in edge_types:
                continue
            fan_out.setdefault(edge.source, set()).add(edge.target)
            fan_in.setdefault(edge.target, set()).add(edge.source)
        return fan_in, fan_out

    @staticmethod
    def _analyze_paragraph(para: CobolParagraph) -> tuple[int, int, int]:
        """Walk one paragraph's statement tree.

        Returns ``(decision_points, extra_boolean_operators, max_nesting_depth)``.
        Uses plain recursion over ``.children`` plus the explicit clause-list
        fallback (mirroring ``CobolProgram.get_all_statements()``'s own
        traversal shape) rather than an explicit stack: paragraph statement
        trees are bounded by source nesting, not the pathological
        machine-generated depths ``program_flow``'s CFG walkers guard
        against.
        """
        visited: set[int] = set()
        counts = {"decisions": 0, "bool_ops": 0, "max_depth": 0}

        def walk(node: Any, depth: int) -> None:
            if not hasattr(node, "node_type"):
                return
            if id(node) in visited:
                return
            visited.add(id(node))

            child_depth = depth
            if isinstance(node, IfStatement):
                counts["decisions"] += 1
                counts["max_depth"] = max(counts["max_depth"], depth + 1)
                child_depth = depth + 1
            elif isinstance(node, EvaluateStatement):
                counts["decisions"] += len(node.when_clauses)
                counts["max_depth"] = max(counts["max_depth"], depth + 1)
                child_depth = depth + 1
                # ``EVALUATE TRUE WHEN A = 1 AND B = 2`` keeps its condition
                # as raw text on the selector, never as a LogicalExpression
                # the child walk below could count.
                for when_clause in node.when_clauses:
                    for selector in when_clause.selectors:
                        if (
                            isinstance(selector, dict)
                            and selector.get("type") == "Condition"
                        ):
                            counts["bool_ops"] += _text_bool_ops(selector.get("text"))
            elif isinstance(node, SearchStatement):
                counts["decisions"] += len(node.when_clauses)
                counts["max_depth"] = max(counts["max_depth"], depth + 1)
                child_depth = depth + 1
                # SEARCH WHEN conditions are raw text too.
                for search_clause in node.when_clauses:
                    counts["bool_ops"] += _text_bool_ops(search_clause.get("condition"))
            elif (
                isinstance(node, PerformStatement)
                and node.perform_type in _LOOP_PERFORM_TYPES
            ):
                # Each AFTER phrase is a loop nested inside the previous one,
                # with its own UNTIL test: score it as the nested inline
                # PERFORM VARYING it is equivalent to (#514).
                loops = 1 + len(node.after_clauses or ())
                counts["decisions"] += loops
                counts["max_depth"] = max(counts["max_depth"], depth + loops)
                child_depth = depth + loops
            elif isinstance(node, GoStatement) and node.depending_on_variable:
                # A computed GO TO is an N-way branch (plus fall-through when
                # the variable is out of range): one decision per target, the
                # same count a WHEN-per-target EVALUATE gets. GO TO opens no
                # block, so nesting depth is unchanged.
                counts["decisions"] += len(node.target_paragraphs)
            elif isinstance(node, LogicalExpression) and (
                str(node.operator).upper() in ("AND", "OR")
            ):
                # A unary NOT adds no path; only AND/OR do.
                counts["bool_ops"] += 1

            if isinstance(node, CobolStatement):
                for pair in _CLAUSE_PAIRS:
                    clauses = [getattr(node, attr, None) for attr in pair]
                    if not any(clauses):
                        continue
                    # SEARCH's not-found path exists with or without an
                    # AT END body; its WHENs are already counted above.
                    if not isinstance(node, SearchStatement):
                        counts["decisions"] += 1
                    for clause in clauses:
                        for stmt in clause or ():
                            walk(stmt, child_depth)

            for child in getattr(node, "children", []):
                walk(child, child_depth)

        for stmt in para.statements:
            walk(stmt, 0)

        return counts["decisions"], counts["bool_ops"], counts["max_depth"]
