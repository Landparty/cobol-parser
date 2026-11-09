"""Regression tests for bug hunt round 10: DATA DIVISION parsing and layout.

Each test names the defect it pins; see the module docstrings of the fixed
files for the reasoning.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser._storage import storage_size
from cobolparser.layout.fields import expand_condition_values
from cobolparser.layout.offsets import compute_program_data_items
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    PictureClause,
    RenamesItem,
)


def _program(data_lines: str, *, extra_divisions: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. R10.\n"
        f"{extra_divisions}"
        "       DATA DIVISION.\n"
        f"{data_lines}"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _ws(entries: str) -> str:
    return _program("       WORKING-STORAGE SECTION.\n" + entries)


def _parse(source: str):
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    return result


def _layout(source: str) -> dict[str, dict]:
    result = _parse(source)
    items = compute_program_data_items(result.ast)["items"]
    return {item["qualified_name"]: item for item in items}


def _pic(pattern: str) -> PictureClause:
    return PictureClause(pattern, SourceLocation(1, 1))


def _conditions(result) -> dict[str, ConditionNameItem]:
    found: dict[str, ConditionNameItem] = {}

    def walk(item: CobolDataItem) -> None:
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                found[child.name] = child
            elif isinstance(child, CobolDataItem):
                walk(child)

    for section in result.ast.get_division("DATA").sections:
        for record in section.data_items:
            walk(record)
    return found


def _renames(result) -> dict[str, RenamesItem]:
    return {
        child.name: child
        for section in result.ast.get_division("DATA").sections
        for child in section.children
        if isinstance(child, RenamesItem)
    }


# ---------------------------------------------------------------------------
# USAGE POINTER-32 / POINTER-64 were sized as zero bytes
# ---------------------------------------------------------------------------


def test_pointer_32_and_pointer_64_occupy_their_address_width() -> None:
    source = _ws(
        "       01 REC.\n"
        "          05 P64 USAGE POINTER-64.\n"
        "          05 P32 POINTER-32.\n"
        "          05 P32B USAGE IS POINTER-32.\n"
        "          05 TAIL PIC X.\n"
    )
    result = _parse(source)
    assert result.warnings == []
    layout = _layout(source)
    assert layout["REC.P64"]["byte_length"] == 8
    assert layout["REC.P32"]["usage"] == "POINTER-32"
    assert layout["REC.P32"]["byte_offset"] == 8
    assert layout["REC.P32"]["byte_length"] == 4
    assert layout["REC.P32B"]["byte_offset"] == 12
    assert layout["REC.TAIL"]["byte_offset"] == 16
    assert layout["REC"]["byte_length"] == 17
    record = result.ast.get_division("DATA").sections[0].data_items[0]
    assert record.calculate_size() == 17
    assert storage_size("POINTER-64", picture_size=None, total_digits=None) == 8
    assert storage_size("POINTER-32", picture_size=None, total_digits=None) == 4


# ---------------------------------------------------------------------------
# Lower-case PICTURE symbols: ``s`` read as unsigned, ``p`` scaling lost
# ---------------------------------------------------------------------------


def test_lowercase_picture_sign_and_scaling_are_recognised() -> None:
    signed = _pic("s9(5)v99")
    assert signed.is_signed
    assert (signed.integer_digits, signed.decimal_digits) == (5, 2)

    scaled = _pic("9(3)ppp")
    assert scaled.size == 3
    assert scaled.total_digits == 3
    assert scaled.integer_digits == 6
    assert scaled.has_scaling_factor

    source = _ws(
        "       01 rec.\n"
        "          05 a pic s9(3) sign leading separate.\n"
        "          05 b pic 9(3)ppp comp-3.\n"
        "          05 c pic x.\n"
    )
    layout = _layout(source)
    # SIGN SEPARATE spends a byte; COMP-3 of three digits is two bytes.
    assert layout["rec.a"]["byte_length"] == 4
    assert layout["rec.b"]["byte_offset"] == 4
    assert layout["rec.b"]["byte_length"] == 2
    assert layout["rec.c"]["byte_offset"] == 6


# ---------------------------------------------------------------------------
# DBCS pictures with B insertion (``GGBGG``) were five bytes and "numeric"
# ---------------------------------------------------------------------------


def test_dbcs_picture_with_b_insertion_is_two_bytes_per_position() -> None:
    pic = _pic("GGBGG")
    assert pic.size == 10
    assert pic.is_edited
    assert not pic.is_numeric_edited
    assert pic.total_digits is None
    assert _pic("G(2)BG").size == 8

    layout = _layout(
        _ws("       01 REC.\n" "          05 D PIC GGBGG.\n" "          05 T PIC X.\n")
    )
    assert layout["REC.D"]["usage"] == "DISPLAY-1"
    assert layout["REC.D"]["byte_length"] == 10
    assert layout["REC.T"]["byte_offset"] == 10


# ---------------------------------------------------------------------------
# Level-66 RENAMES: line breaks and qualifiers lost the THRU operand
# ---------------------------------------------------------------------------


def test_renames_operands_across_lines_and_qualified() -> None:
    result = _parse(
        _ws(
            "       01 REC.\n"
            "          05 A PIC X(2).\n"
            "          05 B PIC X(3).\n"
            "          05 C PIC X(4).\n"
            "       66 R-SPLIT RENAMES A\n"
            "                  THRU C.\n"
            "       66 R-NEXT RENAMES\n"
            "                  B.\n"
            "       66 R-QUAL RENAMES A OF REC THRU C OF REC.\n"
            "       66 R-LATE\n"
            "                  RENAMES B THRU C.\n"
            "       01 AFTER-REC PIC X.\n"
        )
    )
    assert result.warnings == []
    renames = _renames(result)
    assert (renames["R-SPLIT"].renames_from, renames["R-SPLIT"].renames_through) == (
        "A",
        "C",
    )
    assert (renames["R-NEXT"].renames_from, renames["R-NEXT"].renames_through) == (
        "B",
        None,
    )
    qual = renames["R-QUAL"]
    assert (qual.renames_from, qual.renames_through) == ("A", "C")
    assert qual.renames_from_qualifiers == ["REC"]
    assert qual.to_dict()["renames_through_qualifiers"] == ["REC"]
    assert (renames["R-LATE"].renames_from, renames["R-LATE"].renames_through) == (
        "B",
        "C",
    )
    names = [
        item.name for item in result.ast.get_division("DATA").sections[0].data_items
    ]
    assert names == ["REC", "AFTER-REC"]


# ---------------------------------------------------------------------------
# Level-88 VALUE lists
# ---------------------------------------------------------------------------


def test_level_88_thru_range_end_on_next_line_stays_a_range() -> None:
    conditions = _conditions(
        _parse(
            _ws(
                "       01 REC.\n"
                "          05 A PIC 9(2).\n"
                "             88 A-LOW VALUE 1 THRU\n"
                "                            5.\n"
                "             88 A-NEG VALUE -9 THROUGH\n"
                "                            -1.\n"
            )
        )
    )
    assert conditions["A-LOW"].values == ["1", "THROUGH:5"]
    assert expand_condition_values(conditions["A-LOW"].values) == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]
    assert conditions["A-NEG"].values == ["-9", "THROUGH:-1"]


def test_level_88_hex_literal_is_one_byte_not_its_digits() -> None:
    source = _ws(
        "       01 REC.\n"
        "          05 B PIC X.\n"
        "             88 B-HEX VALUE X'C1'.\n"
        "             88 B-LOW VALUE X'00' THRU X'3F'.\n"
        "             88 B-TXT VALUE 'C1'.\n"
    )
    conditions = _conditions(_parse(source))
    assert conditions["B-HEX"].values == ["X'C1'"]
    assert expand_condition_values(conditions["B-HEX"].values) == ["\xc1"]
    assert expand_condition_values(conditions["B-LOW"].values) == ["\x00", "?"]
    # An ordinary literal is still recorded (and read back) as its content.
    assert conditions["B-TXT"].values == ["C1"]
    layout = _layout(source)
    assert layout["REC.B.B-HEX"]["condition_values"] == ["\xc1"]


def test_level_88_when_set_to_false_split_across_lines() -> None:
    conditions = _conditions(
        _parse(
            _ws(
                "       01 REC.\n"
                "          05 F PIC X.\n"
                "             88 F-YES VALUE 'Y'\n"
                "                WHEN SET TO\n"
                "                FALSE IS 'N'.\n"
                "             88 F-NO VALUE 'N' WHEN SET TO FALSE 'Y'.\n"
                "          05 G PIC X.\n"
            )
        )
    )
    assert conditions["F-YES"].values == ["Y"]
    assert conditions["F-YES"].false_value == "N"
    assert conditions["F-NO"].false_value == "Y"


# ---------------------------------------------------------------------------
# FD RECORD VARYING: an omitted FROM/TO bound was filled from the other
# ---------------------------------------------------------------------------


def _fd_record_clause(record_clause: str) -> dict:
    source = _program(
        "       FILE SECTION.\n"
        "       FD F\n"
        f"           {record_clause}.\n"
        "       01 F-REC PIC X(80).\n",
        extra_divisions=(
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT F ASSIGN TO DD1.\n"
        ),
    )
    record = _parse(source).ast.get_division("DATA").sections[0].data_items[0]
    return record.get_metadata("fd_clauses")["record"]


def test_fd_record_varying_bounds_are_read_by_keyword() -> None:
    to_only = _fd_record_clause("RECORD IS VARYING IN SIZE TO 80 CHARACTERS")
    assert (to_only["min"], to_only["max"]) == (None, 80)
    from_only = _fd_record_clause("RECORD VARYING FROM 20 CHARACTERS")
    assert (from_only["min"], from_only["max"]) == (20, None)
    both = _fd_record_clause("RECORD VARYING IN SIZE FROM 20 TO 80")
    assert (both["min"], both["max"]) == (20, 80)
    fixed = _fd_record_clause("RECORD CONTAINS 20 TO 80 CHARACTERS")
    assert (fixed["varying"], fixed["min"], fixed["max"]) == (False, 20, 80)
