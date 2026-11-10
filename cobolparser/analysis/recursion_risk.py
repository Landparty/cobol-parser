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
  cycle is checked for an escape hatch over its whole strongly connected
  component, not just the cycle itself: when two loops share a paragraph,
  each one's "exit" can be the other loop. If no paragraph of the component
  branches outside it or terminates the program, the loop is unconditional.
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
from ..models.statements.call import CallStatement, EntryStatement
from ..models.walk import own_statements
from ._names import callee_names
from .context import ProgramContext
from .program_flow import ProgramFlowReport
from .program_flow.edges import INTERNAL_EDGE_TYPES, PERFORM_EDGE_TYPES
from .program_flow.models import FlowEdgeType
from .value_tracker import DynamicCallAnalyzer

#: Edges that carry control to another paragraph: what a cycle escapes
#: through. ``INTERNAL_EDGE_TYPES`` also holds the synthetic IF_BRANCH /
#: EVALUATE_BRANCH edges, whose target is a branch node (``L1__IF_1``) that
#: is never a cycle member -- so any GO TO loop whose body held an IF read
#: as having "a way out" and was graded MEDIUM, and HIGH was unreachable for
#: every real loop (2026-10-08).
_ESCAPE_EDGE_TYPES: frozenset[FlowEdgeType] = INTERNAL_EDGE_TYPES - {
    FlowEdgeType.IF_BRANCH,
    FlowEdgeType.EVALUATE_BRANCH,
}

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


def _perform_range(target: str, flow_report: ProgramFlowReport) -> list[str]:
    """The procedures ``PERFORM target`` executes, in source order.

    A paragraph is its own range; a SECTION is its header plus every
    paragraph up to the next section, so the range ends at the section's
    last paragraph rather than at the header node.
    """
    nodes = flow_report.nodes
    for idx, node in enumerate(nodes):
        if node.key != target:
            continue
        if node.procedure_type != "SECTION":
            return [target]
        members = [target]
        for later in nodes[idx + 1 :]:
            if later.procedure_type == "SECTION":
                break
            members.append(later.key)
        return members
    return [target]


def _components(flow_report: ProgramFlowReport) -> dict[str, frozenset[str]]:
    """Map each procedure to its strongly connected component over the
    edges a loop can travel (``_ESCAPE_EDGE_TYPES``), by Tarjan's algorithm
    (iterative, so a long GO TO chain cannot hit the recursion limit)."""
    succ: dict[str, list[str]] = {}
    for edge in flow_report.edges:
        if edge.edge_type in _ESCAPE_EDGE_TYPES:
            succ.setdefault(edge.source, []).append(edge.target)
            succ.setdefault(edge.target, [])

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: dict[str, frozenset[str]] = {}
    counter = 0
    for root in succ:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            targets = succ[node]
            if i < len(targets):
                work.append((node, i + 1))
                target = targets[i]
                if target not in index:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index[target])
                continue
            if low[node] == index[node]:
                members: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node:
                        break
                component = frozenset(members)
                for member in members:
                    result[member] = component
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return result


class _FlowIndex:
    """Lookups over one ``ProgramFlowReport``, built once per analysis.

    Every cycle in ``cycle_details`` is checked against the same edges, and
    the "GO TO restart" idiom (every paragraph may jump back to the first)
    yields one cycle per paragraph, each nearly as long as the program:
    rebuilding these per cycle made ``recursion-check`` (and ``lint`` /
    ``health``) cubic -- 17 s at 800 paragraphs (#373).
    """

    def __init__(self, flow_report: ProgramFlowReport) -> None:
        self.flow_report = flow_report
        self.pair_edges: dict[tuple[str, str], list[Any]] = {}
        pair_types: dict[tuple[str, str], set[FlowEdgeType]] = {}
        self.escape_targets: dict[str, set[str]] = {}
        for edge in flow_report.edges:
            if edge.edge_type not in INTERNAL_EDGE_TYPES:
                continue
            pair = (edge.source, edge.target)
            self.pair_edges.setdefault(pair, []).append(edge)
            pair_types.setdefault(pair, set()).add(edge.edge_type)
            if edge.edge_type in _ESCAPE_EDGE_TYPES:
                self.escape_targets.setdefault(edge.source, set()).add(edge.target)
        self.pair_types: dict[tuple[str, str], frozenset[FlowEdgeType]] = {
            pair: frozenset(types) for pair, types in pair_types.items()
        }
        self.nodes_by_name = {node.key: node for node in flow_report.nodes}
        self._ranges: dict[str, list[str]] = {}
        self._escapes: dict[frozenset[str], bool] = {}

    def types(self, hop: tuple[str, str]) -> frozenset[FlowEdgeType]:
        return self.pair_types.get(hop, frozenset())

    def perform_range(self, target: str) -> list[str]:
        cached = self._ranges.get(target)
        if cached is None:
            cached = self._ranges[target] = _perform_range(target, self.flow_report)
        return cached

    def has_escape(self, component: frozenset[str]) -> bool:
        cached = self._escapes.get(component)
        if cached is None:
            cached = self._escapes[component] = self._has_escape(component)
        return cached

    def _has_escape(self, component: frozenset[str]) -> bool:
        for name in component:
            node = self.nodes_by_name.get(name)
            if node is not None and (
                node.has_stop_run
                or node.has_goback
                or node.has_exit_program
                or node.has_cics_exit
                or node.has_abend_call
            ):
                return True
            if not self.escape_targets.get(name, set()) <= component:
                return True
        return False


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
        ast: CobolProgram | ProgramContext,
        flow_report: ProgramFlowReport | None = None,
    ) -> RecursionRiskReport:
        """Analyze *ast* for recursion-driven infinite-loop risks.

        Args:
            ast: The parsed COBOL program AST, or a
                :class:`~.context.ProgramContext` whose flow graph is reused.
            flow_report: An already-computed :class:`ProgramFlowReport` to
                reuse instead of running :class:`ProgramFlowAnalyzer` again
                (it shares cycle detection with this analyzer).

        Returns:
            A :class:`RecursionRiskReport` listing every risk found.
        """
        ctx = ProgramContext.of(ast, flow=flow_report)
        risks = self._perform_goto_risks(ctx.flow)
        risks.extend(self._call_recursion_risks(ctx.ast))
        return RecursionRiskReport(risks=risks)

    def _perform_goto_risks(
        self, flow_report: ProgramFlowReport
    ) -> list[RecursionRisk]:
        risks: list[RecursionRisk] = []
        component_of = _components(flow_report)
        index = _FlowIndex(flow_report)
        for detail in flow_report.cycle_details:
            kind = detail.get("kind")
            if kind not in _LOOP_CYCLE_KINDS:
                continue

            nodes: list[str] = list(detail.get("nodes", []))
            if not nodes:
                continue
            if self._closed_by_perform_range_end(nodes, index):
                continue
            path = " -> ".join([*nodes, nodes[0]])

            if kind == "MIXED" and self._reenters_own_perform_range(nodes, index):
                risks.append(
                    RecursionRisk(
                        mechanism="PERFORM",
                        severity="HIGH",
                        has_escape=False,
                        procedures=nodes,
                        explanation=(
                            f"{path} PERFORMs a range (a SECTION, or a THRU "
                            "range) from inside that same range -- the cycle "
                            "only falls through the range's own paragraphs "
                            "back to the PERFORM. Standard COBOL does not "
                            "support re-entering a range while an earlier "
                            "PERFORM of it is still active; this typically "
                            "corrupts the return address and manifests as an "
                            "infinite loop (or abend) at runtime."
                        ),
                    )
                )
                continue

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
            component = component_of.get(nodes[0], frozenset(nodes))
            has_escape = self._has_escape(component, index)
            if has_escape:
                explanation = (
                    f"{path} forms a {verb} cycle, but at least one paragraph "
                    "in the loop (or in a loop it shares paragraphs with) also "
                    "has another way out (a branch to a paragraph outside "
                    "them, or a program-terminating statement) -- confirm "
                    "that path is actually reachable before ruling out an "
                    "infinite loop."
                )
            else:
                explanation = (
                    f"{path} forms a {verb} cycle with no paragraph in the "
                    "loop, or in any loop it shares paragraphs with, able to "
                    "branch elsewhere or terminate the program -- this is an "
                    "unconditional infinite loop."
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
    def _closed_by_perform_range_end(cycle: list[str], index: _FlowIndex) -> bool:
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

        Linear in the cycle: the range ends of its PERFORM-only hops are
        collected first, then each fall-through-only hop is one set lookup
        (a hop cannot be both, so "some *other* hop" needs no check).
        """
        n = len(cycle)
        hops = [(cycle[i], cycle[(i + 1) % n]) for i in range(n)]
        range_ends: set[str] = set()
        for hop in hops:
            types = index.types(hop)
            if not types or not types <= PERFORM_EDGE_TYPES:
                continue
            for edge in index.pair_edges[hop]:
                # ``PERFORM A`` returns from the end of A; ``PERFORM A THRU
                # C`` (and its ``*_THRU`` edge, whose target is C) from C;
                # ``PERFORM S`` of a SECTION from S's last paragraph -- the
                # header's fall-through into its first paragraph is the
                # range executing, not leaving.
                range_ends.add(index.perform_range(edge.thru_target or edge.target)[-1])
        if not range_ends:
            return False
        return any(
            src in range_ends and index.types((src, tgt)) == {FlowEdgeType.FALL_THROUGH}
            for src, tgt in hops
        )

    @staticmethod
    def _reenters_own_perform_range(cycle: list[str], index: _FlowIndex) -> bool:
        """True if *cycle* is a PERFORM of a multi-procedure range made from
        inside that range: one hop is a PERFORM (or PERFORM THRU) whose
        range -- a SECTION and its paragraphs, or a THRU span -- holds every
        node of the cycle, and every other hop is a plain fall-through
        between members of it.

        ``ProgramFlowAnalyzer`` reports that shape as ``MIXED`` (fall-through
        + PERFORM), but it is the range-level twin of ``P. PERFORM P.``: the
        PERFORM always re-enters a range that is still active, whatever
        other exits its paragraphs have.

        Every hop but the PERFORM must be fall-through only, so at most one
        hop may be anything else -- found in one pass, not one per hop.
        """
        n = len(cycle)
        hops = [(cycle[i], cycle[(i + 1) % n]) for i in range(n)]
        others = [
            hop for hop in hops if index.types(hop) != {FlowEdgeType.FALL_THROUGH}
        ]
        # A hop that is fall-through only carries no PERFORM edge, so the
        # PERFORM hop is the one exception (none means no PERFORM at all).
        if len(others) != 1:
            return False
        hop = others[0]
        cycle_set = set(cycle)
        for edge in index.pair_edges.get(hop, []):
            if edge.edge_type not in PERFORM_EDGE_TYPES:
                continue
            members = set(edge.range_members or index.perform_range(edge.target))
            if len(members) >= 2 and cycle_set <= members:
                return True
        return False

    @staticmethod
    def _has_escape(component: frozenset[str], index: _FlowIndex) -> bool:
        """True if some paragraph in *component* -- the strongly connected
        component holding the cycle -- can terminate the program or branch to
        a paragraph outside it, i.e. the loop is not unconditionally trapped
        once entered.

        Checking the cycle alone is not enough: with ``P1 -> P2 -> P1`` and
        ``P1 -> P3 -> P1``, each cycle's exit is the other cycle, so both
        looked escapable while neither can ever leave (2026-10-14, #393).

        ``has_return`` is a SORT/MERGE ``RETURN sd-file``, which reads the
        next sorted record; it does not end the program, so it is no exit.

        Answered once per component (``_FlowIndex.has_escape``): every
        cycle in it shares the answer.
        """
        return index.has_escape(component)

    @staticmethod
    def _call_recursion_risks(ast: CobolProgram) -> list[RecursionRisk]:
        program_name = (ast.program_name or "").strip().upper()
        if not program_name:
            return []

        DynamicCallAnalyzer().analyze(ast)

        # The programs *ast* is nested in, innermost first. Any of them is
        # necessarily active while *ast* runs -- a contained program is only
        # reachable through its container -- so CALLing one re-enters it.
        enclosing: list[CobolProgram] = []
        parent = ast.parent
        while parent is not None:
            if isinstance(parent, CobolProgram):
                enclosing.append(parent)
            parent = parent.parent

        # Every name the program answers to: its PROGRAM-ID and each of its
        # own ``ENTRY 'name'`` points. A CALL to an alternate entry re-enters
        # the same load module just as a CALL to the PROGRAM-ID does (#515).
        own_names = _names_answered_to(ast)
        container_names = [(unit, _names_answered_to(unit)) for unit in enclosing]

        risks: list[RecursionRisk] = []
        for stmt in own_statements(ast):
            if not isinstance(stmt, CallStatement):
                continue
            if stmt.is_dynamic:
                targets = set(callee_names(stmt.possible_values))
            elif stmt.called_program:
                targets = {stmt.called_program.strip("'\"").upper()}
            else:
                targets = set()
            if not own_names & targets:
                container = next(
                    (unit for unit, names in container_names if names & targets),
                    None,
                )
                if container is not None:
                    risks.append(_container_call_risk(stmt, program_name, container))
                continue

            call_kind = "dynamically " if stmt.is_dynamic else ""
            # Name the program's own PROGRAM-ID when the CALL can reach it
            # that way, else the alternate ENTRY it targets.
            via_entry = program_name not in targets
            target_text = (
                f"'{min(own_names & targets)}', an ENTRY point of " f"'{program_name}'"
                if via_entry
                else f"'{program_name}', the program's own PROGRAM-ID"
            )
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
                            f"This CALL {call_kind}targets {target_text}, "
                            "which is declared "
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
                        f"This CALL {call_kind}targets {target_text}. "
                        "COBOL programs are "
                        "non-reentrant by default -- calling yourself, "
                        "directly or via a dynamic value that can resolve to "
                        "your own name, either abends on re-entry or recurses "
                        "without a runtime-enforced bound."
                    ),
                )
            )
        return risks


def _names_answered_to(unit: CobolProgram) -> set[str]:
    """*unit*'s PROGRAM-ID plus every ``ENTRY 'name'`` in its own code,
    unquoted and uppercased (the form CALL targets are compared in)."""
    names: set[str] = set()
    program_name = (unit.program_name or "").strip().upper()
    if program_name:
        names.add(program_name)
    for stmt in own_statements(unit):
        if isinstance(stmt, EntryStatement) and stmt.entry_name:
            name = stmt.entry_name.strip().strip("'\"").strip().upper()
            if name:
                names.add(name)
    return names


def _container_call_risk(
    stmt: CallStatement, program_name: str, container: CobolProgram
) -> RecursionRisk:
    """A contained program CALLing a program it is nested in: indirect
    recursion, since the container is on the call chain whenever the
    contained program runs."""
    container_name = (container.program_name or "").strip().upper()
    call_kind = "dynamically " if stmt.is_dynamic else ""
    if container.is_recursive:
        return RecursionRisk(
            mechanism="CALL",
            severity="LOW",
            program=container_name,
            is_dynamic=stmt.is_dynamic,
            explanation=(
                f"This CALL {call_kind}targets '{container_name}', a program "
                f"'{program_name}' is nested in -- it is always active while "
                f"'{program_name}' runs, so this re-enters it. "
                f"'{container_name}' is declared IS RECURSIVE, so re-entry is "
                "legal; the recursion still needs a base case the analyzer "
                "cannot verify."
            ),
        )
    return RecursionRisk(
        mechanism="CALL",
        severity="HIGH",
        program=container_name,
        is_dynamic=stmt.is_dynamic,
        explanation=(
            f"This CALL {call_kind}targets '{container_name}', a program "
            f"'{program_name}' is nested in -- it is always active while "
            f"'{program_name}' runs, so this re-enters it. "
            f"'{container_name}' is not declared IS RECURSIVE: re-entering a "
            "non-recursive program abends or recurses without a "
            "runtime-enforced bound."
        ),
    )
