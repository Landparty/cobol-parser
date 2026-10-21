"""Issue #528: ``ImpactResult.to_text()`` (``field-impact --format text``,
``lineage --field ... --format text``) rendered only item hits, so a field
that is only DISPLAYed, ACCEPTed, written to an unbound DD or passed on a
CALL read as feeding / fed by nothing while the JSON listed the port. The
text now lists every hit the JSON does.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO INDD.
           SELECT OUT-F ASSIGN TO OUTDD.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-F.
       01  IN-REC      PIC X(10).
       FD  OUT-F.
       01  OUT-REC     PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-AMT      PIC X(10).
       01  WS-IN       PIC X(4).
       01  WS-SHOW     PIC X(4) VALUE 'ABCD'.
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT IN-F OUTPUT OUT-F
           READ IN-F INTO WS-AMT
           ACCEPT WS-IN
           DISPLAY WS-SHOW
           WRITE OUT-REC FROM WS-AMT
           CALL 'EXTPGM' USING BY CONTENT WS-IN
           CLOSE IN-F OUT-F
           GOBACK.
"""


@pytest.fixture(scope="module")
def graph() -> LineageGraph:
    result = parse_cobol(SOURCE, "FB.cbl")
    assert result.ast is not None
    return LineageGraph([FieldFlowAnalyzer().analyze(result.ast)])


@pytest.mark.parametrize(
    "field_name, direction, port",
    [
        ("WS-IN", "backward", "console:SYSIN@0+4"),
        ("WS-SHOW", "forward", "console:SYSOUT@0+4"),
        ("WS-AMT", "forward", "file:OUTDD@0+10"),
        ("WS-AMT", "backward", "file:INDD@0+10"),
        ("WS-IN", "forward", "call:EXTPGM#1@0+4"),
    ],
)
def test_port_hits_are_in_the_text(graph, field_name, direction, port) -> None:
    result = graph.impact(field_name, direction=direction)
    assert port in {h["field"] for h in result.to_dict()["hits"]}
    assert f"port {port} line " in result.to_text()


@pytest.mark.parametrize("field_name", ["WS-IN", "WS-SHOW", "WS-AMT"])
@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_text_lists_every_json_hit(graph, field_name, direction) -> None:
    result = graph.impact(field_name, direction=direction)
    text = result.to_text()
    for hit in result.to_dict()["hits"]:
        assert hit["field"] in text
