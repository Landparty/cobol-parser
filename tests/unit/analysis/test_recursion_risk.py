"""Tests for RecursionRiskAnalyzer (recursion_risk.py).

Covers:
- PERFORM_RECURSION cycles (mutual and self) always flagged HIGH severity
- GOTO_LOOP cycles: HIGH when no escape, MEDIUM when an escape route exists
- Self-recursive static CALL statements
- Self-recursive dynamic CALL statements (resolved via VALUE clause)
- Non-recursive programs produce no risks
- Report serialization shape
"""

from cobolparser.analysis.recursion_risk import (
    RecursionRisk,
    RecursionRiskAnalyzer,
    RecursionRiskReport,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import GoStatement, PerformStatement
from cobolparser.models.statements.misc import GobackStatement
from cobolparser.parser import parse_cobol

LOC = SourceLocation(1, 12)


def _make_program(
    paragraphs: list[tuple[str, list]], program_name: str = "TEST-PROG"
) -> CobolProgram:
    loc = SourceLocation(1, 1)
    prog = CobolProgram(program_name, loc)

    id_div = CobolDivision("IDENTIFICATION", loc)
    prog.add_division(id_div)

    proc_div = CobolDivision("PROCEDURE", loc)
    prog.add_division(proc_div)

    line = 10
    for pname, stmts in paragraphs:
        para = CobolParagraph(pname, SourceLocation(line, 8))
        for s in stmts:
            para.add_statement(s)
        proc_div.add_paragraph(para)
        line += 1

    return prog


def _perform(target: str) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    return stmt


def _goto(target: str) -> GoStatement:
    stmt = GoStatement(LOC)
    stmt.set_target_paragraph(target)
    return stmt


def _call(program: str, is_dynamic: bool = False) -> CallStatement:
    stmt = CallStatement(LOC)
    stmt.set_called_program(program, is_dynamic)
    return stmt


def _goback() -> GobackStatement:
    return GobackStatement(LOC)


def _parse(source: str):
    return parse_cobol(source).ast


BOILERPLATE_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELFCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

BOILERPLATE_PROC = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


class TestPerformRecursionRisk:
    def test_mutual_perform_cycle_flagged_high(self) -> None:
        prog = _make_program(
            [
                ("PARA-A", [_perform("PARA-B")]),
                ("PARA-B", [_perform("PARA-A")]),
            ]
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        perform_risks = [r for r in report.risks if r.mechanism == "PERFORM"]
        assert len(perform_risks) == 1
        risk = perform_risks[0]
        assert risk.severity == "HIGH"
        assert set(risk.procedures) == {"PARA-A", "PARA-B"}
        assert risk.has_escape is False

    def test_self_perform_flagged_high(self) -> None:
        prog = _make_program([("LOOP-PARA", [_perform("LOOP-PARA"), _goback()])])
        report = RecursionRiskAnalyzer().analyze(prog)
        perform_risks = [r for r in report.risks if r.mechanism == "PERFORM"]
        assert len(perform_risks) == 1
        assert perform_risks[0].procedures == ["LOOP-PARA"]
        assert perform_risks[0].severity == "HIGH"


class TestGotoLoopRisk:
    def test_goto_cycle_with_no_escape_is_high(self) -> None:
        prog = _make_program(
            [
                ("PARA-A", [_goto("PARA-B")]),
                ("PARA-B", [_goto("PARA-A")]),
            ]
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        goto_risks = [r for r in report.risks if r.mechanism == "GOTO"]
        assert len(goto_risks) == 1
        assert goto_risks[0].severity == "HIGH"
        assert goto_risks[0].has_escape is False

    def test_goto_cycle_with_terminating_paragraph_has_escape(self) -> None:
        """PARA-A can also GOBACK, so the loop isn't unconditionally trapped."""
        prog = _make_program(
            [
                ("PARA-A", [_goto("PARA-B")]),
                ("PARA-B", [_goto("PARA-A"), _goback()]),
            ]
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        goto_risks = [r for r in report.risks if r.mechanism == "GOTO"]
        assert len(goto_risks) == 1
        assert goto_risks[0].severity == "MEDIUM"
        assert goto_risks[0].has_escape is True

    def test_acyclic_program_has_no_goto_or_perform_risks(self) -> None:
        prog = _make_program(
            [
                ("MAIN-LOGIC", [_perform("WORK"), _goback()]),
                ("WORK", [_goback()]),
            ]
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        assert report.risks == []


class TestCallRecursionRisk:
    def test_static_self_call_flagged_high(self) -> None:
        prog = _make_program(
            [("MAIN-PARA", [_call("TEST-PROG"), _goback()])],
            program_name="TEST-PROG",
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        call_risks = [r for r in report.risks if r.mechanism == "CALL"]
        assert len(call_risks) == 1
        assert call_risks[0].severity == "HIGH"
        assert call_risks[0].program == "TEST-PROG"
        assert call_risks[0].is_dynamic is False

    def test_call_to_other_program_is_not_flagged(self) -> None:
        prog = _make_program(
            [("MAIN-PARA", [_call("OTHER-PROG"), _goback()])],
            program_name="TEST-PROG",
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        assert [r for r in report.risks if r.mechanism == "CALL"] == []

    def test_dynamic_self_call_resolved_via_value_clause(self) -> None:
        source = (
            BOILERPLATE_HEADER
            + "       01 TARGET-PROG PIC X(8) VALUE 'SELFCALL'.\n"
            + BOILERPLATE_PROC
            + "           CALL TARGET-PROG.\n"
            + "           STOP RUN.\n"
        )
        ast = _parse(source)
        report = RecursionRiskAnalyzer().analyze(ast)
        call_risks = [r for r in report.risks if r.mechanism == "CALL"]
        assert len(call_risks) == 1
        assert call_risks[0].is_dynamic is True

    def test_dynamic_call_to_other_program_is_not_flagged(self) -> None:
        source = (
            BOILERPLATE_HEADER
            + "       01 TARGET-PROG PIC X(8) VALUE 'OTHERPROG'.\n"
            + BOILERPLATE_PROC
            + "           CALL TARGET-PROG.\n"
            + "           STOP RUN.\n"
        )
        ast = _parse(source)
        report = RecursionRiskAnalyzer().analyze(ast)
        assert [r for r in report.risks if r.mechanism == "CALL"] == []


class TestRecursionRiskReport:
    def test_reuses_precomputed_flow_report(self) -> None:
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer

        prog = _make_program([("LOOP-PARA", [_perform("LOOP-PARA"), _goback()])])
        flow_report = ProgramFlowAnalyzer().analyze(prog)
        report = RecursionRiskAnalyzer().analyze(prog, flow_report=flow_report)
        assert any(r.mechanism == "PERFORM" for r in report.risks)

    def test_to_dict_shape_and_summary_counts(self) -> None:
        prog = _make_program(
            [
                ("PARA-A", [_perform("PARA-B")]),
                ("PARA-B", [_perform("PARA-A")]),
            ]
        )
        d = RecursionRiskAnalyzer().analyze(prog).to_dict()
        assert "risks" in d and "summary" in d
        assert d["summary"]["risk_count"] == len(d["risks"])
        assert d["summary"]["high_severity_count"] == 1
        risk_dict = d["risks"][0]
        assert risk_dict["mechanism"] == "PERFORM"
        assert risk_dict["severity"] == "HIGH"
        assert "explanation" in risk_dict
        assert "procedures" in risk_dict
        assert "program" not in risk_dict

    def test_call_risk_to_dict_omits_has_escape(self) -> None:
        prog = _make_program(
            [("MAIN-PARA", [_call("TEST-PROG"), _goback()])],
            program_name="TEST-PROG",
        )
        report = RecursionRiskAnalyzer().analyze(prog)
        risk_dict = report.risks[0].to_dict()
        assert risk_dict["mechanism"] == "CALL"
        assert "has_escape" not in risk_dict
        assert risk_dict["program"] == "TEST-PROG"
        assert risk_dict["is_dynamic"] is False

    def test_empty_report_defaults(self) -> None:
        report = RecursionRiskReport()
        assert report.risk_count == 0
        assert report.to_dict()["summary"]["risk_count"] == 0

    def test_recursion_risk_dataclass_defaults(self) -> None:
        risk = RecursionRisk(mechanism="CALL", severity="HIGH", explanation="x")
        assert risk.procedures == []
        assert risk.program is None
        assert risk.is_dynamic is False
        assert risk.has_escape is False
