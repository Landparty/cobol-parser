"""Branch scenarios a CICS program needs (2026-11-02): the EIB and the
COMMAREA are its inputs, a never-changed WORKING-STORAGE VALUE is a
literal, ``DFHRESP(...)`` is its number, and each numeric comparison is
also targeted at its edge."""

from pathlib import Path

from cobolparser.generators import ProgramFixtureGenerator

CUSTVAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAX-ID              PIC 9(6) VALUE 899999.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-CUST-ID         PIC 9(6).
           05  LK-RESULT          PIC X(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF LK-CUST-ID > 0 AND LK-CUST-ID NOT > WS-MAX-ID
               MOVE 'OK' TO LK-RESULT
           ELSE
               MOVE 'NO' TO LK-RESULT
           END-IF
           EXEC CICS RETURN END-EXEC.
"""

PSEUDO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PSEUDO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                PIC S9(8) COMP.
       01  WS-REC                 PIC X(10).
       01  WS-STATE               PIC X.
       LINKAGE SECTION.
       01  DFHCOMMAREA            PIC X.
       PROCEDURE DIVISION.
       0000-MAIN.
           IF EIBCALEN = 0
               MOVE 'F' TO WS-STATE
           ELSE
               PERFORM 2000-NEXT
           END-IF
           EXEC CICS RETURN END-EXEC.
       2000-NEXT.
           EXEC CICS READ FILE('CUSTFIL') INTO(WS-REC)
               RIDFLD(WS-STATE) RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(NOTFND)
               MOVE 'N' TO WS-STATE
           END-IF.
"""


def _bundle(tmp_path: Path, source: str) -> dict:
    path = tmp_path / "prog.cbl"
    path.write_text(source)
    generator = ProgramFixtureGenerator(entry_parameters=True)
    return generator.generate_with_scenarios_from_file(
        str(path), mode="branches", seed=7
    ).to_dict(bundle_version=1)


def _entry(scenario: dict) -> dict:
    parameters = scenario["entry_parameters"]
    return parameters["sequence"][0] if parameters else {}


def test_commarea_is_an_input_and_a_value_item_is_a_literal(tmp_path):
    bundle = _bundle(tmp_path, CUSTVAL)
    statuses = {
        d["arm_key"]: d["status"] for d in bundle["scenario_coverage"]["details"]
    }
    assert statuses["0000-MAIN@12:5/THEN"] == "targeted"
    ids = [_entry(s).get("LK-CUST-ID") for s in bundle["scenarios"][1:]]
    # Both edges of the THEN arm: 1 and exactly WS-MAX-ID's VALUE.
    assert "1" in ids and "899999" in ids
    assert "900000" in ids


def test_eib_fields_on_the_path_are_set_only_where_needed(tmp_path):
    bundle = _bundle(tmp_path, PSEUDO)
    happy, *branches = bundle["scenarios"]
    assert "EIBCALEN" not in _entry(happy)
    by_name = {s["name"]: _entry(s) for s in branches}
    first = next(v for k, v in by_name.items() if "IF@12 THEN" in k)
    assert first["EIBCALEN"] == "0"
    # The NOTFND arm in 2000-NEXT is reached only with EIBCALEN not 0.
    notfnd = next(
        s for s in branches if s["name"].startswith("2000-NEXT") and "THEN" in s["name"]
    )
    assert _entry(notfnd)["EIBCALEN"] != "0"
    read = next(f for f in notfnd["fixtures"] if f["category"] == "CICS")
    assert read["sequence"][0]["WS-RESP"] == "13"


SCREEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCREEN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  KEYS.
           05  KEY-ENTER          PIC X VALUE X'7D'.
           05  KEY-PF3            PIC X VALUE '3'.
       01  WS-RESP                PIC S9(8) COMP.
       01  WS-REC                 PIC X(10).
       01  WS-STATE               PIC X.
       LINKAGE SECTION.
       01  DFHCOMMAREA            PIC X.
       PROCEDURE DIVISION.
       0000-MAIN.
           EVALUATE EIBAID
               WHEN KEY-PF3
                   MOVE 'X' TO WS-STATE
               WHEN KEY-ENTER
                   PERFORM 2000-READ
               WHEN OTHER
                   MOVE 'I' TO WS-STATE
           END-EVALUATE
           EXEC CICS RETURN END-EXEC.
       2000-READ.
           EXEC CICS READ FILE('CUSTFIL') INTO(WS-REC)
               RIDFLD(WS-STATE) RESP(WS-RESP)
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE 'F' TO WS-STATE
               WHEN DFHRESP(NOTFND)
                   MOVE 'N' TO WS-STATE
               WHEN OTHER
                   MOVE 'E' TO WS-STATE
           END-EVALUATE.
"""


def test_when_selectors_naming_constants_and_dfhresp_are_targeted(tmp_path):
    """`EVALUATE EIBAID WHEN DFHENTER` (a DFHAID constant) and `EVALUATE
    WS-RESP WHEN DFHRESP(NOTFND)` were "not supported in v1": a CICS
    screen program's second screen was never generated (stress test
    2026-11-02, ORDINQ). A WHEN now folds both, as the IF path does."""
    bundle = _bundle(tmp_path, SCREEN)
    statuses = {
        d["arm_key"]: d["status"] for d in bundle["scenario_coverage"]["details"]
    }
    assert set(statuses.values()) == {"targeted"}, statuses
    by_name = {s["name"]: s for s in bundle["scenarios"]}
    pf3 = next(s for k, s in by_name.items() if k.endswith("WHEN KEY-PF3"))
    assert _entry(pf3)["EIBAID"] == "3"
    notfnd = next(s for k, s in by_name.items() if "DFHRESP" in k and "NOTFND" in k)
    read = next(f for f in notfnd["fixtures"] if f["category"] == "CICS")
    assert read["sequence"][0]["WS-RESP"] == "13"
