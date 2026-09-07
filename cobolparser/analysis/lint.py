"""
One-pass lint aggregation over the existing per-concern analyzers.

Every analyzer in this package answers one question well and returns its own
report shape -- ``DeadCodeReport.dead_items``, ``MoveTypeReport.violations``,
``ComplexityReport.procedures``, and so on. That is right for a caller who
wants *that* answer, and wrong for the two callers who want "tell me what is
wrong with this program": a CI gate and an editor. Both have to spawn one
process per analyzer today (each re-parsing the same file), then learn seven
different JSON shapes to render one list of problems.

:class:`LintAnalyzer` is that list. It runs a chosen set of rules over one
already-parsed AST and flattens every report into a single stream of
:class:`LintFinding` -- ``rule``, ``severity``, ``message``, ``location``,
``symbol`` -- ordered by source position. Nothing here re-implements any
analysis: each rule is a thin mapping from an existing analyzer's report onto
that shape, so a fix or an improvement in (say) ``move_type_checker.py``
reaches lint output with no change here.

Rule ids are deliberately the *CLI subcommand names* of the analyzers behind
them (``dead-code``, ``move-type-check``, ...) rather than a second private
vocabulary, so ``cobol-parser lint --rule dead-code`` and
``cobol-parser dead-code`` are visibly the same analyzer.

Two properties matter more than breadth here:

- **Severity is per finding, not per rule.** An analyzer that already grades
  its own findings (MOVE's ERROR/WARNING kinds, recursion's HIGH/MEDIUM,
  complexity's LOW/MODERATE/HIGH rating) keeps that grading; the rest carry
  a fixed severity chosen for the rule. ``_SEVERITY_*`` tables below are the
  whole of that policy.
- **A quiet report is not automatically a clean program.** Anything an
  analyzer could not check (MOVE operands whose data category never
  resolved, most often an unresolved COPY) is surfaced in
  :attr:`LintReport.caveats`, and a rule that raised is recorded in
  :attr:`LintReport.failed_rules` instead of taking the rest of the report
  down with it. A caller that gates on ``findings`` alone must still show
  those two lists, or it will report "no problems" for a file that was
  largely unexamined.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolProgram
from .program_flow import ProgramFlowAnalyzer, ProgramFlowReport

# Severity vocabulary, most severe first. Ordering is meaningful: it backs
# --min-severity filtering and --fail-on gating in the CLI.
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

_SEVERITY_RANK: dict[str, int] = {name: rank for rank, name in enumerate(SEVERITIES)}

# Every rule this module can run, in the order findings from a program are
# reported when two land on the same line. The CLI exposes these verbatim as
# --rule values.
RULES: tuple[str, ...] = (
    "dead-code",
    "unused-variables",
    "move-type-check",
    "io-sequence",
    "linkage-check",
    "recursion-check",
    "complexity",
    "dclgen-check",
)

_RULE_ORDER: dict[str, int] = {name: order for order, name in enumerate(RULES)}

# I/O sequencing: every kind but one describes an operation that fails at
# run time (reading a file that was never opened, closing it twice). The
# exception -- a file still open when the program ends -- is a hygiene
# problem, not a failure, since the runtime closes it anyway.
_SEVERITY_IO: dict[str, str] = {
    "READ_BEFORE_OPEN": "error",
    "WRITE_BEFORE_OPEN": "error",
    "REWRITE_BEFORE_OPEN": "error",
    "DELETE_BEFORE_OPEN": "error",
    "START_BEFORE_OPEN": "error",
    "DOUBLE_OPEN": "error",
    "CLOSE_NOT_OPEN": "error",
    "DOUBLE_CLOSE": "error",
    "FILE_LEFT_OPEN": "warning",
}

# LINKAGE: an argument-count mismatch or an unknown entry point is a wrong
# call that will misbehave at run time. A declared-but-unreferenced LINKAGE
# item is only ever suspicious -- a called program is entitled to ignore a
# parameter its caller passes.
_SEVERITY_LINKAGE: dict[str, str] = {
    "TOO_MANY_ARGS": "error",
    "TOO_FEW_ARGS": "error",
    "VALUE_TO_LINKAGE": "error",
    "UNKNOWN_ENTRY": "error",
    "UNREFERENCED_LINKAGE": "warning",
}

# Recursion risk grades itself HIGH when the cycle it found has no escape
# route (an unconditional PERFORM/GO TO loop, or a program that CALLs
# itself) -- that is an infinite loop, not a smell. MEDIUM means an escape
# route exists and the loop terminates if the data ever satisfies it.
_SEVERITY_RECURSION: dict[str, str] = {"HIGH": "error", "MEDIUM": "warning"}

# Complexity is never an error: a 40-branch paragraph is hard to test, not
# wrong. HIGH (above the thresholds' `high` band) is worth a warning, and
# MODERATE is informational. LOW produces no finding at all.
_SEVERITY_COMPLEXITY: dict[str, str] = {"HIGH": "warning", "MODERATE": "info"}


@dataclass
class LintFinding:
    """One problem found in a program, by one rule.

    ``symbol`` is the program name the finding is *about* -- the paragraph,
    data item, file or called program -- not a source excerpt. It is what
    lets a consumer whose line numbers have shifted (an editor holding the
    unexpanded file while the analyzers ran over copybook-expanded text)
    re-anchor the finding by searching for the declaration instead of
    trusting :attr:`location` blindly.
    """

    rule: str
    severity: str
    message: str
    location: SourceLocation | None = None
    symbol: str | None = None
    # Where :attr:`location` really is, when the analyzed text was
    # copybook-expanded: the file on disk and the line in it. Set by
    # :func:`apply_source_map` from the expander's own per-line map, so a
    # consumer no longer has to guess by searching for :attr:`symbol`.
    # ``None`` means no expansion ran (``location`` is already on-disk truth)
    # or the map had nothing for that line.
    origin_file: str | None = None
    origin_line: int | None = None
    # The underlying analyzer's own category for this finding, when it has
    # one (IOViolationKind.READ_BEFORE_OPEN, RecursionRisk.severity, ...).
    # Preserved so a consumer can filter more finely than by rule without
    # parsing `message`.
    kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "location": self.location.to_dict() if self.location else None,
            "symbol": self.symbol,
            "kind": self.kind,
        }
        # Emitted only when it is known, so a consumer can tell "this finding
        # is on line 42 of THIS file" from "nobody mapped it" -- rather than
        # having to treat a defaulted echo of `location` as an answer.
        if self.origin_file is not None or self.origin_line is not None:
            result["origin"] = {"file": self.origin_file, "line": self.origin_line}
        return result


@dataclass
class LintReport:
    """Every finding from one lint run, plus what was and wasn't checked."""

    findings: list[LintFinding] = field(default_factory=list)
    # Rules that actually ran to completion, in RULES order.
    rules_run: list[str] = field(default_factory=list)
    # Rules that raised, as {"rule": ..., "error": ...}. A rule in here
    # contributed no findings; its concern is unexamined.
    failed_rules: list[dict[str, str]] = field(default_factory=list)
    # Human-readable limits on this run's coverage -- see the module
    # docstring. Empty means every rule that ran examined everything it
    # knows how to examine.
    caveats: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")

    def counts_by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule] = counts.get(finding.rule, 0) + 1
        return counts

    def worst_severity(self) -> str | None:
        """The most severe severity present, or None for a clean report."""
        worst: str | None = None
        for finding in self.findings:
            if (
                worst is None
                or _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[worst]
            ):
                worst = finding.severity
        return worst

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "rules_run": list(self.rules_run),
            "failed_rules": list(self.failed_rules),
            "caveats": list(self.caveats),
            "summary": {
                "total": len(self.findings),
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
                "by_rule": self.counts_by_rule(),
            },
        }


def _sort_key(finding: LintFinding) -> tuple[int, int, int, int, str]:
    """Order findings by source position, then by rule, then by message.

    Findings with no location sort *after* every located one (a program-level
    observation belongs at the end of a file-ordered listing, not at line 0
    pretending to be the first problem in the file). The rule and message
    tie-breakers keep the order total, so the same program always yields
    byte-identical output.
    """
    if finding.location is None:
        return (1, 0, 0, _RULE_ORDER.get(finding.rule, len(RULES)), finding.message)
    return (
        0,
        finding.location.line,
        finding.location.column,
        _RULE_ORDER.get(finding.rule, len(RULES)),
        finding.message,
    )


def _deduplicate(findings: list[LintFinding]) -> list[LintFinding]:
    """Drop findings identical to one already in the list.

    An analyzer can legitimately report the same problem twice -- the I/O
    sequence checker reaches one READ down two different paragraph paths and
    reports "READ before OPEN" once per path, for instance. Those are two
    facts about the control flow graph, but only one thing to fix, and every
    field a consumer can see (rule, severity, message, symbol, kind,
    location) is identical, so the second is indistinguishable noise here: an
    editor would stack two identical squiggles on one line and a CI log would
    print the line twice. Order-preserving, so the first occurrence keeps the
    position :func:`_sort_key` gave it.

    Deliberately not pushed down into the analyzers: each of them reports
    what its own analysis found, and collapsing that is this aggregate
    view's choice to make, not a change to what they mean.
    """
    seen: set[tuple[Any, ...]] = set()
    unique: list[LintFinding] = []
    for finding in findings:
        location = finding.location
        key = (
            finding.rule,
            finding.severity,
            finding.message,
            finding.symbol,
            finding.kind,
            (
                None
                if location is None
                else (location.line, location.column, location.length)
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def filter_by_severity(
    findings: list[LintFinding], min_severity: str
) -> list[LintFinding]:
    """Keep only findings at or above *min_severity* (see :data:`SEVERITIES`)."""
    if min_severity not in _SEVERITY_RANK:
        raise ValueError(
            f"unknown severity: {min_severity!r} (expected one of {', '.join(SEVERITIES)})"
        )
    limit = _SEVERITY_RANK[min_severity]
    return [f for f in findings if _SEVERITY_RANK[f.severity] <= limit]


def apply_source_map(
    report: LintReport, source_map: dict[int, tuple[str, int]] | None
) -> LintReport:
    """Stamp every located finding with the file and line it really came from.

    Analyzer locations count lines in whatever text was parsed. When that text
    is the copybook-*expanded* source, a finding after an expanded ``COPY``
    sits well below the line the same code occupies in the file on disk, and
    a finding inside an inlined member does not belong to that file at all.
    ``source_map`` -- the expander's own per-line record, carried on
    ``ParseResult.expansion_source_map`` -- answers both exactly, replacing
    the search-for-the-symbol guesswork every consumer had to do instead.

    A ``None`` map (nothing was expanded) leaves the report untouched: the
    locations are already on-disk truth. So does a line the map does not
    cover; the finding keeps ``origin_file``/``origin_line`` unset rather than
    claiming a line nobody vouched for.

    The report is modified in place and returned, for chaining.
    """
    if not source_map:
        return report
    for finding in report.findings:
        if finding.location is None:
            continue
        origin = source_map.get(finding.location.line)
        if origin is None:
            continue
        finding.origin_file, finding.origin_line = origin
    return report


class LintAnalyzer:
    """Runs several analyzers over one AST and flattens them into findings.

    Args:
        rules: The rule ids to run, defaulting to all of :data:`RULES`. An
            unknown id raises ``ValueError`` rather than being ignored --
            a typo'd ``--rule`` must not read as "that rule found nothing".

    Example:
        >>> report = LintAnalyzer().analyze(ast)              # doctest: +SKIP
        >>> [f.rule for f in report.findings]                 # doctest: +SKIP
        ['move-type-check', 'dead-code']
    """

    def __init__(self, rules: list[str] | tuple[str, ...] | None = None) -> None:
        selected = tuple(RULES) if rules is None else tuple(rules)
        unknown = [r for r in selected if r not in _RULE_ORDER]
        if unknown:
            raise ValueError(
                f"unknown lint rule(s): {', '.join(sorted(unknown))} "
                f"(expected one of {', '.join(RULES)})"
            )
        # Deduplicated and put back into RULES order, so `--rule complexity
        # --rule dead-code` and the reverse produce the same report.
        self._rules = tuple(r for r in RULES if r in set(selected))
        self._flow_cache: tuple[CobolProgram, ProgramFlowReport] | None = None

    @property
    def rules(self) -> tuple[str, ...]:
        return self._rules

    def analyze(
        self,
        ast: CobolProgram,
        *,
        flow_report: ProgramFlowReport | None = None,
        copybook_item_names: set[str] | None = None,
    ) -> LintReport:
        """Run the selected rules over *ast* and return one merged report.

        Args:
            ast: The parsed COBOL program AST.
            flow_report: An already-computed :class:`ProgramFlowReport` to
                reuse. Two rules (``recursion-check``, ``complexity``) need
                the control flow graph; without this they would each build
                their own, walking the same AST twice.
            copybook_item_names: Upper-cased names of data items that
                reached *ast* through an expanded COPY, when the caller
                knows them (the ``lint`` CLI works them out by diffing an
                unexpanded parse). ``unused-variables`` grades a finding on
                one of these as info rather than warning. Omitting it means
                "not known", which grades every unused item as the program's
                own -- never the reverse, so a missing set can only
                over-report, not hide anything.

        A source file with several ``PROGRAM-ID``s parses into one outer
        program carrying the rest as ``contained_programs``; every rule here
        is program-scoped, so each unit is linted on its own and the findings
        are merged. Linting only the outermost unit -- what this did before --
        left a contained program entirely unexamined while reporting a clean
        file.

        Returns:
            A :class:`LintReport`. A rule that raises is recorded in
            ``failed_rules`` and costs only its own findings -- the point of
            a lint pass is to report as much as it can, and one analyzer
            tripping over an exotic program should not blank the other six.
        """
        report = LintReport()
        units = ast.program_units()
        for index, unit in enumerate(units):
            # A caller-supplied flow report describes the outermost unit only;
            # the others build their own.
            self._analyze_unit(
                unit,
                report,
                flow_report=flow_report if index == 0 else None,
                copybook_item_names=copybook_item_names,
            )

        report.findings.sort(key=_sort_key)
        report.findings = _deduplicate(report.findings)
        # Two units that hit the same limit ("a COPY could not be resolved")
        # produce the same caveat text twice; say it once.
        report.caveats = list(dict.fromkeys(report.caveats))
        return report

    def _analyze_unit(
        self,
        ast: CobolProgram,
        report: LintReport,
        *,
        flow_report: ProgramFlowReport | None,
        copybook_item_names: set[str] | None,
    ) -> None:
        """Run every selected rule over one program unit, into *report*."""
        collectors: dict[str, Callable[[], list[LintFinding]]] = {
            "dead-code": lambda: self._dead_code(ast),
            "unused-variables": lambda: self._unused_variables(
                ast, copybook_item_names
            ),
            "move-type-check": lambda: self._move_type_check(ast, report),
            "io-sequence": lambda: self._io_sequence(ast),
            "linkage-check": lambda: self._linkage_check(ast),
            "recursion-check": lambda: self._recursion_check(
                ast, self._flow(ast, flow_report)
            ),
            "complexity": lambda: self._complexity(ast, self._flow(ast, flow_report)),
            "dclgen-check": lambda: self._dclgen_check(ast, report),
        }

        for rule in self._rules:
            try:
                report.findings.extend(collectors[rule]())
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                # One entry per rule however many units it failed on: the
                # reader needs to know the concern went unexamined, not how
                # many times the same exception was raised.
                if not any(f["rule"] == rule for f in report.failed_rules):
                    report.failed_rules.append(
                        {"rule": rule, "error": f"{type(exc).__name__}: {exc}"}
                    )
                continue
            if rule not in report.rules_run:
                report.rules_run.append(rule)

    # -- Shared control flow graph --------------------------------------------

    def _flow(
        self, ast: CobolProgram, provided: ProgramFlowReport | None
    ) -> ProgramFlowReport:
        """The CFG the flow-dependent rules share, built at most once.

        Cached on the instance for the duration of one analyze() call rather
        than passed around, so adding a third flow-dependent rule does not
        mean threading another argument through every collector.
        """
        if provided is not None:
            return provided
        cached = self._flow_cache
        if cached is None or cached[0] is not ast:
            cached = (ast, ProgramFlowAnalyzer().analyze(ast))
            self._flow_cache = cached
        return cached[1]

    # -- Per-rule collectors ---------------------------------------------------

    def _dead_code(self, ast: CobolProgram) -> list[LintFinding]:
        from .dead_code import DeadCodeAnalyzer

        report = DeadCodeAnalyzer().analyze(ast)
        return [
            LintFinding(
                rule="dead-code",
                severity="warning",
                message=f"{item.procedure_type.lower()} {item.name} is never referenced",
                location=item.location,
                symbol=item.name,
                kind=item.procedure_type,
            )
            for item in report.dead_items
        ]

    def _unused_variables(
        self, ast: CobolProgram, copybook_item_names: set[str] | None
    ) -> list[LintFinding]:
        from .unused_variables import UnusedVariableAnalyzer

        result = UnusedVariableAnalyzer().analyze(
            ast, copybook_item_names=copybook_item_names
        )
        findings: list[LintFinding] = []
        for item in result.unused_items:
            findings.append(
                LintFinding(
                    rule="unused-variables",
                    # An unused item the program declares itself is dead
                    # weight its author can delete; one that arrived through
                    # a COPY is normal -- a copybook describes a whole
                    # record and no single program uses every field of it.
                    severity="info" if item.from_copybook else "warning",
                    message=(
                        f"{item.section} item {item.name} (level {item.level:02d}) "
                        "is never referenced in the PROCEDURE DIVISION"
                    ),
                    location=item.location,
                    symbol=item.name,
                    kind=item.section,
                )
            )
        return findings

    def _move_type_check(
        self, ast: CobolProgram, report: LintReport
    ) -> list[LintFinding]:
        from .move_type_checker import MoveTypeChecker

        result = MoveTypeChecker().check(ast)
        if result.unresolved_count:
            report.caveats.append(
                f"move-type-check skipped {result.unresolved_count} MOVE operand(s) whose data "
                "category could not be resolved (most often an unresolved COPY) -- pass "
                "--copybook-path so they can be checked"
            )
        return [
            LintFinding(
                rule="move-type-check",
                severity="error" if v.kind.name == "ERROR" else "warning",
                message=v.message,
                location=v.location,
                symbol=v.source_name,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _io_sequence(self, ast: CobolProgram) -> list[LintFinding]:
        from .io_sequence import IOSequenceAnalyzer

        result = IOSequenceAnalyzer().analyze(ast)
        return [
            LintFinding(
                rule="io-sequence",
                severity=_SEVERITY_IO.get(v.kind.name, "warning"),
                message=v.message,
                location=v.location,
                symbol=v.file_name,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _linkage_check(self, ast: CobolProgram) -> list[LintFinding]:
        from .linkage_checker import LinkageChecker

        result = LinkageChecker().check(ast)
        return [
            LintFinding(
                rule="linkage-check",
                severity=_SEVERITY_LINKAGE.get(v.kind.name, "warning"),
                message=v.message,
                location=v.location,
                symbol=v.call_target,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _recursion_check(
        self, ast: CobolProgram, flow_report: ProgramFlowReport
    ) -> list[LintFinding]:
        from .recursion_risk import RecursionRiskAnalyzer

        result = RecursionRiskAnalyzer().analyze(ast, flow_report=flow_report)
        findings: list[LintFinding] = []
        for risk in result.risks:
            # A risk describes a cycle, not a point -- RecursionRisk carries
            # no location of its own. The cycle's first procedure (or the
            # self-called program) is what a reader needs to find it, and is
            # enough for a consumer to re-anchor by name.
            symbol = (
                risk.program
                if risk.mechanism == "CALL"
                else (risk.procedures[0] if risk.procedures else None)
            )
            findings.append(
                LintFinding(
                    rule="recursion-check",
                    severity=_SEVERITY_RECURSION.get(risk.severity, "warning"),
                    message=risk.explanation,
                    location=None,
                    symbol=symbol,
                    kind=risk.mechanism,
                )
            )
        return findings

    def _complexity(
        self, ast: CobolProgram, flow_report: ProgramFlowReport
    ) -> list[LintFinding]:
        from .complexity import ComplexityAnalyzer

        result = ComplexityAnalyzer().analyze(ast, flow_report=flow_report)
        findings: list[LintFinding] = []
        for proc in result.procedures:
            severity = _SEVERITY_COMPLEXITY.get(proc.rating)
            if severity is None:  # LOW -- nothing to say
                continue
            findings.append(
                LintFinding(
                    rule="complexity",
                    severity=severity,
                    message=(
                        f"{proc.procedure_type.lower()} {proc.name} has cyclomatic complexity "
                        f"{proc.cyclomatic_complexity} ({proc.rating}), nesting depth "
                        f"{proc.max_nesting_depth}, {proc.statement_count} statement(s)"
                    ),
                    location=proc.location,
                    symbol=proc.name,
                    kind=proc.rating,
                )
            )
        return findings

    def _dclgen_check(self, ast: CobolProgram, report: LintReport) -> list[LintFinding]:
        from .dclgen_check import DclgenChecker

        result = DclgenChecker().check(ast)
        # A host variable no DECLARE TABLE speaks for is not a clean one: the
        # DCLGEN block may simply not have been COPY'd into this compile.
        # Said once, with a count, rather than as a finding per variable.
        if result.unchecked:
            report.caveats.append(
                f"dclgen-check: {len(result.unchecked)} host variable(s) could "
                "not be checked against a DECLARE TABLE column -- run "
                "`cobol-parser dclgen-check` for the reason per variable"
            )
        for column, tables in sorted(result.ambiguous_columns.items()):
            report.caveats.append(
                f"dclgen-check: column {column} is declared by "
                f"{', '.join(sorted(tables))}; host variables of that name "
                "were checked against the first"
            )
        return [
            LintFinding(
                rule="dclgen-check",
                severity=violation.severity,
                message=violation.message,
                location=violation.location,
                symbol=violation.host_variable,
                kind=violation.kind,
            )
            for violation in result.violations
        ]
