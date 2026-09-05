"""Storage-size arithmetic: the byte widths every layout and record image
in the package is built from.

The expected values here are not derived from the IBM manuals alone -- the
whole table was checked against GnuCOBOL by compiling a program declaring
these items and reading back ``LENGTH OF`` and the raw group bytes.  See
``test_encoding.py``'s module docstring for that probe's output.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.storage import (
    binary_byte_length,
    packed_byte_length,
    storage_size,
)


class TestBinaryByteLength:
    @pytest.mark.parametrize(
        ("digits", "expected"),
        [(1, 2), (4, 2), (5, 4), (9, 4), (10, 8), (18, 8), (19, 16), (31, 16)],
    )
    def test_ibm_width_table(self, digits, expected):
        assert binary_byte_length(digits) == expected


class TestPackedByteLength:
    @pytest.mark.parametrize(
        ("digits", "expected"),
        [(1, 1), (2, 2), (3, 2), (7, 4), (8, 5), (9, 5), (18, 10)],
    )
    def test_digit_nibbles_plus_sign_nibble_rounded_up(self, digits, expected):
        assert packed_byte_length(digits) == expected

    def test_odd_digit_count_leaves_no_slack(self):
        # 7 digits + 1 sign nibble = 8 nibbles = exactly 4 bytes.
        assert packed_byte_length(7) == 4
        # 8 digits + 1 sign nibble = 9 nibbles, which needs a padding nibble.
        assert packed_byte_length(8) == 5


class TestStorageSize:
    def test_display_is_its_picture_size(self):
        assert storage_size("DISPLAY", picture_size=6, total_digits=None) == 6

    def test_absent_usage_defaults_to_display(self):
        assert storage_size(None, picture_size=6, total_digits=None) == 6

    def test_comp_3_packs_two_digits_per_byte(self):
        # PIC S9(7)V99 COMP-3: nine display positions, five real bytes.
        assert storage_size("COMP-3", picture_size=9, total_digits=9) == 5

    def test_packed_decimal_is_a_synonym_for_comp_3(self):
        assert storage_size("PACKED-DECIMAL", picture_size=9, total_digits=9) == 5

    @pytest.mark.parametrize(
        "usage", ["COMP", "COMPUTATIONAL", "COMP-4", "COMP-5", "BINARY"]
    )
    def test_every_binary_usage_shares_one_width_table(self, usage):
        assert storage_size(usage, picture_size=4, total_digits=4) == 2
        assert storage_size(usage, picture_size=9, total_digits=9) == 4

    def test_comp_1_and_comp_2_are_fixed_width_and_pictureless(self):
        assert storage_size("COMP-1", picture_size=None, total_digits=None) == 4
        assert storage_size("COMP-2", picture_size=None, total_digits=None) == 8

    def test_index_occupies_a_fullword_despite_having_no_picture(self):
        # Regression: sized from its (absent) PICTURE this came out as zero
        # bytes, silently collapsing every offset after it in the record.
        assert storage_size("INDEX", picture_size=None, total_digits=None) == 4

    @pytest.mark.parametrize(
        "usage", ["POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER"]
    )
    def test_pointers_occupy_a_fullword(self, usage):
        assert storage_size(usage, picture_size=None, total_digits=None) == 4

    def test_sign_separate_spends_a_byte_the_picture_does_not_count(self):
        assert (
            storage_size(
                "DISPLAY",
                picture_size=5,
                total_digits=5,
                sign_clause="LEADING SEPARATE",
                is_signed=True,
            )
            == 6
        )

    def test_sign_trailing_without_separate_is_an_overpunch_not_a_byte(self):
        assert (
            storage_size(
                "DISPLAY",
                picture_size=5,
                total_digits=5,
                sign_clause="TRAILING",
                is_signed=True,
            )
            == 5
        )

    def test_sign_separate_on_a_comp_3_field_adds_nothing(self):
        # COBOL permits the clause there but the sign lives in the packed
        # encoding's own nibble, so it cannot cost a byte.
        assert (
            storage_size(
                "COMP-3",
                picture_size=9,
                total_digits=9,
                sign_clause="LEADING SEPARATE",
                is_signed=True,
            )
            == 5
        )

    def test_usage_matching_is_case_insensitive(self):
        assert storage_size("comp-3", picture_size=9, total_digits=9) == 5

    def test_pictureless_binary_has_no_width_to_report(self):
        assert storage_size("COMP-3", picture_size=None, total_digits=None) == 0
