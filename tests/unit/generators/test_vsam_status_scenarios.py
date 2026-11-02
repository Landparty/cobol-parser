"""FILE STATUS scenarios of VSAM programs (#803 follow-up).

The planner's `mode="all"` families fail one file statement at a time
(`site_status_key`), with every FILE STATUS code the program tests that
statement for, and pin the path that runs the statement: the branch arms
that PERFORM its paragraph, and the INVALID KEY clause it sits in.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator
from cobolparser.generators.scenarios import ScenarioPlanner

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRAN-FILE ASSIGN TO TRANIN
               FILE STATUS IS WS-TRAN-FS.
           SELECT ACCT-KSDS ASSIGN TO ACCTKS
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS AC-ID
               ALTERNATE RECORD KEY IS AC-NAME WITH DUPLICATES
               FILE STATUS IS WS-ACCT-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TRAN-FILE.
       01  TRAN-REC.
           05 TR-CODE         PIC X.
           05 TR-ID           PIC 9(6).
           05 TR-NAME         PIC X(10).
       FD  ACCT-KSDS.
       01  ACCT-REC.
           05 AC-ID           PIC 9(6).
           05 AC-NAME         PIC X(10).
           05 AC-BAL          PIC 9(7).
       WORKING-STORAGE SECTION.
       01  WS-TRAN-FS         PIC XX.
       01  WS-ACCT-FS         PIC XX.
           88 ACCT-OK         VALUE '00'.
           88 ACCT-NOTFND     VALUE '23'.
       01  WS-EOF             PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT TRAN-FILE
           OPEN I-O ACCT-KSDS
           PERFORM UNTIL WS-EOF = 'Y'
               READ TRAN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-APPLY
               END-READ
           END-PERFORM
           CLOSE TRAN-FILE ACCT-KSDS
           GOBACK.
       1000-APPLY.
           EVALUATE TR-CODE
               WHEN 'C' PERFORM 2000-CHANGE
               WHEN 'N' PERFORM 3000-BY-NAME
               WHEN 'A' PERFORM 4000-ADD
           END-EVALUATE.
       2000-CHANGE.
           MOVE TR-ID TO AC-ID
           READ ACCT-KSDS
           IF ACCT-NOTFND
               DISPLAY 'NO ACCOUNT ' TR-ID
           ELSE
               ADD 1 TO AC-BAL
               REWRITE ACCT-REC
           END-IF.
       3000-BY-NAME.
           MOVE TR-NAME TO AC-NAME
           READ ACCT-KSDS KEY IS AC-NAME
           IF WS-ACCT-FS = '02'
               DISPLAY 'MORE THAN ONE ' TR-NAME
           END-IF.
       4000-ADD.
           MOVE TR-ID TO AC-ID
           READ ACCT-KSDS
               INVALID KEY
                   MOVE TR-NAME TO AC-NAME
                   WRITE ACCT-REC
                       INVALID KEY DISPLAY 'ADD FAILED ' WS-ACCT-FS
                   END-WRITE
           END-READ.
"""


def _plan():
    ast = parse_cobol(SOURCE, filename="VSTEST.cbl").ast
    assert ast is not None
    index = ProgramLayoutIndex.build(ast)
    report = BoundaryInventoryAnalyzer().analyze(ast, index)
    constraints = ConstraintExtractor().extract(ast, index, report)
    flow = ProgramFlowAnalyzer().analyze(ast)
    plan = ScenarioPlanner().plan(constraints, flow, report, mode="all")
    return ast, index, report, constraints, plan


def _line(report, category, key, paragraph):
    return next(
        b.ref.line
        for b in report.boundaries
        if b.ref.category == category
        and b.ref.key == key
        and b.ref.paragraph == paragraph
    )


def _by_name(plan, name):
    matches = [s for s in plan.scenarios if s.name == name]
    assert matches, [s.name for s in plan.scenarios]
    return matches[0]


def test_status_tests_collect_literals_and_88_values():
    _, _, _, constraints, _ = _plan()
    # ACCT-OK (00) is never tested, so it is not listed.
    assert constraints.status_tests["WS-ACCT-FS"] == ["02", "23"]


def test_write_boundary_carries_the_file_status_field():
    _, _, report, _, _ = _plan()
    writes = [b for b in report.boundaries if b.ref.category == "WRITE"]
    assert writes and writes[0].status_field == "WS-ACCT-FS"


def test_statement_sites_record_paragraph_and_handler_clause():
    _, _, report, constraints, _ = _plan()
    read_line = _line(report, "READ", "ACCT-KSDS", "4000-ADD")
    write_line = _line(report, "WRITE", "ACCT-REC", "4000-ADD")
    site = constraints.statement_sites[write_line]
    assert site.paragraph == "4000-ADD"
    assert site.handlers == ((read_line, "INVALID_KEY"),)
    assert str(write_line) in constraints.to_dict()["statement_sites"]


def test_file_status_scenario_fails_one_statement_on_its_path():
    _, _, report, _, plan = _plan()
    line = _line(report, "READ", "ACCT-KSDS", "2000-CHANGE")
    scenario = _by_name(plan, "file status 23: READ ACCT-KSDS")
    assert scenario.status_overrides == {f"READ:ACCT-KSDS@{line}": "23"}
    # 2000-CHANGE runs only for TR-CODE 'C'.
    assert scenario.witnesses["TRAN-REC.TR-CODE"] == "C"
    assert "path to the statement included" in scenario.intent


def test_alternate_key_read_gets_its_02_case():
    _, _, report, _, plan = _plan()
    line = _line(report, "READ", "ACCT-KSDS", "3000-BY-NAME")
    scenario = _by_name(plan, "file status 02: READ ACCT-KSDS")
    assert scenario.status_overrides == {f"READ:ACCT-KSDS@{line}": "02"}
    assert scenario.witnesses["TRAN-REC.TR-CODE"] == "N"


def test_write_in_an_invalid_key_clause_fails_the_outer_read_too():
    _, _, report, _, plan = _plan()
    read_line = _line(report, "READ", "ACCT-KSDS", "4000-ADD")
    write_line = _line(report, "WRITE", "ACCT-REC", "4000-ADD")
    scenario = _by_name(plan, "error status: WRITE ACCT-REC INVALID KEY")
    assert scenario.status_overrides == {
        f"WRITE:ACCT-REC@{write_line}": "22",
        f"READ:ACCT-KSDS@{read_line}": "23",
    }
    assert scenario.witnesses["TRAN-REC.TR-CODE"] == "A"


def test_failed_write_fixture_is_status_only():
    ast, index, report, _, _ = _plan()
    bundle = ProgramFixtureGenerator().generate_with_scenarios(
        ast, index, report, mode="all", seed=7
    )
    scenario = next(
        s
        for s in bundle.scenarios
        if s.name == "error status: WRITE ACCT-REC INVALID KEY"
    )
    write = next(f for f in scenario.fixtures if f.ref.category == "WRITE")
    assert write.direction == "STATUS_ONLY"
    assert write.status == {"WS-ACCT-FS": "22"}


def test_prime_key_read_never_gets_02():
    _, _, _, _, plan = _plan()
    # WRITE / REWRITE may return 02 too (the file has a duplicate alternate
    # key); among the READs only the one by that key can.
    twos = [s for s in plan.scenarios if s.name.startswith("file status 02: READ")]
    assert len(twos) == 1


def _plan_of(source: str, name: str):
    ast = parse_cobol(source, filename=f"{name}.cbl").ast
    assert ast is not None
    index = ProgramLayoutIndex.build(ast)
    report = BoundaryInventoryAnalyzer().analyze(ast, index)
    constraints = ConstraintExtractor().extract(ast, index, report)
    flow = ProgramFlowAnalyzer().analyze(ast)
    return (
        report,
        constraints,
        ScenarioPlanner().plan(constraints, flow, report, mode="all"),
    )


BROWSE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSBROWSE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-KSDS ASSIGN TO CUSTKS
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CK-ID
               ALTERNATE RECORD KEY IS CK-BRANCH WITH DUPLICATES
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-KSDS.
       01  CUST-REC.
           05 CK-ID           PIC 9(6).
           05 CK-BRANCH       PIC X(4).
       WORKING-STORAGE SECTION.
       01  WS-FS              PIC XX.
       01  WS-DONE            PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT CUST-KSDS
           PERFORM 1000-BY-BRANCH
           PERFORM 2000-BY-ID
           CLOSE CUST-KSDS
           GOBACK.
       1000-BY-BRANCH.
           MOVE 'B001' TO CK-BRANCH
           START CUST-KSDS KEY IS EQUAL CK-BRANCH
               INVALID KEY MOVE 'Y' TO WS-DONE
           END-START
           PERFORM UNTIL WS-DONE = 'Y'
               READ CUST-KSDS NEXT
                   AT END MOVE 'Y' TO WS-DONE
                   NOT AT END
                       IF WS-FS = '02'
                           DISPLAY 'SAME BRANCH FOLLOWS'
                       END-IF
               END-READ
           END-PERFORM.
       2000-BY-ID.
           MOVE 'N' TO WS-DONE
           MOVE 0 TO CK-ID
           START CUST-KSDS KEY IS NOT LESS THAN CK-ID
           PERFORM UNTIL WS-DONE = 'Y'
               READ CUST-KSDS NEXT
                   AT END MOVE 'Y' TO WS-DONE
               END-READ
           END-PERFORM.
"""


def test_sequential_read_by_a_duplicate_key_of_reference_gets_02():
    report, constraints, plan = _plan_of(BROWSE_SOURCE, "VSBROWSE")
    by_branch = _line(report, "READ", "CUST-KSDS", "1000-BY-BRANCH")
    by_id = _line(report, "READ", "CUST-KSDS", "2000-BY-ID")
    # The START before it in its paragraph set the key of reference.
    assert constraints.statement_sites[by_branch].duplicate_key
    assert not constraints.statement_sites[by_id].duplicate_key
    scenario = _by_name(plan, "file status 02: READ CUST-KSDS")
    assert scenario.status_overrides == {f"READ:CUST-KSDS@{by_branch}": "02"}
    twos = [s for s in plan.scenarios if s.name.startswith("file status 02: READ")]
    assert len(twos) == 1


ESDS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSLOG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT AUD-ESDS ASSIGN TO AUDESDS
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-FS.
           SELECT SLOT-RRDS ASSIGN TO SLOTS
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS WS-SLOT
               FILE STATUS IS WS-RFS.
       DATA DIVISION.
       FILE SECTION.
       FD  AUD-ESDS.
       01  AUD-REC            PIC X(20).
       FD  SLOT-RRDS.
       01  SLOT-REC           PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-FS              PIC XX.
       01  WS-RFS             PIC XX.
       01  WS-SLOT            PIC 9(4).
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN EXTEND AUD-ESDS
           IF WS-FS = '35'
               OPEN OUTPUT AUD-ESDS
           END-IF
           OPEN I-O SLOT-RRDS
           MOVE 'EVENT' TO AUD-REC
           WRITE AUD-REC
           IF WS-FS NOT = '00'
               DISPLAY 'WRITE FAILED ' WS-FS
           END-IF
           MOVE 1 TO WS-SLOT
           WRITE SLOT-REC
           IF WS-RFS NOT = '00'
               DISPLAY 'SLOT FAILED ' WS-RFS
           END-IF
           CLOSE AUD-ESDS SLOT-RRDS
           GOBACK.
"""


def test_sequential_write_fails_with_34_and_relative_with_22():
    report, constraints, plan = _plan_of(ESDS_SOURCE, "VSLOG")
    esds_line = _line(report, "WRITE", "AUD-REC", "0000-MAIN")
    assert constraints.statement_sites[esds_line].organization == "SEQUENTIAL"
    esds = _by_name(plan, "file status 34: WRITE AUD-REC")
    assert esds.status_overrides == {f"WRITE:AUD-REC@{esds_line}": "34"}
    assert not [s for s in plan.scenarios if s.name == "file status 22: WRITE AUD-REC"]
    rrds_line = _line(report, "WRITE", "SLOT-REC", "0000-MAIN")
    assert constraints.statement_sites[rrds_line].organization == "RELATIVE"
    _by_name(plan, "file status 22: WRITE SLOT-REC")


def test_open_output_is_never_given_35():
    report, constraints, plan = _plan_of(ESDS_SOURCE, "VSLOG")
    opens = [
        b
        for b in report.boundaries
        if b.ref.category == "OPEN" and b.ref.key == "AUD-ESDS"
    ]
    modes = [dict(constraints.statement_sites[b.ref.line].open_modes) for b in opens]
    assert modes == [{"AUD-ESDS": "EXTEND"}, {"AUD-ESDS": "OUTPUT"}]
    output_line = opens[1].ref.line
    for scenario in plan.scenarios:
        assert f"OPEN:AUD-ESDS@{output_line}" not in scenario.status_overrides
    extend = _by_name(plan, "error status: OPEN AUD-ESDS not found")
    assert extend.status_overrides == {f"OPEN:AUD-ESDS@{opens[0].ref.line}": "35"}
