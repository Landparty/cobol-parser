"""Regression tests for the 2026-08-16 analyzer-subcommand audit.

Each test class pins one confirmed finding:

* A1 — IOSequenceAnalyzer walked the AST in *source* order, so the canonical
  correct COBOL shape (OPEN/READ in a main paragraph that PERFORMs a
  wrap-up paragraph declared after it) produced CLOSE_NOT_OPEN /
  FILE_LEFT_OPEN / READ_BEFORE_OPEN false positives.
* A2 — CallStatement.set_possible_values used ``list(set(...))``, making
  `analyze`'s JSON ``possible_values`` order vary per process
  (hash randomization).
* A3 — LanguageEnvironmentAnalyzer scanned quoted string literals for
  ``FUNCTION <name>``, so DISPLAY 'FUNCTION KEYS ARE DISABLED' reported a
  fictitious intrinsic function ``KEYS``.
* A4 — IMSSegmentAnalyzer ignored MOVEs to a group SSA's segment-name child
  field; the stale static VALUE won with full confidence.
* A5 — MoveTypeChecker misclassified multi-part alphabetic PICTUREs
  (``AA(3)`` fell through to ALPHANUMERIC, hiding an illegal
  numeric→alphabetic MOVE).
* A6 — MoveTypeChecker treated ``9(5)CR`` as UNKNOWN while the equivalent
  ``9(5)DB`` was NUMERIC_EDITED (only by accident, via the 'B' insertion
  character).
* A7 — TechnicalDebtAnalyzer graded the *unrounded* float score, so a JSON
  score of 10.0 could carry grade "B" against its own A<=10 band.
* A8 — ComplexityAnalyzer collapsed same-named paragraphs in different
  sections, silently dropping the second body's complexity.
* A9 — compute_program_data_items nulled the usage of a PIC-less
  USAGE-only record root (77 X USAGE COMP-1.).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.ims_segment_analyzer import IMSSegmentAnalyzer
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer, IOViolationKind
from cobolparser.analysis.language_env_analyzer import LanguageEnvironmentAnalyzer
from cobolparser.analysis.move_type_checker import MoveTypeChecker
from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer, _grade_for
from cobolparser.layout.offsets import compute_program_data_items


def _parse(source: str):
    result = parse_cobol(source)
    assert result.ast is not None
    return result.ast


class TestA1IoSequenceExecutionOrder:
    def test_close_in_performed_wrapup_paragraph_is_not_a_violation(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOFIX.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT MY-FILE.
           READ MY-FILE.
           PERFORM WRAP-UP.
           STOP RUN.
       WRAP-UP.
           CLOSE MY-FILE.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        assert report.violations == []

    def test_open_in_performed_init_paragraph_declared_last(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOFIX2.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PARA.
           READ MY-FILE.
           CLOSE MY-FILE.
           STOP RUN.
       INIT-PARA.
           OPEN INPUT MY-FILE.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        assert report.violations == []

    def test_perform_thru_range_is_inlined(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOTHRU.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM OPEN-PARA THRU CLOSE-PARA.
           STOP RUN.
       OPEN-PARA.
           OPEN INPUT MY-FILE.
       READ-PARA.
           READ MY-FILE.
       CLOSE-PARA.
           CLOSE MY-FILE.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        assert report.violations == []

    def test_goto_target_is_followed(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOGOTO.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT MY-FILE.
           GO TO FINISH-PARA.
       SKIPPED-PARA.
           READ OTHER-FILE.
       FINISH-PARA.
           CLOSE MY-FILE.
           STOP RUN.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        # MY-FILE lifecycle is clean; SKIPPED-PARA is unreachable so its
        # READ on the never-opened OTHER-FILE is not walked.
        assert report.violations == []

    def test_recursive_perform_terminates(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOREC.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM LOOP-PARA.
           STOP RUN.
       LOOP-PARA.
           OPEN INPUT MY-FILE.
           PERFORM LOOP-PARA.
           CLOSE MY-FILE.
""")
        report = IOSequenceAnalyzer().analyze(ast)  # must not hang
        kinds = {v.kind for v in report.violations}
        # The re-entrant PERFORM is skipped; only the double lifecycle
        # question matters here — no crash, no infinite loop.
        assert IOViolationKind.READ_BEFORE_OPEN not in kinds

    def test_real_violation_still_detected(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOBAD.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           READ MY-FILE.
           STOP RUN.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        assert [v.kind for v in report.violations] == [IOViolationKind.READ_BEFORE_OPEN]

    def test_file_left_open_still_detected_through_perform(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOLEAK.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PARA.
           STOP RUN.
       INIT-PARA.
           OPEN INPUT MY-FILE.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        assert [v.kind for v in report.violations] == [IOViolationKind.FILE_LEFT_OPEN]


class TestA2PossibleValuesDeterministic:
    def test_possible_values_are_sorted(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNSORT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PROG PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGE' TO WS-PROG.
           MOVE 'PROGB' TO WS-PROG.
           MOVE 'PROGD' TO WS-PROG.
           MOVE 'PROGA' TO WS-PROG.
           MOVE 'PROGC' TO WS-PROG.
           CALL WS-PROG.
           STOP RUN.
""")
        from cobolparser.analysis.value_tracker import DynamicCallAnalyzer

        DynamicCallAnalyzer().analyze(ast)
        (call,) = ast.find_all_by_type("CallStatement")
        assert call.possible_values == sorted(call.possible_values)
        assert call.possible_values == [
            "PROGA",
            "PROGB",
            "PROGC",
            "PROGD",
            "PROGE",
        ]


class TestA3FunctionInsideLiteralIsProse:
    def test_string_literals_are_not_scanned_for_function(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEPROSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(30).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'FUNCTION KEYS ARE DISABLED'.
           MOVE 'NO FUNCTION SELECTED' TO WS-MSG.
           STOP RUN.
""")
        result = LanguageEnvironmentAnalyzer().analyze(ast)
        assert result.intrinsic_usages == []
        assert not result.to_dict()["uses_intrinsic_functions"]

    def test_real_function_reference_still_detected(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEREAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10).
       01 WS-Y PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE FUNCTION UPPER-CASE(WS-X) TO WS-Y.
           STOP RUN.
""")
        result = LanguageEnvironmentAnalyzer().analyze(ast)
        names = {u.function_name.upper() for u in result.intrinsic_usages}
        assert "UPPER-CASE" in names


class TestA4IMSMovedSegmentName:
    def test_move_to_ssa_child_field_is_merged_with_static_value(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSMOVE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GU-FUNC PIC X(4) VALUE 'GU  '.
       01 SSA1.
          05 SSA1-SEG-NAME PIC X(8) VALUE 'SEGA    '.
       LINKAGE SECTION.
       01 DB-PCB PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'SEGB    ' TO SSA1-SEG-NAME.
           CALL 'CBLTDLI' USING GU-FUNC DB-PCB IO-AREA SSA1.
           STOP RUN.
""")
        calls = IMSSegmentAnalyzer().analyze(ast)
        assert len(calls) == 1
        # Both the static VALUE and the MOVEd name are candidates, reported
        # via the "/" multi-candidate convention.
        assert calls[0].segment_names == ["SEGA/SEGB"]


class TestA5A6MoveTypePictureClassification:
    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MTPIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM PIC 9(5).
       01 WS-AL5 PIC AA(3).
       01 WS-AMT-CR PIC 9(5)CR.
       01 WS-AMT-DB PIC 9(5)DB.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-NUM TO WS-AL5.
           MOVE WS-AMT-CR TO WS-NUM.
           MOVE WS-AMT-DB TO WS-NUM.
           STOP RUN.
"""

    def test_multi_part_alphabetic_picture_is_alphabetic(self):
        from cobolparser.analysis.move_type_checker import MoveViolationKind

        report = MoveTypeChecker().check(_parse(self.SOURCE))
        errors = [v for v in report.violations if v.kind is MoveViolationKind.ERROR]
        assert any(
            v.target_name == "WS-AL5" and v.target_category.name == "ALPHABETIC"
            for v in errors
        )

    def test_cr_and_db_sign_symbols_classify_identically(self):
        from cobolparser.analysis.move_type_checker import MoveViolationKind

        report = MoveTypeChecker().check(_parse(self.SOURCE))
        warned_sources = {
            v.source_name
            for v in report.violations
            if v.kind is MoveViolationKind.WARNING
        }
        assert {"WS-AMT-CR", "WS-AMT-DB"} <= warned_sources
        # Neither PIC fell through to UNKNOWN.
        assert report.unresolved_count == 0


class TestA7GradeMatchesSerializedScore:
    def test_band_edge_score_grades_from_rounded_value(self):
        # One unused variable, no procedures: redundancy component is
        # exactly 100/3, weighted 30/100 -> raw score 10.000000000000002,
        # which must grade as "A" (the value the JSON prints is 10.0).
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNUSED PIC X.
""")
        report = TechnicalDebtAnalyzer().analyze(ast)
        assert report.to_dict()["score"] == report.score
        assert report.grade == _grade_for(report.score)
        assert (report.score, report.grade) == (10.0, "A")

    def test_no_procedures_components_still_carry_a_finding(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYF.
""")
        report = TechnicalDebtAnalyzer().analyze(ast)
        for component in report.components:
            assert component.findings, f"{component.name} has no findings"


class TestA8SameNamedParagraphs:
    def test_same_named_paragraphs_measured_separately(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMENAME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9.
       PROCEDURE DIVISION.
       SEC-ONE SECTION.
       DO-WORK.
           DISPLAY 'ONE'.
       SEC-TWO SECTION.
       DO-WORK.
           IF WS-A = 1
              IF WS-A = 1
                 IF WS-A = 1
                    DISPLAY 'DEEP'
                 END-IF
              END-IF
           END-IF.
           STOP RUN.
""")
        report = ComplexityAnalyzer().analyze(ast)
        by_key = {p.qualified_name: p for p in report.procedures if p.name == "DO-WORK"}
        # Issue #258: each same-named paragraph is its own flow node now, so
        # each is measured on its own body rather than both summed into one.
        assert set(by_key) == {"DO-WORK OF SEC-ONE", "DO-WORK OF SEC-TWO"}
        assert by_key["DO-WORK OF SEC-ONE"].cyclomatic_complexity == 1
        assert by_key["DO-WORK OF SEC-TWO"].cyclomatic_complexity == 4
        assert by_key["DO-WORK OF SEC-TWO"].max_nesting_depth == 3


class TestA9UsageOnlyRootDataItem:
    def test_pic_less_comp1_root_reports_its_usage(self):
        ast = _parse("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. USAGEROOT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77 WS-ROOT-FLOAT USAGE COMP-1.
       01 WS-REC.
          05 WS-NESTED-FLOAT USAGE COMP-1.
""")
        output = compute_program_data_items(ast)
        by_name = {i["qualified_name"]: i for i in output["items"]}
        root = by_name["WS-ROOT-FLOAT"]
        nested = by_name["WS-REC.WS-NESTED-FLOAT"]
        assert root["usage"] == nested["usage"] == "COMP-1"
        assert root["byte_length"] == 4
