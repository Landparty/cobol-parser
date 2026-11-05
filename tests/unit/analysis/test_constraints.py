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


# Same shape as _HEADER, but with TWO condition names on one field -- the
# arrangement that exposed the "every 88 arm gets the parent's whole value
# union" bug (a single 88, as in _HEADER's F1-VALID, cannot show it).
_HEADER_TWO_88S = _HEADER.replace(
    "           05  F1-STATUS       PIC X.\n"
    "              88  F1-VALID     VALUE 'A' 'B'.\n",
    "           05  F1-STATUS       PIC X.\n"
    "              88  F1-VALID     VALUE 'A' 'B'.\n"
    "           05  F1-TYPE         PIC X(02).\n"
    "              88  F1-TYPE-M    VALUE '05'.\n"
    "              88  F1-TYPE-F    VALUE '09'.\n",
)


def _extract(procedure_body: str, filename: str = "t.cbl", header: str = ""):
    source = (header or _HEADER) + procedure_body
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


class TestToDictSerialization:
    def test_field_constraint_branch_constraint_and_report_all_serialize(self):
        _, _, _, report = _extract(
            "           IF F1-QTY = 42\n"
            "               DISPLAY 'HIT'\n"
            "           END-IF.\n"
        )
        as_dict = report.to_dict()
        assert as_dict["branches"]
        branch_dict = as_dict["branches"][0]
        assert branch_dict["branch_id"]
        assert branch_dict["parent_proc"] == "MAIN-PARA"
        assert set(branch_dict["arms"]) == {"THEN", "ELSE"}
        then_constraint = branch_dict["arms"]["THEN"][0]
        assert then_constraint == {
            "field": "F1-REC.F1-QTY",
            "op": "eq",
            "values": ["42"],
            "origin": then_constraint["origin"],
            "negated": False,
        }
        assert branch_dict["unsupported"] == []

    def test_sequence_constraint_serializes(self):
        _, _, _, report = _extract(
            "           PERFORM UNTIL WS-EOF = 'Y'\n"
            "               READ F1\n"
            "                   AT END MOVE 'Y' TO WS-EOF\n"
            "               END-READ\n"
            "           END-PERFORM.\n"
        )
        as_dict = report.to_dict()
        assert as_dict["sequence_constraints"]
        seq_dict = as_dict["sequence_constraints"][0]
        assert seq_dict["boundary"] == {"category": "READ", "key": "F1"}
        assert seq_dict["length"] is None
        assert "PERFORM-UNTIL" in seq_dict["origin"]


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
        # WHEN OTHER is the negation of every prior arm, not "unconstrained".
        # Leaving it empty was not neutral: an unconstrained level-88 field is
        # generated by drawing from its own condition_values, so the scenario
        # named for the OTHER arm was seeded with the very values that arm
        # excludes and could never reach its own branch.
        other = branch.arms["WHEN_OTHER"]
        assert [(c.op, c.values) for c in other] == [("not_in_set", ("A", "B"))]

    def test_evaluate_true_class_and_sign_tests_in_stacked_whens(self):
        """``WHEN X NOT NUMERIC`` arrives as raw condition text; it used to be
        reported unparseable, which left every arm of the EVALUATE (stacked
        WHENs and WHEN OTHER) without a scenario."""
        _, _, _, report = _extract(
            "           EVALUATE TRUE\n"
            "               WHEN F1-QTY NOT NUMERIC\n"
            "               WHEN F1-QTY IS ZERO\n"
            "                   DISPLAY 'NO'\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'OK'\n"
            "           END-EVALUATE.\n"
        )
        branch = _branch(report)
        assert not any("not structurally parseable" in u for u in branch.unsupported)
        first = branch.arms["WHEN_1#1"][0]
        assert (first.op, first.negated) == ("class_numeric", True)
        second = branch.arms["WHEN_1#2"][0]
        assert (second.op, second.values) == ("eq", ("0",))

    def test_level_88_arms_are_scoped_to_their_own_condition_name(self):
        """`resolve()` maps an 88 to its *parent* field, and
        `FieldSpec.condition_values` is deliberately the union of every 88
        under that field. Reading the union here made every arm of an
        `EVALUATE TRUE / WHEN <88>` chain produce a byte-identical
        constraint: the solver picked the first value for all of them, so
        the scenario named for the second arm was seeded with the first
        arm's value and never reached the branch it was named for."""
        _, _, _, report = _extract(
            "           EVALUATE TRUE\n"
            "               WHEN F1-TYPE-M\n"
            "                   DISPLAY 'M'\n"
            "               WHEN F1-TYPE-F\n"
            "                   DISPLAY 'F'\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'X'\n"
            "           END-EVALUATE.\n",
            header=_HEADER_TWO_88S,
        )
        branch = _branch(report)
        assert branch.arms["WHEN_1"][0].values == ("05",)
        assert branch.arms["WHEN_2"][0].values == ("09",)
        assert branch.arms["WHEN_OTHER"][0].values == ("05", "09")
        assert branch.arms["WHEN_OTHER"][0].op == "not_in_set"

    def test_when_other_over_different_fields_negates_each_arm(self):
        """NOT(F1-QTY = 1) AND NOT(F1-STATUS = 'Z') is a conjunction, which
        the FieldConstraint vocabulary expresses (bug hunt 2026-11-05,
        round 2: it used to stay unconstrained)."""
        _, _, _, report = _extract(
            "           EVALUATE TRUE\n"
            "               WHEN F1-QTY = 1\n"
            "                   DISPLAY 'A'\n"
            "               WHEN F1-STATUS = 'Z'\n"
            "                   DISPLAY 'B'\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'C'\n"
            "           END-EVALUATE.\n"
        )
        branch = _branch(report)
        assert sorted((c.op, c.values) for c in branch.arms["WHEN_OTHER"]) == [
            ("ne", ("1",)),
            ("ne", ("Z",)),
        ]
        assert branch.unmodeled_arms == {}

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
        # EVALUATE is first-match: each later arm also carries the negation
        # of every earlier arm. A THRU range negates through one of its
        # bounds, the one still satisfiable with the rest (2..10 -> < 2,
        # since ANY leaves F1-QTY free).
        assert [(c.op, c.values) for c in branch.arms["WHEN_2"]] == [
            ("ge", ("2",)),
            ("le", ("10",)),
            ("ne", ("1",)),
        ]
        assert [(c.op, c.values) for c in branch.arms["WHEN_3"]] == [
            ("ne", ("1",)),
            ("lt", ("2",)),
        ]


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

    def test_search_when_and_is_two_conjuncts_not_one_made_up_literal(self):
        # Issue #348: the raw text split on its first operator made the whole
        # tail ("A' AND F1-QTY = 5") the right-hand value of one equality.
        _, _, _, report = _extract(
            "           SEARCH F1-REC\n"
            "               WHEN F1-STATUS = 'A' AND F1-QTY = 5\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
        )
        branch = _branch(report)
        assert [(c.field.spec.name, c.op, c.values) for c in branch.arms["WHEN_1"]] == [
            ("F1-STATUS", "eq", ("A",)),
            ("F1-QTY", "eq", ("5",)),
        ]
        assert branch.unsupported == []

    def test_search_when_or_is_one_arm_variant_per_side(self):
        _, _, _, report = _extract(
            "           SEARCH F1-REC\n"
            "               WHEN F1-STATUS = 'A' OR F1-QTY > 7\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
        )
        branch = _branch(report)
        assert [
            [(c.field.spec.name, c.op, c.values) for c in branch.arms[arm]]
            for arm in ("WHEN_1#1", "WHEN_1#2")
        ] == [[("F1-STATUS", "eq", ("A",))], [("F1-QTY", "gt", ("7",))]]

    def test_search_when_tree_is_recorded_alongside_the_text(self):
        ast, _, _, _ = _extract(
            "           SEARCH F1-REC\n"
            "               WHEN F1-STATUS = 'A' AND F1-QTY = 5\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
        )
        (search,) = ast.find_all_by_type("SearchStatement")
        clause = search.when_clauses[0]
        assert clause["condition"] == "F1-STATUS = 'A' AND F1-QTY = 5"
        assert clause["condition_tree"].operator == "AND"
        serialized = search.to_dict()["when_clauses"][0]
        assert serialized["condition"] == clause["condition"]
        assert serialized["condition_tree"]["operator"] == "AND"


class TestRelationalTextCompound:
    """The raw-text fallback reports a compound condition rather than
    inventing a literal out of its tail (issue #348)."""

    def test_and_in_text_is_unsupported(self):
        from cobolparser.analysis.constraints import _parse_relational_text

        _, index, boundary_report, _ = _extract("           STOP RUN.\n")
        unsupported: list[str] = []
        fed = {
            name.upper() for b in boundary_report.boundaries for name in b.record_names
        }
        result = _parse_relational_text(
            "F1-STATUS = 'A' AND F1-QTY = 5", index, fed, "T", unsupported
        )
        assert result is None
        assert len(unsupported) == 1
        assert "compound condition" in unsupported[0]

    def test_and_inside_a_quoted_literal_is_not_a_connective(self):
        from cobolparser.analysis.constraints import _parse_relational_text

        _, index, _, _ = _extract("           STOP RUN.\n")
        unsupported: list[str] = []
        _parse_relational_text("F1-STATUS = 'A AND B'", index, set(), "T", unsupported)
        assert not any("compound condition" in reason for reason in unsupported)


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

    def test_multi_subject_evaluate_is_reported_unsupported_not_silently_dropped(self):
        _, _, _, report = _extract(
            "           EVALUATE F1-QTY ALSO F1-STATUS\n"
            "               WHEN 42 ALSO 'A'\n"
            "                   DISPLAY 'HIT'\n"
            "               WHEN OTHER\n"
            "                   DISPLAY 'MISS'\n"
            "           END-EVALUATE.\n"
        )
        branch = _branch(report)
        assert branch.arms == {}
        assert "multi-subject EVALUATE (ALSO) not supported in v1" in branch.unsupported

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
