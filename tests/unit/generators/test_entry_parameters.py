"""ProgramFixtureGenerator(entry_parameters=True): a subprogram's own
PROCEDURE DIVISION USING items as a boundary (mocky-mock#275). Its caller
supplies them, so each scenario gets their values, a stub expectation for
every field the program writes back, and branches on them are targeted."""

from __future__ import annotations

import json

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator
from cobolparser.layout.program import ProgramLayoutIndex

CALCSUB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCSUB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE  PIC V999 VALUE .050.
       LINKAGE SECTION.
       01  LK-PARMS.
           05  LK-AMOUNT  PIC 9(7)V99.
           05  LK-TAX     PIC 9(7)V99.
           05  LK-RC      PIC 99.
       PROCEDURE DIVISION USING LK-PARMS.
       0000-MAIN.
           IF LK-AMOUNT = 0
               MOVE 8 TO LK-RC
           ELSE
               COMPUTE LK-TAX = LK-AMOUNT * WS-RATE
               MOVE 0 TO LK-RC
           END-IF
           GOBACK.
"""

NO_USING = CALCSUB.replace(" USING LK-PARMS", "")


def _analyze(source: str):
    ast = parse_cobol(source, "CALCSUB.cbl").ast
    index = ProgramLayoutIndex.build(ast)
    report = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ast, index, report


def _bundle(source: str = CALCSUB, *, mode: str = "branches", on: bool = True):
    ast, index, report = _analyze(source)
    return ProgramFixtureGenerator(entry_parameters=on).generate_with_scenarios(
        ast, index, report, mode=mode, seed=7
    )


def test_off_by_default_keeps_the_bundle_shape():
    bundle = _bundle(on=False)
    assert "entry_parameters" not in bundle.to_json()
    assert [s.name for s in bundle.scenarios] == ["happy path"]


def test_happy_path_gets_parameter_values_and_output_stubs():
    bundle = _bundle(mode="happy")
    (scenario,) = bundle.scenarios
    params = scenario.entry_parameters
    assert params is not None
    assert (params.ref.category, params.ref.key) == ("ENTRY", "CALCSUB")
    assert [spec.qualified_name for spec in params.layout] == [
        "LK-PARMS.LK-AMOUNT",
        "LK-PARMS.LK-TAX",
        "LK-PARMS.LK-RC",
    ]
    assert len(params.sequence) == 1
    stubs = [(e.kind, e.ref) for e in scenario.expectations]
    # LK-AMOUNT is only read: it is an input, not something to assert on.
    assert stubs == [("stub", "LK-PARMS.LK-TAX"), ("stub", "LK-PARMS.LK-RC")]
    payload = json.loads(bundle.to_json())["scenarios"][0]["entry_parameters"]
    assert payload["category"] == "ENTRY" and payload["key"] == "CALCSUB"


def test_branches_on_parameters_are_targeted_and_verified():
    bundle = _bundle(mode="branches")
    by_name = {s.name: s for s in bundle.scenarios}
    then = by_name["0000-MAIN: IF@13 THEN"]
    other = by_name["0000-MAIN: IF@13 ELSE"]
    assert float(then.entry_parameters.sequence[0]["LK-AMOUNT"]) == 0
    assert float(other.entry_parameters.sequence[0]["LK-AMOUNT"]) != 0
    assert then.verification["status"] == "verified"
    assert other.verification["status"] == "verified"
    assert bundle.scenario_coverage["missed"] == 0


def test_same_seed_is_deterministic():
    assert _bundle().to_json() == _bundle().to_json()


def test_a_program_without_using_gets_nothing_extra():
    bundle = _bundle(NO_USING, mode="happy")
    assert bundle.scenarios[0].entry_parameters is None
    assert bundle.scenarios[0].expectations == []


def test_extractor_treats_extra_fed_names_as_boundary_fed():
    ast, index, report = _analyze(CALCSUB)
    plain = ConstraintExtractor().extract(ast, index, report)
    assert plain.branches[0].arms == {}
    fed = ConstraintExtractor().extract(
        ast, index, report, extra_fed_names=["LK-PARMS"]
    )
    assert set(fed.branches[0].arms) == {"THEN", "ELSE"}
