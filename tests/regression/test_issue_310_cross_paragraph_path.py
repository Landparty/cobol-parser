"""Issue #310: a branch in a paragraph PERFORMed from inside another
paragraph's IF / EVALUATE arm got a ``verified`` scenario whose data never
reached it -- the guard on the PERFORM was not part of the path condition,
because `BranchConstraints.enclosing` stops at the top of the paragraph.

Option 1: a paragraph PERFORMed from exactly one arm takes that arm's guard.
Option 2: one reached from several guarded places gets a `path_gaps` entry,
so its scenario is ``unverified`` instead of claiming the arm.
"""

from __future__ import annotations

from cobolparser.generators import ProgramFixtureGenerator

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEEP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-CODE   PIC XX.
           05  IN-TYPE   PIC X.
           05  IN-AMT    PIC 9(5).
           05  IN-QTY    PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS   PIC XX.
       01  WS-EOF  PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM CHECK-PARA
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           GOBACK.
"""

ISSUE = HEADER + """\
       CHECK-PARA.
           IF IN-CODE = 'QQ'
               PERFORM DEEP-PARA
           END-IF
           EVALUATE IN-TYPE
               WHEN 'A'
                   PERFORM DEEP2-PARA
               WHEN 'B'
                   DISPLAY 'TYPE B'
           END-EVALUATE.
       DEEP-PARA.
           IF IN-AMT > 500
               DISPLAY 'BIG'
           ELSE
               DISPLAY 'SMALL'
           END-IF.
       DEEP2-PARA.
           IF IN-QTY > 10
               DISPLAY 'MANY'
           ELSE
               DISPLAY 'FEW'
           END-IF.
"""

TWO_GUARDED_SITES = HEADER + """\
       CHECK-PARA.
           IF IN-CODE = 'QQ'
               PERFORM DEEP-PARA
           END-IF
           IF IN-TYPE = 'A'
               PERFORM DEEP-PARA
           END-IF.
       DEEP-PARA.
           IF IN-AMT > 500
               DISPLAY 'BIG'
           ELSE
               DISPLAY 'SMALL'
           END-IF.
"""

ONE_UNGUARDED_SITE = HEADER + """\
       CHECK-PARA.
           IF IN-CODE = 'QQ'
               PERFORM DEEP-PARA
           END-IF
           PERFORM DEEP-PARA.
       DEEP-PARA.
           IF IN-AMT > 500
               DISPLAY 'BIG'
           ELSE
               DISPLAY 'SMALL'
           END-IF.
"""


def _bundle(tmp_path, source: str):
    path = tmp_path / "DEEP.cbl"
    path.write_text(source)
    return ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(path), mode="branches", seed=1
    )


def _scenarios_with(bundle, paragraph: str):
    return [s for s in bundle.scenarios if f"{paragraph}: " in s.name]


def _read_row(scenario) -> dict[str, str]:
    (read,) = [f for f in scenario.fixtures if f.ref.category == "READ"]
    return read.sequence[0]


def test_single_guarded_perform_folds_its_guard(tmp_path) -> None:
    bundle = _bundle(tmp_path, ISSUE)
    deep = _scenarios_with(bundle, "DEEP-PARA")
    deep2 = _scenarios_with(bundle, "DEEP2-PARA")
    assert deep and deep2
    for scenario in deep:
        assert _read_row(scenario)["IN-CODE"] == "QQ", scenario.name
        assert scenario.verification["status"] == "verified"
    for scenario in deep2:
        assert _read_row(scenario)["IN-TYPE"] == "A", scenario.name
        assert scenario.verification["status"] == "verified"


def test_several_guarded_performs_mark_the_scenario_unverified(tmp_path) -> None:
    bundle = _bundle(tmp_path, TWO_GUARDED_SITES)
    deep = _scenarios_with(bundle, "DEEP-PARA")
    assert deep
    for scenario in deep:
        assert scenario.verification["status"] == "unverified"
        assert any(
            "DEEP-PARA is reached from 2 places" in gap
            for gap in scenario.verification["gaps"]
        )


def test_an_unguarded_perform_needs_no_guard(tmp_path) -> None:
    bundle = _bundle(tmp_path, ONE_UNGUARDED_SITE)
    deep = _scenarios_with(bundle, "DEEP-PARA")
    assert deep
    for scenario in deep:
        assert scenario.verification["status"] == "verified"
        assert scenario.verification["gaps"] == []
