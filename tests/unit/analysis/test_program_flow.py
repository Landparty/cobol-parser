"""Tests for program flow analysis."""

import pytest

from cobolparser.analysis.program_flow import (
    FlowEdge,
    FlowEdgeType,
    FlowNode,
    ProgramFlowAnalyzer,
    ProgramFlowReport,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.base import CobolExpression
from cobolparser.models.statements.call import CallStatement, EntryStatement
from cobolparser.models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    StopStatement,
    WhenClause,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    ContinueStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    SortStatement,
)
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOC = SourceLocation(1, 12)


def _make_program(
    paragraphs: list[tuple[str, list]],
    sections: list[tuple[str, list[tuple[str, list]]]] | None = None,
) -> CobolProgram:
    loc = SourceLocation(1, 1)
    prog = CobolProgram("TEST-PROG", loc)

    id_div = CobolDivision("IDENTIFICATION", loc)
    prog.add_division(id_div)

    proc_div = CobolDivision("PROCEDURE", loc)
    prog.add_division(proc_div)

    line = 10
    if sections:
        for sec_name, sec_paras in sections:
            sec = CobolSection(sec_name, SourceLocation(line, 8))
            line += 1
            for pname, stmts in sec_paras:
                para = CobolParagraph(pname, SourceLocation(line, 8))
                for s in stmts:
                    para.add_statement(s)
                sec.add_paragraph(para)
                line += 1
            proc_div.add_section(sec)
    else:
        for pname, stmts in paragraphs:
            para = CobolParagraph(pname, SourceLocation(line, 8))
            for s in stmts:
                para.add_statement(s)
            proc_div.add_paragraph(para)
            line += 1

    return prog


def _perform(target: str, thru: str | None = None) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    if thru:
        stmt.set_thru_paragraph(thru)
    return stmt


def _perform_until(target: str) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    expr = CobolExpression("COMPARISON", LOC)
    stmt.set_until_clause(expr)
    return stmt


def _perform_times(target: str, times: int) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    stmt.set_times_clause(times)
    return stmt


def _goto(target: str) -> GoStatement:
    stmt = GoStatement(LOC)
    stmt.set_target_paragraph(target)
    return stmt


def _goto_depending(targets: list[str], var: str) -> GoStatement:
    stmt = GoStatement(LOC)
    if targets:
        stmt.set_target_paragraph(targets[0])
    for t in targets[1:]:
        stmt.add_operand(t)
    stmt.set_depending_on_variable(var)
    return stmt


def _call(program: str, is_dynamic: bool = False) -> CallStatement:
    stmt = CallStatement(LOC)
    stmt.set_called_program(program, is_dynamic)
    return stmt


def _entry(name: str) -> EntryStatement:
    stmt = EntryStatement(LOC)
    stmt.set_entry_name(name)
    return stmt


def _stop_run() -> StopStatement:
    stmt = StopStatement(LOC)
    stmt.stop_type = "RUN"
    return stmt


def _goback() -> GobackStatement:
    return GobackStatement(LOC)


def _exit_program() -> ExitStatement:
    stmt = ExitStatement(LOC)
    stmt.set_exit_type("PROGRAM")
    return stmt


def _if_stmt(then_stmts: list, else_stmts: list | None = None) -> IfStatement:
    stmt = IfStatement(LOC)
    cond = CobolExpression("COMPARISON", LOC)
    stmt.set_condition(cond)
    for s in then_stmts:
        stmt.add_then_statement(s)
    for s in else_stmts or []:
        stmt.add_else_statement(s)
    return stmt


def _evaluate(when_count: int = 1) -> EvaluateStatement:
    stmt = EvaluateStatement(LOC)
    stmt.add_subject("WS-VAR")
    for _ in range(when_count):
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc.add_statement(ContinueStatement(LOC))
        stmt.add_when_clause(wc)
    return stmt


def _sort_with_procedures(
    input_proc: str | None = None,
    output_proc: str | None = None,
) -> SortStatement:
    stmt = SortStatement(LOC)
    stmt.set_file_name("SORT-FILE")
    if input_proc:
        stmt.set_input_procedure(input_proc)
    if output_proc:
        stmt.set_output_procedure(output_proc)
    return stmt


def _merge_with_procedure(output_proc: str) -> MergeStatement:
    stmt = MergeStatement(LOC)
    stmt.set_file_name("MERGE-FILE")
    stmt.set_output_procedure(output_proc)
    return stmt


def _alter(from_para: str, to_para: str) -> AlterStatement:
    stmt = AlterStatement(LOC)
    stmt.add_alteration(from_para, to_para)
    return stmt


def _continue() -> ContinueStatement:
    return ContinueStatement(LOC)


# ---------------------------------------------------------------------------
# Tests: ProgramFlowAnalyzer - basic structure
# ---------------------------------------------------------------------------


class TestProgramFlowAnalyzerBasic:
    """Basic tests for node and edge collection."""

    def test_no_procedure_division(self) -> None:
        """Program without PROCEDURE DIVISION returns empty report."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.node_count == 0
        assert report.edge_count == 0
        assert report.program_name == "EMPTY"

    def test_empty_procedure_division(self) -> None:
        """Empty PROCEDURE DIVISION returns empty report."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY", loc)
        proc_div = CobolDivision("PROCEDURE", loc)
        prog.add_division(proc_div)

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.node_count == 0

    def test_single_paragraph(self) -> None:
        """Single paragraph becomes one node, marked as entry point."""
        prog = _make_program([("MAIN-LOGIC", [_continue()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.node_count == 1
        assert report.nodes[0].name == "MAIN-LOGIC"
        assert report.nodes[0].is_entry_point
        assert report.entry_points == ["MAIN-LOGIC"]

    def test_multiple_paragraphs_collected(self) -> None:
        """All paragraphs are collected as nodes."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue()]),
                ("PROCESS", [_continue()]),
                ("CLEANUP", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.node_count == 3
        names = [n.name for n in report.nodes]
        assert names == ["MAIN-LOGIC", "PROCESS", "CLEANUP"]

    def test_sections_and_paragraphs(self) -> None:
        """Sections and their paragraphs are collected."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("MAIN-SECTION", [("MAIN-PARA", [_continue()])]),
                ("UTIL-SECTION", [("UTIL-PARA", [_continue()])]),
            ],
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        names = [n.name for n in report.nodes]
        assert "MAIN-SECTION" in names
        assert "MAIN-PARA" in names
        assert "UTIL-SECTION" in names
        assert "UTIL-PARA" in names

    def test_statement_count(self) -> None:
        """Statement count is tracked per node."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue(), _continue(), _continue()]),
                ("OTHER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        main_node = report.nodes[0]
        assert main_node.statement_count == 3
        other_node = report.nodes[1]
        assert other_node.statement_count == 1


# ---------------------------------------------------------------------------
# Tests: PERFORM edges
# ---------------------------------------------------------------------------


class TestProgramFlowPerform:
    """Tests for PERFORM statement edge generation."""

    def test_simple_perform(self) -> None:
        """PERFORM creates a PERFORM edge."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("PROCESS")]),
                ("PROCESS", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert len(perform_edges) == 1
        assert perform_edges[0].source == "MAIN-LOGIC"
        assert perform_edges[0].target == "PROCESS"
        assert not perform_edges[0].is_loop

    def test_perform_thru(self) -> None:
        """PERFORM THRU creates both PERFORM and PERFORM_THRU edges."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("STEP-A", thru="STEP-C")]),
                ("STEP-A", [_continue()]),
                ("STEP-B", [_continue()]),
                ("STEP-C", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        types = {e.edge_type for e in report.edges if e.source == "MAIN-LOGIC"}
        assert FlowEdgeType.PERFORM in types
        assert FlowEdgeType.PERFORM_THRU in types

    def test_perform_until_is_loop(self) -> None:
        """PERFORM UNTIL creates a loop edge."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform_until("READ-LOOP")]),
                ("READ-LOOP", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert len(perform_edges) == 1
        assert perform_edges[0].is_loop
        assert perform_edges[0].perform_type == "UNTIL"

    def test_perform_times_is_loop(self) -> None:
        """PERFORM TIMES creates a loop edge."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform_times("WORK", 5)]),
                ("WORK", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert len(perform_edges) == 1
        assert perform_edges[0].is_loop
        assert perform_edges[0].perform_type == "TIMES"

    def test_perform_count_metric(self) -> None:
        """PERFORM statements are counted in node metrics."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("A"), _perform("B")]),
                ("A", [_continue()]),
                ("B", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].perform_count == 2


# ---------------------------------------------------------------------------
# Tests: GO TO edges
# ---------------------------------------------------------------------------


class TestProgramFlowGoTo:
    """Tests for GO TO statement edge generation."""

    def test_simple_goto(self) -> None:
        """GO TO creates a GOTO edge."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_goto("ERROR-HANDLER")]),
                ("ERROR-HANDLER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        goto_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.GOTO]
        assert len(goto_edges) == 1
        assert goto_edges[0].source == "MAIN-LOGIC"
        assert goto_edges[0].target == "ERROR-HANDLER"

    def test_goto_depending(self) -> None:
        """GO TO DEPENDING creates GOTO_DEPENDING edges for each target."""
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_goto_depending(["STEP-1", "STEP-2", "STEP-3"], "WS-IDX")],
                ),
                ("STEP-1", [_continue()]),
                ("STEP-2", [_continue()]),
                ("STEP-3", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        dep_edges = [
            e for e in report.edges if e.edge_type == FlowEdgeType.GOTO_DEPENDING
        ]
        targets = {e.target for e in dep_edges}
        assert targets == {"STEP-1", "STEP-2", "STEP-3"}
        assert all("DEPENDING ON WS-IDX" in (e.condition or "") for e in dep_edges)

    def test_goto_count_metric(self) -> None:
        """GO TO statements are counted in node metrics."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_goto("NEXT")]),
                ("NEXT", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].goto_count == 1


# ---------------------------------------------------------------------------
# Tests: CALL edges and external calls
# ---------------------------------------------------------------------------


class TestProgramFlowCall:
    """Tests for CALL statement edge generation and external call tracking."""

    def test_static_call(self) -> None:
        """Static CALL creates a CALL edge and records external call."""
        prog = _make_program([("MAIN-LOGIC", [_call("'SUBPROG'")])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        call_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.CALL]
        assert len(call_edges) == 1
        assert call_edges[0].target == "SUBPROG"

        assert len(report.external_calls) == 1
        assert report.external_calls[0]["program"] == "SUBPROG"
        assert not report.external_calls[0]["is_dynamic"]

    def test_dynamic_call(self) -> None:
        """Dynamic CALL creates a CALL_DYNAMIC edge."""
        prog = _make_program([("MAIN-LOGIC", [_call("WS-PROG-NAME", is_dynamic=True)])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        dynamic_edges = [
            e for e in report.edges if e.edge_type == FlowEdgeType.CALL_DYNAMIC
        ]
        assert len(dynamic_edges) == 1
        assert report.external_calls[0]["is_dynamic"]

    def test_call_count_metric(self) -> None:
        """CALL statements are counted in node metrics."""
        prog = _make_program([("MAIN-LOGIC", [_call("'A'"), _call("'B'")])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].call_count == 2


# ---------------------------------------------------------------------------
# Tests: Exit points
# ---------------------------------------------------------------------------


class TestProgramFlowExitPoints:
    """Tests for exit point detection."""

    def test_stop_run_marks_exit(self) -> None:
        """STOP RUN marks the paragraph as an exit point."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_stop_run
        assert report.nodes[0].is_exit_point
        assert "MAIN-LOGIC" in report.exit_points

    def test_goback_marks_exit(self) -> None:
        """GOBACK marks the paragraph as an exit point."""
        prog = _make_program([("MAIN-LOGIC", [_goback()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_goback
        assert report.nodes[0].is_exit_point

    def test_exit_program_marks_exit(self) -> None:
        """EXIT PROGRAM marks the paragraph as an exit point."""
        prog = _make_program([("MAIN-LOGIC", [_exit_program()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_exit_program
        assert report.nodes[0].is_exit_point

    def test_multiple_exit_points(self) -> None:
        """Multiple paragraphs with terminators are all reported."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("WORK"), _stop_run()]),
                ("WORK", [_continue()]),
                ("ERROR-EXIT", [_goback()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert set(report.exit_points) == {"MAIN-LOGIC", "ERROR-EXIT"}


# ---------------------------------------------------------------------------
# Tests: Entry points (ENTRY statement)
# ---------------------------------------------------------------------------


class TestProgramFlowEntryPoints:
    """Tests for entry point detection including ENTRY statements."""

    def test_first_paragraph_is_entry(self) -> None:
        """The first procedure is always the primary entry point."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue()]),
                ("OTHER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.entry_points[0] == "MAIN-LOGIC"

    def test_entry_statement_adds_entry_point(self) -> None:
        """ENTRY statements register additional entry points."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_entry("'ALTENTRY'")]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert "ALTENTRY" in report.entry_points


# ---------------------------------------------------------------------------
# Tests: Branching metrics (IF, EVALUATE)
# ---------------------------------------------------------------------------


class TestProgramFlowBranching:
    """Tests for branching statement metrics."""

    def test_if_count(self) -> None:
        """IF statements are counted in node metrics."""
        prog = _make_program(
            [("MAIN-LOGIC", [_if_stmt([_continue()]), _if_stmt([_continue()])])]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].if_count == 2

    def test_evaluate_count(self) -> None:
        """EVALUATE statements are counted in node metrics."""
        prog = _make_program([("MAIN-LOGIC", [_evaluate(when_count=3)])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].evaluate_count == 1

    def test_nested_perform_in_if(self) -> None:
        """PERFORM inside IF branches still generates edges."""
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_if_stmt([_perform("A")], [_perform("B")])],
                ),
                ("A", [_continue()]),
                ("B", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_targets = {
            e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM
        }
        assert perform_targets == {"A", "B"}


# ---------------------------------------------------------------------------
# Tests: SORT/MERGE procedure edges
# ---------------------------------------------------------------------------


class TestProgramFlowSortMerge:
    """Tests for SORT/MERGE procedure edge generation."""

    def test_sort_input_output_procedures(self) -> None:
        """SORT INPUT/OUTPUT PROCEDURE creates edges."""
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_sort_with_procedures("IN-PROC", "OUT-PROC")],
                ),
                ("IN-PROC", [_continue()]),
                ("OUT-PROC", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        edge_types = {
            (e.edge_type, e.target) for e in report.edges if e.source == "MAIN-LOGIC"
        }
        assert (FlowEdgeType.SORT_INPUT_PROCEDURE, "IN-PROC") in edge_types
        assert (FlowEdgeType.SORT_OUTPUT_PROCEDURE, "OUT-PROC") in edge_types

    def test_merge_output_procedure(self) -> None:
        """MERGE OUTPUT PROCEDURE creates an edge."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_merge_with_procedure("MERGE-OUT")]),
                ("MERGE-OUT", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        merge_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.MERGE_OUTPUT_PROCEDURE
        ]
        assert len(merge_edges) == 1
        assert merge_edges[0].target == "MERGE-OUT"


# ---------------------------------------------------------------------------
# Tests: ALTER edges
# ---------------------------------------------------------------------------


class TestProgramFlowAlter:
    """Tests for ALTER statement edge generation."""

    def test_alter_creates_edge(self) -> None:
        """ALTER creates an ALTER edge from source to target."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_alter("SWITCH", "NEW-TARGET")]),
                ("SWITCH", [_continue()]),
                ("NEW-TARGET", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        alter_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.ALTER]
        assert len(alter_edges) == 1
        assert alter_edges[0].source == "SWITCH"
        assert alter_edges[0].target == "NEW-TARGET"


# ---------------------------------------------------------------------------
# Tests: Fall-through edges
# ---------------------------------------------------------------------------


class TestProgramFlowFallThrough:
    """Tests for implicit fall-through edge generation."""

    def test_fall_through_between_paragraphs(self) -> None:
        """Sequential paragraphs get fall-through edges."""
        prog = _make_program(
            [
                ("PARA-A", [_continue()]),
                ("PARA-B", [_continue()]),
                ("PARA-C", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        pairs = [(e.source, e.target) for e in ft_edges]
        assert ("PARA-A", "PARA-B") in pairs
        assert ("PARA-B", "PARA-C") in pairs

    def test_no_fall_through_after_stop_run(self) -> None:
        """STOP RUN prevents fall-through to next paragraph."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
                ("UNREACHABLE", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        assert len(ft_edges) == 0

    def test_no_fall_through_after_goback(self) -> None:
        """GOBACK prevents fall-through to next paragraph."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_goback()]),
                ("NEXT", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        assert len(ft_edges) == 0


# ---------------------------------------------------------------------------
# Tests: Report serialization
# ---------------------------------------------------------------------------


class TestProgramFlowReport:
    """Tests for the ProgramFlowReport data class."""

    def test_to_dict_structure(self) -> None:
        """to_dict() produces the expected JSON structure."""
        report = ProgramFlowReport(program_name="TEST")
        report.nodes = [
            FlowNode("MAIN", "PARAGRAPH", SourceLocation(10, 8), is_entry_point=True)
        ]
        report.edges = [
            FlowEdge(
                "MAIN",
                "SUB",
                FlowEdgeType.PERFORM,
                SourceLocation(11, 12),
            )
        ]
        report.entry_points = ["MAIN"]
        report.exit_points = []
        report.external_calls = []

        d = report.to_dict()

        assert d["program_name"] == "TEST"
        assert len(d["nodes"]) == 1
        assert d["nodes"][0]["name"] == "MAIN"
        assert d["nodes"][0]["is_entry_point"] is True
        assert len(d["edges"]) == 1
        assert d["edges"][0]["type"] == "PERFORM"
        assert d["summary"]["node_count"] == 1
        assert d["summary"]["edge_count"] == 1

    def test_empty_report(self) -> None:
        """Empty report has correct defaults."""
        report = ProgramFlowReport()
        assert report.node_count == 0
        assert report.edge_count == 0

    def test_flow_node_to_dict(self) -> None:
        """FlowNode.to_dict() includes branching and call metrics."""
        node = FlowNode(
            "MAIN",
            "PARAGRAPH",
            SourceLocation(10, 8),
            if_count=2,
            evaluate_count=1,
            perform_count=3,
        )
        d = node.to_dict()
        assert d["branching"]["if_count"] == 2
        assert d["branching"]["evaluate_count"] == 1
        assert d["calls"]["perform_count"] == 3

    def test_flow_edge_to_dict_with_loop(self) -> None:
        """FlowEdge.to_dict() includes loop info when present."""
        edge = FlowEdge(
            "A",
            "B",
            FlowEdgeType.PERFORM,
            SourceLocation(1, 1),
            is_loop=True,
            perform_type="UNTIL",
        )
        d = edge.to_dict()
        assert d["is_loop"] is True
        assert d["perform_type"] == "UNTIL"


# ---------------------------------------------------------------------------
# Tests: Integration with real COBOL parsing
# ---------------------------------------------------------------------------


class TestProgramFlowIntegration:
    """Integration tests using parse_cobol to build the AST."""

    def test_basic_program_flow(self) -> None:
        """Parse a real COBOL program and analyze its flow."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOWTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-DATA
           PERFORM PROCESS-DATA
           STOP RUN.
       INIT-DATA.
           DISPLAY "INIT".
       PROCESS-DATA.
           DISPLAY "PROCESS".
"""
        result = parse_cobol(source, filename="flowtest.cbl")
        assert result.ast is not None

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        assert report.program_name == "FLOWTEST"
        node_names = [n.name for n in report.nodes]
        assert "MAIN-LOGIC" in node_names
        assert "INIT-DATA" in node_names
        assert "PROCESS-DATA" in node_names

        perform_targets = {
            e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM
        }
        assert "INIT-DATA" in perform_targets
        assert "PROCESS-DATA" in perform_targets

        assert "MAIN-LOGIC" in report.exit_points

    def test_goto_flow(self) -> None:
        """GO TO statements are tracked in parsed COBOL."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-FLAG = 1
               GO TO ERROR-EXIT
           END-IF
           STOP RUN.
       ERROR-EXIT.
           DISPLAY "ERROR"
           STOP RUN.
"""
        result = parse_cobol(source, filename="gototest.cbl")
        assert result.ast is not None

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        goto_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.GOTO]
        assert any(e.target == "ERROR-EXIT" for e in goto_edges)

    def test_call_flow(self) -> None:
        """CALL statements are tracked in parsed COBOL."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'SUBPROG' USING WS-PARAM
           STOP RUN.
"""
        result = parse_cobol(source, filename="calltest.cbl")
        assert result.ast is not None

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        assert len(report.external_calls) >= 1
        assert any(c["program"] == "SUBPROG" for c in report.external_calls)

    def test_perform_until_loop(self) -> None:
        """PERFORM UNTIL is detected as a loop in parsed COBOL."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM READ-FILE UNTIL WS-EOF = 'Y'
           STOP RUN.
       READ-FILE.
           DISPLAY "READING".
"""
        result = parse_cobol(source, filename="looptest.cbl")
        assert result.ast is not None

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        loop_edges = [
            e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM and e.is_loop
        ]
        assert len(loop_edges) >= 1

    def test_complex_program_flow(self) -> None:
        """Complex program with multiple flow constructs."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPLEX.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PARA
           PERFORM PROCESS-PARA
           PERFORM CLEANUP-PARA
           STOP RUN.
       INIT-PARA.
           DISPLAY "INIT".
       PROCESS-PARA.
           IF WS-FLAG = 1
               PERFORM SPECIAL-LOGIC
           END-IF
           DISPLAY "PROCESS".
       SPECIAL-LOGIC.
           DISPLAY "SPECIAL".
       CLEANUP-PARA.
           DISPLAY "CLEANUP"
           GOBACK.
"""
        result = parse_cobol(source, filename="complex.cbl")
        assert result.ast is not None

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)

        assert report.node_count >= 4
        assert report.edge_count >= 3
        assert len(report.entry_points) >= 1
        assert len(report.exit_points) >= 1

        # Verify the report serializes cleanly
        d = report.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "summary" in d


# ---------------------------------------------------------------------------
# Tests: Public API imports
# ---------------------------------------------------------------------------


class TestProgramFlowPublicAPI:
    """Tests for public API availability."""

    def test_import_from_analysis(self) -> None:
        """Classes are importable from cobolparser.analysis."""
        from cobolparser.analysis import (  # noqa: F401
            FlowEdge,
            FlowEdgeType,
            FlowNode,
            ProgramFlowAnalyzer,
            ProgramFlowReport,
        )

    def test_import_from_top_level(self) -> None:
        """Classes are importable from cobolparser."""
        from cobolparser import (  # noqa: F401
            FlowEdge,
            FlowEdgeType,
            FlowNode,
            ProgramFlowAnalyzer,
            ProgramFlowReport,
        )


# ---------------------------------------------------------------------------
# Tests: Full output validation — verifying the flow display is correct
# ---------------------------------------------------------------------------


class TestProgramFlowOutputDisplay:
    """End-to-end tests that verify the JSON output properly represents
    program flow.  Each test parses real COBOL, runs the analyzer, converts
    the report to a dict (the same dict the CLI serialises as JSON), and
    checks the complete structure for correctness."""

    # -- helper ---------------------------------------------------------------

    @staticmethod
    def _analyze(source: str) -> dict:
        """Parse COBOL source and return the flow report dict."""
        result = parse_cobol(source, filename="<test>")
        assert result.ast is not None, f"Parse failed: {result.errors}"
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)
        return report.to_dict()

    # -- top-level structure --------------------------------------------------

    def test_output_has_required_top_level_keys(self) -> None:
        """Output dict must contain all top-level keys."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TOPKEYS.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        d = self._analyze(source)

        required_keys = {
            "program_name",
            "nodes",
            "edges",
            "entry_points",
            "exit_points",
            "external_calls",
            "summary",
        }
        assert required_keys.issubset(d.keys())

    def test_output_summary_matches_lists(self) -> None:
        """Summary counts must agree with the actual lists."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUMTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK-PARA
           STOP RUN.
       WORK-PARA.
           DISPLAY "WORKING".
"""
        d = self._analyze(source)

        assert d["summary"]["node_count"] == len(d["nodes"])
        assert d["summary"]["edge_count"] == len(d["edges"])
        assert d["summary"]["entry_point_count"] == len(d["entry_points"])
        assert d["summary"]["exit_point_count"] == len(d["exit_points"])
        assert d["summary"]["external_call_count"] == len(d["external_calls"])

    def test_program_name_in_output(self) -> None:
        """Output contains the correct PROGRAM-ID."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MY-APP.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        d = self._analyze(source)
        assert d["program_name"] == "MY-APP"

    # -- node output ----------------------------------------------------------

    def test_node_output_has_required_fields(self) -> None:
        """Each node in the output must have name, type, location,
        statement_count, branching, and calls."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NODEFIELDS.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "HELLO"
           STOP RUN.
"""
        d = self._analyze(source)
        node = d["nodes"][0]

        assert "name" in node
        assert "type" in node
        assert "location" in node
        assert "statement_count" in node
        assert "branching" in node
        assert "calls" in node
        # location must be a dict with line
        assert "line" in node["location"]

    def test_node_branching_metrics_correct(self) -> None:
        """IF and EVALUATE counts in output match the source code."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRANCHOUT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-X = 1
               DISPLAY "ONE"
           END-IF
           IF WS-X = 2
               DISPLAY "TWO"
           END-IF
           EVALUATE WS-X
               WHEN 1 DISPLAY "A"
               WHEN 2 DISPLAY "B"
               WHEN OTHER DISPLAY "C"
           END-EVALUATE
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]

        assert main["branching"]["if_count"] == 2
        assert main["branching"]["evaluate_count"] == 1

    def test_node_call_metrics_correct(self) -> None:
        """PERFORM, GOTO, and CALL counts in output match the source."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLMETRIC.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK-A
           PERFORM WORK-B
           PERFORM WORK-C
           CALL 'EXTPROG'
           GO TO DONE.
       WORK-A.
           DISPLAY "A".
       WORK-B.
           DISPLAY "B".
       WORK-C.
           DISPLAY "C".
       DONE.
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]

        assert main["calls"]["perform_count"] == 3
        assert main["calls"]["call_count"] == 1
        assert main["calls"]["goto_count"] == 1

    def test_entry_point_flagged_on_first_node(self) -> None:
        """The first paragraph should have is_entry_point = True."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYPT.
       PROCEDURE DIVISION.
       FIRST-PARA.
           DISPLAY "FIRST".
       SECOND-PARA.
           DISPLAY "SECOND".
"""
        d = self._analyze(source)

        first_node = d["nodes"][0]
        assert first_node["name"] == "FIRST-PARA"
        assert first_node.get("is_entry_point") is True

        # Second node should NOT have is_entry_point
        second_node = d["nodes"][1]
        assert "is_entry_point" not in second_node or not second_node["is_entry_point"]

    def test_exit_point_flagged_on_stop_run_node(self) -> None:
        """Paragraphs with STOP RUN should have is_exit_point = True."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITPT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK
           STOP RUN.
       WORK.
           DISPLAY "WORK".
"""
        d = self._analyze(source)

        main = next(n for n in d["nodes"] if n["name"] == "MAIN-LOGIC")
        work = next(n for n in d["nodes"] if n["name"] == "WORK")

        assert main.get("is_exit_point") is True
        assert main.get("has_stop_run") is True
        assert "is_exit_point" not in work or not work["is_exit_point"]

    # -- edge output ----------------------------------------------------------

    def test_perform_edges_show_source_and_target(self) -> None:
        """PERFORM edges must identify correct source and target paragraphs."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFEDGE.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-DATA
           PERFORM PROCESS
           PERFORM CLEANUP
           STOP RUN.
       INIT-DATA.
           DISPLAY "INIT".
       PROCESS.
           DISPLAY "PROC".
       CLEANUP.
           DISPLAY "CLEAN".
"""
        d = self._analyze(source)

        perform_edges = [e for e in d["edges"] if e["type"] == "PERFORM"]
        edge_pairs = {(e["source"], e["target"]) for e in perform_edges}

        assert ("MAIN-LOGIC", "INIT-DATA") in edge_pairs
        assert ("MAIN-LOGIC", "PROCESS") in edge_pairs
        assert ("MAIN-LOGIC", "CLEANUP") in edge_pairs

    def test_perform_edge_shows_perform_type(self) -> None:
        """PERFORM edges include perform_type field."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFTYPE.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK-PARA
           PERFORM WORK-PARA 3 TIMES
           STOP RUN.
       WORK-PARA.
           DISPLAY "W".
"""
        d = self._analyze(source)

        perform_edges = [e for e in d["edges"] if e["type"] == "PERFORM"]
        types = [e.get("perform_type") for e in perform_edges]

        assert "SIMPLE" in types
        assert "TIMES" in types

    def test_loop_edges_flagged_in_output(self) -> None:
        """PERFORM UNTIL/TIMES/VARYING edges have is_loop = True."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPOUT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM READ-LOOP UNTIL WS-FLAG = 'Y'
           STOP RUN.
       READ-LOOP.
           DISPLAY "READING".
"""
        d = self._analyze(source)

        loop_edges = [
            e for e in d["edges"] if e["type"] == "PERFORM" and e.get("is_loop")
        ]
        assert len(loop_edges) >= 1
        assert loop_edges[0]["target"] == "READ-LOOP"
        assert loop_edges[0]["perform_type"] == "UNTIL"

    def test_goto_edge_in_output(self) -> None:
        """GO TO edges show correct source and target."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOOUT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           GO TO THE-END.
       THE-END.
           STOP RUN.
"""
        d = self._analyze(source)

        goto_edges = [e for e in d["edges"] if e["type"] == "GOTO"]
        assert len(goto_edges) == 1
        assert goto_edges[0]["source"] == "MAIN-LOGIC"
        assert goto_edges[0]["target"] == "THE-END"

    def test_goto_depending_edges_in_output(self) -> None:
        """GO TO DEPENDING produces GOTO_DEPENDING edges (unit-level with
        manually constructed AST, since the parser simplifies this syntax)."""
        prog = _make_program(
            [
                (
                    "MAIN-LOGIC",
                    [_goto_depending(["STEP-1", "STEP-2", "STEP-3"], "WS-IDX")],
                ),
                ("STEP-1", [_continue()]),
                ("STEP-2", [_continue()]),
                ("STEP-3", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        dep_edges = [e for e in d["edges"] if e["type"] == "GOTO_DEPENDING"]
        dep_targets = {e["target"] for e in dep_edges}

        assert "STEP-1" in dep_targets
        assert "STEP-2" in dep_targets
        assert "STEP-3" in dep_targets
        # Each edge should carry the condition
        for edge in dep_edges:
            assert "condition" in edge
            assert "DEPENDING ON" in edge["condition"]

    def test_call_edge_in_output(self) -> None:
        """CALL edges show source paragraph and target program."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLOUT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'BILLING'
           CALL 'REPORTING'
           STOP RUN.
"""
        d = self._analyze(source)

        call_edges = [e for e in d["edges"] if e["type"] == "CALL"]
        targets = {e["target"] for e in call_edges}

        assert "BILLING" in targets
        assert "REPORTING" in targets
        assert all(e["source"] == "MAIN-LOGIC" for e in call_edges)

    def test_dynamic_call_edge_type_in_output(self) -> None:
        """Dynamic CALL edges use type CALL_DYNAMIC."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE 'SUBPGM01'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL WS-PGM
           STOP RUN.
"""
        d = self._analyze(source)

        dynamic_edges = [e for e in d["edges"] if e["type"] == "CALL_DYNAMIC"]
        assert len(dynamic_edges) >= 1

    def test_fall_through_edges_in_output(self) -> None:
        """Sequential paragraphs without terminators produce FALL_THROUGH edges."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLTHRU.
       PROCEDURE DIVISION.
       PARA-A.
           DISPLAY "A".
       PARA-B.
           DISPLAY "B".
       PARA-C.
           DISPLAY "C"
           STOP RUN.
"""
        d = self._analyze(source)

        ft_edges = [e for e in d["edges"] if e["type"] == "FALL_THROUGH"]
        ft_pairs = [(e["source"], e["target"]) for e in ft_edges]

        assert ("PARA-A", "PARA-B") in ft_pairs
        assert ("PARA-B", "PARA-C") in ft_pairs

    def test_no_fall_through_after_terminator(self) -> None:
        """No FALL_THROUGH edge after a paragraph that ends with STOP RUN."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
       UNREACHABLE.
           DISPLAY "NEVER".
"""
        d = self._analyze(source)

        ft_from_main = [
            e
            for e in d["edges"]
            if e["type"] == "FALL_THROUGH" and e["source"] == "MAIN-LOGIC"
        ]
        assert len(ft_from_main) == 0

    def test_perform_thru_edges_in_output(self) -> None:
        """PERFORM THRU produces both PERFORM and PERFORM_THRU edges."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUOUT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM STEP-A THRU STEP-C
           STOP RUN.
       STEP-A.
           DISPLAY "A".
       STEP-B.
           DISPLAY "B".
       STEP-C.
           DISPLAY "C".
"""
        d = self._analyze(source)

        edge_types_from_main = {
            e["type"] for e in d["edges"] if e["source"] == "MAIN-LOGIC"
        }
        assert "PERFORM" in edge_types_from_main
        assert "PERFORM_THRU" in edge_types_from_main

        perf_edge = next(
            e
            for e in d["edges"]
            if e["source"] == "MAIN-LOGIC" and e["type"] == "PERFORM"
        )
        thru_edge = next(
            e
            for e in d["edges"]
            if e["source"] == "MAIN-LOGIC" and e["type"] == "PERFORM_THRU"
        )
        assert perf_edge["target"] == "STEP-A"
        assert thru_edge["target"] == "STEP-C"

    # -- external calls -------------------------------------------------------

    def test_external_calls_in_output(self) -> None:
        """External calls list has program name, dynamic flag, and caller."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTCALLS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE 'DYNPGM'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'STATIC-PGM'
           CALL WS-PGM
           STOP RUN.
"""
        d = self._analyze(source)

        assert len(d["external_calls"]) >= 2

        static_call = next(
            (c for c in d["external_calls"] if c["program"] == "STATIC-PGM"), None
        )
        assert static_call is not None
        assert static_call["is_dynamic"] is False
        assert static_call["called_from"] == "MAIN-LOGIC"
        assert "location" in static_call

        dynamic_call = next((c for c in d["external_calls"] if c["is_dynamic"]), None)
        assert dynamic_call is not None

    # -- entry / exit points lists -------------------------------------------

    def test_entry_points_list_in_output(self) -> None:
        """entry_points list includes the first paragraph."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYLIST.
       PROCEDURE DIVISION.
       PROGRAM-START.
           PERFORM DO-WORK
           STOP RUN.
       DO-WORK.
           DISPLAY "WORK".
"""
        d = self._analyze(source)

        assert "PROGRAM-START" in d["entry_points"]

    def test_exit_points_list_in_output(self) -> None:
        """exit_points list includes all paragraphs with terminators."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITLIST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK-A
           STOP RUN.
       WORK-A.
           DISPLAY "A".
       ERROR-EXIT.
           DISPLAY "ERR"
           GOBACK.
"""
        d = self._analyze(source)

        assert "MAIN-LOGIC" in d["exit_points"]
        assert "ERROR-EXIT" in d["exit_points"]
        assert "WORK-A" not in d["exit_points"]

    # -- complete flow for a realistic program --------------------------------

    def test_full_program_flow_output(self) -> None:
        """End-to-end: a realistic program's flow output shows correct
        overall structure — all paragraph nodes, PERFORM edges from main,
        conditional branching, CALL to external, GOBACK exit, and summary."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORDER-TYPE   PIC X VALUE 'N'.
       01 WS-STATUS        PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PROCESSING
           PERFORM VALIDATE-ORDER
           PERFORM PROCESS-ORDER
           PERFORM FINALIZE
           STOP RUN.
       INIT-PROCESSING.
           DISPLAY "INITIALIZING".
       VALIDATE-ORDER.
           IF WS-STATUS = 0
               DISPLAY "VALID"
           ELSE
               GO TO ERROR-HANDLER
           END-IF.
       PROCESS-ORDER.
           EVALUATE WS-ORDER-TYPE
               WHEN 'N' DISPLAY "NEW ORDER"
               WHEN 'R' DISPLAY "RETURN"
               WHEN OTHER DISPLAY "UNKNOWN"
           END-EVALUATE
           CALL 'ORDERSVC'.
       ERROR-HANDLER.
           DISPLAY "ERROR OCCURRED"
           GOBACK.
       FINALIZE.
           DISPLAY "DONE".
"""
        d = self._analyze(source)

        # -- program name --
        assert d["program_name"] == "ORDERPROC"

        # -- all paragraphs present --
        node_names = [n["name"] for n in d["nodes"]]
        for expected in [
            "MAIN-LOGIC",
            "INIT-PROCESSING",
            "VALIDATE-ORDER",
            "PROCESS-ORDER",
            "ERROR-HANDLER",
            "FINALIZE",
        ]:
            assert expected in node_names, f"{expected} missing from nodes"

        # -- entry point --
        assert d["entry_points"][0] == "MAIN-LOGIC"
        main_node = next(n for n in d["nodes"] if n["name"] == "MAIN-LOGIC")
        assert main_node.get("is_entry_point") is True

        # -- exit points --
        assert "MAIN-LOGIC" in d["exit_points"]  # STOP RUN
        assert "ERROR-HANDLER" in d["exit_points"]  # GOBACK

        # -- PERFORM edges from MAIN-LOGIC --
        perform_targets = {
            e["target"]
            for e in d["edges"]
            if e["source"] == "MAIN-LOGIC" and e["type"] == "PERFORM"
        }
        assert perform_targets == {
            "INIT-PROCESSING",
            "VALIDATE-ORDER",
            "PROCESS-ORDER",
            "FINALIZE",
        }

        # -- GOTO edge from VALIDATE-ORDER --
        goto_edges = [
            e
            for e in d["edges"]
            if e["type"] == "GOTO" and e["source"] == "VALIDATE-ORDER"
        ]
        assert len(goto_edges) == 1
        assert goto_edges[0]["target"] == "ERROR-HANDLER"

        # -- CALL edge from PROCESS-ORDER --
        call_edges = [
            e
            for e in d["edges"]
            if e["type"] == "CALL" and e["source"] == "PROCESS-ORDER"
        ]
        assert len(call_edges) == 1
        assert call_edges[0]["target"] == "ORDERSVC"

        # -- external calls list --
        assert len(d["external_calls"]) >= 1
        assert d["external_calls"][0]["program"] == "ORDERSVC"

        # -- branching metrics --
        validate = next(n for n in d["nodes"] if n["name"] == "VALIDATE-ORDER")
        assert validate["branching"]["if_count"] >= 1

        process = next(n for n in d["nodes"] if n["name"] == "PROCESS-ORDER")
        assert process["branching"]["evaluate_count"] >= 1

        error = next(n for n in d["nodes"] if n["name"] == "ERROR-HANDLER")
        assert error.get("is_exit_point") is True
        assert error.get("has_goback") is True

        # -- summary counts match --
        assert d["summary"]["node_count"] == len(d["nodes"])
        assert d["summary"]["edge_count"] == len(d["edges"])

    # -- sample file test using control_flow.cbl ------------------------------

    def test_control_flow_sample_output(self) -> None:
        """Analyze the control_flow.cbl sample file and verify key flow
        relationships are properly represented in the output."""
        import pathlib

        sample = (
            pathlib.Path(__file__).parent.parent.parent / "samples" / "control_flow.cbl"
        )
        if not sample.exists():
            pytest.skip(f"Sample file not found: {sample}")

        source = sample.read_text(encoding="utf-8")
        d = self._analyze(source)

        assert d["program_name"] == "CTRLFLOW"

        node_names = {n["name"] for n in d["nodes"]}
        # Key paragraphs must appear
        for name in [
            "MAIN-LOGIC",
            "IF-TESTS",
            "EVALUATE-TESTS",
            "PERFORM-TESTS",
            "GOTO-TESTS",
            "SEARCH-TESTS",
            "SIMPLE-PARA",
        ]:
            assert name in node_names, f"{name} missing from output nodes"

        # MAIN-LOGIC performs each test section
        main_performs = {
            e["target"]
            for e in d["edges"]
            if e["source"] == "MAIN-LOGIC" and e["type"] == "PERFORM"
        }
        assert "IF-TESTS" in main_performs
        assert "EVALUATE-TESTS" in main_performs
        assert "PERFORM-TESTS" in main_performs
        assert "GOTO-TESTS" in main_performs
        assert "SEARCH-TESTS" in main_performs

        # MAIN-LOGIC is entry and exit
        assert "MAIN-LOGIC" in d["entry_points"]
        assert "MAIN-LOGIC" in d["exit_points"]

        # IF-TESTS has multiple IF statements
        if_node = next(n for n in d["nodes"] if n["name"] == "IF-TESTS")
        assert if_node["branching"]["if_count"] > 0

        # EVALUATE-TESTS has EVALUATE statements
        eval_node = next(n for n in d["nodes"] if n["name"] == "EVALUATE-TESTS")
        assert eval_node["branching"]["evaluate_count"] > 0

        # PERFORM-TESTS performs SIMPLE-PARA
        perf_performs = {
            e["target"]
            for e in d["edges"]
            if e["source"] == "PERFORM-TESTS" and e["type"] == "PERFORM"
        }
        assert "SIMPLE-PARA" in perf_performs

        # GOTO-TESTS has GO TO edges
        goto_edges = [
            e for e in d["edges"] if e["type"] == "GOTO" and e["source"] == "GOTO-TESTS"
        ]
        assert len(goto_edges) >= 1

        # Summary is consistent
        assert d["summary"]["node_count"] == len(d["nodes"])
        assert d["summary"]["edge_count"] == len(d["edges"])

    # -- CLI output test using subprocess -------------------------------------

    def test_cli_program_flow_json_output(self) -> None:
        """The program-flow CLI subcommand produces valid JSON with
        the expected top-level structure."""
        import json
        import subprocess
        import sys
        import tempfile

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLITEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK-PARA
           STOP RUN.
       WORK-PARA.
           DISPLAY "WORK".
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as tmp:
            tmp.write(source)
            tmp.flush()
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from cobolparser.cli.parse import main; main()",
                    "program-flow",
                    tmp.name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        stdout = proc.stdout.strip()
        assert stdout, f"CLI produced no output; stderr: {proc.stderr}"

        d = json.loads(stdout)

        assert d["program_name"] == "CLITEST"
        assert len(d["nodes"]) >= 2
        assert len(d["edges"]) >= 1
        assert "summary" in d

    def test_cli_compact_output(self) -> None:
        """--compact flag produces single-line JSON."""
        import json
        import subprocess
        import sys
        import tempfile

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPACT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as tmp:
            tmp.write(source)
            tmp.flush()
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from cobolparser.cli.parse import main; main()",
                    "program-flow",
                    "--compact",
                    tmp.name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        stdout = proc.stdout.strip()
        assert stdout, f"CLI produced no output; stderr: {proc.stderr}"

        # Compact JSON is a single line
        lines = [line for line in stdout.splitlines() if line.strip()]
        assert len(lines) == 1

        d = json.loads(stdout)
        assert d["program_name"] == "COMPACT"


# ---------------------------------------------------------------------------
# Tests: Statement types and decisions in output
# ---------------------------------------------------------------------------


class TestProgramFlowStatementsAndDecisions:
    """Tests verifying that all statement types and decision points
    are properly represented in the flow output."""

    @staticmethod
    def _analyze(source: str) -> dict:
        result = parse_cobol(source, filename="<test>")
        assert result.ast is not None, f"Parse failed: {result.errors}"
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(result.ast)
        return report.to_dict()

    # -- statement_types field ------------------------------------------------

    def test_statement_types_present_in_output(self) -> None:
        """Every node in the output includes a statement_types dict."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STYPES.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "HELLO"
           STOP RUN.
"""
        d = self._analyze(source)
        assert "statement_types" in d["nodes"][0]
        assert isinstance(d["nodes"][0]["statement_types"], dict)

    def test_statement_types_counts_display(self) -> None:
        """DISPLAY statements are counted in statement_types."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISPCNT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "FIRST"
           DISPLAY "SECOND"
           DISPLAY "THIRD"
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]

        assert main["statement_types"].get("DISPLAY") == 3
        assert main["statement_types"].get("STOP") == 1

    def test_statement_types_counts_perform(self) -> None:
        """PERFORM statements are counted in statement_types."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFCNT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM WORK
           PERFORM WORK
           STOP RUN.
       WORK.
           DISPLAY "W".
"""
        d = self._analyze(source)
        main = d["nodes"][0]

        assert main["statement_types"].get("PERFORM") == 2

    def test_statement_types_multiple_verb_types(self) -> None:
        """Multiple different verb types are all tracked."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIVERB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       01 WS-Y PIC 9 VALUE 2.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "HI"
           MOVE 1 TO WS-X
           ADD 1 TO WS-Y
           PERFORM WORK
           CALL 'EXTERN'
           STOP RUN.
       WORK.
           DISPLAY "W".
"""
        d = self._analyze(source)
        main = d["nodes"][0]
        stypes = main["statement_types"]

        assert "DISPLAY" in stypes
        assert "MOVE" in stypes
        assert "ADD" in stypes
        assert "PERFORM" in stypes
        assert "CALL" in stypes
        assert "STOP" in stypes

    def test_statement_types_nested_in_if(self) -> None:
        """Statements nested inside IF blocks are still counted."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTIF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-X = 1
               DISPLAY "YES"
               MOVE 2 TO WS-X
           ELSE
               DISPLAY "NO"
           END-IF
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]
        stypes = main["statement_types"]

        # IF itself + DISPLAY x2 + MOVE + STOP
        assert stypes.get("IF") == 1
        assert stypes.get("DISPLAY") == 2
        assert stypes.get("MOVE") == 1

    def test_statement_types_nested_in_evaluate(self) -> None:
        """Statements nested inside EVALUATE WHEN clauses are counted."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-X
               WHEN 1 DISPLAY "ONE"
               WHEN 2 DISPLAY "TWO"
               WHEN OTHER DISPLAY "OTHER"
           END-EVALUATE
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]
        stypes = main["statement_types"]

        assert stypes.get("EVALUATE") == 1
        assert stypes.get("DISPLAY") == 3

    # -- decisions field ------------------------------------------------------

    def test_decisions_present_in_output(self) -> None:
        """Every node includes a decisions list."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECPRES.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        d = self._analyze(source)
        assert "decisions" in d["nodes"][0]
        assert isinstance(d["nodes"][0]["decisions"], list)

    def test_if_decision_recorded(self) -> None:
        """IF statements produce decision entries with type, has_else, location."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFDEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-X = 1
               DISPLAY "YES"
           END-IF
           STOP RUN.
"""
        d = self._analyze(source)
        main = d["nodes"][0]
        decisions = main["decisions"]

        if_decisions = [dec for dec in decisions if dec["type"] == "IF"]
        assert len(if_decisions) == 1
        assert if_decisions[0]["has_else"] is False
        assert "location" in if_decisions[0]

    def test_if_else_decision_records_has_else(self) -> None:
        """IF-ELSE decisions have has_else = True."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFELSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-X = 1
               DISPLAY "YES"
           ELSE
               DISPLAY "NO"
           END-IF
           STOP RUN.
"""
        d = self._analyze(source)
        decisions = d["nodes"][0]["decisions"]
        if_dec = next(dec for dec in decisions if dec["type"] == "IF")
        assert if_dec["has_else"] is True

    def test_evaluate_decision_recorded(self) -> None:
        """EVALUATE statements produce decision entries with subjects and
        when_count."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALDEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-X
               WHEN 1 DISPLAY "ONE"
               WHEN 2 DISPLAY "TWO"
               WHEN OTHER DISPLAY "DEFAULT"
           END-EVALUATE
           STOP RUN.
"""
        d = self._analyze(source)
        decisions = d["nodes"][0]["decisions"]

        eval_decisions = [dec for dec in decisions if dec["type"] == "EVALUATE"]
        assert len(eval_decisions) == 1
        assert eval_decisions[0]["when_count"] == 2  # excludes WHEN OTHER
        assert eval_decisions[0]["has_default"] is True
        assert "subjects" in eval_decisions[0]
        assert "location" in eval_decisions[0]

    def test_evaluate_no_default(self) -> None:
        """EVALUATE without WHEN OTHER has has_default = False."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALNODEF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-X
               WHEN 1 DISPLAY "ONE"
           END-EVALUATE
           STOP RUN.
"""
        d = self._analyze(source)
        decisions = d["nodes"][0]["decisions"]
        eval_dec = next(dec for dec in decisions if dec["type"] == "EVALUATE")
        assert eval_dec["has_default"] is False

    def test_multiple_decisions_per_paragraph(self) -> None:
        """Multiple IF/EVALUATE in one paragraph produce multiple decisions."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIDEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 1.
       01 WS-B PIC X VALUE 'X'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-A = 1
               DISPLAY "A IS 1"
           END-IF
           EVALUATE WS-B
               WHEN 'X' DISPLAY "IS X"
               WHEN 'Y' DISPLAY "IS Y"
           END-EVALUATE
           IF WS-A = 2
               DISPLAY "A IS 2"
           ELSE
               DISPLAY "A IS NOT 2"
           END-IF
           STOP RUN.
"""
        d = self._analyze(source)
        decisions = d["nodes"][0]["decisions"]

        assert len(decisions) == 3
        types = [dec["type"] for dec in decisions]
        assert types.count("IF") == 2
        assert types.count("EVALUATE") == 1

    def test_decisions_empty_when_no_branching(self) -> None:
        """Paragraphs with no branching have an empty decisions list."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOBRANCH.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "HELLO"
           STOP RUN.
"""
        d = self._analyze(source)
        assert d["nodes"][0]["decisions"] == []

    # -- combined statement_types and decisions in full flow -------------------

    def test_full_flow_with_statements_and_decisions(self) -> None:
        """Realistic program: each paragraph's statement_types and decisions
        are correctly populated in the output."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FULLFLOW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC 9 VALUE 0.
       01 WS-TYPE   PIC X VALUE 'A'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM VALIDATE-INPUT
           PERFORM PROCESS-DATA
           STOP RUN.
       VALIDATE-INPUT.
           IF WS-STATUS = 0
               DISPLAY "VALID"
           ELSE
               DISPLAY "INVALID"
               GO TO ERROR-EXIT
           END-IF.
       PROCESS-DATA.
           EVALUATE WS-TYPE
               WHEN 'A' DISPLAY "TYPE A"
               WHEN 'B' DISPLAY "TYPE B"
               WHEN OTHER DISPLAY "UNKNOWN"
           END-EVALUATE
           MOVE 1 TO WS-STATUS
           CALL 'PROCESS-SVC'.
       ERROR-EXIT.
           DISPLAY "ERROR"
           GOBACK.
"""
        d = self._analyze(source)

        # -- MAIN-LOGIC: 2 PERFORMs + STOP --
        main = next(n for n in d["nodes"] if n["name"] == "MAIN-LOGIC")
        assert main["statement_types"].get("PERFORM") == 2
        assert main["statement_types"].get("STOP") == 1
        assert main["decisions"] == []  # no branching in main

        # -- VALIDATE-INPUT: IF with ELSE, nested DISPLAY + GOTO --
        validate = next(n for n in d["nodes"] if n["name"] == "VALIDATE-INPUT")
        assert "IF" in validate["statement_types"]
        assert validate["statement_types"].get("DISPLAY") == 2
        assert validate["statement_types"].get("GOTO") == 1
        assert len(validate["decisions"]) == 1
        assert validate["decisions"][0]["type"] == "IF"
        assert validate["decisions"][0]["has_else"] is True

        # -- PROCESS-DATA: EVALUATE + MOVE + CALL --
        process = next(n for n in d["nodes"] if n["name"] == "PROCESS-DATA")
        assert "EVALUATE" in process["statement_types"]
        assert process["statement_types"].get("DISPLAY") == 3  # inside WHEN clauses
        assert process["statement_types"].get("MOVE") == 1
        assert process["statement_types"].get("CALL") == 1
        assert len(process["decisions"]) == 1
        assert process["decisions"][0]["type"] == "EVALUATE"
        assert process["decisions"][0]["when_count"] == 2
        assert process["decisions"][0]["has_default"] is True

        # -- ERROR-EXIT: DISPLAY + GOBACK, no decisions --
        error = next(n for n in d["nodes"] if n["name"] == "ERROR-EXIT")
        assert error["statement_types"].get("DISPLAY") == 1
        assert error["statement_types"].get("GOBACK") == 1
        assert error["decisions"] == []


# ---------------------------------------------------------------------------
# Tests: Edge cases and coverage gaps
# ---------------------------------------------------------------------------


class TestProgramFlowEdgeCases:
    """Tests covering edge cases, defensive guards, and uncovered branches."""

    # -- has_exit_program in to_dict output -----------------------------------

    def test_exit_program_in_to_dict(self) -> None:
        """FlowNode.to_dict() includes has_exit_program when set."""
        node = FlowNode(
            "EXIT-PARA",
            "PARAGRAPH",
            SourceLocation(10, 8),
            has_exit_program=True,
        )
        d = node.to_dict()
        assert d.get("has_exit_program") is True

    def test_exit_program_absent_when_false(self) -> None:
        """FlowNode.to_dict() omits has_exit_program when False."""
        node = FlowNode("NORMAL", "PARAGRAPH", SourceLocation(10, 8))
        d = node.to_dict()
        assert "has_exit_program" not in d

    # -- period-only paragraph name filtered ----------------------------------

    def test_period_paragraph_filtered(self) -> None:
        """Synthetic period-only paragraph names are excluded from nodes."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_continue()]),
                (".", [_continue()]),  # synthetic period paragraph
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        names = [n.name for n in report.nodes]
        assert "." not in names
        assert "MAIN-LOGIC" in names

    # -- case insensitive matching -------------------------------------------

    def test_case_insensitive_paragraph_names(self) -> None:
        """Paragraph names are uppercased for consistent matching."""
        prog = _make_program(
            [
                ("main-logic", [_perform("helper-para")]),
                ("helper-para", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        names = [n.name for n in report.nodes]
        assert "MAIN-LOGIC" in names
        assert "HELPER-PARA" in names

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert perform_edges[0].target == "HELPER-PARA"

    # -- empty CALL program name guard ----------------------------------------

    def test_empty_call_program_name_ignored(self) -> None:
        """CALL with empty-quote program name produces no edges."""
        stmt = CallStatement(LOC)
        stmt.set_called_program("''", is_dynamic=False)

        prog = _make_program([("MAIN-LOGIC", [stmt, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        call_edges = [
            e
            for e in report.edges
            if e.edge_type in (FlowEdgeType.CALL, FlowEdgeType.CALL_DYNAMIC)
        ]
        assert len(call_edges) == 0
        assert len(report.external_calls) == 0

    # -- dynamic call with possible_values ------------------------------------

    def test_dynamic_call_possible_values_in_output(self) -> None:
        """Dynamic CALL with possible_values includes them in external_calls."""
        stmt = CallStatement(LOC)
        stmt.set_called_program("WS-PGM", is_dynamic=True)
        stmt.set_possible_values(["PROG-A", "PROG-B"])

        prog = _make_program([("MAIN-LOGIC", [stmt, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.external_calls) == 1
        ext = report.external_calls[0]
        assert ext["is_dynamic"] is True
        assert set(ext["possible_values"]) == {"PROG-A", "PROG-B"}

    # -- whitespace entry name filtered (bug fix) ----------------------------

    def test_whitespace_entry_name_filtered(self) -> None:
        """ENTRY statements with whitespace-only names are excluded."""
        entry = EntryStatement(LOC)
        entry.set_entry_name("\n")  # whitespace-only

        prog = _make_program([("MAIN-LOGIC", [entry, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert all(ep.strip() for ep in report.entry_points)
        assert "\n" not in report.entry_points

    def test_empty_entry_name_filtered(self) -> None:
        """ENTRY statements with empty string names are excluded."""
        entry = EntryStatement(LOC)
        entry.set_entry_name("''")  # empty after quote strip

        prog = _make_program([("MAIN-LOGIC", [entry, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # Only the first procedure entry point should exist
        for ep in report.entry_points:
            assert ep.strip()  # no empty entry points

    # -- duplicate paragraph name (top-level already in section) ---------------

    def test_duplicate_paragraph_name_not_doubled(self) -> None:
        """A paragraph that exists in a section is not duplicated as top-level."""
        prog = _make_program(
            paragraphs=[],
            sections=[
                ("SEC-A", [("PARA-1", [_continue()])]),
            ],
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        names = [n.name for n in report.nodes]
        assert names.count("PARA-1") == 1

    # -- inline PERFORM with statements inside --------------------------------

    def test_inline_perform_statements_counted(self) -> None:
        """Statements inside inline PERFORM blocks are counted."""
        perf = PerformStatement(LOC)
        # inline PERFORM (no target paragraph)
        inner_display = ContinueStatement(LOC)
        inner_display2 = ContinueStatement(LOC)
        perf.add_inline_statement(inner_display)
        perf.add_inline_statement(inner_display2)

        prog = _make_program([("MAIN-LOGIC", [perf, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        main = report.nodes[0]
        # PERFORM itself + 2 inline + STOP = 4 statements
        assert main.statement_count == 4

    # -- PERFORM VARYING is detected as loop ----------------------------------

    def test_perform_varying_is_loop(self) -> None:
        """PERFORM VARYING creates a loop edge."""
        from cobolparser.models.statements.base import CobolExpression

        stmt = PerformStatement(LOC)
        stmt.set_target_paragraph("LOOP-PARA")
        cond = CobolExpression("COMPARISON", LOC)
        stmt.set_varying_clause("WS-I", "1", "1", cond)

        prog = _make_program(
            [
                ("MAIN-LOGIC", [stmt, _stop_run()]),
                ("LOOP-PARA", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert len(perform_edges) == 1
        assert perform_edges[0].is_loop is True
        assert perform_edges[0].perform_type == "VARYING"

    # -- EXIT with non-PROGRAM type (SECTION, PARAGRAPH) ----------------------

    def test_exit_section_not_marked_as_exit_point(self) -> None:
        """EXIT SECTION does not mark the paragraph as a program exit point."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("SECTION")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert not report.nodes[0].is_exit_point
        assert not report.nodes[0].has_exit_program

    # -- no fall-through after EXIT PROGRAM -----------------------------------

    def test_no_fall_through_after_exit_program(self) -> None:
        """EXIT PROGRAM prevents fall-through to next paragraph."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_exit_program()]),
                ("NEXT-PARA", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        assert len(ft_edges) == 0

    # -- analyzer reuse (calling analyze twice) --------------------------------

    def test_analyzer_reuse_resets_state(self) -> None:
        """Calling analyze() a second time resets all state."""
        prog1 = _make_program(
            [
                ("PROG1-MAIN", [_perform("PROG1-WORK"), _stop_run()]),
                ("PROG1-WORK", [_continue()]),
            ]
        )
        prog2 = _make_program(
            [
                ("PROG2-MAIN", [_stop_run()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report1 = analyzer.analyze(prog1)
        report2 = analyzer.analyze(prog2)

        assert report1.node_count == 2
        assert report2.node_count == 1
        # Ensure no state leakage from first analysis
        names2 = [n.name for n in report2.nodes]
        assert "PROG1-MAIN" not in names2
        assert "PROG2-MAIN" in names2

    # -- single paragraph (last paragraph has no fall-through) ----------------

    def test_single_paragraph_no_fall_through(self) -> None:
        """A single paragraph produces no fall-through edges."""
        prog = _make_program([("ONLY-PARA", [_stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        assert len(ft_edges) == 0

    # -- SEARCH decision with at_end_clause -----------------------------------

    def test_search_decision_with_at_end(self) -> None:
        """SEARCH with AT END produces a decision with has_at_end=True."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        search.add_when_clause("WS-TABLE(IDX) = TARGET", [_continue()])
        search.set_at_end_clause([_continue()])

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        decisions = report.nodes[0].decisions
        search_decs = [d for d in decisions if d["type"] == "SEARCH"]
        assert len(search_decs) == 1
        assert search_decs[0]["has_at_end"] is True
        assert search_decs[0]["table_name"] == "WS-TABLE"
        assert search_decs[0]["when_count"] == 1

    def test_search_decision_without_at_end(self) -> None:
        """SEARCH without AT END has has_at_end=False."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        search.add_when_clause("condition", [_continue()])

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        search_decs = [d for d in report.nodes[0].decisions if d["type"] == "SEARCH"]
        assert len(search_decs) == 1
        assert search_decs[0]["has_at_end"] is False

    # -- IF without condition (defensive) ------------------------------------

    def test_if_without_condition(self) -> None:
        """IF statement with no condition set still records a decision."""
        if_stmt = IfStatement(LOC)
        if_stmt.add_then_statement(_continue())

        prog = _make_program([("MAIN-LOGIC", [if_stmt, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        decisions = report.nodes[0].decisions
        assert len(decisions) == 1
        assert decisions[0]["type"] == "IF"
        assert "condition" not in decisions[0]  # no condition key when None

    # -- EVALUATE with expression subject (to_dict branch) -------------------

    def test_evaluate_expression_subject(self) -> None:
        """EVALUATE with CobolExpression subject serialises it via to_dict."""
        from cobolparser.models.statements.base import CobolExpression

        eval_stmt = EvaluateStatement(LOC)
        expr = CobolExpression("COMPARISON", LOC)
        eval_stmt.add_subject(expr)
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc.add_statement(_continue())
        eval_stmt.add_when_clause(wc)

        prog = _make_program([("MAIN-LOGIC", [eval_stmt, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        decisions = report.nodes[0].decisions
        assert len(decisions) == 1
        # Subject should be serialised dict, not a string
        assert isinstance(decisions[0]["subjects"][0], dict)
        assert "expression_type" in decisions[0]["subjects"][0]

    # -- GO TO with no target (defensive) ------------------------------------

    def test_goto_no_target_no_edge(self) -> None:
        """GO TO with no target_paragraph produces no edges."""
        goto = GoStatement(LOC)
        # Don't set target

        prog = _make_program([("MAIN-LOGIC", [goto, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        goto_edges = [
            e
            for e in report.edges
            if e.edge_type in (FlowEdgeType.GOTO, FlowEdgeType.GOTO_DEPENDING)
        ]
        assert len(goto_edges) == 0

    # -- PERFORM with no target (inline only) ---------------------------------

    def test_perform_no_target_no_edge(self) -> None:
        """Inline PERFORM (no target_paragraph) produces no PERFORM edge."""
        perf = PerformStatement(LOC)
        perf.add_inline_statement(_continue())

        prog = _make_program([("MAIN-LOGIC", [perf, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert len(perform_edges) == 0

    # -- CALL with no called_program (defensive) ------------------------------

    def test_call_no_program_no_edge(self) -> None:
        """CALL with no called_program produces no edges."""
        call = CallStatement(LOC)
        # Don't set called_program

        prog = _make_program([("MAIN-LOGIC", [call, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        call_edges = [
            e
            for e in report.edges
            if e.edge_type in (FlowEdgeType.CALL, FlowEdgeType.CALL_DYNAMIC)
        ]
        assert len(call_edges) == 0
        assert len(report.external_calls) == 0

    # -- FlowEdge to_dict with condition but no loop --------------------------

    def test_edge_condition_without_loop(self) -> None:
        """FlowEdge.to_dict() includes condition even without is_loop."""
        edge = FlowEdge(
            "A",
            "B",
            FlowEdgeType.GOTO_DEPENDING,
            SourceLocation(1, 1),
            condition="DEPENDING ON WS-VAR",
        )
        d = edge.to_dict()
        assert d["condition"] == "DEPENDING ON WS-VAR"
        assert "is_loop" not in d

    # -- run against all sample files without crashing -------------------------

    def test_analyze_all_sample_files_no_crash(self) -> None:
        """ProgramFlowAnalyzer should handle all sample .cbl files without error."""
        import pathlib

        samples_dir = pathlib.Path(__file__).parent.parent.parent / "samples"
        if not samples_dir.exists():
            pytest.skip("samples directory not found")

        cbl_files = sorted(samples_dir.glob("*.cbl"))
        assert len(cbl_files) > 0, "No .cbl files found"

        analyzer = ProgramFlowAnalyzer()
        for cbl_file in cbl_files:
            source = cbl_file.read_text(encoding="utf-8")
            result = parse_cobol(source, filename=str(cbl_file))
            if result.ast is not None:
                report = analyzer.analyze(result.ast)
                d = report.to_dict()
                # Basic structural invariants
                assert d["summary"]["node_count"] == len(d["nodes"])
                assert d["summary"]["edge_count"] == len(d["edges"])
                # All entry_points should be non-empty strings
                for ep in d["entry_points"]:
                    assert ep.strip(), f"Empty entry point in {cbl_file.name}"


# ---------------------------------------------------------------------------
# Tests: New features — SORT/MERGE THRU, CANCEL, RETURN, EXIT variants,
#         CALL exception handlers, search_count, cycles, unreachable nodes
# ---------------------------------------------------------------------------


class TestProgramFlowSortMergeThru:
    """Tests for SORT/MERGE THRU edge generation."""

    def test_sort_input_procedure_thru_edge(self) -> None:
        """SORT INPUT PROCEDURE THRU creates a SORT_INPUT_PROCEDURE_THRU edge."""
        stmt = SortStatement(LOC)
        stmt.set_file_name("SORT-FILE")
        stmt.set_input_procedure("IN-START", thru="IN-END")

        prog = _make_program(
            [
                ("MAIN-LOGIC", [stmt]),
                ("IN-START", [_continue()]),
                ("IN-END", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        edge_types = {(e.edge_type, e.target) for e in report.edges}
        assert (FlowEdgeType.SORT_INPUT_PROCEDURE, "IN-START") in edge_types
        assert (FlowEdgeType.SORT_INPUT_PROCEDURE_THRU, "IN-END") in edge_types

    def test_sort_output_procedure_thru_edge(self) -> None:
        """SORT OUTPUT PROCEDURE THRU creates a SORT_OUTPUT_PROCEDURE_THRU edge."""
        stmt = SortStatement(LOC)
        stmt.set_file_name("SORT-FILE")
        stmt.set_output_procedure("OUT-START", thru="OUT-END")

        prog = _make_program(
            [
                ("MAIN-LOGIC", [stmt]),
                ("OUT-START", [_continue()]),
                ("OUT-END", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        edge_types = {(e.edge_type, e.target) for e in report.edges}
        assert (FlowEdgeType.SORT_OUTPUT_PROCEDURE, "OUT-START") in edge_types
        assert (FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU, "OUT-END") in edge_types

    def test_sort_without_thru_no_thru_edge(self) -> None:
        """SORT without THRU does not create THRU edges."""
        stmt = SortStatement(LOC)
        stmt.set_file_name("SORT-FILE")
        stmt.set_input_procedure("IN-PROC")  # no thru

        prog = _make_program(
            [
                ("MAIN-LOGIC", [stmt]),
                ("IN-PROC", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        thru_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.SORT_INPUT_PROCEDURE_THRU
        ]
        assert len(thru_edges) == 0

    def test_merge_output_procedure_thru_edge(self) -> None:
        """MERGE OUTPUT PROCEDURE THRU creates a MERGE_OUTPUT_PROCEDURE_THRU edge."""
        from cobolparser.models.statements.misc import MergeStatement

        stmt = MergeStatement(LOC)
        stmt.set_file_name("MERGE-FILE")
        stmt.set_output_procedure("MERGE-START", thru="MERGE-END")

        prog = _make_program(
            [
                ("MAIN-LOGIC", [stmt]),
                ("MERGE-START", [_continue()]),
                ("MERGE-END", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        edge_types = {(e.edge_type, e.target) for e in report.edges}
        assert (FlowEdgeType.MERGE_OUTPUT_PROCEDURE, "MERGE-START") in edge_types
        assert (FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU, "MERGE-END") in edge_types

    def test_sort_thru_edge_types_in_enum(self) -> None:
        """New SORT/MERGE THRU edge types exist in FlowEdgeType."""
        assert FlowEdgeType.SORT_INPUT_PROCEDURE_THRU.value == "SORT_INPUT_PROCEDURE_THRU"
        assert (
            FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU.value == "SORT_OUTPUT_PROCEDURE_THRU"
        )
        assert (
            FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU.value
            == "MERGE_OUTPUT_PROCEDURE_THRU"
        )


class TestProgramFlowCancel:
    """Tests for CANCEL statement tracking."""

    def test_cancel_recorded_in_report(self) -> None:
        """CANCEL records the cancelled program name and source."""
        from cobolparser.models.statements.misc import CancelStatement

        cancel = CancelStatement(LOC)
        cancel.add_program_name("'SUBPROG'")

        prog = _make_program([("MAIN-LOGIC", [cancel, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.program_cancellations) == 1
        assert report.program_cancellations[0]["program"] == "SUBPROG"
        assert report.program_cancellations[0]["cancelled_from"] == "MAIN-LOGIC"
        assert "location" in report.program_cancellations[0]

    def test_cancel_multiple_programs(self) -> None:
        """CANCEL with multiple program names records each."""
        from cobolparser.models.statements.misc import CancelStatement

        cancel = CancelStatement(LOC)
        cancel.add_program_name("'PROG-A'")
        cancel.add_program_name("'PROG-B'")

        prog = _make_program([("MAIN-LOGIC", [cancel, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.program_cancellations) == 2
        names = {c["program"] for c in report.program_cancellations}
        assert names == {"PROG-A", "PROG-B"}

    def test_cancel_in_to_dict(self) -> None:
        """program_cancellations appears in to_dict output with correct count."""
        from cobolparser.models.statements.misc import CancelStatement

        cancel = CancelStatement(LOC)
        cancel.add_program_name("'UTIL'")

        prog = _make_program([("MAIN-LOGIC", [cancel, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert "program_cancellations" in d
        assert len(d["program_cancellations"]) == 1
        assert d["summary"]["cancellation_count"] == 1

    def test_no_cancel_empty_list(self) -> None:
        """No CANCEL statements means empty program_cancellations list."""
        prog = _make_program([("MAIN-LOGIC", [_stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.program_cancellations == []
        d = report.to_dict()
        assert d["summary"]["cancellation_count"] == 0


class TestProgramFlowReturn:
    """Tests for RETURN statement handling."""

    def test_return_sets_has_return_flag(self) -> None:
        """RETURN statement sets has_return on the FlowNode."""
        from cobolparser.models.statements.misc import ReturnStatement

        ret = ReturnStatement(LOC)
        ret.set_file_name("SORT-FILE")

        prog = _make_program([("OUTPUT-PROC", [ret])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_return is True

    def test_return_has_return_in_to_dict(self) -> None:
        """has_return appears in FlowNode.to_dict() when True."""
        from cobolparser.models.statements.misc import ReturnStatement

        ret = ReturnStatement(LOC)
        ret.set_file_name("SORT-FILE")

        prog = _make_program([("OUTPUT-PROC", [ret])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0].get("has_return") is True

    def test_return_at_end_nested_statements_scanned(self) -> None:
        """Statements inside RETURN AT END clause are scanned for flow."""
        from cobolparser.models.statements.misc import ReturnStatement

        ret = ReturnStatement(LOC)
        ret.set_file_name("SORT-FILE")
        ret.set_at_end_clause([_stop_run()])

        prog = _make_program([("OUTPUT-PROC", [ret])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # STOP RUN inside AT END should be counted and mark the proc as exit
        assert report.nodes[0].has_stop_run is True
        assert "OUTPUT-PROC" in report.exit_points

    def test_return_not_at_end_nested_statements_scanned(self) -> None:
        """Statements inside RETURN NOT AT END clause are scanned."""
        from cobolparser.models.statements.misc import ReturnStatement

        ret = ReturnStatement(LOC)
        ret.set_file_name("SORT-FILE")
        ret.set_not_at_end_clause([_perform("PROCESS-REC")])

        prog = _make_program(
            [
                ("OUTPUT-PROC", [ret]),
                ("PROCESS-REC", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert any(e.target == "PROCESS-REC" for e in perform_edges)

    def test_no_return_flag_when_absent(self) -> None:
        """has_return is absent from to_dict when no RETURN statement exists."""
        prog = _make_program([("MAIN-LOGIC", [_stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert "has_return" not in d["nodes"][0]


class TestProgramFlowExitVariants:
    """Tests for EXIT SECTION, EXIT PARAGRAPH, and EXIT PERFORM."""

    def test_exit_section_sets_flag(self) -> None:
        """EXIT SECTION sets has_exit_section on the FlowNode."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("SECTION")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_exit_section is True
        assert not report.nodes[0].has_exit_program
        assert not report.nodes[0].is_exit_point

    def test_exit_paragraph_sets_flag(self) -> None:
        """EXIT PARAGRAPH sets has_exit_paragraph on the FlowNode."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PARAGRAPH")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_exit_paragraph is True
        assert not report.nodes[0].has_exit_program

    def test_exit_perform_sets_flag(self) -> None:
        """EXIT PERFORM sets has_exit_perform on the FlowNode."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PERFORM")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_exit_perform is True

    def test_exit_section_in_to_dict(self) -> None:
        """has_exit_section appears in FlowNode.to_dict() when True."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("SECTION")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0].get("has_exit_section") is True

    def test_exit_paragraph_in_to_dict(self) -> None:
        """has_exit_paragraph appears in FlowNode.to_dict() when True."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PARAGRAPH")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0].get("has_exit_paragraph") is True

    def test_exit_perform_in_to_dict(self) -> None:
        """has_exit_perform appears in FlowNode.to_dict() when True."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PERFORM")

        prog = _make_program([("MAIN-LOGIC", [exit_stmt])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0].get("has_exit_perform") is True

    def test_flags_absent_when_false(self) -> None:
        """EXIT variant flags are absent from to_dict when not set."""
        prog = _make_program([("MAIN-LOGIC", [_continue()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        node_dict = d["nodes"][0]
        assert "has_exit_section" not in node_dict
        assert "has_exit_paragraph" not in node_dict
        assert "has_exit_perform" not in node_dict


class TestProgramFlowCallExceptionHandlers:
    """Tests for CALL ON EXCEPTION / NOT ON EXCEPTION handler scanning."""

    def test_perform_in_on_exception_creates_edge(self) -> None:
        """PERFORM inside ON EXCEPTION handler generates a flow edge."""
        call = CallStatement(LOC)
        call.set_called_program("'SUBPROG'")
        call.on_exception = [_perform("ERROR-HANDLER")]

        prog = _make_program(
            [
                ("MAIN-LOGIC", [call, _stop_run()]),
                ("ERROR-HANDLER", [_goback()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert any(e.target == "ERROR-HANDLER" for e in perform_edges)

    def test_stop_run_in_on_exception_marks_exit(self) -> None:
        """STOP RUN inside ON EXCEPTION marks paragraph as exit point."""
        call = CallStatement(LOC)
        call.set_called_program("'SUBPROG'")
        call.on_exception = [_stop_run()]

        prog = _make_program([("MAIN-LOGIC", [call])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].has_stop_run is True
        assert "MAIN-LOGIC" in report.exit_points

    def test_perform_in_on_overflow_creates_edge(self) -> None:
        """PERFORM inside ON OVERFLOW handler generates a flow edge."""
        call = CallStatement(LOC)
        call.set_called_program("'SUBPROG'")
        call.on_overflow = [_perform("OVERFLOW-HANDLER")]

        prog = _make_program(
            [
                ("MAIN-LOGIC", [call, _stop_run()]),
                ("OVERFLOW-HANDLER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert any(e.target == "OVERFLOW-HANDLER" for e in perform_edges)

    def test_perform_in_not_on_exception_creates_edge(self) -> None:
        """PERFORM inside NOT ON EXCEPTION handler generates a flow edge."""
        call = CallStatement(LOC)
        call.set_called_program("'SUBPROG'")
        call.not_on_exception = [_perform("SUCCESS-HANDLER")]

        prog = _make_program(
            [
                ("MAIN-LOGIC", [call, _stop_run()]),
                ("SUCCESS-HANDLER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        assert any(e.target == "SUCCESS-HANDLER" for e in perform_edges)

    def test_nested_statements_in_handlers_counted(self) -> None:
        """Statements inside CALL exception handlers are counted in statement_count."""
        call = CallStatement(LOC)
        call.set_called_program("'SUBPROG'")
        call.on_exception = [_continue(), _continue()]  # 2 statements in handler

        prog = _make_program([("MAIN-LOGIC", [call, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # CALL + 2 handler stmts + STOP RUN = 4
        assert report.nodes[0].statement_count == 4


class TestProgramFlowSearchCount:
    """Tests for search_count metric on FlowNode."""

    def test_search_increments_search_count(self) -> None:
        """SEARCH statement increments search_count on the node."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        search.add_when_clause("condition", [_continue()])

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].search_count == 1

    def test_multiple_search_counts(self) -> None:
        """Multiple SEARCH statements accumulate in search_count."""
        from cobolparser.models.statements.control import SearchStatement

        s1 = SearchStatement(LOC)
        s1.set_table_name("TABLE-A")
        s1.add_when_clause("c1", [_continue()])

        s2 = SearchStatement(LOC)
        s2.set_table_name("TABLE-B")
        s2.add_when_clause("c2", [_continue()])

        prog = _make_program([("MAIN-LOGIC", [s1, s2, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.nodes[0].search_count == 2

    def test_search_count_in_to_dict(self) -> None:
        """search_count appears in branching dict in FlowNode.to_dict()."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        search.add_when_clause("condition", [_continue()])

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0]["branching"]["search_count"] == 1

    def test_search_count_zero_when_absent(self) -> None:
        """search_count is 0 (present in dict) when no SEARCH statements."""
        prog = _make_program([("MAIN-LOGIC", [_stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert d["nodes"][0]["branching"]["search_count"] == 0


class TestProgramFlowCycleDetection:
    """Tests for cycle detection in the control flow graph."""

    def test_no_cycles_in_linear_flow(self) -> None:
        """A linear program with no loops has no cycles."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("WORK"), _stop_run()]),
                ("WORK", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.cycles == []
        assert report.to_dict()["summary"]["cycle_count"] == 0

    def test_self_perform_creates_cycle(self) -> None:
        """A paragraph that PERFORMs itself is a cycle."""
        prog = _make_program(
            [
                ("LOOP-PARA", [_perform("LOOP-PARA")]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.cycles) >= 1
        # The self-loop cycle should contain LOOP-PARA
        all_cycle_nodes = {node for cycle in report.cycles for node in cycle}
        assert "LOOP-PARA" in all_cycle_nodes

    def test_mutual_perform_cycle(self) -> None:
        """A → B → A via PERFORM forms a cycle."""
        prog = _make_program(
            [
                ("PARA-A", [_perform("PARA-B")]),
                ("PARA-B", [_perform("PARA-A")]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.cycles) >= 1
        all_cycle_nodes = {node for cycle in report.cycles for node in cycle}
        assert "PARA-A" in all_cycle_nodes
        assert "PARA-B" in all_cycle_nodes

    def test_goto_cycle_detected(self) -> None:
        """A → B via GO TO and B → A via fall-through creates a cycle."""
        prog = _make_program(
            [
                ("PARA-A", [_goto("PARA-B")]),
                ("PARA-B", [_goto("PARA-A")]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.cycles) >= 1

    def test_cycles_in_to_dict(self) -> None:
        """Cycles appear in to_dict() under the 'cycles' key."""
        prog = _make_program(
            [
                ("LOOP-PARA", [_perform("LOOP-PARA"), _stop_run()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert "cycles" in d
        assert d["summary"]["cycle_count"] >= 1

    def test_no_cycles_empty_program(self) -> None:
        """Empty procedure division has no cycles."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY", loc)
        proc_div = CobolDivision("PROCEDURE", loc)
        prog.add_division(proc_div)

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.cycles == []


class TestProgramFlowUnreachableNodes:
    """Tests for unreachable node detection."""

    def test_no_unreachable_in_linear_flow(self) -> None:
        """A linear program with fall-through has no unreachable nodes."""
        prog = _make_program(
            [
                ("PARA-A", [_continue()]),
                ("PARA-B", [_continue()]),
                ("PARA-C", [_stop_run()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.unreachable_nodes == []
        assert report.to_dict()["summary"]["unreachable_node_count"] == 0

    def test_paragraph_after_stop_run_is_unreachable(self) -> None:
        """A paragraph after STOP RUN with no other path is unreachable."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
                ("NEVER-CALLED", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # MAIN-LOGIC has STOP RUN so no fall-through, and no PERFORM to NEVER-CALLED
        assert "NEVER-CALLED" in report.unreachable_nodes

    def test_performed_paragraph_is_reachable(self) -> None:
        """A paragraph that is PERFORMed is reachable."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("HELPER"), _stop_run()]),
                ("HELPER", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert "HELPER" not in report.unreachable_nodes

    def test_goto_target_is_reachable(self) -> None:
        """A paragraph targeted by GO TO is reachable."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_goto("ERROR-EXIT")]),
                ("ERROR-EXIT", [_stop_run()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert "ERROR-EXIT" not in report.unreachable_nodes

    def test_unreachable_nodes_in_to_dict(self) -> None:
        """unreachable_nodes appears in to_dict() with correct count."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_stop_run()]),
                ("DEAD-CODE", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)
        d = report.to_dict()

        assert "unreachable_nodes" in d
        assert "DEAD-CODE" in d["unreachable_nodes"]
        assert d["summary"]["unreachable_node_count"] >= 1

    def test_all_reachable_empty_unreachable_list(self) -> None:
        """When all nodes are reachable, unreachable_nodes is empty."""
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("WORK"), _stop_run()]),
                ("WORK", [_continue()]),
            ]
        )

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.unreachable_nodes == []


class TestProgramFlowReportNewFields:
    """Tests for new top-level fields in ProgramFlowReport.to_dict()."""

    def test_to_dict_has_program_cancellations(self) -> None:
        """to_dict() includes program_cancellations key."""
        report = ProgramFlowReport(program_name="TEST")
        d = report.to_dict()
        assert "program_cancellations" in d
        assert isinstance(d["program_cancellations"], list)

    def test_to_dict_has_cycles(self) -> None:
        """to_dict() includes cycles key."""
        report = ProgramFlowReport(program_name="TEST")
        d = report.to_dict()
        assert "cycles" in d
        assert isinstance(d["cycles"], list)

    def test_to_dict_has_unreachable_nodes(self) -> None:
        """to_dict() includes unreachable_nodes key."""
        report = ProgramFlowReport(program_name="TEST")
        d = report.to_dict()
        assert "unreachable_nodes" in d
        assert isinstance(d["unreachable_nodes"], list)

    def test_summary_has_new_counts(self) -> None:
        """summary dict includes cancellation_count, cycle_count, unreachable_node_count."""
        report = ProgramFlowReport(program_name="TEST")
        d = report.to_dict()
        summary = d["summary"]
        assert "cancellation_count" in summary
        assert "cycle_count" in summary
        assert "unreachable_node_count" in summary

    def test_summary_counts_match_lists(self) -> None:
        """New summary counts reflect the actual list lengths."""
        report = ProgramFlowReport(program_name="TEST")
        report.program_cancellations = [{"program": "X", "cancelled_from": "Y"}]
        report.cycles = [["A", "B"], ["C"]]
        report.unreachable_nodes = ["DEAD"]
        d = report.to_dict()
        assert d["summary"]["cancellation_count"] == 1
        assert d["summary"]["cycle_count"] == 2
        assert d["summary"]["unreachable_node_count"] == 1

    def test_branching_dict_has_search_count(self) -> None:
        """FlowNode.to_dict() branching dict includes search_count."""
        node = FlowNode("PARA", "PARAGRAPH", SourceLocation(1, 1))
        d = node.to_dict()
        assert "search_count" in d["branching"]
        assert d["branching"]["search_count"] == 0


# ---------------------------------------------------------------------------
# Tests: Real-COBOL integration — all new features exercised via parse_cobol
# ---------------------------------------------------------------------------


class TestProgramFlowRealCobolIntegration:
    """Integration tests that parse actual COBOL source with parse_cobol()
    and verify every new feature added to ProgramFlowAnalyzer.

    These complement the unit tests that use manually-constructed ASTs by
    proving that the full pipeline (lexer → parser → analyzer) produces the
    expected results on real COBOL text.
    """

    @staticmethod
    def _analyze(source: str) -> "ProgramFlowReport":  # type: ignore[name-defined]
        result = parse_cobol(source, filename="<integration-test>")
        assert result.ast is not None, f"Parse failed: {result.errors}"
        return ProgramFlowAnalyzer().analyze(result.ast)

    # ------------------------------------------------------------------
    # SORT INPUT/OUTPUT PROCEDURE THRU
    # ------------------------------------------------------------------

    def test_sort_input_procedure_thru_real_cobol(self) -> None:
        """SORT INPUT PROCEDURE ... THRU produces the correct edge types."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTTHRU.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-WRK ASSIGN TO 'SORTWRK'.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-WRK.
       01 SORT-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-DONE PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SORT SORT-WRK ON ASCENDING KEY SORT-REC
               INPUT PROCEDURE IN-START THRU IN-END
               OUTPUT PROCEDURE OUT-START THRU OUT-END.
           STOP RUN.
       IN-START.
           DISPLAY 'INPUT START'.
       IN-END.
           EXIT.
       OUT-START.
           DISPLAY 'OUTPUT START'.
       OUT-END.
           EXIT.
"""
        report = self._analyze(source)
        edge_pairs = {(e.edge_type, e.target) for e in report.edges}

        assert (FlowEdgeType.SORT_INPUT_PROCEDURE, "IN-START") in edge_pairs
        assert (FlowEdgeType.SORT_INPUT_PROCEDURE_THRU, "IN-END") in edge_pairs
        assert (FlowEdgeType.SORT_OUTPUT_PROCEDURE, "OUT-START") in edge_pairs
        assert (FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU, "OUT-END") in edge_pairs

    def test_sort_output_procedure_thru_no_input_thru(self) -> None:
        """SORT with OUTPUT THRU but no INPUT THRU emits only one THRU edge."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTOUT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-WRK ASSIGN TO 'SORTWRK'.
           SELECT IN-FILE ASSIGN TO 'INPUT'.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-WRK.
       01 SORT-REC PIC X(80).
       FD IN-FILE.
       01 IN-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SORT SORT-WRK ON ASCENDING KEY SORT-REC
               USING IN-FILE
               OUTPUT PROCEDURE OUT-A THRU OUT-Z.
           STOP RUN.
       OUT-A.
           DISPLAY 'A'.
       OUT-Z.
           EXIT.
"""
        report = self._analyze(source)
        thru_edges = [
            e for e in report.edges
            if e.edge_type == FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU
        ]
        input_thru_edges = [
            e for e in report.edges
            if e.edge_type == FlowEdgeType.SORT_INPUT_PROCEDURE_THRU
        ]

        assert len(thru_edges) == 1
        assert thru_edges[0].target == "OUT-Z"
        assert len(input_thru_edges) == 0

    # ------------------------------------------------------------------
    # MERGE OUTPUT PROCEDURE THRU
    # ------------------------------------------------------------------

    def test_merge_output_procedure_thru_real_cobol(self) -> None:
        """MERGE OUTPUT PROCEDURE ... THRU produces the correct edge types."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MERGETHRU.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MERGE-WRK  ASSIGN TO 'MRGWRK'.
           SELECT MERGE-IN1  ASSIGN TO 'MRGF1'.
           SELECT MERGE-IN2  ASSIGN TO 'MRGF2'.
       DATA DIVISION.
       FILE SECTION.
       SD MERGE-WRK.
       01 MERGE-REC PIC X(80).
       FD MERGE-IN1.
       01 IN1-REC PIC X(80).
       FD MERGE-IN2.
       01 IN2-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MERGE MERGE-WRK ON ASCENDING KEY MERGE-REC
               USING MERGE-IN1 MERGE-IN2
               OUTPUT PROCEDURE OUT-START THRU OUT-END.
           STOP RUN.
       OUT-START.
           RETURN MERGE-WRK
               AT END MOVE 'Y' TO WS-EOF
           END-RETURN.
       OUT-END.
           EXIT.
"""
        report = self._analyze(source)
        edge_pairs = {(e.edge_type, e.target) for e in report.edges}

        assert (FlowEdgeType.MERGE_OUTPUT_PROCEDURE, "OUT-START") in edge_pairs
        assert (FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU, "OUT-END") in edge_pairs

    # ------------------------------------------------------------------
    # CANCEL statement tracking
    # ------------------------------------------------------------------

    def test_cancel_tracked_in_real_cobol(self) -> None:
        """CANCEL statement records cancelled program and calling paragraph."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCELTEST.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'MODULE-A' USING WS-PARAM
           CANCEL 'MODULE-A'
           STOP RUN.
"""
        report = self._analyze(source)

        assert len(report.program_cancellations) == 1
        c = report.program_cancellations[0]
        assert c["program"] == "MODULE-A"
        assert c["cancelled_from"] == "MAIN-LOGIC"
        assert "location" in c

    def test_cancel_count_in_summary(self) -> None:
        """cancellation_count in summary matches the cancellations list."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCELCNT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM LOAD-MODULES
           PERFORM DO-WORK
           PERFORM UNLOAD-MODULES
           STOP RUN.
       LOAD-MODULES.
           CALL 'MOD-A'
           CALL 'MOD-B'.
       DO-WORK.
           DISPLAY 'WORKING'.
       UNLOAD-MODULES.
           CANCEL 'MOD-A'
           CANCEL 'MOD-B'.
"""
        report = self._analyze(source)
        d = report.to_dict()

        assert d["summary"]["cancellation_count"] == 2
        assert d["summary"]["cancellation_count"] == len(d["program_cancellations"])
        names = {c["program"] for c in d["program_cancellations"]}
        assert names == {"MOD-A", "MOD-B"}

    # ------------------------------------------------------------------
    # RETURN statement (SORT/MERGE output procedure)
    # ------------------------------------------------------------------

    def test_return_has_return_flag_real_cobol(self) -> None:
        """RETURN inside a SORT output procedure sets has_return on the node."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RETFLAG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-WRK ASSIGN TO 'SORTWRK'.
           SELECT IN-FILE  ASSIGN TO 'INPUT'.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-WRK.
       01 SORT-REC PIC X(80).
       FD IN-FILE.
       01 IN-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SORT SORT-WRK ON ASCENDING KEY SORT-REC
               USING IN-FILE
               OUTPUT PROCEDURE OUTPUT-PROC.
           STOP RUN.
       OUTPUT-PROC.
           RETURN SORT-WRK
               AT END MOVE 'Y' TO WS-EOF
               NOT AT END PERFORM WRITE-RECORD
           END-RETURN.
       WRITE-RECORD.
           DISPLAY SORT-REC.
"""
        report = self._analyze(source)

        out_node = next((n for n in report.nodes if n.name == "OUTPUT-PROC"), None)
        assert out_node is not None
        assert out_node.has_return is True

        d = report.to_dict()
        out_dict = next(n for n in d["nodes"] if n["name"] == "OUTPUT-PROC")
        assert out_dict.get("has_return") is True

    def test_return_not_at_end_generates_perform_edge(self) -> None:
        """PERFORM inside RETURN NOT AT END clause creates a flow edge."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RETEDGE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-WRK ASSIGN TO 'SORTWRK'.
           SELECT IN-FILE  ASSIGN TO 'INPUT'.
       DATA DIVISION.
       FILE SECTION.
       SD SORT-WRK.
       01 SORT-REC PIC X(80).
       FD IN-FILE.
       01 IN-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SORT SORT-WRK ON ASCENDING KEY SORT-REC
               USING IN-FILE
               OUTPUT PROCEDURE OUTPUT-PROC.
           STOP RUN.
       OUTPUT-PROC.
           RETURN SORT-WRK
               AT END MOVE 'Y' TO WS-EOF
               NOT AT END PERFORM PROCESS-RECORD
           END-RETURN.
       PROCESS-RECORD.
           DISPLAY SORT-REC.
"""
        report = self._analyze(source)

        perform_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.PERFORM]
        targets = {e.target for e in perform_edges if e.source == "OUTPUT-PROC"}
        assert "PROCESS-RECORD" in targets

    # ------------------------------------------------------------------
    # EXIT SECTION / EXIT PARAGRAPH / EXIT PERFORM
    # ------------------------------------------------------------------

    def test_exit_section_flag_real_cobol(self) -> None:
        """EXIT SECTION sets has_exit_section on the paragraph's FlowNode."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXSEC.
       PROCEDURE DIVISION.
       WORK SECTION.
       WORK-PARA.
           IF 1 = 1
               EXIT SECTION
           END-IF
           DISPLAY 'NEVER'.
       MAIN SECTION.
       MAIN-PARA.
           PERFORM WORK-PARA
           STOP RUN.
"""
        report = self._analyze(source)
        work_node = next((n for n in report.nodes if n.name == "WORK-PARA"), None)
        assert work_node is not None
        assert work_node.has_exit_section is True

        d = report.to_dict()
        work_dict = next(n for n in d["nodes"] if n["name"] == "WORK-PARA")
        assert work_dict.get("has_exit_section") is True

    def test_exit_paragraph_flag_real_cobol(self) -> None:
        """EXIT PARAGRAPH sets has_exit_paragraph on the FlowNode."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXPARA.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM COND-EXIT
           STOP RUN.
       COND-EXIT.
           IF 1 = 1
               EXIT PARAGRAPH
           END-IF
           DISPLAY 'CONTINUATION'.
       AFTER-COND.
           DISPLAY 'AFTER'.
"""
        report = self._analyze(source)
        node = next((n for n in report.nodes if n.name == "COND-EXIT"), None)
        assert node is not None
        assert node.has_exit_paragraph is True

    def test_exit_perform_flag_real_cobol(self) -> None:
        """EXIT PERFORM inside an inline PERFORM sets has_exit_perform."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXPERF.
       WORKING-STORAGE SECTION.
       01 WS-CTR PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM UNTIL WS-CTR > 10
               ADD 1 TO WS-CTR
               IF WS-CTR = 5
                   EXIT PERFORM
               END-IF
           END-PERFORM
           STOP RUN.
"""
        report = self._analyze(source)
        main_node = next((n for n in report.nodes if n.name == "MAIN-LOGIC"), None)
        assert main_node is not None
        assert main_node.has_exit_perform is True

        d = report.to_dict()
        main_dict = next(n for n in d["nodes"] if n["name"] == "MAIN-LOGIC")
        assert main_dict.get("has_exit_perform") is True

    # ------------------------------------------------------------------
    # CALL ON EXCEPTION / NOT ON EXCEPTION / ON OVERFLOW
    # ------------------------------------------------------------------

    def test_call_on_exception_perform_creates_edge(self) -> None:
        """PERFORM inside ON EXCEPTION generates a flow edge from the caller."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXCPERF.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'SUBPROG' USING WS-IN
               ON EXCEPTION
                   PERFORM ERROR-HANDLER
               NOT ON EXCEPTION
                   PERFORM SUCCESS-HANDLER
           END-CALL.
           STOP RUN.
       ERROR-HANDLER.
           DISPLAY 'ERROR'.
       SUCCESS-HANDLER.
           DISPLAY 'OK'.
"""
        report = self._analyze(source)
        perform_edges = {e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM}

        assert "ERROR-HANDLER" in perform_edges
        assert "SUCCESS-HANDLER" in perform_edges

    def test_call_on_exception_stop_run_marks_exit(self) -> None:
        """STOP RUN inside ON EXCEPTION marks the paragraph as an exit point."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXCSTOP.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'CRITICAL-SVC'
               ON EXCEPTION
                   DISPLAY 'FATAL ERROR'
                   STOP RUN
           END-CALL.
           DISPLAY 'CONTINUING'.
           STOP RUN.
"""
        report = self._analyze(source)
        main_node = next(n for n in report.nodes if n.name == "MAIN-LOGIC")
        assert main_node.has_stop_run is True
        assert "MAIN-LOGIC" in report.exit_points

    def test_call_on_overflow_perform_creates_edge(self) -> None:
        """PERFORM inside ON OVERFLOW generates a flow edge."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OVFLW.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'SUBPROG'
               ON OVERFLOW
                   PERFORM OVERFLOW-HANDLER
           END-CALL.
           STOP RUN.
       OVERFLOW-HANDLER.
           DISPLAY 'OVERFLOW'.
"""
        report = self._analyze(source)
        perform_edges = {e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM}
        assert "OVERFLOW-HANDLER" in perform_edges

    def test_call_exception_sample_file(self) -> None:
        """The call_exception_handlers_complete.cbl sample produces PERFORM
        edges for paragraphs called from within exception handler branches."""
        import pathlib

        sample = (
            pathlib.Path(__file__).parent.parent.parent
            / "samples"
            / "call_exception_handlers_complete.cbl"
        )
        if not sample.exists():
            pytest.skip(f"Sample not found: {sample}")

        report = self._analyze(sample.read_text(encoding="utf-8"))

        # Paragraphs PERFORMed from inside exception handlers must appear
        perform_targets = {
            e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM
        }
        # These come from ON EXCEPTION handler branches in the sample file
        assert "LOG-ERROR" in perform_targets
        assert "HANDLE-SERVICE-FAILURE" in perform_targets

    # ------------------------------------------------------------------
    # SEARCH statement — search_count metric
    # ------------------------------------------------------------------

    def test_search_count_real_cobol(self) -> None:
        """SEARCH statement increments search_count in the branching metrics."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCHCNT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TABLE.
           05 WS-ENTRY OCCURS 10 TIMES INDEXED BY WS-IDX.
               10 WS-KEY PIC X(5).
               10 WS-VAL PIC X(10).
       01 WS-FIND PIC X(5) VALUE 'KEY01'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SET WS-IDX TO 1
           SEARCH WS-ENTRY
               AT END DISPLAY 'NOT FOUND'
               WHEN WS-KEY(WS-IDX) = WS-FIND
                   DISPLAY WS-VAL(WS-IDX)
           END-SEARCH.
           STOP RUN.
"""
        report = self._analyze(source)
        main_node = next(n for n in report.nodes if n.name == "MAIN-LOGIC")
        assert main_node.search_count == 1

        d = report.to_dict()
        main_dict = next(n for n in d["nodes"] if n["name"] == "MAIN-LOGIC")
        assert main_dict["branching"]["search_count"] == 1

    def test_search_count_real_cobol_sample(self) -> None:
        """The control_flow.cbl sample's SEARCH-TESTS paragraph has a
        positive search_count in the flow report."""
        import pathlib

        sample = (
            pathlib.Path(__file__).parent.parent.parent / "samples" / "control_flow.cbl"
        )
        if not sample.exists():
            pytest.skip(f"Sample not found: {sample}")

        report = self._analyze(sample.read_text(encoding="utf-8"))

        search_node = next(
            (n for n in report.nodes if n.name == "SEARCH-TESTS"), None
        )
        assert search_node is not None
        assert search_node.search_count >= 1

    def test_multiple_search_statements_real_cobol(self) -> None:
        """Two SEARCH statements in one paragraph give search_count == 2."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCH2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TABLE-A.
           05 A-ENTRY OCCURS 5 TIMES INDEXED BY A-IDX.
               10 A-KEY PIC X(3).
       01 TABLE-B.
           05 B-ENTRY OCCURS 5 TIMES INDEXED BY B-IDX.
               10 B-KEY PIC X(3).
       01 WS-FIND PIC X(3) VALUE 'XYZ'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           SET A-IDX TO 1
           SEARCH A-ENTRY
               AT END DISPLAY 'A NOT FOUND'
               WHEN A-KEY(A-IDX) = WS-FIND DISPLAY 'A FOUND'
           END-SEARCH.
           SET B-IDX TO 1
           SEARCH B-ENTRY
               AT END DISPLAY 'B NOT FOUND'
               WHEN B-KEY(B-IDX) = WS-FIND DISPLAY 'B FOUND'
           END-SEARCH.
           STOP RUN.
"""
        report = self._analyze(source)
        main_node = next(n for n in report.nodes if n.name == "MAIN-LOGIC")
        assert main_node.search_count == 2

    # ------------------------------------------------------------------
    # Cycle detection
    # ------------------------------------------------------------------

    def test_mutual_perform_cycle_real_cobol(self) -> None:
        """Two paragraphs that PERFORM each other form a detected cycle."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CYCLTEST.
       PROCEDURE DIVISION.
       PARA-A.
           PERFORM PARA-B.
       PARA-B.
           PERFORM PARA-A.
"""
        report = self._analyze(source)

        assert len(report.cycles) >= 1
        all_cycle_nodes = {node for cycle in report.cycles for node in cycle}
        assert "PARA-A" in all_cycle_nodes
        assert "PARA-B" in all_cycle_nodes

        d = report.to_dict()
        assert d["summary"]["cycle_count"] >= 1
        assert isinstance(d["cycles"][0], list)

    def test_self_perform_cycle_real_cobol(self) -> None:
        """A paragraph that PERFORMs itself is detected as a cycle."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELFLOOP.
       PROCEDURE DIVISION.
       LOOP-PARA.
           PERFORM LOOP-PARA.
"""
        report = self._analyze(source)

        assert len(report.cycles) >= 1
        all_cycle_nodes = {n for c in report.cycles for n in c}
        assert "LOOP-PARA" in all_cycle_nodes

    def test_no_cycle_in_normal_flow_real_cobol(self) -> None:
        """A program with no recursive PERFORM has cycles == []."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOCYCLE.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PARA
           PERFORM WORK-PARA
           PERFORM DONE-PARA
           STOP RUN.
       INIT-PARA.
           DISPLAY 'INIT'.
       WORK-PARA.
           DISPLAY 'WORK'.
       DONE-PARA.
           DISPLAY 'DONE'.
"""
        report = self._analyze(source)

        assert report.cycles == []
        assert report.to_dict()["summary"]["cycle_count"] == 0

    def test_three_way_cycle_real_cobol(self) -> None:
        """A → B → C → A mutual PERFORM chain is detected."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CYCLE3.
       PROCEDURE DIVISION.
       PARA-A.
           PERFORM PARA-B.
       PARA-B.
           PERFORM PARA-C.
       PARA-C.
           PERFORM PARA-A.
"""
        report = self._analyze(source)

        assert len(report.cycles) >= 1
        all_cycle_nodes = {n for c in report.cycles for n in c}
        assert "PARA-A" in all_cycle_nodes
        assert "PARA-B" in all_cycle_nodes
        assert "PARA-C" in all_cycle_nodes

    # ------------------------------------------------------------------
    # Unreachable node detection
    # ------------------------------------------------------------------

    def test_unreachable_after_stop_run_real_cobol(self) -> None:
        """Paragraphs with no path from any entry point are unreachable."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEADCODE.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
       NEVER-CALLED.
           DISPLAY 'DEAD CODE'.
       ALSO-DEAD.
           DISPLAY 'ALSO DEAD'.
"""
        report = self._analyze(source)

        assert "NEVER-CALLED" in report.unreachable_nodes
        assert "ALSO-DEAD" in report.unreachable_nodes
        assert "MAIN-LOGIC" not in report.unreachable_nodes

        d = report.to_dict()
        assert d["summary"]["unreachable_node_count"] == 2
        assert "NEVER-CALLED" in d["unreachable_nodes"]

    def test_reachable_via_perform_real_cobol(self) -> None:
        """All PERFORMed paragraphs are reachable — unreachable list is empty."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FULLREACH.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM INIT-PARA
           PERFORM WORK-PARA
           PERFORM EXIT-PARA
           STOP RUN.
       INIT-PARA.
           DISPLAY 'INIT'.
       WORK-PARA.
           DISPLAY 'WORK'.
       EXIT-PARA.
           DISPLAY 'EXIT'.
"""
        report = self._analyze(source)

        assert report.unreachable_nodes == []
        assert report.to_dict()["summary"]["unreachable_node_count"] == 0

    def test_reachable_via_goto_real_cobol(self) -> None:
        """Paragraph targeted by GO TO is not unreachable."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOREAC.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF 1 = 1
               GO TO ERROR-EXIT
           END-IF
           STOP RUN.
       ERROR-EXIT.
           DISPLAY 'ERROR'
           STOP RUN.
"""
        report = self._analyze(source)

        assert "ERROR-EXIT" not in report.unreachable_nodes

    def test_unreachable_count_in_summary_real_cobol(self) -> None:
        """unreachable_node_count in summary matches unreachable_nodes list."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. URCNT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
       DEAD-1.
           DISPLAY 'D1'.
       DEAD-2.
           DISPLAY 'D2'.
       DEAD-3.
           DISPLAY 'D3'.
"""
        report = self._analyze(source)
        d = report.to_dict()

        assert d["summary"]["unreachable_node_count"] == len(d["unreachable_nodes"])
        assert d["summary"]["unreachable_node_count"] == 3

    # ------------------------------------------------------------------
    # Combined real-COBOL program exercising multiple new features
    # ------------------------------------------------------------------

    def test_full_feature_integration_real_cobol(self) -> None:
        """One realistic program exercises CANCEL, SEARCH, EXIT PERFORM,
        CALL exception handlers, unreachable detection, and summary counts
        all in a single parse-and-analyze run."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FULLINT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC 9 VALUE 0.
       01 WS-LOOKUP-TABLE.
           05 WS-CODE-ENTRY OCCURS 5 TIMES INDEXED BY WS-IDX.
               10 WS-CODE PIC X(3).
               10 WS-DESC PIC X(20).
       01 WS-FIND-CODE PIC X(3) VALUE 'ERR'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM LOAD-CODES
           PERFORM LOOKUP-CODE
           CALL 'EXTERNAL-SVC' USING WS-STATUS
               ON EXCEPTION
                   PERFORM ERROR-HANDLER
               NOT ON EXCEPTION
                   PERFORM SUCCESS-HANDLER
           END-CALL.
           CANCEL 'EXTERNAL-SVC'.
           PERFORM CLEANUP
           STOP RUN.
       LOAD-CODES.
           DISPLAY 'LOADING'.
       LOOKUP-CODE.
           SET WS-IDX TO 1
           SEARCH WS-CODE-ENTRY
               AT END DISPLAY 'CODE NOT FOUND'
               WHEN WS-CODE(WS-IDX) = WS-FIND-CODE
                   DISPLAY WS-DESC(WS-IDX)
           END-SEARCH.
       ERROR-HANDLER.
           DISPLAY 'SERVICE ERROR'
           MOVE 1 TO WS-STATUS.
       SUCCESS-HANDLER.
           DISPLAY 'SERVICE OK'
           MOVE 0 TO WS-STATUS.
       CLEANUP.
           DISPLAY 'CLEANUP'
           GOBACK.
       DEAD-PARA.
           DISPLAY 'UNREACHABLE'.
"""
        report = self._analyze(source)

        # -- all paragraphs found --
        node_names = {n.name for n in report.nodes}
        for expected in [
            "MAIN-LOGIC", "LOAD-CODES", "LOOKUP-CODE",
            "ERROR-HANDLER", "SUCCESS-HANDLER", "CLEANUP", "DEAD-PARA",
        ]:
            assert expected in node_names

        # -- CANCEL tracking --
        assert len(report.program_cancellations) == 1
        assert report.program_cancellations[0]["program"] == "EXTERNAL-SVC"
        assert report.program_cancellations[0]["cancelled_from"] == "MAIN-LOGIC"

        # -- SEARCH count --
        lookup_node = next(n for n in report.nodes if n.name == "LOOKUP-CODE")
        assert lookup_node.search_count == 1

        # -- CALL exception handler edges --
        perform_targets = {
            e.target for e in report.edges if e.edge_type == FlowEdgeType.PERFORM
        }
        assert "ERROR-HANDLER" in perform_targets
        assert "SUCCESS-HANDLER" in perform_targets

        # -- unreachable detection --
        assert "DEAD-PARA" in report.unreachable_nodes

        # -- no cycles (normal flow) --
        assert report.cycles == []

        # -- summary consistency --
        d = report.to_dict()
        assert d["summary"]["node_count"] == len(d["nodes"])
        assert d["summary"]["edge_count"] == len(d["edges"])
        assert d["summary"]["cancellation_count"] == 1
        assert d["summary"]["unreachable_node_count"] >= 1


# ---------------------------------------------------------------------------
# Tests: Edge-case coverage (audit gaps)
# ---------------------------------------------------------------------------


class TestProgramFlowAuditEdgeCases:
    """Covers boundary conditions and untested branches found by the deep audit."""

    # ------------------------------------------------------------------
    # CANCEL: empty program_names list
    # ------------------------------------------------------------------

    def test_cancel_empty_program_names_ignored(self) -> None:
        """CANCEL with no program names produces no cancellations."""
        from cobolparser.models.statements.misc import CancelStatement

        cancel = CancelStatement(LOC)
        # add_program_name is never called -> program_names stays []
        prog = _make_program([("MAIN-LOGIC", [cancel, _stop_run()])])

        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert report.program_cancellations == []

    # ------------------------------------------------------------------
    # CALL: called_program is None
    # ------------------------------------------------------------------

    def test_call_none_program_no_edge(self) -> None:
        """CALL statement whose called_program was never set produces no edges."""
        call = CallStatement(LOC)
        # set_called_program is deliberately NOT called

        prog = _make_program([("MAIN-LOGIC", [call, _stop_run()])])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        call_edges = [
            e
            for e in report.edges
            if e.edge_type in (FlowEdgeType.CALL, FlowEdgeType.CALL_DYNAMIC)
        ]
        assert len(call_edges) == 0
        assert report.external_calls == []

    # ------------------------------------------------------------------
    # SORT/MERGE THRU without base procedure
    # ------------------------------------------------------------------

    def test_sort_input_procedure_thru_without_base_creates_no_edge(self) -> None:
        """SORT with input_procedure_thru but no input_procedure -> no SORT edges."""
        stmt = SortStatement(LOC)
        stmt.set_file_name("SORT-FILE")
        stmt.input_procedure_thru = "PROC-END"  # THRU set directly, base is None

        prog = _make_program([
            ("MAIN-LOGIC", [stmt, _stop_run()]),
            ("PROC-END", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        sort_input_edges = [
            e
            for e in report.edges
            if e.edge_type
            in (FlowEdgeType.SORT_INPUT_PROCEDURE, FlowEdgeType.SORT_INPUT_PROCEDURE_THRU)
        ]
        assert len(sort_input_edges) == 0

    def test_sort_output_procedure_thru_without_base_creates_no_edge(self) -> None:
        """SORT with output_procedure_thru but no output_procedure -> no edges."""
        stmt = SortStatement(LOC)
        stmt.set_file_name("SORT-FILE")
        stmt.output_procedure_thru = "PROC-END"  # THRU set directly, base is None

        prog = _make_program([
            ("MAIN-LOGIC", [stmt, _stop_run()]),
            ("PROC-END", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        sort_output_edges = [
            e
            for e in report.edges
            if e.edge_type
            in (FlowEdgeType.SORT_OUTPUT_PROCEDURE, FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU)
        ]
        assert len(sort_output_edges) == 0

    def test_merge_output_procedure_thru_without_base_creates_no_edge(self) -> None:
        """MERGE with output_procedure_thru but no output_procedure -> no edges."""
        from cobolparser.models.statements.misc import MergeStatement

        stmt = MergeStatement(LOC)
        stmt.set_file_name("MERGE-FILE")
        stmt.output_procedure_thru = "PROC-END"  # THRU set directly, base is None

        prog = _make_program([
            ("MAIN-LOGIC", [stmt, _stop_run()]),
            ("PROC-END", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        merge_output_edges = [
            e
            for e in report.edges
            if e.edge_type
            in (
                FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
                FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
            )
        ]
        assert len(merge_output_edges) == 0

    # ------------------------------------------------------------------
    # Fall-through: EXIT SECTION/PARAGRAPH/PERFORM do NOT block it
    # ------------------------------------------------------------------

    def test_fall_through_after_exit_section(self) -> None:
        """EXIT SECTION does NOT prevent fall-through to the next paragraph."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("SECTION")

        prog = _make_program([
            ("PARA-A", [exit_stmt]),
            ("PARA-B", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.FALL_THROUGH
            and e.source == "PARA-A"
            and e.target == "PARA-B"
        ]
        assert len(ft_edges) == 1

    def test_fall_through_after_exit_paragraph(self) -> None:
        """EXIT PARAGRAPH does NOT prevent fall-through to the next paragraph."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PARAGRAPH")

        prog = _make_program([
            ("PARA-A", [exit_stmt]),
            ("PARA-B", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.FALL_THROUGH
            and e.source == "PARA-A"
            and e.target == "PARA-B"
        ]
        assert len(ft_edges) == 1

    def test_fall_through_after_exit_perform(self) -> None:
        """EXIT PERFORM does NOT prevent fall-through to the next paragraph."""
        exit_stmt = ExitStatement(LOC)
        exit_stmt.set_exit_type("PERFORM")

        prog = _make_program([
            ("PARA-A", [exit_stmt]),
            ("PARA-B", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.FALL_THROUGH
            and e.source == "PARA-A"
            and e.target == "PARA-B"
        ]
        assert len(ft_edges) == 1

    def test_fall_through_after_goto_depending(self) -> None:
        """GO TO DEPENDING ON is conditional; fall-through still happens."""
        prog = _make_program([
            ("DISPATCH", [_goto_depending(["BRANCH-A", "BRANCH-B"], "WS-IDX")]),
            ("NEXT-PARA", [_continue()]),
            ("BRANCH-A", [_continue()]),
            ("BRANCH-B", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        ft_edges = [
            e
            for e in report.edges
            if e.edge_type == FlowEdgeType.FALL_THROUGH
            and e.source == "DISPATCH"
            and e.target == "NEXT-PARA"
        ]
        assert len(ft_edges) == 1

    # ------------------------------------------------------------------
    # Cycle detection: multiple independent cycles
    # ------------------------------------------------------------------

    def test_two_independent_cycles_both_detected(self) -> None:
        """Two disjoint cycle clusters are both reported in cycles list."""
        prog = _make_program([
            ("LOOP-A", [_perform("LOOP-B")]),
            ("LOOP-B", [_perform("LOOP-A")]),
            ("LOOP-C", [_perform("LOOP-D")]),
            ("LOOP-D", [_perform("LOOP-C")]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert len(report.cycles) >= 2
        all_nodes_in_cycles = {n for cycle in report.cycles for n in cycle}
        assert {"LOOP-A", "LOOP-B"}.issubset(all_nodes_in_cycles)
        assert {"LOOP-C", "LOOP-D"}.issubset(all_nodes_in_cycles)

    # ------------------------------------------------------------------
    # Cycle detection: de-duplication
    # ------------------------------------------------------------------

    def test_cycle_deduplication_same_cycle_reported_once(self) -> None:
        """The same cycle found from multiple DFS entry points is only in
        cycles list once."""
        prog = _make_program([
            ("LOOP-A", [_perform("LOOP-B")]),
            ("LOOP-B", [_perform("LOOP-C")]),
            ("LOOP-C", [_perform("LOOP-A")]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # Exactly one unique cycle in the graph
        assert len(report.cycles) == 1
        assert set(report.cycles[0]) == {"LOOP-A", "LOOP-B", "LOOP-C"}

    # ------------------------------------------------------------------
    # Unreachable: empty entry_points
    # ------------------------------------------------------------------

    def test_all_nodes_unreachable_when_entry_points_cleared(self) -> None:
        """After clearing _entry_points and re-running detection, all nodes
        are reported as unreachable."""
        prog = _make_program([
            ("PARA-A", [_perform("PARA-B")]),
            ("PARA-B", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        analyzer.analyze(prog)  # normal run first to populate _nodes/_ordered_procedures

        # Manually clear entry points to simulate the boundary condition
        analyzer._entry_points = []
        analyzer._unreachable_nodes = []
        analyzer._detect_unreachable_nodes()

        assert "PARA-A" in analyzer._unreachable_nodes
        assert "PARA-B" in analyzer._unreachable_nodes

    # ------------------------------------------------------------------
    # Unreachable: entry point not in _nodes (external ENTRY)
    # ------------------------------------------------------------------

    def test_entry_point_not_in_nodes_skipped_gracefully(self) -> None:
        """An ENTRY statement name that has no matching paragraph node is
        skipped without error during reachability analysis."""
        entry = EntryStatement(LOC)
        entry.set_entry_name("'GHOST-ENTRY'")  # No matching paragraph

        prog = _make_program([
            ("MAIN-LOGIC", [entry, _stop_run()]),
            ("ISOLATED", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # GHOST-ENTRY was registered as an entry point but has no node
        assert "GHOST-ENTRY" in report.entry_points
        # ISOLATED is unreachable from MAIN-LOGIC (no edge to it)
        assert "ISOLATED" in report.unreachable_nodes

    # ------------------------------------------------------------------
    # Unreachable: isolated cycle cluster
    # ------------------------------------------------------------------

    def test_unreachable_isolated_cycle_cluster(self) -> None:
        """A mutual cycle disconnected from the entry point is marked
        unreachable, even though a cycle exists among those nodes."""
        prog = _make_program([
            ("MAIN-LOGIC", [_stop_run()]),
            ("CYCLE-A", [_perform("CYCLE-B")]),
            ("CYCLE-B", [_perform("CYCLE-A")]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        assert "CYCLE-A" in report.unreachable_nodes
        assert "CYCLE-B" in report.unreachable_nodes
        # The cycle itself is still detected even though it's unreachable
        assert len(report.cycles) >= 1
        cycle_nodes = {n for c in report.cycles for n in c}
        assert {"CYCLE-A", "CYCLE-B"}.issubset(cycle_nodes)

    # ------------------------------------------------------------------
    # SearchStatement: when_clause dict missing "statements" key
    # ------------------------------------------------------------------

    def test_search_when_clause_missing_statements_key_no_crash(self) -> None:
        """SearchStatement when_clause without 'statements' key falls back to
        empty list and does not crash."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        # Inject a when_clause dict without the "statements" key
        search.when_clauses.append({"condition": "WS-TABLE(IDX) = TARGET"})

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # Should not crash; search_count should still be incremented
        main_node = next(n for n in report.nodes if n.name == "MAIN-LOGIC")
        assert main_node.search_count == 1

    # ------------------------------------------------------------------
    # SearchStatement: at_end_clause as empty list
    # ------------------------------------------------------------------

    def test_search_at_end_clause_empty_list_treated_as_none(self) -> None:
        """SearchStatement with at_end_clause=[] is falsy and recorded as
        has_at_end=False in decisions."""
        from cobolparser.models.statements.control import SearchStatement

        search = SearchStatement(LOC)
        search.set_table_name("WS-TABLE")
        search.add_when_clause("WS-TABLE(IDX) = TARGET", [_continue()])
        search.at_end_clause = []  # Empty list, not None

        prog = _make_program([("MAIN-LOGIC", [search, _stop_run()])])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        main_node = next(n for n in report.nodes if n.name == "MAIN-LOGIC")
        search_decisions = [d for d in main_node.decisions if d["type"] == "SEARCH"]
        assert len(search_decisions) == 1
        assert search_decisions[0]["has_at_end"] is False

    # ------------------------------------------------------------------
    # FlowNode: all boolean exit fields absent from to_dict when False
    # ------------------------------------------------------------------

    def test_flow_node_all_exit_flags_false_omitted_from_dict(self) -> None:
        """FlowNode.to_dict() omits every exit-related boolean when it is
        False (the default)."""
        node = FlowNode("NORMAL", "PARAGRAPH", SourceLocation(1, 1))
        d = node.to_dict()

        for field_name in (
            "has_stop_run",
            "has_goback",
            "has_exit_program",
            "has_return",
            "has_exit_section",
            "has_exit_paragraph",
            "has_exit_perform",
            "is_exit_point",
        ):
            assert field_name not in d, f"Expected {field_name!r} to be absent when False"

    def test_flow_node_is_entry_point_false_omitted(self) -> None:
        """FlowNode.to_dict() omits is_entry_point when False."""
        node = FlowNode("NORMAL", "PARAGRAPH", SourceLocation(1, 1))
        assert "is_entry_point" not in node.to_dict()

    # ------------------------------------------------------------------
    # FlowEdge: perform_type=None omitted from to_dict
    # ------------------------------------------------------------------

    def test_flow_edge_perform_type_none_omitted(self) -> None:
        """FlowEdge.to_dict() omits perform_type when it is None."""
        edge = FlowEdge(
            "A",
            "B",
            FlowEdgeType.PERFORM,
            SourceLocation(1, 1),
            perform_type=None,
        )
        d = edge.to_dict()
        assert "perform_type" not in d

    def test_flow_edge_perform_type_times_included(self) -> None:
        """FlowEdge.to_dict() includes perform_type when set."""
        edge = FlowEdge(
            "A",
            "B",
            FlowEdgeType.PERFORM,
            SourceLocation(1, 1),
            perform_type="TIMES",
        )
        d = edge.to_dict()
        assert d["perform_type"] == "TIMES"

    def test_flow_edge_perform_type_varying_included(self) -> None:
        """FlowEdge.to_dict() includes VARYING perform_type."""
        edge = FlowEdge(
            "A",
            "B",
            FlowEdgeType.PERFORM,
            SourceLocation(1, 1),
            perform_type="VARYING",
        )
        assert edge.to_dict()["perform_type"] == "VARYING"

    # ------------------------------------------------------------------
    # Report: empty new fields serialize to valid JSON
    # ------------------------------------------------------------------

    def test_report_empty_new_fields_serialize_to_json(self) -> None:
        """ProgramFlowReport with empty cycles/unreachable/cancellations
        produces valid JSON with correct zero counts in summary."""
        import json

        report = ProgramFlowReport(program_name="TEST")
        d = report.to_dict()

        json_str = json.dumps(d)
        parsed = json.loads(json_str)

        assert parsed["cycles"] == []
        assert parsed["unreachable_nodes"] == []
        assert parsed["program_cancellations"] == []
        assert parsed["summary"]["cycle_count"] == 0
        assert parsed["summary"]["unreachable_node_count"] == 0
        assert parsed["summary"]["cancellation_count"] == 0

    # ------------------------------------------------------------------
    # _INTERNAL_EDGE_TYPES: CALL edges excluded from cycle/reachability
    # ------------------------------------------------------------------

    def test_call_edges_excluded_from_cycle_detection(self) -> None:
        """A CALL edge from MAIN to EXTERNAL doesn't form a cycle even if
        EXTERNAL has a PERFORM back to MAIN (EXTERNAL is a separate paragraph
        but CALL is external—only internal edges count)."""
        # MAIN calls 'EXTERNAL-PROG' (external); no paragraph named that exists.
        # WORKER only reachable via PERFORM from MAIN.
        prog = _make_program([
            ("MAIN", [_call("'EXTERNAL-PROG'"), _perform("WORKER"), _stop_run()]),
            ("WORKER", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # CALL edge is present but not used for cycle detection
        call_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.CALL]
        assert len(call_edges) == 1

        # No cycle should be found (PERFORM WORKER -> no back edge)
        assert report.cycles == []

    def test_call_dynamic_edges_excluded_from_unreachable_detection(self) -> None:
        """A dynamic CALL edge does not make a paragraph reachable."""
        # MAIN dynamically calls 'HANDLER', but HANDLER is also a paragraph.
        # Since CALL edges are external, HANDLER paragraph is still unreachable
        # from MAIN via internal flow.
        prog = _make_program([
            ("MAIN", [_call("WS-PROG-NAME", is_dynamic=True), _stop_run()]),
            ("HANDLER", [_continue()]),
        ])
        analyzer = ProgramFlowAnalyzer()
        report = analyzer.analyze(prog)

        # Dynamic CALL edge present
        dyn_edges = [e for e in report.edges if e.edge_type == FlowEdgeType.CALL_DYNAMIC]
        assert len(dyn_edges) == 1

        # HANDLER is unreachable via internal flow
        assert "HANDLER" in report.unreachable_nodes
