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
