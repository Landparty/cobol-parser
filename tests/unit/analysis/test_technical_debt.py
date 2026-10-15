"""Tests for TechnicalDebtAnalyzer (technical_debt.py).

Covers:
- A clean, straight-line program scores 0 / grade A
- Each smell (complexity, redundancy, control-flow, size) moves only its
  own component, isolated via zero-weighting the others
- Component contributions, weighted, sum to the reported total score
- Custom DebtWeights are honored
- Top-offenders surfaces the right procedures with the right reasons
- Report serialization shape
"""

from cobolparser.analysis.recursion_risk import RecursionRisk, RecursionRiskReport
from cobolparser.analysis.technical_debt import (
    DebtWeights,
    TechnicalDebtAnalyzer,
)
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEBTTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 0.
"""


def _analyze(source: str, **kwargs):
    result = parse_cobol(source, filename="debttest.cbl")
    assert result.ast is not None, result.errors
    return TechnicalDebtAnalyzer(**kwargs).analyze(result.ast)


def _component(report, name: str):
    for c in report.components:
        if c.name == name:
            return c
    raise AssertionError(f"component {name!r} not found")


CLEAN_SOURCE = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY WS-A
           DISPLAY WS-B
           STOP RUN.
"""


class TestCleanProgram:
    def test_clean_program_scores_zero_grade_a(self) -> None:
        report = _analyze(CLEAN_SOURCE)
        assert report.score == 0.0
        assert report.grade == "A"
        assert report.top_offenders == []

    def test_every_component_present(self) -> None:
        report = _analyze(CLEAN_SOURCE)
        names = {c.name for c in report.components}
        assert names == {"complexity", "redundancy", "control_flow", "size"}


class TestComponentIsolation:
    def test_high_complexity_only_moves_complexity_component(self) -> None:
        # 25 chained IFs push MAIN-PARA's cyclomatic complexity into HIGH.
        conditions = "\n".join(
            f"           IF WS-A = {i}\n               DISPLAY {i}\n           END-IF"
            for i in range(25)
        )
        source = (
            HEADER
            + "       PROCEDURE DIVISION.\n       MAIN-PARA.\n"
            + conditions
            + "\n           STOP RUN.\n"
        )
        weights = DebtWeights(
            complexity=100.0, redundancy=0.0, control_flow=0.0, size=0.0
        )
        report = _analyze(source, weights=weights)
        assert _component(report, "complexity").score > 0
        # Only the complexity component carries weight, so it alone
        # determines the total score, regardless of any other component's
        # own (unweighted) score.
        assert report.score == _component(report, "complexity").score

    def test_dead_code_only_moves_redundancy_component(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        weights = DebtWeights(
            complexity=0.0, redundancy=100.0, control_flow=0.0, size=0.0
        )
        report = _analyze(source, weights=weights)
        assert _component(report, "redundancy").score > 0
        # The composite score is rounded to the 2 decimals to_dict()
        # serializes, so it and the grade always agree.
        assert report.score == round(_component(report, "redundancy").score, 2)

    def test_goto_only_moves_control_flow_component(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO END-PARA.
       END-PARA.
           STOP RUN.
"""
        weights = DebtWeights(
            complexity=0.0, redundancy=0.0, control_flow=100.0, size=0.0
        )
        report = _analyze(source, weights=weights)
        assert _component(report, "control_flow").score > 0
        assert report.score == _component(report, "control_flow").score

    def test_oversized_paragraph_only_moves_size_component(self) -> None:
        moves = "\n".join(f"           MOVE {i} TO WS-A" for i in range(60))
        source = (
            HEADER
            + "       PROCEDURE DIVISION.\n       MAIN-PARA.\n"
            + moves
            + "\n           STOP RUN.\n"
        )
        weights = DebtWeights(
            complexity=0.0, redundancy=0.0, control_flow=0.0, size=100.0
        )
        report = _analyze(source, weights=weights, size_threshold=50)
        assert _component(report, "size").score > 0
        assert report.score == _component(report, "size").score


class TestWeightsAndScore:
    def test_component_contributions_sum_to_total_score(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO END-PARA.
       END-PARA.
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        report = _analyze(source)
        total_weight = report.weights.total
        expected = sum(c.contribution for c in report.components) / total_weight
        # Rounded to 2 decimals before grading (score/grade consistency).
        assert report.score == round(max(0.0, min(100.0, expected)), 2)

    def test_custom_weights_are_honored(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        default_report = _analyze(source)
        zero_redundancy_report = _analyze(
            source,
            weights=DebtWeights(
                complexity=25.0, redundancy=0.0, control_flow=25.0, size=25.0
            ),
        )
        assert zero_redundancy_report.score != default_report.score

    def test_score_bounded_zero_to_hundred(self) -> None:
        report = _analyze(CLEAN_SOURCE)
        assert 0.0 <= report.score <= 100.0


class TestTopOffenders:
    def test_unreachable_self_looping_procedure_is_top_offender(self) -> None:
        # A GO TO to itself gives DeadCodeAnalyzer an incoming edge (it does
        # not special-case self-references), so this paragraph isn't "dead"
        # by that analyzer's own definition -- but it's still unreachable
        # from any entry point and a no-escape recursion cycle, both of
        # which the offender list should surface.
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           GO TO NEVER-CALLED.
"""
        report = _analyze(source)
        offender_names = {o.name for o in report.top_offenders}
        assert "NEVER-CALLED" in offender_names
        never_called = next(o for o in report.top_offenders if o.name == "NEVER-CALLED")
        assert any("unreachable" in r for r in never_called.reasons)
        assert any("recursion cycle" in r for r in never_called.reasons)

    def test_medium_severity_recursion_risk_not_reported_as_no_escape(self) -> None:
        """Regression: a MEDIUM-severity risk (RecursionRiskAnalyzer's own
        grading for a GOTO_LOOP/MIXED cycle that DOES have an escape route)
        must not be surfaced via the "no-escape recursion cycle" reason --
        that text is only accurate for HIGH-severity, no-escape cycles."""
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO END-PARA.
       END-PARA.
           STOP RUN.
"""
        result = parse_cobol(source, filename="debttest.cbl")
        assert result.ast is not None
        medium_recursion_report = RecursionRiskReport(
            risks=[
                RecursionRisk(
                    mechanism="GOTO",
                    severity="MEDIUM",
                    explanation="cycle has an escape route",
                    procedures=["MAIN-PARA"],
                    has_escape=True,
                )
            ]
        )
        report = TechnicalDebtAnalyzer().analyze(
            result.ast, recursion_report=medium_recursion_report
        )
        main_para = next(o for o in report.top_offenders if o.name == "MAIN-PARA")
        assert not any("recursion cycle" in r for r in main_para.reasons)

    def test_dead_paragraph_is_top_offender(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        report = _analyze(source)
        offender_names = {o.name for o in report.top_offenders}
        assert "NEVER-CALLED" in offender_names
        never_called = next(o for o in report.top_offenders if o.name == "NEVER-CALLED")
        assert any("dead code" in r for r in never_called.reasons)

    def test_top_n_limits_results(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       DEAD-A.
           DISPLAY "A"
           STOP RUN.
       DEAD-B.
           DISPLAY "B"
           STOP RUN.
       DEAD-C.
           DISPLAY "C"
           STOP RUN.
"""
        result = parse_cobol(source, filename="debttest.cbl")
        assert result.ast is not None
        report = TechnicalDebtAnalyzer().analyze(result.ast, top_n=1)
        assert len(report.top_offenders) == 1


class TestReportSerialization:
    def test_to_dict_shape(self) -> None:
        report = _analyze(CLEAN_SOURCE)
        data = report.to_dict()
        for key in (
            "program_name",
            "score",
            "grade",
            "weights",
            "components",
            "top_offenders",
            "complexity_summary",
            "redundancy_summary",
        ):
            assert key in data
        assert data["program_name"] == "DEBTTEST"
        assert data["grade"] == "A"

    def test_component_to_dict_shape(self) -> None:
        report = _analyze(CLEAN_SOURCE)
        comp_dict = report.components[0].to_dict()
        for key in ("name", "score", "weight", "findings"):
            assert key in comp_dict


class TestContainedProgramScoping:
    _SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "INNER"
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       P1.
           ALTER P2 TO PROCEED TO P3.
           GO TO P2.
       P2.
           GO TO P3.
       P3.
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""

    def _control_flow(self, unit):
        report = TechnicalDebtAnalyzer().analyze(unit)
        return next(c for c in report.components if c.name == "control_flow")

    def test_nested_programs_alter_is_not_charged_to_its_container(self) -> None:
        result = parse_cobol(self._SOURCE, filename="nested.cbl")
        assert result.ast is not None and not result.errors
        outer = self._control_flow(result.ast)
        assert outer.score == 0.0
        assert not any("ALTER statement" in f for f in outer.findings)

    def test_nested_program_still_counts_its_own_alter(self) -> None:
        result = parse_cobol(self._SOURCE, filename="nested.cbl")
        inner_unit = result.ast.find_program_unit("INNER")
        assert inner_unit is not None
        inner = self._control_flow(inner_unit)
        assert "1 ALTER statement(s) in use" in inner.findings


class TestParseErrorsWithholdTheGrade:
    """Issue #397: a mostly-unparsed program's AST is nearly empty and scores
    as debt-free. Told how many parse errors it came from, the analyzer keeps
    the score but withholds the grade and says why."""

    SOURCE = HEADER + "       PROCEDURE DIVISION.\n       P1.\n           STOP RUN.\n"

    def _ast(self):
        result = parse_cobol(self.SOURCE, filename="debttest.cbl")
        assert result.ast is not None
        return result.ast

    def test_default_has_no_parse_errors(self) -> None:
        report = TechnicalDebtAnalyzer().analyze(self._ast())
        assert report.grade == "A"
        assert report.parse_error_count == 0
        assert report.caveats == []

    def test_parse_errors_withhold_the_grade(self) -> None:
        report = TechnicalDebtAnalyzer().analyze(self._ast(), parse_error_count=4)
        assert report.grade is None
        assert report.parse_error_count == 4
        assert len(report.caveats) == 1
        assert "4 error(s)" in report.caveats[0]

    def test_score_is_kept(self) -> None:
        ast = self._ast()
        clean = TechnicalDebtAnalyzer().analyze(ast)
        broken = TechnicalDebtAnalyzer().analyze(ast, parse_error_count=1)
        assert broken.score == clean.score

    def test_serialized(self) -> None:
        data = (
            TechnicalDebtAnalyzer().analyze(self._ast(), parse_error_count=2).to_dict()
        )
        assert data["grade"] is None
        assert data["parse_error_count"] == 2
        assert data["caveats"]
