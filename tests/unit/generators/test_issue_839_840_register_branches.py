"""Issues #839 and #840: an EVALUATE on a CALL's RETURN-CODE, and a branch
on the SQLCODE an EXEC SQL statement leaves, are driven by the boundary mock."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.data.options import DataGeneratorOptions

RC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RC3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN       PIC X(5).
       01  WS-RC       PIC S9(4) COMP.
       01  WS-MSG      PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUBX' USING WS-IN
           END-CALL
           MOVE RETURN-CODE TO WS-RC
           EVALUATE WS-RC
             WHEN 0 MOVE "OK" TO WS-MSG
             WHEN 12 MOVE "X" TO WS-MSG
             WHEN OTHER MOVE "Z" TO WS-MSG
           END-EVALUATE
           CALL 'SUBY' USING WS-IN
           EVALUATE RETURN-CODE
             WHEN 0 MOVE "OK" TO WS-MSG
             WHEN 4 THRU 8 MOVE "W" TO WS-MSG
           END-EVALUATE
           GOBACK.
"""

SQL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  HV-CNT      PIC S9(9) COMP.
       01  HV-ID       PIC X(5).
       01  WS-FLAG     PIC X.
       01  WS-RC       PIC S9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL DECLARE C1 CURSOR FOR SELECT ID FROM ACCT
           END-EXEC
           EXEC SQL SELECT COUNT(*) INTO :HV-CNT FROM ACCT END-EXEC
           IF SQLCODE < 0
              MOVE 'E' TO WS-FLAG
              GOBACK
           END-IF
           EXEC SQL OPEN C1 END-EXEC
           MOVE SQLCODE TO WS-RC
           EVALUATE WS-RC
             WHEN 0 CONTINUE
             WHEN -805 MOVE 'P' TO WS-FLAG
             WHEN OTHER MOVE 'Q' TO WS-FLAG
           END-EVALUATE
           PERFORM UNTIL SQLCODE NOT = 0
              EXEC SQL FETCH C1 INTO :HV-ID END-EXEC
           END-PERFORM
           IF SQLCODE NOT = 100
              MOVE 'X' TO WS-FLAG
           END-IF
           GOBACK.
"""


def _bundle(source: str):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=3))
    return generator.generate_with_scenarios(
        result.ast, index, report, mode="all", seed=7
    )


def _scenario(bundle, fragment: str):
    return next(s for s in bundle.scenarios if fragment in s.name)


def _call_rc(scenario, key: str) -> int:
    (fixture,) = [
        f for f in scenario.fixtures if f.ref.category == "CALL" and f.ref.key == key
    ]
    return int(fixture.sequence[0]["RETURN-CODE"])


def _sqlcode(scenario, key: str) -> int:
    (fixture,) = [
        f for f in scenario.fixtures if f.ref.category == "SQL" and f.ref.key == key
    ]
    return int(fixture.status["SQLCODE"])


def test_evaluate_arms_on_return_code_drive_the_call_mock():
    bundle = _bundle(RC_SOURCE)
    both_zero = _scenario(bundle, "EVALUATE@13 WHEN 0 ")
    assert _call_rc(both_zero, "SUBX") == 0 and _call_rc(both_zero, "SUBY") == 0
    assert _call_rc(_scenario(bundle, "EVALUATE@13 WHEN 12"), "SUBX") == 12
    other = _scenario(bundle, "EVALUATE@13 WHEN OTHER")
    assert _call_rc(other, "SUBX") not in (0, 12)
    assert 4 <= _call_rc(_scenario(bundle, "EVALUATE@19 WHEN 4..8"), "SUBY") <= 8
    edges = {
        _call_rc(s, "SUBY") for s in bundle.scenarios if "at RETURN-CODE" in s.name
    }
    assert edges == {4, 8}


def test_sqlcode_branches_drive_the_sql_mock_with_realistic_codes():
    bundle = _bundle(SQL_SOURCE)
    assert _sqlcode(_scenario(bundle, "IF@15 THEN"), "SELECT") < 0
    assert _sqlcode(_scenario(bundle, "IF@15 ELSE"), "SELECT") >= 0
    assert _sqlcode(_scenario(bundle, "WHEN -805"), "OPEN") == -805
    assert _sqlcode(_scenario(bundle, "WHEN 0"), "OPEN") == 0
    assert _sqlcode(_scenario(bundle, "WHEN OTHER"), "OPEN") not in (0, -805)
    # A negative witness is a code DB2 really returns, not a picture midpoint.
    assert _sqlcode(_scenario(bundle, "IF@15 THEN"), "SELECT") > -1000


def test_the_happy_path_is_all_zero_and_every_sqlcode_scenario_verifies():
    bundle = _bundle(SQL_SOURCE)
    happy = _scenario(bundle, "happy path")
    assert {_sqlcode(happy, k) for k in ("SELECT", "OPEN")} == {0}
    for scenario in bundle.scenarios:
        verification = scenario.verification or {}
        if "SQLCODE" in str(verification):
            assert verification["status"] == "verified", scenario.name
