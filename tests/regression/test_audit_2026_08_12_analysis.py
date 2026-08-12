"""Regression tests for the 2026-08-12 analysis/generators audit fixes.

One test class per finding:

- A-A1: ConstantFolder poisons conditional handler bodies (AT END / INVALID
  KEY / ON SIZE ERROR / ON OVERFLOW / ...) instead of walking past them.
- A-A2 lives in tests/unit/test_flowchart_generator.py (TestExternalCallEndToEnd).
- A-A3: CRUDMatrixGenerator records each file's OWN open mode from
  ``IOOpenStatement.file_modes``, not the statement's first mode group.
- A-A4: ConstantFolder._ordered_paragraphs interleaves sections and
  top-level paragraphs by source line, so PERFORM THRU ranges spanning both
  resolve correctly.
- A-A5: boundary_inventory / constraints nested-statement walks descend into
  on_size_error / not_on_size_error / not_on_overflow / not_at_eop_clause.
- A-A6: domains.NumericDomain.pick() picks on the field's decimal grid so a
  rendered witness can never collapse onto an excluded value.
- A-A7: OPEN/CLOSE boundaries carry status_field, so ScenarioPlanner's
  "OPEN -> FILE STATUS 35" error family can fire.
- A-B1: IOSequenceAnalyzer treats only STOP RUN (not STOP 'literal') as
  program termination.
- A-B2: SQL/CICS/DLI boundary keys are order-independent unique prefixes
  computed against every other same-category site's FULL text.
- A-B3: DynamicCallAnalyzer no longer records an untracked identifier-shaped
  MOVE source as a possible CALL value; it marks the set incomplete instead.
- A-B4: ProgramLayoutIndex refuses to guess between duplicate level-88
  condition names declared under different parent fields.
- A-C1: ProcedureScanner handles a bare/empty SECTION without a stale
  current-procedure side channel (behavior-preserving delete; smoke-tested).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer, IOSequenceAnalyzer
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.analysis.domains import Witness, solve
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.data.layout import FieldCategory, FieldSpec
from cobolparser.generators.data.program_layout import ResolvedField
from cobolparser.generators.scenarios import ScenarioPlanner
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem


def _ast(source: str, filename: str = "audit.cbl"):
    result = parse_cobol(source, filename=filename)
    assert result.ast is not None, result.errors
    return result.ast


def _fold(source: str):
    ast = _ast(source)
    index = ProgramLayoutIndex.build(ast)
    return ConstantFolder().fold(ast, index)


def _boundaries(source: str):
    ast = _ast(source)
    index = ProgramLayoutIndex.build(ast)
    return ast, index, BoundaryInventoryAnalyzer().analyze(ast, index)


class TestA1HandlerBodiesPoisonTheFold:
    """A-A1: a conditional handler body may or may not fire, so every field
    it could write must be poisoned -- 'exact by construction, or absent'."""

    def test_at_end_move_poisons_the_eof_flag(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ATENDPOISON.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'N' TO WS-EOF
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
           DISPLAY WS-EOF
           STOP RUN.
"""
        result = _fold(source)
        # Emitting WS-EOF="N" would be wrong in any scenario where AT END
        # fires; the field must be absent, never guessed.
        assert "WS-EOF" not in result.known

    def test_without_a_handler_the_flag_still_folds(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOHANDLER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'N' TO WS-EOF
           READ F1
           DISPLAY WS-EOF
           STOP RUN.
"""
        result = _fold(source)
        assert result.known.get("WS-EOF") == "N"

    def test_on_size_error_poisons_only_what_the_handler_writes(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIZEERR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 5 TO WS-A
           MOVE 1 TO WS-B
           ADD 1 TO WS-B
               ON SIZE ERROR MOVE 0 TO WS-A
           END-ADD
           DISPLAY WS-A
           DISPLAY WS-B
           STOP RUN.
"""
        result = _fold(source)
        assert "WS-A" not in result.known  # the handler could set it to 0
        assert result.known.get("WS-B") == "2"  # untouched by the handler

    def test_handler_write_to_the_statements_own_target_wins(self):
        # `ADD 1 TO X ON SIZE ERROR MOVE 0 TO X`: the handler poisoning must
        # run AFTER the fold of the ADD itself, or a stale folded value for X
        # would survive.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELFTGT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-X
           ADD 1 TO WS-X
               ON SIZE ERROR MOVE 0 TO WS-X
           END-ADD
           DISPLAY WS-X
           STOP RUN.
"""
        result = _fold(source)
        assert "WS-X" not in result.known


class TestA3OpenModesPerFile:
    """A-A3: `OPEN INPUT IN-FILE OUTPUT OUT-FILE` records each file under
    its own mode group, not the statement's first mode for all files."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPENMODES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE.
           CLOSE IN-FILE OUT-FILE.
           STOP RUN.
"""

    def test_each_file_gets_its_own_mode(self):
        matrix = CRUDMatrixGenerator().analyze(_ast(self.SOURCE))
        modes = {e.file_name: e.open_modes for e in matrix.entries}
        assert modes["IN-FILE"] == ["INPUT"]
        assert modes["OUT-FILE"] == ["OUTPUT"]


class TestA4OrderedParagraphsInterleaveSections:
    """A-A4: PERFORM THRU across a top-level paragraph and a section-owned
    one resolves against a source-ordered list, not sections-first."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERING.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT-PARA THRU P1
           DISPLAY WS-A
           DISPLAY WS-B
           STOP RUN.
       INIT-PARA.
           MOVE 1 TO WS-A.
       SEC-1 SECTION.
       P1.
           MOVE 2 TO WS-B.
"""

    def test_thru_range_spanning_a_section_boundary_folds(self):
        # With the old sections-first ordering, P1 sorted BEFORE INIT-PARA,
        # the THRU range came back empty, and neither MOVE was seen.
        result = _fold(self.SOURCE)
        assert result.known.get("WS-A") == "1"
        assert result.known.get("WS-B") == "2"


class TestA5SizeErrorBodiesAreWalked:
    """A-A5: on_size_error (and the other missing NOT-variant clause
    bodies) are walked by boundary inventory and constraint extraction."""

    def test_call_inside_on_size_error_is_a_boundary(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIZECALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD WS-A TO WS-B
               ON SIZE ERROR CALL 'ERRLOG'
           END-ADD
           STOP RUN.
"""
        _, _, report = _boundaries(source)
        calls = [b for b in report.boundaries if b.ref.category == "CALL"]
        assert [b.ref.key for b in calls] == ["ERRLOG"]

    def test_branch_inside_on_size_error_is_extracted(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIZEBRANCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC X.
       01  WS-A PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-X
           ADD 1 TO WS-A
               ON SIZE ERROR
                   IF WS-X = 'E'
                       DISPLAY 'ERR'
                   END-IF
           END-ADD
           STOP RUN.
"""
        ast, index, report = _boundaries(source)
        creport = ConstraintExtractor().extract(ast, index, report)
        assert any(
            c.field.spec.name == "WS-X"
            for branch in creport.branches
            for arm in branch.arms.values()
            for c in arm
        )


def _numeric_spec(integer_digits: int = 1, decimal_digits: int = 0) -> FieldSpec:
    picture = f"9({integer_digits})" + (
        f"V9({decimal_digits})" if decimal_digits else ""
    )
    return FieldSpec(
        name="WS-N",
        path=("WS-N",),
        column="WS-N",
        level=5,
        picture=picture,
        usage="DISPLAY",
        category=FieldCategory.NUMERIC,
        size=integer_digits + decimal_digits,
        integer_digits=integer_digits,
        decimal_digits=decimal_digits,
        is_signed=False,
        condition_values=[],
    )


def _constraint(spec: FieldSpec, op: str, values: tuple[str, ...]) -> FieldConstraint:
    record = CobolDataItem(name="WS-REC", level=1, location=SourceLocation(1, 1))
    return FieldConstraint(
        field=ResolvedField(spec=spec, section="working_storage", record=record),
        op=op,
        values=values,
        origin="TEST",
    )


class TestA6WitnessOnTheDecimalGrid:
    """A-A6: NumericDomain.pick() picks on the field's own decimal grid, so
    the rendered witness can never round back onto an excluded value."""

    def test_pic_9_ne_4_never_renders_4(self):
        # Old behavior: midpoint of [0, 9] was 4.5, which dodged the
        # float-equality exclusion check and RENDERED (rounded) to "4".
        spec = _numeric_spec(integer_digits=1)
        result = solve(spec, [_constraint(spec, "ne", ("4",))])
        assert isinstance(result, Witness)
        assert result.value != "4"
        assert float(result.value) != 4.0

    def test_decimal_field_witness_is_on_the_grid_and_in_range(self):
        spec = _numeric_spec(integer_digits=2, decimal_digits=2)
        result = solve(
            spec,
            [_constraint(spec, "gt", ("1.25",)), _constraint(spec, "lt", ("1.27",))],
        )
        assert isinstance(result, Witness)
        assert result.value == "1.26"  # the only 10^-2 grid point in range

    def test_decimal_exclusion_is_respected_after_quantization(self):
        spec = _numeric_spec(integer_digits=2, decimal_digits=2)
        result = solve(
            spec,
            [
                _constraint(spec, "ge", ("2.50",)),
                _constraint(spec, "le", ("2.52",)),
                _constraint(spec, "ne", ("2.51",)),
            ],
        )
        assert isinstance(result, Witness)
        assert result.value in ("2.50", "2.52")


class TestA7OpenBoundariesCarryStatusField:
    """A-A7: OPEN (and CLOSE) boundaries resolve the declared FILE STATUS
    field, so the planner's OPEN error-status family can fire."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPENSTAT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           READ F1
               AT END DISPLAY 'EOF'
           END-READ
           CLOSE F1
           STOP RUN.
"""

    def test_open_and_close_boundaries_have_the_status_field(self):
        _, _, report = _boundaries(self.SOURCE)
        by_category = {b.ref.category: b for b in report.boundaries}
        assert by_category["OPEN"].status_field == "WS-FS"
        assert by_category["CLOSE"].status_field == "WS-FS"

    def test_scenario_planner_emits_the_open_error_status_family(self):
        ast, index, report = _boundaries(self.SOURCE)
        creport = ConstraintExtractor().extract(ast, index, report)
        flow = ProgramFlowAnalyzer().analyze(ast)
        plan = ScenarioPlanner().plan(creport, flow, report, mode="all")
        open_error = [
            s for s in plan.scenarios if s.name == "error status: OPEN F1 not found"
        ]
        assert open_error, [s.name for s in plan.scenarios]
        assert open_error[0].status_overrides == {"OPEN:F1": "35"}


class TestB1StopLiteralIsNotTermination:
    """A-B1: STOP 'literal' pauses for the operator and continues; only
    STOP RUN terminates the program for open-file leak detection."""

    def test_stop_literal_between_open_and_read_is_clean(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPLIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           STOP 'OPERATOR PAUSE'
           READ F1
               AT END DISPLAY 'EOF'
           END-READ
           CLOSE F1
           STOP RUN.
"""
        report = IOSequenceAnalyzer().analyze(_ast(source))
        assert report.violations == []

    def test_stop_run_still_flags_files_left_open(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPRUN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           STOP RUN.
"""
        report = IOSequenceAnalyzer().analyze(_ast(source))
        assert [v.kind.name for v in report.violations] == ["FILE_LEFT_OPEN"]


class TestB2ExecKeysAreOrderIndependentPrefixes:
    """A-B2: SQL/CICS/DLI keys are computed against every OTHER site's FULL
    normalized text, so they are order-independent and prefix-unique."""

    def test_two_selects_from_the_same_table_get_distinct_keys(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLKEYS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(5).
       01 WS-B PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL SELECT A INTO :WS-A FROM T END-EXEC.
           EXEC SQL SELECT B INTO :WS-B FROM T END-EXEC.
           STOP RUN.
"""
        _, _, report = _boundaries(source)
        keys = [b.ref.key for b in report.boundaries if b.ref.category == "SQL"]
        assert sorted(keys) == ["SELECT A", "SELECT B"]
        # The first site must not have kept a bare "SELECT" key (a prefix of
        # its sibling's text) just because it was assigned first.
        assert "SELECT" not in keys

    def test_keys_do_not_depend_on_site_order(self):
        template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLORDER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(5).
       01 WS-B PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
{stmts}           STOP RUN.
"""
        first = "           EXEC SQL SELECT A INTO :WS-A FROM T END-EXEC.\n"
        second = "           EXEC SQL SELECT B INTO :WS-B FROM T END-EXEC.\n"

        def keys(stmts: str) -> set[str]:
            _, _, report = _boundaries(template.format(stmts=stmts))
            return {b.ref.key for b in report.boundaries if b.ref.category == "SQL"}

        assert keys(first + second) == keys(second + first)


class TestB3UntrackedIdentifierSourceIsNotAValue:
    """A-B3: `MOVE WS-INPUT-PROG TO WS-TARGET` with an untracked source must
    not record the NAME "WS-INPUT-PROG" as a possible CALL value."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNTRACKED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INPUT-PROG PIC X(8).
       01 WS-TARGET PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-INPUT-PROG TO WS-TARGET
           CALL WS-TARGET
           STOP RUN.
"""

    def _dynamic_call(self, ast):
        return next(c for c in ast.find_statements("CALL") if c.is_dynamic)

    def test_source_name_is_not_recorded_as_a_value(self):
        ast = _ast(self.SOURCE)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(ast)
        assert analyzer.get_variable_values("WS-TARGET") == []
        assert self._dynamic_call(ast).possible_values == []

    def test_target_value_set_is_flagged_incomplete(self):
        ast = _ast(self.SOURCE)
        DynamicCallAnalyzer().analyze(ast)
        call = self._dynamic_call(ast)
        assert call.get_metadata("possible_values_incomplete") is True

    def test_quoted_literal_moves_are_still_tracked_and_complete(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUOTED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TARGET PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'SUBPROG' TO WS-TARGET
           CALL WS-TARGET
           STOP RUN.
"""
        ast = _ast(source)
        DynamicCallAnalyzer().analyze(ast)
        call = self._dynamic_call(ast)
        assert call.possible_values == ["SUBPROG"]
        assert not call.get_metadata("possible_values_incomplete")

    def test_incompleteness_propagates_through_variable_moves(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROPAGATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNKNOWN PIC X(8).
       01 WS-MID PIC X(8).
       01 WS-TARGET PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'REALPROG' TO WS-MID
           MOVE WS-UNKNOWN TO WS-MID
           MOVE WS-MID TO WS-TARGET
           CALL WS-TARGET
           STOP RUN.
"""
        ast = _ast(source)
        DynamicCallAnalyzer().analyze(ast)
        call = self._dynamic_call(ast)
        # The known value still propagates, but the set is flagged as not
        # exhaustive because WS-MID also received an unresolvable value.
        assert call.possible_values == ["REALPROG"]
        assert call.get_metadata("possible_values_incomplete") is True


class TestB4DuplicateConditionNamesAreAmbiguous:
    """A-B4: the same 88 name under two different parent fields must refuse
    to resolve (with an ambiguities entry), not silently keep the last one."""

    def test_duplicate_88_name_refuses_to_guess(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUP88.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC-A.
          05 A-STATUS PIC X.
             88 IS-READY VALUE 'Y'.
       01 REC-B.
          05 B-STATUS PIC X.
             88 IS-READY VALUE 'R'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
        index = ProgramLayoutIndex.build(_ast(source))
        assert index.resolve("IS-READY") is None
        assert index.ambiguities["IS-READY"] == [
            "REC-A.A-STATUS",
            "REC-B.B-STATUS",
        ]

    def test_unique_88_name_still_resolves_to_its_parent(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNIQ88.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC-A.
          05 A-STATUS PIC X.
             88 IS-READY VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
        index = ProgramLayoutIndex.build(_ast(source))
        resolved = index.resolve("IS-READY")
        assert resolved is not None
        assert resolved.spec.name == "A-STATUS"
        assert "IS-READY" not in index.ambiguities


class TestC1EmptySectionScan:
    """A-C1: a bare SECTION header owns no statements; scanning a program
    containing one must neither crash nor misattribute statements."""

    def test_program_with_empty_section_scans_cleanly(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYSEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA
           STOP RUN.
       EMPTY-SEC SECTION.
       WORK-SEC SECTION.
       WORK-PARA.
           DISPLAY 'WORK'.
"""
        report = ProgramFlowAnalyzer().analyze(_ast(source))
        names = {n.name for n in report.nodes}
        assert "WORK-PARA" in names
        work = next(n for n in report.nodes if n.name == "WORK-PARA")
        assert work.statement_count == 1
