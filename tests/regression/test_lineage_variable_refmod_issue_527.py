"""Issue #527: a reference modifier whose start is a data name
(``WS-REC(WS-POS:10)``) was treated as ``WS-REC(1:10)``, so a group MOVE
only reached the fields in the group's first ten bytes and every later one
(R-CITY) was missing from lineage, with no caveat. Such an operand may be
any window of the item: it now reaches every field under it, inexactly, and
a caveat names it.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer, FieldFlowReport
from cobolparser.analysis.lineage_graph import LineageGraph


def _report(procedure: str) -> FieldFlowReport:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. RM2.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-REC.\n"
        "           05  R-ID    PIC X(4).\n"
        "           05  R-NAME  PIC X(20).\n"
        "           05  R-CITY  PIC X(10).\n"
        "       01  WS-POS      PIC 99.\n"
        "       01  WS-LEN      PIC 99.\n"
        "       01  WS-WORD     PIC X(10).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           MOVE 25 TO WS-POS\n"
        + "".join(f"           {line}\n" for line in procedure.strip().splitlines())
        + "           GOBACK.\n"
    )
    result = parse_cobol(source, "RM2.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


FIELDS = {"WS-REC.R-ID", "WS-REC.R-NAME", "WS-REC.R-CITY"}


def _hits(report: FieldFlowReport, name: str, direction: str) -> dict[str, str]:
    result = LineageGraph([report]).impact(name, direction=direction)
    return {h.field: h.confidence for h in result.hits if h.node_kind == "item"}


def test_variable_start_read_reaches_every_field() -> None:
    report = _report("MOVE WS-REC(WS-POS:10) TO WS-WORD")
    hits = _hits(report, "WS-WORD", "backward")
    assert set(hits) == FIELDS
    assert set(hits.values()) == {"overlap"}
    assert "WS-WORD" in _hits(report, "R-CITY", "forward")
    assert any("WS-REC(WS-POS:10)" in c for c in report.caveats)


def test_variable_start_write_reaches_every_field() -> None:
    report = _report("MOVE WS-WORD TO WS-REC(WS-POS:10)")
    hits = _hits(report, "WS-WORD", "forward")
    assert set(hits) == FIELDS
    assert set(hits.values()) == {"overlap"}
    assert "WS-WORD" in _hits(report, "R-CITY", "backward")
    assert any("non-literal" in c for c in report.caveats)


def test_variable_length_is_loose_too() -> None:
    report = _report("MOVE WS-REC(1:WS-LEN) TO WS-WORD")
    assert set(_hits(report, "WS-WORD", "backward")) == FIELDS


def test_literal_refmod_is_unchanged() -> None:
    report = _report("MOVE WS-REC(25:10) TO WS-WORD")
    hits = _hits(report, "WS-WORD", "backward")
    assert hits == {"WS-REC.R-CITY": "exact"}
    assert not any("non-literal" in c for c in report.caveats)


def test_elementary_variable_refmod_is_inexact() -> None:
    report = _report("MOVE WS-WORD(WS-POS:2) TO WS-LEN")
    assert _hits(report, "WS-LEN", "backward") == {"WS-WORD": "overlap"}


def test_variable_refmod_outside_move_is_inexact() -> None:
    # STRING / DISPLAY / arithmetic do not go through the MOVE overlay, but
    # the caveat promises an inexact mapping there too: no exact edge may
    # come out of an operand whose window is unknown.
    report = _report(
        "STRING WS-REC(WS-POS:10) DELIMITED BY SIZE INTO WS-WORD\n"
        "DISPLAY WS-REC(WS-POS:5)"
    )
    hits = _hits(report, "WS-WORD", "backward")
    assert set(hits) == FIELDS
    assert set(hits.values()) == {"overlap"}
    assert not any(edge.exact for edge in report.edges if edge.line in (15, 16))
