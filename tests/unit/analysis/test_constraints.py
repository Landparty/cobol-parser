"""Unit tests for ConstraintExtractor (cobolparser.analysis.constraints).

One hand-built program per condition form in the parent plan's Phase 4 table
(relational comparisons, level-88 in_set, figurative constants, class/sign
tests), AND/OR/NOT composition via De Morgan, EVALUATE TRUE + 88s, WHEN
OTHER, SEARCH WHEN, and the READ/AT-END/PERFORM-UNTIL triple producing a
SequenceConstraint.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor

# A shared FILE SECTION every test program below re-uses: a READ of F1 (no
# INTO) makes F1-REC's fields "boundary-fed" per BoundaryInventoryAnalyzer's
# own record_names -- the precondition ConstraintExtractor requires before it
# will extract a constraint at all.
from cobolparser.generators import ProgramLayoutIndex

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONDTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-QTY          PIC 9(3).
           05  F1-STATUS       PIC X.
              88  F1-VALID     VALUE 'A' 'B'.
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
"""


def _extract(procedure_body: str, filename: str = "t.cbl"):
    source = _HEADER + procedure_body
    result = parse_cobol(source, filename=filename)
    assert result.ast is not None, result.errors
    assert result.errors == []
    index = ProgramLayoutIndex.build(result.ast)
    boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    report = ConstraintExtractor().extract(result.ast, index, boundary_report)
    return result.ast, index, boundary_report, report


def _branch(report, line_contains=None):
    """The one BranchConstraints whose branch_id contains MAIN-PARA (all test
    programs here only ever have one paragraph)."""
    assert len(report.branches) == 1, report.branches
    return report.branches[0]


class TestRelationalComparisons:
    def test_equal_literal(self):
        _, _, _, report = _extract(
            "           IF F1-QTY = 42\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"] == [
            c for c in branch.arms["THEN"] if c.op == "eq" and c.values == ("42",)
        ]
        assert branch.arms["ELSE"][0].op == "ne"
        assert branch.arms["ELSE"][0].values == ("42",)

    def test_not_equal(self):
        _, _, _, report = _extract(
            "           IF F1-QTY NOT = 42\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"][0].op == "ne"
        assert branch.arms["ELSE"][0].op == "eq"

    def test_greater_less_and_or_equal(self):
        _, _, _, report = _extract(
            "           IF F1-QTY > 5\n"
            "               DISPLAY 'A'\n"
            "           END-IF\n"
            "           IF F1-QTY < 5\n"
            "               DISPLAY 'B'\n"
            "           END-IF\n"
            "           IF F1-QTY >= 5\n"
            "               DISPLAY 'C'\n"
            "           END-IF\n"
            "           IF F1-QTY <= 5\n"
            "               DISPLAY 'D'\n"
            "           END-IF.\n"
        )
        assert len(report.branches) == 4
        ops = [b.arms["THEN"][0].op for b in report.branches]
        assert ops == ["gt", "lt", "ge", "le"]
        # Each ELSE is the complementary operator.
        else_ops = [b.arms["ELSE"][0].op for b in report.branches]
        assert else_ops == ["le", "ge", "lt", "gt"]

    def test_reversed_operand_order_flips_direction(self):
        # "42 > F1-QTY" means F1-QTY < 42 -- the field is on the right.
        _, _, _, report = _extract(
            "           IF 42 > F1-QTY\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        constraint = branch.arms["THEN"][0]
        assert constraint.op == "lt"
        assert constraint.values == ("42",)
        assert constraint.field.spec.name == "F1-QTY"


class TestLiteralSetAndFigurative:
    def test_string_literal_equality(self):
        _, _, _, report = _extract(
            "           IF F1-STATUS = 'A'\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"][0].op == "eq"
        assert branch.arms["THEN"][0].values == ("A",)

    def test_figurative_spaces(self):
        _, _, _, report = _extract(
            "           IF F1-STATUS = SPACES\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        constraint = branch.arms["THEN"][0]
        assert constraint.op == "figurative"
        assert constraint.values == ("SPACES",)
        assert constraint.negated is False
        assert branch.arms["ELSE"][0].negated is True


class TestLevel88:
    def test_bare_condition_name_resolves_to_in_set(self):
        _, _, _, report = _extract(
            "           IF F1-VALID\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        constraint = branch.arms["THEN"][0]
        assert constraint.op == "in_set"
        assert set(constraint.values) == {"A", "B"}
        assert branch.arms["ELSE"][0].op == "not_in_set"


class TestClassAndSignConditions:
    def test_is_numeric_and_is_not_numeric(self):
        _, _, _, report = _extract(
            "           IF F1-QTY IS NUMERIC\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"][0].op == "class_numeric"
        assert branch.arms["THEN"][0].negated is False
        assert branch.arms["ELSE"][0].op == "class_numeric"
        assert branch.arms["ELSE"][0].negated is True

    def test_is_alphabetic(self):
        _, _, _, report = _extract(
            "           IF F1-STATUS IS ALPHABETIC\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"][0].op == "class_alphabetic"

    def test_sign_conditions_fold_into_relational(self):
        _, _, _, report = _extract(
            "           IF F1-QTY IS POSITIVE\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms["THEN"][0].op == "gt"
        assert branch.arms["THEN"][0].values == ("0",)
        assert branch.arms["ELSE"][0].op == "le"


class TestConjunctionDisjunctionNegation:
    def test_and_stays_one_conjunct_list(self):
        _, _, _, report = _extract(
            "           IF F1-QTY > 10 AND F1-QTY < 100\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert {c.op for c in branch.arms["THEN"]} == {"gt", "lt"}
        # De Morgan: NOT(A AND B) = NOT A OR NOT B -- two separate ELSE arms.
        assert "ELSE#1" in branch.arms
        assert "ELSE#2" in branch.arms
        assert "ELSE" not in branch.arms
        else_ops = {branch.arms["ELSE#1"][0].op, branch.arms["ELSE#2"][0].op}
        assert else_ops == {"le", "ge"}

    def test_or_splits_into_multiple_then_arms(self):
        _, _, _, report = _extract(
            "           IF F1-QTY = 1 OR F1-QTY = 2\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert "THEN#1" in branch.arms
        assert "THEN#2" in branch.arms
        # De Morgan: NOT(A OR B) = NOT A AND NOT B -- one combined ELSE arm.
        assert branch.arms["ELSE"] == [c for c in branch.arms["ELSE"] if c.op == "ne"]
        assert len(branch.arms["ELSE"]) == 2


class TestUnsupportedForms:
    def test_two_resolved_fields_is_unsupported(self):
        _, _, _, report = _extract(
            "           IF F1-QTY > F1-STATUS\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        branch = _branch(report)
        assert branch.arms == {}
        assert any("two resolved fields" in u for u in branch.unsupported)

    def test_non_boundary_fed_field_is_unsupported(self):
        source = _HEADER.replace(
            "       01  WS-EOF              PIC X VALUE 'N'.\n",
            "       01  WS-EOF              PIC X VALUE 'N'.\n"
            "       01  WS-COUNTER          PIC 9(3).\n",
        )
        result = parse_cobol(
            source + "           IF WS-COUNTER > 5\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n",
            filename="t.cbl",
        )
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        report = ConstraintExtractor().extract(result.ast, index, boundary_report)
        branch = _branch(report)
        assert branch.arms == {}
        assert any("field not boundary-fed" in u for u in branch.unsupported)


class TestEvaluate:
    def test_evaluate_true_with_level_88(self):
        _, _, _, report = _extract(
            "           EVALUATE TRUE\n"
            "               WHEN F1-VALID\n"
            "                   DISPLAY 'OK'\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'NO'\n"
            "           END-EVALUATE.\n"
        )
        branch = _branch(report)
        assert branch.arms["WHEN_1"][0].op == "in_set"
        assert branch.arms["WHEN_OTHER"] == []

    def test_evaluate_data_driven_literal_and_range(self):
        _, _, _, report = _extract(
            "           EVALUATE F1-QTY\n"
            "               WHEN 1\n"
            "                   DISPLAY 'ONE'\n"
            "               WHEN 2 THRU 10\n"
            "                   DISPLAY 'RANGE'\n"
            "               WHEN ANY\n"
            "                   DISPLAY 'ANY'\n"
            "           END-EVALUATE.\n"
        )
        branch = _branch(report)
        assert branch.arms["WHEN_1"] == [
            c for c in branch.arms["WHEN_1"] if c.op == "eq" and c.values == ("1",)
        ]
        range_ops = {c.op for c in branch.arms["WHEN_2"]}
        assert range_ops == {"ge", "le"}
        assert branch.arms["WHEN_3"] == []


class TestSearch:
    def test_search_when_simple_relational(self):
        _, _, _, report = _extract(
            "           SEARCH F1-REC\n"
            "               AT END DISPLAY 'NOTFOUND'\n"
            "               WHEN F1-QTY = 5\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
        )
        branch = _branch(report)
        assert branch.arms["WHEN_1"][0].op == "eq"
        assert branch.arms["WHEN_1"][0].values == ("5",)
        assert "AT_END" in branch.arms


class TestSequenceConstraint:
    def test_perform_until_eof_flag_pattern(self):
        _, _, boundary_report, report = _extract(
            "           PERFORM UNTIL WS-EOF = 'Y'\n"
            "               READ F1\n"
            "                   AT END MOVE 'Y' TO WS-EOF\n"
            "               END-READ\n"
            "           END-PERFORM.\n"
        )
        assert len(report.sequence_constraints) == 1
        seq = report.sequence_constraints[0]
        assert seq.boundary.category == "READ"
        assert seq.boundary.key == "F1"
        assert seq.length is None
        assert "PERFORM-UNTIL" in seq.origin
        # The SequenceConstraint's BoundaryRef must be a real one from the
        # boundary report, not a freshly synthesized stand-in.
        assert seq.boundary in [b.ref for b in boundary_report.boundaries]

    def test_pure_counter_loop_is_out_of_scope_not_a_gap(self):
        # WS-COUNTER (unlike WS-EOF) is never MOVEd inside any READ's AT END
        # clause and is not boundary-fed -- a plain internal counter loop.
        source = _HEADER.replace(
            "       01  WS-EOF              PIC X VALUE 'N'.\n",
            "       01  WS-EOF              PIC X VALUE 'N'.\n"
            "       01  WS-COUNTER          PIC 9(3) VALUE 0.\n",
        )
        result = parse_cobol(
            source + "           PERFORM UNTIL WS-COUNTER > 5\n"
            "               ADD 1 TO WS-COUNTER\n"
            "           END-PERFORM.\n",
            filename="t.cbl",
        )
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        report = ConstraintExtractor().extract(result.ast, index, boundary_report)
        assert report.sequence_constraints == []
        # Silence is correct here, not a silent drop: nothing in this
        # condition touches a boundary-fed field.
        assert report.unsupported == []
