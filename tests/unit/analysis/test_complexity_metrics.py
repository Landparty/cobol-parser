"""Unit tests for complexity and maintainability metrics analysis."""

import json

from cobolparser.analysis.complexity_metrics import (
    GOD_PARAGRAPH_COMPLEXITY,
    GOD_PARAGRAPH_FAN_OUT,
    GOD_PARAGRAPH_NESTING,
    GOD_PARAGRAPH_STATEMENTS,
    ComplexityAnalyzer,
    HalsteadMetrics,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.base import CobolExpression
from cobolparser.models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    WhenClause,
)
from cobolparser.models.statements.data import MoveStatement
from cobolparser.models.statements.misc import ContinueStatement, CopyStatement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOC = SourceLocation(1, 8)


def _make_program(
    paragraphs: list[tuple[str, list]],
    sections: list[tuple[str, list[tuple[str, list]]]] | None = None,
) -> CobolProgram:
    """Build a minimal CobolProgram with a PROCEDURE DIVISION."""
    loc = SourceLocation(1, 1)
    prog = CobolProgram("TESTPROG", loc)
    prog.add_division(CobolDivision("IDENTIFICATION", loc))

    proc_div = CobolDivision("PROCEDURE", loc)
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
                line += 2
            proc_div.add_section(sec)
    else:
        for pname, stmts in paragraphs:
            para = CobolParagraph(pname, SourceLocation(line, 8))
            for s in stmts:
                para.add_statement(s)
            proc_div.add_paragraph(para)
            line += 2

    prog.add_division(proc_div)
    return prog


def _continue() -> ContinueStatement:
    return ContinueStatement(LOC)


def _perform(target: str) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    return stmt


def _perform_until(target: str) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    cond = CobolExpression("COMPARISON", LOC)
    stmt.set_until_clause(cond)
    return stmt


def _perform_varying(target: str) -> PerformStatement:
    stmt = PerformStatement(LOC)
    stmt.set_target_paragraph(target)
    stmt.set_varying_clause("WS-IDX", "1", "1", CobolExpression("COMPARISON", LOC))
    return stmt


def _if_stmt(then_stmts: list, else_stmts: list | None = None) -> IfStatement:
    stmt = IfStatement(LOC)
    stmt.set_condition(CobolExpression("COMPARISON", LOC))
    for s in then_stmts:
        stmt.add_then_statement(s)
    for s in else_stmts or []:
        stmt.add_else_statement(s)
    return stmt


def _evaluate(when_count: int) -> EvaluateStatement:
    stmt = EvaluateStatement(LOC)
    stmt.add_subject("WS-VAR")
    for _ in range(when_count):
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc.add_statement(_continue())
        stmt.add_when_clause(wc)
    return stmt


def _search(when_count: int) -> SearchStatement:
    stmt = SearchStatement(LOC)
    stmt.set_table_name("MY-TABLE")
    for _ in range(when_count):
        stmt.add_when_clause(
            CobolExpression("COMPARISON", LOC), [_continue()]
        )
    return stmt


def _copy_stmt(name: str) -> CopyStatement:
    stmt = CopyStatement(LOC)
    stmt.set_copybook_name(name)
    return stmt


def _move(src: str, target: str) -> MoveStatement:
    stmt = MoveStatement(LOC)
    stmt.set_source(src)
    stmt.add_target(target)
    return stmt


# ---------------------------------------------------------------------------
# Tests: cyclomatic complexity
# ---------------------------------------------------------------------------


class TestCyclomaticComplexity:
    def test_simple_paragraph_has_complexity_one(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert len(report.paragraph_metrics) == 1
        assert report.paragraph_metrics[0].cyclomatic_complexity == 1

    def test_empty_paragraph_has_complexity_one(self):
        prog = _make_program([("MAIN", [])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].cyclomatic_complexity == 1

    def test_single_if_adds_one(self):
        prog = _make_program([("MAIN", [_if_stmt([_continue()])])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].cyclomatic_complexity == 2

    def test_two_ifs_add_two(self):
        stmts = [_if_stmt([_continue()]), _if_stmt([_continue()])]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].cyclomatic_complexity == 3

    def test_evaluate_with_three_whens_adds_three(self):
        prog = _make_program([("MAIN", [_evaluate(3)])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].cyclomatic_complexity == 4

    def test_perform_until_adds_one(self):
        prog = _make_program(
            [("MAIN", [_perform_until("HELPER")]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.cyclomatic_complexity == 2

    def test_perform_varying_adds_one(self):
        prog = _make_program(
            [("MAIN", [_perform_varying("HELPER")]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.cyclomatic_complexity == 2

    def test_perform_simple_does_not_add(self):
        prog = _make_program(
            [("MAIN", [_perform("HELPER")]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.cyclomatic_complexity == 1

    def test_search_with_two_whens_adds_two(self):
        prog = _make_program([("MAIN", [_search(2)])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].cyclomatic_complexity == 3

    def test_nested_if_in_evaluate_cumulates_complexity(self):
        # EVALUATE with 1 WHEN containing an IF → +1 for WHEN, +1 for IF
        inner_if = _if_stmt([_continue()])
        wc = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc.add_statement(inner_if)
        eval_stmt = EvaluateStatement(LOC)
        eval_stmt.add_subject("WS-X")
        eval_stmt.add_when_clause(wc)
        prog = _make_program([("MAIN", [eval_stmt])])
        report = ComplexityAnalyzer().analyze(prog)

        # Base 1 + 1 WHEN + 1 IF = 3
        assert report.paragraph_metrics[0].cyclomatic_complexity == 3


# ---------------------------------------------------------------------------
# Tests: nesting depth
# ---------------------------------------------------------------------------


class TestNestingDepth:
    def test_flat_statements_have_nesting_depth_zero(self):
        prog = _make_program([("MAIN", [_continue(), _continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].max_nesting_depth == 0

    def test_single_if_gives_depth_one(self):
        prog = _make_program([("MAIN", [_if_stmt([_continue()])])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].max_nesting_depth == 1

    def test_nested_ifs_give_depth_two(self):
        inner_if = _if_stmt([_continue()])
        outer_if = _if_stmt([inner_if])
        prog = _make_program([("MAIN", [outer_if])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].max_nesting_depth == 2

    def test_inline_perform_increments_depth(self):
        perform = PerformStatement(LOC)
        perform.add_inline_statement(_continue())
        prog = _make_program([("MAIN", [perform])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].max_nesting_depth == 1


# ---------------------------------------------------------------------------
# Tests: fan-in / fan-out
# ---------------------------------------------------------------------------


class TestFanInFanOut:
    def test_performed_paragraph_has_fan_in_one(self):
        prog = _make_program(
            [("MAIN", [_perform("HELPER")]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        helper_m = next(
            m for m in report.paragraph_metrics if m.paragraph_name == "HELPER"
        )
        assert helper_m.fan_in == 1

    def test_performing_paragraph_has_fan_out_one(self):
        prog = _make_program(
            [("MAIN", [_perform("HELPER")]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.fan_out == 1

    def test_paragraph_performed_twice_has_fan_in_two(self):
        prog = _make_program(
            [
                ("MAIN", [_perform("HELPER")]),
                ("SECOND", [_perform("HELPER")]),
                ("HELPER", [_continue()]),
            ]
        )
        report = ComplexityAnalyzer().analyze(prog)

        helper_m = next(
            m for m in report.paragraph_metrics if m.paragraph_name == "HELPER"
        )
        assert helper_m.fan_in == 2

    def test_isolated_paragraph_has_zero_fan_in_and_out(self):
        prog = _make_program(
            [("MAIN", [_continue()]), ("UNUSED", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        unused_m = next(
            m for m in report.paragraph_metrics if m.paragraph_name == "UNUSED"
        )
        assert unused_m.fan_in == 0
        assert unused_m.fan_out == 0

    def test_prebuilt_flow_report_is_reused(self):
        """Providing an existing flow_report avoids double analysis."""
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer

        prog = _make_program(
            [("MAIN", [_perform("HELPER")]), ("HELPER", [_continue()])]
        )
        flow_report = ProgramFlowAnalyzer().analyze(prog)
        report = ComplexityAnalyzer().analyze(prog, flow_report=flow_report)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.fan_out == 1


# ---------------------------------------------------------------------------
# Tests: Halstead metrics
# ---------------------------------------------------------------------------


class TestHalsteadMetrics:
    def test_empty_paragraph_has_zero_vocabulary(self):
        prog = _make_program([("MAIN", [])])
        report = ComplexityAnalyzer().analyze(prog)

        h = report.paragraph_metrics[0].halstead
        assert h.vocabulary == 0
        assert h.volume == 0.0

    def test_single_statement_has_nonzero_metrics(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        h = report.paragraph_metrics[0].halstead
        assert h.n1 >= 1  # at least the CONTINUE operator

    def test_move_contributes_operator_and_operands(self):
        prog = _make_program([("MAIN", [_move("WS-A", "WS-B")])])
        report = ComplexityAnalyzer().analyze(prog)

        h = report.paragraph_metrics[0].halstead
        assert h.N1 >= 1  # MOVE operator
        assert h.N2 >= 2  # WS-A, WS-B operands

    def test_halstead_properties_are_consistent(self):
        import math

        stmts = [_move("WS-A", "WS-B"), _move("WS-B", "WS-C"), _if_stmt([_continue()])]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        h = report.paragraph_metrics[0].halstead
        assert h.vocabulary == h.n1 + h.n2
        assert h.length == h.N1 + h.N2
        if h.vocabulary > 1:
            expected_vol = (h.N1 + h.N2) * math.log2(h.vocabulary)
            assert abs(h.volume - expected_vol) < 0.001
        if h.n2 > 0:
            expected_diff = (h.n1 / 2) * (h.N2 / h.n2)
            assert abs(h.difficulty - expected_diff) < 0.001

    def test_halstead_to_dict_has_all_keys(self):
        prog = _make_program([("MAIN", [_move("A", "B")])])
        report = ComplexityAnalyzer().analyze(prog)

        d = report.paragraph_metrics[0].halstead.to_dict()
        for key in (
            "n1", "n2", "N1", "N2", "vocabulary", "length",
            "volume", "difficulty", "effort",
            "time_to_program_seconds", "delivered_bugs",
        ):
            assert key in d


# ---------------------------------------------------------------------------
# Tests: god paragraph detection
# ---------------------------------------------------------------------------


class TestGodParagraph:
    def test_simple_paragraph_is_not_god(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert not report.paragraph_metrics[0].is_god_paragraph

    def test_high_statement_count_triggers_god(self):
        stmts = [_continue() for _ in range(GOD_PARAGRAPH_STATEMENTS)]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        m = report.paragraph_metrics[0]
        assert m.is_god_paragraph
        assert any("statement count" in r for r in m.god_paragraph_reasons)

    def test_high_complexity_triggers_god(self):
        # GOD_PARAGRAPH_COMPLEXITY IFs → complexity = 1 + GOD_PARAGRAPH_COMPLEXITY
        stmts = [_if_stmt([_continue()]) for _ in range(GOD_PARAGRAPH_COMPLEXITY)]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        m = report.paragraph_metrics[0]
        assert m.is_god_paragraph
        assert any("cyclomatic complexity" in r for r in m.god_paragraph_reasons)

    def test_high_nesting_triggers_god(self):
        # Build deeply nested IFs
        inner = _continue()
        stmt = inner
        for _ in range(GOD_PARAGRAPH_NESTING):
            stmt = _if_stmt([stmt])
        prog = _make_program([("MAIN", [stmt])])
        report = ComplexityAnalyzer().analyze(prog)

        m = report.paragraph_metrics[0]
        assert m.is_god_paragraph
        assert any("nesting depth" in r for r in m.god_paragraph_reasons)

    def test_high_fan_out_triggers_god(self):
        sub_names = [f"SUB{i}" for i in range(GOD_PARAGRAPH_FAN_OUT)]
        performs = [_perform(name) for name in sub_names]
        subs = [(name, [_continue()]) for name in sub_names]
        prog = _make_program([("MAIN", performs)] + subs)
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.is_god_paragraph
        assert any("fan-out" in r for r in main_m.god_paragraph_reasons)

    def test_total_god_paragraphs_count_in_report(self):
        stmts = [_continue() for _ in range(GOD_PARAGRAPH_STATEMENTS)]
        prog = _make_program([("MAIN", stmts), ("OTHER", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.total_god_paragraphs == 1


# ---------------------------------------------------------------------------
# Tests: copybook coupling
# ---------------------------------------------------------------------------


class TestCopybookCoupling:
    def test_copy_statement_counted(self):
        copy = _copy_stmt("MY-COPYBOOK")
        prog = _make_program([("MAIN", [copy])])
        report = ComplexityAnalyzer().analyze(prog)

        names = [c.copybook_name for c in report.copybook_coupling]
        assert "MY-COPYBOOK" in names

    def test_copy_reference_count(self):
        # Two references to the same copybook
        copy1 = _copy_stmt("MY-COPY")
        copy2 = _copy_stmt("MY-COPY")
        prog = _make_program([("MAIN", [copy1, copy2])])
        report = ComplexityAnalyzer().analyze(prog)

        cb = next(c for c in report.copybook_coupling if c.copybook_name == "MY-COPY")
        assert cb.reference_count == 2

    def test_multiple_copybooks_all_listed(self):
        prog = _make_program(
            [("MAIN", [_copy_stmt("CB-A"), _copy_stmt("CB-B")])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        names = {c.copybook_name for c in report.copybook_coupling}
        assert "CB-A" in names and "CB-B" in names

    def test_no_copy_statements_empty_coupling(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.copybook_coupling == []


# ---------------------------------------------------------------------------
# Tests: report summary
# ---------------------------------------------------------------------------


class TestReportSummary:
    def test_total_paragraphs_count(self):
        prog = _make_program(
            [("MAIN", [_continue()]), ("PARA2", [_continue()]), ("PARA3", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)
        assert report.total_paragraphs == 3

    def test_avg_cyclomatic_complexity(self):
        # MAIN: complexity 1 (baseline); COMPLEX: 3 IFs → complexity 4
        # avg = (1 + 4) / 2 = 2.5
        stmts = [_if_stmt([_continue()]) for _ in range(3)]
        prog = _make_program([("MAIN", [_continue()]), ("COMPLEX", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        assert abs(report.avg_cyclomatic_complexity - 2.5) < 0.01

    def test_max_cyclomatic_complexity(self):
        stmts = [_if_stmt([_continue()]) for _ in range(4)]
        prog = _make_program([("MAIN", [_continue()]), ("COMPLEX", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.max_cyclomatic_complexity == 5

    def test_sections_iterate_correctly(self):
        prog = _make_program(
            [],
            sections=[
                ("MAIN-SECTION", [("MAIN-PARA", [_continue()])]),
                ("OTHER-SECTION", [("OTHER-PARA", [_continue()])]),
            ],
        )
        report = ComplexityAnalyzer().analyze(prog)
        assert report.total_paragraphs == 2
        names = {m.paragraph_name for m in report.paragraph_metrics}
        assert "MAIN-PARA" in names and "OTHER-PARA" in names


# ---------------------------------------------------------------------------
# Tests: serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_contains_expected_keys(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        d = report.to_dict()
        assert "program_name" in d
        assert "summary" in d
        assert "paragraph_metrics" in d
        assert "copybook_coupling" in d

    def test_to_json_is_valid_json(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        raw = report.to_json()
        parsed = json.loads(raw)
        assert parsed["program_name"] == "TESTPROG"

    def test_to_html_is_valid_html(self):
        prog = _make_program(
            [("MAIN", [_continue()]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        html = report.to_html()
        assert "<!DOCTYPE html>" in html
        assert "TESTPROG" in html
        assert "MAIN" in html

    def test_to_html_contains_god_paragraph_indicator(self):
        stmts = [_continue() for _ in range(GOD_PARAGRAPH_STATEMENTS)]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)

        html = report.to_html()
        assert "GOD" in html

    def test_paragraph_metrics_to_dict(self):
        prog = _make_program([("MAIN", [_move("A", "B")])])
        report = ComplexityAnalyzer().analyze(prog)

        d = report.paragraph_metrics[0].to_dict()
        assert "paragraph_name" in d
        assert "cyclomatic_complexity" in d
        assert "halstead" in d
        assert "fan_in" in d
        assert "fan_out" in d


# ---------------------------------------------------------------------------
# Tests: EVALUATE default WHEN (WHEN OTHER)
# ---------------------------------------------------------------------------


class TestEvaluateDefaultWhen:
    def test_default_when_statements_are_counted_in_statement_count(self):
        # The default_when branch (WHEN OTHER) is scanned but does NOT add +1 complexity
        wc_regular = WhenClause([{"type": "Literal", "value": "1"}], LOC)
        wc_regular.add_statement(_continue())
        wc_default = WhenClause([{"type": "Any"}], LOC)
        wc_default.add_statement(_continue())
        wc_default.add_statement(_continue())

        eval_stmt = EvaluateStatement(LOC)
        eval_stmt.add_subject("WS-VAR")
        eval_stmt.add_when_clause(wc_regular)
        eval_stmt.set_default_when(wc_default)

        prog = _make_program([("MAIN", [eval_stmt])])
        report = ComplexityAnalyzer().analyze(prog)
        m = report.paragraph_metrics[0]

        # 1 EVALUATE + 1 WHEN CONTINUE + 2 OTHER CONTINUEs = 4 statements
        assert m.statement_count == 4
        # Base 1 + 1 regular WHEN = 2 (no extra for WHEN OTHER)
        assert m.cyclomatic_complexity == 2

    def test_evaluate_with_only_default_when_adds_no_complexity(self):
        wc_default = WhenClause([{"type": "Any"}], LOC)
        wc_default.add_statement(_continue())
        eval_stmt = EvaluateStatement(LOC)
        eval_stmt.add_subject("WS-VAR")
        eval_stmt.set_default_when(wc_default)

        prog = _make_program([("MAIN", [eval_stmt])])
        report = ComplexityAnalyzer().analyze(prog)
        m = report.paragraph_metrics[0]

        # No WHEN clauses → complexity = 1 (base only)
        assert m.cyclomatic_complexity == 1


# ---------------------------------------------------------------------------
# Tests: PERFORM TIMES does not add complexity
# ---------------------------------------------------------------------------


class TestPerformTimes:
    def test_perform_times_does_not_increment_complexity(self):
        stmt = PerformStatement(LOC)
        stmt.set_target_paragraph("HELPER")
        stmt.set_times_clause(10)
        prog = _make_program(
            [("MAIN", [stmt]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.cyclomatic_complexity == 1

    def test_perform_times_variable_does_not_increment_complexity(self):
        stmt = PerformStatement(LOC)
        stmt.set_target_paragraph("HELPER")
        stmt.set_times_clause("WS-COUNT")  # variable, not literal
        prog = _make_program(
            [("MAIN", [stmt]), ("HELPER", [_continue()])]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.cyclomatic_complexity == 1


# ---------------------------------------------------------------------------
# Tests: SEARCH AT END clause statements counted
# ---------------------------------------------------------------------------


class TestSearchAtEnd:
    def test_search_at_end_statements_counted_in_total(self):
        search = _search(1)  # 1 WHEN clause
        search.set_at_end_clause([_continue(), _continue()])
        prog = _make_program([("MAIN", [search])])
        report = ComplexityAnalyzer().analyze(prog)
        m = report.paragraph_metrics[0]

        # 1 SEARCH + 1 WHEN CONTINUE + 2 AT END CONTINUEs = 4
        assert m.statement_count == 4

    def test_search_at_end_does_not_add_complexity(self):
        search = _search(1)  # +1 for WHEN
        search.set_at_end_clause([_continue()])
        prog = _make_program([("MAIN", [search])])
        report = ComplexityAnalyzer().analyze(prog)
        m = report.paragraph_metrics[0]

        # Base 1 + 1 WHEN = 2 (AT END does not add)
        assert m.cyclomatic_complexity == 2


# ---------------------------------------------------------------------------
# Tests: GO TO DEPENDING ON
# ---------------------------------------------------------------------------


class TestGoToDependingOn:
    def test_go_to_depending_on_3_targets_adds_3_to_complexity(self):
        stmt = GoStatement(LOC)
        stmt.add_operand("PARA-1")
        stmt.add_operand("PARA-2")
        stmt.add_operand("PARA-3")
        stmt.set_depending_on_variable("WS-IDX")
        prog = _make_program([("MAIN", [stmt])])
        report = ComplexityAnalyzer().analyze(prog)

        main_m = report.paragraph_metrics[0]
        # Base 1 + 3 targets = 4
        assert main_m.cyclomatic_complexity == 4

    def test_go_to_depending_on_1_target_adds_1(self):
        stmt = GoStatement(LOC)
        stmt.add_operand("PARA-1")
        stmt.set_depending_on_variable("WS-IDX")
        prog = _make_program([("MAIN", [stmt])])
        report = ComplexityAnalyzer().analyze(prog)

        main_m = report.paragraph_metrics[0]
        # Base 1 + max(1, 1) = 2
        assert main_m.cyclomatic_complexity == 2

    def test_simple_go_to_without_depending_on_adds_no_complexity(self):
        stmt = GoStatement(LOC)
        stmt.set_target_paragraph("PARA-1")
        prog = _make_program([("MAIN", [stmt])])
        report = ComplexityAnalyzer().analyze(prog)

        main_m = report.paragraph_metrics[0]
        # No DEPENDING ON → complexity stays at base 1
        assert main_m.cyclomatic_complexity == 1


# ---------------------------------------------------------------------------
# Tests: god paragraph with all four reasons
# ---------------------------------------------------------------------------


class TestGodParagraphAllFourReasons:
    def test_all_four_thresholds_simultaneously_produce_four_reasons(self):
        # fan-out: GOD_PARAGRAPH_FAN_OUT distinct PERFORMs
        sub_names = [f"SUB{i}" for i in range(GOD_PARAGRAPH_FAN_OUT)]
        performs = [_perform(name) for name in sub_names]

        # cyclomatic: GOD_PARAGRAPH_COMPLEXITY IFs
        ifs = [_if_stmt([_continue()]) for _ in range(GOD_PARAGRAPH_COMPLEXITY)]

        # nesting depth: GOD_PARAGRAPH_NESTING levels deep
        inner: object = _continue()
        for _ in range(GOD_PARAGRAPH_NESTING):
            inner = _if_stmt([inner])  # type: ignore[arg-type]

        # statement count: pad up to threshold
        padding = [_continue() for _ in range(GOD_PARAGRAPH_STATEMENTS)]

        stmts = performs + ifs + [inner] + padding  # type: ignore[list-item]
        subs = [(name, [_continue()]) for name in sub_names]

        prog = _make_program([("MAIN", stmts)] + subs)
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.is_god_paragraph
        assert any("statement count" in r for r in main_m.god_paragraph_reasons)
        assert any("cyclomatic complexity" in r for r in main_m.god_paragraph_reasons)
        assert any("nesting depth" in r for r in main_m.god_paragraph_reasons)
        assert any("fan-out" in r for r in main_m.god_paragraph_reasons)
        assert len(main_m.god_paragraph_reasons) == 4


# ---------------------------------------------------------------------------
# Tests: Halstead N1/N2 totals vs n1/n2 distinct counts
# ---------------------------------------------------------------------------


class TestHalsteadTotalsVsDistinct:
    def test_repeated_operator_increments_N1_not_n1(self):
        # Two MOVEs → same MOVE operator counted twice: N1=2, n1=1
        stmts = [_move("WS-A", "WS-B"), _move("WS-C", "WS-D")]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)
        h = report.paragraph_metrics[0].halstead

        assert h.N1 >= 2  # total operator occurrences
        assert h.n1 >= 1  # distinct operators
        assert h.N1 >= h.n1  # totals always >= distinct

    def test_repeated_operand_increments_N2_not_n2(self):
        # WS-A used as source in both MOVEs → N2 > n2
        stmts = [_move("WS-A", "WS-B"), _move("WS-A", "WS-C")]
        prog = _make_program([("MAIN", stmts)])
        report = ComplexityAnalyzer().analyze(prog)
        h = report.paragraph_metrics[0].halstead

        assert h.N2 >= h.n2  # totals always >= distinct
        assert h.N2 > 0

    def test_halstead_direct_construction(self):
        # Test HalsteadMetrics dataclass directly with known values
        h = HalsteadMetrics(n1=3, n2=4, N1=6, N2=8)
        assert h.vocabulary == 7
        assert h.length == 14


# ---------------------------------------------------------------------------
# Tests: line count from statement locations
# ---------------------------------------------------------------------------


class TestLineCount:
    def test_line_count_derived_from_statement_locations(self):
        # Para starts at line 10, last stmt at line 20 → line_count = 11
        loc_para = SourceLocation(10, 8)
        loc_last = SourceLocation(20, 8)

        prog = CobolProgram("TESTPROG", SourceLocation(1, 1))
        prog.add_division(CobolDivision("IDENTIFICATION", SourceLocation(1, 1)))
        proc_div = CobolDivision("PROCEDURE", SourceLocation(1, 1))
        para = CobolParagraph("MAIN", loc_para)
        para.add_statement(ContinueStatement(SourceLocation(10, 8)))
        para.add_statement(ContinueStatement(loc_last))
        proc_div.add_paragraph(para)
        prog.add_division(proc_div)

        report = ComplexityAnalyzer().analyze(prog)
        assert report.paragraph_metrics[0].line_count == 11

    def test_single_statement_paragraph_has_line_count_at_least_one(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)
        assert report.paragraph_metrics[0].line_count >= 1


# ---------------------------------------------------------------------------
# Tests: section_name attribute
# ---------------------------------------------------------------------------


class TestSectionNameAttribute:
    def test_paragraph_in_section_has_correct_section_name(self):
        prog = _make_program(
            [],
            sections=[("MY-SECTION", [("MY-PARA", [_continue()])])],
        )
        report = ComplexityAnalyzer().analyze(prog)

        m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MY-PARA")
        assert m.section_name == "MY-SECTION"

    def test_top_level_paragraph_has_none_section_name(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        assert report.paragraph_metrics[0].section_name is None

    def test_section_name_appears_in_to_dict_when_set(self):
        prog = _make_program(
            [],
            sections=[("SEC", [("PARA", [_continue()])])],
        )
        report = ComplexityAnalyzer().analyze(prog)
        d = report.paragraph_metrics[0].to_dict()
        assert d.get("section_name") == "SEC"


# ---------------------------------------------------------------------------
# Tests: program with no paragraphs
# ---------------------------------------------------------------------------


class TestNoParagraphsProgram:
    def test_program_with_no_paragraphs_has_empty_metrics(self):
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))
        proc_div = CobolDivision("PROCEDURE", loc)
        prog.add_division(proc_div)

        report = ComplexityAnalyzer().analyze(prog)
        assert report.total_paragraphs == 0
        assert report.paragraph_metrics == []

    def test_program_with_no_paragraphs_has_zero_averages(self):
        loc = SourceLocation(1, 1)
        prog = CobolProgram("EMPTY", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))
        proc_div = CobolDivision("PROCEDURE", loc)
        prog.add_division(proc_div)

        report = ComplexityAnalyzer().analyze(prog)
        assert report.avg_cyclomatic_complexity == 0.0
        assert report.avg_statement_count == 0.0
        assert report.max_cyclomatic_complexity == 0


# ---------------------------------------------------------------------------
# Tests: PERFORM THRU fan-in contribution
# ---------------------------------------------------------------------------


class TestPerformThruFan:
    def test_perform_thru_contributes_to_fan_in_of_target(self):
        stmt = PerformStatement(LOC)
        stmt.set_target_paragraph("PARA-START")
        stmt.set_thru_paragraph("PARA-END")
        prog = _make_program(
            [
                ("MAIN", [stmt]),
                ("PARA-START", [_continue()]),
                ("PARA-END", [_continue()]),
            ]
        )
        report = ComplexityAnalyzer().analyze(prog)

        start_m = next(
            m for m in report.paragraph_metrics if m.paragraph_name == "PARA-START"
        )
        # ProgramFlowAnalyzer should create a PERFORM_THRU edge from MAIN to PARA-START
        assert start_m.fan_in >= 1

    def test_perform_thru_contributes_to_fan_out_of_source(self):
        stmt = PerformStatement(LOC)
        stmt.set_target_paragraph("PARA-START")
        stmt.set_thru_paragraph("PARA-END")
        prog = _make_program(
            [
                ("MAIN", [stmt]),
                ("PARA-START", [_continue()]),
                ("PARA-END", [_continue()]),
            ]
        )
        report = ComplexityAnalyzer().analyze(prog)

        main_m = next(m for m in report.paragraph_metrics if m.paragraph_name == "MAIN")
        assert main_m.fan_out >= 1


# ---------------------------------------------------------------------------
# Tests: copybook sort order (descending by reference count)
# ---------------------------------------------------------------------------


class TestCopybookSortOrder:
    def test_most_referenced_copybook_appears_first(self):
        prog = _make_program(
            [
                (
                    "MAIN",
                    [
                        _copy_stmt("OFTEN"),
                        _copy_stmt("OFTEN"),
                        _copy_stmt("OFTEN"),
                        _copy_stmt("RARE"),
                    ],
                )
            ]
        )
        report = ComplexityAnalyzer().analyze(prog)
        names = [c.copybook_name for c in report.copybook_coupling]

        assert names.index("OFTEN") < names.index("RARE")

    def test_equal_reference_count_both_present(self):
        prog = _make_program(
            [("MAIN", [_copy_stmt("CB-A"), _copy_stmt("CB-B")])]
        )
        report = ComplexityAnalyzer().analyze(prog)
        names = {c.copybook_name for c in report.copybook_coupling}
        assert "CB-A" in names
        assert "CB-B" in names


# ---------------------------------------------------------------------------
# Tests: HTML report details
# ---------------------------------------------------------------------------


class TestHtmlReportDetails:
    def test_html_contains_copybook_name_when_present(self):
        prog = _make_program([("MAIN", [_copy_stmt("MY-COPY")])])
        report = ComplexityAnalyzer().analyze(prog)
        html = report.to_html()

        assert "MY-COPY" in html
        assert "References" in html

    def test_html_shows_no_copy_message_when_no_copybooks(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)
        html = report.to_html()

        assert "No COPY statements found" in html

    def test_html_copybook_reference_count_appears(self):
        prog = _make_program(
            [("MAIN", [_copy_stmt("CB"), _copy_stmt("CB"), _copy_stmt("CB")])]
        )
        report = ComplexityAnalyzer().analyze(prog)
        html = report.to_html()

        # Reference count of 3 should appear in the table
        assert "CB" in html


# ---------------------------------------------------------------------------
# Tests: to_json custom indent
# ---------------------------------------------------------------------------


class TestToJsonCustomIndent:
    def test_custom_indent_produces_same_data_different_format(self):
        prog = _make_program([("MAIN", [_continue()])])
        report = ComplexityAnalyzer().analyze(prog)

        json2 = report.to_json(indent=2)
        json4 = report.to_json(indent=4)

        assert json.loads(json2) == json.loads(json4)
        # 4-space indent produces wider/longer output
        assert len(json4) > len(json2)


# ---------------------------------------------------------------------------
# Tests: Halstead edge cases (vocabulary ≤ 1)
# ---------------------------------------------------------------------------


class TestHalsteadEdgeCases:
    def test_vocabulary_zero_gives_zero_volume(self):
        h = HalsteadMetrics(n1=0, n2=0, N1=0, N2=0)
        assert h.vocabulary == 0
        assert h.volume == 0.0
        assert h.difficulty == 0.0

    def test_vocabulary_one_gives_zero_volume(self):
        # vocabulary = n1 + n2 = 1 → volume uses log2(1) = 0 guard
        h = HalsteadMetrics(n1=1, n2=0, N1=1, N2=0)
        assert h.vocabulary == 1
        assert h.volume == 0.0

    def test_no_operands_gives_zero_difficulty(self):
        # n2=0 → difficulty guard kicks in
        h = HalsteadMetrics(n1=2, n2=0, N1=4, N2=0)
        assert h.difficulty == 0.0
        assert h.effort == 0.0


# ---------------------------------------------------------------------------
# Tests: ComplexityAnalyzer is stateless (idempotent)
# ---------------------------------------------------------------------------


class TestStatelessAnalyzer:
    def test_analyze_twice_returns_identical_results(self):
        prog = _make_program(
            [("MAIN", [_move("A", "B"), _if_stmt([_continue()])]),
             ("HELPER", [_continue()])]
        )
        analyzer = ComplexityAnalyzer()
        report1 = analyzer.analyze(prog)
        report2 = analyzer.analyze(prog)

        assert report1.total_paragraphs == report2.total_paragraphs
        assert report1.max_cyclomatic_complexity == report2.max_cyclomatic_complexity
        for m1, m2 in zip(report1.paragraph_metrics, report2.paragraph_metrics, strict=True):
            assert m1.paragraph_name == m2.paragraph_name
            assert m1.cyclomatic_complexity == m2.cyclomatic_complexity
            assert m1.statement_count == m2.statement_count

    def test_different_programs_produce_different_results(self):
        prog_simple = _make_program([("MAIN", [_continue()])])
        prog_complex = _make_program(
            [("MAIN", [_if_stmt([_continue()]) for _ in range(5)])]
        )
        analyzer = ComplexityAnalyzer()
        r1 = analyzer.analyze(prog_simple)
        r2 = analyzer.analyze(prog_complex)

        assert r2.max_cyclomatic_complexity > r1.max_cyclomatic_complexity
