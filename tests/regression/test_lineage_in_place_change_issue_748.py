"""#748: a value changed in place read as an unchanged copy.

``MOVE IN-AMT TO WS-AMT`` / ``MULTIPLY 100 BY WS-AMT`` / ``MOVE WS-AMT TO
OUT-AMT`` reported OUT-AMT as ``[move]`` with ``derived: false``: the
receiver of ADD / SUBTRACT / MULTIPLY / DIVIDE without GIVING gets no edge to
anything else (#535), so no arithmetic hop ever landed on a path that only
passes through it. The change is now recorded in the report's ``in_place``
and counted on every path (and port summary) through the item.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer, FieldFlowReport
from cobolparser.analysis.lineage_graph import LineageGraph


def _source(change: str, before: bool = False) -> str:
    moves = [
        "READ IN-FILE",
        "MOVE IN-AMT TO WS-AMT",
        change,
        "MOVE WS-AMT TO OUT-AMT",
        "WRITE OUT-REC",
    ]
    if before:
        moves = [change, *[m for m in moves if m != change]]
    body = ["OPEN INPUT IN-FILE OUTPUT OUT-FILE", *moves, "CLOSE IN-FILE OUT-FILE"]
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. S.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC.\n"
        "          05 IN-AMT   PIC 9(5).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC.\n"
        "          05 OUT-AMT  PIC 9(7).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-AMT      PIC 9(7).\n"
        "       PROCEDURE DIVISION.\n"
        + "".join(f"           {line}\n" for line in body)
        + "           STOP RUN.\n"
    )


CHANGES = [
    "ADD 1 TO WS-AMT",
    "SUBTRACT 3 FROM WS-AMT",
    "MULTIPLY 100 BY WS-AMT",
    "DIVIDE 4 INTO WS-AMT",
]


def _report(source: str) -> FieldFlowReport:
    result = parse_cobol(source, "S.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


def _hit(result, field: str):
    return next(h for h in result.hits if h.field == field)


@pytest.mark.parametrize("change", CHANGES)
def test_in_place_change_is_recorded(change: str) -> None:
    report = _report(_source(change))
    assert [(e.source.name, e.target.name) for e in report.in_place] == [
        ("WS-AMT", "WS-AMT")
    ]
    assert report.to_dict()["in_place"]


@pytest.mark.parametrize("change", CHANGES)
def test_forward_impact_through_the_item_is_derived(change: str) -> None:
    graph = LineageGraph([_report(_source(change))])
    forward = graph.impact("IN-AMT")
    out = _hit(forward, "OUT-REC.OUT-AMT")
    assert out.derived
    assert out.confidence == "exact"
    assert not _hit(forward, "WS-AMT").derived
    ports = [h for h in forward.hits if h.node_kind != "item"]
    assert ports and all(h.derived for h in ports)
    verb = change.split()[0]
    assert f"({verb} line" in forward.to_text()


@pytest.mark.parametrize("change", CHANGES)
def test_backward_impact_through_the_item_is_derived(change: str) -> None:
    graph = LineageGraph([_report(_source(change))])
    backward = graph.impact("OUT-AMT", direction="backward")
    assert _hit(backward, "IN-REC.IN-AMT").derived


@pytest.mark.parametrize("change", CHANGES)
def test_port_summary_is_derived(change: str) -> None:
    summary = _report(_source(change)).summary
    assert summary and all(flow.derived for flow in summary)


def test_plain_copy_stays_a_copy() -> None:
    report = _report(_source("DISPLAY WS-AMT"))
    assert report.in_place == []
    forward = LineageGraph([report]).impact("IN-AMT")
    assert not _hit(forward, "OUT-REC.OUT-AMT").derived
    assert not any(flow.derived for flow in report.summary)


def test_change_before_the_value_arrives_is_only_a_candidate() -> None:
    forward = LineageGraph([_report(_source("ADD 1 TO WS-AMT", before=True))]).impact(
        "IN-AMT"
    )
    out = _hit(forward, "OUT-REC.OUT-AMT")
    assert out.derived
    assert out.confidence == "candidate"


def test_graph_round_trips_in_place_through_to_dict() -> None:
    report = _report(_source("MULTIPLY 100 BY WS-AMT"))
    graph = LineageGraph([report.to_dict()])
    assert _hit(graph.impact("IN-AMT"), "OUT-REC.OUT-AMT").derived
