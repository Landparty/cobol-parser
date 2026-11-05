"""A scenario's name is a claim; these tests are about making the bundle
able to back it up.

Two problems, one root cause. First, `ScenarioPlanner` v1 pinned only the
targeted arm's OWN conjuncts, leaving every enclosing condition to whatever
the value generator happened to produce -- so a scenario named for a nested
arm routinely generated data that never reached it, and the only way to find
out was to run each case under a tracer. Second, nothing ever re-checked the
emitted data against the conditions that motivated it, so even the
non-nested cases were labels rather than verdicts.

`BranchConstraints.enclosing` + `_path_constraints` fix the first;
`generators.verification` answers the second, in the bundle, per scenario.
"""

from __future__ import annotations

from decimal import Decimal

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.verification import satisfies

NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).
           05  INV-TYPE       PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE
           PERFORM READ-ONE UNTIL WS-EOF = "Y"
           CLOSE INV-FILE.
       READ-ONE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF INV-QTY > 500
               IF INV-TYPE = "AB"
                   ADD INV-QTY TO WS-TOTAL
               END-IF
           END-IF.
"""


def _branch_scenarios(bundle):
    """Every scenario but the happy path, which targets no branch."""
    return [s for s in bundle.scenarios if s.name != "happy path"]


def _bundle(source: str, mode: str = "branches", rows: int = 3):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=rows))
    return generator.generate_with_scenarios(
        result.ast, index, report, mode=mode, seed=7
    )


def _read_rows(scenario):
    return [
        row
        for fixture in scenario.fixtures
        if fixture.ref.category == "READ"
        for row in fixture.sequence
    ]


class TestPathConditionAccumulation:
    def test_the_extractor_records_each_branches_enclosing_arms(self):
        result = parse_cobol(NESTED_SOURCE, filename="t.cbl")
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        constraints = ConstraintExtractor().extract(result.ast, index, report)

        outer = [b for b in constraints.branches if not b.enclosing]
        inner = [b for b in constraints.branches if b.enclosing]
        assert len(outer) == 1 and len(inner) == 1
        # The inner IF is reached only through the outer IF's THEN arm.
        assert inner[0].enclosing == ((outer[0].branch_id, "THEN"),)

    def test_a_nested_arms_scenario_also_pins_its_enclosing_condition(self):
        """The regression this closes: the inner arm's scenario used to pin
        only INV-TYPE, leaving INV-QTY wherever chance put it -- so the
        scenario named for the inner branch usually never reached it."""
        bundle = _bundle(NESTED_SOURCE)
        # The inner IF's THEN arm: the only scenario that both folded a path
        # condition in and targets a THEN arm of its own.
        then_arm = next(
            s
            for s in bundle.scenarios
            if "path condition from" in s.intent
            and s.intent.split(" (")[0].endswith("/THEN")
        )
        rows = _read_rows(then_arm)
        assert rows
        for row in rows:
            assert Decimal(row["INV-QTY"]) > 500  # the ENCLOSING condition
            assert row["INV-TYPE"].rstrip() == "AB"  # its own

    def test_the_intent_says_when_a_path_condition_was_folded_in(self):
        bundle = _bundle(NESTED_SOURCE)
        assert any("path condition from" in s.intent for s in bundle.scenarios)


GUARDED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GUARDED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-RC         PIC X.
           05  INV-QTY        PIC 9(4).
           05  INV-TYPE       PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       01  WS-ERRORS          PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE
           PERFORM READ-ONE THRU READ-ONE-EXIT UNTIL WS-EOF = "Y"
           CLOSE INV-FILE.
       READ-ONE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
                      GO TO READ-ONE-EXIT
           END-READ
           IF INV-RC NOT = "V"
               ADD 1 TO WS-ERRORS
               GO TO READ-ONE-EXIT
           END-IF
           EVALUATE INV-TYPE
               WHEN "AA"
                   CONTINUE
               WHEN OTHER
                   ADD 1 TO WS-ERRORS
                   GO TO READ-ONE-EXIT
           END-EVALUATE
           IF INV-QTY > 500
               ADD INV-QTY TO WS-TOTAL
           END-IF.
       READ-ONE-EXIT.
           EXIT.
"""


class TestEarlyExitGuards:
    """A branch below ``IF bad ... GO TO exit END-IF`` runs only when that
    guard's other arm is taken -- exactly as if it were nested in it.
    Scenarios used to pin only the target arm, so with the guard's field
    left to chance the case left the paragraph before reaching its arm
    (ACHPROC's account checks sat below `IF WS-AV-RESULT-CODE NOT = 'V'
    ... GO TO 2200-EXIT`: all six cases ran the routing-error exit)."""

    def test_the_guards_staying_arm_is_part_of_the_enclosing_path(self):
        result = parse_cobol(GUARDED_SOURCE, filename="t.cbl")
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        constraints = ConstraintExtractor().extract(result.ast, index, report)
        by_line = {b.line: b for b in constraints.branches}
        guard, evaluate, target = (by_line[line] for line in sorted(by_line))
        assert guard.enclosing == ()
        assert evaluate.enclosing == ((guard.branch_id, "ELSE"),)
        assert target.enclosing == (
            (guard.branch_id, "ELSE"),
            (evaluate.branch_id, "WHEN_1"),
        )

    def test_a_scenario_below_the_guards_passes_them(self):
        bundle = _bundle(GUARDED_SOURCE)
        scenario = next(
            s
            for s in bundle.scenarios
            if s.intent.split(" (")[0].endswith("/THEN")
            and s.name == "READ-ONE: IF@39 THEN"
        )
        rows = _read_rows(scenario)
        assert rows
        for row in rows:
            assert row["INV-RC"] == "V"
            assert row["INV-TYPE"].rstrip() == "AA"
            assert Decimal(row["INV-QTY"]) > 500
        assert scenario.verification["status"] == "verified"

    def test_a_branch_with_two_staying_arms_is_no_guard(self):
        """Both arms fall through: reaching the next statement needs either,
        a disjunction the path cannot carry, so nothing is added."""
        source = GUARDED_SOURCE.replace(
            "               ADD 1 TO WS-ERRORS\n               GO TO READ-ONE-EXIT\n"
            "           END-IF",
            "               ADD 1 TO WS-ERRORS\n           END-IF",
        )
        result = parse_cobol(source, filename="t.cbl")
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        constraints = ConstraintExtractor().extract(result.ast, index, report)
        by_line = {b.line: b for b in constraints.branches}
        _guard, evaluate, _target = (by_line[line] for line in sorted(by_line))
        assert evaluate.enclosing == ()


class TestSelfVerification:
    def test_every_branch_scenario_carries_a_verdict(self):
        bundle = _bundle(NESTED_SOURCE)
        assert _branch_scenarios(bundle)
        for scenario in _branch_scenarios(bundle):
            assert scenario.verification is not None
            assert scenario.verification["status"] in ("verified", "unverified")

    def test_a_well_pinned_scenario_verifies_against_its_own_data(self):
        bundle = _bundle(NESTED_SOURCE)
        for scenario in _branch_scenarios(bundle):
            assert scenario.verification["status"] == "verified", (
                scenario.name,
                scenario.verification,
            )
            for verdict in scenario.verification["fields"]:
                assert verdict["status"] == "satisfied"
                assert verdict["rows"]

    def test_the_happy_path_scenario_has_nothing_to_verify(self):
        """`mode="happy"` targets no branch, so a verdict would be a claim
        about nothing -- it stays absent rather than being stamped
        "verified"."""
        bundle = _bundle(NESTED_SOURCE, mode="happy")
        assert [s.verification for s in bundle.scenarios] == [None]

    def test_branch_modes_keep_the_happy_path_first_and_unverified(self):
        """`branches` adds scenarios on top of the happy path, it does not
        replace it: the same scenario `mode="happy"` emits comes first, still
        with no verdict."""
        happy = _bundle(NESTED_SOURCE, mode="happy").scenarios[0]
        first = _bundle(NESTED_SOURCE).scenarios[0]
        assert first.name == "happy path"
        assert first.verification is None
        assert first.to_dict() == happy.to_dict()

    def test_an_undecidable_comparison_is_reported_not_assumed_good(self):
        """`IF WS-INPUT > 0` on a `PIC X` field: ordering an alphanumeric
        domain against a numeric literal is not something the allow/deny set
        can express, so no witness for it can exist.

        The arm is therefore reported as *missed*, with the reason, rather
        than turned into a scenario. It used to become a scenario whose data
        was picked as though the constraint were satisfiable -- `_apply_text`
        returned "still satisfiable" for every relational op -- leaving a
        fixture named for a branch it does not reach. A named scenario is a
        claim; "I could not model this" has to be a coverage miss, not a
        scenario carrying a caveat.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INPUT           PIC X(10).
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           ACCEPT WS-INPUT
           IF WS-INPUT > 0
               ADD 1 TO WS-TOTAL
           END-IF.
"""
        bundle = _bundle(source)
        assert [s.name for s in bundle.scenarios] == ["happy path"]
        coverage = bundle.scenario_coverage
        assert coverage["targeted"] == 0
        assert coverage["missed"] == coverage["total_arms"] > 0
        # Every miss names why, and the reason is the modelling gap itself --
        # not a generic "no witness".
        reasons = [detail["reason"] for detail in coverage["details"]]
        assert reasons and all(reason for reason in reasons)
        assert any(
            "gt on an alphanumeric domain is not modeled" in reason
            for reason in reasons
        )

    def test_verification_is_serialized_into_the_bundle_json(self):
        import json

        bundle = _bundle(NESTED_SOURCE)
        payload = json.loads(bundle.to_json())
        branch = [s for s in payload["scenarios"] if s["name"] != "happy path"]
        assert branch
        assert all("verification" in s for s in branch)


class TestSatisfies:
    """The predicate itself: an honest `None` wherever the answer is not
    knowable from a rendered string."""

    @staticmethod
    def _constraint(op: str, *values: str, negated: bool = False) -> FieldConstraint:
        return FieldConstraint(
            field=None,  # unused by `satisfies`
            op=op,
            values=values,
            origin="test",
            negated=negated,
        )

    def test_numeric_relations(self):
        assert satisfies(self._constraint("gt", "500"), "0501") is True
        assert satisfies(self._constraint("gt", "500"), "0500") is False
        assert satisfies(self._constraint("le", "500"), "0500") is True

    def test_alphanumeric_equality_ignores_picture_padding(self):
        assert satisfies(self._constraint("eq", "AB"), "AB  ") is True
        assert satisfies(self._constraint("ne", "AB"), "AB  ") is False

    def test_mixed_numeric_and_text_ordering_is_undecidable(self):
        assert satisfies(self._constraint("gt", "0"), "XXXX") is None
        assert satisfies(self._constraint("le", "0"), "XXXX") is None

    def test_mixed_numeric_and_text_equality_still_decides(self):
        """A value that is not a number cannot equal a numeric literal,
        whichever way the comparison is read."""
        assert satisfies(self._constraint("eq", "0"), "XXXX") is False
        assert satisfies(self._constraint("ne", "0"), "XXXX") is True

    def test_set_membership(self):
        assert satisfies(self._constraint("in_set", "05", "09"), "09") is True
        assert satisfies(self._constraint("in_set", "05", "09"), "07") is False
        assert satisfies(self._constraint("not_in_set", "05", "09"), "07") is True

    def test_class_tests_honour_negation(self):
        assert satisfies(self._constraint("class_numeric"), "0042") is True
        assert satisfies(self._constraint("class_numeric"), "AB") is False
        assert satisfies(self._constraint("class_numeric", negated=True), "AB") is True
        assert satisfies(self._constraint("class_alphabetic"), "AB") is True

    def test_numeric_class_on_alphanumeric_field_needs_every_position(self):
        """ "00000000" in a PIC X(10) is padded with two spaces: NOT
        NUMERIC, so a THEN arm seeded with it must not read as verified."""
        from cobolparser.generators.data.layout import FieldCategory, FieldSpec
        from cobolparser.generators.data.program_layout import ResolvedField
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.models.data_items import CobolDataItem

        spec = FieldSpec(
            name="IN-NAME",
            path=("IN-NAME",),
            column="IN-NAME",
            level=5,
            picture="X(10)",
            usage="DISPLAY",
            category=FieldCategory.ALPHANUMERIC,
            size=10,
            integer_digits=0,
            decimal_digits=0,
            is_signed=False,
        )
        record = CobolDataItem(name="IN-REC", level=1, location=SourceLocation(1, 1))
        field_ = ResolvedField(spec=spec, section="file", record=record)
        numeric = FieldConstraint(field_, "class_numeric", (), origin="test")
        assert satisfies(numeric, "00000000") is False
        assert satisfies(numeric, "0000000000") is True
        not_numeric = FieldConstraint(
            field_, "class_numeric", (), origin="test", negated=True
        )
        assert satisfies(not_numeric, "00000000") is True

    def test_figurative_space_and_zero(self):
        assert satisfies(self._constraint("figurative", "SPACES"), "   ") is True
        assert satisfies(self._constraint("figurative", "ZERO"), "0000") is True
        assert satisfies(self._constraint("figurative", "ZERO"), "0001") is False
        # LOW-VALUE/HIGH-VALUE have no text representation to compare.
        assert satisfies(self._constraint("figurative", "LOW-VALUES"), "  ") is None

    def test_an_unmodelled_op_is_undecidable(self):
        assert satisfies(self._constraint("no-such-op", "1"), "1") is None


# --- review findings on the path-folding machinery (Copilot, PR #198) -------


OR_SPLIT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORSPLIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).
           05  INV-TYPE       PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE
           PERFORM READ-ONE UNTIL WS-EOF = "Y"
           CLOSE INV-FILE.
       READ-ONE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF INV-QTY = 100 OR INV-QTY = 200
%s
           END-IF.
"""


def _inner_then(bundle):
    """The scenario for the inner branch's THEN arm."""
    return next(
        s
        for s in bundle.scenarios
        if "path condition from" in s.intent
        and s.intent.split(" (")[0].endswith("/THEN")
    )


class TestOrSplitEnclosingArms:
    """`_register_variants` registers `THEN#1`/`THEN#2`/... and NO bare
    `THEN` for a condition containing an OR, while `BranchConstraints.
    enclosing` names the base arm id. A plain lookup therefore misses every
    such arm, and the enclosing path silently went unfolded -- leaving
    exactly the "scenario named for an arm its data doesn't reach" problem
    this feature exists to remove."""

    def test_a_disjunctive_enclosing_arm_is_still_folded(self):
        inner = (
            '               IF INV-TYPE = "AB"\n'
            "                   ADD INV-QTY TO WS-TOTAL\n"
            "               END-IF"
        )
        bundle = _bundle(OR_SPLIT_SOURCE % inner)
        rows = _read_rows(_inner_then(bundle))
        assert rows
        for row in rows:
            # One of the enclosing disjuncts, not whatever chance produced.
            assert Decimal(row["INV-QTY"]) in (100, 200)
            assert row["INV-TYPE"].rstrip() == "AB"

    def test_the_satisfiable_disjunct_is_chosen_not_just_the_first(self):
        """`IF A = 100 OR A = 200 / IF A = 200`: folding the first disjunct
        would make the set unsatisfiable and report the inner arm as
        unreachable, when `A = 200` reaches it perfectly well."""
        inner = (
            "               IF INV-QTY = 200\n"
            "                   ADD INV-QTY TO WS-TOTAL\n"
            "               END-IF"
        )
        bundle = _bundle(OR_SPLIT_SOURCE % inner)
        scenario = _inner_then(bundle)
        assert scenario.verification["status"] == "verified"
        rows = _read_rows(scenario)
        assert rows
        for row in rows:
            assert Decimal(row["INV-QTY"]) == 200


class TestMergePropagatesPathGaps:
    def test_a_merged_candidates_path_gaps_are_not_dropped(self):
        """A merged-in candidate brings its own unpinned enclosing arms with
        it. Dropping them would let the merged scenario report "verified"
        while an arm it now claims is not actually pinned -- the silent
        false positive `path_gaps` exists to prevent."""
        from cobolparser.generators.scenarios import PlannedScenario, _merge_candidates

        first = PlannedScenario(name="a", intent="a", arm_keys=["B@1:1/THEN"])
        first.field_constraints = {"F1": []}
        second = PlannedScenario(
            name="b",
            intent="b",
            arm_keys=["B@2:1/THEN"],
            path_gaps=["enclosing arm B@1:1/THEN has no modeled constraints"],
        )
        second.field_constraints = {"F2": []}

        scenarios, outcomes = _merge_candidates([("1", first), ("2", second)])
        assert [o.status for o in outcomes] == ["targeted", "merged"]
        assert len(scenarios) == 1
        assert scenarios[0].path_gaps == [
            "enclosing arm B@1:1/THEN has no modeled constraints"
        ]


class TestSearchAtEndIsAnArm:
    def test_a_branch_under_search_at_end_records_that_enclosing_arm(self):
        """`_extract_search` registers an `arms["AT_END"]` entry, so a
        statement nested under `SEARCH ... AT END` does have an enclosing
        path condition to join to. Leaving it untagged made such a branch
        look top-level, and a scenario for it could read "verified" without
        its data establishing that the table search found nothing."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAB.
           05  WS-ENTRY  PIC X(2) OCCURS 3 TIMES INDEXED BY WS-IDX.
       01  WS-FLAG       PIC X VALUE "N".
       01  WS-TOTAL      PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ENTRY
               AT END
                   IF WS-FLAG = "Y"
                       ADD 1 TO WS-TOTAL
                   END-IF
               WHEN WS-ENTRY (WS-IDX) = "AB"
                   ADD 2 TO WS-TOTAL
           END-SEARCH.
"""
        result = parse_cobol(source, filename="t.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        constraints = ConstraintExtractor().extract(result.ast, index, report)

        search = next(b for b in constraints.branches if "AT_END" in b.arms)
        nested = [b for b in constraints.branches if b.enclosing]
        assert nested, [b.branch_id for b in constraints.branches]
        assert nested[0].enclosing == ((search.branch_id, "AT_END"),)
