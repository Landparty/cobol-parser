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

    def test_sql_host_variable_in_a_table_is_inexact(self) -> None:
        """Issue #507: a multi-row FETCH into / INSERT from a table field was
        flagged exact, against "every edge through a table is inexact"."""
        report = _program(
            """
01 WS-ARR.
   05 EMPNO PIC X(6) OCCURS 10 TIMES.
01 WS-ONE PIC X(6).
""",
            """
EXEC SQL DECLARE C1 CURSOR FOR SELECT EMPNO FROM EMP END-EXEC
EXEC SQL FETCH NEXT ROWSET FROM C1 FOR 10 ROWS
  INTO :EMPNO END-EXEC
EXEC SQL INSERT INTO EMP3 (EMPNO) VALUES (:EMPNO) END-EXEC
EXEC SQL INSERT INTO EMP4 (EMPNO) VALUES (:WS-ONE) END-EXEC
""",
        )
        flagged = _flagged(report)
        assert flagged[("sql", "sql:EMP.EMPNO", "WS-ARR.EMPNO")] is False
        assert flagged[("sql", "WS-ARR.EMPNO", "sql:EMP3.EMPNO")] is False
        # A host variable outside any table keeps its exact edge.
        assert flagged[("sql", "WS-ONE", "sql:EMP4.EMPNO")] is True


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


class TestArithmeticCorresponding:
    WS = """
01 WS-IN.
   05 IN-ID PIC X(5).
   05 IN-AMT PIC 9(5).
   05 IN-FEE PIC S9(3)V99 COMP-3.
   05 IN-NOTE PIC 9(3).
   05 IN-SUB.
      10 IN-QTY PIC 9(3).
01 WS-OUT.
   05 IN-ID PIC X(5).
   05 IN-AMT PIC 9(5).
   05 IN-FEE PIC ZZ9.99.
   05 IN-NOTE PIC X(3).
   05 IN-SUB.
      10 IN-QTY PIC 9(3).
"""

    @pytest.mark.parametrize(
        ("statement", "verb"),
        [
            ("ADD CORRESPONDING WS-IN TO WS-OUT", "ADD"),
            ("SUBTRACT CORR WS-IN FROM WS-OUT ROUNDED", "SUBTRACT"),
        ],
    )
    def test_pairs_numeric_items_by_name_path_only(self, statement, verb) -> None:
        report = _program(self.WS, statement)
        # Same-name numeric pairs (numeric-edited receiver included, nested
        # groups matched by their full path); IN-ID is alphanumeric on both
        # sides and IN-NOTE on the receiving one, so neither takes part.
        assert _edges(report) == {
            ("arith", "WS-IN.IN-AMT", "WS-OUT.IN-AMT"),
            ("arith", "WS-IN.IN-FEE", "WS-OUT.IN-FEE"),
            ("arith", "WS-IN.IN-SUB.IN-QTY", "WS-OUT.IN-SUB.IN-QTY"),
        }
        assert all(e.exact for e in report.edges)
        assert {e.statement for e in report.edges} == {f"{verb} CORRESPONDING"}

    def test_plain_add_of_groups_is_unchanged(self) -> None:
        report = _program(
            "01 A PIC 9(3).\n01 B PIC 9(3).\n01 C PIC 9(3).", "ADD A TO B GIVING C"
        )
        assert _edges(report) == {("arith", "A", "C"), ("arith", "B", "C")}


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


def test_condition_names_under_a_filler_and_renames_are_not_undeclared() -> None:
    # Issue #485: xref used to drop the level-88s under a FILLER and every
    # level-66 RENAMES item, and lineage reported them as undeclared.
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. F88.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SW.
           05  FILLER   PIC X VALUE 'N'.
               88  SW-ON  VALUE 'Y'.
       01  WS-REC.
           05  R-A PIC X(3).
           05  R-B PIC 9(2).
       66  R-AB RENAMES R-A THRU R-B.
       PROCEDURE DIVISION.
           SET SW-ON TO TRUE
           IF SW-ON DISPLAY R-AB END-IF
           GOBACK.
"""
    result = parse_cobol(source)
    assert result.ast is not None
    report = FieldFlowAnalyzer().analyze(result.ast)
    assert not any("not declared in this program" in c for c in report.caveats)


def _source_report(source: str) -> FieldFlowReport:
    result = parse_cobol(source)
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


_RENAMES_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. R66.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-OUT PIC X(5).
       01  WS-IN  PIC X(5).
       01  WS-REC.
           05  R-A PIC X(3).
           05  R-B PIC 9(2).
           05  R-C PIC X(4).
       66  R-AB RENAMES R-A THRU R-B.
       PROCEDURE DIVISION.
           MOVE WS-IN TO R-AB
           MOVE R-AB TO WS-OUT
           GOBACK.
"""


def test_renames_item_flows_through_the_fields_it_renames() -> None:
    # Issue #485 review: once xref declared R-AB, lineage must trace it
    # (R-A THRU R-B) rather than drop it with no caveat.
    report = _source_report(_RENAMES_SOURCE)
    edges = _edges(report)
    assert ("move", "WS-REC.R-A", "WS-OUT") in edges
    assert ("move", "WS-REC.R-B", "WS-OUT") in edges
    assert ("move", "WS-IN", "WS-REC.R-A") in edges
    assert ("move", "WS-IN", "WS-REC.R-B") in edges
    assert not any("R-C" in label for _k, s, t in edges for label in (s, t))
    assert not any("not traced" in c for c in report.caveats)
    alias = next(i for i in report.items if i["name"] == "R-AB")
    assert (alias["level"], alias["offset"], alias["length"]) == (66, 0, 5)
    assert alias["record"] == "WS-REC"


def test_renames_item_that_cannot_be_placed_is_a_caveat() -> None:
    report = _source_report(
        _RENAMES_SOURCE.replace("RENAMES R-A THRU R-B", "RENAMES R-A THRU NOPE")
    )
    assert any(
        c.startswith("RENAMES item R-AB not traced") and "NOPE" in c
        for c in report.caveats
    )


WRITE_FROM_FLAT = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLATOUT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO OUTDD.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC                PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-ID              PIC X(10).
           05  WS-AMT             PIC 9(6).
       01  WS-LONG                PIC X(30).
       PROCEDURE DIVISION.
           WRITE OUT-REC FROM WS-REC
           WRITE OUT-REC FROM WS-LONG
           GOBACK.
"""


class TestWriteFromFlatRecord:
    """WRITE flat-REC FROM structured-REC puts each source field on the
    file at its own bytes, exactly, instead of the whole record."""

    def test_source_fields_reach_their_own_bytes(self) -> None:
        result = parse_cobol(WRITE_FROM_FLAT, "FLATOUT.cbl")
        assert result.ast is not None
        report = FieldFlowAnalyzer().analyze(result.ast)
        to_file = {
            (e.source.label(), e.target.label(), e.exact)
            for e in report.edges
            if e.target.label().startswith("file:")
        }
        assert ("WS-REC.WS-ID", "file:OUTDD@0+10", True) in to_file
        assert ("WS-REC.WS-AMT", "file:OUTDD@10+6", True) in to_file
        assert not any(
            src.startswith("WS-REC") and "@0+20" in dst for src, dst, _ in to_file
        )
        # A source longer than the record is truncated: through the record.
        assert ("OUT-REC", "file:OUTDD@0+20", True) in to_file


def _funnel(fields: int) -> str:
    """*fields* input fields all MOVEd through one work area to *fields*
    output fields: a summary of fields x fields flows."""
    ins = "\n".join(f"          05 IN-F{i} PIC X(4)." for i in range(fields))
    outs = "\n".join(f"          05 OUT-F{i} PIC X(4)." for i in range(fields))
    moves_in = "\n".join(f"           MOVE IN-F{i} TO WS-HUB." for i in range(fields))
    moves_out = "\n".join(f"           MOVE WS-HUB TO OUT-F{i}." for i in range(fields))
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FUNNEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INF ASSIGN TO INDD.
           SELECT OUTF ASSIGN TO OUTDD.
       DATA DIVISION.
       FILE SECTION.
       FD INF.
       01 IN-REC.
{ins}
       FD OUTF.
       01 OUT-REC.
{outs}
       WORKING-STORAGE SECTION.
       01 WS-HUB PIC X(4).
       PROCEDURE DIVISION.
           READ INF.
{moves_in}
{moves_out}
           WRITE OUT-REC.
           GOBACK.
"""


@pytest.fixture(scope="module")
def ast():
    result = parse_cobol(_funnel(12), "FUNNEL.cbl")
    assert result.ast is not None
    return result.ast


class TestSummaryLimit:
    def test_unlimited_lists_every_flow(self, ast) -> None:
        report = FieldFlowAnalyzer(summary_limit=None).analyze(ast)
        assert len(report.summary) == 144
        assert not report.summary_truncated
        assert not any("summary" in c for c in report.caveats)

    def test_limit_stops_the_summary_with_a_caveat(self, ast) -> None:
        full = FieldFlowAnalyzer(summary_limit=None).analyze(ast)
        report = FieldFlowAnalyzer(summary_limit=50).analyze(ast)
        assert len(report.summary) == 50
        assert report.summary_truncated
        assert set(report.summary) <= set(full.summary)
        # The edges, which LineageGraph traces, are never cut.
        assert report.edges == full.edges
        assert any("stops at 50 flows" in c for c in report.caveats)
        data = report.to_dict()
        assert data["statistics"]["summary"] == 50
        assert data["statistics"]["summary_truncated"] is True

    def test_limit_zero_skips_the_summary(self, ast) -> None:
        report = FieldFlowAnalyzer(summary_limit=0).analyze(ast)
        assert report.summary == [] and report.summary_truncated
        assert any("not computed" in c for c in report.caveats)

    def test_limit_not_reached(self, ast) -> None:
        report = FieldFlowAnalyzer(summary_limit=144).analyze(ast)
        assert len(report.summary) == 144 and not report.summary_truncated

    def test_default_limit(self) -> None:
        from cobolparser.analysis.field_lineage import DEFAULT_SUMMARY_LIMIT

        assert FieldFlowAnalyzer().summary_limit == DEFAULT_SUMMARY_LIMIT

    def test_negative_limit_is_refused(self) -> None:
        with pytest.raises(ValueError):
            FieldFlowAnalyzer(summary_limit=-1)
