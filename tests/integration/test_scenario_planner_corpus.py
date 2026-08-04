"""Integration test: ScenarioPlanner over the shamrice corpus.

Exit criteria (Phase 5, per the parent plan): the "fully test" claim is
measurable -- coverage accounting is exact (targeted + merged + missed ==
total) for every program, and every scenario's witnesses are already
PICTURE-valid (they came from `domains.solve()`, never re-validated here).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.scenarios import ScenarioPlanner

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))


def _plan(cbl_path: Path, mode: str):
    source = cbl_path.read_text(encoding="utf-8", errors="replace")
    result = parse_cobol(source, filename=str(cbl_path))
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    constraint_report = ConstraintExtractor().extract(
        result.ast, index, boundary_report
    )
    flow_report = ProgramFlowAnalyzer().analyze(result.ast)
    return ScenarioPlanner().plan(
        constraint_report, flow_report, boundary_report, mode=mode
    )


class TestScenarioPlannerCorpus:
    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    @pytest.mark.parametrize("mode", ["branches", "all"])
    def test_coverage_accounting_is_exact(self, cbl_path: Path, mode: str) -> None:
        plan = _plan(cbl_path, mode)
        c = plan.coverage
        assert c.targeted + c.merged + c.missed == c.total_arms
        assert len(c.details) == c.total_arms
        for detail in c.details:
            if detail.status == "missed":
                assert detail.reason, f"{cbl_path.name}: missed arm with no reason"
            if detail.status == "merged":
                assert detail.merged_into, f"{cbl_path.name}: merged arm with no target"

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20

    def test_at_least_one_program_produces_scenarios(self) -> None:
        totals = [len(_plan(p, "all").scenarios) for p in _ALL_CBL]
        assert sum(totals) > 0
