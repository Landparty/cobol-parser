"""Tests for program flow analysis."""

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
