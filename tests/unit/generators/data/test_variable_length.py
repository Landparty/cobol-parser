"""Fixed- vs variable-length record generation.

A copybook says how long a record *can* be; it does not say whether the file
holding it is RECFM=F (every record the layout's full length) or RECFM=V
(each record only as long as its own ``OCCURS ... DEPENDING ON`` counter
makes it, behind an RDW).  These tests pin both readings of the same layout,
and the invariant tying them together: the fixed image is exactly the
variable image with every occurrence present and no RDW.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data.copybook import (
    CopybookDataGenerator,
    parse_copybook_records,
)
from cobolparser.generators.data.encoding import (
    MAX_VARIABLE_RECORD,
    RDW_SIZE,
    EncodingOptions,
    RecordEncodingError,
    RecordFormat,
    encode_rdw,
    encode_record,
    encoding_caveats,
    minimum_record_length,
    record_length,
    row_record_length,
)
from cobolparser.generators.data.layout import (
    VaryingLength,
    flatten_record,
    occurrence_count,
    present_indexes,
    unresolved_odo_counters,
)
from cobolparser.generators.data.options import DataGeneratorOptions

# One counter, one table, and a field *after* the table -- which is the case
# that separates a real variable-length record from a truncated one: ORD-TOTAL
# has to move up into the space the absent occurrences would have taken.
ORDER_COPYBOOK = """
       01  ORDER-REC.
           05  ORD-ID            PIC X(4).
           05  ORD-LINE-COUNT    PIC 9(2).
           05  ORD-LINES OCCURS 1 TO 4 TIMES
                         DEPENDING ON ORD-LINE-COUNT.
               10  ORD-SKU       PIC X(3).
           05  ORD-TOTAL         PIC 9(5).
"""

FIXED_COPYBOOK = """
       01  CUST-REC.
           05  CUST-ID           PIC X(6).
           05  CUST-NAME         PIC X(10).
"""

FIXED = EncodingOptions()
VARIABLE = EncodingOptions(record_format=RecordFormat.VARIABLE)
BARE = EncodingOptions(record_format=RecordFormat.VARIABLE_BARE)
AUTO = EncodingOptions(record_format=RecordFormat.AUTO)


def specs_for(copybook: str):
    """Flatten *copybook* with byte-complete (record-image) options."""
    record = parse_copybook_records(copybook)[0]
    return flatten_record(record, DataGeneratorOptions().for_record_image())


def order_row(count: str) -> list[str]:
    """One ORDER-REC row whose counter says *count*, all four SKUs filled."""
    return ["ORD1", count, "AAA", "BBB", "CCC", "DDD", "00042"]


# The worked example from mainframestechhelp.com's "reading a VL PS file
# sequentially" tutorial, which is where this second mechanism came from: the
# record layout is an ordinary fixed one -- no table, nothing subordinate to a
# counter -- and what varies is how many of its bytes each record carries.
# EMPREC-LEN lives in WORKING-STORAGE, so the length is nowhere in the record;
# it travels in the RDW.
EMPVL_PROGRAM = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPVL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPFILE ASSIGN TO INPUT01
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE  IS SEQUENTIAL
               FILE STATUS  IS WS-FS1.
       DATA DIVISION.
       FILE SECTION.
       FD  EMPFILE
           RECORD VARYING FROM 47 TO 80 CHARACTERS
                  DEPENDING ON EMPREC-LEN
           RECORDING MODE IS V.
       01  EMP-RECORD80.
           05  EMP-ID          PIC X(6).
           05  EMP-NAME        PIC X(25).
           05  EMP-DEPT        PIC X(10).
           05  EMP-SALARY      PIC 9(6).
           05  EMP-COMMENT     PIC X(33).
       WORKING-STORAGE SECTION.
       01  WS-FS1              PIC XX.
       01  EMPREC-LEN          PIC S9(4) COMP.
       PROCEDURE DIVISION.
           CONTINUE.
"""


def empvl(**options):
    """A dataset for the EMPVL program's FD-varying record."""
    opts = DataGeneratorOptions(**{"rows": 6, "seed": 7, **options})
    return CopybookDataGenerator(opts.for_record_image()).generate_from_source(
        EMPVL_PROGRAM, filename="EMPVL.cbl"
    )


class TestFdRecordVarying:
    """`FD ... RECORD VARYING FROM min TO max` with no ODO table anywhere.

    The second, independent way a COBOL record's length varies -- and the one
    an OCCURS DEPENDING ON walk cannot see, because the declaration is on the
    FD rather than in the record.
    """

    def test_the_fd_clause_is_read_off_the_record(self):
        dataset = empvl()
        assert dataset.varying == VaryingLength(47, 80, "EMPREC-LEN")

    def test_a_record_with_no_table_still_counts_as_variable(self):
        dataset = empvl()
        assert not any(spec.odo_controls for spec in dataset.fields)
        assert dataset.is_variable_length

    def test_every_record_lands_inside_the_declared_range(self):
        dataset = empvl(rows=40)
        assert all(47 <= length <= 80 for length in dataset.declared_lengths)

    def test_the_lengths_actually_vary(self):
        assert len(set(empvl(rows=40).declared_lengths)) > 1

    def test_the_written_record_is_cut_to_its_declared_length(self):
        dataset = empvl()
        raw = dataset.to_records(BARE)
        offset = 0
        for length in dataset.declared_lengths:
            assert raw[offset : offset + length]
            offset += length
        assert offset == len(raw)

    def test_the_cut_can_fall_mid_field(self):
        # EMP-COMMENT starts at byte 47, so any declared length below 80
        # ends part-way through it -- which is exactly what a program reading
        # EMP-RECORD80(1:EMPREC-LEN) sees.
        dataset = empvl(rows=40)
        assert any(47 < length < 80 for length in dataset.declared_lengths)

    def test_the_rdw_carries_the_declared_length(self):
        dataset = empvl()
        raw = dataset.to_records(VARIABLE)
        offset = 0
        for length in dataset.declared_lengths:
            assert int.from_bytes(raw[offset : offset + 2], "big") == length + RDW_SIZE
            offset += length + RDW_SIZE
        assert offset == len(raw)

    def test_auto_picks_variable_for_an_fd_varying_record(self):
        dataset = empvl()
        assert (
            AUTO.resolved_format(dataset.fields, varying=True) is RecordFormat.VARIABLE
        )

    def test_fixed_writes_full_length_records_and_says_so(self):
        dataset = empvl()
        raw = dataset.to_records(FIXED)
        assert len(raw) == 6 * record_length(dataset.fields)
        caveats = encoding_caveats(dataset.fields, FIXED, varying=dataset.varying)
        assert any("fixed-length output was asked for" in c for c in caveats)

    def test_the_minimum_comes_from_the_fd_not_the_layout(self):
        dataset = empvl()
        assert dataset.minimum_record_length() == 47
        assert dataset.record_length() == 80

    def test_reported_lengths_match_the_bytes_written(self):
        dataset = empvl()
        for opts in (VARIABLE, BARE, FIXED):
            reported = dataset.record_lengths(opts)
            raw = dataset.to_records(opts)
            assert sum(reported) == len(raw)

    def test_the_same_seed_reproduces_the_lengths_too(self):
        assert empvl().declared_lengths == empvl().declared_lengths

    def test_record_contains_min_to_max_is_the_same_declaration(self):
        # RECORD CONTAINS 47 TO 80 says the same thing without the VARYING
        # keyword, and the parser records it identically.
        source = EMPVL_PROGRAM.replace(
            "RECORD VARYING FROM 47 TO 80 CHARACTERS\n"
            "                  DEPENDING ON EMPREC-LEN",
            "RECORD CONTAINS 47 TO 80 CHARACTERS",
        )
        opts = DataGeneratorOptions(rows=4, seed=7).for_record_image()
        dataset = CopybookDataGenerator(opts).generate_from_source(
            source, filename="EMPVL.cbl"
        )
        assert dataset.varying == VaryingLength(47, 80, None)


class TestExplicitVaryingRange:
    """`DataGeneratorOptions.record_varying`, for a copybook with no FD."""

    def test_an_explicit_range_makes_a_plain_copybook_vary(self):
        options = DataGeneratorOptions(
            rows=20, seed=3, record_varying=(10, 16)
        ).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(FIXED_COPYBOOK)
        assert dataset.varying == VaryingLength(10, 16, None)
        assert all(10 <= n <= 16 for n in dataset.declared_lengths)

    def test_it_overrides_the_fd_when_both_are_present(self):
        dataset = empvl(record_varying=(50, 52))
        assert dataset.varying == VaryingLength(50, 52, None)
        assert all(50 <= n <= 52 for n in dataset.declared_lengths)

    def test_a_range_beyond_the_record_is_clamped_to_it(self):
        # CUST-REC is 16 bytes; an FD promising 40 cannot be honoured by
        # padding, because the bytes were never declared.
        options = DataGeneratorOptions(
            rows=5, seed=3, record_varying=(4, 40)
        ).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(FIXED_COPYBOOK)
        assert dataset.varying == VaryingLength(4, 16, None)

    def test_a_degenerate_range_is_not_a_varying_record(self):
        options = DataGeneratorOptions(
            rows=5, seed=3, record_varying=(16, 16)
        ).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(FIXED_COPYBOOK)
        assert dataset.varying is None
        assert dataset.declared_lengths is None

    @pytest.mark.parametrize("bad", [(-1, 5), (9, 4)])
    def test_a_nonsense_range_is_refused(self, bad):
        with pytest.raises(ValueError):
            DataGeneratorOptions(record_varying=bad)

    def test_the_depending_on_field_is_filled_in_when_it_is_in_the_record(self):
        # Normally the length item is a WORKING-STORAGE counter, so there is
        # nothing to write; when a copybook does put it in the record,
        # leaving the generated value would contradict the record's own
        # length.
        source = """
       01  MSG-REC.
           05  MSG-LEN         PIC 9(3).
           05  MSG-TEXT        PIC X(40).
"""
        record = parse_copybook_records(source)[0]
        record.set_metadata(
            "fd_clauses",
            {
                "record": {
                    "varying": True,
                    "min": 10,
                    "max": 30,
                    "depending_on": "MSG-LEN",
                }
            },
        )
        options = DataGeneratorOptions(rows=8, seed=4).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_record(record)
        column = dataset.header.index("MSG-LEN")
        assert [int(row[column]) for row in dataset.rows] == dataset.declared_lengths


class TestBothMechanismsAtOnce:
    """A record can declare both, and then only one of them can decide.

    The table does: its count is real data saying how many occurrences this
    record holds, while an FD range only bounds the length. Cutting the
    table-trimmed body to an FD-drawn length on top would slice a table
    mid-occurrence at an unrelated offset. Every surface has to agree on
    that, or the caveat is a lie -- which is what these pin.
    """

    @staticmethod
    def both():
        """A dataset whose record has an ODO table *and* an FD range."""
        record = parse_copybook_records(ORDER_COPYBOOK)[0]
        record.set_metadata(
            "fd_clauses",
            {
                "record": {
                    "varying": True,
                    "min": 5,
                    "max": 20,
                    "depending_on": "ORD-LINE-COUNT",
                }
            },
        )
        options = DataGeneratorOptions(rows=6, seed=3).for_record_image()
        return CopybookDataGenerator(options).generate_from_record(record)

    def test_the_caveat_says_the_table_decides(self):
        specs = specs_for(ORDER_COPYBOOK)
        caveats = encoding_caveats(specs, VARIABLE, varying=VaryingLength(10, 20))
        assert any("the table decides each record's length" in c for c in caveats)

    def test_no_length_is_drawn_for_a_record_a_table_already_sizes(self):
        dataset = self.both()
        assert dataset.varying is not None  # still recorded, for the caveat
        assert dataset.declared_lengths is None

    def test_the_minimum_comes_from_the_table_not_the_fd_floor(self):
        dataset = self.both()
        assert dataset.minimum_record_length() == minimum_record_length(dataset.fields)
        assert dataset.minimum_record_length() != dataset.varying.minimum

    def test_reported_lengths_still_match_the_bytes_written(self):
        dataset = self.both()
        for opts in (VARIABLE, BARE, FIXED):
            assert sum(dataset.record_lengths(opts)) == len(dataset.to_records(opts))

    def test_a_data_length_passed_directly_is_ignored_for_an_odo_layout(self):
        # Defence in depth: the generator never passes both, but a direct
        # caller could, and the caveat's promise has to hold there too.
        specs = specs_for(ORDER_COPYBOOK)
        row = order_row("02")
        assert encode_record(specs, row, BARE, data_length=3) == encode_record(
            specs, row, BARE
        )
        assert row_record_length(specs, row, BARE, data_length=3) == row_record_length(
            specs, row, BARE
        )

    def test_a_data_length_is_still_honoured_without_a_table(self):
        specs = specs_for(FIXED_COPYBOOK)
        row = ["C00001", "ACME"]
        assert len(encode_record(specs, row, BARE, data_length=9)) == 9

    def test_the_hex_dump_reports_the_layouts_span_not_the_fd_range(self):
        dataset = self.both()
        header = dataset.to_hex_dump(VARIABLE).splitlines()[2]
        low = minimum_record_length(dataset.fields) + RDW_SIZE
        high = record_length(dataset.fields) + RDW_SIZE
        assert f"record length: {low} to {high} bytes" in header
        # The FD clause is still shown, as metadata rather than as the span.
        assert any(
            "FD RECORD VARYING FROM 5 TO 20" in line
            for line in dataset.to_hex_dump(VARIABLE).splitlines()
        )


class TestOdoLayout:
    def test_a_table_field_records_the_dimension_its_counter_governs(self):
        specs = {s.column: s for s in specs_for(ORDER_COPYBOOK)}
        (control,) = specs["ORD-SKU(1)"].odo_controls
        assert control.depending_on == "ORD-LINE-COUNT"
        assert control.subscript_index == 0
        assert (control.min_times, control.max_times) == (1, 4)

    def test_fields_outside_the_table_carry_no_control(self):
        specs = {s.column: s for s in specs_for(ORDER_COPYBOOK)}
        assert specs["ORD-ID"].odo_controls == ()
        assert specs["ORD-TOTAL"].odo_controls == ()

    def test_the_counter_field_learns_the_bounds_it_controls(self):
        specs = {s.column: s for s in specs_for(ORDER_COPYBOOK)}
        assert specs["ORD-LINE-COUNT"].odo_counter_bounds == (1, 4)
        assert specs["ORD-ID"].odo_counter_bounds is None

    def test_a_layout_without_a_depending_on_table_has_no_controls(self):
        assert all(not s.odo_controls for s in specs_for(FIXED_COPYBOOK))

    def test_a_declared_zero_lower_bound_survives(self):
        # `occurs.min_times or 1` would read OCCURS 0 TO n as a minimum of 1,
        # and an empty table would never be generated.
        copybook = ORDER_COPYBOOK.replace("OCCURS 1 TO 4", "OCCURS 0 TO 4")
        specs = {s.column: s for s in specs_for(copybook)}
        assert specs["ORD-LINE-COUNT"].odo_counter_bounds == (0, 4)

    def test_disjoint_bounds_collapse_to_the_tightest_maximum(self):
        # One counter, two tables that cannot both be satisfied: A holds at
        # most 3, B needs at least 5. Taking the larger *minimum* would name
        # occurrence 5 of a 3-occurrence table -- the over-counting direction,
        # which is the one that describes bytes the record does not have.
        copybook = """
       01  R.
           05  N PIC 9.
           05  A OCCURS 1 TO 3 TIMES
                       DEPENDING ON N.
               10 AV PIC X.
           05  B OCCURS 5 TO 8 TIMES
                       DEPENDING ON N.
               10 BV PIC X.
"""
        specs = {s.column: s for s in specs_for(copybook)}
        assert specs["N"].odo_counter_bounds == (3, 3)

    def test_overlapping_bounds_still_intersect(self):
        copybook = """
       01  R.
           05  N PIC 9.
           05  A OCCURS 1 TO 6 TIMES
                       DEPENDING ON N.
               10 AV PIC X.
           05  B OCCURS 3 TO 9 TIMES
                       DEPENDING ON N.
               10 BV PIC X.
"""
        specs = {s.column: s for s in specs_for(copybook)}
        assert specs["N"].odo_counter_bounds == (3, 6)

    def test_max_occurs_clamps_the_bounds_to_what_was_flattened(self):
        # A counter allowed to name occurrence 4 of a table flattened to 2
        # would describe bytes no FieldSpec covers.
        record = parse_copybook_records(ORDER_COPYBOOK)[0]
        options = DataGeneratorOptions(max_occurs=2, include_filler=True)
        specs = {s.column: s for s in flatten_record(record, options)}
        assert specs["ORD-LINE-COUNT"].odo_counter_bounds == (1, 2)


class TestPresentIndexes:
    def test_occurrences_past_the_counter_drop_out(self):
        specs = specs_for(ORDER_COPYBOOK)
        kept = [specs[i].column for i in present_indexes(specs, order_row("02"))]
        assert kept == [
            "ORD-ID",
            "ORD-LINE-COUNT",
            "ORD-SKU(1)",
            "ORD-SKU(2)",
            "ORD-TOTAL",
        ]

    def test_a_full_count_keeps_every_field(self):
        specs = specs_for(ORDER_COPYBOOK)
        assert present_indexes(specs, order_row("04")) == list(range(len(specs)))

    def test_a_count_above_the_maximum_is_clamped_not_honoured(self):
        specs = specs_for(ORDER_COPYBOOK)
        assert present_indexes(specs, order_row("99")) == list(range(len(specs)))

    def test_a_count_below_the_minimum_is_clamped_up(self):
        specs = specs_for(ORDER_COPYBOOK)
        kept = [specs[i].column for i in present_indexes(specs, order_row("00"))]
        assert "ORD-SKU(1)" in kept
        assert "ORD-SKU(2)" not in kept

    @pytest.mark.parametrize("cell", ["", "   ", "not-a-number"])
    def test_an_unusable_counter_reserves_the_whole_table(self, cell):
        specs = specs_for(ORDER_COPYBOOK)
        assert present_indexes(specs, order_row(cell)) == list(range(len(specs)))

    def test_a_layout_without_odo_keeps_every_field(self):
        specs = specs_for(FIXED_COPYBOOK)
        assert present_indexes(specs, ["A", "B"]) == [0, 1]

    def test_occurrence_count_clamps_into_the_declared_bounds(self):
        (control,) = specs_for(ORDER_COPYBOOK)[2].odo_controls
        assert occurrence_count(control, {"ORD-LINE-COUNT": "3"}) == 3
        assert occurrence_count(control, {"ORD-LINE-COUNT": "9"}) == 4
        assert occurrence_count(control, {}) == 4


class TestComplexOdo:
    """A ``DEPENDING ON`` table nested inside an ordinary ``OCCURS``.

    IBM's *complex ODO*: the counter is subscripted too, so each outer
    occurrence carries its own count.  Resolving the counter by name alone
    would collapse them and trim every outer occurrence to the last one's
    count.
    """

    COPYBOOK = """
       01  R.
           05  G OCCURS 2 TIMES.
               10  CNT PIC 9.
               10  TAB OCCURS 1 TO 3 TIMES
                            DEPENDING ON CNT.
                   15  V PIC X.
"""

    def test_the_nested_control_names_the_inner_dimension(self):
        specs = {s.column: s for s in specs_for(self.COPYBOOK)}
        (control,) = specs["V(1,1)"].odo_controls
        assert (control.depending_on, control.subscript_index) == ("CNT", 1)

    def test_each_outer_occurrence_follows_its_own_counter(self):
        specs = specs_for(self.COPYBOOK)
        row = ["1", "a", "b", "c", "3", "d", "e", "f"]
        kept = [specs[i].column for i in present_indexes(specs, row)]
        assert kept == ["CNT(1)", "V(1,1)", "CNT(2)", "V(2,1)", "V(2,2)", "V(2,3)"]

    def test_the_record_is_as_long_as_both_counts_make_it(self):
        specs = specs_for(self.COPYBOOK)
        row = ["1", "a", "b", "c", "3", "d", "e", "f"]
        assert encode_record(specs, row, BARE) == b"1a3def"


class TestCounterGeneration:
    def test_a_generated_counter_always_names_a_real_occurrence(self):
        options = DataGeneratorOptions(rows=60, seed=11).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        column = dataset.header.index("ORD-LINE-COUNT")
        counts = {int(row[column]) for row in dataset.rows}
        assert counts <= {1, 2, 3, 4}

    def test_the_count_actually_varies_rather_than_pinning_to_the_maximum(self):
        options = DataGeneratorOptions(rows=60, seed=11).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        column = dataset.header.index("ORD-LINE-COUNT")
        assert len({row[column] for row in dataset.rows}) > 1

    def test_a_declared_value_inside_the_bounds_still_wins(self):
        copybook = ORDER_COPYBOOK.replace(
            "05  ORD-LINE-COUNT    PIC 9(2).",
            "05  ORD-LINE-COUNT    PIC 9(2) VALUE 3.",
        )
        options = DataGeneratorOptions(rows=5, seed=3).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(copybook)
        column = dataset.header.index("ORD-LINE-COUNT")
        assert {row[column] for row in dataset.rows} == {"3"}

    def test_unique_fields_cannot_push_a_counter_out_of_range(self):
        # The unique-value fallback is a plain counter, which for a narrow
        # table would name occurrences the record does not contain.
        options = DataGeneratorOptions(
            rows=40, seed=3, unique_fields=("ORD-LINE-COUNT",)
        ).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        column = dataset.header.index("ORD-LINE-COUNT")
        assert all(1 <= int(row[column]) <= 4 for row in dataset.rows)

    def test_a_declared_value_the_table_cannot_hold_is_overridden(self):
        copybook = ORDER_COPYBOOK.replace(
            "05  ORD-LINE-COUNT    PIC 9(2).",
            "05  ORD-LINE-COUNT    PIC 9(2) VALUE 40.",
        )
        options = DataGeneratorOptions(rows=5, seed=3).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(copybook)
        column = dataset.header.index("ORD-LINE-COUNT")
        assert all(1 <= int(row[column]) <= 4 for row in dataset.rows)


class TestRdw:
    def test_the_length_includes_the_rdw_itself(self):
        assert encode_rdw(80) == bytes.fromhex("00540000")

    def test_the_reserved_halfword_is_zero(self):
        assert encode_rdw(1)[2:] == b"\x00\x00"

    def test_it_is_big_endian_whatever_the_record_is(self):
        assert encode_rdw(0x0102 - RDW_SIZE)[:2] == b"\x01\x02"

    def test_a_record_too_long_to_describe_is_refused(self):
        with pytest.raises(RecordEncodingError, match="spanned"):
            encode_rdw(MAX_VARIABLE_RECORD)


class TestEncodeRecord:
    def test_fixed_writes_every_occurrence(self):
        specs = specs_for(ORDER_COPYBOOK)
        assert encode_record(specs, order_row("02"), FIXED) == (
            b"ORD1" b"02" b"AAA" b"BBB" b"CCC" b"DDD" b"00042"
        )

    def test_variable_drops_the_unused_occurrences_and_closes_the_gap(self):
        specs = specs_for(ORDER_COPYBOOK)
        raw = encode_record(specs, order_row("02"), VARIABLE)
        # 4 + 2 + 2*3 + 5 = 17 data bytes, + 4 for the RDW = 21 = 0x15.
        assert raw == bytes.fromhex("00150000") + b"ORD102AAABBB00042"

    def test_variable_bare_is_the_same_record_without_the_rdw(self):
        specs = specs_for(ORDER_COPYBOOK)
        framed = encode_record(specs, order_row("02"), VARIABLE)
        assert encode_record(specs, order_row("02"), BARE) == framed[RDW_SIZE:]

    def test_a_full_count_reproduces_the_fixed_image_byte_for_byte(self):
        specs = specs_for(ORDER_COPYBOOK)
        row = order_row("04")
        assert encode_record(specs, row, BARE) == encode_record(specs, row, FIXED)

    def test_a_fixed_length_layout_encodes_identically_under_every_format(self):
        specs = specs_for(FIXED_COPYBOOK)
        row = ["C00001", "ACME"]
        fixed = encode_record(specs, row, FIXED)
        assert encode_record(specs, row, BARE) == fixed
        assert encode_record(specs, row, VARIABLE) == encode_rdw(len(fixed)) + fixed

    def test_row_length_disagreeing_with_the_layout_is_still_refused(self):
        specs = specs_for(ORDER_COPYBOOK)
        with pytest.raises(RecordEncodingError, match="cells"):
            encode_record(specs, ["ORD1"], VARIABLE)


class TestResolvedFormat:
    def test_auto_picks_variable_for_a_layout_with_a_depending_on_table(self):
        specs = specs_for(ORDER_COPYBOOK)
        assert AUTO.resolved_format(specs) is RecordFormat.VARIABLE

    def test_auto_picks_fixed_for_a_layout_without_one(self):
        specs = specs_for(FIXED_COPYBOOK)
        assert AUTO.resolved_format(specs) is RecordFormat.FIXED

    def test_an_explicit_format_is_never_second_guessed(self):
        assert FIXED.resolved_format(specs_for(ORDER_COPYBOOK)) is RecordFormat.FIXED

    def test_the_default_is_fixed(self):
        assert EncodingOptions().record_format is RecordFormat.FIXED

    def test_only_the_trimmed_formats_report_is_variable(self):
        assert RecordFormat.VARIABLE.is_variable
        assert RecordFormat.VARIABLE_BARE.is_variable
        assert not RecordFormat.FIXED.is_variable
        assert not RecordFormat.AUTO.is_variable


class TestRecordLengths:
    def test_record_length_is_the_maximum(self):
        assert record_length(specs_for(ORDER_COPYBOOK)) == 4 + 2 + 4 * 3 + 5

    def test_minimum_record_length_holds_one_occurrence(self):
        assert minimum_record_length(specs_for(ORDER_COPYBOOK)) == 4 + 2 + 3 + 5

    def test_the_two_agree_for_a_fixed_length_layout(self):
        specs = specs_for(FIXED_COPYBOOK)
        assert minimum_record_length(specs) == record_length(specs)

    def test_a_rows_length_matches_the_bytes_it_encodes_to(self):
        specs = specs_for(ORDER_COPYBOOK)
        for count in ("01", "02", "03", "04"):
            row = order_row(count)
            for opts in (FIXED, VARIABLE, BARE):
                assert row_record_length(specs, row, opts) == len(
                    encode_record(specs, row, opts)
                )

    def test_the_dataset_reports_a_length_per_row(self):
        options = DataGeneratorOptions(rows=8, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        lengths = dataset.record_lengths(VARIABLE)
        assert len(lengths) == 8
        assert set(lengths) == {
            len(encode_record(dataset.fields, row, VARIABLE)) for row in dataset.rows
        }

    def test_the_dataset_reports_the_same_bounds_as_the_layout(self):
        options = DataGeneratorOptions(rows=2, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        assert dataset.record_length() == record_length(dataset.fields)
        assert dataset.minimum_record_length() == minimum_record_length(dataset.fields)
        assert dataset.minimum_record_length() < dataset.record_length()

    def test_a_variable_layout_says_so(self):
        options = DataGeneratorOptions(rows=1, seed=5).for_record_image()
        generator = CopybookDataGenerator(options)
        assert generator.generate_from_source(ORDER_COPYBOOK).is_variable_length
        assert not generator.generate_from_source(FIXED_COPYBOOK).is_variable_length


class TestCaveats:
    def test_fixed_output_says_the_table_is_written_at_its_maximum(self):
        caveats = encoding_caveats(specs_for(ORDER_COPYBOOK), FIXED)
        assert any("maximum length" in c for c in caveats)

    def test_variable_output_has_nothing_to_apologise_for(self):
        caveats = encoding_caveats(specs_for(ORDER_COPYBOOK), VARIABLE)
        assert not any("maximum length" in c for c in caveats)

    def test_omitting_the_options_keeps_the_fixed_length_reading(self):
        assert encoding_caveats(specs_for(ORDER_COPYBOOK)) == encoding_caveats(
            specs_for(ORDER_COPYBOOK), FIXED
        )

    def test_a_counter_outside_the_record_is_reported_not_assumed(self):
        copybook = ORDER_COPYBOOK.replace(
            "DEPENDING ON ORD-LINE-COUNT", "DEPENDING ON WS-N"
        )
        specs = specs_for(copybook)
        assert unresolved_odo_counters(specs) == ["WS-N"]
        assert any(
            "not part of the record" in c for c in encoding_caveats(specs, VARIABLE)
        )

    def test_a_resolvable_counter_is_not_reported(self):
        assert unresolved_odo_counters(specs_for(ORDER_COPYBOOK)) == []


class TestHexDump:
    def test_the_header_names_the_format_and_the_length_range(self):
        options = DataGeneratorOptions(rows=2, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        header = dataset.to_hex_dump(VARIABLE).splitlines()
        assert "record format: variable (RECFM=V/VB)" in header[1]
        assert "record length: 18 to 27 bytes (RDW included)" in header[2]

    def test_the_rdw_gets_a_row_of_its_own_so_offsets_stay_true(self):
        options = DataGeneratorOptions(rows=1, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        lines = dataset.to_hex_dump(VARIABLE).splitlines()
        rdw_line = next(line for line in lines if "(RDW)" in line)
        assert rdw_line.startswith("000000     4")
        first_field = next(line for line in lines if "ORD-ID" in line and "|" in line)
        assert first_field.startswith("000004")

    def test_the_fixed_dump_has_no_rdw_row(self):
        options = DataGeneratorOptions(rows=1, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        assert "(RDW)" not in dataset.to_hex_dump(FIXED)

    def test_each_record_header_carries_its_own_length(self):
        options = DataGeneratorOptions(rows=4, seed=5).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        dump = dataset.to_hex_dump(VARIABLE)
        for index, length in enumerate(dataset.record_lengths(VARIABLE), start=1):
            assert f"--- record {index} of 4: {length} bytes ---" in dump


class TestDeterminism:
    def test_the_same_seed_writes_the_same_variable_length_bytes(self):
        def build() -> bytes:
            options = DataGeneratorOptions(rows=20, seed=99).for_record_image()
            dataset = CopybookDataGenerator(options).generate_from_source(
                ORDER_COPYBOOK
            )
            return dataset.to_records(VARIABLE)

        assert build() == build()

    def test_the_variable_file_is_shorter_than_the_fixed_one(self):
        options = DataGeneratorOptions(rows=20, seed=99).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        assert len(dataset.to_records(VARIABLE)) < len(dataset.to_records(FIXED))

    def test_a_separator_still_follows_every_variable_record(self):
        options = DataGeneratorOptions(rows=3, seed=99).for_record_image()
        dataset = CopybookDataGenerator(options).generate_from_source(ORDER_COPYBOOK)
        raw = dataset.to_records(
            EncodingOptions(
                record_format=RecordFormat.VARIABLE_BARE, record_separator=b"\n"
            )
        )
        assert raw.count(b"\n") == 3
        assert raw.endswith(b"\n")
