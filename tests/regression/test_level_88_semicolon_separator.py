"""Regression tests: a semicolon separates level-88 VALUE entries (issue #343).

The level-88 VALUE loop treated only a comma as a separator, so a ``;`` ended
the list and every value after it was dropped (with only an "Unparsed token"
warning that did not mention the lost values).
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.layout.fields import expand_condition_values
from cobolparser.models.data_items import ConditionNameItem


def _conditions(entries: str) -> tuple[dict[str, ConditionNameItem], list[str]]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SEMI88.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{entries}"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    found = {
        item.name: item
        for item in result.ast.find_all_by_type("ConditionNameItem")
        if isinstance(item, ConditionNameItem)
    }
    return found, list(result.warnings)


def test_semicolon_between_single_values_keeps_every_value() -> None:
    conditions, warnings = _conditions(
        "       01 C PIC X.\n" "          88 C1 VALUES 'A', 'B'; 'C'.\n"
    )
    assert conditions["C1"].values == ["A", "B", "C"]
    assert not any("';'" in w for w in warnings)


def test_semicolon_between_ranges_keeps_both_ranges() -> None:
    conditions, warnings = _conditions(
        "       01 C PIC X.\n" "          88 C2 VALUE 'A' THRU 'C'; 'X' THRU 'Z'.\n"
    )
    assert conditions["C2"].values == ["A", "THROUGH:C", "X", "THROUGH:Z"]
    assert not any("';'" in w for w in warnings)


def test_semicolon_numeric_values_and_mixed_separators() -> None:
    conditions, _ = _conditions(
        "       01 N PIC 9.\n"
        "          88 N-ODD VALUES 1 ; 3 , 5;\n"
        "                          7 THRU 9.\n"
    )
    assert conditions["N-ODD"].values == ["1", "3", "5", "7", "THROUGH:9"]
    assert expand_condition_values(conditions["N-ODD"].values) == [
        "1",
        "3",
        "5",
        "7",
        "8",
        "9",
    ]
