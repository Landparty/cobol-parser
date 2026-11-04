"""FieldWideningAnalyzer: what a PICTURE change breaks across programs.

The programs are in tests/samples/widening/: CUSTWRT writes the customer
file (CUST-REC) and passes a copy of it to CUSTSUB; CUSTRD reads the same
dataset through its own copy of the layout.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.field_widening import (
    INVALID_MOVE,
    Capacity,
    FieldWideningAnalyzer,
    WideningReport,
    capacity_of,
    normalize_picture,
)
from cobolparser.analysis.lineage_graph import DatasetBinding, LineageGraph

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
WIDENING = SAMPLES / "widening"


def _report(path: Path) -> dict:
    result = parse_cobol(path.read_text())
    assert result.success, result.errors
    return FieldFlowAnalyzer().analyze(result.ast).to_dict()


@pytest.fixture(scope="module")
def reports() -> list[dict]:
    return [
        _report(WIDENING / f"{name}.cbl") for name in ("CUSTWRT", "CUSTSUB", "CUSTRD")
    ]


@pytest.fixture(scope="module")
def graph(reports: list[dict]) -> LineageGraph:
    return LineageGraph(
        reports,
        [
            DatasetBinding("CUSTWRT", "CUSTOUT", "PROD.CUST"),
            DatasetBinding("CUSTRD", "CUSTIN", "PROD.CUST"),
        ],
    )


def _find(report: WideningReport, kind: str, program: str | None, field: str):
    matches = [
        f
        for f in report.findings
        if f.kind == kind and f.program == program and f.field == field
    ]
    assert matches, [(f.kind, f.program, f.field) for f in report.findings]
    return matches[0]


def _absent(report: WideningReport, program: str | None, field: str) -> None:
    assert not [
        f for f in report.findings if f.program == program and f.field == field
    ], report.to_text()


class TestCapacity:
    @pytest.mark.parametrize(
        ("picture", "usage", "expected"),
        [
            ("9(6)", "DISPLAY", Capacity(True, 6, 0)),
            ("S9(7)V99", "COMP-3", Capacity(True, 7, 2, signed=True)),
            # An edited item keeps a sign only through a sign symbol (#757).
            ("ZZZ,ZZ9.99", None, Capacity(True, 6, 2)),
            ("ZZZ,ZZ9.99-", None, Capacity(True, 6, 2, signed=True)),
            ("+ZZZ9", None, Capacity(True, 4, 0, signed=True)),
            ("ZZ9CR", None, Capacity(True, 3, 0, signed=True)),
            ("ZZ9DB", None, Capacity(True, 3, 0, signed=True)),
            ("X(10)", None, Capacity(False, chars=10)),
            ("N(4)", "NATIONAL", Capacity(False, chars=4)),
            ("XX/XX", None, Capacity(False, chars=5)),
        ],
    )
    def test_capacity_of(self, picture, usage, expected) -> None:
        assert capacity_of(picture, usage, None, False) == expected

    def test_unknown(self) -> None:
        assert capacity_of(None, "COMP-2", 8, False) is None
        assert capacity_of("9(4)", "POINTER", 4, False) is None
        assert capacity_of(None, None, None, True) is None
        assert capacity_of(None, None, 12, True) == Capacity(
            False, chars=12, group=True
        )

    def test_losses(self) -> None:
        wide = Capacity(True, 9, 2, signed=True)
        assert wide.losses(Capacity(True, 7, 2, signed=True)) == ["high-order digits"]
        assert wide.losses(Capacity(True, 9, 1, signed=True)) == ["decimal places"]
        assert wide.losses(Capacity(True, 9, 2)) == ["sign"]
        # An elementary alphanumeric receiver gets the digits only: the sign
        # is lost and a noninteger MOVE is invalid (#765, #822); a group
        # receiver copies the bytes.
        assert wide.losses(Capacity(False, chars=10)) == [
            "characters",
            "sign",
            INVALID_MOVE,
        ]
        assert wide.losses(Capacity(False, chars=11)) == ["sign", INVALID_MOVE]
        assert wide.losses(Capacity(False, chars=10, group=True)) == ["characters"]
        assert wide.losses(Capacity(False, chars=11, group=True)) == []
        assert Capacity(True, 9).losses(Capacity(False, chars=9)) == []
        text = Capacity(False, chars=8)
        assert text.losses(Capacity(False, chars=7)) == ["characters"]
        assert text.losses(Capacity(True, 7)) == ["high-order digits"]
        assert text.losses(Capacity(True, 8)) == []

    def test_through(self) -> None:
        wide = Capacity(True, 9, 2, signed=True)
        assert wide.through(Capacity(True, 7, 3)) == Capacity(True, 7, 2)
        assert wide.through(Capacity(False, chars=6)) == Capacity(False, chars=6)
        assert Capacity(False, chars=9).through(Capacity(True, 6)) == Capacity(True, 6)
        assert Capacity(False, chars=9).through(Capacity(False, chars=4)) == Capacity(
            False, chars=4
        )

    def test_describe(self) -> None:
        assert Capacity(True, 7, 2, signed=True).describe() == (
            "signed 7 integer + 2 decimal digits"
        )
        assert Capacity(True, 6).describe() == "6 digits"
        assert Capacity(False, chars=3).describe() == "3 characters"

    def test_normalize_picture(self) -> None:
        assert normalize_picture("PIC S9(7)V99.") == "S9(7)V99"
        assert normalize_picture("picture is x(3)") == "X(3)"
        assert normalize_picture(" 9(9) ") == "9(9)"


class TestWidening:
    def test_start(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze(
            "CUST-ID", "PIC 9(9)", program="CUSTWRT"
        )
        assert report.start_found
        (start,) = report.starts
        assert start["qualified_name"] == "CUST-REC.CUST-ID"
        assert (start["old_bytes"], start["new_bytes"]) == (6, 9)
        assert start["new_usage"] == "DISPLAY"

    def test_truncations(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        text = _find(report, "truncation", "CUSTWRT", "WS-ID-TEXT")
        assert text.severity == "error"
        assert "loses characters" in text.message
        assert text.line == 28
        assert _find(report, "truncation", "CUSTWRT", "WS-CUST.WS-ID").severity == (
            "error"
        )
        # Across the dataset, into the reader's own copy of the field.
        reader = _find(report, "truncation", "CUSTRD", "CUST-REC.CUST-ID")
        assert reader.severity == "error"
        assert any(hop.node.startswith("PROD.CUST") for hop in reader.path)
        # Wide enough: no finding.
        _absent(report, "CUSTWRT", "WS-ID-WIDE")
        _absent(report, "CUSTWRT", "WS-COUNT")

    def test_pre_existing(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        short = _find(report, "truncation", "CUSTWRT", "WS-ID-SHORT")
        assert short.severity == "info"
        assert short.pre_existing
        assert "could not hold the old value" in short.message

    def test_cut_once_along_a_path(self, graph) -> None:
        # CUSTSUB's SUB-ID gets CUST-ID only through WS-ID and LK-ID, each
        # 6 digits: the cut happens at WS-ID and is not reported again.
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        _absent(report, "CUSTSUB", "SUB-ID")
        _absent(report, "CUSTSUB", "LK-CUST.LK-ID")

    def test_decimal_places_are_a_warning(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-BAL", "S9(7)V999")
        copy_ = _find(report, "truncation", "CUSTWRT", "WS-BAL-COPY")
        assert copy_.severity == "warning"
        assert "decimal places" in copy_.message
        # Already one decimal short: the change adds nothing in kind.
        short = _find(report, "truncation", "CUSTWRT", "WS-BAL-SHORT")
        assert short.pre_existing and short.severity == "info"

    def test_new_loss_beside_an_old_one(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-BAL", "S9(9)V99")
        short = _find(report, "truncation", "CUSTWRT", "WS-BAL-SHORT")
        assert short.severity == "error"
        assert not short.pre_existing

    def test_computed_values_are_warnings(self) -> None:
        reports = [
            _report(SAMPLES / "lineage" / f"{n}.cbl")
            for n in ("WRITER", "READER", "SUBPGM")
        ]
        report = FieldWideningAnalyzer(LineageGraph(reports)).analyze(
            "WS-AMT", "9(10)V99", "WRITER"
        )
        # ADD WS-AMT TO WS-TOTAL: 9(9)V99 no longer holds the sum.
        total = _find(report, "truncation", "WRITER", "WS-TOTAL")
        assert total.severity == "warning"
        assert total.message.startswith("a value computed from it")
        # COMPUTE WS-FEE = WS-AMT * WS-RATE overflowed the old value too
        # (a rate): the arithmetic's business, not reported.
        _absent(report, "WRITER", "WS-FEE")
        # A REDEFINES is a layout question, not a receiver.
        assert not [
            f for f in report.findings if f.kind == "truncation" and f.field == "WS-ALT"
        ]
        redefines = _find(report, "layout", "WRITER", "WS-ALT")
        assert "REDEFINES" in redefines.message

    def test_column(self) -> None:
        reports = [_report(SAMPLES / "lineage" / "WRITER.cbl")]
        report = FieldWideningAnalyzer(LineageGraph(reports)).analyze(
            "WS-AMT", "9(9)V99"
        )
        column = _find(report, "column", None, "ACCOUNT.BALANCE")
        assert column.severity == "warning"
        assert "DCLGEN" in column.message


class TestLayout:
    def test_record_and_file(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        shifted = _find(report, "layout", "CUSTWRT", "CUST-REC")
        assert "grows from 31 to 34 bytes" in shifted.message
        assert "CUST-REC.CUST-NAME" in shifted.message
        lrecl = _find(report, "layout", "CUSTWRT", "file:CUSTOUT")
        assert "LRECL" in lrecl.message and "PROD.CUST" in lrecl.message
        other = _find(report, "layout", "CUSTRD", "dataset:PROD.CUST")
        assert other.severity == "error"

    def test_group_move(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        move = _find(report, "layout", "CUSTWRT", "WS-CUST")
        assert move.statement == "MOVE"
        assert move.line == 34

    def test_same_layout(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        same = _find(report, "same-layout", "CUSTRD", "CUST-REC.CUST-ID")
        assert same.severity == "info"

    def test_caller_of_a_widened_linkage_record(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("LK-ID", "9(9)")
        caller = _find(report, "layout", "CUSTWRT", "WS-CUST")
        assert caller.severity == "error"
        assert "addresses bytes past the argument" in caller.message

    def test_callee_of_a_widened_argument(self) -> None:
        reports = [
            _report(SAMPLES / "lineage" / f"{n}.cbl") for n in ("WRITER", "SUBPGM")
        ]
        report = FieldWideningAnalyzer(LineageGraph(reports)).analyze(
            "WS-ACCT", "X(12)", "WRITER"
        )
        _find(report, "layout", "WRITER", "call:SUBPGM#1")
        callee = _find(report, "layout", "SUBPGM", "LK-REC")
        assert "LINKAGE parameter 1" in callee.message

    def test_same_size_moves_nothing(self, graph) -> None:
        # 9(6) -> X(6): same bytes, so no record changes.
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "X(6)", "CUSTWRT")
        assert not [f for f in report.findings if f.kind == "layout"]


class TestNarrowing:
    def test_feeders_are_cut(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("SUB-ID", "9(4)")
        feeder = _find(report, "truncation", "CUSTSUB", "LK-CUST.LK-ID")
        assert feeder.severity == "error"
        assert feeder.message.startswith("feeds SUB-ID")
        # Further back, already reported at the nearest feeder.
        _absent(report, "CUSTWRT", "WS-CUST.WS-ID")


class TestEdgeCases:
    def test_no_such_field(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("NOPE", "9(9)")
        assert not report.start_found
        assert report.to_dict()["start_found"] is False
        assert "no such field" in report.to_text()

    def test_group_start(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-REC", "X(40)", "CUSTWRT")
        assert report.starts == []
        assert "group item" in report.caveats[0]

    def test_unsizable_picture(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "", "CUSTWRT")
        assert report.starts == []
        assert "not a PICTURE" in report.caveats[0]

    def test_several_matches(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)")
        assert {s["program"] for s in report.starts} == {"CUSTWRT", "CUSTRD"}
        assert any("matches 2 fields" in c for c in report.caveats)

    def test_report_without_pictures(self, reports) -> None:
        stripped = copy.deepcopy(reports)
        for data in stripped:
            if data["program_id"] == "CUSTRD":
                for item in data["items"]:
                    item.pop("picture", None)
        graph = LineageGraph(
            stripped,
            [
                DatasetBinding("CUSTWRT", "CUSTOUT", "PROD.CUST"),
                DatasetBinding("CUSTRD", "CUSTIN", "PROD.CUST"),
            ],
        )
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        assert "CUSTRD:CUST-REC.CUST-ID: no PICTURE in its report" in report.unchecked
        _absent(report, "CUSTRD", "CUST-REC.CUST-ID")
        # And as the start: not checked, said so.
        report = FieldWideningAnalyzer(graph).analyze("RD-ID", "9(9)")
        assert report.starts == []
        assert "no PICTURE" in report.caveats[0]

    def test_shapes(self, graph) -> None:
        report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", "CUSTWRT")
        data = report.to_dict()
        assert data["widening_version"] == "1"
        assert data["summary"]["findings"] == len(data["findings"])
        assert data["summary"]["error"] >= 3
        assert data["programs"] == ["CUSTRD", "CUSTWRT"]
        assert report.worst_severity() == "error"
        # Errors first.
        severities = [f["severity"] for f in data["findings"]]
        assert severities == sorted(severities, key=["error", "warning", "info"].index)
        assert "path" in data["findings"][0] or data["findings"][0]["kind"] == "layout"
        text = report.to_text()
        assert text.startswith("CUST-ID -> PIC 9(9)")
        assert "[pre-existing]" in text
        assert WideningReport("X", "9", None).worst_severity() is None
        assert "No findings." in WideningReport("X", "9", None).to_text()


class TestLineageReportAdditions:
    """What field_lineage records for this check: PICTURE / USAGE /
    REDEFINES on items, and group-level byte transfers between records."""

    def test_items(self) -> None:
        data = _report(SAMPLES / "lineage" / "WRITER.cbl")
        items = {i["qualified_name"]: i for i in data["items"]}
        assert items["WS-REC.WS-AMT"]["picture"] == "9(7)V99"
        assert items["WS-REC.WS-AMT"]["usage"] == "DISPLAY"
        assert "picture" not in items["WS-REC"]
        assert items["WS-ALT"]["redefines"] == "WS-REC"
        assert "redefines" not in items["WS-REC"]

    def test_overlays(self) -> None:
        data = _report(SAMPLES / "lineage" / "WRITER.cbl")
        assert data["overlays"] == [
            {
                "source": "IN-REC",
                "target": "WS-REC",
                "source_length": 19,
                "target_length": 19,
                "line": 30,
                "statement": "READ INTO",
            }
        ]
        # Elementary MOVEs and MOVE CORRESPONDING pair by name, not bytes.
        data = _report(WIDENING / "CUSTSUB.cbl")
        assert data["overlays"] == []

    def test_overlay_origin(self) -> None:
        from cobolparser.analysis.field_lineage import apply_source_map

        result = parse_cobol((SAMPLES / "lineage" / "WRITER.cbl").read_text())
        report = FieldFlowAnalyzer().analyze(result.ast)
        apply_source_map(report, {30: ("WRITER.cpy", 7)})
        (overlay,) = report.to_dict()["overlays"]
        assert overlay["origin"] == {"file": "WRITER.cpy", "line": 7}
        graph = LineageGraph([report.to_dict()])
        found = FieldWideningAnalyzer(graph).analyze("WS-AMT", "9(9)V99")
        assert _find(found, "layout", "WRITER", "IN-REC").line == 7


def _inline(*sources: str) -> LineageGraph:
    reports = []
    for source in sources:
        result = parse_cobol(source)
        assert result.success, result.errors
        reports.append(FieldFlowAnalyzer().analyze(result.ast).to_dict())
    return LineageGraph(reports, [])


def _program(name: str, data: str, procedure: str, using: str = "") -> str:
    lines = [
        "IDENTIFICATION DIVISION.",
        f"PROGRAM-ID. {name}.",
        "DATA DIVISION.",
        *data.strip().splitlines(),
        f"PROCEDURE DIVISION{using}.",
        *procedure.strip().splitlines(),
    ]
    return "\n".join("       " + line.strip() for line in lines) + "\n"


class TestRegressions:
    def test_edited_receiver_without_sign_symbol_drops_the_sign(self) -> None:
        """#757: ZZZZ9 cannot show a sign; -ZZZ9 can."""
        graph = _inline(
            _program(
                "SIGNED",
                """
                WORKING-STORAGE SECTION.
                01 AMT PIC 9(4).
                01 ED-PLAIN PIC ZZZ9.
                01 ED-SIGN PIC -ZZZ9.
                """,
                "MOVE AMT TO ED-PLAIN. MOVE AMT TO ED-SIGN. GOBACK.",
            )
        )
        report = FieldWideningAnalyzer(graph).analyze("AMT", "S9(4)")
        finding = _find(report, "truncation", "SIGNED", "ED-PLAIN")
        assert "sign" in finding.message
        _absent(report, "SIGNED", "ED-SIGN")

    def test_sign_and_decimal_point_into_alphanumeric(self) -> None:
        """#822 (#765's fix never landed): a signed numeric MOVEd to an
        elementary alphanumeric item loses its sign, a noninteger one makes
        the MOVE invalid; a group receiver keeps both."""
        graph = _inline(
            _program(
                "WID",
                """
                WORKING-STORAGE SECTION.
                01 AMT PIC 9(5).
                01 R-I PIC X(6).
                01 R-K PIC 9(5).
                01 R-X PIC X(12).
                01 R-G.
                   05 R-G1 PIC X(9).
                """,
                "MOVE AMT TO R-I R-K R-G. MOVE AMT TO R-X. GOBACK.",
            )
        )
        report = FieldWideningAnalyzer(graph).analyze("AMT", "S9(5)")
        for field in ("R-I", "R-X", "R-K"):
            finding = _find(report, "truncation", "WID", field)
            assert finding.severity == "error"
            assert finding.message.endswith("loses sign")
        _absent(report, "WID", "R-G.R-G1")

        report = FieldWideningAnalyzer(graph).analyze("AMT", "9(6)V99")
        finding = _find(report, "truncation", "WID", "R-X")
        assert finding.severity == "error"
        assert INVALID_MOVE in finding.message
        assert not [
            f
            for f in report.findings
            if f.kind == "truncation" and f.field == "R-G.R-G1"
        ]

    def test_receiver_of_a_literal_subscript_is_checked(self) -> None:
        """#759: MOVE A(2) TO X reaches X through an occurrence node."""
        graph = _inline(
            _program(
                "OCC",
                """
                WORKING-STORAGE SECTION.
                01 REC.
                   05 T OCCURS 3.
                      10 A PIC 9(3).
                01 OUT-A PIC 9(3).
                """,
                "MOVE A(2) TO OUT-A. GOBACK.",
            )
        )
        report = FieldWideningAnalyzer(graph).analyze("A", "9(5)")
        finding = _find(report, "truncation", "OCC", "OUT-A")
        assert "high-order digits" in finding.message
        # The start at one subscript is the start, not a receiver.
        _absent(report, "OCC", "REC.T.A(2)")

    def test_redefines_only_flagged_when_it_covers_the_change(self) -> None:
        """#760: a REDEFINES after the changed field just shifts with it."""
        graph = _inline(
            _program(
                "REDEF",
                """
                WORKING-STORAGE SECTION.
                01 REC.
                   05 G-A.
                      10 AMT PIC 9(5).
                      10 FIL PIC X(3).
                   05 G-B REDEFINES G-A PIC X(8).
                   05 D-X PIC X(8).
                   05 D-N REDEFINES D-X PIC 9(8).
                01 REC2 REDEFINES REC PIC X(16).
                """,
                "GOBACK.",
            )
        )
        report = FieldWideningAnalyzer(graph).analyze("AMT", "9(7)")
        _find(report, "layout", "REDEF", "REC.G-B")
        _find(report, "layout", "REDEF", "REC2")
        _absent(report, "REDEF", "REC.D-X")
        _absent(report, "REDEF", "REC.D-N")

    def test_entry_point_linkage_both_ways(self) -> None:
        """#761: a CALL of an ENTRY name meets the ENTRY's USING record."""
        caller = _program(
            "CALLR",
            """
            WORKING-STORAGE SECTION.
            01 REC.
               05 A PIC 9(3).
               05 B PIC X(7).
            """,
            "CALL 'SUBE' USING REC. GOBACK.",
        )
        callee = _program(
            "SUBP",
            """
            LINKAGE SECTION.
            01 LREC PIC X(10).
            01 LREC2 PIC X(4).
            """,
            """
            DISPLAY LREC2. GOBACK.
            ENTRY 'SUBE' USING LREC.
            DISPLAY LREC. GOBACK.
            """,
            using=" USING LREC2",
        )
        graph = _inline(caller, callee)
        forward = FieldWideningAnalyzer(graph).analyze("A", "9(5)", "CALLR")
        _find(forward, "layout", "SUBP", "LREC")
        _absent(forward, "SUBP", "LREC2")
        backward = FieldWideningAnalyzer(graph).analyze("LREC", "X(12)", "SUBP")
        finding = _find(backward, "layout", "CALLR", "REC")
        assert finding.severity == "error"
        assert "to SUBE" in finding.message
        none = FieldWideningAnalyzer(graph).analyze("LREC2", "X(12)", "SUBP")
        _absent(none, "CALLR", "REC")
