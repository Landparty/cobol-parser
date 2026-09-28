"""RELEASE ... FROM / RETURN ... INTO read the whole operand.

``RELEASE rec FROM x`` / ``RETURN sd INTO x`` read one token after
FROM/INTO, truncating ``WS-REC OF GRP`` and ``TBL (I)``. They now take the
whole operand through the same helper MOVE uses.
"""

from __future__ import annotations

from cobolparser import parse_cobol

SORT_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRTQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SF ASSIGN TO SORTWK.
       DATA DIVISION.
       FILE SECTION.
       SD SF.
       01 SR PIC X(10).
       WORKING-STORAGE SECTION.
       01 GRP.
          05 WS-REC PIC X(10).
          05 TBL PIC X(10) OCCURS 5.
       01 I PIC 9.
       PROCEDURE DIVISION.
       P1.
           SORT SF ON ASCENDING KEY SR
               INPUT PROCEDURE P2 OUTPUT PROCEDURE P3.
           STOP RUN.
       P2.
           RELEASE SR FROM WS-REC OF GRP.
           RELEASE SR FROM TBL (I).
           RELEASE SR.
       P3.
           RETURN SF INTO TBL OF GRP (I) AT END CONTINUE END-RETURN.
           RETURN SF RECORD INTO WS-REC IN GRP AT END CONTINUE.
"""


def test_release_and_return_operands_are_whole():
    result = parse_cobol(SORT_PROGRAM)
    assert result.success, result.errors
    assert not result.warnings
    releases = result.ast.find_all_by_type("ReleaseStatement")
    assert [r.from_source for r in releases] == ["WS-REC OF GRP", "TBL ( I )", None]
    returns = result.ast.find_all_by_type("ReturnStatement")
    assert [r.into_target for r in returns] == ["TBL OF GRP ( I )", "WS-REC IN GRP"]
