"""Per-row witness pinning (`PlannedScenario.row_witnesses`).

Groundwork for branches whose reachability is a property of the *sequence*
rather than of any single record -- "a prior '05' record sharing a key with a
following '09' record". `witnesses` cannot express that: it pins one value to
every generated row. Nothing in the planner populates `row_witnesses` yet (the
correlation analysis that would is designed but unbuilt -- see
docs/2026-09-04-cross-record-correlation-design.md); these tests pin the
plumbing so the pinning path is not the blocker when it is.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.scenarios import PlannedScenario

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ROWWIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-KEY          PIC X(04).
           05  F1-TYPE         PIC X(02).
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ.
"""


def _read_sequence(override: PlannedScenario | None, rows: int = 3):
    """The READ boundary's generated rows under *override*.

    Goes through `_build_fixture` (the seam `generate_with_scenarios` itself
    uses to apply a `PlannedScenario`) rather than the public entry points:
    nothing in the planner emits `row_witnesses` yet, so there is no program
    that would exercise this end to end.
    """
    result = parse_cobol(_SOURCE, filename="rowwit.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=rows, seed=7))
    boundary = next(b for b in report.boundaries if b.ref.category == "READ")
    fixture, _, _ = generator._build_fixture(
        boundary, index, 7, {}, "t", override=override
    )
    assert fixture is not None
    return fixture.sequence


def test_scenario_wide_witness_pins_every_row():
    """The existing behavior, grounded so the per-row case reads as a
    deliberate contrast rather than an accident."""
    override = PlannedScenario(
        name="all-rows", intent="t", witnesses={"F1-REC.F1-TYPE": "09"}
    )
    sequence = _read_sequence(override)
    assert [row["F1-TYPE"] for row in sequence] == ["09", "09", "09"]


def test_row_witness_overrides_only_its_own_row():
    override = PlannedScenario(
        name="correlated",
        intent="t",
        witnesses={"F1-REC.F1-TYPE": "09"},
        row_witnesses={0: {"F1-REC.F1-TYPE": "05"}},
    )
    sequence = _read_sequence(override)
    assert [row["F1-TYPE"] for row in sequence] == ["05", "09", "09"]


def test_row_witnesses_can_correlate_two_rows_on_a_shared_key():
    """The shape the planner cannot yet derive but can now express: row 0 is
    the '05' record and row 1 the '09' record, both carrying the same key."""
    override = PlannedScenario(
        name="prior-manual-then-forced",
        intent="t",
        row_witnesses={
            0: {"F1-REC.F1-KEY": "G100", "F1-REC.F1-TYPE": "05"},
            1: {"F1-REC.F1-KEY": "G100", "F1-REC.F1-TYPE": "09"},
        },
    )
    sequence = _read_sequence(override)
    assert sequence[0]["F1-KEY"] == sequence[1]["F1-KEY"] == "G100"
    assert sequence[0]["F1-TYPE"] == "05"
    assert sequence[1]["F1-TYPE"] == "09"


def test_a_pinned_row_beyond_the_default_length_still_gets_generated():
    """A witness pinned to a row the sequence never reaches would silently do
    nothing, so a per-row pin raises the minimum sequence length."""
    override = PlannedScenario(
        name="long", intent="t", row_witnesses={4: {"F1-REC.F1-TYPE": "77"}}
    )
    sequence = _read_sequence(override, rows=2)
    assert len(sequence) == 5
    assert sequence[4]["F1-TYPE"] == "77"


def test_row_witnesses_round_trip_through_to_dict():
    scenario = PlannedScenario(name="s", intent="t", row_witnesses={0: {"A.B": "01"}})
    assert scenario.to_dict()["row_witnesses"] == {0: {"A.B": "01"}}
