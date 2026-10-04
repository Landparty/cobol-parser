"""Tests for ComplexityAnalyzer (complexity.py).

Covers:
- Straight-line paragraph = complexity 1
- IF (with/without ELSE) adds exactly one decision
- Nested IF increases max_nesting_depth
- EVALUATE counts WHEN arms, excludes WHEN OTHER
- SEARCH counts WHEN arms
- Loop-form PERFORM (UNTIL/TIMES/VARYING) adds a decision; simple PERFORM does not
- Exception-handling clauses (AT END, ON SIZE ERROR) each add a decision
- AND/OR only affects extended_complexity, not cyclomatic_complexity
- GO TO count / goto_density on the program summary
- Fan-in / fan-out derived from real PERFORM/GO TO edges
- SECTION procedures report trivial complexity
- Threshold-based rating and report serialization shape
"""

from cobolparser.analysis.complexity import (
    ComplexityAnalyzer,
    ComplexityThresholds,
)
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPLEXTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 0.
       01 WS-C PIC 9 VALUE 0.
       01 WS-EOF PIC X VALUE 'N'.
       01 WS-IDX PIC 9 VALUE 0.
"""


def _analyze(source: str):
    result = parse_cobol(source, filename="complextest.cbl")
    assert result.ast is not None, result.errors
    return ComplexityAnalyzer().analyze(result.ast)


def _proc(report, name: str):
    matches = [p for p in report.procedures if p.name == name]
    assert matches, f"{name} not found in {[p.name for p in report.procedures]}"
    return matches[0]


class TestStraightLine:
    def test_straight_line_paragraph_is_complexity_one(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "HELLO"
           MOVE 1 TO WS-A
           STOP RUN.
"""
        report = _analyze(source)
        proc = _proc(report, "MAIN-PARA")
        assert proc.cyclomatic_complexity == 1
        assert proc.extended_complexity == 1
        assert proc.max_nesting_depth == 0
        assert proc.rating == "LOW"


class TestIf:
    def test_if_without_else_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2

    def test_if_with_else_still_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           ELSE
               DISPLAY "NOT ONE"
           END-IF
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2

    def test_nested_if_increases_complexity_and_depth(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               IF WS-B = 2
                   DISPLAY "BOTH"
               END-IF
           END-IF
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 3
        assert proc.max_nesting_depth == 2


class TestEvaluate:
    def test_evaluate_counts_when_arms_excludes_when_other(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-A
               WHEN 1
                   DISPLAY "ONE"
               WHEN 2
                   DISPLAY "TWO"
               WHEN 3
                   DISPLAY "THREE"
               WHEN OTHER
                   DISPLAY "OTHER"
           END-EVALUATE
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        # base 1 + 3 WHEN arms (WHEN OTHER excluded)
        assert proc.cyclomatic_complexity == 4

    def test_evaluate_without_when_other(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-A
               WHEN 1
                   DISPLAY "ONE"
               WHEN 2
                   DISPLAY "TWO"
           END-EVALUATE
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 3


class TestSearch:
    def test_search_counts_when_arms(self) -> None:
        source = HEADER + """\
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TABLE.
           05 WS-ENTRY OCCURS 5 TIMES INDEXED BY WS-IX PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ENTRY
               WHEN WS-ENTRY(WS-IX) = 1
                   DISPLAY "FOUND"
           END-SEARCH
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2


class TestPerformLoop:
    def test_simple_perform_target_does_not_add_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA
           STOP RUN.
       WORK-PARA.
           DISPLAY "WORKING".
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 1

    def test_perform_until_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-EOF = 'Y'
               DISPLAY "LOOPING"
               MOVE 'Y' TO WS-EOF
           END-PERFORM
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2

    def test_perform_times_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 3 TIMES
               DISPLAY "LOOPING"
           END-PERFORM
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2

    def test_perform_varying_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-IDX FROM 1 BY 1 UNTIL WS-IDX > 3
               DISPLAY "LOOPING"
           END-PERFORM
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2


class TestExceptionClauses:
    def test_on_size_error_adds_one_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-A
               ON SIZE ERROR
                   DISPLAY "OVERFLOW"
           END-ADD
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2

    def test_on_size_error_and_not_on_size_error_add_two_decisions(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-A
               ON SIZE ERROR
                   DISPLAY "OVERFLOW"
               NOT ON SIZE ERROR
                   DISPLAY "OK"
           END-ADD
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 3

    def test_at_end_clause_adds_one_decision(self) -> None:
        source = HEADER + """\
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-FILE ASSIGN TO "SEQFILE"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD SEQ-FILE.
       01 SEQ-RECORD PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT SEQ-FILE
           READ SEQ-FILE
               AT END MOVE 'Y' TO WS-EOF
           END-READ
           CLOSE SEQ-FILE
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2


class TestExtendedComplexity:
    def test_and_or_only_affects_extended_complexity(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1 AND WS-B = 2 OR WS-C = 3
               DISPLAY "MATCH"
           END-IF
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2
        # 2 boolean operators (AND, OR) on top of the base IF decision
        assert proc.extended_complexity == 4

    def test_no_boolean_operators_keeps_extended_equal_to_cyclomatic(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
"""
        proc = _proc(_analyze(source), "MAIN-PARA")
        assert proc.extended_complexity == proc.cyclomatic_complexity


class TestGotoAndDensity:
    def test_goto_count_and_density(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "A"
           GO TO END-PARA.
       END-PARA.
           DISPLAY "B"
           STOP RUN.
"""
        report = _analyze(source)
        proc = _proc(report, "MAIN-PARA")
        assert proc.goto_count == 1
        assert report.goto_density > 0


class TestGotoDependingOn:
    """Regression for #263: GO TO ... DEPENDING ON is a multi-way branch."""

    def test_goto_depending_on_adds_one_decision_per_target(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       P-GOD.
           GO TO P-ONE P-TWO P-THREE DEPENDING ON WS-A.
           GOBACK.
       P-ONE.
           DISPLAY "1".
       P-TWO.
           DISPLAY "2".
       P-THREE.
           DISPLAY "3".
"""
        report = _analyze(source)
        proc = _proc(report, "P-GOD")
        assert proc.cyclomatic_complexity == 4
        assert proc.extended_complexity == 4
        # GO TO opens no block: nesting depth is unchanged.
        assert proc.max_nesting_depth == 0

    def test_plain_goto_adds_no_decision(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       P-GO.
           GO TO P-ONE.
       P-ONE.
           DISPLAY "1".
"""
        report = _analyze(source)
        assert _proc(report, "P-GO").cyclomatic_complexity == 1


class TestFanInOut:
    def test_fan_in_and_fan_out_from_perform_edges(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA-A
           PERFORM WORK-PARA-B
           STOP RUN.
       WORK-PARA-A.
           PERFORM WORK-PARA-B.
       WORK-PARA-B.
           DISPLAY "SHARED".
"""
        report = _analyze(source)
        main_para = _proc(report, "MAIN-PARA")
        work_b = _proc(report, "WORK-PARA-B")
        assert main_para.fan_out == 2
        # WORK-PARA-B is performed by both MAIN-PARA and WORK-PARA-A
        assert work_b.fan_in == 2


class TestSectionsAndRatings:
    def test_section_reports_trivial_complexity(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
"""
        report = _analyze(source)
        section = _proc(report, "MAIN-SECTION")
        assert section.procedure_type == "SECTION"
        assert section.cyclomatic_complexity == 1
        assert section.extended_complexity == 1
        assert section.max_nesting_depth == 0

    def test_custom_thresholds_change_rating(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
"""
        result = parse_cobol(source, filename="complextest.cbl")
        assert result.ast is not None
        thresholds = ComplexityThresholds(moderate=1, high=3)
        report = ComplexityAnalyzer(thresholds=thresholds).analyze(result.ast)
        proc = _proc(report, "MAIN-PARA")
        assert proc.cyclomatic_complexity == 2
        assert proc.rating == "MODERATE"


class TestReportSerialization:
    def test_to_dict_shape(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
"""
        report = _analyze(source)
        data = report.to_dict()
        assert data["program_name"] == "COMPLEXTEST"
        assert "procedures" in data
        assert "thresholds" in data
        summary = data["summary"]
        for key in (
            "procedure_count",
            "total_complexity",
            "max_complexity",
            "mean_complexity",
            "moderate_count",
            "high_count",
            "goto_density",
        ):
            assert key in summary

    def test_procedure_to_dict_shape(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "HELLO"
           STOP RUN.
"""
        report = _analyze(source)
        proc_dict = report.procedures[0].to_dict()
        for key in (
            "name",
            "type",
            "location",
            "cyclomatic_complexity",
            "extended_complexity",
            "max_nesting_depth",
            "statement_count",
            "goto_count",
            "fan_in",
            "fan_out",
            "rating",
        ):
            assert key in proc_dict


class TestNoProcedureDivision:
    def test_missing_procedure_division_returns_empty_report(self) -> None:
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.models.program import CobolProgram

        prog = CobolProgram("EMPTY", SourceLocation(1, 1))
        report = ComplexityAnalyzer().analyze(prog)
        assert report.procedures == []
        assert report.total_complexity == 0
        assert report.mean_complexity == 0.0
