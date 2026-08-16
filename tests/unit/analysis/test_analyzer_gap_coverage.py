"""Tests for analyzer code paths that previously had no coverage.

Added by the 2026-08-16 analyzer-subcommand audit. Each class targets a
specific untested branch found by coverage analysis:

* ComplexityAnalyzer's INVALID KEY / CALL ON EXCEPTION / STRING ON OVERFLOW
  decision counting, and the precomputed ``flow_report=`` path.
* RecursionRiskAnalyzer's escape-route grading via a branch leaving the
  cycle (not just via a terminating statement), and MIXED cycles.
* RedundancyAnalyzer's EVALUATE fingerprinting (all prior clone tests used
  flat MOVE/DISPLAY paragraphs) and a Type-2 renamed clone of a nested
  control-flow shape.
* TechnicalDebtAnalyzer grade bands beyond A/B, and weight normalization
  when weights do not sum to 100.
* compute_program_data_items on LINKAGE SECTION items (previously only
  WORKING-STORAGE was exercised end-to-end).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer
from cobolparser.analysis.redundancy import RedundancyAnalyzer
from cobolparser.analysis.technical_debt import (
    DebtWeights,
    TechnicalDebtAnalyzer,
    _grade_for,
)
from cobolparser.generators.data.layout_offsets import compute_program_data_items


def _parse(source: str):
    result = parse_cobol(source)
    assert result.ast is not None
    return result.ast


class TestComplexityExceptionClauses:
    def test_invalid_key_call_exception_and_overflow_each_count(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. CPLX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ MY-FILE
              INVALID KEY DISPLAY 'BAD'
           END-READ.
           CALL 'SUB1'
              ON EXCEPTION DISPLAY 'ERR'
           END-CALL.
           STRING 'A' 'B' DELIMITED BY SIZE INTO WS-X
              ON OVERFLOW DISPLAY 'OVR'
           END-STRING.
           STOP RUN.
""")
        report = ComplexityAnalyzer().analyze(ast)
        (main,) = report.procedures
        # 1 + INVALID KEY + ON EXCEPTION + ON OVERFLOW
        assert main.cyclomatic_complexity == 4

    def test_precomputed_flow_report_gives_same_result(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PREFLOW.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA.
           STOP RUN.
       SUB-PARA.
           DISPLAY 'X'.
""")
        flow = ProgramFlowAnalyzer().analyze(ast)
        with_flow = ComplexityAnalyzer().analyze(ast, flow_report=flow)
        without_flow = ComplexityAnalyzer().analyze(ast)
        assert with_flow.to_dict() == without_flow.to_dict()


class TestRecursionRiskEscapeRoutes:
    def test_cycle_with_branch_out_is_medium(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. ESC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-F PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO LOOP-A.
       LOOP-A.
           IF WS-F = 1 GO TO OUT-PARA.
           GO TO LOOP-B.
       LOOP-B.
           GO TO LOOP-A.
       OUT-PARA.
           STOP RUN.
""")
        report = RecursionRiskAnalyzer().analyze(ast)
        gotos = [r for r in report.risks if r.mechanism == "GOTO"]
        assert gotos and all(r.severity == "MEDIUM" for r in gotos)

    def test_mixed_perform_goto_cycle_reported(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIX.
       PROCEDURE DIVISION.
       PARA-A.
           PERFORM PARA-B.
       PARA-B.
           GO TO PARA-A.
""")
        report = RecursionRiskAnalyzer().analyze(ast)
        mechanisms = {r.mechanism for r in report.risks}
        assert "MIXED" in mechanisms
        assert all(r.severity == "HIGH" for r in report.risks if r.mechanism == "MIXED")


class TestRedundancyStructuredClones:
    EVAL_BODY = """           EVALUATE {var}
              WHEN 1 DISPLAY 'ONE'
              WHEN OTHER DISPLAY 'MANY'
           END-EVALUATE.
           MOVE 1 TO {var}.
           DISPLAY 'DONE'.
"""

    def _program(self, var_three: str) -> str:
        return (
            """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLONES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9.
       01 WS-B PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM EVAL-ONE.
           PERFORM EVAL-TWO.
           STOP RUN.
       EVAL-ONE.
"""
            + self.EVAL_BODY.format(var="WS-A")
            + "       EVAL-TWO.\n"
            + self.EVAL_BODY.format(var=var_three)
        )

    def test_identical_evaluate_paragraphs_are_type1_clones(self):
        ast = _parse(self._program("WS-A"))
        report = RedundancyAnalyzer().analyze(ast)
        (group,) = report.clone_groups
        assert group.clone_type == "TYPE_1"
        assert {m.name for m in group.members} == {"EVAL-ONE", "EVAL-TWO"}

    def test_renamed_evaluate_paragraphs_are_type2_clones(self):
        ast = _parse(self._program("WS-B"))
        report = RedundancyAnalyzer().analyze(ast)
        (group,) = report.clone_groups
        assert group.clone_type == "TYPE_2"
        assert {m.name for m in group.members} == {"EVAL-ONE", "EVAL-TWO"}


class TestTechnicalDebtGradesAndWeights:
    def test_grade_bands_beyond_a_and_b(self):
        assert [_grade_for(s) for s in (10.0, 10.01, 25.0, 25.01)] == [
            "A",
            "B",
            "B",
            "C",
        ]
        assert [_grade_for(s) for s in (45.0, 45.01, 70.0, 70.01, 100.0)] == [
            "C",
            "D",
            "D",
            "F",
            "F",
        ]

    def test_weights_not_summing_to_100_normalize(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. WNORM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNUSED PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
""")
        # Same relative weights, different absolute sums — identical score.
        small = TechnicalDebtAnalyzer(
            weights=DebtWeights(complexity=3, redundancy=3, control_flow=3, size=1)
        ).analyze(ast)
        large = TechnicalDebtAnalyzer(
            weights=DebtWeights(complexity=30, redundancy=30, control_flow=30, size=10)
        ).analyze(ast)
        assert small.score == large.score
        assert small.grade == large.grade


class TestDataItemsBeyondWorkingStorage:
    def test_linkage_section_items_are_reported(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. LNK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(4).
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-ID PIC 9(5).
          05 LK-NAME PIC X(10).
       PROCEDURE DIVISION USING LK-REC.
       MAIN-PARA.
           STOP RUN.
""")
        output = compute_program_data_items(ast)
        by_name = {i["qualified_name"]: i for i in output["items"]}
        assert by_name["LK-REC"]["byte_length"] == 15
        assert by_name["LK-REC.LK-ID"]["byte_offset"] == 0
        assert by_name["LK-REC.LK-NAME"]["byte_offset"] == 5
        assert by_name["WS-X"]["byte_length"] == 4
