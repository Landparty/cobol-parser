"""Cross-program field lineage (``analysis.lineage_graph``).

Three programs in ``tests/samples/lineage``: WRITER reads PROD.TRAN.DAILY,
computes a fee, writes a temporary dataset, CALLs SUBPGM and updates
ACCOUNT.BALANCE; a SORT step SUMs the fee into PROD.FEE.SUMMARY, which
READER reads, using the account number as a key into a VSAM master and
into ACCOUNT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer, FieldFlowReport
from cobolparser.analysis.lineage_graph import (
    DatasetBinding,
    LineageGraph,
    Passthrough,
    normalize_dataset,
    reports_from_scan,
)
from cobolparser.scan import ScanOptions, scan_files

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "lineage"


def _report(name: str) -> FieldFlowReport:
    result = parse_cobol((SAMPLES / f"{name}.cbl").read_text(), f"{name}.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


BINDINGS = [
    DatasetBinding("WRITER", "INFILE", "PROD.TRAN.DAILY(0)", "FEEJOB", "STEP010"),
    DatasetBinding("WRITER", "OUTFILE", "&&FEES", "FEEJOB", "STEP010"),
    DatasetBinding("READER", "FEEIN", "PROD.FEE.SUMMARY(+1)", "FEEJOB", "STEP030"),
    DatasetBinding("READER", "MASTER", "PROD.ACCT.MASTER", "FEEJOB", "STEP030"),
]
SUM_FEE = Passthrough(
    "&&FEES", "PROD.FEE.SUMMARY(+1)", "copy", ((19, 7),), "FEEJOB", "STEP020", "SORT"
)


@pytest.fixture(scope="module")
def reports() -> list[FieldFlowReport]:
    return [_report(n) for n in ("WRITER", "SUBPGM", "READER")]


@pytest.fixture(scope="module")
def graph(reports) -> LineageGraph:
    return LineageGraph(reports, BINDINGS, [SUM_FEE])


def _hits(result) -> dict[tuple[str | None, str], object]:
    return {(h.program, h.field): h for h in result.hits}


class TestNormalizeDataset:
    def test_gdg_generations_fold_to_the_base(self) -> None:
        assert normalize_dataset("prod.x(+1)") == "PROD.X"
        assert normalize_dataset("PROD.X(0)") == "PROD.X"
        assert normalize_dataset("PROD.X.G0012V00") == "PROD.X"

    def test_temporaries_are_job_scoped(self) -> None:
        assert normalize_dataset("&&T", "JOBA") == "JOBA/&&T"
        assert normalize_dataset("&&T", "JOBA") != normalize_dataset("&&T", "JOBB")


class TestDatasetJoin:
    def test_value_crosses_sort_sum_as_aggregate(self, graph) -> None:
        result = graph.impact("WS-FEE", program="WRITER")
        hits = _hits(result)
        fee = hits[("READER", "FEE-REC.FEE-FEE")]
        assert fee.derived  # the SORT SUM rewrote it
        assert "aggregate" in [h.kind for h in fee.path]
        assert result.datasets == ["FEEJOB/&&FEES", "PROD.FEE.SUMMARY"]

    def test_unsummed_bytes_are_plain_copies(self, graph) -> None:
        hits = _hits(graph.impact_dataset("PROD.TRAN.DAILY"))
        acct = hits[("READER", "FEE-REC.FEE-ACCT")]
        assert not acct.derived
        assert acct.confidence == "exact"

    def test_depth_zero_stays_in_the_program(self, graph) -> None:
        result = graph.impact("WS-FEE", program="WRITER", depth=0)
        assert result.programs == ["WRITER"]

    def test_reformat_stops_the_flow(self, reports) -> None:
        reformat = Passthrough(
            "&&FEES", "PROD.FEE.SUMMARY(+1)", "reformat", (), "FEEJOB", "S2", "SORT"
        )
        graph = LineageGraph(reports, BINDINGS, [reformat])
        result = graph.impact("WS-FEE", program="WRITER")
        assert "READER" not in result.programs
        assert any("reformats" in c for c in graph.caveats)

    def test_unbound_dd_is_reported(self, reports) -> None:
        graph = LineageGraph(reports)
        assert "WRITER: DD OUTFILE is not bound to any dataset" in graph.unjoined

    def test_temporary_from_another_job_does_not_join(self, reports) -> None:
        other = [
            BINDINGS[0],
            DatasetBinding("WRITER", "OUTFILE", "&&FEES", "JOBA"),
            DatasetBinding("READER", "FEEIN", "&&FEES", "JOBB"),
        ]
        result = LineageGraph(reports, other).impact("WS-FEE", program="WRITER")
        assert "READER" not in result.programs

    def test_bindings_accept_dicts(self, reports) -> None:
        graph = LineageGraph(
            [r.to_dict() for r in reports],
            [vars(b) for b in BINDINGS],
            [
                {
                    "input": "&&FEES",
                    "output": "PROD.FEE.SUMMARY(+1)",
                    "kind": "copy",
                    "aggregate_ranges": [[19, 7]],
                    "job": "FEEJOB",
                }
            ],
        )
        assert "READER" in graph.impact("WS-FEE", program="WRITER").programs


class TestCallAndSqlJoins:
    def test_call_argument_meets_linkage_parameter(self, graph) -> None:
        hits = _hits(graph.impact("IN-AMT", program="WRITER"))
        assert ("SUBPGM", "LK-REC.LK-AMT") in hits
        assert ("SUBPGM", "LK-FEE") in hits
        # ... and the callee's result comes back into the caller's WS-FEE
        assert ("WRITER", "WS-FEE") in hits

    def test_table_column_joins_writer_and_reader(self, graph) -> None:
        result = graph.impact_table("ACCOUNT.BALANCE")
        assert ("READER", "WS-FEE") in _hits(result)
        backward = graph.impact_table("BALANCE", direction="backward")
        assert backward.hits == []  # a bare column names no table

    def test_table_name_without_schema(self, reports) -> None:
        graph = LineageGraph(reports)
        result = graph.impact_table("ACCOUNT.BALANCE", direction="backward")
        assert "WRITER" in result.programs

    def test_backward_trace(self, graph) -> None:
        result = graph.impact("WS-FEE", program="READER", direction="backward")
        assert "ACCOUNT.BALANCE" in result.tables
        assert "PROD.TRAN.DAILY" in result.datasets
        text = result.to_text()
        assert "is fed by" in text
        assert " -> " in text

    def test_opaque_callee_passes_values_through(self) -> None:
        graph = LineageGraph([_report("WRITER")])
        # The account number reaches WS-FEE only through SUBPGM.
        result = graph.impact("IN-ACCT", program="WRITER")
        assert graph.opaque_callees == ["SUBPGM"]
        assert any("SUBPGM" in c for c in result.caveats)
        assert ("WRITER", "WS-FEE") in _hits(result)

    def test_unknown_field(self, graph) -> None:
        result = graph.impact("NO-SUCH-FIELD")
        assert result.hits == []
        assert result.caveats == ["NO-SUCH-FIELD: no such field in any report"]


class TestKeyRelationships:
    def test_candidates(self, graph) -> None:
        found = {(k.source, k.key, k.statement) for k in graph.key_relationships()}
        assert (
            "PROD.FEE.SUMMARY@0+10",
            "PROD.ACCT.MASTER@0+10",
            "READ KEY",
        ) in found
        assert (
            "PROD.TRAN.DAILY@0+10",
            "ACCOUNT.ACCT_NO",
            "EXEC SQL WHERE",
        ) in found


def test_to_dict(graph) -> None:
    data = graph.to_dict()
    assert data["programs"] == ["READER", "SUBPGM", "WRITER"]
    assert data["statistics"]["tables"] == 1
    assert data["unjoined"] == []
    result = graph.impact("WS-FEE", program="WRITER").to_dict()
    assert result["direction"] == "forward"
    assert result["hits"][0]["path"]


def test_reports_from_scan() -> None:
    paths = [str(SAMPLES / f"{n}.cbl") for n in ("WRITER", "READER")]
    paths.append(str(SAMPLES / "MISSING.cbl"))
    scan = scan_files(paths, ScanOptions(analyzers=("lineage",)), workers=1)
    reports, problems = reports_from_scan(scan)
    assert sorted(r["program_id"] for r in reports) == ["READER", "WRITER"]
    assert len(problems) == 1 and "MISSING.cbl" in problems[0]


class TestStoredJoinEdges:
    def test_rebuilt_graph_answers_the_same(self, reports, graph) -> None:
        import json

        stored = json.loads(json.dumps(graph.join_edges()))
        again = LineageGraph([r.to_dict() for r in reports], join_edges=stored)
        for query in (
            lambda g: g.impact("WS-FEE", program="WRITER"),
            lambda g: g.impact("WS-FEE", program="READER", direction="backward"),
            lambda g: g.impact_dataset("PROD.TRAN.DAILY"),
        ):
            assert query(again).to_dict() == query(graph).to_dict()
        assert again.key_relationships() == graph.key_relationships()

    def test_join_edges_are_only_joins(self, graph) -> None:
        kinds = {e["kind"] for e in graph.join_edges()}
        assert kinds <= {"dataset", "copy", "aggregate", "call", "table", "opaque-call"}
        assert {"dataset", "aggregate", "call", "table"} <= kinds

    def test_opaque_edges_survive_the_round_trip(self) -> None:
        writer = _report("WRITER")
        first = LineageGraph([writer])
        again = LineageGraph([writer], join_edges=first.join_edges())
        assert again.opaque_callees == ["SUBPGM"]
        assert any("SUBPGM" in c for c in again.caveats)


def test_impact_from_several_programs(graph) -> None:
    result = graph.impact("WS-FEE", program=["WRITER", "READER"])
    assert result.start == ["WRITER:WS-FEE", "READER:WS-FEE"]
    hits = _hits(result)
    assert ("READER", "console:SYSOUT@0+7") in hits
    assert ("WRITER", "OUT-REC.OUT-FEE") in hits
