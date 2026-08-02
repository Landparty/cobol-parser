"""Contract tests for the copybook -> CSV data generator's public API.

Pins the shapes that downstream consumers (the CLI, the vendored backend
adapter, and any test-fixture tooling) depend on: the exported names, the
constructor/method signatures, the FieldSpec and GeneratedDataset dicts, and
the guarantee that a seed reproduces a run exactly.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import cobolparser.generators as generators
from cobolparser.generators import (
    CopybookDataGenerator,
    CopybookLayoutError,
    DataGeneratorOptions,
    FieldCategory,
    FieldSpec,
    GeneratedDataset,
)

pytestmark = pytest.mark.contract

COPYBOOK = Path(__file__).parents[1] / "samples" / "copybooks" / "TXNDATA.cpy"

_FIELD_SPEC_KEYS = {
    "name",
    "column",
    "qualified_name",
    "level",
    "picture",
    "usage",
    "category",
    "size",
    "integer_digits",
    "decimal_digits",
    "is_signed",
    "value_clause",
    "condition_values",
    "subscripts",
    "redefines",
}

_DATASET_KEYS = {"record_name", "seed", "row_count", "fields", "rows"}


def _dataset(**options) -> GeneratedDataset:
    options.setdefault("rows", 4)
    options.setdefault("seed", 2024)
    return CopybookDataGenerator(DataGeneratorOptions(**options)).generate_from_file(
        COPYBOOK
    )


class TestExportedNames:
    @pytest.mark.parametrize(
        "name",
        [
            "CopybookDataGenerator",
            "CopybookLayoutError",
            "DataGeneratorOptions",
            "FieldCategory",
            "FieldSpec",
            "GeneratedDataset",
            "flatten_record",
            "parse_copybook_records",
        ],
    )
    def test_name_is_exported_from_the_generators_package(self, name):
        assert name in generators.__all__
        assert hasattr(generators, name)

    def test_layout_error_is_a_value_error(self):
        # Callers may catch ValueError without knowing the specific type.
        assert issubclass(CopybookLayoutError, ValueError)


class TestOptionsContract:
    @pytest.mark.parametrize(
        ("option", "default"),
        [
            ("rows", 10),
            ("seed", None),
            ("include_filler", False),
            ("include_redefines", False),
            ("expand_occurs", True),
            ("max_occurs", None),
            ("respect_values", True),
            ("use_condition_values", True),
            ("semantic_hints", True),
            ("header_style", "short"),
            ("unique_fields", ()),
            ("blank_rate", 0.0),
        ],
    )
    def test_option_default_is_stable(self, option, default):
        assert getattr(DataGeneratorOptions(), option) == default

    def test_invalid_options_raise_value_error(self):
        with pytest.raises(ValueError):
            DataGeneratorOptions(rows=-1)


class TestGeneratorContract:
    def test_generator_accepts_no_options(self):
        assert CopybookDataGenerator().options.rows == 10

    def test_generate_from_source_signature(self):
        params = inspect.signature(
            CopybookDataGenerator.generate_from_source
        ).parameters
        assert "source" in params
        assert params["filename"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["record"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_generate_from_file_signature(self):
        params = inspect.signature(CopybookDataGenerator.generate_from_file).parameters
        assert "path" in params
        assert params["record"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_generate_returns_a_generated_dataset(self):
        assert isinstance(_dataset(), GeneratedDataset)


class TestFieldSpecContract:
    def test_to_dict_keys_are_stable(self):
        spec = _dataset().fields[0]
        assert set(spec.to_dict()) == _FIELD_SPEC_KEYS

    def test_category_serialises_as_a_string(self):
        payload = _dataset().fields[0].to_dict()
        assert isinstance(payload["category"], str)
        assert payload["category"] in {c.value for c in FieldCategory}

    def test_field_spec_is_the_declared_type(self):
        assert all(isinstance(f, FieldSpec) for f in _dataset().fields)

    def test_qualified_name_is_dot_separated_from_the_record_root(self):
        spec = _dataset().fields[0]
        assert spec.qualified_name.split(".")[0] == "TXN-RECORD"
        assert spec.qualified_name.endswith(spec.name)


class TestDatasetContract:
    def test_to_dict_keys_are_stable(self):
        assert set(_dataset().to_dict()) == _DATASET_KEYS

    def test_header_is_a_list_of_unique_strings(self):
        header = _dataset().header
        assert all(isinstance(column, str) for column in header)
        assert len(header) == len(set(header))

    def test_rows_are_lists_of_strings(self):
        dataset = _dataset()
        assert all(isinstance(cell, str) for row in dataset.rows for cell in row)

    def test_to_csv_starts_with_the_header_row(self):
        dataset = _dataset()
        first_line = dataset.to_csv().splitlines()[0]
        assert first_line == ",".join(dataset.header)

    def test_to_dicts_length_matches_rows(self):
        dataset = _dataset()
        assert len(dataset.to_dicts()) == len(dataset.rows)

    def test_seed_is_always_reported_even_when_not_supplied(self):
        assert isinstance(_dataset(seed=None).seed, int)


class TestReproducibilityContract:
    def test_a_seed_pins_the_output_exactly(self):
        assert (
            _dataset(rows=12, seed=555).to_csv() == _dataset(rows=12, seed=555).to_csv()
        )

    def test_reported_seed_replays_an_unseeded_run(self):
        original = _dataset(rows=8, seed=None)
        assert _dataset(rows=8, seed=original.seed).to_csv() == original.to_csv()
