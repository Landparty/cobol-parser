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
