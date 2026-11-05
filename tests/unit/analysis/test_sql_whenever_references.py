"""``EXEC SQL WHENEVER ... GO TO p`` makes ``p`` a branch target (#349).

The precompiler puts a ``GO TO p`` after every SQL statement the directive
covers, so dead-code must count ``p`` as referenced and program flow must
carry an edge into it.
"""

from __future__ import annotations

import pytest

from cobolparser import DeadCodeAnalyzer, LintAnalyzer
from cobolparser.analysis._sql_whenever import whenever_goto_target
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.analysis.program_flow.models import FlowEdgeType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.parser import parse_cobol


def _program(*directives: str, extra: str = "") -> str:
    body = "\n".join(f"           EXEC SQL {d} END-EXEC" for d in directives)
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. WH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
{body}
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           STOP RUN.
       SQL-ERR.
           DISPLAY 'SQL ERROR'
           STOP RUN.
{extra}"""


def _dead(source: str) -> list[str]:
    result = parse_cobol(source)
    assert result.ast is not None
    return [d.name for d in DeadCodeAnalyzer().analyze(result.ast).dead_items]


def _exec_sql(text: str) -> ExecSQLStatement:
    stmt = ExecSQLStatement(SourceLocation(1, 1))
    stmt.set_sql_text(text)
    return stmt


def _whenever_edges(source: str) -> set[tuple[str, str]]:
    result = parse_cobol(source)
    assert result.ast is not None
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    return {
        (e.source, e.target)
        for e in flow.edges
        if e.edge_type is FlowEdgeType.SQL_WHENEVER
    }


class TestDeadCode:
    def test_issue_reproduction_handler_is_live(self) -> None:
        assert _dead(_program("WHENEVER SQLERROR GO TO SQL-ERR")) == []

    @pytest.mark.parametrize(
        "directive",
        [
            "WHENEVER SQLERROR GO TO SQL-ERR",
            "WHENEVER SQLERROR GOTO SQL-ERR",
            "WHENEVER SQLWARNING GO TO SQL-ERR",
            "WHENEVER NOT FOUND GO TO SQL-ERR",
            "WHENEVER NOT   FOUND GOTO :SQL-ERR",
            "WHENEVER SQLERROR GO TO :SQL-ERR",
            "whenever sqlerror go to sql-err",
        ],
    )
    def test_every_condition_and_spelling(self, directive: str) -> None:
        assert _dead(_program(directive)) == []

    def test_continue_references_nothing(self) -> None:
        assert _dead(_program("WHENEVER SQLERROR CONTINUE")) == ["SQL-ERR"]

    def test_without_directive_handler_is_still_dead(self) -> None:
        assert _dead(_program()) == ["SQL-ERR"]

    def test_only_the_named_handler_is_revived(self) -> None:
        extra = """       OTHER-PARA.
           DISPLAY 'NEVER'
           STOP RUN.
"""
        assert _dead(_program("WHENEVER SQLERROR GO TO SQL-ERR", extra=extra)) == [
            "OTHER-PARA"
        ]

    def test_lint_dead_code_rule_is_quiet(self) -> None:
        result = parse_cobol(_program("WHENEVER SQLERROR GO TO SQL-ERR"))
        assert result.ast is not None
        report = LintAnalyzer(["dead-code"]).analyze(result.ast)
        assert report.findings == []


class TestProgramFlow:
    def test_edge_from_directive_paragraph_to_handler(self) -> None:
        source = _program("WHENEVER SQLERROR GO TO SQL-ERR")
        assert _whenever_edges(source) == {("MAIN-PARA", "SQL-ERR")}

    def test_continue_adds_no_edge(self) -> None:
        assert _whenever_edges(_program("WHENEVER SQLERROR CONTINUE")) == set()

    def test_unknown_target_adds_no_edge(self) -> None:
        assert _whenever_edges(_program("WHENEVER SQLERROR GO TO NO-SUCH")) == set()

    def test_handler_is_not_unreachable(self) -> None:
        result = parse_cobol(_program("WHENEVER SQLERROR GO TO SQL-ERR"))
        assert result.ast is not None
        flow = ProgramFlowAnalyzer().analyze(result.ast)
        assert "SQL-ERR" not in flow.unreachable_nodes


class TestWheneverGotoTarget:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("WHENEVER SQLERROR GO TO SQL-ERR", "SQL-ERR"),
            ("WHENEVER NOT FOUND GOTO:NF-PARA", "NF-PARA"),
            ("WHENEVER SQLWARNING CONTINUE", None),
            ("WHENEVER SQLERROR GO TO", None),
        ],
    )
    def test_text_forms(self, text: str, expected: str | None) -> None:
        assert whenever_goto_target(_exec_sql(text)) == expected

    def test_non_whenever_statement(self) -> None:
        assert whenever_goto_target(_exec_sql("SELECT 1 FROM T1")) is None


def _flow_and_dead(source: str) -> tuple[set[tuple[str, str]], list[str], list[str]]:
    result = parse_cobol(source)
    assert result.ast is not None
    flow = ProgramFlowAnalyzer().analyze(result.ast)
    edges = {
        (e.source, e.target)
        for e in flow.edges
        if e.edge_type is FlowEdgeType.SQL_WHENEVER
    }
    dead = [d.name for d in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    return edges, sorted(flow.unreachable_nodes), dead


def _procedures(body: str) -> str:
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. WH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(10).
       PROCEDURE DIVISION.
{body}       SQL-ERR.
           DISPLAY 'SQL ERROR'
           STOP RUN.
"""


class TestCoverageIsSourceOrder:
    """WHENEVER is a precompiler directive: it covers the SQL statements
    after it in source order, and the branch comes from those statements,
    not from the paragraph holding the directive (review of #461)."""

    def test_directive_in_never_performed_setup_paragraph(self) -> None:
        source = _procedures("""       MAIN-PARA.
           PERFORM P1
           STOP RUN.
       SQL-SETUP.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC.
       P1.
           IF A = SPACES
              EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           END-IF
           GOBACK.
""")
        edges, unreachable, dead = _flow_and_dead(source)
        assert edges == {("P1", "SQL-ERR")}
        assert unreachable == ["SQL-SETUP"]
        assert dead == ["SQL-SETUP"]

    def test_sql_before_the_directive_is_not_covered(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           STOP RUN.
""")
        edges, unreachable, dead = _flow_and_dead(source)
        assert edges == set()
        assert unreachable == ["SQL-ERR"]
        assert dead == ["SQL-ERR"]

    def test_continue_switches_the_condition_off(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           STOP RUN.
""")
        edges, _, dead = _flow_and_dead(source)
        assert edges == set()
        assert dead == ["SQL-ERR"]

    def test_other_conditions_stay_in_effect(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL WHENEVER NOT FOUND GO TO SQL-ERR END-EXEC
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           STOP RUN.
""")
        edges, _, dead = _flow_and_dead(source)
        assert edges == {("MAIN-PARA", "SQL-ERR")}
        assert dead == []

    def test_covered_sql_only_in_dead_paragraph(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           STOP RUN.
       OLD-PARA.
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           STOP RUN.
""")
        edges, unreachable, dead = _flow_and_dead(source)
        assert edges == {("OLD-PARA", "SQL-ERR")}
        assert unreachable == ["OLD-PARA", "SQL-ERR"]
        assert dead == ["OLD-PARA", "SQL-ERR"]

    def test_declarations_are_not_covered(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           EXEC SQL DECLARE C1 CURSOR FOR SELECT C1 FROM T1 END-EXEC
           EXEC SQL INCLUDE SQLCA END-EXEC
           STOP RUN.
""")
        edges, _, dead = _flow_and_dead(source)
        assert edges == set()
        assert dead == ["SQL-ERR"]

    def test_one_edge_per_paragraph(self) -> None:
        source = _procedures("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           EXEC SQL SELECT C1 INTO :A FROM T1 END-EXEC
           EXEC SQL SELECT C2 INTO :A FROM T1 END-EXEC
           STOP RUN.
""")
        result = parse_cobol(source)
        assert result.ast is not None
        flow = ProgramFlowAnalyzer().analyze(result.ast)
        assert [
            (e.source, e.target)
            for e in flow.edges
            if e.edge_type is FlowEdgeType.SQL_WHENEVER
        ] == [("MAIN-PARA", "SQL-ERR")]


DGTT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHDGTT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC.
           EXEC SQL
             DECLARE GLOBAL TEMPORARY TABLE SESSION.T1 (C1 INT)
           END-EXEC.
           STOP RUN.
       ERR-PARA.
           DISPLAY 'ERR'.
           STOP RUN.
"""


def test_declare_global_temporary_table_is_covered() -> None:
    """DECLARE GLOBAL TEMPORARY TABLE is executable SQL (it sets SQLCODE),
    so the WHENEVER SQLERROR handler is reached from it, unlike a DCLGEN
    DECLARE TABLE."""
    ast = parse_cobol(DGTT_SOURCE).ast
    assert ast is not None
    assert [d.name for d in DeadCodeAnalyzer().analyze(ast).dead_items] == []
    assert ProgramFlowAnalyzer().analyze(ast).unreachable_nodes == []


class TestDeclareStatementAndVariable:
    """`DECLARE s STATEMENT` / `DECLARE :hv VARIABLE` set no SQLCODE (#830)."""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STMT PIC X(100).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC.
           EXEC SQL DECLARE S1 STATEMENT END-EXEC.
           EXEC SQL DECLARE S2, S3 STATEMENT END-EXEC.
           EXEC SQL DECLARE :WS-STMT VARIABLE CCSID 37 END-EXEC.
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.
           EXEC SQL COMMIT END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'ERR'.
           GOBACK.
"""

    def test_handler_reached_only_through_declarations_is_dead(self) -> None:
        assert _dead(self.SOURCE) == ["ERR-PARA"]
        assert _whenever_edges(self.SOURCE) == set()

    def test_an_executable_statement_still_branches(self) -> None:
        source = self.SOURCE.replace(
            "           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.\n", ""
        )
        assert _dead(source) == []
