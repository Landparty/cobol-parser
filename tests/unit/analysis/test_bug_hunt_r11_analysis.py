"""Bug hunt round 11: dead code, program flow, dynamic CALL values, MOVE
type checking, DCLGEN, IO diagnostics, constant folding and IMS segments.

Each test reproduces one defect found by feeding a small, valid COBOL
program through the public analyzer API.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.dclgen_check import DclgenChecker
from cobolparser.analysis.dead_code import DeadCodeAnalyzer
from cobolparser.analysis.ims_segment_analyzer import IMSSegmentAnalyzer
from cobolparser.analysis.io_diagnostics import IODiagnosticHelper, IOErrorCode
from cobolparser.analysis.move_type_checker import MoveTypeChecker
from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.analysis.value_tracker import DynamicCallAnalyzer
from cobolparser.generators import ProgramLayoutIndex


def _parse(source: str):
    result = parse_cobol(source)
    assert not result.errors, result.errors
    return result.ast


def _program(procedure: str, working_storage: str = "", head: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T1.\n"
        f"{head}"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{working_storage}"
        "       PROCEDURE DIVISION.\n"
        f"{procedure}"
    )


# ---------------------------------------------------------------------------
# Sentences before the first paragraph header (the parser's unnamed paragraph)
# ---------------------------------------------------------------------------

_SECTION_BODY = _program(
    "       MAIN SECTION.\n"
    "           PERFORM WORK-SEC\n"
    "           STOP RUN.\n"
    "       M-DEAD.\n"
    "           DISPLAY 'DEAD'.\n"
    "       WORK-SEC SECTION.\n"
    "           DISPLAY 'W'.\n"
    "       UNUSED SECTION.\n"
    "       U1.\n"
    "           DISPLAY 'DEAD'.\n"
)


def test_dead_code_sees_stop_run_in_a_section_body():
    dead = [
        d.name for d in DeadCodeAnalyzer().analyze(_parse(_SECTION_BODY)).dead_items
    ]
    # MAIN's own STOP RUN ends the program: nothing after it falls through.
    assert "M-DEAD" in dead
    assert "UNUSED" in dead and "U1" in dead
    assert "WORK-SEC" not in dead


def test_dead_code_sees_stop_run_before_the_first_paragraph():
    ast = _parse(
        _program(
            "           PERFORM P2\n"
            "           STOP RUN.\n"
            "       P1.\n"
            "           DISPLAY 'DEAD'.\n"
            "       P2.\n"
            "           DISPLAY 'LIVE'.\n"
        )
    )
    dead = [d.name for d in DeadCodeAnalyzer().analyze(ast).dead_items]
    assert dead == ["P1"]


def test_dead_code_leading_sentences_without_terminator_still_fall_through():
    ast = _parse(
        _program("           DISPLAY 'X'.\n       P1.\n           STOP RUN.\n")
    )
    assert DeadCodeAnalyzer().analyze(ast).dead_items == []


def test_program_flow_scans_a_section_body_as_the_section_node():
    report = ProgramFlowAnalyzer().analyze(_parse(_SECTION_BODY))
    edges = {(e.source, e.target, e.edge_type) for e in report.edges}
    assert ("MAIN", "WORK-SEC", FlowEdgeType.PERFORM) in edges
    # The section's STOP RUN suppresses its fall-through edge.
    assert ("MAIN", "M-DEAD", FlowEdgeType.FALL_THROUGH) not in edges
    assert "M-DEAD" in report.unreachable_nodes
    main = next(n for n in report.nodes if n.name == "MAIN")
    assert main.statement_count == 2


# ---------------------------------------------------------------------------
# DynamicCallAnalyzer
# ---------------------------------------------------------------------------


def _dynamic_call(statement: str, working_storage: str | None = None):
    ws = working_storage or (
        "       01 WS-PROG PIC X(8) VALUE 'PROGA'.\n" "       01 WS-IN PIC X(8).\n"
    )
    ast = _parse(
        _program(
            "       P1.\n"
            f"{statement}"
            "           CALL WS-PROG\n"
            "           STOP RUN.\n",
            ws,
        )
    )
    DynamicCallAnalyzer().analyze(ast)
    return next(c for c in ast.find_all_by_type("CallStatement") if c.is_dynamic)


def test_dynamic_call_values_incomplete_after_accept_string_initialize():
    for statement in (
        "           ACCEPT WS-PROG\n",
        "           STRING 'PR' 'OGB' DELIMITED BY SIZE INTO WS-PROG\n",
        "           UNSTRING WS-IN DELIMITED BY ' ' INTO WS-PROG\n",
        "           INITIALIZE WS-PROG\n",
        "           INSPECT WS-PROG REPLACING ALL 'A' BY 'B'\n",
        "           CALL 'GETNAME' USING WS-PROG\n",
    ):
        call = _dynamic_call(statement)
        assert call.possible_values == ["PROGA"], statement
        assert call.get_metadata("possible_values_incomplete") is True, statement


def test_dynamic_call_values_incomplete_after_group_or_partial_move():
    group_ws = (
        "       01 WS-GRP.\n          05 WS-PROG PIC X(8) VALUE 'PROGA'.\n"
        "       01 WS-IN PIC X(8).\n"
    )
    call = _dynamic_call("           MOVE WS-IN TO WS-GRP\n", group_ws)
    assert call.get_metadata("possible_values_incomplete") is True
    # A literal MOVE to the group gives WS-PROG its slice of the literal,
    # an exact value (#511).
    call = _dynamic_call("           MOVE 'PROGB' TO WS-GRP\n", group_ws)
    assert call.possible_values == ["PROGA", "PROGB"]
    assert call.get_metadata("possible_values_incomplete") is None

    call = _dynamic_call("           MOVE SPACES TO WS-PROG(1:4)\n")
    # A reference-modified MOVE is not the item's whole value.
    assert call.possible_values == ["PROGA"]
    assert call.get_metadata("possible_values_incomplete") is True


def test_dynamic_call_values_complete_for_plain_and_qualified_moves():
    call = _dynamic_call("           MOVE 'PROGB' TO WS-PROG\n")
    assert call.possible_values == ["PROGA", "PROGB"]
    assert not call.get_metadata("possible_values_incomplete")

    group_ws = "       01 WS-GRP.\n          05 WS-PROG PIC X(8) VALUE 'PROGA'.\n"
    call = _dynamic_call("           MOVE 'PROGB' TO WS-PROG OF WS-GRP\n", group_ws)
    assert call.possible_values == ["PROGA", "PROGB"]
    assert not call.get_metadata("possible_values_incomplete")


# ---------------------------------------------------------------------------
# MoveTypeChecker
# ---------------------------------------------------------------------------

_DUPLICATE_NAMES = (
    "       01 GRP1.\n"
    "          05 WS-A PIC X(5).\n"
    "       01 GRP2.\n"
    "          05 WS-A PIC 9(5).\n"
    "       01 WS-AL PIC A(5).\n"
)


def _moves(statement: str):
    ast = _parse(
        _program(
            "       P1.\n" f"{statement}" "           STOP RUN.\n", _DUPLICATE_NAMES
        )
    )
    return MoveTypeChecker().check(ast)


def test_move_type_check_resolves_qualified_duplicate_names():
    assert _moves("           MOVE 'ABCDE' TO WS-A OF GRP1\n").violations == []
    assert _moves("           MOVE WS-A OF GRP1 TO WS-AL\n").violations == []
    # The other declaration is still checked as what it is.
    report = _moves("           MOVE 'ABCDE' TO WS-A OF GRP2\n")
    assert [v.target_category.name for v in report.violations] == ["NUMERIC"]


def test_move_type_check_unqualified_ambiguous_name_is_unresolved():
    report = _moves("           MOVE WS-A TO WS-AL\n")
    assert report.violations == []
    assert report.unresolved_count == 1


# ---------------------------------------------------------------------------
# DclgenChecker / DECLARE TABLE columns
# ---------------------------------------------------------------------------


def _dclgen(columns: str, items: str, host_vars: str, selected: str):
    ast = _parse(
        _program(
            "       P1.\n"
            f"           EXEC SQL SELECT {selected} INTO {host_vars}\n"
            "             FROM T END-EXEC\n"
            "           STOP RUN.\n",
            "           EXEC SQL DECLARE T TABLE\n"
            f"           ( {columns}\n"
            "           ) END-EXEC.\n"
            f"{items}",
        )
    )
    return DclgenChecker().check(ast)


def test_dclgen_usage_synonyms_are_not_mismatches():
    report = _dclgen(
        "A DECIMAL(7, 2) NOT NULL,\n"
        "             B SMALLINT NOT NULL,\n"
        "             C INTEGER NOT NULL,\n"
        "             D DOUBLE NOT NULL",
        "       01 A PIC S9(5)V9(2) PACKED-DECIMAL.\n"
        "       01 B PIC S9(4) BINARY.\n"
        "       01 C PIC S9(9) COMPUTATIONAL-4.\n"
        "       01 D COMPUTATIONAL-2.\n",
        ":A, :B, :C, :D",
        "A, B, C, D",
    )
    assert report.checked == ["A", "B", "C", "D"]
    assert report.violations == []


def test_dclgen_not_null_after_type_words_is_not_nullable():
    report = _dclgen(
        "E CHAR(8) FOR BIT DATA NOT NULL,\n"
        "             F CHAR(4) CCSID EBCDIC NOT NULL",
        "       01 E PIC X(8).\n       01 F PIC X(4).\n",
        ":E, :F",
        "E, F",
    )
    assert report.checked == ["E", "F"]
    assert report.violations == []


# ---------------------------------------------------------------------------
# IODiagnosticHelper
# ---------------------------------------------------------------------------


def test_rewrite_is_valid_on_a_record_sequential_file():
    assert (
        IODiagnosticHelper.validate_io_statement_type("REWRITE", "SEQUENTIAL") is None
    )
    assert (
        IODiagnosticHelper.validate_io_statement_type("REWRITE", "LINE SEQUENTIAL")
        == IOErrorCode.IO_REWRITE_INVALID_ORG
    )


# ---------------------------------------------------------------------------
# ConstantFolder
# ---------------------------------------------------------------------------


def test_const_fold_entry_skips_declaratives():
    ast = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T1.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INDD.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC PIC X(80).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X.\n"
        "       01 WS-B PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        "       DECLARATIVES.\n"
        "       ERR SECTION.\n"
        "           USE AFTER ERROR PROCEDURE ON IN-FILE.\n"
        "       ERR-P.\n"
        "           MOVE 'E' TO WS-B\n"
        "           DISPLAY WS-B.\n"
        "       END DECLARATIVES.\n"
        "       MAIN SECTION.\n"
        "       M1.\n"
        "           MOVE 'M' TO WS-A\n"
        "           DISPLAY WS-A\n"
        "           STOP RUN.\n"
    )
    result = ConstantFolder().fold(ast, ProgramLayoutIndex.build(ast))
    # WS-B is shown only inside the USE procedure, a site the walk never
    # reaches (the runtime may still run it), so it is not knowable.
    assert result.known == {"WS-A": "M"}


# ---------------------------------------------------------------------------
# IMSSegmentAnalyzer
# ---------------------------------------------------------------------------


def test_ims_qualified_move_into_ssa_segment_name_is_tracked():
    ast = _parse(
        _program(
            "       P1.\n"
            "           MOVE 'ORDER   ' TO SEG-NAME OF SSA2\n"
            "           CALL 'CBLTDLI' USING DLI-GU DB-PCB IO-AREA SSA1\n"
            "           CALL 'CBLTDLI' USING DLI-GN DB-PCB IO-AREA SSA2\n"
            "           GOBACK.\n",
            "       01 DLI-GU PIC X(4) VALUE 'GU  '.\n"
            "       01 DLI-GN PIC X(4) VALUE 'GN  '.\n"
            "       01 IO-AREA PIC X(100).\n"
            "       01 DB-PCB PIC X(40).\n"
            "       01 SSA1.\n"
            "          05 SEG-NAME PIC X(8) VALUE 'CUSTOMER'.\n"
            "          05 FILLER PIC X VALUE SPACE.\n"
            "       01 SSA2.\n"
            "          05 SEG-NAME PIC X(8) VALUE 'ADDRESS '.\n"
            "          05 FILLER PIC X VALUE SPACE.\n",
        )
    )
    calls = IMSSegmentAnalyzer().analyze(ast)
    assert [c.segment_names for c in calls] == [["CUSTOMER"], ["ADDRESS/ORDER"]]
