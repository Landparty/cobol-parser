"""
Composite technical-debt scoring for COBOL programs.

Combines :class:`~.complexity.ComplexityAnalyzer`,
:class:`~.redundancy.RedundancyAnalyzer`, and control-flow smells from
:class:`~.program_flow.ProgramFlowAnalyzer` /
:class:`~.recursion_risk.RecursionRiskAnalyzer` into one 0-100 debt score
("higher = more debt"), a letter grade, and a **top-offenders** list of the
worst procedures with the specific findings that put them there.

Every point on the score traces back to a named finding -- the composite is
a weighted rollup (see :class:`DebtWeights`), never a bare, unexplained
number. The weights are the one honestly arbitrary part of this module; they
are a visible, overridable dataclass rather than buried constants, precisely
so a caller who disagrees with the house default can say so explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolProgram
from .complexity import ComplexityAnalyzer, ComplexityReport
from .program_flow import ProgramFlowAnalyzer, ProgramFlowReport
from .recursion_risk import RecursionRiskAnalyzer, RecursionRiskReport
from .redundancy import RedundancyAnalyzer, RedundancyReport

# Above this many statements, a paragraph counts as oversized for the "size"
# debt component -- a maintainability smell independent of how many branches
# it has (a long, straight-line paragraph is still hard to hold in your head).
_DEFAULT_SIZE_THRESHOLD = 50

_GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (10.0, "A"),
    (25.0, "B"),
    (45.0, "C"),
    (70.0, "D"),
)


def _grade_for(score: float) -> str:
    for cutoff, grade in _GRADE_BANDS:
        if score <= cutoff:
            return grade
    return "F"


@dataclass
class DebtWeights:
    """Relative weight of each debt component.

    Defaults sum to 100 for a directly-readable 0-100 score, but any
    positive weights work -- the composite always normalizes by the sum of
    the weights actually supplied.
    """

    complexity: float = 30.0
    redundancy: float = 30.0
    control_flow: float = 30.0
    size: float = 10.0

    @property
    def total(self) -> float:
        return self.complexity + self.redundancy + self.control_flow + self.size


@dataclass
class ComponentBreakdown:
    """One weighted component of the composite debt score."""

    name: str
    score: float  # 0-100, this component alone
    weight: float
    findings: list[str] = field(default_factory=list)

    @property
    def contribution(self) -> float:
        """This component's share of the final 0-100 score."""
        return self.score * self.weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "weight": self.weight,
            "findings": self.findings,
        }


@dataclass
class OffenderProcedure:
    """A procedure flagged among the worst contributors to program debt."""

    name: str
    location: SourceLocation
    severity: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "location": self.location.to_dict(),
            "severity": round(self.severity, 2),
            "reasons": self.reasons,
        }


@dataclass
class TechnicalDebtReport:
    """Program-wide technical debt report."""

    program_name: str = ""
    score: float = 0.0
    #: ``None`` when the program parsed with errors: the score then measures
    #: only the part of the program the parser recovered, and a letter grade
    #: would read as a verdict on code nobody saw (#397).
    grade: str | None = "A"
    weights: DebtWeights = field(default_factory=DebtWeights)
    components: list[ComponentBreakdown] = field(default_factory=list)
    top_offenders: list[OffenderProcedure] = field(default_factory=list)
    complexity_summary: dict[str, Any] = field(default_factory=dict)
    redundancy_summary: dict[str, Any] = field(default_factory=dict)
    #: Parse errors the analyzed AST was recovered from (``analyze``'s
    #: *parse_error_count*). Nonzero withholds the grade.
    parse_error_count: int = 0
    #: Why the report may not reflect the program, in words.
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "score": round(self.score, 2),
            "grade": self.grade,
            "parse_error_count": self.parse_error_count,
            "caveats": list(self.caveats),
            "weights": {
                "complexity": self.weights.complexity,
                "redundancy": self.weights.redundancy,
                "control_flow": self.weights.control_flow,
                "size": self.weights.size,
            },
            "components": [c.to_dict() for c in self.components],
            "top_offenders": [o.to_dict() for o in self.top_offenders],
            "complexity_summary": self.complexity_summary,
            "redundancy_summary": self.redundancy_summary,
        }


class TechnicalDebtAnalyzer:
    """Computes a composite, explainable technical-debt score.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer

        result = parse_cobol(source)
        report = TechnicalDebtAnalyzer().analyze(result.ast)
        print(f"{report.program_name}: {report.score:.1f} ({report.grade})")
        for o in report.top_offenders:
            print(f"  {o.name}: {', '.join(o.reasons)}")
        ```
    """

    def __init__(
        self,
        weights: DebtWeights | None = None,
        size_threshold: int = _DEFAULT_SIZE_THRESHOLD,
    ) -> None:
        self._weights = weights or DebtWeights()
        self._size_threshold = size_threshold

    def analyze(
        self,
        ast: CobolProgram,
        *,
        flow_report: ProgramFlowReport | None = None,
        complexity_report: ComplexityReport | None = None,
        redundancy_report: RedundancyReport | None = None,
        recursion_report: RecursionRiskReport | None = None,
        top_n: int = 5,
        parse_error_count: int = 0,
    ) -> TechnicalDebtReport:
        """Analyze a COBOL program and compute its technical-debt score.

        Any of the four sub-reports can be passed in precomputed (a caller
        that already ran these analyzers avoids redundant passes over the
        same AST); each is computed fresh when omitted.

        *parse_error_count* is ``len(ParseResult.errors)``. A file that mostly
        failed to parse hands over an AST with almost nothing in it, which
        scores as debt-free; when it is nonzero the score is still computed
        over what was recovered, but ``grade`` is ``None`` and ``caveats``
        says why (#397).
        """
        if flow_report is None:
            flow_report = ProgramFlowAnalyzer().analyze(ast)
        if complexity_report is None:
            complexity_report = ComplexityAnalyzer().analyze(
                ast, flow_report=flow_report
            )
        if redundancy_report is None:
            redundancy_report = RedundancyAnalyzer().analyze(ast)
        if recursion_report is None:
            recursion_report = RecursionRiskAnalyzer().analyze(
                ast, flow_report=flow_report
            )

        weights = self._weights
        components = [
            self._complexity_component(complexity_report, weights),
            self._redundancy_component(redundancy_report, complexity_report, weights),
            self._control_flow_component(
                ast, flow_report, recursion_report, complexity_report, weights
            ),
            self._size_component(complexity_report, weights),
        ]

        total_weight = weights.total
        score = (
            sum(c.contribution for c in components) / total_weight
            if total_weight > 0
            else 0.0
        )
        # Round to the same 2 decimals to_dict() serializes: grading the raw
        # float let accumulated noise (10.000000000000002) push a score the
        # JSON prints as 10.0 across the A/B band edge — the emitted score
        # and grade must always agree.
        score = round(max(0.0, min(100.0, score)), 2)

        top_offenders = self._top_offenders(
            complexity_report,
            redundancy_report,
            flow_report,
            recursion_report,
            top_n,
        )

        caveats: list[str] = []
        if parse_error_count > 0:
            caveats.append(
                f"the program parsed with {parse_error_count} error(s): the "
                "score covers only what the parser recovered, so no grade "
                "is given"
            )

        return TechnicalDebtReport(
            program_name=ast.program_name,
            score=score,
            grade=_grade_for(score) if parse_error_count <= 0 else None,
            parse_error_count=max(0, parse_error_count),
            caveats=caveats,
            weights=weights,
            components=components,
            top_offenders=top_offenders,
            complexity_summary=complexity_report.to_dict()["summary"],
            redundancy_summary=redundancy_report.to_dict()["summary"],
        )

    # -- components ------------------------------------------------------

    @staticmethod
    def _complexity_component(
        report: ComplexityReport, weights: DebtWeights
    ) -> ComponentBreakdown:
        total = len(report.procedures)
        findings: list[str] = []
        if total == 0:
            findings.append("no procedures to rate")
            return ComponentBreakdown("complexity", 0.0, weights.complexity, findings)

        units = report.moderate_count * 1 + report.high_count * 3
        score = min(100.0, 100.0 * units / (3 * total))
        if report.high_count:
            findings.append(f"{report.high_count} procedure(s) rated HIGH complexity")
        if report.moderate_count:
            findings.append(
                f"{report.moderate_count} procedure(s) rated MODERATE complexity"
            )
        if not findings:
            findings.append("no procedures exceed the complexity thresholds")
        return ComponentBreakdown("complexity", score, weights.complexity, findings)

    @staticmethod
    def _redundancy_component(
        report: RedundancyReport,
        complexity_report: ComplexityReport,
        weights: DebtWeights,
    ) -> ComponentBreakdown:
        total_statements = sum(p.statement_count for p in complexity_report.procedures)
        cloned_ratio = (
            min(1.0, report.cloned_statement_count / total_statements)
            if total_statements
            else 0.0
        )
        score = 100.0 * (report.dead_ratio + report.unused_ratio + cloned_ratio) / 3

        findings: list[str] = []
        if report.dead_items:
            findings.append(
                f"{len(report.dead_items)} dead procedure(s) "
                f"({report.dead_ratio:.0%} of all procedures)"
            )
        if report.unused_items:
            findings.append(
                f"{len(report.unused_items)} unused variable(s) "
                f"({report.unused_ratio:.0%} of all declared items)"
            )
        if report.clone_groups:
            findings.append(
                f"{len(report.clone_groups)} duplicate-paragraph clone group(s)"
            )
        if not findings:
            findings.append("no dead code, unused variables, or clones found")
        return ComponentBreakdown("redundancy", score, weights.redundancy, findings)

    @staticmethod
    def _control_flow_component(
        ast: CobolProgram,
        flow_report: ProgramFlowReport,
        recursion_report: RecursionRiskReport,
        complexity_report: ComplexityReport,
        weights: DebtWeights,
    ) -> ComponentBreakdown:
        findings: list[str] = []

        goto_penalty = min(40.0, complexity_report.goto_density * 4)
        if complexity_report.goto_density > 0:
            findings.append(
                f"GO TO density {complexity_report.goto_density:.1f} per 100 statements"
            )

        # This unit's own PROCEDURE DIVISION only: a contained program is a
        # child of the CobolProgram node (not of its divisions), and every
        # other component here is scoped to *ast* alone -- counting a nested
        # program's ALTERs charged them to its container as well as to the
        # nested unit itself (``health --program``, ``scan``).
        procedure = ast.get_division("PROCEDURE")
        alter_count = (
            len(procedure.find_all_by_type("AlterStatement")) if procedure else 0
        )
        alter_penalty = min(30.0, alter_count * 15.0)
        if alter_count:
            findings.append(f"{alter_count} ALTER statement(s) in use")

        high_risks = [r for r in recursion_report.risks if r.severity == "HIGH"]
        recursion_penalty = min(50.0, len(high_risks) * 25.0)
        if high_risks:
            findings.append(f"{len(high_risks)} HIGH-severity recursion risk(s)")

        total_procs = len(complexity_report.procedures)
        unreachable_ratio = (
            len(flow_report.unreachable_nodes) / total_procs if total_procs else 0.0
        )
        unreachable_penalty = min(30.0, 100.0 * unreachable_ratio)
        if flow_report.unreachable_nodes:
            findings.append(
                f"{len(flow_report.unreachable_nodes)} unreachable procedure(s)"
            )

        score = min(
            100.0,
            goto_penalty + alter_penalty + recursion_penalty + unreachable_penalty,
        )
        if not findings:
            findings.append("no GO TO/ALTER/recursion/unreachable-code smells found")
        return ComponentBreakdown("control_flow", score, weights.control_flow, findings)

    def _size_component(
        self, report: ComplexityReport, weights: DebtWeights
    ) -> ComponentBreakdown:
        total = len(report.procedures)
        findings: list[str] = []
        if total == 0:
            findings.append("no procedures to rate")
            return ComponentBreakdown("size", 0.0, weights.size, findings)

        oversized = [
            p for p in report.procedures if p.statement_count > self._size_threshold
        ]
        score = 100.0 * len(oversized) / total
        if oversized:
            findings.append(
                f"{len(oversized)} procedure(s) over {self._size_threshold} statements"
            )
        else:
            findings.append(f"no procedures over {self._size_threshold} statements")
        return ComponentBreakdown("size", score, weights.size, findings)

    # -- top offenders -----------------------------------------------------

    @staticmethod
    def _top_offenders(
        complexity_report: ComplexityReport,
        redundancy_report: RedundancyReport,
        flow_report: ProgramFlowReport,
        recursion_report: RecursionRiskReport,
        top_n: int,
    ) -> list[OffenderProcedure]:
        dead_names = {
            getattr(item, "qualified_name", None) or item.name
            for item in redundancy_report.dead_items
        }
        cloned_names = {
            member.name
            for group in redundancy_report.clone_groups
            for member in group.members
        }
        unreachable_names = set(flow_report.unreachable_nodes)
        # HIGH only: a MEDIUM-severity GOTO_LOOP/MIXED cycle has an escape
        # route (per RecursionRiskAnalyzer's own has_escape grading), so
        # calling it a "no-escape recursion cycle" below would be wrong.
        recursive_names: set[str] = set()
        for risk in recursion_report.risks:
            if risk.mechanism != "CALL" and risk.severity == "HIGH":
                recursive_names.update(risk.procedures)

        offenders: list[OffenderProcedure] = []
        for proc in complexity_report.procedures:
            severity = 0.0
            reasons: list[str] = []
            # Flow keys: "X1 OF S2" for a paragraph sharing its name.
            key = proc.qualified_name or proc.name

            if proc.rating == "HIGH":
                severity += 30
                reasons.append(f"complexity {proc.cyclomatic_complexity} (HIGH)")
            elif proc.rating == "MODERATE":
                severity += 10
                reasons.append(f"complexity {proc.cyclomatic_complexity} (MODERATE)")

            if proc.goto_count:
                severity += proc.goto_count * 3
                reasons.append(f"{proc.goto_count} GO TO(s)")

            if key in dead_names:
                severity += 20
                reasons.append("dead code (unreferenced)")

            if proc.name in cloned_names:
                severity += 15
                reasons.append("member of a duplicate-paragraph clone group")

            if key in unreachable_names:
                severity += 20
                reasons.append("unreachable from any entry point")

            if key in recursive_names:
                severity += 25
                reasons.append("member of a no-escape recursion cycle")

            if severity > 0:
                offenders.append(
                    OffenderProcedure(
                        name=proc.name,
                        location=proc.location,
                        severity=severity,
                        reasons=reasons,
                    )
                )

        offenders.sort(key=lambda o: (-o.severity, o.name))
        return offenders[:top_n]
