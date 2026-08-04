"""Unit tests for BoundaryInventoryAnalyzer (cobolparser.analysis.boundary_inventory).

Covers key/layout/direction resolution per category, nested-body reachability
(the exact holes the 2026-07-09 silent-drop audit found in program_flow), the
CALL argument-direction ladder (by-content rule, callee-source, caller
dataflow, assumed-bidirectional fallback), non-interactive ACCEPT filtering,
and a cross-check against IOLogger's independent file-operations walk.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.io_logger import IOLogger
from cobolparser.generators import ProgramLayoutIndex


def _analyze(source: str, filename: str = "t.cbl"):
    result = parse_cobol(source, filename=filename)
    assert result.ast is not None, result.errors
    assert result.errors == []
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return result.ast, index, report


class TestFileOps:
    def test_read_write_open_close_over_file_operations_sample(self):
        _, _, report = _analyze(
            open("tests/samples/file_operations.cbl").read(),
            "file_operations.cbl",
        )
        categories = {b.ref.category for b in report.boundaries}
        assert categories >= {
            "OPEN",
            "CLOSE",
            "READ",
            "WRITE",
            "REWRITE",
            "START",
            "DELETE",
        }
        # OPT-FILE's SELECT has no matching FD in this fixture -- a known,
        # pre-existing gap surfaced by ProgramLayoutIndex itself (Phase 1)
        # and merged into this report; not a Phase 2 resolution failure.
        assert report.unresolved == [
            "file 'OPT-FILE' has a SELECT but no matching FD/SD record"
        ]

        reads = [b for b in report.boundaries if b.ref.category == "READ"]
        assert all(b.direction == "IN" for b in reads)
        assert all(b.status_field for b in reads)

        writes = [b for b in report.boundaries if b.ref.category == "WRITE"]
        assert all(b.direction == "OUT" for b in writes)
        assert all(b.record_names for b in writes)

        opens = [b for b in report.boundaries if b.ref.category == "OPEN"]
        assert all(b.direction == "STATUS_ONLY" for b in opens)

    def test_write_and_rewrite_key_on_the_record_not_the_fd(self):
        # WRITE/REWRITE syntax names the *record*; the key must reflect that
        # (this is exactly the record_named() gap found during development).
        _, _, report = _analyze(
            open("tests/samples/file_operations.cbl").read(),
            "file_operations.cbl",
        )
        rewrite = next(b for b in report.boundaries if b.ref.category == "REWRITE")
        assert rewrite.ref.key == "IDX-RECORD"
        assert rewrite.record_names == ["IDX-RECORD"]

    def test_at_end_and_invalid_key_handlers_detected(self):
        _, _, report = _analyze(
            open("tests/samples/file_operations.cbl").read(),
            "file_operations.cbl",
        )
        reads = [b for b in report.boundaries if b.ref.category == "READ"]
        assert any("AT_END" in b.handlers for b in reads)
        assert any("INVALID_KEY" in b.handlers for b in reads)


class TestNestedReachability:
    """A boundary hidden inside IF/EVALUATE/SEARCH bodies must not be missed
    -- the exact holes the 2026-07-09 silent-drop audit found elsewhere."""

    def test_read_inside_if_branch(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTIF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC              PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = 'Y'
               READ F1
           ELSE
               DISPLAY 'NO'
           END-IF.
"""
        _, _, report = _analyze(source, "nestif.cbl")
        reads = [b for b in report.boundaries if b.ref.category == "READ"]
        assert len(reads) == 1
        assert reads[0].ref.key == "F1"

    def test_call_inside_evaluate_when(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE             PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-CODE
               WHEN 1
                   CALL 'PGMA'
               WHEN OTHER
                   CALL 'PGMB'
           END-EVALUATE.
"""
        _, _, report = _analyze(source, "nesteval.cbl")
        calls = {b.ref.key for b in report.boundaries if b.ref.category == "CALL"}
        assert calls == {"PGMA", "PGMB"}

    def test_read_inside_search_when(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTSEARCH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC              PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-TABLE.
           05  WS-ITEM OCCURS 3 TIMES PIC X(5).
       01  WS-IDX               PIC 9 USAGE INDEX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ITEM
               AT END DISPLAY 'NOT FOUND'
               WHEN WS-ITEM (WS-IDX) = 'X'
                   READ F1
           END-SEARCH.
"""
        _, _, report = _analyze(source, "nestsearch.cbl")
        reads = [b for b in report.boundaries if b.ref.category == "READ"]
        assert len(reads) == 1


class TestCallArgumentDirectionLadder:
    def test_by_content_and_by_value_are_always_out(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONTENTMODE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(5).
       01  WS-B                PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUB' USING BY CONTENT WS-A BY VALUE WS-B.
"""
        _, _, report = _analyze(source, "contentmode.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        by_name = {a.name: a for a in call.call_args}
        assert by_name["WS-A"].direction == "OUT"
        assert by_name["WS-A"].provenance == "by-content-rule"
        assert by_name["WS-B"].direction == "OUT"
        assert by_name["WS-B"].provenance == "by-content-rule"

    def test_by_content_scopes_to_its_own_phrase_only(self):
        # BY CONTENT applies to every argument up to the next BY-phrase --
        # a bare comma does not reset it, but a new BY REFERENCE does.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONTENTSCOPE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(5).
       01  WS-B                PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUB' USING BY CONTENT WS-A BY REFERENCE WS-B.
"""
        _, _, report = _analyze(source, "contentscope.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        by_name = {a.name: a for a in call.call_args}
        assert by_name["WS-A"].passing_mode == "CONTENT"
        assert by_name["WS-B"].passing_mode == "REFERENCE"

    def test_caller_dataflow_out_in_and_bidirectional(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAFLOW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-OUT-ARG          PIC 9(5).
       01  WS-IN-ARG           PIC 9(5).
       01  WS-BOTH-ARG         PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 5 TO WS-OUT-ARG
           MOVE 1 TO WS-BOTH-ARG
           CALL 'SUB' USING WS-OUT-ARG WS-IN-ARG WS-BOTH-ARG
           DISPLAY WS-IN-ARG
           DISPLAY WS-BOTH-ARG.
"""
        _, _, report = _analyze(source, "dataflow.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        by_name = {a.name: a for a in call.call_args}
        assert by_name["WS-OUT-ARG"].direction == "OUT"
        assert by_name["WS-OUT-ARG"].provenance == "caller-dataflow"
        assert by_name["WS-IN-ARG"].direction == "IN"
        assert by_name["WS-BOTH-ARG"].direction == "BIDIRECTIONAL"

    def test_no_surrounding_dataflow_falls_back_to_assumed_bidirectional(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NODATAFLOW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ARG              PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUB' USING WS-ARG.
"""
        _, _, report = _analyze(source, "nodataflow.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        arg = call.call_args[0]
        assert arg.direction == "BIDIRECTIONAL"
        assert arg.provenance == "assumed-bidirectional"

    def test_callee_source_rung_uses_arithmetic_writes_not_just_move(self):
        # subprogram_demo.cbl's CALCULATOR computes its result via COMPUTE,
        # not MOVE -- the write-detection must generalize beyond MOVE.
        result = parse_cobol("tests/samples/subprogram_demo.cbl")
        assert result.ast is not None
        caller = result.ast
        calculator = caller.contained_programs[0]
        assert calculator.program_name == "CALCULATOR"
        caller_index = ProgramLayoutIndex.build(caller)
        calc_index = ProgramLayoutIndex.build(calculator)

        report = BoundaryInventoryAnalyzer().analyze(
            caller,
            caller_index,
            callee_indexes={"CALCULATOR": calc_index},
            callee_asts={"CALCULATOR": calculator},
        )
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        by_name = {a.name: a for a in call.call_args}
        # LK-RESULT (5th LINKAGE item, position 3) is written via
        # COMPUTE LK-RESULT = ... in every EVALUATE arm -> IN.
        assert by_name["WS-RESULT"].direction == "IN"
        assert by_name["WS-RESULT"].provenance == "callee-source"
        # LK-NUM1/LK-NUM2/LK-OPERATION are only ever read by CALCULATOR -> OUT.
        assert by_name["WS-INPUT-NUM1"].direction == "OUT"

    def test_giving_and_returning_parameters_are_always_in(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GIVINGCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUB' GIVING WS-RESULT.
"""
        _, _, report = _analyze(source, "givingcall.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        assert any(
            a.name == "WS-RESULT"
            and a.direction == "IN"
            and a.provenance == "giving-parameter"
            for a in call.call_args
        )


class TestDynamicCall:
    def test_dynamic_call_keys_on_uppercased_identifier(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNCALLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ws-dynprog          PIC X(8) VALUE 'SUBPROG'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL ws-dynprog.
"""
        _, _, report = _analyze(source, "dyncalltest.cbl")
        dyncall = next(b for b in report.boundaries if b.ref.category == "DYNCALL")
        assert dyncall.ref.key == "WS-DYNPROG"


class TestSql:
    def test_select_is_in_insert_is_out(self):
        result = parse_cobol("tests/samples/ibm_extensions.cbl")
        assert result.ast is not None
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        sql_boundaries = [b for b in report.boundaries if b.ref.category == "SQL"]
        assert sql_boundaries
        assert any(b.direction == "IN" for b in sql_boundaries)
        assert any(b.direction == "OUT" for b in sql_boundaries)
        assert all(b.status_field == "SQLCODE" for b in sql_boundaries)

    def test_sql_keys_are_unique_shortest_prefixes(self):
        result = parse_cobol("tests/samples/ibm_extensions.cbl")
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        keys = [b.ref.key for b in report.boundaries if b.ref.category == "SQL"]
        assert len(keys) == len(set(keys)), f"SQL keys must be unique: {keys}"


class TestAccept:
    def test_console_accept_is_a_boundary(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPTTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REPLY            PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-REPLY.
"""
        _, _, report = _analyze(source, "accepttest.cbl")
        accepts = [b for b in report.boundaries if b.ref.category == "ACCEPT"]
        assert len(accepts) == 1
        assert accepts[0].direction == "IN"
        assert accepts[0].record_names == ["WS-REPLY"]

    def test_non_interactive_accept_is_not_a_boundary(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPTDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TODAY            PIC 9(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-TODAY FROM DATE.
"""
        _, _, report = _analyze(source, "acceptdate.cbl")
        assert [b for b in report.boundaries if b.ref.category == "ACCEPT"] == []


class TestDisplayIsNotABoundary:
    def test_display_produces_no_boundary(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISPLAYTEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HELLO'.
"""
        _, _, report = _analyze(source, "displaytest.cbl")
        assert report.boundaries == []


class TestIOLoggerCrossCheck:
    """Two independent walks over the same sample must agree on the set of
    file operations -- IOLogger (pre-existing) and BoundaryInventoryAnalyzer
    (this phase)."""

    def test_file_operation_counts_agree_with_io_logger(self):
        source = open("tests/samples/file_operations.cbl").read()
        result = parse_cobol(source, filename="file_operations.cbl")
        assert result.ast is not None
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)

        io_report = IOLogger().analyze(result.ast)
        # IOLogger's `.operation` is mode-qualified for OPEN ("OPEN INPUT",
        # "OPEN OUTPUT", "OPEN I-O"); take the base verb for comparison.
        io_ops = {op.operation.split()[0] for op in io_report.file_operations}
        boundary_categories = {
            b.ref.category
            for b in report.boundaries
            if b.ref.category
            in (
                "READ",
                "WRITE",
                "REWRITE",
                "OPEN",
                "CLOSE",
                "DELETE",
                "START",
                "UNLOCK",
            )
        }
        # Every file-op category IOLogger saw, this inventory saw too.
        assert io_ops <= boundary_categories


class TestLayoutIndexUnresolvedPropagation:
    """ProgramLayoutIndex.unresolved (Phase 1 gaps -- an unownable FILE
    SECTION record, a SELECT with no matching FD/SD) must ride along on the
    BoundaryReport, not be silently lost between phases."""

    def test_index_unresolved_is_merged_into_the_report(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GHOSTFILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GHOST-FILE ASSIGN TO 'GHOST.DAT'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DUMMY            PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""
        result = parse_cobol(source, filename="ghostfile.cbl")
        assert result.ast is not None
        index = ProgramLayoutIndex.build(result.ast)
        assert index.unresolved  # sanity: the index itself found the gap

        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        assert report.unresolved == index.unresolved
