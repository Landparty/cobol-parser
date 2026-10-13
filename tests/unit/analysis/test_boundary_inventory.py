"""Unit tests for BoundaryInventoryAnalyzer (cobolparser.analysis.boundary_inventory).

Covers key/layout/direction resolution per category, nested-body reachability
(the exact holes the 2026-07-09 silent-drop audit found in program_flow), the
CALL argument-direction ladder (by-content rule, callee-source, caller
dataflow, assumed-bidirectional fallback), non-interactive ACCEPT filtering,
and a cross-check against IOLogger's independent file-operations walk.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import (
    BoundaryInventoryAnalyzer,
    _condition_field_names,
    _condition_read_names,
)
from cobolparser.analysis.io_logger import IOLogger
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.base import ArithmeticExpression, FunctionCall
from cobolparser.models.statements.control import EvaluateStatement


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


class TestCallerDataflowReadsInWriteShapedStatements:
    """Issue #268: a CALL argument read after the CALL by ADD / COMPUTE /
    STRING / MULTIPLY / SUBTRACT (a *write-shaped* statement) was graded OUT,
    because only MOVE's ``.source`` counted as a read."""

    HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WSREADS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(4).
       01  WS-B                PIC 9(4).
       01  WS-C                PIC 9(4).
       01  WS-D                PIC X(4).
       01  WS-E                PIC X.
       01  WS-P                PIC 99.
       01  WS-T                PIC 9(4).
       01  WS-OUT              PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""

    def _args(self, body: str) -> dict:
        _, _, report = _analyze(self.HEADER + body, "wsreads.cbl")
        call = next(b for b in report.boundaries if b.ref.category == "CALL")
        return {a.name: a for a in call.call_args}

    def test_issue_268_repro_add_compute_string_read_the_args(self):
        args = self._args("""\
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           MOVE 'X' TO WS-D
           CALL 'SUBA' USING WS-A WS-B WS-D
           ADD WS-A TO WS-T
           COMPUTE WS-T = WS-B * 2
           STRING WS-D DELIMITED BY SIZE INTO WS-OUT.
""")
        for name in ("WS-A", "WS-B", "WS-D"):
            assert args[name].direction == "BIDIRECTIONAL", name
            assert args[name].provenance == "caller-dataflow", name

    def test_to_from_by_into_targets_without_giving_are_read(self):
        args = self._args("""\
           MOVE 1 TO WS-A WS-B WS-C
           CALL 'SUBA' USING WS-A WS-B WS-C
           ADD 1 TO WS-A
           MULTIPLY 3 BY WS-B
           DIVIDE 2 INTO WS-C.
""")
        for name in ("WS-A", "WS-B", "WS-C"):
            assert args[name].direction == "BIDIRECTIONAL", name

    def test_subtract_from_target_without_giving_is_read(self):
        args = self._args("""\
           MOVE 1 TO WS-A
           CALL 'SUBA' USING WS-A
           SUBTRACT 1 FROM WS-A.
""")
        assert args["WS-A"].direction == "BIDIRECTIONAL"

    def test_giving_receiver_is_written_not_read(self):
        # WS-A is only stored into by GIVING after the call -> still OUT.
        args = self._args("""\
           MOVE 1 TO WS-A
           CALL 'SUBA' USING WS-A
           ADD WS-B TO WS-C GIVING WS-A.
""")
        assert args["WS-A"].direction == "OUT"
        assert args["WS-A"].provenance == "caller-dataflow"

    def test_to_operand_with_giving_is_read_not_written(self):
        # ``ADD 1 TO WS-A GIVING WS-T`` reads WS-A and stores only WS-T, so
        # WS-A (written before the call) is BIDIRECTIONAL, not OUT.
        args = self._args("""\
           MOVE 1 TO WS-A
           CALL 'SUBA' USING WS-A
           ADD 1 TO WS-A GIVING WS-T.
""")
        assert args["WS-A"].direction == "BIDIRECTIONAL"
        assert args["WS-A"].provenance == "caller-dataflow"

    def test_unstring_source_and_string_pointer_are_read(self):
        args = self._args("""\
           MOVE 'A,B' TO WS-OUT
           MOVE 1 TO WS-P
           CALL 'SUBA' USING WS-OUT WS-P
           STRING 'Z' DELIMITED BY SIZE INTO WS-D
               WITH POINTER WS-P
           UNSTRING WS-OUT DELIMITED BY ',' INTO WS-D.
""")
        assert args["WS-OUT"].direction == "BIDIRECTIONAL"
        assert args["WS-P"].direction == "BIDIRECTIONAL"

    def test_set_up_by_and_initialize_replacing_read(self):
        args = self._args("""\
           MOVE 1 TO WS-P WS-A
           CALL 'SUBA' USING WS-P WS-A
           SET WS-P UP BY 1
           INITIALIZE WS-T REPLACING NUMERIC DATA BY WS-A.
""")
        assert args["WS-P"].direction == "BIDIRECTIONAL"
        assert args["WS-A"].direction == "BIDIRECTIONAL"

    def test_unknown_write_shaped_type_degrades_to_assumed_bidirectional(self):
        source = self.HEADER + """\
           MOVE 1 TO WS-A
           CALL 'SUBA' USING WS-A
           MOVE WS-A TO WS-T.
"""
        result = parse_cobol(source, filename="wsreads.cbl")
        assert result.ast is not None
        index = ProgramLayoutIndex.build(result.ast)
        statements = list(result.ast.get_all_statements())

        class _OpaqueWrite:
            # A write-shaped type this module has no read list for.
            def __init__(self) -> None:
                self.targets = ["WS-T"]
                self.operands = ["WS-A", "WS-T"]

        statements[-1] = _OpaqueWrite()
        call_pos = next(
            i for i, s in enumerate(statements) if type(s).__name__ == "CallStatement"
        )
        direction, provenance = BoundaryInventoryAnalyzer._caller_dataflow_direction(
            "WS-A", index, statements, call_pos
        )
        assert (direction, provenance) == ("BIDIRECTIONAL", "assumed-bidirectional")


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

    def test_system_accept_with_a_format_qualifier_is_not_a_boundary(self):
        # cobolparser keeps the qualifier in from_source ("DATE YYYYMMDD",
        # "DAY YYYYDDD"); compared whole, the commonest date idiom read as
        # console input, so gen-fixtures generated stdin data for it and
        # mockymock reported a boundary key mismatch.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPTFMT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TODAY            PIC 9(8).
       01  WS-JULIAN           PIC 9(7).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-TODAY FROM DATE YYYYMMDD
           ACCEPT WS-JULIAN FROM DAY YYYYDDD.
"""
        _, _, report = _analyze(source, "acceptfmt.cbl")
        assert [b for b in report.boundaries if b.ref.category == "ACCEPT"] == []
        assert report.unresolved == []


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


class TestConditionFieldNamesExpressionTrees:
    """`_condition_field_names`/`_condition_read_names` against hand-built
    AST nodes exercising the ``str | CobolExpression`` shapes
    ``EvaluateStatement.subjects``/``ConditionalExpression`` operands are
    typed for. The current parser only ever produces bare strings for these
    (arithmetic sub-expressions are flattened to text before they reach the
    condition tree), so this is regression coverage for the documented type
    contract itself -- a future parser change that starts building real
    nested expressions must not silently go unread by the CALL
    argument-direction ladder the way a plain string subject already is.
    """

    def test_evaluate_subject_that_is_an_expression_is_still_read(self):
        loc = SourceLocation(line=1, column=1)
        arithmetic = ArithmeticExpression("+", loc)
        arithmetic.set_left_operand("WS-RC")
        arithmetic.set_right_operand("0")

        stmt = EvaluateStatement(loc)
        stmt.add_subject(arithmetic)

        assert _condition_read_names(stmt) == ["WS-RC", "0"]

    def test_function_call_arguments_are_read(self):
        loc = SourceLocation(line=1, column=1)
        call = FunctionCall("UPPER-CASE", loc)
        call.add_argument("WS-NAME")

        assert _condition_field_names(call) == ["WS-NAME"]

    def test_nested_arithmetic_operand_inside_a_comparison_is_read(self):
        from cobolparser.models.statements.base import ConditionalExpression

        loc = SourceLocation(line=1, column=1)
        arithmetic = ArithmeticExpression("+", loc)
        arithmetic.set_left_operand("WS-A")
        arithmetic.set_right_operand("WS-B")

        comparison = ConditionalExpression("EQUAL", loc)
        comparison.set_left_operand(arithmetic)
        comparison.set_right_operand("WS-C")

        assert _condition_field_names(comparison) == ["WS-A", "WS-B", "WS-C"]


class TestCalleeSourceBindsByProcedureUsing:
    """Rung 2 matched the Nth argument to the callee's Nth LINKAGE 01 in
    declaration order; the formal parameter is the Nth name of its
    PROCEDURE DIVISION USING. With LINKAGE declared A, B, C and USING B C A,
    the argument the callee writes (the third) used to read OUT and the
    first IN."""

    _CALLEE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB1.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-A PIC X(4).
       01 LK-B PIC X(4).
       01 LK-C PIC X(4).
       PROCEDURE DIVISION USING LK-B LK-C LK-A.
           MOVE 'X' TO LK-A.
           GOBACK.
"""
    _CALLER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-1 PIC X(4).
       01 WS-2 PIC X(4).
       01 WS-3 PIC X(4).
       PROCEDURE DIVISION.
       P1.
           CALL 'SUB1' USING WS-1 WS-2 WS-3.
           GOBACK.
"""

    def test_directions_follow_using_order(self):
        callee = parse_cobol(self._CALLEE).ast
        caller = parse_cobol(self._CALLER).ast
        report = BoundaryInventoryAnalyzer().analyze(
            caller,
            ProgramLayoutIndex.build(caller),
            callee_indexes={"SUB1": ProgramLayoutIndex.build(callee)},
            callee_asts={"SUB1": callee},
        )
        (boundary,) = report.boundaries
        assert [(a.name, a.direction, a.provenance) for a in boundary.call_args] == [
            ("WS-1", "OUT", "callee-source"),
            ("WS-2", "OUT", "callee-source"),
            ("WS-3", "IN", "callee-source"),
        ]


class TestMultiLineExecKeys:
    """Two multi-line EXEC sites whose text agrees up to a line break must
    still get distinct keys: the uniqueness check compared the
    whitespace-collapsed key against the other sites' RAW text, so a
    prefix spanning a line break never matched and both sites were cut
    to the same key (CICSONLN's two SEND MAPs, differing only in
    ERASE/DATAONLY on their third line)."""

    def test_cics_sites_differing_after_a_line_break_get_distinct_keys(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSKEYS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAP-AREA         PIC X(100).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS SEND MAP('CINQMAP') MAPSET('CINQSET')
               FROM(WS-MAP-AREA)
               ERASE
           END-EXEC
           EXEC CICS SEND MAP('CINQMAP') MAPSET('CINQSET')
               FROM(WS-MAP-AREA)
               DATAONLY
           END-EXEC
           GOBACK.
"""
        _, _, report = _analyze(source, "cicskeys.cbl")
        keys = [b.ref.key for b in report.boundaries if b.ref.category == "CICS"]
        assert len(keys) == 2
        assert len(set(keys)) == 2, f"CICS keys must be unique: {keys}"
        assert keys[0].endswith("ERASE")
        assert keys[1].endswith("DATAONLY")

    def test_sql_sites_differing_after_a_line_break_get_distinct_keys(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLKEYS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-ID               PIC X(8).
       01  WS-NAME             PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               UPDATE CUSTOMER
               SET NAME = :WS-NAME
               WHERE ID = :WS-ID
           END-EXEC
           EXEC SQL
               UPDATE CUSTOMER
               SET STATUS = 'X'
               WHERE ID = :WS-ID
           END-EXEC
           GOBACK.
"""
        _, _, report = _analyze(source, "sqlkeys.cbl")
        keys = [b.ref.key for b in report.boundaries if b.ref.category == "SQL"]
        assert len(keys) == 2
        assert len(set(keys)) == 2, f"SQL keys must be unique: {keys}"


class TestDynamicCallSentinelCandidates:
    def test_only_figurative_candidates_are_unresolved(self):
        _, _, report = _analyze(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DISPATCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-PGM PIC X(8).\n"
            "       01 WS-ARG PIC X(4).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           MOVE SPACES TO WS-PGM.\n"
            "           CALL WS-PGM USING WS-ARG.\n"
            "           STOP RUN.\n"
        )
        assert any(
            "dynamic CALL WS-PGM: no possible target values resolved" in note
            for note in report.unresolved
        )
