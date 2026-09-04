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
    def test_the_extractor_records_each_branchs_enclosing_arms(self):
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


class TestSelfVerification:
    def test_every_branch_scenario_carries_a_verdict(self):
        bundle = _bundle(NESTED_SOURCE)
        assert bundle.scenarios
        for scenario in bundle.scenarios:
            assert scenario.verification is not None
            assert scenario.verification["status"] in ("verified", "unverified")

    def test_a_well_pinned_scenario_verifies_against_its_own_data(self):
        bundle = _bundle(NESTED_SOURCE)
        for scenario in bundle.scenarios:
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

    def test_an_undecidable_comparison_is_reported_not_assumed_good(self):
        """`IF WS-INPUT > 0` on a `PIC X` field: the solver has no numeric
        domain to work in and the generated text cannot be ordered against a
        numeric literal at all. "I could not check this" and "this is fine"
        are different answers, and the bundle says which one it means."""
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
        assert bundle.scenarios
        for scenario in bundle.scenarios:
            assert scenario.verification["status"] == "unverified"
            statuses = {v["status"] for v in scenario.verification["fields"]}
            assert statuses == {"unknown"}

    def test_verification_is_serialized_into_the_bundle_json(self):
        import json

        bundle = _bundle(NESTED_SOURCE)
        payload = json.loads(bundle.to_json())
        assert all("verification" in s for s in payload["scenarios"])


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

    def test_figurative_space_and_zero(self):
        assert satisfies(self._constraint("figurative", "SPACES"), "   ") is True
        assert satisfies(self._constraint("figurative", "ZERO"), "0000") is True
        assert satisfies(self._constraint("figurative", "ZERO"), "0001") is False
        # LOW-VALUE/HIGH-VALUE have no text representation to compare.
        assert satisfies(self._constraint("figurative", "LOW-VALUES"), "  ") is None

    def test_an_unmodelled_op_is_undecidable(self):
        assert satisfies(self._constraint("no-such-op", "1"), "1") is None
