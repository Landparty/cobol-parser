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
from pathlib import Path
from unittest.mock import patch

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators.data.bundle import BUNDLE_VERSION, _slugify
from cobolparser.generators.data.errors import ProgramLayoutError
from cobolparser.generators.data.program_layout import ProgramLayoutIndex
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

# Resolved relative to this file rather than the process cwd: cibuildwheel's
# test-command runs pytest against the installed wheel from a directory that
# isn't the repo root, so a cwd-relative "tests/samples/..." string silently
# resolves to nothing there even though it works under `pytest tests/`.
_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

FILE_OPERATIONS = str(_SAMPLES_DIR / "file_operations.cbl")
SUBPROGRAM_DEMO = str(_SAMPLES_DIR / "subprogram_demo.cbl")
IBM_EXTENSIONS = str(_SAMPLES_DIR / "ibm_extensions.cbl")

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

    def test_manifest_sequence_stays_a_list_not_a_hint_string(self):
        """A consumer that runs MANIFEST.json through the same deserializer
        as a real bundle (a reasonable thing to try, since the top-level
        shape otherwise matches) must not silently iterate a hint string
        character-by-character in place of real rows -- `sequence`'s type
        must match the normal bundle schema (always a list) everywhere in
        the manifest, never a "see <slug>/" string. The path hint lives in
        its own `csv_path` key instead, correctly `None` for a fixture that
        got no CSV written for it (STATUS_ONLY/no-sequence boundaries)."""
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            with open(os.path.join(tmp, "MANIFEST.json")) as handle:
                manifest = json.load(handle)

            wrote_any_csv_path = False
            for scenario, scenario_dict in zip(
                bundle.scenarios, manifest["scenarios"], strict=True
            ):
                slug = _slugify(scenario.name)
                for fixture, fixture_dict in zip(
                    scenario.fixtures, scenario_dict["fixtures"], strict=True
                ):
                    assert fixture_dict["sequence"] == []
                    if fixture.layout and fixture.sequence:
                        assert (
                            fixture_dict["csv_path"] == f"{slug}/{fixture.ref.key}.csv"
                        )
                        assert os.path.isfile(
                            os.path.join(tmp, fixture_dict["csv_path"])
                        )
                        wrote_any_csv_path = True
                    else:
                        assert fixture_dict["csv_path"] is None
            assert wrote_any_csv_path  # the assertions above weren't vacuous

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

    def _call_literal_bundle(self, literal: str):
        """A program whose only fixture-worthy boundary is a static CALL
        with an attacker-controlled literal as its program name -- the
        literal becomes the boundary key untouched (see
        boundary_inventory.py's `_classify_call`)."""
        source = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLKEY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL '{literal}' GIVING WS-RESULT.
"""
        with tempfile.NamedTemporaryFile("w", suffix=".cbl", delete=False) as handle:
            handle.write(source)
            path = handle.name
        try:
            return ProgramFixtureGenerator().generate_from_file(path, seed=1)
        finally:
            os.unlink(path)

    def test_call_key_with_absolute_path_does_not_escape_output_dir(self):
        bundle = self._call_literal_bundle("/tmp/pwned-oob")
        target = os.path.join(os.sep, "tmp", "pwned-oob.csv")
        existed_before = os.path.isfile(target)
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            # Nothing escaped into the absolute path the literal names.
            assert os.path.isfile(target) == existed_before
            # The fixture still got written -- flattened into scenario_dir.
            scenario_dir = os.path.join(tmp, "happy-path")
            written = os.listdir(scenario_dir)
            assert any(name.endswith(".csv") for name in written)
            for name in written:
                assert os.sep not in name.removesuffix(".csv")
                assert "/" not in name

    def test_call_key_with_traversal_does_not_escape_output_dir(self):
        bundle = self._call_literal_bundle("../../../../tmp/pwned-traversal")
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            scenario_dir = os.path.join(tmp, "happy-path")
            written = os.listdir(scenario_dir)
            assert any(name.endswith(".csv") for name in written)
            for name in written:
                # No path separator survives sanitization, so the name is
                # necessarily a single component -- any ".." substrings left
                # over (e.g. ".._.._tmp_pwned-traversal.csv") are inert.
                assert "/" not in name
                assert os.sep not in name
            # Nothing was written outside the requested output tree.
            for root, _dirs, files in os.walk(tmp):
                for f in files:
                    full = os.path.abspath(os.path.join(root, f))
                    assert full.startswith(
                        os.path.abspath(tmp) + os.sep
                    ) or full == os.path.abspath(os.path.join(tmp, "MANIFEST.json"))

    def test_manifest_csv_path_matches_the_sanitized_filename_on_disk(self):
        bundle = self._call_literal_bundle("/tmp/pwned-oob")
        with tempfile.TemporaryDirectory() as tmp:
            bundle.write_csv_dir(tmp)
            with open(os.path.join(tmp, "MANIFEST.json")) as handle:
                manifest = json.load(handle)
            csv_paths = [
                fixture["csv_path"]
                for scenario in manifest["scenarios"]
                for fixture in scenario["fixtures"]
                if fixture["csv_path"] is not None
            ]
            assert csv_paths
            for rel_path in csv_paths:
                assert os.path.isfile(os.path.join(tmp, rel_path))


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


class TestTerminalStatusFieldResolution:
    """Regression coverage for a bug the mockymock Phase 8 integration
    uncovered: `terminal`'s field name used to fall back to the literal
    string "FILE-STATUS" whenever a boundary had no resolvable FILE STATUS
    field, instead of mirroring `_status_dict`'s safer (and pre-existing)
    two-step resolution (`boundary.status_field`, then
    `index.file_facts(...)`) and giving up with `None` only when both fail.
    A consumer that spliced that placeholder in as a literal MOVE target
    (exactly what mockymock's `.cut` scaffolder does) would generate COBOL
    that fails to compile, since "FILE-STATUS" is not a real data-name in
    the target program."""

    def test_terminal_is_none_not_a_placeholder_when_no_status_field_exists(self):
        # F1 (_SCENARIO_MODE_HEADER) has an AT END handler but declares no
        # FILE STATUS clause at all -- there is truly nothing to name.
        bundle = _scenario_mode_bundle("happy")
        read_fixture = next(
            f for f in bundle.scenarios[0].fixtures if f.ref.category == "READ"
        )
        assert read_fixture.terminal is None

    def test_terminal_resolves_the_real_declared_status_field(self):
        # SEQ-FILE (tests/samples/file_operations.cbl) declares
        # FILE STATUS IS WS-SEQ-STATUS and has a READ ... AT END -- terminal
        # must name that real field, not a placeholder.
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        read_fixture = next(
            (
                f
                for f in bundle.scenarios[0].fixtures
                if f.ref.category == "READ" and f.ref.key == "SEQ-FILE"
            ),
            None,
        )
        assert read_fixture is not None
        assert read_fixture.terminal == {"WS-SEQ-STATUS": "10"}


class TestTier1CallCountExpectations:
    """Phase 7 tier 1 (structural): call_count is derivable exactly from a
    scenario's own generated sequence, so it is emitted for every boundary
    that actually got a fixture -- never a guess, never absent when it could
    be exact."""

    def test_status_only_boundary_gets_call_count_of_one(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        opens = [
            e
            for e in bundle.scenarios[0].expectations
            if e.kind == "call_count" and e.ref.startswith("OPEN:")
        ]
        assert opens
        assert all(e.value == 1 for e in opens)

    def test_read_with_at_end_handler_counts_rows_plus_one(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        seq_file_read = next(
            f
            for f in bundle.scenarios[0].fixtures
            if f.ref.category == "READ" and f.ref.key == "SEQ-FILE"
        )
        assert seq_file_read.terminal is not None
        expectation = next(
            e
            for e in bundle.scenarios[0].expectations
            if e.kind == "call_count" and e.ref == "READ:SEQ-FILE"
        )
        assert expectation.value == len(seq_file_read.sequence) + 1 == 11

    def test_read_without_at_end_handler_counts_rows_only(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        # IDX-FILE has two distinct READ boundaries: a keyed random read (no
        # AT END, INVALID KEY only) and a NEXT RECORD read (has AT END) --
        # only the former should have no "+1".
        idx_reads = [
            f
            for f in bundle.scenarios[0].fixtures
            if f.ref.category == "READ" and f.ref.key == "IDX-FILE"
        ]
        no_at_end = next(f for f in idx_reads if f.terminal is None)
        expectation = next(
            e
            for e in bundle.scenarios[0].expectations
            if e.kind == "call_count"
            and e.ref == "READ:IDX-FILE"
            and e.value == len(no_at_end.sequence)
        )
        assert expectation.value == 10

    def test_call_boundary_gets_call_count_of_one(self):
        bundle = ProgramFixtureGenerator().generate_from_file(
            SUBPROGRAM_DEMO, seed=3, callee_paths=[]
        )
        calculator_count = next(
            e
            for e in bundle.scenarios[0].expectations
            if e.kind == "call_count" and e.ref == "CALL:CALCULATOR"
        )
        assert calculator_count.value == 1

    def test_out_boundary_gets_no_call_count_expectation(self):
        bundle = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        write_expectations = [
            e for e in bundle.scenarios[0].expectations if e.ref.startswith("WRITE:")
        ]
        assert write_expectations
        assert all(e.kind == "stub" for e in write_expectations)

    def test_empty_input_scenario_call_count_is_one_not_zero(self):
        # F1 (see _SCENARIO_MODE_HEADER) declares no FILE STATUS clause, so
        # read_fixture.terminal is correctly None here (nothing to name in
        # the dict) -- but the boundary still has an AT END handler, so the
        # READ is genuinely invoked once (the call that hits end-of-file)
        # even with a zero-length sequence. call_count must count that
        # invocation regardless of whether a status field could be named.
        bundle = _scenario_mode_bundle("all")
        empty = next(s for s in bundle.scenarios if s.name == "empty input")
        read_fixture = next(f for f in empty.fixtures if f.ref.category == "READ")
        assert read_fixture.sequence == []
        assert read_fixture.terminal is None
        expectation = next(
            e for e in empty.expectations if e.kind == "call_count" and "F1" in e.ref
        )
        assert expectation.value == 1

    def test_happy_mode_and_branch_modes_both_get_call_count(self):
        # Tier 1 is not gated on mode -- generate_with_scenarios(mode="happy")
        # delegates to generate() unchanged, so it must carry the exact same
        # call_count expectations, not a mode-specific subset.
        happy = ProgramFixtureGenerator().generate_from_file(FILE_OPERATIONS, seed=1)
        via_scenarios = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            FILE_OPERATIONS, mode="happy", seed=1
        )
        assert happy.to_json() == via_scenarios.to_json()
        assert any(e.kind == "call_count" for e in happy.scenarios[0].expectations)


_TIER2_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TIER2TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-QTY               PIC 9(3).
       01  WS-DOUBLE            PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-QTY.
           MULTIPLY WS-QTY BY 2 GIVING WS-DOUBLE.
           DISPLAY WS-DOUBLE.
           STOP RUN.
"""


def _tier2_bundle(seed: int = 7):
    result = parse_cobol(_TIER2_HEADER, filename="tier2test.cbl")
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return ProgramFixtureGenerator().generate(result.ast, index, report, seed=seed)


class TestTier2FieldEqualsExpectations:
    """Phase 7 tier 2: ConstantFolder wired into the generator, seeded from
    each scenario's own single-invocation mocked inputs."""

    def test_field_equals_expectation_matches_the_mocked_input(self):
        bundle = _tier2_bundle(seed=7)
        scenario = bundle.scenarios[0]
        accept_fixture = next(
            f for f in scenario.fixtures if f.ref.category == "ACCEPT"
        )
        qty = int(accept_fixture.sequence[0]["WS-QTY"])
        expectation = next(e for e in scenario.expectations if e.kind == "field_equals")
        assert expectation.ref == "WS-DOUBLE"
        assert expectation.value == str(qty * 2)
        assert "mock-supplied" in expectation.note

    def test_field_equals_is_reproducible_for_the_same_seed(self):
        a = _tier2_bundle(seed=42)
        b = _tier2_bundle(seed=42)
        assert a.to_json() == b.to_json()

    def test_read_boundary_is_never_seeded_for_tier2(self):
        # A multi-row READ sequence has no single representative value, so
        # it must never seed the fold -- a bare DISPLAY of the READ record
        # with no intervening MOVE would only produce a field_equals if the
        # (wrong) mock-generated row leaked in as a seed.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READNOFOLD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-QTY               PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1.
           DISPLAY F1-QTY.
           STOP RUN.
"""
        result = parse_cobol(source, filename="readnofold.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=1)
        assert not any(
            e.kind == "field_equals" for e in bundle.scenarios[0].expectations
        )


_CALLER_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLERPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VAL               PIC 9(5).
       01  WS-DYNAMIC-NAME      PIC X(8) VALUE 'EXTCALC'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'EXTCALC' USING WS-VAL
           CALL WS-DYNAMIC-NAME USING WS-VAL
           STOP RUN.
"""

_CALLEE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTCALC.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-VAL                PIC 9(5).
       PROCEDURE DIVISION USING LK-VAL.
       MAIN-PARA.
           MOVE 99 TO LK-VAL
           GOBACK.
"""


def _parsed_caller():
    result = parse_cobol(_CALLER_SOURCE, filename="callerprog.cbl")
    assert result.ast is not None, result.errors
    return result.ast


class TestCalleeResolution:
    """Covers ProgramFixtureGenerator._resolve_callees / _find_callee_file --
    the --callee-path file lookup used when a static CALL target isn't a
    contained program in the same compilation unit."""

    def test_find_callee_file_matches_exact_name(self, tmp_path):
        callee_path = tmp_path / "EXTCALC.cbl"
        callee_path.write_text(_CALLEE_SOURCE)
        found = ProgramFixtureGenerator._find_callee_file("EXTCALC", [str(tmp_path)])
        assert found == str(callee_path)

    def test_find_callee_file_falls_back_to_lowercase_and_alt_extensions(
        self, tmp_path
    ):
        callee_path = tmp_path / "extcalc.cob"
        callee_path.write_text(_CALLEE_SOURCE)
        found = ProgramFixtureGenerator._find_callee_file("EXTCALC", [str(tmp_path)])
        assert found == str(callee_path)

    def test_find_callee_file_returns_none_when_absent_from_every_directory(
        self, tmp_path
    ):
        found = ProgramFixtureGenerator._find_callee_file("NOSUCHPROG", [str(tmp_path)])
        assert found is None

    def test_resolve_callees_finds_static_call_target_on_disk(self, tmp_path):
        (tmp_path / "EXTCALC.cbl").write_text(_CALLEE_SOURCE)
        ast = _parsed_caller()
        indexes, asts = ProgramFixtureGenerator()._resolve_callees(ast, [str(tmp_path)])
        assert "EXTCALC" in indexes
        assert "EXTCALC" in asts
        assert asts["EXTCALC"].program_name == "EXTCALC"

    def test_resolve_callees_skips_dynamic_call_targets(self, tmp_path):
        (tmp_path / "EXTCALC.cbl").write_text(_CALLEE_SOURCE)
        ast = _parsed_caller()
        # The dynamic CALL WS-DYNAMIC-NAME (identifier, not a literal) never
        # contributes a static name, so its resolution shouldn't matter --
        # only the static CALL 'EXTCALC' should be resolved either way, and
        # no crash should come from the dynamic target being un-resolvable.
        indexes, _ = ProgramFixtureGenerator()._resolve_callees(ast, [str(tmp_path)])
        assert list(indexes) == ["EXTCALC"]

    def test_resolve_callees_leaves_unfound_targets_absent(self, tmp_path):
        ast = _parsed_caller()
        indexes, asts = ProgramFixtureGenerator()._resolve_callees(ast, [str(tmp_path)])
        assert indexes == {}
        assert asts == {}

    def test_resolve_callees_swallows_program_layout_error(self, tmp_path):
        (tmp_path / "EXTCALC.cbl").write_text(_CALLEE_SOURCE)
        ast = _parsed_caller()
        with patch.object(
            ProgramLayoutIndex,
            "from_file",
            side_effect=ProgramLayoutError("boom"),
        ):
            indexes, asts = ProgramFixtureGenerator()._resolve_callees(
                ast, [str(tmp_path)]
            )
        assert indexes == {}
        assert asts == {}

    def test_resolve_callees_prefers_contained_program_over_callee_path(self, tmp_path):
        # A caller/callee bundled in one compilation unit is resolved for
        # free from `contained_programs` and never needs a file lookup --
        # even if a --callee-path directory also has a matching name, the
        # bundled AST wins (contained_programs is populated first and the
        # callee_paths loop skips names already in callee_asts).
        (tmp_path / "CALCULATOR.cbl").write_text(_CALLEE_SOURCE)
        with open(SUBPROGRAM_DEMO) as handle:
            result = parse_cobol(handle.read(), filename=SUBPROGRAM_DEMO)
        assert result.ast is not None, result.errors
        indexes, asts = ProgramFixtureGenerator()._resolve_callees(
            result.ast, [str(tmp_path)]
        )
        assert asts["CALCULATOR"].program_name == "CALCULATOR"
        # The bundled CALCULATOR (from subprogram_demo.cbl) has five LINKAGE
        # items including LK-NUM1 -- the on-disk stand-in saved under the
        # same name only has LK-VAL, so resolving LK-NUM1 proves the bundled
        # AST won over the callee_paths file lookup.
        assert indexes["CALCULATOR"].record_named("LK-NUM1") is not None
        assert indexes["CALCULATOR"].record_named("LK-VAL") is None

    def test_end_to_end_call_arg_direction_uses_callee_source_provenance(
        self, tmp_path
    ):
        (tmp_path / "EXTCALC.cbl").write_text(_CALLEE_SOURCE)
        caller_path = tmp_path / "CALLERPROG.cbl"
        caller_path.write_text(_CALLER_SOURCE)
        bundle = ProgramFixtureGenerator().generate_from_file(
            str(caller_path), seed=1, callee_paths=[str(tmp_path)]
        )
        # EXTCALC writes to its one LINKAGE item (MOVE 99 TO LK-VAL), so the
        # v1 "writes-at-all -> IN" rule resolves WS-VAL's direction from the
        # callee's own source rather than falling back to the caller's own
        # dataflow guess -- confirmed by the generated value showing up as
        # part of the CALL fixture's IN payload.
        call_fixtures = [
            f for f in bundle.scenarios[0].fixtures if f.ref.category == "CALL"
        ]
        assert call_fixtures
        assert any("WS-VAL" in fixture.sequence[0] for fixture in call_fixtures)
