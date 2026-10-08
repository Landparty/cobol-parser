"""Per-program field lineage (``analysis.field_lineage``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import (
    FieldFlowAnalyzer,
    FieldFlowReport,
    LineageEdge,
    LineageNode,
    apply_source_map,
    normalize_ddname,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "lineage"


def _report(name: str) -> FieldFlowReport:
    result = parse_cobol((SAMPLES / f"{name}.cbl").read_text(), f"{name}.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


def _edges(report: FieldFlowReport) -> set[tuple[str, str, str]]:
    return {(e.kind, e.source.label(), e.target.label()) for e in report.edges}


@pytest.fixture(scope="module")
def writer() -> FieldFlowReport:
    return _report("WRITER")


@pytest.fixture(scope="module")
def misc() -> FieldFlowReport:
    return _report("MISC")


class TestEdgeKinds:
    def test_read_into_reaches_fields_through_the_record(self, writer) -> None:
        edges = _edges(writer)
        assert ("read", "file:INFILE@10+9", "IN-REC.IN-AMT") in edges
        assert ("move", "IN-REC.IN-AMT", "WS-REC.WS-AMT") in edges

    def test_compute_is_arith_and_guarded_inside_if(self, writer) -> None:
        fee = [
            e for e in writer.edges if e.kind == "arith" and e.target.name == "WS-FEE"
        ]
        assert {e.source.name for e in fee} == {"WS-RATE", "WS-REC.WS-AMT"}
        assert all(e.guarded for e in fee)

    def test_add_is_unguarded(self, writer) -> None:
        add = [e for e in writer.edges if e.target.name == "WS-TOTAL"]
        assert add and not any(e.guarded for e in add)

    def test_write_maps_fields_to_byte_ranges(self, writer) -> None:
        edges = _edges(writer)
        assert ("write", "OUT-REC.OUT-FEE", "file:OUTFILE@19+7") in edges

    def test_call_by_reference_goes_both_ways(self, writer) -> None:
        edges = _edges(writer)
        assert ("call", "WS-FEE", "call:SUBPGM#2@0+7") in edges
        assert ("call", "call:SUBPGM#2@0+7", "WS-FEE") in edges

    def test_sql_and_display_ports(self, writer) -> None:
        edges = _edges(writer)
        assert ("sql", "WS-TOTAL", "sql:ACCOUNT.BALANCE") in edges
        assert ("display", "WS-TOTAL", "console:SYSOUT@0+11") in edges

    def test_redefines_is_two_way(self, writer) -> None:
        edges = _edges(writer)
        assert ("redefines", "WS-ALT", "WS-REC.WS-ACCT") in edges
        assert ("redefines", "WS-REC.WS-ACCT", "WS-ALT") in edges

    def test_move_corresponding_pairs_by_name(self, misc) -> None:
        edges = _edges(misc)
        assert ("move", "WS-A.ACCT", "WS-B.ACCT") in edges
        assert ("move", "WS-A.AMT", "WS-B.AMT") in edges
        assert ("move", "WS-A.ACCT", "WS-B.AMT") not in edges

    def test_group_move_is_an_inexact_overlay(self, misc) -> None:
        overlay = [
            e
            for e in misc.edges
            if e.source.name == "IN-REC" and e.target.name.startswith("WS-A.")
        ]
        assert {e.target.name for e in overlay} == {"WS-A.ACCT", "WS-A.AMT"}
        assert not any(e.exact for e in overlay)

    def test_string_accept_and_write_from(self, misc) -> None:
        edges = _edges(misc)
        assert ("string", "WS-CODE", "WS-PARM") in edges
        assert ("accept", "console:SYSIN@0+8", "WS-PARM") in edges
        assert ("move", "WS-LINE", "OUT-REC") in edges

    def test_sort_using_giving(self, misc) -> None:
        sort_line = max(e.line for e in misc.edges)
        at_sort = {
            (e.kind, e.source.label(), e.target.label())
            for e in misc.edges
            if e.line == sort_line
        }
        assert ("move", "IN-REC", "SRT-REC") in at_sort
        assert ("move", "SRT-REC", "OUT-REC") in at_sort

    def test_dynamic_call_resolves_its_candidates(self, misc) -> None:
        assert misc.port("call", "SUBA#1") is not None
        assert misc.caveats == []

    def test_ut_s_prefix_is_stripped_from_dd_names(self, misc) -> None:
        assert misc.port("file", "INFILE") is not None


class TestLinkageAndKeys:
    def test_linkage_parameters_are_ports(self) -> None:
        report = _report("SUBPGM")
        edges = _edges(report)
        assert ("linkage", "linkage:SUBPGM#1@10+9", "LK-REC.LK-AMT") in edges
        assert ("linkage", "LK-FEE", "linkage:SUBPGM#2@0+7") in edges

    def test_key_uses(self) -> None:
        report = _report("READER")
        keys = {(k.port.kind, k.port.name, k.statement) for k in report.key_uses}
        assert ("file", "MASTER", "READ KEY") in keys
        assert ("file", "MASTER", "SELECT RECORD KEY") in keys
        assert ("sql", "ACCOUNT.ACCT_NO", "EXEC SQL WHERE") in keys


class TestSummary:
    def test_port_to_port_flows(self) -> None:
        report = _report("SUBPGM")
        [flow] = report.summary
        assert flow.source.label() == "linkage:SUBPGM#1@10+9"
        assert flow.target.label() == "linkage:SUBPGM#2@0+7"
        assert flow.derived
        assert flow.via == ("LK-REC.LK-AMT", "WS-WORK", "LK-FEE")

    def test_redefines_are_never_chained(self, writer) -> None:
        # WS-ALT overlays the whole of WS-REC: going ACCT -> ALT -> AMT
        # would invent a flow from the account number into the amount.
        pairs = {(f.source.label(), f.target.label()) for f in writer.summary}
        assert ("call:SUBPGM#1@0+10", "call:SUBPGM#1@10+9") not in pairs
        assert ("call:SUBPGM#1@10+9", "file:OUTFILE@10+9") in pairs


class TestSerialization:
    def test_round_trip(self, writer) -> None:
        data = writer.to_dict()
        assert data["lineage_version"] == "1"
        assert data["statistics"]["edges"] == len(writer.edges)
        again = [LineageEdge.from_dict(e) for e in data["edges"]]
        assert again == writer.edges
        node = LineageNode.from_dict(data["edges"][0]["source"])
        assert node == writer.edges[0].source

    def test_text(self, writer) -> None:
        text = writer.to_text()
        assert text.startswith("Field lineage: WRITER")
        assert "sql      ACCOUNT.BALANCE" in text

    def test_apply_source_map_stamps_origin(self) -> None:
        report = _report("SUBPGM")
        line = report.edges[-1].line
        apply_source_map(report, {line: ("SUBPGM.cpy", 7)})
        data = report.edges[-1].to_dict()
        assert data["origin"] == {"file": "SUBPGM.cpy", "line": 7}
        assert apply_source_map(report, None) is report


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("UT-S-INFILE", "INFILE"), ("S-OUT", "OUT"), ("infile", "INFILE"), (None, "")],
)
def test_normalize_ddname(raw, expected) -> None:
    assert normalize_ddname(raw) == expected


def test_every_enterprise_sample_analyzes() -> None:
    root = Path(__file__).resolve().parents[2] / "samples" / "enterprise"
    for path in sorted(root.glob("*.cbl")):
        result = parse_cobol(path.read_text(), path.name)
        assert result.ast is not None, path.name
        for unit in result.ast.program_units():
            report = FieldFlowAnalyzer().analyze(unit)
            assert report.to_dict()["program_id"] == report.program_id
