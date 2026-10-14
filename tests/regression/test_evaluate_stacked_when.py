"""Stacked WHEN phrases share the statements after the last one (#314).

``WHEN 'A' WHEN 'B' PERFORM SET-RATE`` is one arm, taken for either value.
The AST keeps one `WhenClause` per WHEN phrase, so the 'A' clause has no
statements of its own; consumers used to read it as a separate arm that does
nothing. They now go through `EvaluateStatement.when_groups()`.
"""

from __future__ import annotations

from cobolparser import BusinessRuleExtractor, ProgramFlowAnalyzer, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.scenarios import ScenarioPlanner
from cobolparser.models.statements import EvaluateStatement

_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STACKW.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  WS-T            PIC X.
           05  WS-AMT          PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-R                PIC 9(5).
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
           EVALUATE WS-T
             WHEN 'A'
             WHEN 'B'
               PERFORM SET-RATE
             WHEN 'C'
               MOVE 1 TO WS-R
             WHEN OTHER
               MOVE 0 TO WS-R
           END-EVALUATE
           GOBACK.
       SET-RATE.
           COMPUTE WS-R = WS-AMT * 3.
"""


def _ast():
    result = parse_cobol(_PROGRAM, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def _evaluate(ast) -> EvaluateStatement:
    found = ast.find_all_by_type("EVALUATE") or [
        s for s in ast.get_all_statements() if isinstance(s, EvaluateStatement)
    ]
    (stmt,) = [s for s in found if isinstance(s, EvaluateStatement)]
    return stmt


def test_ast_keeps_one_clause_per_when_phrase():
    stmt = _evaluate(_ast())
    # The AST shape is unchanged: three WhenClauses, the first empty.
    assert [len(c.statements) for c in stmt.when_clauses] == [0, 1, 1]
    groups = stmt.when_groups()
    assert [len(g) for g in groups] == [2, 1]
    assert groups[0][-1] is stmt.when_clauses[1]


def test_trailing_empty_whens_form_one_group():
    stmt = _evaluate(_ast())
    stmt.when_clauses[1].stacked = True
    assert [len(g) for g in stmt.when_groups()] == [3]


def _evaluate_body(body: str) -> EvaluateStatement:
    source = (
        _PROGRAM.split("           EVALUATE WS-T")[0]
        + body
        + ("           GOBACK.\n       SET-RATE.\n           CONTINUE.\n")
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None
    return _evaluate(result.ast)


def test_empty_when_whose_body_never_reached_the_ast_is_not_stacked():
    # An unexpanded COPY leaves WHEN 'F' with no statements in the AST, but
    # the source had a body there: 'F' must not inherit 'G's PERFORM.
    stmt = _evaluate_body(
        "           EVALUATE WS-T\n"
        "             WHEN 'F'\n"
        "               COPY HANDLEF.\n"
        "             WHEN 'G'\n"
        "               PERFORM SET-RATE\n"
        "           END-EVALUATE\n"
    )
    assert [len(c.statements) for c in stmt.when_clauses] == [0, 1]
    assert [c.stacked for c in stmt.when_clauses] == [False, False]
    assert [len(g) for g in stmt.when_groups()] == [1, 1]


def test_unexpanded_copy_on_the_when_line_is_not_stacked():
    stmt = _evaluate_body(
        "           EVALUATE WS-T\n"
        "             WHEN 'F' COPY HANDLEF.\n"
        "             WHEN 'G'\n"
        "               PERFORM SET-RATE\n"
        "           END-EVALUATE\n"
    )
    assert [len(g) for g in stmt.when_groups()] == [1, 1]


def test_unexpanded_copy_elsewhere_does_not_break_a_real_stack():
    stmt = _evaluate_body(
        "           COPY OTHERCP.\n"
        "           EVALUATE WS-T\n"
        "             WHEN 'A'\n"
        "             WHEN 'B'\n"
        "               PERFORM SET-RATE\n"
        "             WHEN 'C'\n"
        "               COPY HANDLEC.\n"
        "           END-EVALUATE\n"
    )
    assert [len(g) for g in stmt.when_groups()] == [2, 1]


def test_empty_when_before_when_other_is_not_stacked():
    stmt = _evaluate_body(
        "           EVALUATE WS-T\n"
        "             WHEN 'A'\n"
        "             WHEN OTHER\n"
        "               PERFORM SET-RATE\n"
        "           END-EVALUATE\n"
    )
    assert [c.stacked for c in stmt.when_clauses] == [False]
    assert [len(g) for g in stmt.when_groups()] == [1]


def test_parser_marks_only_the_stacked_phrase():
    stmt = _evaluate(_ast())
    assert [c.stacked for c in stmt.when_clauses] == [True, False, False]


def test_business_rules_reads_one_arm_for_the_stack():
    report = BusinessRuleExtractor().analyze(_ast())
    decision = next(r for r in report.rules if r.kind == "decision")
    labels = [(b.label, b.condition) for b in decision.branches]
    assert labels[0] == ("WHEN", "WS-T = 'A' OR WS-T = 'B'")
    assert labels[1] == ("WHEN", "WS-T = 'C'")
    assert labels[2][0] == "WHEN OTHER"
    assert "NOT (WS-T = 'A')" in labels[2][1]
    assert "PERFORM SET-RATE" in decision.branches[0].actions[0].text
    calculation = next(r for r in report.rules if r.kind == "calculation")
    assert calculation.reached_via == ["BR-001 WHEN WS-T = 'A' OR WS-T = 'B'"]


def test_program_flow_has_one_arm_owning_the_perform():
    flow = ProgramFlowAnalyzer().analyze(_ast())
    (branch,) = flow.branch_nodes
    arms = [(a.arm_id.rsplit("__", 1)[1], a.label) for a in branch.arms]
    assert arms == [
        ("WHEN_1", "WHEN A / WHEN B"),
        ("WHEN_2", "WHEN C"),
        ("WHEN_OTHER", "WHEN OTHER"),
    ]
    assert branch.arms[0].nested_call_targets == ["SET-RATE"]


def _constraints(ast):
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ConstraintExtractor().extract(ast, index, boundaries), boundaries


def test_constraints_split_the_stack_into_disjuncts_of_one_arm():
    report, _ = _constraints(_ast())
    (branch,) = report.branches
    arms = {k: [(c.op, c.negated, c.values) for c in v] for k, v in branch.arms.items()}
    assert sorted(arms) == ["WHEN_1#1", "WHEN_1#2", "WHEN_2", "WHEN_OTHER"]
    assert arms["WHEN_1#1"][0][2] == ("A",)
    assert arms["WHEN_1#2"][0][2] == ("B",)
    # WHEN 'C' must falsify both phrases of the stack before it.
    assert len(arms["WHEN_2"]) == 3
    # WHEN OTHER excludes all three values.
    assert arms["WHEN_OTHER"] == [("not_in_set", False, ("A", "B", "C"))]


def test_scenario_coverage_counts_the_stack_once():
    ast = _ast()
    report, boundaries = _constraints(ast)
    flow = ProgramFlowAnalyzer().analyze(ast)
    plan = ScenarioPlanner().plan(report, flow, boundaries, mode="branches")
    keys = sorted(k.rsplit("/", 1)[1] for s in plan.scenarios for k in s.arm_keys)
    assert {"WHEN_1#1", "WHEN_1#2", "WHEN_2", "WHEN_OTHER"} <= set(keys)
    names = [s.name for s in plan.scenarios]
    assert any("WHEN A / WHEN B" in n for n in names), names
