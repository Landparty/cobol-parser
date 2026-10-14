"""Unit tests for ConstantFolder (cobolparser.analysis.const_fold).

Phase 7 tier 2 of the `gen-fixtures` initiative. Covers: chains that fold
(MOVE literal/copy, ADD/SUBTRACT/MULTIPLY/COMPUTE), chains poisoned by an
unknown or unmodeled write, GIVING forms (target unmodified, base read from
its own current value), loop/branch write-poisoning, DIVIDE's unconditional
poison, self-referencing operands, PERFORM (inline/paragraph/THRU)
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

    def test_divide_into_folds_exact_quotient(self):
        # DivideStatement.division_mode now records BY vs INTO, so the
        # unambiguous forms fold -- see _fold_divide and
        # tests/regression/test_bug_review_2026_08_12.py for the poisoned
        # cases (inexact quotient, ROUNDED, REMAINDER, divide-by-zero).
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-A.\n"
            "           MOVE 2 TO WS-B.\n"
            "           DIVIDE WS-B INTO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "5"}

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


class TestSelfReference:
    """An operand that is also a target or GIVING name is still an addend.
    ``.operands`` dedups those names, so these used to be poisoned (TO/FROM)
    or silently under-counted (GIVING); ``source_operands`` keeps what was
    written before TO/FROM/GIVING. Every expected value was checked against
    GnuCOBOL."""

    def test_add_x_to_x_doubles_it(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           ADD WS-A TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "10"}

    def test_subtract_x_from_x_zeroes_it(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           SUBTRACT WS-A FROM WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "0"}

    def test_add_with_giving_to_one_of_its_own_addends(self):
        # `ADD 7 WS-A GIVING WS-A` is 7 + WS-A, not 7: the GIVING name is an
        # addend too. It used to fold to 7.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           ADD 7 WS-A GIVING WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "12"}

    def test_partial_overlap_is_not_undercounted(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           MOVE 2 TO WS-B.\n"
            "           ADD WS-A, WS-B TO WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "12"}

    def test_subtract_giving_from_its_own_subtrahend(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-A.\n"
            "           SUBTRACT WS-A FROM 20 GIVING WS-A.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {"WS-A": "15"}


class TestFigurativeZeroAndNational:
    def test_move_zero_then_arithmetic_folds(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE ZERO TO WS-A WS-NAME.\n"
            "           MOVE ZEROES TO WS-B.\n"
            "           ADD 3 TO WS-A.\n"
            "           ADD WS-A ZERO GIVING WS-B.\n"
            "           DISPLAY WS-A WS-B WS-NAME.\n"
        )
        assert fold.known == {"WS-A": "3", "WS-B": "3", "WS-NAME": "00000"}

    def test_national_move_truncates_to_characters_not_bytes(self):
        # PIC N(3) is six bytes but three characters.
        fold = _fold(
            "       MAIN-PARA.\n"
            '           MOVE "ABCDEF" TO WS-NAT.\n'
            "           DISPLAY WS-NAT.\n",
            extra_data="       01  WS-NAT              PIC N(3).\n",
        )
        assert fold.known == {"WS-NAT": "ABC"}


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

    def test_sequential_perform_of_the_same_paragraph_walks_both_times(self):
        # Pins the `visiting` add/discard lifetime: a paragraph performed
        # twice in a row (not a cycle -- the second PERFORM starts only
        # after the first has fully returned) must be walked both times,
        # not skipped the second time as if it were still "in progress".
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 0 TO WS-A.\n"
            "           PERFORM HELPER.\n"
            "           PERFORM HELPER.\n"
            "           DISPLAY WS-A.\n"
            "       HELPER.\n"
            "           ADD 10 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "20"}

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

    def test_long_straight_line_perform_chain_does_not_blow_the_stack(self):
        # Regression: `_walk_perform` used to follow a chain of out-of-line
        # PERFORMs by recursing through Python's own call stack, one frame
        # per paragraph -- an ordinary large program (a few hundred chained
        # paragraphs, well under sys.getrecursionlimit()'s default of 1000)
        # was enough to raise an uncaught RecursionError. 2000 paragraphs
        # exercises the fix (an explicit frame stack) well past that.
        n = 2000
        # STOP RUN after the PERFORM: without it, control falls through
        # into PARA-1 and re-walks the chain from every paragraph (#246),
        # which is TestWalkBudget's case, not this one.
        paras = [
            "       MAIN-PARA.\n           MOVE 1 TO WS-A.\n           PERFORM PARA-1.\n"
            "           STOP RUN.\n"
        ]
        for i in range(1, n):
            nxt = i + 1
            if nxt < n:
                paras.append(f"       PARA-{i}.\n           PERFORM PARA-{nxt}.\n")
            else:
                paras.append(f"       PARA-{i}.\n           DISPLAY WS-A.\n")
        fold = _fold("".join(paras))
        assert fold.known == {"WS-A": "1"}

    def test_long_perform_chain_inside_a_loop_body_does_not_blow_the_stack(self):
        # Same regression as above, for `_poison_written_names`'s own
        # PERFORM-chain-following (reached when a loop body performs into a
        # long chain of paragraphs, poisoning what each could write).
        n = 2000
        paras = [
            "       MAIN-PARA.\n"
            "           PERFORM UNTIL WS-FLAG = 'Y'\n"
            "               PERFORM PARA-1\n"
            "           END-PERFORM.\n"
            "           STOP RUN.\n"
        ]
        for i in range(1, n):
            nxt = i + 1
            if nxt < n:
                paras.append(f"       PARA-{i}.\n           PERFORM PARA-{nxt}.\n")
            else:
                paras.append(f"       PARA-{i}.\n           MOVE 1 TO WS-A.\n")
        fold = _fold("".join(paras))
        # Reaching this line without a RecursionError is the point; every
        # field in the poisoned loop body is unknowable by construction.
        assert fold.known == {}


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

    def test_accept_into_reference_modified_target_poisons_rather_than_restores(self):
        # Regression: a subscripted/reference-modified ACCEPT target only
        # writes PART of its base item, unlike the plain-target case in
        # test_accept_does_not_poison_its_own_seeded_value above, so it must
        # be poisoned (forgotten) rather than restored to the seeded value
        # of the WHOLE field.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           ACCEPT WS-NAME(1:2).\n"
            "           DISPLAY WS-NAME.\n",
            seed_values={"WS-NAME": "ABCDE"},
        )
        assert "WS-NAME" not in fold.known

    def test_read_into_reference_modified_target_poisons_rather_than_restores(self):
        # Same regression as above, for READ INTO: only bytes 1-5 of
        # WS-BUFFER are actually written by this READ, so the whole field
        # must not be asserted as the seeded value.
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
            "       01  F1-REC                PIC X(10).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  WS-BUFFER             PIC X(20).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           READ F1 INTO WS-BUFFER(1:5).\n"
            "           DISPLAY WS-BUFFER.\n"
        )
        result = parse_cobol(source, filename="t.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        fold = ConstantFolder().fold(
            result.ast, index, seed_values={"WS-BUFFER": "X" * 20}
        )
        assert "WS-BUFFER" not in fold.known


class TestToDict:
    def test_known_dict_round_trips(self):
        fold = _fold("           MOVE 5 TO WS-A.\n" "           DISPLAY WS-A.\n")
        assert fold.to_dict() == {"known": {"WS-A": "5"}}
        # to_dict() must be a copy, not an alias, of the internal dict.
        fold.to_dict()["known"]["WS-A"] = "mutated"
        assert fold.known["WS-A"] == "5"


class TestLoopVariablesAndAliases:
    """Writes that hide outside a statement's body/operands: PERFORM VARYING
    / AFTER counters, SEARCH VARYING, and a level-66 RENAMES alias."""

    def test_inline_perform_varying_poisons_its_loop_variable(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 5 TO WS-B.\n"
            "           PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3\n"
            "               CONTINUE\n"
            "           END-PERFORM.\n"
            "           DISPLAY WS-A WS-B.\n"
        )
        # WS-A ends at 4, never at its pre-loop 7; WS-B is untouched.
        assert fold.known == {"WS-B": "5"}

    def test_out_of_line_perform_varying_poisons_its_loop_variable(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           PERFORM HELPER VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       HELPER.\n"
            "           CONTINUE.\n"
        )
        assert fold.known == {}

    def test_perform_varying_after_poisons_every_loop_variable(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           MOVE 7 TO WS-B.\n"
            "           PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3\n"
            "                   AFTER WS-B FROM 1 BY 1 UNTIL WS-B > 2\n"
            "               CONTINUE\n"
            "           END-PERFORM.\n"
            "           DISPLAY WS-A WS-B.\n"
        )
        assert fold.known == {}

    def test_perform_varying_nested_in_an_if_arm_poisons_its_loop_variable(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           IF WS-FLAG = 'Y'\n"
            "               PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3\n"
            "                   CONTINUE\n"
            "               END-PERFORM\n"
            "           END-IF.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_search_varying_poisons_its_varying_variable(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-A.\n"
            "           SEARCH WS-E VARYING WS-A AT END CONTINUE\n"
            "               WHEN WS-E (IX) = 'A' CONTINUE\n"
            "           END-SEARCH.\n"
            "           DISPLAY WS-A.\n",
            extra_data=(
                "       01  WS-T.\n"
                "           05  WS-E PIC X OCCURS 3 INDEXED BY IX.\n"
            ),
        )
        assert fold.known == {}

    def test_write_through_renames_alias_poisons_the_covered_leaves(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'AA' TO WS-G.\n"
            "           MOVE 'XY' TO WS-H.\n"
            "           MOVE 'ZZ' TO WS-I.\n"
            "           MOVE 'BB' TO WS-J.\n"
            "           MOVE 'PQRS' TO WS-RN.\n"
            "           DISPLAY WS-G WS-H WS-I WS-J.\n",
            extra_data=(
                "       01  WS-GRP.\n"
                "           05  WS-G PIC X(2).\n"
                "           05  WS-H PIC X(2).\n"
                "           05  WS-I PIC X(2).\n"
                "           05  WS-J PIC X(2).\n"
                "       66  WS-RN RENAMES WS-H THRU WS-I.\n"
            ),
        )
        # Only WS-H..WS-I share the alias's bytes; WS-G / WS-J stay known.
        assert fold.known == {"WS-GRP.WS-G": "AA", "WS-GRP.WS-J": "BB"}

    def test_single_operand_renames_alias_poisons_its_field(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'XY' TO WS-H.\n"
            "           MOVE 'PQ' TO WS-RN.\n"
            "           DISPLAY WS-H.\n",
            extra_data=(
                "       01  WS-GRP.\n"
                "           05  WS-H PIC X(2).\n"
                "       66  WS-RN RENAMES WS-H.\n"
            ),
        )
        assert fold.known == {}


_ALIASING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALIASES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'F.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R1.
          05 A PIC X(4).
       01 R2.
          05 B PIC 9(4).
       WORKING-STORAGE SECTION.
       01 X5 PIC X(5).
       01 J3 PIC X(3) JUSTIFIED RIGHT.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _fold_aliasing(procedure_body: str):
    result = parse_cobol(_ALIASING_SOURCE + procedure_body, filename="t.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    return ConstantFolder().fold(result.ast, index, seed_values={})


class TestStorageAliasing:
    """Issue #245: three ways two names share storage that the folder used
    to miss, each producing a `field_equals` value the program never held."""

    def test_sibling_fd_records_share_one_record_area(self):
        # Every 01 under one FD implicitly redefines the same area: writing
        # A overwrites B's bytes.
        fold = _fold_aliasing(
            "           MOVE 1234 TO B.\n"
            "           MOVE 'ABCD' TO A.\n"
            "           DISPLAY B.\n"
        )
        assert "R2.B" not in fold.known

    def test_sibling_fd_record_alias_does_not_poison_unrelated_storage(self):
        fold = _fold_aliasing(
            "           MOVE 'ABCDE' TO X5.\n"
            "           MOVE 'ABCD' TO A.\n"
            "           DISPLAY X5.\n"
        )
        assert fold.known == {"X5": "ABCDE"}

    def test_write_from_moves_the_source_into_the_record_first(self):
        fold = _fold_aliasing(
            "           MOVE 'AB' TO A.\n"
            "           MOVE 'ZZZZZ' TO X5.\n"
            "           WRITE R1 FROM X5.\n"
            "           DISPLAY A.\n"
        )
        assert "R1.A" not in fold.known

    def test_rewrite_from_also_overwrites_the_record(self):
        fold = _fold_aliasing(
            "           MOVE 'AB' TO A.\n"
            "           MOVE 'ZZZZZ' TO X5.\n"
            "           REWRITE R1 FROM X5.\n"
            "           DISPLAY A.\n"
        )
        assert "R1.A" not in fold.known

    def test_justified_right_keeps_the_rightmost_of_the_padded_source(self):
        # X5 holds "ABCD " (space-padded to five), so J3 receives "CD ".
        fold = _fold_aliasing(
            "           MOVE 'ABCD' TO X5.\n"
            "           MOVE X5 TO J3.\n"
            "           DISPLAY J3.\n"
        )
        assert fold.known.get("J3") == "CD "

    def test_justified_right_from_a_full_width_source_is_unchanged(self):
        fold = _fold_aliasing(
            "           MOVE 'ABCDE' TO X5.\n"
            "           MOVE X5 TO J3.\n"
            "           DISPLAY J3.\n"
        )
        assert fold.known.get("J3") == "CDE"


class TestValueAtObservationPoint:
    """Issue #246: a `field_equals` value is what the DISPLAY/WRITE emitted
    (decision (a) in the issue), and the walk follows control as it falls
    through from the entry paragraph into the next one."""

    _DATA = "       01  N3                  PIC S9(3).\n"

    def test_value_is_taken_at_the_display_not_at_the_end_of_the_walk(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "           MOVE 2 TO N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        assert fold.known == {"N3": "1"}

    def test_two_sites_observing_different_values_drop_the_field(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "           MOVE 2 TO N3.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        assert "N3" not in fold.known

    def test_two_sites_observing_the_same_value_keep_it(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        assert fold.known == {"N3": "1"}

    def test_a_site_where_the_value_is_unknown_drops_the_field(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "           MOVE WS-UNKNOWN TO N3.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        assert "N3" not in fold.known

    def test_control_falls_through_into_the_next_paragraph(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "       NEXT-PARA.\n"
            "           MOVE 2 TO N3.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        # The program displays 1 then 2: no single value is right.
        assert "N3" not in fold.known

    def test_fall_through_reaches_a_display_only_the_next_paragraph_makes(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO N3.\n"
            "       NEXT-PARA.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n",
            extra_data=self._DATA,
        )
        assert fold.known == {"N3": "7"}

    def test_stop_run_in_the_entry_paragraph_ends_the_walk(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO N3.\n"
            "           DISPLAY N3.\n"
            "           STOP RUN.\n"
            "       NEXT-PARA.\n"
            "           MOVE 2 TO N3.\n"
            "           DISPLAY N4.\n",
            extra_data=self._DATA
            + "       01  N4                  PIC S9(3) VALUE 4.\n",
        )
        # NEXT-PARA is never walked: its MOVE does not leak into N3, and
        # N4, shown only there, is not claimed.
        assert fold.known == {"N3": "1"}


class TestWalkBudget:
    """Fall-through (#246) follows real control flow, so a chain of
    paragraphs that each PERFORM the next and never STOP RUN is re-walked
    from every paragraph -- quadratic. Past `_MAX_WALK_STEPS` the fold
    gives up and reports nothing, quickly, instead of a partial answer."""

    def test_quadratic_fall_through_chain_reports_nothing(self):
        n = 2000
        paras = [
            "       MAIN-PARA.\n           MOVE 1 TO WS-A.\n           PERFORM PARA-1.\n"
        ]
        for i in range(1, n):
            nxt = i + 1
            if nxt < n:
                paras.append(f"       PARA-{i}.\n           PERFORM PARA-{nxt}.\n")
            else:
                paras.append(f"       PARA-{i}.\n           DISPLAY WS-A.\n")
        fold = _fold("".join(paras))
        assert fold.known == {}


class TestControlFlowTheWalkDoesNotFollow:
    """Every value below was checked against the program's real output under
    GnuCOBOL 3.2. A `field_equals` value must hold at *every* DISPLAY/WRITE
    of the field: one the walk skipped (PERFORM of a SECTION), one it took
    as unconditional (a GO TO / EXIT PARAGRAPH inside an IF), or a site it
    never looked at (inside an IF arm or loop, or past a GO TO) used to
    produce a value the program never showed there."""

    def test_perform_of_a_section_runs_its_paragraphs(self):
        # GnuCOBOL: 002
        fold = _fold(
            "       MAIN-SEC SECTION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM SEC-A.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       SEC-A SECTION.\n"
            "       SEC-A-P.\n"
            "           MOVE 2 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "2"}

    def test_perform_of_a_section_with_unnamed_paragraphs(self):
        # GnuCOBOL: 003
        fold = _fold(
            "       MAIN-SEC SECTION.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM SEC-A.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       SEC-A SECTION.\n"
            "           MOVE 2 TO WS-A.\n"
            "           ADD 1 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "3"}

    def test_perform_thru_a_section_range(self):
        fold = _fold(
            "       MAIN-SEC SECTION.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM SEC-A THRU SEC-B.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       SEC-A SECTION.\n"
            "           MOVE 2 TO WS-A.\n"
            "       SEC-B SECTION.\n"
            "       SEC-B-1.\n"
            "           ADD 5 TO WS-A.\n"
            "       SEC-B-2.\n"
            "           ADD 1 TO WS-A.\n"
            "       SEC-C SECTION.\n"
            "           MOVE 9 TO WS-A.\n"
        )
        assert fold.known == {"WS-A": "8"}

    def test_perform_of_an_unknown_procedure_forgets_everything(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM NO-SUCH-PARA.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
        )
        assert fold.known == {}

    def test_conditional_go_to_the_range_exit_skips_the_move(self):
        # GnuCOBOL: 001 (the GO TO is taken), never 002
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-B.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM P1 THRU P1-EXIT.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       P1.\n"
            "           IF WS-B = 5\n"
            "              GO TO P1-EXIT\n"
            "           END-IF.\n"
            "           MOVE 2 TO WS-A.\n"
            "       P1-EXIT.\n"
            "           EXIT.\n"
        )
        assert "WS-A" not in fold.known

    def test_conditional_exit_paragraph_skips_the_move(self):
        # GnuCOBOL: 001, never 002
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-B.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM P1.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       P1.\n"
            "           IF WS-B = 5\n"
            "              EXIT PARAGRAPH\n"
            "           END-IF.\n"
            "           MOVE 2 TO WS-A.\n"
        )
        assert "WS-A" not in fold.known

    def test_a_field_untouched_past_a_conditional_exit_stays_known(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 7 TO WS-B.\n"
            "           PERFORM P1.\n"
            "           DISPLAY WS-B.\n"
            "           STOP RUN.\n"
            "       P1.\n"
            "           IF WS-FLAG = 'Y'\n"
            "              EXIT PARAGRAPH\n"
            "           END-IF.\n"
            "           MOVE 2 TO WS-A.\n"
        )
        assert fold.known == {"WS-B": "7"}

    def test_displays_inside_an_if_arm_and_a_loop_are_sites_too(self):
        # GnuCOBOL: 001 002 003 004 -- not "always 1"
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-B.\n"
            "           MOVE 1 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
            "           IF WS-B = 5\n"
            "              MOVE 2 TO WS-A\n"
            "              DISPLAY WS-A\n"
            "           END-IF.\n"
            "           PERFORM 2 TIMES\n"
            "              ADD 1 TO WS-A\n"
            "              DISPLAY WS-A\n"
            "           END-PERFORM.\n"
            "           STOP RUN.\n"
        )
        assert "WS-A" not in fold.known

    def test_a_display_only_a_go_to_reaches_is_a_site_too(self):
        # GnuCOBOL: 001 002
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
            "           GO TO P9.\n"
            "       P8.\n"
            "           STOP RUN.\n"
            "       P9.\n"
            "           MOVE 2 TO WS-A.\n"
            "           DISPLAY WS-A.\n"
            "           GO TO P8.\n"
        )
        assert "WS-A" not in fold.known

    def test_a_search_when_body_may_run(self):
        # GnuCOBOL: 002
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'ABC' TO WS-T.\n"
            "           MOVE 1 TO WS-A.\n"
            "           SET WS-TI TO 1.\n"
            "           SEARCH WS-TE\n"
            "              AT END MOVE 7 TO WS-B\n"
            "              WHEN WS-TE(WS-TI) = 'B'\n"
            "                 MOVE 2 TO WS-A\n"
            "           END-SEARCH.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n",
            extra_data=(
                "       01  WS-T.\n"
                "           05  WS-TE PIC X OCCURS 3 INDEXED BY WS-TI.\n"
            ),
        )
        assert "WS-A" not in fold.known

    def test_a_sort_input_procedure_runs(self):
        # GnuCOBOL: 002
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT SW ASSIGN TO 'SW.TMP'.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       SD SW.\n"
            "       01 SW-REC.\n"
            "          05 SW-KEY PIC 9(3).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 X PIC 9(3) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 1 TO X.\n"
            "           SORT SW ON ASCENDING KEY SW-KEY\n"
            "              INPUT PROCEDURE IS P-IN\n"
            "              OUTPUT PROCEDURE IS P-OUT.\n"
            "           DISPLAY X.\n"
            "           STOP RUN.\n"
            "       P-IN.\n"
            "           MOVE 5 TO SW-KEY.\n"
            "           RELEASE SW-REC.\n"
            "           MOVE 2 TO X.\n"
            "       P-OUT.\n"
            "           RETURN SW AT END CONTINUE END-RETURN.\n"
        )
        result = parse_cobol(source, filename="t.cbl")
        assert result.errors == [], result.errors
        fold = ConstantFolder().fold(result.ast, ProgramLayoutIndex.build(result.ast))
        assert "X" not in fold.known

    def test_a_compute_past_a_conditional_exit_may_not_run(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 5 TO WS-B.\n"
            "           MOVE 1 TO WS-A.\n"
            "           PERFORM P1.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
            "       P1.\n"
            "           IF WS-B = 5\n"
            "              EXIT PARAGRAPH\n"
            "           END-IF.\n"
            "           COMPUTE WS-A = 2 + 3.\n"
        )
        assert "WS-A" not in fold.known


class TestCallMayWriteSharedStorage:
    """A CALL can change storage it was never passed: a contained program
    writes a GLOBAL item by name, and every program declaring the same
    EXTERNAL item shares its bytes."""

    def test_contained_program_writes_a_global_item(self):
        # GnuCOBOL 3.2 displays 002.
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. G1.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 X PIC 9(3) VALUE 0 GLOBAL.\n"
            "       01 Y PIC 9(3) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 1 TO X.\n"
            "           MOVE 4 TO Y.\n"
            "           CALL 'INNER'.\n"
            "           DISPLAY X.\n"
            "           DISPLAY Y.\n"
            "           STOP RUN.\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. INNER.\n"
            "       PROCEDURE DIVISION.\n"
            "           MOVE 2 TO X.\n"
            "           GOBACK.\n"
            "       END PROGRAM INNER.\n"
            "       END PROGRAM G1.\n"
        )
        result = parse_cobol(source, filename="t.cbl")
        assert result.errors == [], result.errors
        fold = ConstantFolder().fold(result.ast, ProgramLayoutIndex.build(result.ast))
        assert fold.known == {"Y": "4"}

    def test_external_group_leaves_are_forgotten_by_a_call(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO WS-EXT-A.\n"
            "           MOVE 4 TO WS-A.\n"
            "           CALL 'OTHER'.\n"
            "           DISPLAY WS-EXT-A.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n",
            extra_data=(
                "       01  WS-EXT EXTERNAL.\n" "           05  WS-EXT-A PIC 9(3).\n"
            ),
        )
        assert fold.known == {"WS-A": "4"}


class TestInspectAndExecWrites:
    """Issue #317: writes that live outside `.operands` must poison."""

    def test_inspect_tallying_counter_is_forgotten(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'A,B,C' TO WS-NAME.\n"
            "           MOVE ZERO TO WS-A.\n"
            "           MOVE 7 TO WS-B.\n"
            "           INSPECT WS-NAME TALLYING WS-A FOR ALL ','.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
        )
        assert fold.known == {"WS-B": "7"}

    def test_inspect_tallying_for_characters_counter_is_forgotten(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 1 TO WS-A.\n"
            "           INSPECT WS-NAME TALLYING WS-A FOR CHARACTERS.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_exec_cics_into_length_resp_are_forgotten(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'ABC' TO WS-NAME.\n"
            "           MOVE 0 TO WS-A.\n"
            "           MOVE 0 TO WS-B.\n"
            "           MOVE 5 TO WS-TOTAL.\n"
            "           EXEC CICS RECEIVE INTO(WS-NAME) LENGTH(WS-A)\n"
            "                RESP(WS-B) END-EXEC.\n"
            "           DISPLAY WS-NAME.\n"
            "           DISPLAY WS-A.\n"
            "           DISPLAY WS-B.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-TOTAL": "5"}

    def test_exec_dli_into_is_forgotten(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 'ABC' TO WS-NAME.\n"
            "           MOVE 5 TO WS-TOTAL.\n"
            "           EXEC DLI GU USING PCB(1) SEGMENT(ROOT)\n"
            "                INTO(WS-NAME) END-EXEC.\n"
            "           DISPLAY WS-NAME.\n"
            "           DISPLAY WS-TOTAL.\n"
        )
        assert fold.known == {"WS-TOTAL": "5"}

    def test_exec_cics_inside_a_branch_is_forgotten(self):
        fold = _fold(
            "       MAIN-PARA.\n"
            "           MOVE 0 TO WS-A.\n"
            "           IF WS-FLAG = 'Y'\n"
            "               EXEC CICS RECEIVE INTO(WS-NAME) LENGTH(WS-A)\n"
            "               END-EXEC\n"
            "           END-IF.\n"
            "           DISPLAY WS-A.\n"
        )
        assert fold.known == {}

    def test_exec_cics_set_address_of_forgets_the_record(self):
        # SET(ADDRESS OF LS-REC) re-points the record at new storage, so a
        # value moved into it before is not what the DISPLAY shows.
        fold = _fold(
            "       MAIN-PARA.\n"
            "           EXEC CICS GETMAIN SET(ADDRESS OF LS-REC) FLENGTH(3)\n"
            "           END-EXEC.\n"
            "           MOVE 'ABC' TO LS-F.\n"
            "           EXEC CICS READ FILE('F') RIDFLD(WS-A)\n"
            "                SET(ADDRESS OF LS-REC) END-EXEC.\n"
            "           DISPLAY LS-F.\n",
            extra_data=(
                "       LINKAGE SECTION.\n"
                "       01  LS-REC.\n"
                "           05  LS-F PIC X(3).\n"
            ),
        )
        assert fold.known == {}
