"""Unit tests for ProgramFixtureGenerator (cobolparser.generators.program_fixtures).

Covers bundle assembly per boundary category, determinism (same seed ->
byte-identical JSON; adding a boundary leaves other boundaries' values
unchanged -- pins the sub-seed scheme), the CALL-argument IN/OUT split, and
write_csv_dir's directory/MANIFEST shape.
"""

from __future__ import annotations

import json
import os
import tempfile

from cobolparser.generators.data.bundle import BUNDLE_VERSION
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

FILE_OPERATIONS = "tests/samples/file_operations.cbl"
SUBPROGRAM_DEMO = "tests/samples/subprogram_demo.cbl"
IBM_EXTENSIONS = "tests/samples/ibm_extensions.cbl"


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
