from __future__ import annotations

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators.data.layout_offsets import compute_record_layout
from cobolparser.models.data_items import CobolDataItem


def _parse_record(data_division_body: str) -> CobolDataItem:
    source = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. LAYOUTTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{data_division_body}
       PROCEDURE DIVISION.
           STOP RUN.
"""
    result = parse_cobol(source, filename="layouttest.cbl", error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.ast is not None, result.errors
    assert result.errors == []
    section = result.ast.get_division("DATA").get_section_by_name("WORKING-STORAGE")
    return section.data_items[0]


class TestFlatRecord:
    def test_sequential_elementary_items_get_increasing_offsets(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-FIELD-A       PIC X(5).\n"
            "           05  WS-FIELD-B       PIC 9(3).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-REC"].byte_offset == 0
        assert by_name["WS-REC"].byte_length == 8
        assert by_name["WS-REC"].is_group is True

        assert by_name["WS-FIELD-A"].byte_offset == 0
        assert by_name["WS-FIELD-A"].byte_length == 5
        assert by_name["WS-FIELD-A"].picture == "X(5)"
        assert by_name["WS-FIELD-A"].usage == "DISPLAY"
        assert by_name["WS-FIELD-A"].is_group is False

        assert by_name["WS-FIELD-B"].byte_offset == 5
        assert by_name["WS-FIELD-B"].byte_length == 3
        assert by_name["WS-FIELD-B"].qualified_name == "WS-REC.WS-FIELD-B"
        assert by_name["WS-FIELD-B"].parent_qualified_name == "WS-REC"

    def test_comp3_field_uses_packed_byte_length_not_display_digits(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-AMOUNT        PIC S9(7)V99 COMP-3.\n"
        )
        layout = compute_record_layout(record)
        field = next(item for item in layout if item.name == "WS-AMOUNT")
        # 9 total digits -> (9+1)//2 = 5 bytes, not 9 DISPLAY characters.
        assert field.byte_length == 5

    def test_77_level_record_is_its_own_flat_item(self):
        record = _parse_record("       77  WS-COUNTER          PIC 9(4) COMP.\n")
        layout = compute_record_layout(record)
        assert len(layout) == 1
        assert layout[0].name == "WS-COUNTER"
        assert layout[0].byte_offset == 0
        assert layout[0].byte_length == 2  # COMP, <=4 digits -> 2 bytes
        assert layout[0].is_group is False


class TestNestedGroups:
    def test_group_length_is_sum_of_children_and_children_offsets_are_correct(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-HEADER.\n"
            "               10  WS-ID        PIC 9(4).\n"
            "               10  WS-NAME      PIC X(10).\n"
            "           05  WS-TRAILER       PIC X(2).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-HEADER"].is_group is True
        assert by_name["WS-HEADER"].byte_offset == 0
        assert by_name["WS-HEADER"].byte_length == 14  # 4 + 10

        assert by_name["WS-ID"].byte_offset == 0
        assert by_name["WS-ID"].byte_length == 4
        assert by_name["WS-ID"].qualified_name == "WS-REC.WS-HEADER.WS-ID"

        assert by_name["WS-NAME"].byte_offset == 4
        assert by_name["WS-NAME"].byte_length == 10

        assert by_name["WS-TRAILER"].byte_offset == 14
        assert by_name["WS-REC"].byte_length == 16


class TestRedefines:
    def test_redefines_shares_offset_and_advances_past_the_larger_alternative(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-ORIGINAL      PIC X(4).\n"
            "           05  WS-REDEF REDEFINES WS-ORIGINAL PIC 9(6).\n"
            "           05  WS-AFTER         PIC X(2).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-ORIGINAL"].byte_offset == 0
        assert by_name["WS-ORIGINAL"].byte_length == 4
        assert by_name["WS-REDEF"].byte_offset == 0
        assert by_name["WS-REDEF"].byte_length == 6
        assert by_name["WS-REDEF"].redefines_chain == ["WS-ORIGINAL"]
        # the slot's footprint is max(4, 6) = 6, not 4 -- WS-AFTER must
        # start after the *larger* alternative.
        assert by_name["WS-AFTER"].byte_offset == 6
        assert by_name["WS-REC"].byte_length == 8

    def test_three_way_redefines_chain_is_reported_in_order(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-BASE          PIC X(4).\n"
            "           05  WS-REDEF-1 REDEFINES WS-BASE PIC 9(4).\n"
            "           05  WS-REDEF-2 REDEFINES WS-REDEF-1 PIC X(4).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-REDEF-1"].redefines_chain == ["WS-BASE"]
        assert by_name["WS-REDEF-2"].redefines_chain == ["WS-REDEF-1", "WS-BASE"]
        assert by_name["WS-BASE"].byte_offset == by_name["WS-REDEF-1"].byte_offset == by_name["WS-REDEF-2"].byte_offset == 0


class TestOccurs:
    def test_elementary_occurs_reports_one_occurrence_length_but_advances_past_all(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-TABLE         PIC X(2) OCCURS 5 TIMES.\n"
            "           05  WS-AFTER         PIC X(3).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-TABLE"].byte_length == 2
        assert by_name["WS-TABLE"].occurs == {"min": 5, "max": 5}
        assert by_name["WS-AFTER"].byte_offset == 10  # 2 * 5

    def test_group_occurs_multiplies_the_whole_group_footprint(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-LINE-ITEM OCCURS 3 TIMES.\n"
            "               10  WS-CODE      PIC X(2).\n"
            "               10  WS-QTY       PIC 9(3).\n"
            "           05  WS-TOTAL         PIC 9(5).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-LINE-ITEM"].byte_length == 5  # 2 + 3, one occurrence
        assert by_name["WS-LINE-ITEM"].occurs == {"min": 3, "max": 3}
        assert by_name["WS-CODE"].byte_offset == 0
        assert by_name["WS-QTY"].byte_offset == 2
        # After 3 occurrences of the 5-byte group: 15 bytes.
        assert by_name["WS-TOTAL"].byte_offset == 15
        assert by_name["WS-REC"].byte_length == 20


class TestOccursDependingOn:
    # NOTE: fixed-format COBOL only recognizes columns 8-72 as the code
    # area -- columns 73-80 are the identification area and get silently
    # truncated by the lexer. "OCCURS 1 TO 10 TIMES DEPENDING ON
    # WS-COUNT." does not fit on one line at this indentation, so the
    # DEPENDING ON clause is wrapped onto a continuation line to stay
    # inside the code area (verified empirically: writing it on one
    # line silently drops "ON WS-COUNT.", parses as a fixed OCCURS 10,
    # and was the actual root cause of this test class's first failures).
    def test_odo_table_itself_has_a_known_offset(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-COUNT         PIC 9(3).\n"
            "           05  WS-TABLE         PIC X(2) OCCURS 1 TO 10 TIMES\n"
            "               DEPENDING ON WS-COUNT.\n"
            "           05  WS-AFTER         PIC X(4).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-TABLE"].byte_offset == 3
        assert by_name["WS-TABLE"].offset_ambiguous is False
        assert by_name["WS-TABLE"].occurs == {"min": 1, "max": 10}

    def test_everything_after_an_odo_table_is_flagged_ambiguous(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-COUNT         PIC 9(3).\n"
            "           05  WS-TABLE         PIC X(2) OCCURS 1 TO 10 TIMES\n"
            "               DEPENDING ON WS-COUNT.\n"
            "           05  WS-AFTER         PIC X(4).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["WS-AFTER"].offset_ambiguous is True
        assert by_name["WS-AFTER"].byte_offset is None
        # the record's own overall byte_length is likewise unknowable
        assert by_name["WS-REC"].offset_ambiguous is False  # the record root itself always starts at 0

    def test_odo_nested_inside_a_group_makes_the_groups_own_siblings_ambiguous(self):
        record = _parse_record(
            "       01  REC.\n"
            "           05  GROUP-WITH-ODO.\n"
            "               10  WS-COUNT     PIC 9(3).\n"
            "               10  WS-ITEMS     PIC X(2) OCCURS 1 TO 10 TIMES\n"
            "                   DEPENDING ON WS-COUNT.\n"
            "           05  AFTER-GROUP      PIC X(4).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        # The group itself, and its own direct children, still have
        # known offsets -- the ambiguity starts only once WS-ITEMS is
        # reached inside the group.
        assert by_name["GROUP-WITH-ODO"].byte_offset == 0
        assert by_name["GROUP-WITH-ODO"].offset_ambiguous is False
        assert by_name["WS-COUNT"].byte_offset == 0
        assert by_name["WS-COUNT"].offset_ambiguous is False
        assert by_name["WS-ITEMS"].byte_offset == 3
        assert by_name["WS-ITEMS"].offset_ambiguous is False

        # But AFTER-GROUP -- a sibling of the *group*, not of WS-ITEMS --
        # is data-dependent too, since it comes after a group whose size
        # is only known at runtime.
        assert by_name["AFTER-GROUP"].offset_ambiguous is True
        assert by_name["AFTER-GROUP"].byte_offset is None

    def test_odo_two_levels_deep_propagates_through_both_nesting_hops(self):
        # OUTER -> INNER -> WS-ITEMS (the ODO table). AFTER-INNER is one
        # hop from the ODO (a sibling of INNER, inside OUTER's own
        # sibling list); AFTER-OUTER is two hops out (a sibling of OUTER,
        # inside REC's own sibling list). Both must end up ambiguous --
        # propagation must not stop after a single level of nesting.
        record = _parse_record(
            "       01  REC.\n"
            "           05  OUTER.\n"
            "               10  INNER.\n"
            "                   15  WS-COUNT  PIC 9(3).\n"
            "                   15  WS-ITEMS  PIC X(2) OCCURS 1 TO 10\n"
            "                       TIMES DEPENDING ON WS-COUNT.\n"
            "               10  AFTER-INNER   PIC X(4).\n"
            "           05  AFTER-OUTER       PIC X(4).\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        # Known offsets right up to (and including) the ODO table itself.
        assert by_name["INNER"].offset_ambiguous is False
        assert by_name["WS-ITEMS"].offset_ambiguous is False

        # One hop out: AFTER-INNER, a sibling of INNER within OUTER.
        assert by_name["AFTER-INNER"].offset_ambiguous is True
        assert by_name["AFTER-INNER"].byte_offset is None

        # Two hops out: AFTER-OUTER, a sibling of OUTER within REC.
        assert by_name["AFTER-OUTER"].offset_ambiguous is True
        assert by_name["AFTER-OUTER"].byte_offset is None


class TestLevel88:
    def test_each_condition_name_gets_its_own_entry_with_its_own_values(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-STATUS        PIC X.\n"
            "               88  STATUS-ACTIVE     VALUE \"A\".\n"
            "               88  STATUS-INACTIVE   VALUE \"I\", \"D\".\n"
        )
        layout = compute_record_layout(record)
        by_name = {item.name: item for item in layout}

        assert by_name["STATUS-ACTIVE"].level == 88
        assert by_name["STATUS-ACTIVE"].condition_values == ["A"]
        assert by_name["STATUS-ACTIVE"].parent_qualified_name == "WS-REC.WS-STATUS"
        assert by_name["STATUS-ACTIVE"].byte_offset == 0
        assert by_name["STATUS-ACTIVE"].byte_length == 1

        assert by_name["STATUS-INACTIVE"].condition_values == ["I", "D"]
        # STATUS-ACTIVE's values must NOT leak into STATUS-INACTIVE's list
        # (that's the whole point of expand_condition_values being
        # per-condition-name, unlike layout.py's merged _condition_values).

    def test_thru_range_expands_on_a_level_88_entry(self):
        record = _parse_record(
            "       01  WS-REC.\n"
            "           05  WS-CODE          PIC 9.\n"
            "               88  CODE-LOW-RANGE    VALUE 2 THRU 4.\n"
        )
        layout = compute_record_layout(record)
        entry = next(item for item in layout if item.name == "CODE-LOW-RANGE")
        assert entry.condition_values == ["2", "3", "4"]
