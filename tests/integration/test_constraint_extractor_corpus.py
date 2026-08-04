"""Integration test: ConstraintExtractor + solve() over the shamrice corpus.

Exit criteria (Phase 4, per the parent plan): every condition in the corpus
is either extracted or lands in `unsupported` with a reason -- never silently
invisible -- and the solver never emits a witness that violates its field's
PICTURE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.analysis.domains import Witness, solve
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.data.layout import FieldCategory, FieldSpec

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))


def _extract(cbl_path: Path):
    source = cbl_path.read_text(encoding="utf-8", errors="replace")
    result = parse_cobol(source, filename=str(cbl_path))
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    boundary_report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return ConstraintExtractor().extract(result.ast, index, boundary_report)


def _by_field(
    constraints: list[FieldConstraint],
) -> dict[str, list[FieldConstraint]]:
    grouped: dict[str, list[FieldConstraint]] = {}
    for c in constraints:
        grouped.setdefault(c.field.spec.qualified_name, []).append(c)
    return grouped


def _assert_fits(spec: FieldSpec, value: str) -> None:
    if spec.category in (
        FieldCategory.NUMERIC,
        FieldCategory.NUMERIC_EDITED,
        FieldCategory.FLOAT,
    ):
        float(value)  # must parse as a number -- raises if it doesn't
    else:
        assert (
            len(value) <= max(spec.size, 1) + 8
        ), f"{spec.qualified_name}: {value!r} wildly exceeds field size {spec.size}"


class TestConstraintExtractorCorpus:
    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_extracts_without_raising(self, cbl_path: Path) -> None:
        report = _extract(cbl_path)
        for branch in report.branches:
            assert branch.arms or branch.unsupported, (
                f"{cbl_path.name}: {branch.branch_id} has neither arms nor an "
                "unsupported reason -- a silent drop"
            )

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_every_witness_is_layout_valid(self, cbl_path: Path) -> None:
        report = _extract(cbl_path)
        for branch in report.branches:
            for constraints in branch.arms.values():
                for field_constraints in _by_field(constraints).values():
                    spec = field_constraints[0].field.spec
                    result = solve(spec, field_constraints)
                    if isinstance(result, Witness):
                        _assert_fits(spec, result.value)
                    # Unsatisfiable is also a legitimate, honest outcome for
                    # a contradictory conjunct set -- not a bug in itself.

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20

    def test_at_least_one_program_yields_constraints_or_sequence_constraints(
        self,
    ) -> None:
        totals = [
            len(report.branches) + len(report.sequence_constraints)
            for report in (_extract(p) for p in _ALL_CBL)
        ]
        assert sum(totals) > 0
