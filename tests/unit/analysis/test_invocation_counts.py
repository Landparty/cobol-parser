"""Unit tests for cobolparser.analysis.invocation_counts (issue #363)."""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.invocation_counts import count_invocations
from cobolparser.generators.data.program_layout import ProgramLayoutIndex
from cobolparser.models.statements.control import PerformStatement

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNTS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS IN-KEY
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY          PIC X(5).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
           88  WS-FS-OK        VALUE '00'.
           88  WS-FS-GOOD      VALUE '00' THRU '09'.
           88  WS-FS-BAD       VALUE '10' '23' '35'.
       01  WS-IN              PIC X.
       01  WS-N                PIC 9.
       01  WS-RATE             PIC 9(3).
       PROCEDURE DIVISION.
"""


def _counts(procedure: str) -> dict[str, list[int | None]]:
    result = parse_cobol(_HEADER + procedure, filename="counts.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    counts = count_invocations(result.ast, report, index)
    found: dict[str, list[int | None]] = {}
    for boundary in report.boundaries:
        ref = boundary.ref
        found.setdefault(f"{ref.category}:{ref.key}", []).append(
            counts.for_boundary(ref)
        )
    return found


def test_status_check_through_a_level_88_does_not_hide_later_counts():
    found = _counts("""\
       MAIN-PARA.
           OPEN INPUT IN-FILE
           IF NOT WS-FS-OK
              DISPLAY 'OPEN FAILED'
              GOBACK
           END-IF
           ACCEPT WS-IN
           STOP RUN.
""")
    assert found["OPEN:IN-FILE"] == [1]
    assert found["ACCEPT:WS-IN"] == [1]


def test_status_check_mixed_with_data_is_not_exempt():
    found = _counts("""\
       MAIN-PARA.
           OPEN INPUT IN-FILE
           IF WS-FS NOT = '00' OR WS-IN = 'X'
              STOP RUN
           END-IF
           ACCEPT WS-IN
           STOP RUN.
""")
    assert found["OPEN:IN-FILE"] == [1]
    assert found["ACCEPT:WS-IN"] == [None]


def test_invalid_key_handler_is_decided_by_the_status_fixture():
    found = _counts("""\
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE
               INVALID KEY STOP RUN
           END-READ
           ACCEPT WS-IN
           CLOSE IN-FILE
           STOP RUN.
""")
    assert found["READ:IN-FILE"] == [1]
    assert found["ACCEPT:WS-IN"] == [1]
    assert found["CLOSE:IN-FILE"] == [1]


def test_evaluate_arms_are_unknown_and_a_stop_in_one_hides_the_rest():
    found = _counts("""\
       MAIN-PARA.
           ACCEPT WS-IN
           EVALUATE WS-IN
               WHEN 'A' CALL 'GETRATE' USING WS-RATE
               WHEN OTHER STOP RUN
           END-EVALUATE
           CALL 'AFTER' USING WS-RATE
           STOP RUN.
""")
    assert found["ACCEPT:WS-IN"] == [1]
    assert found["CALL:GETRATE"] == [None]
    assert found["CALL:AFTER"] == [None]


def test_variable_times_and_varying_bodies_are_unknown():
    found = _counts("""\
       MAIN-PARA.
           PERFORM WS-N TIMES
               CALL 'VARTIMES' USING WS-RATE
           END-PERFORM
           PERFORM VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 3
               CALL 'VARYING' USING WS-RATE
           END-PERFORM
           CALL 'AFTER' USING WS-RATE
           STOP RUN.
""")
    assert found["CALL:VARTIMES"] == [None]
    assert found["CALL:VARYING"] == [None]
    assert found["CALL:AFTER"] == [1]


def test_exit_paragraph_on_the_main_line_hides_what_follows():
    found = _counts("""\
       MAIN-PARA.
           PERFORM SUB-PARA
           STOP RUN.
       SUB-PARA.
           CALL 'BEFORE' USING WS-RATE
           EXIT PARAGRAPH
           CALL 'AFTER' USING WS-RATE.
""")
    assert found["CALL:BEFORE"] == [1]
    assert found["CALL:AFTER"] == [None]


def test_a_transfer_inside_a_literal_times_body_reports_nothing():
    found = _counts("""\
       MAIN-PARA.
           CALL 'FIRST' USING WS-RATE
           PERFORM 3 TIMES
               CALL 'LOOPED' USING WS-RATE
               GO TO END-PARA
           END-PERFORM.
       END-PARA.
           STOP RUN.
""")
    assert found["CALL:FIRST"] == [None]
    assert found["CALL:LOOPED"] == [None]


def test_paragraph_reached_by_fall_through_and_perform_counts_both():
    found = _counts("""\
       MAIN-PARA.
           PERFORM SUB-PARA.
       SUB-PARA.
           CALL 'TWICE' USING WS-RATE.
""")
    assert found["CALL:TWICE"] == [2]


def test_unknown_perform_target_hides_what_follows():
    found = _counts("""\
       MAIN-PARA.
           CALL 'BEFORE' USING WS-RATE
           PERFORM NO-SUCH-PARA
           CALL 'AFTER' USING WS-RATE
           STOP RUN.
""")
    assert found["CALL:BEFORE"] == [1]
    assert found["CALL:AFTER"] == [None]


def test_count_at_reports_a_perform_statement():
    source = _HEADER + """\
       MAIN-PARA.
           PERFORM SUB-PARA
           STOP RUN.
       SUB-PARA.
           ACCEPT WS-IN.
"""
    result = parse_cobol(source, filename="counts.cbl")
    assert result.ast is not None
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    counts = count_invocations(result.ast, report, index)
    perform_line = source.splitlines().index("           PERFORM SUB-PARA") + 1
    assert counts.count_at(perform_line, PerformStatement) == 1
    assert counts.count_at(perform_line + 100, PerformStatement) is None


def test_go_to_out_of_a_performed_paragraph_reports_nothing():
    found = _counts("""\
       MAIN-PARA.
           CALL 'FIRST' USING WS-RATE
           PERFORM SUB-PARA
           STOP RUN.
       SUB-PARA.
           GO TO END-PARA.
       END-PARA.
           STOP RUN.
""")
    assert found["CALL:FIRST"] == [None]


def test_go_to_depending_on_reports_nothing():
    found = _counts("""\
       MAIN-PARA.
           CALL 'FIRST' USING WS-RATE
           GO TO A-PARA B-PARA DEPENDING ON WS-N.
       A-PARA.
           STOP RUN.
       B-PARA.
           STOP RUN.
""")
    assert found["CALL:FIRST"] == [None]


def test_a_program_with_alter_follows_no_go_to():
    found = _counts("""\
       MAIN-PARA.
           ALTER SWITCH-PARA TO PROCEED TO B-PARA
           CALL 'FIRST' USING WS-RATE
           GO TO A-PARA.
       SWITCH-PARA.
           GO TO A-PARA.
       A-PARA.
           STOP RUN.
       B-PARA.
           STOP RUN.
""")
    assert found["CALL:FIRST"] == [None]


def test_go_to_a_section_continues_at_its_first_paragraph():
    found = _counts("""\
       MAIN-SECTION SECTION.
       MAIN-PARA.
           GO TO LATER-SECTION.
       SKIPPED-PARA.
           CALL 'NEVER' USING WS-RATE.
       LATER-SECTION SECTION.
       LATER-PARA.
           CALL 'AFTER' USING WS-RATE
           STOP RUN.
""")
    assert found["CALL:AFTER"] == [1]
    assert found["CALL:NEVER"] == [None]


def test_go_to_an_unknown_target_reports_nothing():
    found = _counts("""\
       MAIN-PARA.
           CALL 'FIRST' USING WS-RATE
           GO TO NO-SUCH-PARA.
""")
    assert found["CALL:FIRST"] == [None]


# -- issue #590: the arm a success status takes is not exempt -------------

_STATUS_CHECK = """\
       MAIN-PARA.
           OPEN INPUT IN-FILE
           IF {condition}
              {then_arm}
           ELSE
              {else_arm}
           END-IF
           CALL 'ERRLOG' USING WS-IN
           STOP RUN.
"""


def _status_check(condition: str, goback_arm: str) -> dict[str, list[int | None]]:
    arms = {"then_arm": "CONTINUE", "else_arm": "CONTINUE"}
    arms[f"{goback_arm}_arm"] = "GOBACK"
    return _counts(_STATUS_CHECK.format(condition=condition, **arms))


@pytest.mark.parametrize(
    ("condition", "success_arm"),
    [
        ("WS-FS = '00'", "then"),
        ("WS-FS-OK", "then"),
        ("WS-FS NOT = '00'", "else"),
        ("NOT WS-FS-OK", "else"),
        ("'00' = WS-FS", "then"),
        ("WS-FS = ZEROS", "then"),
        ("WS-FS = '00' OR WS-FS = '97'", "then"),
        ("WS-FS > '09'", "else"),
        ("WS-FS-GOOD", "then"),
        ("WS-FS-BAD", "else"),
    ],
)
def test_success_arm_that_ends_the_run_hides_what_follows(condition, success_arm):
    found = _status_check(condition, success_arm)
    assert found["OPEN:IN-FILE"] == [1]
    # On success the GOBACK runs, so ERRLOG runs 0 times: never "once".
    assert found["CALL:ERRLOG"] == [None]


@pytest.mark.parametrize(
    ("condition", "error_arm"),
    [
        ("WS-FS = '00'", "else"),
        ("WS-FS-OK", "else"),
        ("WS-FS NOT = '00'", "then"),
        ("WS-FS > '09'", "then"),
        ("WS-FS-GOOD", "else"),
        ("WS-FS-BAD", "then"),
    ],
)
def test_error_arm_that_ends_the_run_stays_exempt(condition, error_arm):
    assert _status_check(condition, error_arm)["CALL:ERRLOG"] == [1]


def test_status_check_that_cannot_be_evaluated_exempts_neither_arm():
    # A class test: which arm success takes is not worked out, so a transfer
    # in either arm makes what follows uncertain.
    found = _status_check("WS-FS IS NUMERIC", "else")
    assert found["CALL:ERRLOG"] == [None]


def test_sqlcode_success_arm_that_ends_the_run_hides_what_follows():
    found = _counts("""\
       MAIN-PARA.
           EXEC SQL
               SELECT RATE INTO :WS-RATE FROM RATES
           END-EXEC
           IF SQLCODE = 0
              GOBACK
           END-IF
           CALL 'ERRLOG' USING WS-IN
           STOP RUN.
""")
    assert found["CALL:ERRLOG"] == [None]


def test_sqlcode_error_arm_that_ends_the_run_stays_exempt():
    found = _counts("""\
       MAIN-PARA.
           EXEC SQL
               SELECT RATE INTO :WS-RATE FROM RATES
           END-EXEC
           IF SQLCODE < 0
              GOBACK
           END-IF
           CALL 'ERRLOG' USING WS-IN
           STOP RUN.
""")
    assert found["CALL:ERRLOG"] == [1]
