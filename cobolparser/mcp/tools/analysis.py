"""Findings over one program: ``lint``, ``business_rules`` and
``diff_programs``."""

from __future__ import annotations

import difflib
from typing import Any

from ..envelope import Response, ToolError, clamp_limit
from ..workspace import ParsedProgram, stdout_to_stderr
from .common import BaseTools, _attempt, _carry_parse_caveats, _worth_showing


class AnalysisTools(BaseTools):
    """``lint``, ``business_rules`` and ``diff_programs``."""

    # -- lint ----------------------------------------------------------------

    def lint(
        self,
        file: str,
        rules: list[str] | None = None,
        min_severity: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Every lint finding in *file*, worst first, each cited on disk."""
        from ...analysis.lint import SEVERITIES, LintAnalyzer, filter_by_severity

        config = self.workspace.config.lint
        # Rule ids and severities are lower-case words, matched as every
        # other enumerated argument here is: "WARNING" is "warning".
        selected = [r.strip().lower() for r in rules or ()] or list(config.rules)
        severity = (min_severity or config.min_severity or "info").strip().lower()
        if severity not in SEVERITIES:
            raise ToolError(
                f"unknown severity {severity!r} (expected one of "
                f"{', '.join(SEVERITIES)})"
            )
        try:
            analyzer = LintAnalyzer(selected or None)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        report, ordered = _run_lint(parsed, analyzer, response)
        findings = filter_by_severity(ordered, severity)
        shown = response.cap(findings, clamp_limit(limit), "findings")
        answer = {
            "rules_run": list(report.rules_run),
            "min_severity": severity,
            "summary": _lint_summary(findings),
            "findings": [_finding(f, parsed, response) for f in shown],
        }
        return response.build(answer, parsed.program_info())

    # -- business_rules ------------------------------------------------------

    def business_rules(
        self,
        file: str,
        program: str | None = None,
        kind: str | None = None,
        procedure: str | None = None,
        include_technical: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The decisions, validations and calculations *file* implements."""
        from ...analysis.business_rules import RULE_KINDS, BusinessRuleExtractor

        wanted_kind = kind.strip().lower() if kind else None
        if wanted_kind is not None and wanted_kind not in RULE_KINDS:
            raise ToolError(
                f"unknown rule kind {kind!r} (expected one of "
                f"{', '.join(RULE_KINDS)})"
            )
        wanted_procedure = " ".join(procedure.split()).upper() if procedure else None
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        name = "rules+technical" if include_technical else "rules"
        report = _attempt(
            response,
            "business rules",
            lambda: parsed.report(
                name,
                unit,
                lambda: BusinessRuleExtractor(
                    include_technical=include_technical
                ).analyze(unit),
            ),
        )
        if report is None:
            return response.build({"found": False, "rules": []}, program_info)
        for caveat in report.caveats:
            response.caveat("incomplete-analysis", caveat)

        rules = [
            rule
            for rule in report.rules
            if (wanted_kind is None or rule.kind == wanted_kind)
            and (
                wanted_procedure is None
                or wanted_procedure
                in {rule.procedure.upper(), (rule.section or "").upper()}
            )
        ]
        cap = clamp_limit(limit)
        shown = response.cap(rules, cap, "rules")
        tested = {name.upper() for rule in shown for name in rule.condition_names}
        answer: dict[str, Any] = {
            "summary": {
                "rules": len(report.rules),
                **{kind: len(report.rules_of_kind(kind)) for kind in RULE_KINDS},
                "technical_rules_excluded": report.technical_rules_excluded,
                "rules_in_dead_code": sum(1 for r in report.rules if r.in_dead_code),
            },
            "rule_count": len(rules),
            "rules": [
                _rule(rule, index, parsed, response, cap)
                for index, rule in enumerate(shown)
            ],
            "condition_names": [
                {"name": c.name, "means": c.condition}
                for c in report.condition_names
                if c.name.upper() in tested
            ],
        }
        if report.technical_rules_excluded and not include_technical:
            answer["note"] = (
                f"{report.technical_rules_excluded} technical rule(s) (FILE "
                "STATUS, end-of-file flags, SQLCODE, EIB fields) are left out; "
                "pass include_technical=true to see them"
            )
        if wanted_procedure is not None and not rules:
            procedures = sorted(
                {r.procedure.upper() for r in report.rules}
                | {(r.section or "").upper() for r in report.rules if r.section}
            )
            answer["suggestions"] = difflib.get_close_matches(
                wanted_procedure, procedures, n=5
            )
        return response.build(answer, program_info)

    # -- diff_programs -------------------------------------------------------

    def diff_programs(
        self,
        old_file: str,
        new_file: str,
        old_program: str | None = None,
        new_program: str | None = None,
        category: str | None = None,
        rename_threshold: float | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """What changed in a program's behaviour between two versions."""
        from ...analysis.ast_diff import ProgramDiffer

        categories = ("program", "file", "data", "procedure")
        wanted = category.strip().lower() if category else None
        if wanted is not None and wanted not in categories:
            raise ToolError(
                f"unknown category {category!r} (expected one of "
                f"{', '.join(categories)})"
            )
        threshold = 0.8 if rename_threshold is None else rename_threshold
        if not 0.0 <= threshold <= 1.0:
            raise ToolError(
                f"rename_threshold must be between 0.0 and 1.0, got {threshold}"
            )
        old = self.workspace.program(old_file)
        new = self.workspace.program(new_file)
        response = Response()
        _carry_parse_caveats(old, response)
        _carry_parse_caveats(new, response)
        old_unit = old.unit(old_program, response)
        new_unit = new.unit(new_program, response)
        answer: dict[str, Any] = {
            "old": old.program_info(old_unit),
            "new": new.program_info(new_unit),
        }
        report = _attempt(
            response,
            "program diff",
            lambda: ProgramDiffer(rename_threshold=threshold).diff(old_unit, new_unit),
        )
        if report is None:
            return response.build(answer)
        for caveat in report.caveats:
            response.caveat("incomplete-analysis", caveat)
        changes = [c for c in report.changes if wanted is None or c.category == wanted]
        shown = response.cap(changes, clamp_limit(limit), "changes")
        answer.update(
            {
                "summary": {
                    "total_changes": report.change_count,
                    "by_category": {
                        key: len(value)
                        for key, value in report.changes_by_category().items()
                    },
                    "by_kind": report.counts_by_kind(),
                },
                "changes": [_change(c, old, new, response) for c in shown],
            }
        )
        if not report.has_changes:
            answer["note"] = (
                "no structural change: the two versions differ at most in "
                "layout, comments, sequence numbers or spacing"
            )
        return response.build(answer)


def _run_lint(
    parsed: ParsedProgram, analyzer: Any, response: Response
) -> tuple[Any, list[Any]]:
    """Lint the whole file: the report and its findings, worst first.

    Worst first, then source order, so a list cut to a limit keeps the
    errors. Failed rules and the report's own caveats go on *response*.
    """
    from ...analysis.lint import SEVERITIES, add_parse_errors

    with stdout_to_stderr():
        report = analyzer.analyze(
            parsed.ast, copybook_item_names=_copybook_item_names(parsed)
        )
    add_parse_errors(report, list(parsed.result.errors))
    for failure in report.failed_rules:
        response.caveat(
            "analyzer-failed",
            f"lint rule {failure['rule']} did not run: {failure['error']}",
            f"no {failure['rule']} findings are reported",
        )
    for caveat in report.caveats:
        response.caveat("incomplete-analysis", caveat)
    rank = {name: i for i, name in enumerate(SEVERITIES)}
    ordered = sorted(
        enumerate(report.findings), key=lambda pair: (rank[pair[1].severity], pair[0])
    )
    return report, [f for _, f in ordered]


def _lint_summary(findings: list[Any]) -> dict[str, int]:
    from ...analysis.lint import SEVERITIES

    summary = {"total": len(findings)}
    for name in SEVERITIES:
        summary[name] = sum(1 for f in findings if f.severity == name)
    return summary


def _finding(f: Any, parsed: ParsedProgram, response: Response) -> dict[str, Any]:
    return {
        "rule": f.rule,
        "severity": f.severity,
        "message": f.message,
        "symbol": f.symbol,
        "kind": f.kind,
        "location": parsed.locate(
            f.location.line if f.location else None,
            f.location.column if f.location else None,
            response,
            column_known=f.column_known,
        ),
    }


def _copybook_item_names(parsed: ParsedProgram) -> set[str] | None:
    """Upper-cased names of data items declared only inside a COPY member.

    What lets lint grade an unused copybook field (every SQLCA field a
    program never reads) as info rather than warning, as the ``lint`` CLI
    does. The CLI finds them by diffing an unexpanded parse; the source map
    already says which file each declaration came from, so no second parse
    is needed. A name the program also declares itself is the program's.
    ``None`` -- "not known" -- when nothing was expanded.
    """
    from ...analysis.unused_variables import collect_declared_items

    if parsed.source_map is None:
        return None
    main = str(parsed.path)
    copied: set[str] = set()
    local: set[str] = set()
    for unit in parsed.ast.program_units():
        for item in collect_declared_items(unit):
            location = getattr(item, "location", None)
            origin = parsed.source_map.get(location.line) if location else None
            if origin is None:
                continue
            (local if origin[0] == main else copied).add(item.name.upper())
    return copied - local


def _rule(
    rule: Any, index: int, parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """One business rule, cited on disk, with its empty fields left out."""
    branches = []
    for number, branch in enumerate(rule.branches):
        actions = response.cap(
            list(branch.actions),
            cap,
            f"rules[{index}].branches[{number}].actions",
        )
        branches.append(
            {
                "label": branch.label,
                "condition": branch.condition,
                "actions": [
                    {
                        key: value
                        for key, value in (
                            ("text", action.text),
                            (
                                "location",
                                parsed.locate(
                                    action.location.line,
                                    None,
                                    response,
                                    column_known=False,
                                ),
                            ),
                            ("rule_id", action.rule_id),
                        )
                        if value is not None
                    }
                    for action in actions
                ],
            }
        )
    result: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "kind": rule.kind,
        "statement": rule.statement,
        "procedure": rule.procedure,
        "section": rule.section,
        "location": parsed.locate(
            rule.location.line, None, response, column_known=False
        ),
        "condition": rule.condition,
        "formula": rule.formula,
        "branches": branches,
        "guards": list(rule.guards),
        "reached_via": list(rule.reached_via),
        "inputs": list(rule.inputs),
        "outputs": list(rule.outputs),
        "classification": list(rule.classification),
        "technical": rule.technical,
        "in_dead_code": rule.in_dead_code,
    }
    # A calculation's condition repeats its formula.
    if rule.formula is not None and rule.condition == rule.formula:
        del result["condition"]
    return {key: value for key, value in result.items() if _worth_showing(value)}


def _change(
    change: Any, old: ParsedProgram, new: ParsedProgram, response: Response
) -> dict[str, Any]:
    """One structural difference, each side cited in its own file."""
    result: dict[str, Any] = {
        "kind": change.kind,
        "category": change.category,
        "symbol": change.symbol,
        "detail": change.detail,
        "old": change.old,
        "new": change.new,
        "old_location": (
            old.locate(change.old_location.line, None, response, column_known=False)
            if change.old_location
            else None
        ),
        "new_location": (
            new.locate(change.new_location.line, None, response, column_known=False)
            if change.new_location
            else None
        ),
    }
    return {key: value for key, value in result.items() if value is not None}
