"""Unit tests for ConstantFolder (cobolparser.analysis.const_fold).

Phase 7 tier 2 of the `gen-fixtures` initiative. Covers: chains that fold
(MOVE literal/copy, ADD/SUBTRACT/MULTIPLY/COMPUTE), chains poisoned by an
unknown or unmodeled write, GIVING forms (target unmodified, base read from
its own current value), loop/branch write-poisoning, DIVIDE's unconditional
poison, the documented self-reference gap, PERFORM (inline/paragraph/THRU)
chaining, GO TO/STOP RUN stopping the walk, and DISPLAY/WRITE as the only
observation points that make a folded value visible in the result.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.generators.data.program_layout import ProgramLayoutIndex

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FOLDTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(3).
       01  WS-B                PIC 9(3).
       01  WS-TOTAL            PIC 9(4).
       01  WS-SIGNED           PIC S9(3).
       01  WS-NAME             PIC X(5).
       01  WS-FLAG              PIC X.
"""


def _fold(procedure_body: str, extra_data: str = "", seed_values=None):
    source = _HEADER + extra_data + "       PROCEDURE DIVISION.\n" + procedure_body
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    return ConstantFolder().fold(result.ast, index, seed_values=seed_values)


class TestMoveFolding:
    def test_literal_move_observed_at_display(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 42 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "42"}

    def test_chained_copy_move(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 42 TO WS-A.\n"
            "           MOVE WS-A TO WS-B.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-B": "42"}

    def test_move_from_unresolvable_source_poisons_target(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE WS-UNKNOWN-FIELD TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_quoted_text_literal(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'HELLO' TO WS-NAME.\n"
            "           DISPLAY WS-NAME.\n"
        )
        assert fold.known == {"WS-NAME": "HELLO"}

    def test_text_literal_truncates_to_field_size(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'HELLOTHERE' TO WS-NAME.\n"
            "           DISPLAY WS-NAME.\n"
        )
        assert fold.known == {"WS-NAME": "HELLO"}

    def test_numeric_overflow_poisons_rather_than_truncates(self):
        # WS-A is PIC 9(3): 12345 does not fit without truncation, and this
        # module never guesses COBOL's own numeric MOVE truncation rule.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 12345 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_negative_into_unsigned_field_poisons(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE -5 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_negative_into_signed_field_folds(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE -5 TO WS-SIGNED.\n"
            "           DISPLAY WS-SIGNED.\n"
        )
        assert fold.known == {"WS-SIGNED": "-5"}

    def test_numeric_to_text_cross_category_move_poisons(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           MOVE WS-A TO WS-NAME.\n"
            "           DISPLAY WS-NAME.\n"
        )
        assert fold.known == {}

    def test_move_corresponding_poisons_its_targets(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           MOVE CORRESPONDING WS-A TO WS-B.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        # WS-A itself is untouched by the (poisoning) CORRESPONDING move and
        # stays known; WS-B is the corresponding move's target and is poisoned.
        assert fold.known == {"WS-A": "5"}


class TestArithmeticFolding:
    def test_add_accumulate_literal(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           ADD 5 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "15"}

    def test_add_two_operands_giving(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 20 TO WS-B.\n"
            "           ADD WS-A WS-B GIVING WS-TOTAL.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-TOTAL": "30"}

    def test_add_to_giving_does_not_modify_the_to_operand(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 5 TO WS-B.\n"
            "           ADD WS-B TO WS-A GIVING WS-TOTAL.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-A": "10", "WS-TOTAL": "15"}

    def test_subtract_accumulate(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 4 TO WS-B.\n"
            "           SUBTRACT WS-B FROM WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "6"}

    def test_subtract_giving_does_not_modify_the_from_operand(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 4 TO WS-B.\n"
            "           SUBTRACT WS-B FROM WS-A GIVING WS-TOTAL.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-A": "10", "WS-TOTAL": "6"}

    def test_multiply_format_1_reuses_target_as_second_operand(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           MOVE 3 TO WS-B.\n"
            "           MULTIPLY WS-A BY WS-B.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-B": "15"}

    def test_multiply_giving(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           MOVE 3 TO WS-B.\n"
            "           MULTIPLY WS-A BY WS-B GIVING WS-TOTAL.\n"
            "           DISPLAY WS-B.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-B": "3", "WS-TOTAL": "15"}

    def test_divide_is_always_poisoned(self):
        # BY vs INTO is not recorded on the AST, and the two invert
        # dividend/divisor order -- see the module docstring.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 2 TO WS-B.\n"
            "           DIVIDE WS-B INTO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_compute_arithmetic_expression(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           COMPUTE WS-TOTAL = WS-A * 2 + 1.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-TOTAL": "15"}

    def test_compute_with_parentheses_and_division(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 2 TO WS-A.\n"
            "           MOVE 3 TO WS-B.\n"
            "           COMPUTE WS-TOTAL = (WS-A + WS-B) * 2.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-TOTAL": "10"}

    def test_compute_extreme_exponent_poisons_rather_than_crashes(self):
        # A regression guard: decimal.Overflow is not a subclass of the
        # builtin OverflowError, so an earlier, narrower except clause let
        # this crash the whole walk instead of poisoning the target.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           COMPUTE WS-A = 2 ** 99999.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_compute_inexact_division_poisons(self):
        # 1 / 3 has no exact terminating decimal representation in WS-A's
        # picture -- never rounded/truncated silently.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           COMPUTE WS-A = 1 / 3.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_compute_division_by_zero_poisons(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 0 TO WS-B.\n"
            "           COMPUTE WS-A = 10 / WS-B.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_compute_unknown_operand_poisons(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           COMPUTE WS-TOTAL = WS-A + 1.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {}

    def test_rounded_poisons_the_target(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           ADD 5 TO WS-A ROUNDED.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}


class TestAmbiguousSelfReference:
    """A well-formed ADD/SUBTRACT always has >= 1 real addend; `.operands`
    dedups a target's own name against a pre-existing addend of the same
    name, so a wholly self-referencing accumulate is indistinguishable from
    "no addend at all" -- poisoned rather than silently under-computed."""

    def test_add_x_to_x_is_poisoned_not_undercounted(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           ADD WS-A TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_subtract_x_from_x_is_poisoned(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           SUBTRACT WS-A FROM WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}


class TestLoopAndBranchPoisoning:
    def test_perform_until_poisons_only_fields_written_inside(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           PERFORM UNTIL WS-FLAG = 'Y'\n"
            "               ADD 1 TO WS-B\n"
            "               MOVE 'Y' TO WS-FLAG\n"
            "           END-PERFORM.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-A": "7"}

    def test_perform_times_also_poisons_body_writes(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 3 TO WS-B.\n"
            "           PERFORM 3 TIMES\n"
            "               ADD 1 TO WS-B\n"
            "           END-PERFORM.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-A": "7"}

    def test_if_poisons_writes_in_both_arms(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 1 TO WS-B.\n"
            "           IF WS-A > 0\n"
            "               MOVE 99 TO WS-B\n"
            "           ELSE\n"
            "               MOVE 1 TO WS-B\n"
            "           END-IF.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-A": "7"}

    def test_evaluate_poisons_writes_in_every_when_and_other(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 1 TO WS-B.\n"
            "           EVALUATE WS-A\n"
            "               WHEN 1\n"
            "                   MOVE 10 TO WS-B\n"
            "               WHEN OTHER\n"
            "                   MOVE 20 TO WS-B\n"
            "           END-EVALUATE.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-A": "7"}

    def test_nested_perform_inside_if_arm_is_also_poisoned(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 1 TO WS-B.\n"
            "           IF WS-A > 0\n"
            "               PERFORM HELPER\n"
            "           END-IF.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
            "       HELPER.\n"
            "           MOVE 99 TO WS-B.\n"
        )
        assert fold.known == {"WS-A": "7"}


class TestControlFlowStops:
    def test_go_to_stops_the_walk(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           GO TO OTHER-PARA.\n"
            "           MOVE 99 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
            "       OTHER-PARA.\n"
            "           DISPLAY WS-A.\n"
        )
        # The DISPLAY inside OTHER-PARA is never reached by this walk (it is
        # only entered via GO TO, not the entry paragraph's own chain), and
        # the DISPLAY after GO TO in MAIN-PARA is unreachable code -- neither
        # is an observation point, so nothing is ever reported, even though
        # WS-A is "known" internally.
        assert fold.known == {}

    def test_stop_run_stops_the_walk(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           STOP RUN.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}


class TestPerformChaining:
    def test_simple_perform_paragraph_is_walked_inline(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           PERFORM HELPER.\n"
            "           DISPLAY WS-A.\n"
            "       HELPER.\n"
            "           ADD 10 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "15"}

    def test_perform_thru_walks_the_full_range(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           PERFORM STEP-ONE THRU STEP-TWO.\n"
            "           DISPLAY WS-A.\n"
            "       STEP-ONE.\n"
            "           ADD 10 TO WS-A.\n"
            "       STEP-TWO.\n"
            "           ADD 1 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "16"}

    def test_inline_perform_until_is_still_a_loop(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           PERFORM HELPER UNTIL WS-FLAG = 'Y'.\n"
            "           DISPLAY WS-A.\n"
            "       HELPER.\n"
            "           MOVE 99 TO WS-A.\n"
            "           MOVE 'Y' TO WS-FLAG.\n"
        )
        assert fold.known == {}

    def test_non_looping_perform_cycle_does_not_infinite_loop(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           PERFORM PARA-B.\n"
            "           DISPLAY WS-A.\n"
            "       PARA-B.\n"
            "           ADD 1 TO WS-A.\n"
            "           PERFORM PARA-A.\n"
            "       PARA-A.\n"
            "           PERFORM PARA-B.\n"
        )
        # Just needs to terminate; the exact value is secondary to proving
        # the recursion guard stops a non-looping PERFORM cycle.
        assert "WS-A" in fold.known


class TestObservationPoints:
    def test_known_but_never_displayed_or_written_is_not_reported(self):
        fold = _fold("       MAIN-PARA.\n" "           MOVE 42 TO WS-A.\n")
        assert fold.known == {}

    def test_write_of_an_elementary_record_is_an_observation_point(self):
        # A dedicated header (rather than the shared _HEADER + _fold) since
        # an FD/FILE SECTION must precede WORKING-STORAGE SECTION.
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FOLDTEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT F1 ASSIGN TO 'F1.DAT'.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD  F1.\n"
            "       01  F1-REC              PIC 9(3).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 42 TO F1-REC.\n"
            "           WRITE F1-REC.\n"
        )
        result = parse_cobol(source, filename="t.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        fold = ConstantFolder().fold(result.ast, index)
        assert fold.known == {"F1-REC": "42"}

    def test_seed_values_feed_the_walk(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           ADD 1 TO WS-A.\n"
            "           DISPLAY WS-A.\n",
            seed_values={"WS-A": "10"},
        )
        assert fold.known == {"WS-A": "11"}

    def test_seed_values_for_unresolvable_names_are_ignored(self):
        fold = _fold(
            "       MAIN-PARA.\n" "           DISPLAY WS-A.\n",
            seed_values={"NOT-A-REAL-FIELD": "10"},
        )
        assert fold.known == {}

    def test_accept_does_not_poison_its_own_seeded_value(self):
        # Regression: ACCEPT/READ are exactly the boundary categories
        # program_fixtures.py seeds `env` from before the walk starts -- the
        # walker reaching the ACCEPT statement that represents that exact
        # mock-supplied value must not immediately poison it right back out.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           ACCEPT WS-A.\n"
            "           ADD 1 TO WS-A.\n"
            "           DISPLAY WS-A.\n",
            seed_values={"WS-A": "10"},
        )
        assert fold.known == {"WS-A": "11"}

    def test_read_does_not_poison_its_own_seeded_value(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FOLDTEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT F1 ASSIGN TO 'F1.DAT'.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD  F1.\n"
            "       01  F1-QTY               PIC 9(3).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           READ F1.\n"
            "           ADD 1 TO F1-QTY.\n"
            "           DISPLAY F1-QTY.\n"
        )
        result = parse_cobol(source, filename="t.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        fold = ConstantFolder().fold(result.ast, index, seed_values={"F1-QTY": "10"})
        assert fold.known == {"F1-QTY": "11"}
