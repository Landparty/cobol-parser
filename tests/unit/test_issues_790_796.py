"""Regressions for the 2026-11-01 issue sweep (#790, #793-#796)."""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer
from cobolparser.analysis._sql_flow import analyze_sql
from cobolparser.mcp.link_decks import parse_decks
from cobolparser.mcp.slicing import slice_field
from cobolparser.mcp.sort_layout import map_sort, parse_sort_control, read_back
from cobolparser.mcp.workspace import Workspace

# -- #793: hex VALUE literals ------------------------------------------------

HEX = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HEXCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 HV PIC X(4) VALUE X'C1C2C3C4'.
       01 HEXD.
          05 FILLER PIC X(4) VALUE X'C1C2C3C4'.
       01 HEXT REDEFINES HEXD.
          05 HP PIC X(4).
       01 OK-NAME PIC X(8) VALUE 'PGMOK'.
       PROCEDURE DIVISION.
           CALL HV.
           CALL HP.
           CALL OK-NAME.
           GOBACK.
"""


def _dynamic_calls(source: str) -> dict:
    result = parse_cobol(source)
    assert result.errors == []
    DynamicCallAnalyzer().analyze(result.ast)
    return {
        c.called_program: c
        for c in result.ast.find_all_by_type("CallStatement")
        if c.is_dynamic
    }


def test_hex_value_is_no_candidate_and_incomplete():
    calls = _dynamic_calls(HEX)
    for name in ("HV", "HP"):
        call = calls[name]
        assert not (call.get_metadata("possible_values") or [])
        assert call.get_metadata("possible_values_incomplete") is True
    assert calls["OK-NAME"].get_metadata("possible_values_incomplete") is not True


# -- #790: DB2 delimited identifiers -----------------------------------------


def test_sql_flow_unquotes_delimited_tables():
    cases = {
        'SELECT C1 INTO :HV-A FROM "TAB4"': ("TAB4", "C1"),
        'SELECT C1 INTO :HV-A FROM SCH."TAB5" WHERE C2 = 1': ("SCH.TAB5", "C1"),
        'UPDATE "TAB7" SET C1 = :HV-A': ("TAB7", "C1"),
    }
    for sql, flow in cases.items():
        result = analyze_sql(sql)
        assert [(f.table, f.column) for f in result.flows] == [flow], sql
        assert result.caveats == []


def test_sql_flow_skips_a_delimited_name_with_a_blank():
    result = analyze_sql('SELECT C1 INTO :HV-A FROM "MY TAB" X WHERE X.C2 = 1')
    assert result.flows == []
    assert result.caveats == ["a FROM item that is not a table name is not traced"]


# -- #794: link-edit decks ----------------------------------------------------


def test_continued_include_statements():
    deck = (
        " INCLUDE SYSLIB(MODA,\n"
        "               MODB)\n"
        " INCLUDE SYSLIB(MODC),\n"
        "         OBJLIB(MODD)\n"
        " NAME MAINLM(R)\n"
    )
    (only,) = parse_decks(deck, "a.lnk")
    assert only.load_module == "MAINLM"
    assert [(i["member"], i["library"]) for i in only.includes] == [
        ("MODA", "SYSLIB"),
        ("MODB", "SYSLIB"),
        ("MODC", "SYSLIB"),
        ("MODD", "OBJLIB"),
    ]


def test_one_load_module_per_name_statement():
    deck = (
        " INCLUDE SYSLIB(SUB1)\n ENTRY PGM1\n NAME PGM1(R)\n"
        " INCLUDE SYSLIB(SUB2)\n ENTRY PGM2\n NAME PGM2(R)\n"
    )
    decks = parse_decks(deck, "a.lnk")
    assert [
        (d.load_module, d.entry, [i["member"] for i in d.includes]) for d in decks
    ] == [
        ("PGM1", "PGM1", ["SUB1"]),
        ("PGM2", "PGM2", ["SUB2"]),
    ]


def test_statements_after_last_name_use_the_file_stem():
    decks = parse_decks(" NAME A(R)\n INCLUDE SYSLIB(X)\n", "link/tail.lnk")
    assert [d.load_module for d in decks] == ["A", "TAIL"]


# -- #795: sort_layout ----------------------------------------------------------

FIELDS = [
    ("CUST-ID", 0, 8),
    ("CUST-NAME", 8, 20),
    ("CUST-STATE", 28, 2),
    ("CUST-BAL", 30, 10),
]


def test_outfil_is_named_in_not_mapped():
    control = parse_sort_control(
        [
            "  SORT FIELDS=COPY",
            "  OUTFIL FNAMES=OUT1,INCLUDE=(29,2,CH,EQ,C'NY'),BUILD=(1,8,29,2)",
        ]
    )
    answer = map_sort(control, FIELDS, 40)
    assert answer["not_mapped"] == [
        "OUTFIL FNAMES=OUT1: INCLUDE=(29,2,CH,EQ,C'NY')",
        "OUTFIL FNAMES=OUT1: BUILD=(1,8,29,2)",
    ]
    rows = read_back(control, FIELDS, FIELDS[:1])
    assert rows is not None and "not mapped" in rows[0]["gets"]


def test_field_to_field_comparison():
    control = parse_sort_control(
        ["  SORT FIELDS=(1,8,CH,A)", "  INCLUDE COND=(1,8,CH,EQ,9,8,CH)"]
    )
    (test,) = map_sort(control, FIELDS, 40)["record_tests"]
    assert test["test"].startswith("EQ bytes 9-16 (")


def test_quoted_constant_keeps_comma_and_parenthesis():
    control = parse_sort_control(
        [
            "  SORT FIELDS=(1,8,CH,A)",
            "  INCLUDE COND=((29,2,CH,EQ,C'N,'),OR,(31,1,CH,EQ,C'(X)'))",
        ]
    )
    tests = map_sort(control, FIELDS, 40)["record_tests"]
    assert [t["test"] for t in tests] == ["EQ C'N,'", "EQ C'(X)'"]


def test_unreadable_condition_goes_to_not_mapped():
    control = parse_sort_control(
        ["  SORT FIELDS=(1,8,CH,A)", "  INCLUDE COND=(1,8,SS,EQ,C'A',XX,2)"]
    )
    answer = map_sort(control, FIELDS, 40)
    assert "record_tests" not in answer
    assert answer["not_mapped"] == ["INCLUDE COND=(1,8,SS,EQ,C'A',XX,2)"]


# -- #796: slice ------------------------------------------------------------------

SLC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SLC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(5).
       01 WS-B PIC 9(5).
       01 WS-C PIC 9(5).
       01 WS-D PIC 9(5).
       01 WS-FLAG PIC X.
          88 FLAG-ON VALUE 'Y'.
       01 WS-GRP.
          05 WS-G1 PIC 9(5).
          05 WS-G2 PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-A.
           MOVE WS-A TO WS-B.
           IF WS-B > 10
              COMPUTE WS-C = WS-B * 2
              SET FLAG-ON TO TRUE
           END-IF.
           IF FLAG-ON
              MOVE 1 TO WS-D
           END-IF.
           EVALUATE WS-C
              WHEN 20 MOVE 5 TO WS-G1
              WHEN OTHER MOVE 6 TO WS-G2
           END-EVALUATE.
           ADD WS-G1 TO WS-D.
           DISPLAY WS-D.
           GOBACK.
"""


def _slice(tmp_path: Path, name: str, direction: str) -> dict:
    (tmp_path / "SLC.cbl").write_text(SLC)
    answer = slice_field(Workspace(tmp_path), "SLC.cbl", name, direction)["answer"]
    lines = {
        st["location"]["line"]: st
        for p in answer.get("paragraphs", [])
        for st in p["statements"]
    }
    return {**answer, "lines": lines}


def test_backward_slice_lists_literal_and_set_writes(tmp_path):
    answer = _slice(tmp_path, "WS-D", "backward")
    lines = answer["lines"]
    assert lines[23]["role"] == "data" and lines[23]["flows"] == ["sets WS-D"]
    assert lines[22]["role"] == "control"
    assert lines[20]["flows"] == ["sets WS-FLAG"]
    assert lines[26]["flows"] == ["sets WS-GRP.WS-G1"]
    assert {"WS-FLAG", "WS-B", "WS-C"} <= set(answer["fields"])


def test_backward_slice_of_a_literal_only_field(tmp_path):
    answer = _slice(tmp_path, "WS-G1", "backward")
    assert answer["found"] is True
    assert answer["lines"][26]["role"] == "data"
    assert answer["lines"][25]["role"] == "control"


def test_field_without_edges_is_found(tmp_path):
    answer = _slice(tmp_path, "WS-FLAG", "forward")
    assert answer["found"] is True
    assert answer["lines"][22]["role"] == "decision"
    assert "WS-D" in answer["fields"]


def test_forward_follows_controlled_writes(tmp_path):
    answer = _slice(tmp_path, "WS-A", "forward")
    assert {"WS-FLAG", "WS-GRP.WS-G1", "WS-D"} <= set(answer["fields"])
    assert answer["lines"][30]["role"] == "data"
