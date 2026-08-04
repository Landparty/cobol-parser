"""Contract tests for the FixtureBundle public API (gen-fixtures, Phase 3).

Pins the JSON shape mockymock's `generate --with-data` (Phase 8) will consume
across the repo boundary: bundle_version, the exported names, and the key
sets of every serialized dataclass. A version bump or key-set change here is
a breaking change to that consumer and must be deliberate.
"""

from __future__ import annotations

import inspect

import pytest

import cobolparser.generators as generators
from cobolparser.generators import (
    BUNDLE_VERSION,
    FixtureBundle,
    ProgramFixtureGenerator,
)

pytestmark = pytest.mark.contract

FILE_OPERATIONS = "tests/samples/file_operations.cbl"

_BUNDLE_KEYS = {
    "bundle_version",
    "program_name",
    "seed",
    "scenarios",
    "layouts",
    "coverage",
    "unresolved",
}
_SCENARIO_KEYS = {
    "name",
    "intent",
    "entry",
    "fixtures",
    "expectations",
    "unconstrained",
}
_FIXTURE_KEYS = {
    "category",
    "key",
    "paragraph",
    "line",
    "direction",
    "layout",
    "sequence",
    "terminal",
    "status",
    "provenance",
    "unresolved",
}
_EXPECTATION_KEYS = {"kind", "ref", "value", "note"}
_COVERAGE_KEYS = {"total_boundaries", "resolved_boundaries", "unresolved_boundaries"}


def _bundle(**kwargs) -> FixtureBundle:
    kwargs.setdefault("seed", 2024)
    return ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, **kwargs)


class TestExportedNames:
    @pytest.mark.parametrize(
        "name",
        [
            "ProgramFixtureGenerator",
            "FixtureBundle",
            "Scenario",
            "BoundaryFixture",
            "Expectation",
            "CoverageSummary",
            "BUNDLE_VERSION",
        ],
    )
    def test_name_is_exported_from_the_generators_package(self, name):
        assert hasattr(generators, name)


class TestBundleVersion:
    def test_current_version_is_1(self):
        assert BUNDLE_VERSION == 1

    def test_generated_bundle_carries_the_current_version(self):
        assert _bundle().bundle_version == BUNDLE_VERSION


class TestGeneratorContract:
    def test_generate_from_file_signature(self):
        sig = inspect.signature(ProgramFixtureGenerator.generate_from_file)
        params = set(sig.parameters) - {"self"}
        assert params == {"path", "copybook_paths", "callee_paths", "seed"}

    def test_generate_signature(self):
        sig = inspect.signature(ProgramFixtureGenerator.generate)
        params = set(sig.parameters) - {"self"}
        assert params == {"ast", "index", "report", "seed"}

    def test_generate_from_file_returns_a_fixture_bundle(self):
        assert isinstance(_bundle(), FixtureBundle)


class TestKeySets:
    def test_bundle_to_dict_keys(self):
        assert set(_bundle().to_dict().keys()) == _BUNDLE_KEYS

    def test_scenario_to_dict_keys(self):
        scenario = _bundle().scenarios[0]
        assert set(scenario.to_dict().keys()) == _SCENARIO_KEYS

    def test_fixture_to_dict_keys(self):
        bundle = _bundle()
        fixture = bundle.scenarios[0].fixtures[0]
        assert set(fixture.to_dict().keys()) == _FIXTURE_KEYS

    def test_expectation_to_dict_keys(self):
        bundle = _bundle()
        expectations = bundle.scenarios[0].expectations
        assert expectations, "fixture must have at least one expectation to test"
        assert set(expectations[0].to_dict().keys()) == _EXPECTATION_KEYS

    def test_coverage_to_dict_keys(self):
        assert set(_bundle().coverage.to_dict().keys()) == _COVERAGE_KEYS


class TestReproducibilityContract:
    def test_a_seed_pins_the_output_exactly(self):
        a = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=555)
        b = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=555)
        assert a.to_json() == b.to_json()

    def test_reported_seed_replays_an_unseeded_run(self):
        first = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS)
        replay = ProgramFixtureGenerator().generate_from_file(
            FILE_OPERATIONS, seed=first.seed
        )
        assert first.to_json() == replay.to_json()
