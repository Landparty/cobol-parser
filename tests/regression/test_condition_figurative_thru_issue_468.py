"""A level-88 THRU range with a figurative end keeps its THROUGH marker (#468).

``88 H-ANY VALUE LOW-VALUE THRU HIGH-VALUE`` reached the AST as
``['LOW-VALUE', 'HIGH-VALUE']``: the range end was only taken when it was a
literal, so a figurative one fell through as a second discrete value.
``data-items`` then reported no ``condition_ranges`` and no partial-list
caveat, and every consumer of ``ConditionNameItem.values`` saw two values.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.layout.offsets import compute_program_data_items

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. H.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 R.
          05 H PIC X.
             88 H-ANY VALUE LOW-VALUE THRU HIGH-VALUE.
             88 H-TOP VALUE 'A' THRU
                HIGH-VALUES.
             88 H-PAIR VALUE LOW-VALUE HIGH-VALUE.
       PROCEDURE DIVISION.
           STOP RUN.
"""


def _parse():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    assert result.warnings == []
    return result.ast


def test_figurative_range_end_is_marked() -> None:
    values = {c.name: c.values for c in _parse().find_all_by_type("ConditionNameItem")}
    assert values["H-ANY"] == ["LOW-VALUE", "THROUGH:HIGH-VALUE"]
    assert values["H-TOP"] == ["A", "THROUGH:HIGH-VALUES"]
    # Two discrete figuratives are still two values.
    assert values["H-PAIR"] == ["LOW-VALUE", "HIGH-VALUE"]


def test_data_items_reports_the_range_and_its_caveat() -> None:
    report = compute_program_data_items(_parse())
    by_name = {i["name"]: i for i in report["items"]}
    assert by_name["H-ANY"]["condition_ranges"] == [
        {"from": "LOW-VALUE", "to": "HIGH-VALUE"}
    ]
    assert any("H-ANY" in line for line in report["unresolved"])
    assert not any("H-PAIR" in line for line in report["unresolved"])
