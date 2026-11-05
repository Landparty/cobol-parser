"""Bug hunt of 2026-11-05 (round 2) on generated test cases: a scenario
named for a branch arm whose data ran another arm, while it was reported
verified.

* COMPOUND: ``EVALUATE TRUE / WHEN TYPE-RETAIL AND IN-AGE < 18 / WHEN
  TYPE-RETAIL`` -- the compound WHEN was unsupported, so the second arm's
  data did not negate it: its row was a retail minor, which runs the first
  arm. The first arm was never targeted at all.
* RANGES: a later arm negates a THRU range through the bound that is still
  satisfiable (``WHEN 0 THRU 17 / WHEN 18 THRU 64 / WHEN OTHER``), so WHEN
  OTHER is generated (> 64) instead of being missed as "not modeled".
* PRIMING: a priming arm that ends the loop (``WHEN 'GB' SET WS-EOF TO
  TRUE``) was merged with an arm inside the loop into one scenario, which
  could never reach the second.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HUNT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO INDD
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-F.
       01  IN-REC.
           05  IN-TYPE        PIC X.
               88  TYPE-RETAIL  VALUE "R".
               88  TYPE-CORP    VALUE "C".
           05  IN-AGE         PIC 9(3).
           05  IN-STAT        PIC XX.
       WORKING-STORAGE SECTION.
       01  WS-FS              PIC XX.
       01  WS-EOF             PIC X VALUE "N".
           88  END-OF-FILE    VALUE "Y".
       01  WS-OUT             PIC X(10).
       PROCEDURE DIVISION.
"""

COMPOUND = _HEADER + """\
       MAIN-PARA.
           OPEN INPUT IN-F
           READ IN-F
           EVALUATE TRUE
               WHEN TYPE-RETAIL AND IN-AGE < 18
                   MOVE "MINOR" TO WS-OUT
               WHEN TYPE-RETAIL
                   MOVE "RETAIL" TO WS-OUT
               WHEN TYPE-CORP OR IN-AGE > 900
                   MOVE "CORP" TO WS-OUT
               WHEN OTHER
                   MOVE "OTHER" TO WS-OUT
           END-EVALUATE
           EVALUATE IN-AGE
               WHEN 0 THRU 17
                   MOVE "YOUNG" TO WS-OUT
               WHEN 18 THRU 64
                   MOVE "ADULT" TO WS-OUT
               WHEN OTHER
                   MOVE "SENIOR" TO WS-OUT
           END-EVALUATE
           CLOSE IN-F
           STOP RUN.
"""

PRIMING = _HEADER + """\
       MAIN-PARA.
           OPEN INPUT IN-F
           PERFORM 1000-PRIME
           PERFORM 2000-LOOP UNTIL END-OF-FILE
           CLOSE IN-F
           STOP RUN.
       1000-PRIME.
           READ IN-F
           EVALUATE IN-STAT
               WHEN "OK"
                   CONTINUE
               WHEN "GB"
                   SET END-OF-FILE TO TRUE
           END-EVALUATE.
       2000-LOOP.
           IF IN-AGE > 50
               MOVE "OLD" TO WS-OUT
           END-IF
           READ IN-F
               AT END SET END-OF-FILE TO TRUE
           END-READ.
"""


def _analyze(source: str):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return result.ast, index, report


def _scenarios(source: str, seed: int = 1):
    ast, index, report = _analyze(source)
    return ProgramFixtureGenerator().generate_with_scenarios(
        ast, index, report, mode="branches", seed=seed
    )


def _rows(scenario) -> list[dict[str, str]]:
    return [
        row
        for fixture in scenario.fixtures
        for row in fixture.sequence
        if "IN-TYPE" in row
    ]


def _arm_of(row: dict[str, str]) -> str:
    """The arm COMPOUND's first EVALUATE runs for `row`."""
    kind, age = row["IN-TYPE"], int(row["IN-AGE"])
    if kind == "R" and age < 18:
        return "WHEN_1"
    if kind == "R":
        return "WHEN_2"
    if kind == "C" or age > 900:
        return "WHEN_3"
    return "WHEN_OTHER"


def test_compound_when_is_modeled_and_negated_by_later_arms():
    ast, index, report = _analyze(COMPOUND)
    first = next(b for b in ConstraintExtractor().extract(ast, index, report).branches)
    assert sorted((c.field.spec.name, c.op) for c in first.arms["WHEN_1"]) == [
        ("IN-AGE", "lt"),
        ("IN-TYPE", "in_set"),
    ]
    # NOT (RETAIL AND AGE < 18) for a retail row is AGE >= 18.
    assert ("IN-AGE", "ge", ("18",)) in [
        (c.field.spec.name, c.op, c.values) for c in first.arms["WHEN_2"]
    ]
    # The OR arm is one variant per leg.
    assert {"WHEN_3#1", "WHEN_3#2"} <= set(first.arms)


def _line_of(source: str, text: str) -> int:
    return next(
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if line.strip() == text
    )


def test_every_compound_arm_case_runs_its_arm():
    first = _line_of(COMPOUND, "EVALUATE TRUE")
    checked = 0
    for seed in (1, 2, 3):
        for scenario in _scenarios(COMPOUND, seed).scenarios:
            for arm_key in _arm_keys(scenario):
                position, arm = arm_key.split("@", 1)[1].split("/")
                if int(position.split(":")[0]) != first:
                    continue
                for row in _rows(scenario):
                    assert _arm_of(row) == arm.split("#")[0], (scenario.name, row)
                    checked += 1
    assert checked


def _arm_keys(scenario) -> list[str]:
    intent = (scenario.intent or "").split(" (path condition")[0]
    return [word.strip(",;") for word in intent.split() if "@" in word and "/" in word]


def test_when_other_after_ranges_is_targeted():
    second = _line_of(COMPOUND, "EVALUATE IN-AGE")
    bundle = _scenarios(COMPOUND)
    others = [
        s
        for s in bundle.scenarios
        if any(
            k.split("@", 1)[1].startswith(f"{second}:") and k.endswith("/WHEN_OTHER")
            for k in _arm_keys(s)
        )
    ]
    assert others, [(s.name, s.intent) for s in bundle.scenarios]
    for scenario in others:
        assert all(int(row["IN-AGE"]) > 64 for row in _rows(scenario))


def test_a_loop_ending_arm_is_never_merged():
    ast, index, report = _analyze(PRIMING)
    branches = ConstraintExtractor().extract(ast, index, report).branches
    prime = next(b for b in branches if b.parent_proc == "1000-PRIME")
    assert prime.ending_arms == frozenset({"WHEN_2"})
    bundle = _scenarios(PRIMING)
    (ending,) = [s for s in bundle.scenarios if "WHEN GB" in s.name]
    assert "+" not in ending.name, ending.name
    assert any("2000-LOOP: IF@" in s.name for s in bundle.scenarios)


STOPPING = _HEADER + """\
       MAIN-PARA.
           OPEN INPUT IN-F
           READ IN-F
           EVALUATE IN-STAT
               WHEN "OK"
                   MOVE "FINE" TO WS-OUT
               WHEN "WN"
                   MOVE "WARN" TO WS-OUT
               WHEN OTHER
                   STOP RUN
           END-EVALUATE
           IF IN-AGE > 50
               MOVE "OLD" TO WS-OUT
           END-IF
           CLOSE IN-F
           STOP RUN.
"""


def test_a_branch_below_a_stop_run_arm_keeps_a_staying_arm():
    """`WHEN OTHER STOP RUN` above `IF IN-AGE > 50`: the IF's cases left
    IN-STAT to chance, and a random status stopped the run before the IF
    while the case was reported verified."""
    bundle = _scenarios(STOPPING)
    cases = [s for s in bundle.scenarios if "IF@" in s.name]
    assert cases
    for scenario in cases:
        assert "WHEN_1|WHEN_2" in scenario.intent
        stats = {row["IN-STAT"] for row in _rows(scenario)}
        assert stats and stats <= {"OK", "WN"}, (scenario.name, stats)
