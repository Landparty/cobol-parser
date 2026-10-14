"""Per-program field lineage (``analysis.field_lineage``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis._names import callee_names
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
        assert data["lineage_version"] == "2"
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


def _program(
    ws: str, proc: str, name: str = "T1", fd: str = "", select: str = ""
) -> FieldFlowReport:
    """A small program around WORKING-STORAGE *ws* and PROCEDURE *proc*."""
    lines = ["       IDENTIFICATION DIVISION.", f"       PROGRAM-ID. {name}."]
    if select:
        lines += [
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            f"           {select}",
        ]
    lines.append("       DATA DIVISION.")
    if fd:
        lines.append("       FILE SECTION.")
        lines += ["       " + line for line in fd.strip().splitlines()]
    lines.append("       WORKING-STORAGE SECTION.")
    lines += ["       " + line for line in ws.strip().splitlines()]
    lines += ["       PROCEDURE DIVISION.", "       MAIN-PARA."]
    lines += ["           " + line for line in proc.strip().splitlines()]
    lines.append("           GOBACK.")
    result = parse_cobol("\n".join(lines) + "\n", f"{name}.cbl")
    assert result.ast is not None and not result.errors, result.errors
    return FieldFlowAnalyzer().analyze(result.ast)


@pytest.mark.parametrize(
    "select", ["SELECT F ASSIGN TO INDD,", "SELECT F ASSIGN TO INDD;"]
)
def test_separator_after_assign_names_the_dd_port(select: str) -> None:
    """Issue #342: ``ASSIGN TO INDD,`` made the port ``file:,``."""
    report = _program(
        "01 X PIC X.",
        "OPEN INPUT F\nREAD F\nDISPLAY R",
        fd="FD F.\n01 R PIC X(4).",
        select=select + "\n               ORGANIZATION IS SEQUENTIAL.",
    )
    assert [p.key for p in report.ports if p.kind == "file"] == ["INDD"]


def _flagged(report: FieldFlowReport) -> dict[tuple[str, str, str], bool]:
    return {(e.kind, e.source.label(), e.target.label()): e.exact for e in report.edges}


class TestOccursDependingOn:
    FD = """
FD F.
01 R.
   05 N PIC 9(2).
   05 T OCCURS 1 TO 5 DEPENDING ON N.
      10 TV PIC X(2).
   05 TRAILER PIC X(3).
"""

    def test_fields_after_the_table_have_no_offset_and_do_not_crash(self) -> None:
        report = _program(
            "01 X PIC X.",
            "OPEN INPUT F\nREAD F\nDISPLAY TRAILER",
            fd=self.FD,
            select="SELECT F ASSIGN TO INDD.",
        )
        edges = _edges(report)
        assert ("read", "file:INDD", "R.TRAILER") in edges
        assert ("display", "R.TRAILER", "console:SYSOUT@0+3") in edges
        assert any(f.source.label() == "file:INDD" for f in report.summary)

    def test_none_offsets_sort_first(self) -> None:
        nodes = [LineageNode("file", "DD", 4, 2), LineageNode("file", "DD", None, 3)]
        assert sorted(nodes)[0].offset is None


class TestOccursTables:
    def test_group_move_into_a_table_reaches_every_occurrence_inexactly(self) -> None:
        report = _program(
            """
01 R.
   05 A PIC X(2).
   05 B PIC X(2).
   05 C PIC X(2).
01 T.
   05 E OCCURS 3 PIC X(2).
""",
            "MOVE R TO T",
        )
        flagged = _flagged(report)
        for source in ("R.A", "R.B", "R.C"):
            assert flagged[("move", source, "T.E")] is False

    def test_literal_subscript_writes_its_own_occurrence(self) -> None:
        report = _program(
            "01 WS-X PIC 9(5).",
            "OPEN OUTPUT F\nMOVE WS-X TO AMT(3)\nWRITE R",
            fd="FD F.\n01 R.\n   05 AMT OCCURS 3 PIC 9(5).",
            select="SELECT F ASSIGN TO OUTDD.",
        )
        flagged = _flagged(report)
        assert flagged[("move", "WS-X", "R.AMT(3)")] is True
        assert flagged[("write", "R.AMT(3)", "file:OUTDD@10+5")] is True
        # The table as a whole still reaches every occurrence's bytes, but
        # never as an exact field.
        assert flagged[("write", "R.AMT", "file:OUTDD@0+5")] is False
        assert flagged[("write", "R.AMT", "file:OUTDD@10+5")] is False
        assert ("move", "WS-X", "R.AMT") not in flagged

    def test_variable_subscript_is_the_whole_table_and_inexact(self) -> None:
        report = _program(
            "01 T.\n   05 Y OCCURS 5 PIC 9(2).\n01 I PIC 9.\n01 X PIC 9(3).",
            "MOVE Y(I) TO X",
        )
        assert _flagged(report) == {("move", "T.Y", "X"): False}

    def test_a_huge_table_is_one_inexact_range(self) -> None:
        report = _program(
            """
01 T.
   05 E OCCURS 2000.
      10 E1 PIC X(2).
      10 E2 PIC X(3).
01 U PIC X(10000).
""",
            "MOVE T TO U\nMOVE U TO T",
        )
        flagged = _flagged(report)
        assert flagged[("move", "T.E.E1", "U")] is False
        assert flagged[("move", "U", "T.E.E2")] is False
        assert not any(e.kind == "redefines" for e in report.edges)

    def test_occurrences_are_not_chained_through_the_table(self) -> None:
        report = _program(
            """
01 T.
   05 E OCCURS 3 PIC X(2).
01 A PIC X(2).
01 B PIC X(2).
""",
            "MOVE A TO E(1)\nMOVE E(3) TO B\nCALL 'SUB' USING A B",
        )
        flows = {(f.source.label(), f.target.label()) for f in report.summary}
        # SUB#1 -> A -> E(1) -> E -> E(3) -> B -> SUB#2 would invent a flow.
        assert ("call:SUB#1@0+2", "call:SUB#2@0+2") not in flows


class TestDuplicateNames:
    def test_two_filler_groups_stay_apart(self) -> None:
        report = _program(
            """
01 FILLER.
   05 FA PIC X(2).
01 FILLER.
   05 FB PIC X(2).
01 X PIC X(2).
""",
            "MOVE FA TO X",
        )
        names = [i["qualified_name"] for i in report.items]
        assert "FILLER" in names and "FILLER#2" in names
        records = {i["qualified_name"]: i["record"] for i in report.items}
        assert records["FILLER.FA"] == "FILLER"
        assert records["FILLER.FB"] == "FILLER#2"
        assert not any(e.kind == "redefines" for e in report.edges)


class TestOperands:
    def test_call_arguments_keep_subscript_qualifier_and_refmod(self) -> None:
        report = _program(
            """
01 G.
   05 A PIC X(2).
01 T.
   05 E OCCURS 3 PIC X(2).
01 Z PIC X(4).
""",
            "CALL 'SUB' USING E(2) A OF G OMITTED Z(1:2)",
        )
        edges = _edges(report)
        assert ("call", "T.E(2)", "call:SUB#1@0+2") in edges
        assert ("call", "G.A", "call:SUB#2@0+2") in edges
        assert ("call", "Z", "call:SUB#4@0+4") in edges
        assert report.port("call", "SUB#3") is not None

    def test_subscripts_refmods_and_qualifiers_are_not_values(self) -> None:
        report = _program(
            """
01 T.
   05 Y OCCURS 5 PIC 9(2).
01 I PIC 9.
01 L PIC 9(2).
01 X PIC 9(3).
01 Z PIC X(10).
01 W PIC X(10).
01 G1.
   05 A PIC X(2).
""",
            """COMPUTE X = Y(I) + 1
MOVE Z(1:L) TO W
STRING Z(1:L) DELIMITED BY SIZE INTO W
MOVE A OF G1 TO W""",
        )
        sources = {e.source.name for e in report.edges}
        assert "I" not in sources and "L" not in sources and "G1" not in sources
        edges = _edges(report)
        assert ("arith", "T.Y", "X") in edges
        assert ("move", "Z", "W") in edges
        assert ("string", "Z", "W") in edges
        assert ("move", "G1.A", "W") in edges

    def test_move_corresponding_pairs_a_group_with_an_elementary_item(self) -> None:
        report = _program(
            """
01 S.
   05 X.
      10 XA PIC X(2).
      10 XB PIC X(2).
   05 Y PIC X(2).
01 T.
   05 X PIC X(4).
   05 Y PIC X(2).
""",
            "MOVE CORRESPONDING S TO T",
        )
        flagged = _flagged(report)
        assert flagged[("move", "S.Y", "T.Y")] is True
        assert flagged[("move", "S.X.XA", "T.X")] is False
        assert flagged[("move", "S.X.XB", "T.X")] is False


class TestAccept:
    def test_clock_sources_are_not_a_console_port(self) -> None:
        # The parser keeps the format qualifier in from_source
        # ("DATE YYYYMMDD"); either way the value comes from the runtime's
        # clock, not from data entering the program.
        report = _program(
            """
01 WS-TODAY PIC 9(8).
01 WS-JULIAN PIC 9(7).
01 WS-DOW PIC 9.
01 WS-NOW PIC 9(8).
01 WS-PARM PIC X(8).
""",
            """
ACCEPT WS-TODAY FROM DATE YYYYMMDD
ACCEPT WS-JULIAN FROM DAY YYYYDDD
ACCEPT WS-DOW FROM DAY-OF-WEEK
ACCEPT WS-NOW FROM TIME
ACCEPT WS-PARM
""",
        )
        assert [p.key for p in report.ports if p.kind == "console"] == ["SYSIN"]
        assert {e.target.label() for e in report.edges if e.kind == "accept"} == {
            "WS-PARM"
        }


class TestReturning:
    def test_procedure_division_returning_is_an_outgoing_port(self) -> None:
        text = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 W PIC S9(9) COMP VALUE 5.
       LINKAGE SECTION.
       01 LA PIC X(2).
       01 LR PIC S9(9) COMP.
       PROCEDURE DIVISION USING LA RETURNING LR.
       MAIN-PARA.
           MOVE W TO LR
           GOBACK.
"""
        result = parse_cobol(text, "SUBR.cbl")
        assert result.ast is not None
        report = FieldFlowAnalyzer().analyze(result.ast)
        port = report.port("linkage", "SUBR#RETURNING")
        assert port is not None and port.directions == {"out"}
        assert ("linkage", "LR", "linkage:SUBR#RETURNING@0+4") in _edges(report)


class TestDynamicCallFigurativeCandidates:
    """A MOVE SPACES (or LOW-/HIGH-VALUES, ZERO) to a dynamic CALL's identifier
    is the "no program" sentinel, never a callee: it must not become a
    blank ``call:#n`` port joined to every real candidate."""

    WS = """
01 WS-PGM PIC X(8) VALUE SPACES.
01 WS-ARG PIC X(4).
"""

    def test_blank_candidate_is_not_a_callee(self) -> None:
        report = _program(
            self.WS,
            "MOVE 'SUBA' TO WS-PGM\nMOVE SPACES TO WS-PGM\n"
            "MOVE LOW-VALUES TO WS-PGM\nMOVE HIGH-VALUES TO WS-PGM\n"
            "MOVE ZERO TO WS-PGM\nCALL WS-PGM USING WS-ARG",
        )
        callees = {p.key for p in report.ports if p.kind == "call"}
        assert callees == {"SUBA#1"}
        assert report.caveats == []

    def test_only_blank_candidates_fall_back_to_the_unresolved_caveat(self) -> None:
        report = _program(self.WS, "MOVE SPACES TO WS-PGM\nCALL WS-PGM USING WS-ARG")
        callees = {p.key for p in report.ports if p.kind == "call"}
        assert callees == {"?WS-PGM#1"}
        assert any("no candidate program names" in c for c in report.caveats)

    def test_callee_names_keeps_only_program_names(self) -> None:
        assert callee_names([" ", "\x00", "\xff", "0", "'suba'", "SUBA", "''"]) == [
            "SUBA"
        ]
