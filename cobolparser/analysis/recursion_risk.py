"""
Recursion-driven infinite-loop detection for COBOL programs.

Flags two distinct mechanisms by which a COBOL program can end up looping
forever (or misbehaving in an equivalent way) at runtime:

- **PERFORM / GO TO cycles** at the paragraph level: reuses
  :class:`~.program_flow.ProgramFlowAnalyzer`'s cycle detection
  (``cycle_details``) and adds runtime-risk framing on top of it. An
  out-of-line ``PERFORM`` cycle (paragraph A performs B, B performs A) is
  invalid COBOL -- standard COBOL does not support re-entering a paragraph
  while an earlier PERFORM of it is still active, which typically corrupts
  the return address and manifests as an infinite loop or abend. A ``GO TO``
  cycle is checked for an escape hatch: if every paragraph in the loop has no
  other way out (no branch to a paragraph outside the cycle, no program-
  terminating statement), the loop is unconditional.
- **Self-recursive CALL statements**: a CALL (static, or dynamic with a
  resolvable target -- see :class:`~.value_tracker.DynamicCallAnalyzer`)
  whose target is the enclosing program's own PROGRAM-ID. COBOL programs are
  non-reentrant by default, so calling yourself recurses without bound (or
  abends on re-entry) unless the dialect and compiler support and the
  program actually declares itself recursive -- a declaration this parser
  does not currently track, so every self-CALL is flagged.
"""

from dataclasses import dataclass, field
from typing import Any

from ..models.program import CobolProgram
from ..models.statements.call import CallStatement
from .program_flow import ProgramFlowAnalyzer, ProgramFlowReport
from .program_flow.edges import INTERNAL_EDGE_TYPES, PERFORM_EDGE_TYPES
from .program_flow.models import FlowEdgeType
from .value_tracker import DynamicCallAnalyzer

_LOOP_CYCLE_KINDS = frozenset({"PERFORM_RECURSION", "GOTO_LOOP", "MIXED"})


@dataclass
class RecursionRisk:
    """A single recursion-driven infinite-loop risk."""

    mechanism: str  # "PERFORM" | "GOTO" | "MIXED" | "CALL"
    severity: str  # "HIGH" or "MEDIUM"
    explanation: str
    procedures: list[str] = field(default_factory=list)
    program: str | None = None  # only set for mechanism == "CALL"
    is_dynamic: bool = False  # only meaningful for mechanism == "CALL"
    has_escape: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "mechanism": self.mechanism,
            "severity": self.severity,
            "explanation": self.explanation,
        }
        if self.procedures:
            result["procedures"] = self.procedures
        if self.program is not None:
            result["program"] = self.program
            result["is_dynamic"] = self.is_dynamic
        if self.mechanism != "CALL":
            result["has_escape"] = self.has_escape
        return result


@dataclass
class RecursionRiskReport:
    """Report of recursion-driven infinite-loop risks in a program."""

    risks: list[RecursionRisk] = field(default_factory=list)

    @property
    def risk_count(self) -> int:
        return len(self.risks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risks": [r.to_dict() for r in self.risks],
            "summary": {
                "risk_count": self.risk_count,
                "high_severity_count": sum(
                    1 for r in self.risks if r.severity == "HIGH"
                ),
            },
        }


class RecursionRiskAnalyzer:
    """Finds PERFORM/GO TO cycles and self-recursive CALLs that risk an
    infinite loop (or equivalent runtime misbehavior) rather than terminating.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer

        result = parse_cobol(source)
        report = RecursionRiskAnalyzer().analyze(result.ast)
        for risk in report.risks:
            print(risk.severity, risk.mechanism, risk.explanation)
        ```
    """

    def analyze(
        self,
        ast: CobolProgram,
        flow_report: ProgramFlowReport | None = None,
    ) -> RecursionRiskReport:
        """Analyze *ast* for recursion-driven infinite-loop risks.

        Args:
            ast: The parsed COBOL program AST.
            flow_report: An already-computed :class:`ProgramFlowReport` to
                reuse instead of running :class:`ProgramFlowAnalyzer` again
                (it shares cycle detection with this analyzer).

        Returns:
            A :class:`RecursionRiskReport` listing every risk found.
        """
        if flow_report is None:
            flow_report = ProgramFlowAnalyzer().analyze(ast)

        risks = self._perform_goto_risks(flow_report)
        risks.extend(self._call_recursion_risks(ast))
        return RecursionRiskReport(risks=risks)

    def _perform_goto_risks(
        self, flow_report: ProgramFlowReport
    ) -> list[RecursionRisk]:
        risks: list[RecursionRisk] = []
        for detail in flow_report.cycle_details:
            kind = detail.get("kind")
            if kind not in _LOOP_CYCLE_KINDS:
                continue

            nodes: list[str] = list(detail.get("nodes", []))
            if not nodes:
                continue
            if self._closed_by_perform_range_end(nodes, flow_report):
                continue
            path = " -> ".join([*nodes, nodes[0]])

            if kind == "PERFORM_RECURSION":
                risks.append(
                    RecursionRisk(
                        mechanism="PERFORM",
                        severity="HIGH",
                        has_escape=False,
                        procedures=nodes,
                        explanation=(
                            f"{path} forms an out-of-line PERFORM cycle -- each "
                            "paragraph PERFORMs the next, back to the first. "
                            "Standard COBOL does not support re-entering a "
                            "paragraph while an earlier PERFORM of it is still "
                            "active; this typically corrupts the return address "
                            "and manifests as an infinite loop (or abend) at "
                            "runtime, regardless of any UNTIL/TIMES/VARYING "
                            "clause on the individual PERFORMs."
                        ),
                    )
                )
                continue

            mechanism = "GOTO" if kind == "GOTO_LOOP" else "MIXED"
            verb = "GO TO" if kind == "GOTO_LOOP" else "PERFORM/GO TO"
            has_escape = self._has_escape(nodes, flow_report)
            if has_escape:
                explanation = (
                    f"{path} forms a {verb} cycle, but at least one paragraph "
                    "in the loop also has another way out (a branch to a "
                    "paragraph outside the cycle, or a program-terminating "
                    "statement) -- confirm that path is actually reachable "
                    "before ruling out an infinite loop."
                )
            else:
                explanation = (
                    f"{path} forms a {verb} cycle with no paragraph in the "
                    "loop able to branch elsewhere or terminate the program -- "
                    "this is an unconditional infinite loop."
                )
            risks.append(
                RecursionRisk(
                    mechanism=mechanism,
                    severity="MEDIUM" if has_escape else "HIGH",
                    has_escape=has_escape,
                    procedures=nodes,
                    explanation=explanation,
                )
            )
        return risks

    @staticmethod
    def _closed_by_perform_range_end(
        cycle: list[str], flow_report: ProgramFlowReport
    ) -> bool:
        """True if *cycle* only closes by falling off the end of a PERFORM
        range the cycle itself entered by PERFORM -- an edge that cannot fire.

        ``ProgramFlowAnalyzer`` emits a ``FALL_THROUGH`` edge between *any*
        two adjacent non-terminating procedures, PERFORM targets included (a
        documented over-approximation of the CFG). But a PERFORM *returns*
        at the end of its range; control never runs off the end of
        ``1000-READ`` into ``2000-PROCESS``. So the priming-read idiom --
        ``MAIN`` performs ``1000-READ`` and ``2000-PROCESS``, and
        ``2000-PROCESS`` performs ``1000-READ`` again -- shows up in
        ``cycle_details`` as a ``MIXED`` cycle (``2000-PROCESS ->
        1000-READ`` by PERFORM, ``1000-READ -> 2000-PROCESS`` by
        fall-through) that no execution can traverse.

        The test is per hop, not per node: a hop that *needs* a fall-through
        edge (no PERFORM/GO TO edge connects the same pair) out of paragraph
        ``P`` is impossible when some other hop of the same cycle can *only*
        be closed by a PERFORM whose range ends at ``P`` -- the cycle enters
        the range by PERFORM, so it leaves it by returning. A paragraph that
        is also reachable by fall-through or GO TO (the hop into it is not
        PERFORM-only) keeps its fall-through exit, and a range left by a
        ``GO TO`` rather than by running off its end is still a loop.
        """
        pair_edges: dict[tuple[str, str], list[Any]] = {}
        for edge in flow_report.edges:
            if edge.edge_type in INTERNAL_EDGE_TYPES:
                pair_edges.setdefault((edge.source, edge.target), []).append(edge)

        n = len(cycle)
        hops = [(cycle[i], cycle[(i + 1) % n]) for i in range(n)]
        hop_edges = [pair_edges.get(hop, []) for hop in hops]
        hop_types = [{e.edge_type for e in edges} for edges in hop_edges]

        for i, (src, _tgt) in enumerate(hops):
            if hop_types[i] != {FlowEdgeType.FALL_THROUGH}:
                continue
            for j in range(n):
                if j == i or not hop_types[j] or not hop_types[j] <= PERFORM_EDGE_TYPES:
                    continue
                for edge in hop_edges[j]:
                    # ``PERFORM A`` returns from the end of A; ``PERFORM A
                    # THRU C`` (and its ``*_THRU`` edge, whose target is C)
                    # from C.
                    if (edge.thru_target or edge.target) == src:
                        return True
        return False

    @staticmethod
    def _has_escape(cycle: list[str], flow_report: ProgramFlowReport) -> bool:
        """True if some paragraph in *cycle* can terminate the program or
        branch to a paragraph outside the cycle -- i.e. the loop is not
        unconditionally trapped once entered."""
        cycle_set = set(cycle)
        nodes_by_name = {n.key: n for n in flow_report.nodes}
        for name in cycle:
            node = nodes_by_name.get(name)
            if node is not None and (
                node.has_stop_run
                or node.has_goback
                or node.has_exit_program
                or node.has_return
            ):
                return True
        for edge in flow_report.edges:
            if (
                edge.source in cycle_set
                and edge.target not in cycle_set
                and edge.edge_type in INTERNAL_EDGE_TYPES
            ):
                return True
        return False

    @staticmethod
    def _call_recursion_risks(ast: CobolProgram) -> list[RecursionRisk]:
        program_name = (ast.program_name or "").strip().upper()
        if not program_name:
            return []

        DynamicCallAnalyzer().analyze(ast)

        risks: list[RecursionRisk] = []
        for stmt in ast.find_all_by_type("CallStatement"):
            if not isinstance(stmt, CallStatement):
                continue
            if stmt.is_dynamic:
                targets = {v.strip("'\"").upper() for v in stmt.possible_values}
            elif stmt.called_program:
                targets = {stmt.called_program.strip("'\"").upper()}
            else:
                targets = set()
            if program_name not in targets:
                continue

            call_kind = "dynamically " if stmt.is_dynamic else ""
            if ast.is_recursive:
                # ``PROGRAM-ID. name IS RECURSIVE``: re-entry is legal and
                # the programmer said so. What remains is the ordinary
                # unbounded-recursion question every recursive routine
                # carries, which static analysis cannot settle -- worth
                # noting, not worth an error.
                risks.append(
                    RecursionRisk(
                        mechanism="CALL",
                        severity="LOW",
                        program=program_name,
                        is_dynamic=stmt.is_dynamic,
                        explanation=(
                            f"This CALL {call_kind}targets '{program_name}', "
                            "the program's own PROGRAM-ID, which is declared "
                            "IS RECURSIVE -- re-entry is legal (LOCAL-STORAGE "
                            "is per invocation). The recursion still needs a "
                            "base case the analyzer cannot verify."
                        ),
                    )
                )
                continue
            risks.append(
                RecursionRisk(
                    mechanism="CALL",
                    severity="HIGH",
                    # The resolved target, not stmt.called_program -- for a
                    # dynamic CALL that's a variable name (e.g. "TARGET-PROG"),
                    # not the program name the recursion risk is actually about.
                    program=program_name,
                    is_dynamic=stmt.is_dynamic,
                    explanation=(
                        f"This CALL {call_kind}targets '{program_name}', the "
                        "program's own PROGRAM-ID. COBOL programs are "
                        "non-reentrant by default -- calling yourself, "
                        "directly or via a dynamic value that can resolve to "
                        "your own name, either abends on re-entry or recurses "
                        "without a runtime-enforced bound."
                    ),
                )
            )
        return risks
