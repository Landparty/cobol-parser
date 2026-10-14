from __future__ import annotations

from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.layout import (
    condition_ranges,
    expand_condition_values,
    flatten_record,
)
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause


class TestExpandConditionValues:
    def test_literal_values_pass_through_with_quotes_stripped(self):
        assert expand_condition_values(['"Y"', '"N"']) == ["Y", "N"]

    def test_numeric_thru_range_expands_inclusive(self):
        assert expand_condition_values(["2", "THROUGH:4"]) == ["2", "3", "4"]

    def test_descending_thru_range_still_expands_ascending(self):
        assert expand_condition_values(["4", "THROUGH:2"]) == ["4", "2", "3"]

    def test_non_numeric_thru_range_keeps_only_endpoints(self):
        assert expand_condition_values(['"A"', 'THROUGH:"C"']) == ["A", "C"]

    def test_duplicates_removed_preserving_first_seen_order(self):
        assert expand_condition_values(['"Y"', '"Y"', '"N"']) == ["Y", "N"]

    def test_range_expansion_capped_at_64(self):
        values = expand_condition_values(["1", "THROUGH:999999"])
        assert values == [str(n) for n in range(1, 1 + 64 + 1)]


class TestFieldSpecScalingPositions:
    """`FieldSpec.scaling_positions`/`stored_digits` read the canonical
    `PictureClause.total_digits`/`scaling_leading` set by
    `_parse_scaled_pattern` -- the one place a P run is counted -- rather
    than re-deriving them from the raw picture string, so `gen-data`'s
    record images and the `data-items` CLI's offsets (`layout_offsets.py`,
    which already reads `picture.total_digits` directly) cannot drift
    apart on a P-scaled item."""

    _CPY = """\
       01  REC.
           05 A-PPP      PIC 9(3)PPP.
           05 A-VPP      PIC SVPP9(3).
           05 A-PLAIN    PIC 9(5)V99.
           05 A-X        PIC X(4).
"""

    def _by_name(self):
        (record,) = parse_copybook_records(self._CPY)
        opts = DataGeneratorOptions(rows=1, seed=1)
        return {spec.name: spec for spec in flatten_record(record, opts)}

    def test_trailing_p_run_reports_a_positive_scaling_count(self):
        spec = self._by_name()["A-PPP"]
        assert spec.scaling_positions == 3
        assert spec.stored_digits == 3

    def test_leading_p_run_reports_a_negative_scaling_count(self):
        spec = self._by_name()["A-VPP"]
        assert spec.scaling_positions == -2
        assert spec.stored_digits == 3

    def test_ordinary_decimal_picture_has_no_scaling(self):
        spec = self._by_name()["A-PLAIN"]
        assert spec.scaling_positions == 0
        assert spec.stored_digits == 7

    def test_non_numeric_picture_has_no_scaling(self):
        spec = self._by_name()["A-X"]
        assert spec.scaling_positions == 0

    def test_scaling_positions_matches_the_canonical_picture_parse(self):
        # The property this whole class exists to lock in: FieldSpec's
        # count is not just numerically equal but *sourced from* the same
        # PictureClause fields layout_offsets.py (the data-items CLI)
        # already consumes directly.
        loc = SourceLocation(1, 1)
        for pattern, expected_leading in (("9(3)PPP", False), ("SVPP9(3)", True)):
            picture = PictureClause(pattern, loc)
            assert picture.scaling_leading is expected_leading
            spec = self._by_name()["A-PPP" if not expected_leading else "A-VPP"]
            count = spec.integer_digits + spec.decimal_digits - picture.total_digits
            assert spec.scaling_positions == (-count if expected_leading else count)


def test_group_usage_and_sign_are_inherited_by_elementary_fields():
    copybook = (
        "       01 R.\n"
        "          05 G1 COMP-3.\n"
        "             10 A PIC S9(5).\n"
        "             10 B PIC S9(3).\n"
        "          05 G2 SIGN LEADING SEPARATE.\n"
        "             10 C PIC S9(3).\n"
        "          05 Z PIC X.\n"
    )
    record = parse_copybook_records(copybook)[0]
    specs = flatten_record(record, DataGeneratorOptions().for_record_image())
    got = {s.column: (s.usage, s.sign_clause, s.storage_size) for s in specs}
    assert got == {
        "A": ("COMP-3", None, 3),
        "B": ("COMP-3", None, 2),
        "C": ("DISPLAY", "LEADING SEPARATE", 4),
        "Z": ("DISPLAY", None, 1),
    }
    assert sum(s.storage_size for s in specs) == 10


def test_blank_when_zero_is_carried_on_the_field_spec():
    record = parse_copybook_records(
        "       01 R.\n"
        "          05 D PIC 9(3) BLANK WHEN ZERO.\n"
        "          05 E PIC 9(3).\n"
    )[0]
    specs = flatten_record(record, DataGeneratorOptions())
    assert [s.blank_when_zero for s in specs] == [True, False]


class TestConditionRanges:
    def test_pairs_each_range_end_with_the_literal_before_it(self):
        assert condition_ranges(["1", "THROUGH:3", "7", "9", "THROUGH:12"]) == [
            ("1", "3"),
            ("9", "12"),
        ]

    def test_quotes_are_stripped_and_nothing_is_expanded(self):
        assert condition_ranges(['"A"', 'THROUGH:"Z"']) == [("A", "Z")]
        assert condition_ranges(["1", "THROUGH:999999"]) == [("1", "999999")]

    def test_no_range(self):
        assert condition_ranges(['"Y"', "SPACES"]) == []

    def test_a_range_end_with_no_start_is_skipped(self):
        assert condition_ranges(['ALL "X"', "THROUGH:Z"]) == []
