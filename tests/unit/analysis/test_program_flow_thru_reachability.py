"""THRU range members must count as reachable in the program flow graph.

``PERFORM A THRU C`` executes every paragraph the range physically spans,
but the graph only carries explicit edges to the two endpoints; the
intermediate members ride along in ``range_members``. Reachability must
honor those members: before it did, an intermediate paragraph whose
fall-through edge from its predecessor was suppressed (predecessor contains
a GO TO) was falsely reported unreachable even though the range provably
executes it.
"""

from __future__ import annotations

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer


def _analyze(source: str):
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)
    assert result.success, f"Parse failed: {result.errors}"
    return ProgramFlowAnalyzer().analyze(result.ast)


class TestThruRangeReachability:
    def test_member_behind_conditional_goto_is_reachable(self) -> None:
        # PARA-A contains a GO TO, which suppresses its fall-through edge, so
        # PARA-B has no incoming edge -- but it is a member of the performed
        # THRU range and therefore executes.
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUREACH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PARA-A THRU PARA-C.
           STOP RUN.
       PARA-A.
           IF WS-X = 1
               GO TO PARA-C.
       PARA-B.
           DISPLAY 'B'.
       PARA-C.
           EXIT.
"""
        report = _analyze(src)
        assert "PARA-B" not in report.unreachable_nodes
        assert report.unreachable_nodes == []

    def test_member_behind_unconditional_goto_is_reachable(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUSKIP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PARA-A THRU PARA-C.
           STOP RUN.
       PARA-A.
           GO TO PARA-C.
       PARA-B.
           DISPLAY 'B'.
       PARA-C.
           EXIT.
"""
        report = _analyze(src)
        assert "PARA-B" not in report.unreachable_nodes

    def test_paragraph_outside_range_still_unreachable(self) -> None:
        # The range fix must not blanket-mark everything reachable: a
        # paragraph after the THRU end with no reference and no incoming
        # fall-through stays unreachable.
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUOUT.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PARA-A THRU PARA-B.
           STOP RUN.
       PARA-A.
           DISPLAY 'A'.
       PARA-B.
           GO TO PARA-A.
       ORPHAN-PARA.
           DISPLAY 'NEVER'.
"""
        report = _analyze(src)
        assert "ORPHAN-PARA" in report.unreachable_nodes

    def test_sort_input_procedure_range_member_reachable(self) -> None:
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTREACH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-FILE ASSIGN TO SORTWK.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-FILE.
       01 SORT-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-REC
               INPUT PROCEDURE IS IN-START THRU IN-END
               OUTPUT PROCEDURE IS OUT-START THRU OUT-END.
           STOP RUN.
       IN-START.
           GO TO IN-END.
       IN-MIDDLE.
           DISPLAY 'M'.
       IN-END.
           EXIT.
       OUT-START.
           DISPLAY 'O1'.
       OUT-END.
           EXIT.
"""
        report = _analyze(src)
        assert "IN-MIDDLE" not in report.unreachable_nodes
