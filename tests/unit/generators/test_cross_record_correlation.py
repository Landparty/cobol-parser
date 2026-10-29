"""Cross-record correlation: a branch reached only by a *pair* of records.

``IF TXN-BRANCH = WS-PREV-BRANCH``, where ``MOVE TXN-BRANCH TO
WS-PREV-BRANCH`` runs later in the same paragraph, compares each record
with the one before it. The constraint extractor recognizes the carrier
(`CorrelationConstraint`), the planner pins two rows for it
(`PlannedScenario.row_witnesses`), and verification checks the emitted rows
against the row before. Design:
docs/plans/2026-09-04-cross-record-correlation-design.md.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import (
    ConstraintExtractor,
    CorrelationConstraint,
)
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.data.bundle import BoundaryFixture, Scenario
from cobolparser.generators.scenarios import PlannedScenario, ScenarioPlanner
from cobolparser.generators.verification import verify_scenario

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "correlation" / "BRKRPT.cbl"

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CORR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO F1IN.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-KEY          PIC X(04).
           05  F1-TYPE         PIC X(02).
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
           88  END-OF-FILE     VALUE 'Y'.
"""


def _program(storage: str, body: str, extra: str = "") -> str:
    return (
        _HEAD
        + storage
        + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           READ F1 AT END SET END-OF-FILE TO TRUE END-READ
           PERFORM LOOP-PARA UNTIL END-OF-FILE
           CLOSE F1
           STOP RUN.
       LOOP-PARA.
"""
        + body
        + """\
           READ F1 AT END SET END-OF-FILE TO TRUE END-READ.
"""
        + extra
    )


_PREV = "       01  WS-PREV-KEY         PIC X(04) VALUE SPACES.\n"
_COMPARE = """\
           IF F1-KEY = WS-PREV-KEY
               DISPLAY 'SAME KEY'
           END-IF
"""
_CARRY = "           MOVE F1-KEY TO WS-PREV-KEY\n"


def _analyze(source: str):
    result = parse_cobol(source)
    assert result.success, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    constraints = ConstraintExtractor().extract(result.ast, index, boundaries)
    return result.ast, boundaries, constraints


def _branch(constraints, line_text: str = "IF"):
    (branch,) = [b for b in constraints.branches if b.arms or b.correlations]
    return branch


class TestCarrierDetection:
    def test_recognized(self) -> None:
        _ast, _b, constraints = _analyze(_program(_PREV, _COMPARE + _CARRY))
        branch = _branch(constraints)
        (then,) = branch.correlations["THEN"]
        assert isinstance(then, CorrelationConstraint)
        assert then.field.spec.qualified_name == "F1-REC.F1-KEY"
        assert then.source is not None
        assert then.source.spec.qualified_name == "F1-REC.F1-KEY"
        assert then.carrier == "WS-PREV-KEY"
        assert (then.op, then.offset) == ("eq", -1)
        assert branch.correlations["ELSE"][0].op == "ne"
        assert branch.arms == {"THEN": [], "ELSE": []}
        assert branch.unsupported == []
        data = branch.to_dict()
        assert data["correlations"]["THEN"][0] == {
            "field": "F1-REC.F1-KEY",
            "op": "eq",
            "source": "F1-REC.F1-KEY",
            "carrier": "WS-PREV-KEY",
            "offset": -1,
            "origin": f"IF@{branch.line}",
        }
        assert "previous record's F1-REC.F1-KEY" in then.describe()

    def test_reversed_operands_flip_the_operator(self) -> None:
        compare = """\
           IF WS-PREV-KEY < F1-KEY
               DISPLAY 'RISING'
           END-IF
"""
        _ast, _b, constraints = _analyze(_program(_PREV, compare + _CARRY))
        (then,) = _branch(constraints).correlations["THEN"]
        assert then.op == "gt"
        assert then.field.spec.qualified_name == "F1-REC.F1-KEY"

    def test_with_other_conjuncts(self) -> None:
        compare = """\
           IF F1-KEY = WS-PREV-KEY AND F1-TYPE = '09'
               DISPLAY 'SAME KEY FORCED'
           END-IF
"""
        _ast, _b, constraints = _analyze(_program(_PREV, compare + _CARRY))
        branch = _branch(constraints)
        assert [c.values for c in branch.arms["THEN"]] == [("09",)]
        assert len(branch.correlations["THEN"]) == 1
        # NOT (A AND B) = NOT A OR NOT B: one alternative each.
        assert branch.correlations["ELSE#1"][0].op == "ne"
        assert branch.arms["ELSE#2"][0].op == "ne"
        assert "ELSE#2" not in branch.correlations

    _NOT_A_CARRIER = {
        "moved before the comparison": (_PREV, _CARRY + _COMPARE, ""),
        "moved conditionally": (
            _PREV,
            _COMPARE + """\
           IF F1-TYPE = '05'
               MOVE F1-KEY TO WS-PREV-KEY
           END-IF
""",
            "",
        ),
        "written twice": (
            _PREV,
            _COMPARE + _CARRY + "           MOVE SPACES TO WS-PREV-KEY\n",
            "",
        ),
        "written by another verb": (
            _PREV,
            _COMPARE + _CARRY,
            """\
       OTHER-PARA.
           INITIALIZE WS-PREV-KEY.
""",
        ),
        "a group above it is written": (
            "       01  WS-PREV.\n           05  WS-PREV-KEY     PIC X(04).\n",
            _COMPARE + _CARRY,
            """\
       OTHER-PARA.
           MOVE SPACES TO WS-PREV.
""",
        ),
        "redefined": (
            _PREV + "       01  WS-PREV-ALT REDEFINES WS-PREV-KEY PIC 9(04).\n",
            _COMPARE + _CARRY,
            "",
        ),
        "moved in another paragraph": (
            _PREV,
            _COMPARE + "           PERFORM SAVE-PARA\n",
            """\
       SAVE-PARA.
           MOVE F1-KEY TO WS-PREV-KEY.
""",
        ),
        "set through a level-88": (
            _PREV + "           88  NO-PREV         VALUE SPACES.\n",
            _COMPARE + _CARRY,
            """\
       OTHER-PARA.
           SET NO-PREV TO TRUE.
""",
        ),
        "moved from a working-storage item": (
            _PREV + "       01  WS-OTHER            PIC X(04).\n",
            _COMPARE + "           MOVE WS-OTHER TO WS-PREV-KEY\n",
            "",
        ),
    }

    @pytest.mark.parametrize("case", sorted(_NOT_A_CARRIER))
    def test_not_a_carrier(self, case: str) -> None:
        storage, body, extra = self._NOT_A_CARRIER[case]
        _ast, _b, constraints = _analyze(_program(storage, body, extra))
        compared = [b for b in constraints.branches if "F1-KEY" in str(b.to_dict())]
        assert compared, constraints.to_dict()
        branch = compared[0]
        assert branch.correlations == {}
        assert any(
            "comparison between two resolved fields not supported" in reason
            for reason in branch.unsupported
        ), branch.unsupported


def _plan(source: str):
    ast, boundaries, constraints = _analyze(source)
    flow = ProgramFlowAnalyzer().analyze(ast)
    return ScenarioPlanner().plan(constraints, flow, boundaries, mode="branches")


class TestPlanning:
    def test_two_rows_pinned(self) -> None:
        plan = _plan(_program(_PREV, _COMPARE + _CARRY))
        by_arm = {s.arm_keys[0].rsplit("/", 1)[1]: s for s in plan.scenarios}
        then = by_arm["THEN"]
        key = "F1-REC.F1-KEY"
        assert then.row_witnesses[1][key] == then.row_witnesses[0][key]
        assert len(then.correlations) == 1
        assert "rows 0 and 1 are pinned" in then.intent
        other = by_arm["ELSE"]
        assert other.row_witnesses[1][key] != other.row_witnesses[0][key]
        assert plan.coverage.targeted == 2 and plan.coverage.missed == 0
        assert then.to_dict()["correlations"][0]["carrier"] == "WS-PREV-KEY"

    def test_ordering_comparisons(self) -> None:
        storage = "       01  WS-PREV-N           PIC 9(04) VALUE 0.\n"
        source = _program(
            storage,
            """\
           IF F1-N > WS-PREV-N
               DISPLAY 'RISING'
           END-IF
           MOVE F1-N TO WS-PREV-N
""",
        ).replace(
            "           05  F1-TYPE         PIC X(02).\n",
            "           05  F1-TYPE         PIC X(02).\n           05  F1-N            PIC 9(04).\n",
        )
        plan = _plan(source)
        for scenario in plan.scenarios:
            rows = scenario.row_witnesses
            before, current = int(rows[0]["F1-REC.F1-N"]), int(rows[1]["F1-REC.F1-N"])
            if scenario.arm_keys[0].endswith("/THEN"):
                assert current > before
            else:
                assert current <= before

    def test_unsatisfiable_pair(self) -> None:
        # Nothing an unsigned PIC 9 holds is below zero.
        source = _program(
            "       01  WS-PREV-N           PIC 9(04) VALUE 0.\n",
            """\
           IF F1-N > WS-PREV-N AND F1-N = 0
               DISPLAY 'RISE TO ZERO'
           END-IF
           MOVE F1-N TO WS-PREV-N
""",
        ).replace(
            "           05  F1-TYPE         PIC X(02).\n",
            "           05  F1-TYPE         PIC X(02).\n           05  F1-N            PIC 9(04).\n",
        )
        plan = _plan(source)
        then = [d for d in plan.coverage.details if d.arm_key.endswith("/THEN")]
        assert then[0].status == "missed"
        assert "record before" in (then[0].reason or "")

    def test_never_merged(self) -> None:
        compare = """\
           IF F1-KEY = WS-PREV-KEY AND F1-TYPE = '09'
               DISPLAY 'SAME KEY FORCED'
           END-IF
           IF F1-TYPE = 'ZZ'
               DISPLAY 'ZZ'
           END-IF
"""
        plan = _plan(_program(_PREV, compare + _CARRY))
        correlated = [s for s in plan.scenarios if s.row_witnesses]
        assert correlated
        assert all(len(s.arm_keys) == 1 for s in correlated)

    def test_disjunct_named_for_its_comparison(self) -> None:
        compare = """\
           IF F1-KEY = WS-PREV-KEY AND F1-TYPE = '09'
               DISPLAY 'SAME KEY FORCED'
           END-IF
"""
        plan = _plan(_program(_PREV, compare + _CARRY))
        names = {s.name for s in plan.scenarios}
        assert any("F1-KEY <> previous F1-KEY" in n for n in names), names


class TestVerification:
    def _scenario(self, rows: list[dict[str, str]]):
        _ast, _b, constraints = _analyze(_program(_PREV, _COMPARE + _CARRY))
        (link,) = _branch(constraints).correlations["THEN"]
        spec = link.field.spec
        planned = PlannedScenario(name="s", intent="", correlations=[link])
        fixture = BoundaryFixture(
            ref=None,  # type: ignore[arg-type]
            direction="IN",
            layout=[spec],
            sequence=[{spec.column: r} for r in rows],
        )
        return planned, Scenario(name="s", intent="", fixtures=[fixture])

    def test_satisfied(self) -> None:
        planned, scenario = self._scenario(["AAAA", "BBBB", "BBBB"])
        (verdict,) = verify_scenario(planned, scenario).fields
        assert verdict.status == "satisfied"
        assert verdict.rows == (2,)

    def test_violated(self) -> None:
        planned, scenario = self._scenario(["AAAA", "BBBB", "CCCC"])
        result = verify_scenario(planned, scenario)
        assert result.status == "unverified"
        assert result.fields[0].status == "violated"

    def test_absent(self) -> None:
        planned, _scenario = self._scenario(["AAAA"])
        result = verify_scenario(planned, Scenario(name="s", intent="", fixtures=[]))
        assert result.fields[0].status == "absent"


class TestBundle:
    def test_scenarios_verified(self) -> None:
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(SAMPLE), mode="branches", seed=7
        )
        scenarios = {s.name: s for s in bundle.scenarios}
        then = scenarios["PROCESS-REC: IF@32 THEN"]
        assert then.verification is not None
        assert then.verification["status"] == "verified"
        assert any("previous record" in f["field"] for f in then.verification["fields"])
        rows = [f for f in then.fixtures if f.sequence][0].sequence
        assert rows[0]["TXN-BRANCH"] == rows[1]["TXN-BRANCH"]
        assert rows[1]["TXN-TYPE"] == "09"
        assert bundle.scenario_coverage is not None
        assert bundle.scenario_coverage["missed"] == 0

    def test_deterministic(self) -> None:
        make = ProgramFixtureGenerator().generate_with_scenarios_from_file
        first = make(str(SAMPLE), mode="branches", seed=7).to_json()
        assert make(str(SAMPLE), mode="branches", seed=7).to_json() == first

    @pytest.mark.skipif(shutil.which("cobc") is None, reason="GnuCOBOL not installed")
    def test_reaches_the_paragraph_when_run(self, tmp_path: Path) -> None:
        """The oracle: GnuCOBOL runs BRKRPT on each scenario's rows, and only
        the scenario named for the correlated arm reaches SAME-BRANCH-FORCED."""
        program = tmp_path / "brkrpt"
        subprocess.run(
            ["cobc", "-x", "-std=ibm", "-o", str(program), str(SAMPLE)],
            check=True,
            capture_output=True,
        )
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(SAMPLE), mode="branches", seed=7
        )
        forced = {}
        for scenario in bundle.scenarios:
            rows = [f for f in scenario.fixtures if f.sequence][0].sequence
            (tmp_path / "TXNIN").write_text(
                "".join(
                    r["TXN-BRANCH"].ljust(4)
                    + r["TXN-TYPE"].ljust(2)
                    + r["TXN-AMT"].rjust(5, "0")
                    for r in rows
                )
            )
            out = subprocess.run(
                [str(program)], cwd=tmp_path, capture_output=True, text=True
            ).stdout
            forced[scenario.name] = "FORCED" in out
        assert forced["PROCESS-REC: IF@32 THEN"] is True
        assert forced["happy path"] is False
