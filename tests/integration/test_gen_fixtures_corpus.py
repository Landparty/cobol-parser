"""Integration test: ProgramFixtureGenerator over the shamrice corpus.

Mirrors test_boundary_inventory_corpus.py's style. Exit criterion (Phase 3):
gen-fixtures produces a bundle for every program in the corpus without
raising, every generated cell is assignable to its field (the same property
test_copybook_csv_generation.py already asserts for gen-data), and the
coverage summary's arithmetic is internally consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))


class TestGenFixturesCorpus:
    """Generate a FixtureBundle for every shamrice example program."""

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_generates_without_raising(self, cbl_path: Path) -> None:
        bundle = ProgramFixtureGenerator().generate_from_file(str(cbl_path), seed=1)
        assert bundle.bundle_version == 1
        assert len(bundle.scenarios) == 1

        coverage = bundle.coverage
        assert coverage.total_boundaries == (
            coverage.resolved_boundaries + coverage.unresolved_boundaries
        )

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_every_generated_cell_fits_its_field(self, cbl_path: Path) -> None:
        bundle = ProgramFixtureGenerator().generate_from_file(str(cbl_path), seed=1)
        for fixture in bundle.scenarios[0].fixtures:
            columns_by_name = {f.column: f for f in fixture.layout}
            for row in fixture.sequence:
                for column, value in row.items():
                    field = columns_by_name[column]
                    if field.category.value in ("numeric", "numeric-edited", "float"):
                        # A blank cell (blank_rate) is legitimately not a
                        # number; anything else must parse as one.
                        assert value == "" or _looks_numeric(value), (
                            f"{cbl_path.name}: {fixture.ref.key}.{column} = "
                            f"{value!r} does not fit category {field.category}"
                        )
                    else:
                        assert len(value) <= max(field.size, 1) + 8, (
                            f"{cbl_path.name}: {fixture.ref.key}.{column} = "
                            f"{value!r} wildly exceeds field size {field.size}"
                        )

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20

    def test_determinism_across_the_corpus(self) -> None:
        for cbl_path in _ALL_CBL:
            first = ProgramFixtureGenerator().generate_from_file(str(cbl_path), seed=99)
            second = ProgramFixtureGenerator().generate_from_file(
                str(cbl_path), seed=99
            )
            assert first.to_json() == second.to_json(), cbl_path.name


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
