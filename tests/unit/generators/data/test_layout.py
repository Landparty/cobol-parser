from __future__ import annotations

from cobolparser.generators.data.layout import expand_condition_values


class TestExpandConditionValues:
    def test_literal_values_pass_through_with_quotes_stripped(self):
        assert expand_condition_values(['"Y"', '"N"']) == ["Y", "N"]

    def test_numeric_thru_range_expands_inclusive(self):
        assert expand_condition_values(["2", "THROUGH:4"]) == ["2", "3", "4"]

    def test_descending_thru_range_still_expands_ascending(self):
        assert expand_condition_values(["4", "THROUGH:2"]) == ["4", "2", "3"]

    def test_non_numeric_thru_range_keeps_only_endpoints(self):
        assert expand_condition_values(['"A"', "THROUGH:\"C\""]) == ["A", "C"]

    def test_duplicates_removed_preserving_first_seen_order(self):
        assert expand_condition_values(['"Y"', '"Y"', '"N"']) == ["Y", "N"]

    def test_range_expansion_capped_at_64(self):
        values = expand_condition_values(["1", "THROUGH:999999"])
        assert values == [str(n) for n in range(1, 1 + 64 + 1)]
