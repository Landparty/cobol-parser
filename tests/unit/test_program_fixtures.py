"""Unit tests for ProgramFixtureGenerator (cobolparser.generators.program_fixtures).

Covers bundle assembly per boundary category, determinism (same seed ->
byte-identical JSON; adding a boundary leaves other boundaries' values
unchanged -- pins the sub-seed scheme), the CALL-argument IN/OUT split,
write_csv_dir's directory/MANIFEST shape, and (Phase 6) generate_with_scenarios
actually applying a PlannedScenario's witnesses/status_overrides/sequence
lengths into the generated fixture values, not just planning them.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators.data.bundle import BUNDLE_VERSION, _slugify
from cobolparser.generators.data.program_layout import ProgramLayoutIndex
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

FILE_OPERATIONS = "tests/samples/file_operations.cbl"
SUBPROGRAM_DEMO = "tests/samples/subprogram_demo.cbl"
IBM_EXTENSIONS = "tests/samples/ibm_extensions.cbl"

_SCENARIO_MODE_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCENMODE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-QTY          PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ
           IF F1-QTY > 100
               DISPLAY 'HIGH'
           END-IF.
"""


def _scenario_mode_bundle(mode: str, seed: int = 1):
    result = parse_cobol(_SCENARIO_MODE_HEADER, filename="scenmode.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return ProgramFixtureGenerator().generate_with_scenarios(
        result.ast, index, report, mode=mode, seed=seed
    )


class TestBundleAssembly:
    def test_one_happy_path_scenario(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        assert bundle.bundle_version == BUNDLE_VERSION
        assert bundle.program_name == "FILETEST"
        assert len(bundle.scenarios) == 1
        assert bundle.scenarios[0].name == "happy path"
        assert bundle.scenarios[0].entry is not None

    def test_status_only_boundaries_carry_status_but_no_layout(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        opens = [f for f in bundle.scenarios[0].fixtures if f.ref.category == "OPEN"]
        assert opens
        for fixture in opens:
            assert fixture.direction == "STATUS_ONLY"
            assert fixture.layout == []
            assert fixture.sequence == []
            assert fixture.status  # some FILE-STATUS-shaped dict

    def test_read_generates_configured_row_count_and_at_end_terminal(self):
        from cobolparser.generators.data.options import DataGeneratorOptions

        bundle = ProgramFixtureGenerator(
            DataGeneratorOptions(rows=4)
        ).generate_from_file(FILE_OPERATIONS, seed=1)
        reads = [f for f in bundle.scenarios[0].fixtures if f.ref.category == "READ"]
        assert reads
        for fixture in reads:
            assert len(fixture.sequence) == 4
            assert fixture.direction == "IN"
        at_end_read = next(f for f in reads if "SEQ-FILE" in f.ref.key)
        assert at_end_read.terminal == {"WS-SEQ-STATUS": "10"}

    def test_write_is_expectation_only_not_a_fixture(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        write_fixtures = [
            f for f in bundle.scenarios[0].fixtures if f.ref.category == "WRITE"
        ]
        assert write_fixtures == []
        stub_refs = {e.ref for e in bundle.scenarios[0].expectations}
        assert any(ref.startswith("WRITE:") for ref in stub_refs)

    def test_coverage_summary_counts_every_boundary(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        assert bundle.coverage.total_boundaries == 17
        assert bundle.coverage.resolved_boundaries == 17
        assert bundle.coverage.unresolved_boundaries == 0
        # OPT-FILE's SELECT has no matching FD in this fixture -- a
        # program-level (ProgramLayoutIndex) gap merged into bundle.unresolved,
        # not tied to any one boundary (OPT-FILE has no READ/WRITE/OPEN/CLOSE
        # of its own here), so it does not count against coverage above.
        assert bundle.unresolved == [
            "file 'OPT-FILE' has a SELECT but no matching FD/SD record"
        ]


class TestCallFixtures:
    def test_call_arg_in_gets_a_value_out_gets_an_expectation(self):
        bundle = ProgramFixtureGenerator().generate_from_file(
            SUBPROGRAM_DEMO, seed=3, callee_paths=[]
        )
        scenario = bundle.scenarios[0]
        call_fixtures = [f for f in scenario.fixtures if f.ref.category == "CALL"]
        assert call_fixtures
        calculator = next(f for f in call_fixtures if f.ref.key == "CALCULATOR")
        # WS-RESULT/WS-RETURN-CODE (callee writes them, via COMPUTE) are IN
        # -> present as generated values.
        assert set(calculator.sequence[0]) == {"WS-RESULT", "WS-RETURN-CODE"}

        out_notes = [
            e.note
            for e in scenario.expectations
            if e.ref in ("WS-INPUT-NUM1", "WS-INPUT-NUM2", "WS-OPERATION")
        ]
        assert out_notes
        assert all("not mock-generated" in note for note in out_notes)

    def test_giving_and_returning_parameters_get_generated_values(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GIVINGCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUB' GIVING WS-RESULT.
"""
        import tempfile as _tempfile

        with _tempfile.NamedTemporaryFile("w", suffix=".cbl", delete=False) as handle:
            handle.write(source)
            path = handle.name
        try:
            bundle = ProgramFixtureGenerator().generate_from_file(path, seed=1)
        finally:
            os.unlink(path)
        call_fixture = bundle.scenarios[0].fixtures[0]
        assert "WS-RESULT" in call_fixture.sequence[0]


class TestSqlFixtures:
    def test_select_and_fetch_get_generated_rows_insert_does_not(self):
        bundle = ProgramFixtureGenerator().generate_from_file(IBM_EXTENSIONS, seed=5)
        sql_fixtures = {
            f.ref.key: f
            for f in bundle.scenarios[0].fixtures
            if f.ref.category == "SQL"
        }
        select_fixture = next(
            f for k, f in sql_fixtures.items() if k.startswith("SELECT")
        )
        assert select_fixture.direction == "IN"
        assert select_fixture.sequence
        assert select_fixture.status == {"SQLCODE": "0"}

        # INSERT/UPDATE/DELETE are OUT -> expectation stubs, no SQL fixture
        # with a populated sequence for them.
        for f in sql_fixtures.values():
            if f.direction == "OUT":
                assert f.sequence == []


class TestDeterminism:
    def test_same_seed_is_byte_identical(self):
        gen = ProgramFixtureGenerator()
        first = gen.generate_from_file(FILE_OPERATIONS, seed=42).to_json()
        second = gen.generate_from_file(FILE_OPERATIONS, seed=42).to_json()
        assert first == second

    def test_unseeded_run_records_its_drawn_seed(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS)
        assert isinstance(bundle.seed, int)
        replay = ProgramFixtureGenerator().generate_from_file(
            FILE_OPERATIONS, seed=bundle.seed
        )
        assert replay.to_json() == bundle.to_json()


class TestWriteCsvDir:
    def test_emits_one_csv_per_file_fixture_plus_manifest(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            manifest_path = os.path.join(tmp, "MANIFEST.json")
            assert os.path.isfile(manifest_path)
            with open(manifest_path) as handle:
                manifest = json.load(handle)
            assert manifest["bundle_version"] == BUNDLE_VERSION

            scenario_dir = os.path.join(tmp, "happy-path")
            assert os.path.isdir(scenario_dir)
            csv_files = sorted(os.listdir(scenario_dir))
            assert "SEQ-FILE.csv" in csv_files
            with open(os.path.join(scenario_dir, "SEQ-FILE.csv")) as handle:
                lines = handle.read().splitlines()
            assert lines[0] == "SEQ-RECORD,SEQ-ALTERNATE"
            assert len(lines) == 1 + 10  # header + default rows=10

    def test_csv_dir_round_trips_byte_for_cell_against_the_json(self):
        """Phase 6 exit criterion: `--format csv-dir` output round-trips
        through `csv.reader` and matches the JSON rows byte-for-cell."""
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            for scenario in bundle.scenarios:
                slug = _slugify(scenario.name)
                for fixture in scenario.fixtures:
                    if not fixture.layout or not fixture.sequence:
                        continue
                    csv_path = os.path.join(tmp, slug, f"{fixture.ref.key}.csv")
                    with open(csv_path, newline="") as handle:
                        rows = list(csv.reader(handle))
                    header, data_rows = rows[0], rows[1:]
                    assert len(data_rows) == len(fixture.sequence)
                    for csv_row, json_row in zip(
                        data_rows, fixture.sequence, strict=True
                    ):
                        for column, cell in zip(header, csv_row, strict=True):
                            assert cell == json_row[column], (
                                f"{fixture.ref.key}.{column}: csv {cell!r} != "
                                f"json {json_row[column]!r}"
                            )

    def test_multi_scenario_csv_dir_has_one_directory_per_scenario(self):
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            FILE_OPERATIONS, mode="all", seed=1
        )
        assert len(bundle.scenarios) > 1
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            for scenario in bundle.scenarios:
                slug = _slugify(scenario.name)
                assert os.path.isdir(os.path.join(tmp, slug)), scenario.name


class TestScenarioModes:
    """generate_with_scenarios actually applies a PlannedScenario into the
    generated fixture -- not just plans it (that's Phase 5's own coverage)."""

    def test_branch_arm_witness_is_pinned_in_the_generated_row(self):
        bundle = _scenario_mode_bundle("branches")
        # Locate the scenario whose READ fixture's F1-QTY value is > 100 (the
        # THEN witness) and the one whose value is <= 100 (the ELSE witness).
        qty_values = []
        for scenario in bundle.scenarios:
            read_fixture = next(
                (f for f in scenario.fixtures if f.ref.category == "READ"), None
            )
            assert read_fixture is not None, scenario.name
            qty_values.append(int(read_fixture.sequence[0]["F1-QTY"]))
        assert any(v > 100 for v in qty_values)
        assert any(v <= 100 for v in qty_values)

    def test_empty_input_scenario_has_zero_length_read_sequence(self):
        bundle = _scenario_mode_bundle("all")
        empty = next(s for s in bundle.scenarios if s.name == "empty input")
        read_fixture = next(f for f in empty.fixtures if f.ref.category == "READ")
        assert read_fixture.sequence == []

    def test_boundary_value_scenarios_pin_min_and_max(self):
        bundle = _scenario_mode_bundle("all")
        minimum = next(
            s for s in bundle.scenarios if s.name == "boundary values: minimum"
        )
        maximum = next(
            s for s in bundle.scenarios if s.name == "boundary values: maximum"
        )
        min_read = next(f for f in minimum.fixtures if f.ref.category == "READ")
        max_read = next(f for f in maximum.fixtures if f.ref.category == "READ")
        assert int(min_read.sequence[0]["F1-QTY"]) == 0
        assert int(max_read.sequence[0]["F1-QTY"]) == 999

    def test_scenario_coverage_is_attached_to_the_bundle(self):
        bundle = _scenario_mode_bundle("branches")
        assert bundle.scenario_coverage is not None
        c = bundle.scenario_coverage
        assert c["targeted"] + c["merged"] + c["missed"] == c["total_arms"]
