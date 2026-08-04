"""Unit tests for ScenarioPlanner (cobolparser.generators.scenarios).

A program with one IF yields >= 2 scenarios whose witnesses differ on the
conditioned field; two disjoint-field IFs merge into one scenario; an
unsatisfiable arm lands in ScenarioCoverage.missed with a reason; the fixed
families (`mode="all"`) add empty-input / error-status / boundary-values
scenarios; coverage accounting is exact (targeted + merged + missed == total).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.scenarios import ScenarioPlanner

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCENTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-QTY          PIC 9(3).
           05  F1-CODE         PIC 9(2).
           05  F1-STATUS       PIC X.
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
"""


def _plan(procedure_body: str, mode: str = "branches"):
    source = _HEADER + procedure_body
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == []
    index = ProgramLayoutIndex.build(result.ast)
    boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    constraint_report = ConstraintExtractor().extract(
        result.ast, index, boundary_report
    )
    flow_report = ProgramFlowAnalyzer().analyze(result.ast)
    plan = ScenarioPlanner().plan(
        constraint_report, flow_report, boundary_report, mode=mode
    )
    return plan, constraint_report, boundary_report


class TestSingleIf:
    def test_then_and_else_are_both_targeted_with_differing_witnesses(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n"
        )
        assert len(plan.scenarios) == 2
        witnesses = [s.witnesses["F1-REC.F1-QTY"] for s in plan.scenarios]
        assert float(witnesses[0]) != float(witnesses[1])
        assert plan.coverage.total_arms == 2
        assert plan.coverage.targeted == 2
        assert plan.coverage.merged == 0
        assert plan.coverage.missed == 0

    def test_coverage_accounting_is_exact(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n"
        )
        c = plan.coverage
        assert c.targeted + c.merged + c.missed == c.total_arms
        assert len(c.details) == c.total_arms


class TestMerging:
    def test_disjoint_field_arms_merge_into_one_scenario(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF\n"
            "           IF F1-CODE = 5\n"
            "               DISPLAY 'FIVE'\n"
            "           END-IF.\n"
        )
        # Four arms total (THEN/ELSE x2); THEN(qty)+THEN(code) touch disjoint
        # fields and should merge, same for the two ELSE arms.
        assert plan.coverage.total_arms == 4
        assert plan.coverage.merged >= 1
        merged_outcomes = [d for d in plan.coverage.details if d.status == "merged"]
        assert merged_outcomes
        target_name = merged_outcomes[0].merged_into
        target = next(s for s in plan.scenarios if s.name == target_name)
        assert "F1-REC.F1-QTY" in target.witnesses
        assert "F1-REC.F1-CODE" in target.witnesses
        assert len(target.arm_keys) == 2


class TestUnsatisfiable:
    def test_contradictory_conjunction_is_missed(self):
        plan, _, _ = _plan(
            "           IF F1-QTY = 5 AND F1-QTY = 6\n"
            "               DISPLAY 'IMPOSSIBLE'\n"
            "           END-IF.\n"
        )
        then_outcome = next(
            d for d in plan.coverage.details if d.arm_key.endswith("/THEN")
        )
        assert then_outcome.status == "missed"
        assert "unsatisfiable" in then_outcome.reason


class TestFixedFamilies:
    def test_all_mode_adds_empty_input_scenario(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n",
            mode="all",
        )
        names = {s.name for s in plan.scenarios}
        assert "empty input" in names
        empty = next(s for s in plan.scenarios if s.name == "empty input")
        assert any(sc.length == 0 for sc in empty.sequence_constraints)

    def test_all_mode_adds_error_status_for_declared_invalid_key_handler(self):
        plan, _, _ = _plan(
            "           READ F1\n"
            "               INVALID KEY DISPLAY 'BAD'\n"
            "           END-READ.\n",
            mode="all",
        )
        error_scenarios = [s for s in plan.scenarios if "INVALID KEY" in s.name]
        assert error_scenarios
        assert error_scenarios[0].status_overrides

    def test_all_mode_adds_boundary_value_scenarios_for_touched_numeric_fields(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n",
            mode="all",
        )
        names = {s.name for s in plan.scenarios}
        assert "boundary values: minimum" in names
        assert "boundary values: maximum" in names
        minimum = next(
            s for s in plan.scenarios if s.name == "boundary values: minimum"
        )
        assert float(minimum.witnesses["F1-REC.F1-QTY"]) == 0

    def test_branches_mode_does_not_add_fixed_families(self):
        plan, _, _ = _plan(
            "           IF F1-QTY > 100\n"
            "               DISPLAY 'HIGH'\n"
            "           END-IF.\n",
            mode="branches",
        )
        names = {s.name for s in plan.scenarios}
        assert "empty input" not in names
        assert not any(n.startswith("boundary values") for n in names)
