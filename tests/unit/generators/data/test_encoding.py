"""Record-image encoding: display values -> the bytes a COBOL program reads.

Every expected byte string below is ground truth from GnuCOBOL, not from
reading a manual.  A probe program declaring these exact items was compiled
and its WORKING-STORAGE written to a file::

    01  G.
        05  A-COMP  PIC S9(4) COMP        VALUE 331.
        05  A-C4    PIC S9(9) COMP-4      VALUE 423938499.
        05  A-C5    PIC S9(9) COMP-5      VALUE 423938499.
        05  A-C1    COMP-1.                        *> -2686.2217
        05  A-C2    COMP-2.                        *> -8840.0215
        05  A-PD    PIC S9(7)V99 COMP-3   VALUE 72436.21.
        05  A-ZN    PIC S9(5)             VALUE -12345.
        05  A-ZS    PIC S9(5) SIGN LEADING SEPARATE VALUE -12345.

    LEN=38
    01 4b | 19 44 c9 c3 | c3 c9 44 19 | 8c e3 27 c5
    | 6e 12 83 c0 02 44 c1 c0 | 00 72 43 62 1c
    | 31 32 33 34 75 | 2d 31 32 33 34 35

which is what pins the four decisions this module could not have derived
safely on its own: COMP/COMP-4 are big-endian while COMP-5 and both float
usages follow the *host*; a negative zoned digit sets 0x40 in its zone
(``5`` -> ``u``) rather than using the EBCDIC-derived ``}JKLM`` convention;
and SIGN IS SEPARATE really does spend a whole extra byte.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.encoding import (
    Charset,
    EncodingOptions,
    Endian,
    RecordEncodingError,
    encode_field,
    encode_record,
    encoding_caveats,
    hex_dump,
    record_length,
)
from cobolparser.generators.data.layout import flatten_record
from cobolparser.generators.data.options import DataGeneratorOptions


def specs_for(copybook: str):
    """Flatten *copybook* with byte-complete (record-image) options."""
    record = parse_copybook_records(copybook)[0]
    return flatten_record(record, DataGeneratorOptions().for_record_image())


def one_spec(declaration: str):
    """The single elementary FieldSpec of a one-item record."""
    return specs_for(f"       01  R.\n           05  {declaration}\n")[0]


BIG = EncodingOptions(endian=Endian.BIG)
LITTLE = EncodingOptions(endian=Endian.LITTLE)
EBCDIC = EncodingOptions(charset=Charset.EBCDIC)


class TestPackedDecimal:
    def test_signed_positive_matches_gnucobol(self):
        spec = one_spec("F PIC S9(7)V99 COMP-3.")
        assert encode_field(spec, "72436.21", BIG) == bytes.fromhex("007243621c")

    def test_signed_negative_flips_only_the_sign_nibble(self):
        spec = one_spec("F PIC S9(7)V99 COMP-3.")
        assert encode_field(spec, "-72436.21", BIG) == bytes.fromhex("007243621d")

    def test_unsigned_uses_the_f_sign_nibble(self):
        spec = one_spec("F PIC 9(7)V99 COMP-3.")
        assert encode_field(spec, "72436.21", BIG) == bytes.fromhex("007243621f")

    def test_odd_digit_count_needs_no_padding_nibble(self):
        spec = one_spec("F PIC S9(3) COMP-3.")
        assert encode_field(spec, "123", BIG) == bytes.fromhex("123c")

    def test_even_digit_count_pads_a_high_order_nibble(self):
        spec = one_spec("F PIC S9(4) COMP-3.")
        assert encode_field(spec, "1234", BIG) == bytes.fromhex("01234c")

    def test_implied_decimal_scales_rather_than_storing_a_point(self):
        spec = one_spec("F PIC S9(3)V99 COMP-3.")
        assert encode_field(spec, "1.5", BIG) == bytes.fromhex("00150c")


class TestBinary:
    def test_comp_is_big_endian_regardless_of_the_endian_option(self):
        spec = one_spec("F PIC S9(4) COMP.")
        assert encode_field(spec, "331", BIG) == bytes.fromhex("014b")
        assert encode_field(spec, "331", LITTLE) == bytes.fromhex("014b")

    def test_comp_4_is_big_endian_too(self):
        spec = one_spec("F PIC S9(9) COMP-4.")
        assert encode_field(spec, "423938499", LITTLE) == bytes.fromhex("1944c9c3")

    def test_comp_5_follows_the_endian_option(self):
        spec = one_spec("F PIC S9(9) COMP-5.")
        assert encode_field(spec, "423938499", BIG) == bytes.fromhex("1944c9c3")
        assert encode_field(spec, "423938499", LITTLE) == bytes.fromhex("c3c94419")

    def test_negative_binary_is_twos_complement(self):
        spec = one_spec("F PIC S9(4) COMP.")
        assert encode_field(spec, "-38", BIG) == bytes.fromhex("ffda")

    def test_unsigned_binary_cannot_go_negative(self):
        spec = one_spec("F PIC 9(4) COMP.")
        assert encode_field(spec, "-38", BIG) == bytes.fromhex("0026")

    def test_scaled_binary_stores_the_scaled_integer(self):
        spec = one_spec("F PIC S9(3)V99 COMP.")
        assert encode_field(spec, "1.50", BIG) == (150).to_bytes(4, "big", signed=True)


class TestFloat:
    def test_comp_1_is_ieee_binary32(self):
        spec = one_spec("F COMP-1.")
        assert encode_field(spec, "-2686.2217", LITTLE) == bytes.fromhex("8ce327c5")

    def test_comp_2_is_ieee_binary64(self):
        # The probe's own bytes for this value end 0x6E, one ULP below the
        # correctly-rounded double -- GnuCOBOL converts the decimal literal
        # through its own decimal intermediate and lands a bit low.  Encoding
        # the true nearest double (0x6F) is right, and worth knowing about
        # before anyone diffs a generated record against a compiler-written
        # one and concludes the encoder is broken.
        spec = one_spec("F COMP-2.")
        assert encode_field(spec, "-8840.0215", LITTLE) == bytes.fromhex(
            "6f1283c00244c1c0"
        )

    def test_float_byte_order_follows_the_endian_option(self):
        spec = one_spec("F COMP-1.")
        little = encode_field(spec, "-2686.2217", LITTLE)
        assert encode_field(spec, "-2686.2217", BIG) == little[::-1]

    def test_unparseable_text_encodes_as_zero_rather_than_failing(self):
        spec = one_spec("F COMP-1.")
        assert encode_field(spec, "not a number", LITTLE) == bytes(4)


class TestZonedDecimal:
    def test_negative_ascii_digit_sets_the_zone_bit(self):
        spec = one_spec("F PIC S9(5).")
        assert encode_field(spec, "-12345", EncodingOptions()) == b"1234u"

    def test_positive_ascii_digits_are_plain_characters(self):
        spec = one_spec("F PIC S9(5).")
        assert encode_field(spec, "12345", EncodingOptions()) == b"12345"

    def test_ebcdic_overpunches_the_zone_nibble(self):
        spec = one_spec("F PIC S9(5).")
        assert encode_field(spec, "-12345", EBCDIC) == bytes.fromhex("f1f2f3f4d5")
        assert encode_field(spec, "12345", EBCDIC) == bytes.fromhex("f1f2f3f4c5")

    def test_unsigned_ebcdic_keeps_the_f_zone(self):
        spec = one_spec("F PIC 9(5).")
        assert encode_field(spec, "12345", EBCDIC) == bytes.fromhex("f1f2f3f4f5")

    def test_sign_leading_separate_writes_a_real_sign_byte(self):
        spec = one_spec("F PIC S9(5) SIGN IS LEADING SEPARATE.")
        assert encode_field(spec, "-12345", EncodingOptions()) == b"-12345"
        assert encode_field(spec, "12345", EncodingOptions()) == b"+12345"

    def test_sign_trailing_separate_puts_the_byte_last(self):
        spec = one_spec("F PIC S9(5) SIGN IS TRAILING SEPARATE.")
        assert encode_field(spec, "-12345", EncodingOptions()) == b"12345-"

    def test_sign_leading_overpunches_the_first_digit(self):
        spec = one_spec("F PIC S9(5) SIGN IS LEADING.")
        assert encode_field(spec, "-12345", EncodingOptions()) == b"q2345"

    def test_value_is_right_justified_and_zero_filled(self):
        spec = one_spec("F PIC 9(5).")
        assert encode_field(spec, "7", EncodingOptions()) == b"00007"

    def test_blank_cell_encodes_as_zero(self):
        spec = one_spec("F PIC 9(5).")
        assert encode_field(spec, "", EncodingOptions()) == b"00000"


class TestAlphanumeric:
    def test_short_value_is_space_padded_on_the_right(self):
        spec = one_spec("F PIC X(6).")
        assert encode_field(spec, "AB", EncodingOptions()) == b"AB    "

    def test_ebcdic_pads_with_the_ebcdic_space(self):
        spec = one_spec("F PIC X(6).")
        assert encode_field(spec, "AB", EBCDIC) == bytes.fromhex("c1c2404040") + b"\x40"

    def test_oversized_value_is_truncated_not_rejected(self):
        spec = one_spec("F PIC X(3).")
        assert encode_field(spec, "ABCDEF", EncodingOptions()) == b"ABC"

    def test_numeric_edited_keeps_its_edit_mask(self):
        # The fixed `-` stays in column 1 and the suppressed Z becomes a
        # space -- what GnuCOBOL's MOVE -12.34 TO F leaves there.
        spec = one_spec("F PIC -ZZ9.99.")
        raw = encode_field(spec, "-12.34", EncodingOptions())
        assert len(raw) == spec.storage_size
        assert raw == b"- 12.34"


class TestStorageOnlyUsages:
    def test_index_writes_binary_zeros(self):
        spec = one_spec("F USAGE INDEX.")
        assert encode_field(spec, "544854973", EncodingOptions()) == bytes(4)

    def test_pointer_writes_binary_zeros(self):
        spec = one_spec("F USAGE POINTER.")
        assert encode_field(spec, "12345", EncodingOptions()) == bytes(4)


class TestFiller:
    def test_filler_is_blanked_rather_than_carrying_generated_noise(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  A PIC X(2).\n"
            "           05  FILLER PIC X(3).\n"
        )
        assert encode_record(specs, ["AB", "xyz"], EncodingOptions()) == b"AB   "

    def test_numeric_filler_blanks_to_zeros_not_spaces(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  A PIC X(2).\n"
            "           05  FILLER PIC 9(3).\n"
        )
        assert encode_record(specs, ["AB", "123"], EncodingOptions()) == b"AB000"

    def test_filler_with_a_value_clause_keeps_that_value(self):
        specs = specs_for(
            "       01  R.\n" '           05  FILLER PIC X(3) VALUE "HDR".\n'
        )
        assert encode_record(specs, ["HDR"], EncodingOptions()) == b"HDR"


class TestRecordAssembly:
    COPYBOOK = (
        "       01  CUST-REC.\n"
        "           05  CU-ID    PIC 9(5).\n"
        "           05  CU-BAL   PIC S9(7)V99 COMP-3.\n"
        "           05  FILLER   PIC X(3).\n"
        "           05  CU-COUNT PIC S9(4) COMP.\n"
        "           05  CU-ADJ   PIC S9(5) SIGN IS LEADING SEPARATE.\n"
        "           05  CU-TAGS  OCCURS 3 TIMES PIC X(2).\n"
    )

    def test_record_length_matches_what_gnucobol_reports(self):
        # LENGTH OF CUST-REC under GnuCOBOL for this layout: 5+5+3+2+6+6.
        assert record_length(specs_for(self.COPYBOOK)) == 27

    def test_every_occurs_occurrence_gets_its_own_column(self):
        specs = specs_for(self.COPYBOOK)
        assert [s.column for s in specs][-3:] == [
            "CU-TAGS(1)",
            "CU-TAGS(2)",
            "CU-TAGS(3)",
        ]

    def test_assembled_record_is_exactly_the_predicted_length(self):
        specs = specs_for(self.COPYBOOK)
        row = ["31191", "-592640.32", "", "930", "-72192", "AA", "BB", "CC"]
        raw = encode_record(specs, row, EncodingOptions())
        assert len(raw) == record_length(specs) == 27

    def test_fields_land_at_the_offsets_the_layout_predicts(self):
        specs = specs_for(self.COPYBOOK)
        row = ["31191", "-592640.32", "", "930", "-72192", "AA", "BB", "CC"]
        raw = encode_record(specs, row, EncodingOptions())
        assert raw[0:5] == b"31191"
        assert raw[5:10] == bytes.fromhex("059264032d")
        assert raw[10:13] == b"   "
        assert raw[13:15] == (930).to_bytes(2, "big", signed=True)
        assert raw[15:21] == b"-72192"
        assert raw[21:27] == b"AABBCC"

    def test_redefines_are_excluded_so_no_byte_is_written_twice(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  A PIC X(4).\n"
            "           05  B REDEFINES A PIC 9(4).\n"
        )
        assert [s.column for s in specs] == ["A"]
        assert record_length(specs) == 4

    def test_row_length_mismatch_is_an_error_not_a_short_record(self):
        specs = specs_for(self.COPYBOOK)
        with pytest.raises(RecordEncodingError):
            encode_record(specs, ["31191"], EncodingOptions())


class TestEndianResolution:
    def test_auto_picks_big_endian_for_an_ebcdic_record(self):
        assert EncodingOptions(charset=Charset.EBCDIC).resolved_endian is Endian.BIG

    def test_auto_follows_the_host_for_an_ascii_record(self):
        import sys

        expected = Endian.BIG if sys.byteorder == "big" else Endian.LITTLE
        assert EncodingOptions(charset=Charset.ASCII).resolved_endian is expected

    def test_native_resolves_to_the_host_even_for_ebcdic(self):
        import sys

        expected = Endian.BIG if sys.byteorder == "big" else Endian.LITTLE
        opts = EncodingOptions(charset=Charset.EBCDIC, endian=Endian.NATIVE)
        assert opts.resolved_endian is expected

    def test_an_explicit_order_is_never_overridden(self):
        opts = EncodingOptions(charset=Charset.EBCDIC, endian=Endian.LITTLE)
        assert opts.resolved_endian is Endian.LITTLE


class TestCaveats:
    def test_a_fully_modelled_layout_reports_nothing(self):
        assert (
            encoding_caveats(specs_for("       01  R.\n           05  A PIC X(4).\n"))
            == []
        )

    def test_synchronized_is_reported_rather_than_silently_ignored(self):
        specs = specs_for(
            "       01  R.\n           05  A PIC S9(4) COMP SYNCHRONIZED.\n"
        )
        assert any("SYNCHRONIZED" in c for c in encoding_caveats(specs))

    def test_float_usages_disclose_that_they_are_not_hexadecimal_float(self):
        specs = specs_for("       01  R.\n           05  A COMP-1.\n")
        assert any("IEEE 754" in c for c in encoding_caveats(specs))

    def test_occurs_depending_on_discloses_the_maximum_length_assumption(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  N PIC 9(2).\n"
            "           05  T OCCURS 1 TO 5 TIMES DEPENDING ON N PIC X(2).\n"
        )
        assert any("DEPENDING ON" in c for c in encoding_caveats(specs))


class TestHexDump:
    def test_header_states_the_length_and_every_encoding_choice(self):
        specs = specs_for("       01  R.\n           05  A PIC X(4).\n")
        text = hex_dump(specs, [["ABCD"]], EBCDIC, record_name="R")
        assert "* record layout: R" in text
        assert "* record length: 4 bytes" in text
        assert "charset: ebcdic" in text

    def test_caveats_appear_in_the_header_rather_than_being_dropped(self):
        specs = specs_for(
            "       01  R.\n           05  A PIC S9(4) COMP SYNCHRONIZED.\n"
        )
        text = hex_dump(specs, [["1"]], EncodingOptions())
        assert "* caveat: SYNCHRONIZED" in text

    def test_each_field_is_shown_at_its_own_offset(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  A PIC X(4).\n"
            "           05  B PIC S9(4) COMP.\n"
        )
        text = hex_dump(specs, [["ABCD", "331"]], EncodingOptions())
        assert "000000" in text and "000004" in text
        assert "01 4B" in text

    def test_long_fields_wrap_onto_continuation_lines(self):
        specs = specs_for("       01  R.\n           05  A PIC X(20).\n")
        text = hex_dump(specs, [["A" * 20]], EncodingOptions())
        # 20 bytes at 8 per line is three lines for the one field.
        assert text.count("41 41") >= 3

    def test_one_block_per_record(self):
        specs = specs_for("       01  R.\n           05  A PIC X(2).\n")
        text = hex_dump(specs, [["AB"], ["CD"]], EncodingOptions())
        assert "record 1 of 2" in text and "record 2 of 2" in text


class TestBlankWhenZero:
    def test_zero_is_written_as_spaces(self):
        spec = one_spec("D PIC 9(3) BLANK WHEN ZERO.")
        assert spec.blank_when_zero
        assert encode_field(spec, "0", EncodingOptions()) == b"   "
        assert encode_field(spec, "", EncodingOptions()) == b"   "
        assert encode_field(spec, "0", EBCDIC) == b"\x40\x40\x40"

    def test_non_zero_is_written_as_digits(self):
        spec = one_spec("D PIC 9(3) BLANK WHEN ZERO.")
        assert encode_field(spec, "12", EncodingOptions()) == b"012"

    def test_numeric_edited_zero_is_blank(self):
        spec = one_spec("E PIC ZZ9.99 BLANK WHEN ZERO.")
        assert encode_field(spec, "0.00", EncodingOptions()) == b"      "
        assert encode_field(spec, "3.50", EncodingOptions()) == b"  3.50"

    def test_without_the_clause_zero_is_digits(self):
        spec = one_spec("D PIC 9(3).")
        assert encode_field(spec, "0", EncodingOptions()) == b"000"


class TestNationalCaveat:
    def test_pic_n_is_flagged_as_single_byte_text(self):
        specs = specs_for(
            "       01  R.\n"
            "           05  N1 PIC N(3).\n"
            "           05  N2 PIC N(2) USAGE NATIONAL.\n"
            "           05  X1 PIC X(2).\n"
        )
        caveats = [c for c in encoding_caveats(specs) if "national" in c]
        assert len(caveats) == 1
        assert "UTF-16" in caveats[0]
        assert "R.N1" in caveats[0] and "R.N2" in caveats[0]
        assert "X1" not in caveats[0]

    def test_no_national_data_no_caveat(self):
        specs = specs_for("       01  R.\n           05  X1 PIC X(2).\n")
        assert not any("national" in c for c in encoding_caveats(specs))
