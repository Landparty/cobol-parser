"""Regression test: the gen-fixtures initiative's worked example (Phase 9 of
docs/plans/2026-08-02-program-data-generation-*.md) must keep generating the
exact same FixtureBundle JSON for examples/fixtures/FIXTUREDEMO.cbl at seed
42. FIXTUREDEMO.cbl deliberately touches all four boundary categories the
initiative supports end to end -- file I/O (OPEN/READ/CLOSE), SQL (a plain
host-variable SELECT), a static CALL, and a console ACCEPT -- with every
boundary resolving cleanly (zero entries in report.unresolved / bundle.
unresolved), so the checked-in bundle is a clean, fully-worked reference
rather than one carrying a documented gap like examples/custprog/ does over
in the sibling mocky-mock repo.

The checked-in FIXTUREDEMO.bundle.json is also consumed directly by
mocky-mock's own golden test for its generated .cut (see that repo's
examples/fixtures/), so a deliberate change here must be re-copied there in
the same change -- see this file's own module docstring cross-reference and
.okf/generators.md.
"""

from pathlib import Path

from cobolparser.generators import ProgramFixtureGenerator

FIXTURES_DIR = Path(__file__).parent.parent.parent / "examples" / "fixtures"


def test_fixturedemo_bundle_matches_checked_in_golden():
    bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(FIXTURES_DIR / "FIXTUREDEMO.cbl"), mode="happy", seed=42
    )
    golden = (FIXTURES_DIR / "FIXTUREDEMO.bundle.json").read_text(encoding="utf-8")
    assert bundle.to_json() + "\n" == golden


def test_fixturedemo_bundle_is_fully_resolved():
    """The worked example's whole point is a clean, gap-free reference --
    if a future cobolparser change makes any boundary here unresolvable,
    that is a regression in the example's own premise, not just a byte
    diff the golden-comparison test above would already catch."""
    bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(FIXTURES_DIR / "FIXTUREDEMO.cbl"), mode="happy", seed=42
    )
    assert bundle.unresolved == []
    assert bundle.coverage.unresolved_boundaries == 0
    assert bundle.coverage.total_boundaries == bundle.coverage.resolved_boundaries


def test_fixturedemo_bundle_touches_all_four_boundary_categories():
    bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(FIXTURES_DIR / "FIXTUREDEMO.cbl"), mode="happy", seed=42
    )
    categories = {f.ref.category for f in bundle.scenarios[0].fixtures}
    assert categories == {"ACCEPT", "OPEN", "CLOSE", "SQL", "CALL", "READ"}


def test_fixturedemo_bundle_is_deterministic():
    first = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(FIXTURES_DIR / "FIXTUREDEMO.cbl"), mode="happy", seed=42
    )
    second = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(FIXTURES_DIR / "FIXTUREDEMO.cbl"), mode="happy", seed=42
    )
    assert first.to_json() == second.to_json()
