"""Issue #510: ``LineageGraph._trace`` dropped a port from the hits whenever
it had any onward edge in the query direction. A two-way port -- an unbound
DD opened I-O, a BY REFERENCE argument to a program outside the scan, a
``PROCEDURE DIVISION USING`` parameter -- always has one, back into the same
program, so ``field-impact`` / MCP ``impact_of_change`` / ``where_from``
never named the master file, the external program or the caller. A port is
now dropped only when the trail really continues past it (a join).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer, FieldFlowReport
from cobolparser.analysis.lineage_graph import DatasetBinding, LineageGraph

MUPD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MUPD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MAST ASSIGN TO MASTDD
               ORGANIZATION INDEXED ACCESS RANDOM
               RECORD KEY IS M-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  MAST.
       01  M-REC.
           05 M-KEY   PIC X(5).
           05 M-BAL   PIC 9(7).
       WORKING-STORAGE SECTION.
       01  WS-AMT     PIC 9(7) VALUE 5.
       PROCEDURE DIVISION.
           OPEN I-O MAST
           MOVE '00001' TO M-KEY
           READ MAST
           ADD WS-AMT TO M-BAL
           REWRITE M-REC
           CLOSE MAST
           GOBACK.
"""

CALLR = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN    PIC X(5) VALUE 'ABCDE'.
       01  WS-BUF   PIC X(5).
       PROCEDURE DIVISION.
           MOVE WS-IN TO WS-BUF
           CALL '{callee}' USING WS-BUF
           GOBACK.
"""

SUB2 = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SAVE   PIC X(5).
       LINKAGE SECTION.
       01  LK-AMT    PIC X(5).
       PROCEDURE DIVISION USING LK-AMT.
           MOVE LK-AMT TO WS-SAVE
           DISPLAY WS-SAVE
           GOBACK.
"""


def _report(source: str) -> FieldFlowReport:
    result = parse_cobol(source, "x.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


def _fields(graph: LineageGraph, name: str, direction: str, program=None) -> set:
    return {h.field for h in graph.impact(name, program, direction).hits}


def test_io_master_file_is_reported_both_ways() -> None:
    graph = LineageGraph([_report(MUPD)])
    assert _fields(graph, "WS-AMT", "forward") == {"M-REC.M-BAL", "file:MASTDD@5+7"}
    assert _fields(graph, "M-BAL", "backward") == {"WS-AMT", "file:MASTDD@5+7"}


def test_bound_io_master_file_continues_to_the_dataset() -> None:
    binding = DatasetBinding("MUPD", "MASTDD", "PROD.MASTER", "JOB", "STEP1")
    graph = LineageGraph([_report(MUPD)], [binding])
    hits = _fields(graph, "WS-AMT", "forward")
    assert "PROD.MASTER@5+7" in hits
    assert not any(h.startswith("file:") for h in hits)


def test_by_reference_argument_to_an_outside_program() -> None:
    graph = LineageGraph([_report(CALLR.format(callee="EXTPGM"))])
    assert _fields(graph, "WS-IN", "forward") == {"WS-BUF", "call:EXTPGM#1@0+5"}


def test_by_reference_argument_to_a_program_in_the_scan() -> None:
    graph = LineageGraph([_report(CALLR.format(callee="SUB2")), _report(SUB2)])
    hits = _fields(graph, "WS-IN", "forward", "CALLR")
    # The trail goes on into SUB2, so the CALL port is not where it ends.
    assert ("SUB2", "WS-SAVE") in {
        (h.program, h.field) for h in graph.impact("WS-IN", "CALLR", "forward").hits
    }
    assert not any(h.startswith("call:") for h in hits)


def test_linkage_parameter_is_reported() -> None:
    graph = LineageGraph([_report(SUB2)])
    assert _fields(graph, "WS-SAVE", "backward") == {"LK-AMT", "linkage:SUB2#1@0+5"}
    assert "linkage:SUB2#1@0+5" in _fields(graph, "LK-AMT", "forward")
