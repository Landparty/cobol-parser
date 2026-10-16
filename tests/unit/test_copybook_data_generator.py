"""Unit tests for the copybook -> CSV synthetic data generator.

Covers layout flattening (OCCURS, REDEFINES, FILLER, level-88, duplicate
names), value generation constraints per PICTURE category, option
validation, and the dataset/CSV surface.
"""

from __future__ import annotations

import csv
import io
import struct
from decimal import Decimal
from pathlib import Path

import pytest

from cobolparser.generators.copybook_data import (
    CopybookDataGenerator,
    CopybookLayoutError,
    DataGeneratorOptions,
    FieldCategory,
    flatten_record,
    parse_copybook_records,
)

SAMPLES = Path(__file__).parents[1] / "samples"
TXNDATA = SAMPLES / "copybooks" / "TXNDATA.cpy"
CUSTOMER = SAMPLES / "copybooks" / "CUSTOMER.cpy"
EMPLOYEE = SAMPLES / "copybooks" / "EMPLOYEE.cpy"


def _fields(source: str, **options):
    """Flatten the first record of *source* with the given options."""
    record = parse_copybook_records(source)[0]
    return flatten_record(record, DataGeneratorOptions(**options))


def _by_name(specs, name):
    for spec in specs:
        if spec.name == name:
            return spec
    raise AssertionError(f"no field named {name} in {[s.name for s in specs]}")


def _generate(path, **options):
    return CopybookDataGenerator(DataGeneratorOptions(**options)).generate_from_file(
        path
    )


# ---------------------------------------------------------------------------
# Copybook parsing
# ---------------------------------------------------------------------------


class TestParseCopybookRecords:
    def test_parses_fixed_format_fragment(self):
        records = parse_copybook_records(CUSTOMER.read_text())
        assert [r.name for r in records] == ["CUSTOMER-RECORD"]

    def test_parses_free_form_fragment(self):
        source = "01 FREE-REC.\n  05 FREE-FLD PIC X(4).\n"
        records = parse_copybook_records(source)
        assert records[0].name == "FREE-REC"
        assert _by_name(flatten_record(records[0]), "FREE-FLD").size == 4

    def test_parses_a_whole_program_not_just_a_fragment(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DEMO.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-REC.\n"
            "           05 WS-FLD PIC X(3).\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        assert [r.name for r in parse_copybook_records(source)] == ["WS-REC"]

    def test_free_form_01_with_deeply_indented_subordinates(self):
        # The 01 sits in column 1 but its 05s are indented past column 8.
        # Scoring purely by indent judges this fixed-format and slices the
        # "01 REC." line away, losing the record root entirely.
        source = (
            "01 REC.\n"
            "       05 FLD-A PIC X(5).\n"
            "       05 FLD-B PIC 9(3).\n"
            "       05 FLD-C PIC X(2).\n"
        )
        records = parse_copybook_records(source)
        assert records[0].name == "REC"
        assert [f.name for f in flatten_record(records[0])] == [
            "FLD-A",
            "FLD-B",
            "FLD-C",
        ]

    def test_fixed_format_with_numeric_sequence_area(self):
        # Columns 1-6 hold a real sequence number (the NIST convention); the
        # code still starts at column 8 and must be read as fixed format.
        source = "000100     01 SEQ-REC.\n" "000200         05 SEQ-FLD PIC X(6).\n"
        records = parse_copybook_records(source)
        assert records[0].name == "SEQ-REC"
        assert [f.name for f in flatten_record(records[0])] == ["SEQ-FLD"]

    def test_synthesised_record_name_is_a_legal_data_name(self):
        # The default filename "<copybook>" must not leak its punctuation into
        # the synthesised record name.
        records = parse_copybook_records("     02 ORPHAN-FLD PIC X.\n")
        assert records[0].name == "COPYBOOK-RECORD"

    def test_synthesised_record_name_derives_from_the_filename(self):
        records = parse_copybook_records(
            "     02 ORPHAN-FLD PIC X.\n", filename="/tmp/PAYROLL.cpy"
        )
        assert records[0].name == "PAYROLL-RECORD"

    def test_multiple_records_returned_in_source_order(self):
        source = "01 FIRST-REC.\n  05 A PIC X.\n01 SECOND-REC.\n  05 B PIC X.\n"
        assert [r.name for r in parse_copybook_records(source)] == [
            "FIRST-REC",
            "SECOND-REC",
        ]

    def test_empty_copybook_raises(self):
        with pytest.raises(CopybookLayoutError, match="empty"):
            parse_copybook_records("   \n\n")

    def test_copybook_without_a_record_raises(self):
        with pytest.raises(CopybookLayoutError, match="no level-01 record"):
            parse_copybook_records("      * just a comment\n")


# ---------------------------------------------------------------------------
# Flattening
# ---------------------------------------------------------------------------


class TestFlattenRecord:
    def test_emits_one_column_per_elementary_item(self):
        names = [f.name for f in _fields(CUSTOMER.read_text())]
        assert names == [
            "CUSTOMER-ID",
            "CUSTOMER-NAME",
            "STREET",
            "CITY",
            "STATE",
            "ZIP",
        ]

    def test_group_items_are_not_columns(self):
        names = [f.name for f in _fields(CUSTOMER.read_text())]
        assert "CUSTOMER-ADDRESS" not in names

    def test_occurs_expands_to_one_column_per_occurrence(self):
        columns = [f.column for f in _fields(TXNDATA.read_text())]
        assert "ITEM-CODE(1)" in columns
        assert "ITEM-CODE(3)" in columns
        assert "ITEM-CODE(4)" not in columns

    def test_occurs_subscripts_are_recorded(self):
        specs = [f for f in _fields(TXNDATA.read_text()) if f.name == "ITEM-QTY"]
        assert [s.subscripts for s in specs] == [(1,), (2,), (3,)]

    def test_no_expand_occurs_keeps_only_first_occurrence(self):
        specs = [
            f
            for f in _fields(TXNDATA.read_text(), expand_occurs=False)
            if f.name == "ITEM-CODE"
        ]
        assert len(specs) == 1

    def test_max_occurs_caps_expansion(self):
        specs = [
            f
            for f in _fields(TXNDATA.read_text(), max_occurs=2)
            if f.name == "ITEM-CODE"
        ]
        assert len(specs) == 2

    def test_pathological_occurs_count_is_hard_capped(self):
        # A copybook is free to declare an enormous OCCURS count; nothing
        # requires expanding it 1:1 into FieldSpecs when no caller-supplied
        # max_occurs is given. An internal hard ceiling protects against
        # a multi-million-row copybook exhausting memory.
        from cobolparser.generators.data.layout import _MAX_OCCURS_HARD_CAP

        source = "01 R.\n  05 TBL OCCURS 50000 TIMES PIC X.\n"
        specs = _fields(source)
        assert len(specs) == _MAX_OCCURS_HARD_CAP
        assert specs[-1].subscripts == (_MAX_OCCURS_HARD_CAP,)

    def test_max_occurs_beyond_hard_cap_is_still_clamped(self):
        # The hard ceiling applies regardless of the caller's own config --
        # an explicit --max-occurs larger than the ceiling must not bypass it.
        from cobolparser.generators.data.layout import _MAX_OCCURS_HARD_CAP

        source = "01 R.\n  05 TBL OCCURS 50000 TIMES PIC X.\n"
        specs = _fields(source, max_occurs=_MAX_OCCURS_HARD_CAP + 500)
        assert len(specs) == _MAX_OCCURS_HARD_CAP

    def test_redefines_excluded_by_default(self):
        names = [f.name for f in _fields(TXNDATA.read_text())]
        assert "RAW-AREA" in names
        assert "PART-A" not in names

    def test_redefines_included_on_request(self):
        names = [f.name for f in _fields(TXNDATA.read_text(), include_redefines=True)]
        assert "PART-A" in names and "PART-B" in names

    def test_filler_excluded_by_default(self):
        assert all(not f.is_filler for f in _fields(TXNDATA.read_text()))

    def test_filler_included_on_request(self):
        names = [f.name for f in _fields(TXNDATA.read_text(), include_filler=True)]
        assert "FILLER" in names

    def test_condition_values_collected_and_ranges_expanded(self):
        specs = _fields(TXNDATA.read_text())
        assert _by_name(specs, "TXN-TYPE").condition_values == ["D", "W", "T"]
        assert _by_name(specs, "TXN-STATUS").condition_values == ["1", "2", "3", "4"]

    def test_signed_thru_range_expands(self):
        source = "01 R.\n  05 B PIC S9(3).\n     88 B-SPAN VALUE -2 THRU 2.\n"
        assert _by_name(_fields(source), "B").condition_values == [
            "-2",
            "-1",
            "0",
            "1",
            "2",
        ]

    def test_descending_thru_range_keeps_both_endpoints(self):
        # A descending range is swapped before expansion; iterating from the
        # low bound is what keeps 2 from being dropped.
        source = "01 R.\n  05 D PIC 9(3).\n     88 D-DESC VALUE 4 THRU 2.\n"
        assert sorted(_by_name(_fields(source), "D").condition_values) == [
            "2",
            "3",
            "4",
        ]

    def test_wide_thru_range_is_capped(self):
        source = "01 R.\n  05 E PIC 9(6).\n     88 E-HUGE VALUE 1 THRU 999999.\n"
        values = _by_name(_fields(source), "E").condition_values
        assert 0 < len(values) <= 65

    def test_non_numeric_thru_range_keeps_only_its_endpoints(self):
        source = "01 R.\n  05 G PIC X(2).\n     88 G-TEXT VALUE 'AA' THRU 'ZZ'.\n"
        assert _by_name(_fields(source), "G").condition_values == ["AA", "ZZ"]

    def test_value_clause_captured(self):
        assert _by_name(_fields(TXNDATA.read_text()), "ACTIVE-FLAG").value_clause

    def test_qualified_name_is_the_path_from_the_record_root(self):
        spec = _by_name(_fields(CUSTOMER.read_text()), "CITY")
        assert spec.qualified_name == "CUSTOMER-RECORD.CUSTOMER-ADDRESS.CITY"

    def test_path_header_style_uses_qualified_names(self):
        specs = _fields(CUSTOMER.read_text(), header_style="path")
        assert _by_name(specs, "CITY").column == "CUSTOMER-RECORD.CUSTOMER-ADDRESS.CITY"

    def test_duplicate_names_in_different_groups_are_disambiguated(self):
        source = (
            "01 DUP-REC.\n"
            "  05 GRP-A.\n"
            "    10 SHARED PIC X(3).\n"
            "  05 GRP-B.\n"
            "    10 SHARED PIC X(3).\n"
        )
        columns = [f.column for f in _fields(source)]
        assert columns == ["DUP-REC.GRP-A.SHARED", "DUP-REC.GRP-B.SHARED"]

    def test_occurs_repeats_are_not_treated_as_name_collisions(self):
        # The subscript already disambiguates, so the short name is kept.
        columns = [
            f.column for f in _fields(TXNDATA.read_text()) if f.name == "ITEM-CODE"
        ]
        assert columns == ["ITEM-CODE(1)", "ITEM-CODE(2)", "ITEM-CODE(3)"]

    def test_headers_are_always_unique(self):
        columns = [f.column for f in _fields(TXNDATA.read_text(), include_filler=True)]
        assert len(columns) == len(set(columns))


class TestFieldCategories:
    @pytest.mark.parametrize(
        ("picture", "expected"),
        [
            ("X(10)", FieldCategory.ALPHANUMERIC),
            ("A(5)", FieldCategory.ALPHABETIC),
            ("N(6)", FieldCategory.NATIONAL),
            ("9(5)", FieldCategory.NUMERIC),
            ("S9(7)V99", FieldCategory.NUMERIC),
            ("-ZZ,ZZ9.99", FieldCategory.NUMERIC_EDITED),
        ],
    )
    def test_picture_maps_to_category(self, picture, expected):
        source = f"01 R.\n  05 FLD PIC {picture}.\n"
        assert _by_name(_fields(source), "FLD").category is expected

    def test_comp_2_without_a_picture_is_a_float(self):
        source = "01 R.\n  05 FLD USAGE COMP-2.\n"
        assert _by_name(_fields(source), "FLD").category is FieldCategory.FLOAT

    def test_explicit_sign_is_detected(self):
        source = "01 R.\n  05 FLD PIC S9(5).\n"
        assert _by_name(_fields(source), "FLD").is_signed

    def test_edited_picture_with_sign_symbol_is_signed(self):
        # No 'S', but a leading '-' still lets the field hold a negative.
        source = "01 R.\n  05 FLD PIC -ZZ9.99.\n"
        assert _by_name(_fields(source), "FLD").is_signed

    def test_unsigned_numeric_is_not_signed(self):
        source = "01 R.\n  05 FLD PIC 9(5).\n"
        assert not _by_name(_fields(source), "FLD").is_signed


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class TestGeneration:
    def test_row_count_matches_the_request(self):
        assert len(_generate(TXNDATA, rows=25, seed=1).rows) == 25

    def test_zero_rows_still_yields_a_header(self):
        dataset = _generate(TXNDATA, rows=0, seed=1)
        assert dataset.rows == []
        assert dataset.header

    def test_same_seed_reproduces_identical_output(self):
        first = _generate(TXNDATA, rows=15, seed=4242).to_csv()
        second = _generate(TXNDATA, rows=15, seed=4242).to_csv()
        assert first == second

    def test_different_seeds_differ(self):
        first = _generate(TXNDATA, rows=15, seed=1).to_csv()
        second = _generate(TXNDATA, rows=15, seed=2).to_csv()
        assert first != second

    def test_random_seed_is_recorded_for_replay(self):
        dataset = _generate(TXNDATA, rows=5)
        replay = _generate(TXNDATA, rows=5, seed=dataset.seed)
        assert replay.to_csv() == dataset.to_csv()

    def test_every_row_has_one_cell_per_column(self):
        dataset = _generate(TXNDATA, rows=10, seed=8)
        assert all(len(row) == len(dataset.header) for row in dataset.rows)

    def test_generate_from_source_matches_generate_from_file(self):
        from_source = CopybookDataGenerator(
            DataGeneratorOptions(rows=5, seed=11)
        ).generate_from_source(TXNDATA.read_text())
        assert from_source.to_csv() == _generate(TXNDATA, rows=5, seed=11).to_csv()

    def test_record_selection_by_name(self):
        source = "01 FIRST-REC.\n  05 A PIC X.\n01 SECOND-REC.\n  05 B PIC X.\n"
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        dataset = generator.generate_from_source(source, record="SECOND-REC")
        assert dataset.record_name == "SECOND-REC"
        assert dataset.header == ["B"]

    def test_record_selection_is_case_insensitive(self):
        source = "01 FIRST-REC.\n  05 A PIC X.\n"
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        assert generator.generate_from_source(source, record="first-rec")

    def test_unknown_record_raises_and_lists_the_alternatives(self):
        source = "01 FIRST-REC.\n  05 A PIC X.\n"
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        with pytest.raises(CopybookLayoutError, match="FIRST-REC"):
            generator.generate_from_source(source, record="MISSING")

    def test_record_with_no_generatable_fields_raises(self):
        source = "01 ONLY-FILLER.\n  05 FILLER PIC X(4).\n"
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        with pytest.raises(CopybookLayoutError, match="no generatable fields"):
            generator.generate_from_source(source)


class TestFloatValueClauses:
    """Issue #551: COMP-1/COMP-2 VALUE clauses were rendered through the
    layout's placeholder ``PIC 9(9)``: ``VALUE -2.5E-02`` was written as 0
    and ``-1.5`` as 2."""

    SOURCE = (
        "01 R.\n"
        "  05 B COMP-1 VALUE 2.5E-02.\n"
        "  05 C COMP-2 VALUE -2.5E-02.\n"
        "  05 E COMP-2 VALUE -1.5.\n"
        "  05 F COMP-1 VALUE 3.25.\n"
    )

    def _dataset(self):
        options = DataGeneratorOptions(rows=1, seed=1).for_record_image()
        return CopybookDataGenerator(options).generate_from_source(self.SOURCE)

    def test_csv_cells_keep_sign_and_fraction(self):
        assert self._dataset().rows[0] == ["0.025", "-0.025", "-1.5", "3.25"]

    def test_record_image_holds_the_declared_floats(self):
        from cobolparser.generators import EncodingOptions, Endian

        image = self._dataset().to_records(EncodingOptions(endian=Endian.BIG))
        b, c, e, f = struct.unpack(">fddf", image)
        assert b == pytest.approx(0.025)
        assert c == -0.025
        assert e == -1.5
        assert f == 3.25


class TestValueConstraints:
    """Every generated value must be assignable to the field it came from."""

    def test_alphanumeric_values_never_exceed_the_picture_size(self):
        dataset = _generate(TXNDATA, rows=50, seed=13)
        for index, spec in enumerate(dataset.fields):
            if spec.category is not FieldCategory.ALPHANUMERIC:
                continue
            for row in dataset.rows:
                assert len(row[index]) <= spec.size

    def test_numeric_values_fit_the_declared_digit_counts(self):
        dataset = _generate(TXNDATA, rows=50, seed=17)
        for index, spec in enumerate(dataset.fields):
            if spec.category not in (
                FieldCategory.NUMERIC,
                FieldCategory.NUMERIC_EDITED,
            ):
                continue
            for row in dataset.rows:
                value = Decimal(row[index])
                digits = value.as_tuple()
                assert -digits.exponent <= spec.decimal_digits
                integer_digits = len(digits.digits) + digits.exponent
                assert integer_digits <= spec.integer_digits

    def test_unsigned_fields_never_generate_negatives(self):
        dataset = _generate(TXNDATA, rows=50, seed=19)
        for index, spec in enumerate(dataset.fields):
            if spec.category not in (
                FieldCategory.NUMERIC,
                FieldCategory.NUMERIC_EDITED,
            ):
                continue
            if spec.is_signed:
                continue
            assert all(not row[index].startswith("-") for row in dataset.rows)

    def test_signed_field_does_produce_negatives(self):
        dataset = _generate(TXNDATA, rows=200, seed=23)
        index = dataset.header.index("TXN-AMT")
        assert any(row[index].startswith("-") for row in dataset.rows)

    def test_condition_values_bound_the_domain(self):
        dataset = _generate(TXNDATA, rows=60, seed=29)
        type_index = dataset.header.index("TXN-TYPE")
        status_index = dataset.header.index("TXN-STATUS")
        assert {row[type_index] for row in dataset.rows} <= {"D", "W", "T"}
        assert {row[status_index] for row in dataset.rows} <= {"1", "2", "3", "4"}

    def test_declared_domain_values_are_never_randomly_negated(self):
        # A signed field occasionally negates a *generated* magnitude so
        # negatives get exercised. It must not do that to a value the
        # copybook declared: VALUE 5 must never come out as -5.
        source = (
            "01 R.\n"
            "  05 SIGNED-STATUS PIC S9(3).\n"
            "     88 ST-LOW  VALUE 5.\n"
            "     88 ST-HIGH VALUE 250.\n"
        )
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=200, seed=911))
        dataset = generator.generate_from_source(source)
        assert {row[0] for row in dataset.rows} == {"5", "250"}

    def test_signed_value_clause_is_not_negated_either(self):
        source = "01 R.\n  05 SIGNED-CONST PIC S9(4) VALUE 42.\n"
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=100, seed=913))
        dataset = generator.generate_from_source(source)
        assert {row[0] for row in dataset.rows} == {"42"}

    def test_value_clause_is_honoured(self):
        dataset = _generate(TXNDATA, rows=20, seed=31)
        index = dataset.header.index("ACTIVE-FLAG")
        assert {row[index] for row in dataset.rows} == {"Y"}

    def test_ignoring_values_widens_the_domain(self):
        dataset = _generate(
            TXNDATA,
            rows=60,
            seed=37,
            use_condition_values=False,
            respect_values=False,
        )
        index = dataset.header.index("TXN-TYPE")
        assert {row[index] for row in dataset.rows} - {"D", "W", "T"}

    def test_semantic_hints_produce_readable_values(self):
        dataset = _generate(TXNDATA, rows=20, seed=41)
        city_index = dataset.header.index("CUST-CITY")
        name_index = dataset.header.index("CUST-NAME")
        assert all(row[city_index].replace(" ", "").isalpha() for row in dataset.rows)
        assert all(" " in row[name_index] for row in dataset.rows)

    def test_semantic_hints_can_be_disabled(self):
        dataset = _generate(TXNDATA, rows=20, seed=43, semantic_hints=False)
        index = dataset.header.index("CUST-CITY")
        values = {row[index] for row in dataset.rows}
        assert not values & {"CHICAGO", "SEATTLE", "BOSTON", "DENVER"}

    def test_date_field_generates_a_valid_calendar_date(self):
        dataset = _generate(TXNDATA, rows=40, seed=47)
        index = dataset.header.index("POST-DATE")
        for row in dataset.rows:
            value = row[index]
            assert len(value) == 8
            assert 1900 <= int(value[:4]) <= 2100
            assert 1 <= int(value[4:6]) <= 12
            assert 1 <= int(value[6:]) <= 31

    def test_unique_fields_hold_distinct_values(self):
        dataset = _generate(TXNDATA, rows=40, seed=53, unique_fields=("TXN-ID",))
        index = dataset.header.index("TXN-ID")
        values = [row[index] for row in dataset.rows]
        assert len(values) == len(set(values))

    def test_unique_request_on_a_narrow_field_still_terminates(self):
        # PIC 9 has ten possible values; asking for 40 unique rows must fall
        # back to the counter rather than spin forever.
        source = "01 R.\n  05 NARROW PIC 9.\n"
        generator = CopybookDataGenerator(
            DataGeneratorOptions(rows=40, seed=59, unique_fields=("NARROW",))
        )
        assert len(generator.generate_from_source(source).rows) == 40

    def test_blank_rate_of_one_blanks_every_cell(self):
        dataset = _generate(TXNDATA, rows=5, seed=61, blank_rate=1.0)
        assert all(cell == "" for row in dataset.rows for cell in row)

    def test_blank_rate_of_zero_blanks_nothing(self):
        dataset = _generate(TXNDATA, rows=5, seed=67)
        assert all(cell != "" for row in dataset.rows for cell in row)

    def test_comp_3_field_carries_its_logical_value_not_packed_bytes(self):
        # PIC 9(7)V99 COMP-3 occupies 5 packed bytes, but the CSV must hold the
        # decimal value the program would see, scaled to two decimal places.
        dataset = _generate(EMPLOYEE, rows=10, seed=71)
        spec = _by_name(dataset.fields, "EMPLOYEE-SALARY")
        assert spec.usage == "COMP-3"
        index = dataset.header.index("EMPLOYEE-SALARY")
        for row in dataset.rows:
            value = Decimal(row[index])
            assert -value.as_tuple().exponent == 2
            assert 0 <= value < Decimal(10) ** spec.integer_digits


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


class TestDataGeneratorOptions:
    def test_negative_rows_rejected(self):
        with pytest.raises(ValueError, match="rows"):
            DataGeneratorOptions(rows=-1)

    def test_bad_header_style_rejected(self):
        with pytest.raises(ValueError, match="header_style"):
            DataGeneratorOptions(header_style="wide")

    @pytest.mark.parametrize("rate", [-0.1, 1.1])
    def test_blank_rate_out_of_range_rejected(self, rate):
        with pytest.raises(ValueError, match="blank_rate"):
            DataGeneratorOptions(blank_rate=rate)

    def test_max_occurs_below_one_rejected(self):
        with pytest.raises(ValueError, match="max_occurs"):
            DataGeneratorOptions(max_occurs=0)

    def test_defaults_are_conservative(self):
        options = DataGeneratorOptions()
        assert not options.include_filler
        assert not options.include_redefines
        assert options.expand_occurs


# ---------------------------------------------------------------------------
# Dataset surface
# ---------------------------------------------------------------------------


class TestGeneratedDataset:
    def test_to_csv_round_trips_through_the_csv_module(self):
        dataset = _generate(TXNDATA, rows=8, seed=73)
        parsed = list(csv.reader(io.StringIO(dataset.to_csv())))
        assert parsed[0] == dataset.header
        assert parsed[1:] == dataset.rows

    def test_to_dicts_keys_on_column_names(self):
        dataset = _generate(CUSTOMER, rows=3, seed=79)
        rows = dataset.to_dicts()
        assert len(rows) == 3
        assert set(rows[0]) == set(dataset.header)

    def test_write_csv_matches_to_csv(self, tmp_path):
        dataset = _generate(CUSTOMER, rows=4, seed=83)
        target = tmp_path / "out.csv"
        dataset.write_csv(target)
        written = list(csv.reader(target.open(newline="")))
        assert written == [dataset.header, *dataset.rows]

    def test_write_csv_is_byte_identical_to_to_csv(self, tmp_path):
        # Comparing parsed rows is not enough: the csv module defaults to a
        # "\r\n" terminator, so write_csv once produced different bytes than
        # to_csv for the same dataset, breaking the reproducibility claim
        # between `gen-data -o out.csv` and `gen-data > out.csv`.
        dataset = _generate(TXNDATA, rows=6, seed=857)
        target = tmp_path / "out.csv"
        dataset.write_csv(target)
        assert target.read_bytes() == dataset.to_csv().encode("utf-8")

    def test_line_terminator_is_overridable_on_both_paths(self, tmp_path):
        dataset = _generate(CUSTOMER, rows=2, seed=859)
        target = tmp_path / "crlf.csv"
        dataset.write_csv(target, line_terminator="\r\n")
        assert target.read_bytes() == dataset.to_csv(line_terminator="\r\n").encode(
            "utf-8"
        )
        assert b"\r\n" in target.read_bytes()

    def test_to_dict_describes_the_layout_and_the_rows(self):
        dataset = _generate(CUSTOMER, rows=2, seed=89)
        payload = dataset.to_dict()
        assert payload["record_name"] == "CUSTOMER-RECORD"
        assert payload["row_count"] == 2
        assert payload["seed"] == 89
        assert len(payload["fields"]) == len(dataset.header)
        assert payload["fields"][0]["name"] == "CUSTOMER-ID"

    def test_header_matches_field_columns(self):
        dataset = _generate(TXNDATA, rows=1, seed=97)
        assert dataset.header == [f.column for f in dataset.fields]
