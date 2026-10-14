"""EXEC CICS RETURN / XCTL / ABEND end the flow of control (issue #392).

dead-code, program-flow and recursion-check all treat them as terminators.
A RETURN or XCTL carrying RESP, RESP2 or NOHANDLE is not one: when the
command fails, execution continues at the next statement.
"""

import pytest

from cobolparser.analysis._cics import cics_terminator_kind
from cobolparser.analysis.dead_code import DeadCodeAnalyzer
from cobolparser.analysis.lint import LintAnalyzer
from cobolparser.analysis.program_flow import FlowEdgeType, ProgramFlowAnalyzer
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer
from cobolparser.parser import parse_cobol

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTERM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(4) VALUE 0.
       01 WS-RESP  PIC S9(8) COMP.
       01 WS-AREA  PIC X(80).
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    result = parse_cobol(_HEADER + body)
    assert result.ast is not None
    return result.ast


def _straight_line(command: str) -> str:
    return f"""\
       MAIN-PARA.
           ADD 1 TO WS-COUNT
           EXEC CICS {command} END-EXEC.
       NEXT-PARA.
           ADD 1 TO WS-COUNT
           GOBACK.
"""


def _first_cics(ast):
    return next(
        s
        for s in ast.get_all_statements()
        if getattr(s, "node_type", "") == "EXEC_CICS"
    )


TERMINATING = [
    ("RETURN", "EXEC CICS RETURN"),
    ("RETURN TRANSID('T001') COMMAREA(WS-AREA)", "EXEC CICS RETURN"),
    ("XCTL PROGRAM('OTHER')", "EXEC CICS XCTL"),
    ("ABEND ABCODE('XXXX')", "EXEC CICS ABEND"),
    ("ABEND ABCODE('XXXX') NOHANDLE", "EXEC CICS ABEND"),
]

CONTINUING = [
    "RETURN RESP(WS-RESP)",
    "RETURN TRANSID('T001') RESP(WS-RESP) RESP2(WS-RESP)",
    "XCTL PROGRAM('OTHER') RESP(WS-RESP)",
    "XCTL PROGRAM('OTHER') NOHANDLE",
    "LINK PROGRAM('OTHER')",
    "SEND MAP('M1') ERASE",
]


class TestCicsTerminatorKind:
    @pytest.mark.parametrize(("command", "kind"), TERMINATING)
    def test_terminating_commands(self, command: str, kind: str) -> None:
        ast = _parse(_straight_line(command))
        assert cics_terminator_kind(_first_cics(ast)) == kind

    @pytest.mark.parametrize("command", CONTINUING)
    def test_commands_that_can_continue(self, command: str) -> None:
        ast = _parse(_straight_line(command))
        assert cics_terminator_kind(_first_cics(ast)) is None

    def test_non_cics_statement(self) -> None:
        ast = _parse(_straight_line("RETURN"))
        stmt = ast.get_all_statements()[0]
        assert cics_terminator_kind(stmt) is None


class TestDeadCode:
    def test_paragraphs_after_return_and_xctl_are_dead(self) -> None:
        ast = _parse("""\
       MAIN-PARA.
           ADD 1 TO WS-COUNT
           EXEC CICS RETURN END-EXEC.
       NEVER-RUN-1.
           ADD 1 TO WS-COUNT
           EXEC CICS XCTL PROGRAM('OTHER') END-EXEC.
       NEVER-RUN-2.
           ADD 1 TO WS-COUNT
           GOBACK.
""")
        dead = {item.name for item in DeadCodeAnalyzer().analyze(ast).dead_items}
        assert dead == {"NEVER-RUN-1", "NEVER-RUN-2"}

    @pytest.mark.parametrize(("command", "_kind"), TERMINATING)
    def test_terminator_blocks_fall_through(self, command: str, _kind: str) -> None:
        dead = DeadCodeAnalyzer().analyze(_parse(_straight_line(command))).dead_items
        assert [item.name for item in dead] == ["NEXT-PARA"]

    @pytest.mark.parametrize("command", CONTINUING)
    def test_continuing_command_falls_through(self, command: str) -> None:
        dead = DeadCodeAnalyzer().analyze(_parse(_straight_line(command))).dead_items
        assert dead == []


class TestProgramFlow:
    def test_no_fall_through_after_return(self) -> None:
        report = ProgramFlowAnalyzer().analyze(_parse(_straight_line("RETURN")))
        assert not [e for e in report.edges if e.edge_type == FlowEdgeType.FALL_THROUGH]
        assert report.unreachable_nodes == ["NEXT-PARA"]
        main = next(n for n in report.nodes if n.name == "MAIN-PARA")
        assert main.has_cics_exit
        assert main.is_exit_point
        assert main.exit_statement_kind == "EXEC CICS RETURN"
        assert main.to_dict()["has_cics_exit"] is True
        assert "MAIN-PARA" in report.exit_points

    def test_return_with_resp_still_falls_through(self) -> None:
        report = ProgramFlowAnalyzer().analyze(
            _parse(_straight_line("RETURN RESP(WS-RESP)"))
        )
        fall = [
            (e.source, e.target)
            for e in report.edges
            if e.edge_type == FlowEdgeType.FALL_THROUGH
        ]
        assert fall == [("MAIN-PARA", "NEXT-PARA")]
        main = next(n for n in report.nodes if n.name == "MAIN-PARA")
        assert not main.has_cics_exit
        assert "has_cics_exit" not in main.to_dict()


_RETRY_LOOP = """\
       P1. EXEC CICS RECEIVE INTO(WS-AREA) RESP(WS-RESP) END-EXEC
           IF WS-RESP NOT = DFHRESP(NORMAL) GO TO P2 END-IF
           EXEC CICS {command} END-EXEC.
       P2. ADD 1 TO WS-COUNT
           GO TO P1.
"""


class TestRecursionCheck:
    def test_pseudo_conversational_retry_loop_has_escape(self) -> None:
        ast = _parse(_RETRY_LOOP.format(command="RETURN TRANSID('T001')"))
        risks = RecursionRiskAnalyzer().analyze(ast).risks
        assert risks
        assert all(r.has_escape and r.severity == "MEDIUM" for r in risks)

    def test_retry_loop_is_not_a_lint_error(self) -> None:
        ast = _parse(_RETRY_LOOP.format(command="RETURN TRANSID('T001')"))
        report = LintAnalyzer(["recursion-check"]).analyze(ast)
        assert report.worst_severity() != "error"

    def test_return_with_resp_is_no_escape(self) -> None:
        ast = _parse(_RETRY_LOOP.format(command="RETURN RESP(WS-RESP)"))
        risks = RecursionRiskAnalyzer().analyze(ast).risks
        assert any(r.severity == "HIGH" and not r.has_escape for r in risks)
