"""Tests for LintAnalyzer (lint.py).

Covers:
- Rule selection: default is every rule, an explicit subset is honoured and
  normalized to RULES order, an unknown rule id is rejected rather than
  silently ignored
- Findings carry the rule, severity, message, symbol and location a consumer
  needs, and are ordered by source position with locationless ones last
- Severity grading: per-finding where the underlying analyzer grades itself
  (MOVE ERROR/WARNING), fixed per rule otherwise, and info for an unused item
  that came from a copybook
- Identical findings from one analyzer collapse to one
- A rule that raises is recorded in failed_rules without costing the others
- Coverage caveats (unchecked MOVE operands) reach the report
- filter_by_severity, worst_severity, counts and to_dict shape
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cobolparser.analysis.lint import (
    RULES,
    SEVERITIES,
    LintAnalyzer,
    LintFinding,
    LintReport,
    _deduplicate,
    filter_by_severity,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parser import parse_cobol

# A program with one of nearly everything lint reports: an unused item, a
# lossy MOVE (WARNING), an illegal MOVE (ERROR), and a paragraph nothing
# performs.
PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINTME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNTER        PIC 9(4) VALUE ZERO.
       01  WS-NEVER-USED     PIC X(10).
       01  WS-NAME           PIC X(20).
       01  WS-ALPHA          PIC A(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-NAME TO WS-COUNTER
           MOVE WS-COUNTER TO WS-ALPHA
           PERFORM USED-PARA
           STOP RUN.
       USED-PARA.
           ADD 1 TO WS-COUNTER.
       ORPHAN-PARA.
           DISPLAY 'NEVER PERFORMED'.
"""

# A paragraph that PERFORMs itself: RecursionRiskAnalyzer grades that HIGH
# (no escape route), which lint maps to error.
RECURSIVE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RECPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM LOOP-PARA
           STOP RUN.
       LOOP-PARA.
           ADD 1 TO WS-N
           PERFORM LOOP-PARA.
"""

# Twelve sequential IFs: cyclomatic complexity 13, over the default
# `moderate` threshold of 10 and under `high` (20) -- a MODERATE rating,
# which lint reports as info rather than a warning.
COMPLEX_PROGRAM = (
    """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CPLX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""
    + "".join(
        f"           IF WS-N = {i}\n"
        f"               ADD {i} TO WS-N\n"
        "           END-IF\n"
        for i in range(1, 13)
    )
    + "           STOP RUN.\n"
)

CLEAN_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLEANONE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNTER        PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-COUNTER
           STOP RUN.
"""


# Three program units in one file, each with its own LINKAGE SECTION and
# ENTRY -- enough units that an O(units^2) interface-collection pass (one
# full scope walk per unit's own linkage-check) is distinguishable from an
# O(units) one (one scope walk shared by all three) by a call count.
THREE_UNIT_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-OUTER            PIC X(5).
       PROCEDURE DIVISION USING LK-OUTER.
       OUTER-MAIN.
           CALL 'MIDDLEP' USING LK-OUTER.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIDDLEP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-MIDDLE           PIC X(5).
       PROCEDURE DIVISION USING LK-MIDDLE.
       MIDDLE-MAIN.
           CALL 'INNERP' USING LK-MIDDLE.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-INNER            PIC X(5).
       PROCEDURE DIVISION USING LK-INNER.
       INNER-MAIN.
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM MIDDLEP.
       END PROGRAM OUTERP.
"""


def _ast(source: str = PROGRAM):
    result = parse_cobol(source, filename="lintme.cbl")
    assert result.ast is not None
    return result.ast


def _by_rule(report: LintReport, rule: str) -> list[LintFinding]:
    return [f for f in report.findings if f.rule == rule]


class TestRuleSelection:
    def test_default_runs_every_rule(self) -> None:
        report = LintAnalyzer().analyze(_ast())
        assert report.rules_run == list(RULES)

    def test_explicit_subset_runs_only_those_rules(self) -> None:
        report = LintAnalyzer(["dead-code"]).analyze(_ast())
        assert report.rules_run == ["dead-code"]
        assert {f.rule for f in report.findings} == {"dead-code"}

    def test_selection_is_normalized_to_rules_order(self) -> None:
        # Same set, opposite argument order -> same report, so a caller's
        # --rule ordering can never change the output.
        forward = LintAnalyzer(["dead-code", "complexity"])
        backward = LintAnalyzer(["complexity", "dead-code"])
        assert forward.rules == backward.rules == ("dead-code", "complexity")

    def test_duplicate_rule_ids_collapse(self) -> None:
        assert LintAnalyzer(["dead-code", "dead-code"]).rules == ("dead-code",)

    def test_unknown_rule_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown lint rule"):
            LintAnalyzer(["not-a-rule"])


class TestFindings:
    def test_unused_variable_is_reported_with_its_name(self) -> None:
        report = LintAnalyzer(["unused-variables"]).analyze(_ast())
        assert [f.symbol for f in report.findings] == ["WS-NEVER-USED"]
        finding = report.findings[0]
        assert finding.severity == "warning"
        assert finding.kind == "WORKING-STORAGE"
        assert finding.location is not None
        assert finding.location.line == 6

    def test_dead_paragraph_is_reported(self) -> None:
        report = LintAnalyzer(["dead-code"]).analyze(_ast())
        assert [f.symbol for f in report.findings] == ["ORPHAN-PARA"]
        assert report.findings[0].kind == "PARAGRAPH"
        assert report.findings[0].severity == "warning"

    def test_move_violations_keep_the_checkers_own_grading(self) -> None:
        report = LintAnalyzer(["move-type-check"]).analyze(_ast())
        graded = {f.kind: f.severity for f in report.findings}
        assert graded == {"WARNING": "warning", "ERROR": "error"}

    def test_clean_program_reports_nothing(self) -> None:
        report = LintAnalyzer().analyze(_ast(CLEAN_PROGRAM))
        assert report.findings == []
        assert report.worst_severity() is None
        assert report.failed_rules == []

    def test_findings_are_ordered_by_source_position(self) -> None:
        report = LintAnalyzer().analyze(_ast())
        lines = [f.location.line for f in report.findings if f.location is not None]
        assert lines == sorted(lines)

    def test_locationless_findings_sort_last(self) -> None:
        # A recursion risk describes a cycle across procedures, so it has no
        # single line -- it must not sort ahead of everything at line 0.
        located = LintFinding(
            rule="dead-code",
            severity="warning",
            message="located",
            location=SourceLocation(9, 1),
        )
        floating = LintFinding(
            rule="recursion-check", severity="error", message="floating"
        )
        with (
            patch.object(LintAnalyzer, "_dead_code", return_value=[located]),
            patch.object(LintAnalyzer, "_recursion_check", return_value=[floating]),
        ):
            report = LintAnalyzer(["dead-code", "recursion-check"]).analyze(_ast())
        assert [f.message for f in report.findings] == ["located", "floating"]

    def test_copybook_sourced_unused_item_is_only_informational(self) -> None:
        # Same program, but the caller knows WS-NEVER-USED arrived through a
        # COPY -- a copybook describes a whole record and no one program uses
        # every field of it, so that is not the program's problem.
        report = LintAnalyzer(["unused-variables"]).analyze(
            _ast(), copybook_item_names={"WS-NEVER-USED"}
        )
        assert [f.severity for f in report.findings] == ["info"]


class TestFlowDependentRules:
    def test_a_self_performing_paragraph_is_an_error_on_its_header(self) -> None:
        report = LintAnalyzer(["recursion-check"]).analyze(_ast(RECURSIVE_PROGRAM))
        assert len(report.findings) == 1
        finding = report.findings[0]
        assert finding.severity == "error"
        assert finding.kind == "PERFORM"
        assert finding.symbol == "LOOP-PARA"
        # A cycle spans procedures; it is anchored on its first procedure's
        # header, so an annotation or an inline suppression has a line.
        assert finding.location is not None
        lines = RECURSIVE_PROGRAM.splitlines()
        assert lines[finding.location.line - 1].strip().startswith("LOOP-PARA.")

    def test_a_moderately_complex_paragraph_is_informational(self) -> None:
        report = LintAnalyzer(["complexity"]).analyze(_ast(COMPLEX_PROGRAM))
        assert len(report.findings) == 1
        finding = report.findings[0]
        assert finding.severity == "info"
        assert finding.kind == "MODERATE"
        assert finding.symbol == "MAIN-PARA"
        assert "cyclomatic complexity 13" in finding.message

    def test_a_simple_paragraph_produces_no_complexity_finding(self) -> None:
        # LOW is the common case and says nothing worth a line of output.
        report = LintAnalyzer(["complexity"]).analyze(_ast(CLEAN_PROGRAM))
        assert report.findings == []


class TestDeduplication:
    def test_identical_findings_collapse(self) -> None:
        def finding() -> LintFinding:
            return LintFinding(
                rule="io-sequence",
                severity="error",
                message="READ before OPEN",
                location=SourceLocation(100, 5),
                symbol="EMP-FILE",
                kind="READ_BEFORE_OPEN",
            )

        # Two separately-built objects, not the same one twice: dedup keys on
        # what a consumer can see, not on object identity.
        assert len(_deduplicate([finding(), finding()])) == 1

    def test_findings_differing_only_by_line_are_both_kept(self) -> None:
        first = LintFinding(
            rule="io-sequence",
            severity="error",
            message="READ before OPEN",
            location=SourceLocation(100, 5),
        )
        second = LintFinding(
            rule="io-sequence",
            severity="error",
            message="READ before OPEN",
            location=SourceLocation(120, 5),
        )
        assert len(_deduplicate([first, second])) == 2

    def test_deduplication_preserves_order(self) -> None:
        a = LintFinding(rule="dead-code", severity="warning", message="a")
        b = LintFinding(rule="dead-code", severity="warning", message="b")
        assert [f.message for f in _deduplicate([a, b, a])] == ["a", "b"]


class TestRuleFailureIsolation:
    def test_a_raising_rule_does_not_take_down_the_report(self) -> None:
        with patch.object(LintAnalyzer, "_dead_code", side_effect=RuntimeError("boom")):
            report = LintAnalyzer(["dead-code", "unused-variables"]).analyze(_ast())
        assert report.rules_run == ["unused-variables"]
        assert report.failed_rules == [
            {"rule": "dead-code", "error": "RuntimeError: boom"}
        ]
        # The rule that did run still contributed its findings.
        assert [f.symbol for f in report.findings] == ["WS-NEVER-USED"]


class TestCaveats:
    def test_unchecked_move_operands_are_surfaced(self) -> None:
        # MoveTypeChecker cannot categorize an operand it never saw declared,
        # so "no MOVE findings" here does NOT mean the MOVEs were checked.
        source = PROGRAM.replace(
            "           MOVE WS-NAME TO WS-COUNTER",
            "           MOVE UNDECLARED-FIELD TO WS-COUNTER",
        )
        report = LintAnalyzer(["move-type-check"]).analyze(_ast(source))
        assert any("move-type-check skipped" in c for c in report.caveats)

    def test_function_sources_do_not_blame_a_missing_copy(self) -> None:
        # Issue #291: MOVE FUNCTION TRIM(...) is checked, so no caveat at all.
        source = PROGRAM.replace(
            "           MOVE WS-NAME TO WS-COUNTER",
            "           MOVE FUNCTION TRIM(WS-NAME) TO WS-NAME",
        )
        report = LintAnalyzer(["move-type-check"]).analyze(_ast(source))
        assert report.caveats == []

    def test_uncheckable_function_source_names_the_real_reason(self) -> None:
        source = PROGRAM.replace(
            "           MOVE WS-NAME TO WS-COUNTER",
            "           MOVE FUNCTION NATIONAL-OF(WS-NAME) TO WS-NAME",
        )
        report = LintAnalyzer(["move-type-check"]).analyze(_ast(source))
        assert len(report.caveats) == 1
        assert "intrinsic FUNCTION" in report.caveats[0]
        assert "--copybook-path" not in report.caveats[0]

    def test_both_kinds_of_skipped_move_get_their_own_caveat(self) -> None:
        source = PROGRAM.replace(
            "           MOVE WS-NAME TO WS-COUNTER",
            "           MOVE UNDECLARED-FIELD TO WS-COUNTER\n"
            "           MOVE FUNCTION NUMVAL(WS-NAME) TO WS-NAME",
        )
        report = LintAnalyzer(["move-type-check"]).analyze(_ast(source))
        assert len(report.caveats) == 2
        copybook, function = report.caveats
        assert "skipped 1 MOVE operand(s)" in copybook
        assert "--copybook-path" in copybook
        assert "skipped 1 MOVE operand(s)" in function
        assert "intrinsic FUNCTION" in function
        assert "--copybook-path" not in function

    def test_no_caveats_when_everything_was_checkable(self) -> None:
        report = LintAnalyzer().analyze(_ast(CLEAN_PROGRAM))
        assert report.caveats == []


class TestSeverityHelpers:
    def test_severities_are_ordered_most_severe_first(self) -> None:
        assert SEVERITIES == ("error", "warning", "info")

    @pytest.mark.parametrize(
        ("minimum", "expected"),
        [
            ("error", ["error"]),
            ("warning", ["error", "warning"]),
            ("info", ["error", "warning", "info"]),
        ],
    )
    def test_filter_by_severity(self, minimum: str, expected: list[str]) -> None:
        findings = [
            LintFinding(rule="dead-code", severity=s, message=s) for s in SEVERITIES
        ]
        assert [f.severity for f in filter_by_severity(findings, minimum)] == expected

    def test_filter_rejects_an_unknown_severity(self) -> None:
        with pytest.raises(ValueError, match="unknown severity"):
            filter_by_severity([], "critical")

    def test_worst_severity_is_the_most_severe_present(self) -> None:
        report = LintReport(
            findings=[
                LintFinding(rule="dead-code", severity="warning", message="w"),
                LintFinding(rule="io-sequence", severity="error", message="e"),
            ]
        )
        assert report.worst_severity() == "error"


class TestReportShape:
    def test_to_dict(self) -> None:
        report = LintAnalyzer().analyze(_ast())
        data = report.to_dict()
        assert set(data) == {
            "findings",
            "rules_run",
            "failed_rules",
            "caveats",
            "summary",
        }
        assert data["summary"]["total"] == len(report.findings)
        assert data["summary"]["error"] == report.error_count
        assert data["summary"]["warning"] == report.warning_count
        assert data["summary"]["info"] == report.info_count
        assert data["summary"]["by_rule"] == report.counts_by_rule()
        finding = data["findings"][0]
        assert set(finding) == {
            "rule",
            "severity",
            "message",
            "location",
            "symbol",
            "kind",
        }

    def test_counts_by_rule_covers_every_finding(self) -> None:
        report = LintAnalyzer().analyze(_ast())
        assert sum(report.counts_by_rule().values()) == len(report.findings)


class TestFlowReportReuse:
    def test_a_provided_flow_report_is_not_rebuilt(self) -> None:
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer

        ast = _ast()
        flow_report = ProgramFlowAnalyzer().analyze(ast)
        with patch(
            "cobolparser.analysis.program_flow.ProgramFlowAnalyzer"
        ) as flow_analyzer_class:
            LintAnalyzer(["recursion-check", "complexity"]).analyze(
                ast, flow_report=flow_report
            )
        flow_analyzer_class.assert_not_called()

    def test_the_two_flow_rules_share_one_graph(self) -> None:
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer

        with patch(
            "cobolparser.analysis.program_flow.ProgramFlowAnalyzer",
            wraps=ProgramFlowAnalyzer,
        ) as flow_analyzer_class:
            LintAnalyzer(["recursion-check", "complexity"]).analyze(_ast())
        assert flow_analyzer_class.call_count == 1

    def test_linkage_check_collects_entry_interfaces_once_per_file(self) -> None:
        # Regression: every one of a file's N units' own linkage-check used
        # to redo LinkageChecker.check()'s whole-scope interface collection
        # from scratch (an O(N^2) cost in program units) instead of the
        # single scope-wide pass this now shares across all N. With three
        # units, the walk that visits each unit ONCE (_collect_interfaces)
        # must be called exactly 3 times in total -- not 3*3 = 9.
        from cobolparser.analysis.linkage_checker import LinkageChecker

        with patch.object(
            LinkageChecker,
            "_collect_interfaces",
            wraps=LinkageChecker._collect_interfaces,
            autospec=True,
        ) as collect:
            report = LintAnalyzer(["linkage-check"]).analyze(_ast(THREE_UNIT_PROGRAM))
        assert collect.call_count == 3
        # And the result is unaffected by sharing the collection: no false
        # linkage findings on a file where every CALL matches its callee's
        # declared interface exactly.
        assert _by_rule(report, "linkage-check") == []
