"""IOSequenceAnalyzer: IF / EVALUATE arms are forked and merged (issue #380).

Each arm runs from the state at the branch; afterwards a file holds every
state an arm that falls out of the branch left it in. An arm that ends in a
STOP RUN / GOBACK / GO TO (its own, or a PERFORMed paragraph's) is left out
of the merge. A violation needs to hold on every merged path, except
FILE_LEFT_OPEN, which any path still earns.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer, IOViolationKind

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRANCHY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO RPTDD.
           SELECT OUT-FILE ASSIGN TO OUTDD
               FILE STATUS IS WS-OUT-STAT.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE.
       01  RPT-REC PIC X(80).
       FD  OUT-FILE.
       01  OUT-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-MODE PIC X.
       01  WS-OUT-STAT PIC XX.
       01  WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
"""


def _kinds(procedure: str) -> list[tuple[str, str]]:
    result = parse_cobol(_HEADER + procedure)
    assert result.ast is not None, result.errors
    report = IOSequenceAnalyzer().analyze(result.ast)
    return [(v.kind.name, v.file_name.upper()) for v in report.violations]


def test_issue_380_reproduction_is_clean() -> None:
    assert _kinds("""\
       0000-MAIN.
           IF WS-MODE = 'N' OPEN OUTPUT RPT-FILE
           ELSE OPEN EXTEND RPT-FILE END-IF
           OPEN INPUT OUT-FILE
           IF WS-OUT-STAT NOT = '00'
              DISPLAY 'OPEN FAILED' CLOSE RPT-FILE
              MOVE 16 TO RETURN-CODE STOP RUN
           END-IF
           PERFORM 1000-COPY UNTIL WS-EOF = 'Y'
           CLOSE OUT-FILE RPT-FILE
           STOP RUN.
       1000-COPY.
           READ OUT-FILE AT END MOVE 'Y' TO WS-EOF
           NOT AT END WRITE RPT-REC FROM OUT-REC END-READ.
""") == []


def test_open_in_both_arms_then_again_is_still_a_double_open() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           IF WS-MODE = 'N' OPEN OUTPUT RPT-FILE
           ELSE OPEN EXTEND RPT-FILE END-IF
           OPEN OUTPUT RPT-FILE
           CLOSE RPT-FILE
           STOP RUN.
""")
    assert kinds == [("DOUBLE_OPEN", "RPT-FILE")]


def test_open_on_one_path_only_is_neither_unopened_nor_double_opened() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           IF WS-MODE = 'N' OPEN OUTPUT RPT-FILE END-IF
           WRITE RPT-REC
           OPEN OUTPUT RPT-FILE
           CLOSE RPT-FILE
           STOP RUN.
""")
    assert kinds == []


def test_never_opened_on_any_path_is_still_reported() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           IF WS-MODE = 'N'
              IF WS-EOF = 'Y' DISPLAY 'X' ELSE READ OUT-FILE END-IF
           END-IF
           STOP RUN.
""")
    assert kinds == [("READ_BEFORE_OPEN", "OUT-FILE")]


def test_closed_in_both_arms_then_closed_again_is_a_double_close() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-MODE = 'N' CLOSE OUT-FILE ELSE CLOSE OUT-FILE END-IF
           CLOSE OUT-FILE
           STOP RUN.
""")
    assert kinds == [("DOUBLE_CLOSE", "OUT-FILE")]


def test_file_left_open_on_one_path_is_reported() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-MODE = 'N' CLOSE OUT-FILE END-IF
           STOP RUN.
""")
    assert kinds == [("FILE_LEFT_OPEN", "OUT-FILE")]


def test_goback_arm_is_left_out_and_go_to_arm_is_kept() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-OUT-STAT = '35' CLOSE OUT-FILE GOBACK END-IF
           IF WS-OUT-STAT = '99' CLOSE OUT-FILE GO TO 9000-END END-IF
           READ OUT-FILE
           CLOSE OUT-FILE
           STOP RUN.
       9000-END.
           STOP RUN.
""")
    assert kinds == []


def test_performed_abend_paragraph_ends_only_its_arm() -> None:
    # Before, the PERFORMed STOP RUN ended the whole walk, so the READ and
    # the missing CLOSE after the guard were never examined.
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-OUT-STAT NOT = '00' PERFORM 9999-ABEND END-IF
           READ OUT-FILE
           OPEN INPUT OUT-FILE
           CLOSE OUT-FILE
           STOP RUN.
       9999-ABEND.
           CLOSE OUT-FILE
           STOP RUN.
""")
    assert kinds == [("DOUBLE_OPEN", "OUT-FILE")]


def test_evaluate_arms_are_forked() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           EVALUATE WS-MODE
              WHEN 'N' OPEN OUTPUT RPT-FILE
              WHEN 'A' OPEN EXTEND RPT-FILE
              WHEN OTHER OPEN I-O RPT-FILE
           END-EVALUATE
           WRITE RPT-REC
           CLOSE RPT-FILE
           STOP RUN.
""")
    assert kinds == []


def test_evaluate_all_arms_open_then_open_again_is_a_double_open() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           EVALUATE WS-MODE
              WHEN 'N' OPEN OUTPUT RPT-FILE
              WHEN OTHER OPEN EXTEND RPT-FILE
           END-EVALUATE
           OPEN OUTPUT RPT-FILE
           CLOSE RPT-FILE
           STOP RUN.
""")
    assert kinds == [("DOUBLE_OPEN", "RPT-FILE")]


def test_evaluate_without_other_has_a_fall_through_arm() -> None:
    # No WHEN matched: the file is still unopened on that path, so a second
    # OPEN after the EVALUATE is not a definite double open.
    kinds = _kinds("""\
       0000-MAIN.
           EVALUATE WS-MODE
              WHEN 'N' OPEN OUTPUT RPT-FILE
           END-EVALUATE
           OPEN OUTPUT RPT-FILE
           CLOSE RPT-FILE
           STOP RUN.
""")
    assert kinds == []


def test_no_arm_falls_out() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-MODE = 'N' CLOSE OUT-FILE STOP RUN
           ELSE CLOSE OUT-FILE GOBACK END-IF.
""")
    # Every arm leaves; the walk carries on from the arms' merged state.
    assert IOViolationKind.FILE_LEFT_OPEN.name not in {k for k, _ in kinds}


def test_go_to_exit_arm_carries_its_state_through_a_thru_range() -> None:
    # The GO TO arm's OPEN reaches 1000-EXIT by the THRU range, so the
    # caller's READ / CLOSE are on a path where the file is open.
    kinds = _kinds("""\
       0000-MAIN.
           PERFORM 1000-INIT THRU 1000-EXIT
           IF WS-MODE = 'N' READ OUT-FILE CLOSE OUT-FILE END-IF
           STOP RUN.
       1000-INIT.
           IF WS-MODE = 'N' OPEN INPUT OUT-FILE GO TO 1000-EXIT END-IF.
       1000-EXIT.
           EXIT.
""")
    assert kinds == [("FILE_LEFT_OPEN", "OUT-FILE")]


def test_go_to_arm_state_reaches_a_queued_target() -> None:
    kinds = _kinds("""\
       P1.
           IF WS-MODE = 'N' OPEN INPUT OUT-FILE GO TO P9 END-IF.
       P2.
           GO TO P1.
       P9.
           READ OUT-FILE
           CLOSE OUT-FILE
           STOP RUN.
""")
    assert kinds == []


def test_go_to_arms_that_close_keep_the_file_maybe_closed() -> None:
    # DB104A's shape: each guard closes the file and jumps away, so a later
    # OPEN is not a definite double open.
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-MODE = '1' CLOSE OUT-FILE GO TO 9000-END END-IF
           IF WS-MODE = '2' CLOSE OUT-FILE GO TO 9000-END END-IF
           CLOSE OUT-FILE.
       9000-END.
           OPEN OUTPUT OUT-FILE
           CLOSE OUT-FILE
           STOP RUN.
""")
    assert ("DOUBLE_OPEN", "OUT-FILE") not in kinds


def test_performed_abend_in_an_arm_claims_no_file_left_open() -> None:
    # Same idiom as a STOP RUN written in the arm: no FILE_LEFT_OPEN.
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-OUT-STAT NOT = '00' PERFORM 9999-ABEND END-IF
           CLOSE OUT-FILE
           STOP RUN.
       9999-ABEND.
           DISPLAY 'ABEND'
           STOP RUN.
""")
    assert kinds == []


def test_performed_abend_outside_an_arm_still_claims_file_left_open() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           OPEN INPUT OUT-FILE
           IF WS-OUT-STAT NOT = '00' PERFORM 9999-ABEND END-IF
           PERFORM 9999-ABEND.
       9999-ABEND.
           DISPLAY 'ABEND'
           STOP RUN.
""")
    assert kinds == [("FILE_LEFT_OPEN", "OUT-FILE")]


def test_statements_after_an_if_whose_arms_all_stop_are_not_walked() -> None:
    kinds = _kinds("""\
       0000-MAIN.
           IF WS-MODE = 'N' STOP RUN ELSE GOBACK END-IF
           READ OUT-FILE.
""")
    assert kinds == []


def test_replayed_range_keeps_its_go_to_arm_state() -> None:
    # The second PERFORM from the same entry state replays the first run's
    # summary (#371); the GO TO arm's OPEN must survive the replay too.
    kinds = _kinds("""\
       0000-MAIN.
           PERFORM 1000-INIT THRU 1000-EXIT
           IF WS-MODE = 'N' READ OUT-FILE CLOSE OUT-FILE END-IF
           PERFORM 1000-INIT THRU 1000-EXIT
           IF WS-MODE = 'N' READ OUT-FILE CLOSE OUT-FILE END-IF
           STOP RUN.
       1000-INIT.
           IF WS-MODE = 'N' OPEN INPUT OUT-FILE GO TO 1000-EXIT END-IF.
       1000-EXIT.
           EXIT.
""")
    assert ("READ_BEFORE_OPEN", "OUT-FILE") not in kinds
    assert ("CLOSE_NOT_OPEN", "OUT-FILE") not in kinds
