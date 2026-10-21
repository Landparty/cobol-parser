"""Issue #540: a bare name shared by several fields (``AMT`` in IN-REC and
OUT-REC) started the impact trace from all of them at once, so a flow from
one of them into another was never a hit (a start is never reported), and
nothing said the name was ambiguous. Each matched field is now traced on its
own, and a caveat names every field the bare name matched; MCP reports it as
``ambiguous-name``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.config import ProjectConfig
from cobolparser.mcp.tools import CobolTools
from cobolparser.mcp.workspace import Workspace


def _source(procedure: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. AMTP.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC.\n"
        "          05 ACCT-ID  PIC X(6).\n"
        "          05 AMT      PIC 9(5).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC.\n"
        "          05 ACCT-ID  PIC X(6).\n"
        "          05 AMT      PIC 9(7).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-TOTAL    PIC 9(9) VALUE 0.\n"
        "       01 OUT-GRP.\n"
        "          05 AMT      PIC 9(5).\n"
        "       PROCEDURE DIVISION.\n"
        + "".join(f"           {line}\n" for line in procedure.strip().splitlines())
        + "           STOP RUN.\n"
    )


ISSUE = _source("""
OPEN INPUT IN-FILE OUTPUT OUT-FILE
READ IN-FILE
ADD AMT OF IN-REC TO WS-TOTAL
COMPUTE AMT OF OUT-REC = AMT OF IN-REC * 100
MOVE ACCT-ID OF IN-REC TO ACCT-ID OF OUT-REC
WRITE OUT-REC
CLOSE IN-FILE OUT-FILE
""")


def _graph(source: str) -> LineageGraph:
    result = parse_cobol(source, "AMTP.cbl")
    assert result.ast is not None
    return LineageGraph([FieldFlowAnalyzer().analyze(result.ast)])


def _items(result) -> set[str]:
    return {h.field for h in result.hits if h.node_kind == "item"}


@pytest.fixture(scope="module")
def graph() -> LineageGraph:
    return _graph(ISSUE)


def test_flow_between_same_named_fields_is_a_hit(graph) -> None:
    forward = graph.impact("AMT")
    assert {"OUT-REC.AMT", "WS-TOTAL"} <= _items(forward)
    # The bare answer agrees with the qualified one it contains.
    qualified = graph.impact("AMT OF IN-REC")
    assert _items(qualified) <= _items(forward)
    backward = graph.impact("AMT", direction="backward")
    assert "IN-REC.AMT" in _items(backward)


def test_ambiguity_caveat_names_each_field(graph) -> None:
    result = graph.impact("AMT")
    caveat = (
        "AMTP: AMT matches 3 fields: IN-REC.AMT, OUT-GRP.AMT, OUT-REC.AMT; "
        "qualify with OF to trace one"
    )
    assert result.ambiguous == [caveat]
    assert caveat in result.caveats
    assert caveat in result.to_text()


def test_qualified_name_is_not_ambiguous(graph) -> None:
    result = graph.impact("AMT OF IN-REC")
    assert result.ambiguous == []
    assert not any("matches" in c for c in result.caveats)


def test_single_move_between_same_named_fields() -> None:
    graph = _graph(_source("MOVE AMT OF IN-REC TO AMT OF OUT-GRP"))
    result = graph.impact("AMT")
    assert _items(result) == {"OUT-GRP.AMT"}
    assert result.ambiguous


def test_mcp_ambiguous_name_caveat(tmp_path: Path) -> None:
    (tmp_path / "AMTP.cbl").write_text(ISSUE)
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    for response in (
        tools.impact_of_change("AMT", "AMTP.cbl"),
        tools.where_from("AMT", "AMTP.cbl"),
    ):
        kinds = [c["kind"] for c in response["caveats"]]
        assert "ambiguous-name" in kinds
    fields = {
        h["field"] for h in tools.impact_of_change("AMT", "AMTP.cbl")["answer"]["hits"]
    }
    assert "OUT-REC.AMT" in fields


def test_ambiguity_caveat_survives_a_name_with_no_flow() -> None:
    # #546's "declared, but no value flows" early return must not drop the
    # ambiguity caveat when every match of the bare name is flow-free.
    result = _graph(_source("DISPLAY 'HI'")).impact("AMT")
    assert result.start_found
    assert not result.hits
    assert result.notes
    assert len(result.ambiguous) == 1
    assert "AMT matches 3 fields" in result.ambiguous[0]
    assert result.caveats[0] == result.ambiguous[0]
