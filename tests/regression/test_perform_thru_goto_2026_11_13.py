"""Bug hunt after #903: a conditional GO TO to the exit paragraph of a
``PERFORM ... THRU`` range (or a SORT input procedure) was queued but the
range walk never resumed there, so the PERFORM returned in the loop's
state (file still open), giving false DOUBLE_OPEN / WRITE_WRONG_MODE.
And a GO TO taken up by fall-through inside a range stayed in the range's
recording, so a replay of the range re-queued it and the main walk later
fell into the range out of context (false READ_BEFORE_OPEN)."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer, IOViolationKind

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. M.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO DD1.
           SELECT G ASSIGN TO DD2.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(10).
       FD G.
       01 GR PIC X(10).
       WORKING-STORAGE SECTION.
       01 FLG PIC 9 VALUE 0.
       PROCEDURE DIVISION.
"""


def _kinds(body: str) -> list[IOViolationKind]:
    ast = parse_cobol(HEADER + body).ast
    return [v.kind for v in IOSequenceAnalyzer().analyze(ast).violations]


MAIN = """\
       MAIN-PARA.
           PERFORM LOAD THRU LOAD-EXIT
           OPEN OUTPUT F
           WRITE R
           CLOSE F
           STOP RUN.
"""


class TestGoToExitOfThruRange:
    def test_at_end_close_go_to_exit(self) -> None:
        body = MAIN + """\
       LOAD.
           OPEN INPUT F.
       LOAD-LOOP.
           READ F AT END CLOSE F GO TO LOAD-EXIT.
           GO TO LOAD-LOOP.
       LOAD-EXIT.
           EXIT.
"""
        assert _kinds(body) == []

    def test_if_close_go_to_exit(self) -> None:
        body = MAIN + """\
       LOAD.
           OPEN INPUT F.
       LOAD-LOOP.
           READ F.
           IF FLG = 3
               CLOSE F GO TO LOAD-EXIT.
           GO TO LOAD-LOOP.
       LOAD-EXIT.
           EXIT.
"""
        assert _kinds(body) == []

    def test_exit_without_close_is_still_reported(self) -> None:
        body = MAIN + """\
       LOAD.
           OPEN INPUT F.
       LOAD-LOOP.
           READ F AT END GO TO LOAD-EXIT.
           GO TO LOAD-LOOP.
       LOAD-EXIT.
           EXIT.
"""
        assert IOViolationKind.DOUBLE_OPEN in _kinds(body)

    def test_range_performed_twice(self) -> None:
        body = """\
       MAIN-PARA.
           PERFORM LOAD THRU LOAD-EXIT
           PERFORM LOAD THRU LOAD-EXIT
           STOP RUN.
       LOAD.
           OPEN INPUT F.
       LOAD-LOOP.
           READ F AT END CLOSE F GO TO LOAD-EXIT.
           GO TO LOAD-LOOP.
       LOAD-EXIT.
           EXIT.
"""
        assert _kinds(body) == []

    def test_sort_input_procedure(self) -> None:
        body = """\
       MAIN-PARA.
           SORT SW ON ASCENDING KEY SK
               INPUT PROCEDURE IS LOAD THRU LOAD-EXIT
               GIVING G
           OPEN OUTPUT F
           WRITE R
           CLOSE F
           STOP RUN.
       LOAD.
           OPEN INPUT F.
       LOAD-LOOP.
           READ F AT END CLOSE F GO TO LOAD-EXIT.
           RELEASE SR FROM R
           GO TO LOAD-LOOP.
       LOAD-EXIT.
           EXIT.
"""
        source = (HEADER + body).replace(
            "       WORKING-STORAGE SECTION.",
            "       SD SW.\n       01 SR.\n          05 SK PIC X(10).\n"
            "       WORKING-STORAGE SECTION.",
        )
        ast = parse_cobol(source).ast
        kinds = [v.kind for v in IOSequenceAnalyzer().analyze(ast).violations]
        assert IOViolationKind.DOUBLE_OPEN not in kinds
        assert IOViolationKind.WRITE_WRONG_MODE not in kinds


class TestRangeReplayDoesNotLeakGoTos:
    def test_main_walk_does_not_fall_into_a_performed_range(self) -> None:
        body = """\
       MAIN-PARA.
           OPEN INPUT F
           PERFORM CHK THRU CHK-EXIT
           CLOSE F
           PERFORM CHK THRU CHK-EXIT.
       P-LOOP.
           IF FLG = 1 GO TO P-END.
           GO TO P-LOOP.
       P-END.
           STOP RUN.
       CHK.
           IF FLG = 2 GO TO CHK-ERR.
           GO TO CHK-EXIT.
       CHK-ERR.
           MOVE 1 TO FLG.
       CHK-EXIT.
           EXIT.
       G-READ.
           READ G.
"""
        assert IOViolationKind.READ_BEFORE_OPEN not in _kinds(body)


class TestCycleResumesAtTheLoopExit:
    """When the main walk closes a loop it resumes at the GO TO queued
    last (the loop's own exit), not the oldest one, which skipped the
    paragraphs between the loop and an earlier far jump (NIST SQ114A lost
    a true FILE_LEFT_OPEN)."""

    def test_paragraphs_after_the_loop_are_walked(self) -> None:
        body = """\
       MAIN-PARA.
           OPEN INPUT F
           IF FLG = 1 GO TO P-X.
       P-L.
           READ F
           IF FLG = 2 GO TO P-L-END.
           GO TO P-L.
       P-L-END.
           CLOSE F
           OPEN INPUT G.
       P-X.
           STOP RUN.
"""
        ast = parse_cobol(HEADER + body).ast
        left_open = {
            v.file_name
            for v in IOSequenceAnalyzer().analyze(ast).violations
            if v.kind is IOViolationKind.FILE_LEFT_OPEN
        }
        assert left_open == {"F", "G"}
