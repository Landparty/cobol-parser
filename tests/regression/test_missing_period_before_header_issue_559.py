"""A missing period before a header no longer swallows the header (#559).

The SELECT clause loop stopped only at ``.``, so a SELECT with no period ate
``DATA DIVISION`` (the whole DATA DIVISION was lost) or the next ``SELECT``
(that file disappeared, its ASSIGN overwriting the first one's). The
data-item clause loop stopped only at DIVISION tokens, so ``01 A PIC X``
with no period ate the next ``... SECTION`` header and every following item
landed in the wrong section. Each parse reported ``success=True`` with only
"Unparsed token" warnings.

IBM assumes a period before the header ("a period was assumed before ...");
so does the parser now, with a "missing its terminating period" warning.
"""

from __future__ import annotations

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.parser import CobolParser


def _program(*lines: str) -> str:
    return "".join(f"       {line}\n" for line in lines)


_HEAD = (
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. NP.",
)
_FILE_CONTROL = (
    *_HEAD,
    "ENVIRONMENT DIVISION.",
    "INPUT-OUTPUT SECTION.",
    "FILE-CONTROL.",
)


def _sections(result) -> dict[str, list[str]]:
    return {
        section.section_name: [item.name for item in section.data_items]
        for section in result.ast.data_division.sections
    }


def _selects(result) -> list[tuple[str, str | None]]:
    return [
        (select.file_name, select.assign_to)
        for select in result.ast.find_all_by_type("SelectStatement")
    ]


def _assert_assumed_period(result, header: str) -> None:
    assert not any("Unparsed token" in w for w in result.warnings), result.warnings
    assert any(
        "missing its terminating period" in w and f"before '{header}'" in w
        for w in result.warnings
    ), result.warnings


def test_select_without_period_before_data_division():
    """The issue's repro: the DATA DIVISION used to be lost entirely."""
    result = parse_cobol(
        _program(
            *_FILE_CONTROL,
            "    SELECT IN-F ASSIGN TO INDD",
            "      FILE STATUS IS WS-FS",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD IN-F.",
            "01 IN-REC PIC X(80).",
            "WORKING-STORAGE SECTION.",
            "01 WS-FS PIC XX.",
            "01 WS-UNUSED PIC X.",
            "PROCEDURE DIVISION.",
            "    OPEN INPUT IN-F",
            "    READ IN-F",
            "    DISPLAY IN-REC",
            "    CLOSE IN-F",
            "    GOBACK.",
        )
    )
    assert result.success, result.errors
    assert result.ast.data_division is not None
    assert _sections(result) == {
        "FILE": ["IN-REC"],
        "WORKING-STORAGE": ["WS-FS", "WS-UNUSED"],
    }
    (select,) = result.ast.find_all_by_type("SelectStatement")
    assert select.file_status == "WS-FS"
    _assert_assumed_period(result, "DATA DIVISION")


def test_select_without_period_before_next_select():
    result = parse_cobol(
        _program(
            *_FILE_CONTROL,
            "    SELECT A-F ASSIGN TO ADD",
            "    SELECT B-F ASSIGN TO BDD.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD A-F.",
            "01 A-REC PIC X(80).",
            "FD B-F.",
            "01 B-REC PIC X(80).",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    assert result.success, result.errors
    assert _selects(result) == [("A-F", "ADD"), ("B-F", "BDD")]
    _assert_assumed_period(result, "SELECT")


def test_select_without_period_before_i_o_control():
    result = parse_cobol(
        _program(
            *_FILE_CONTROL,
            "    SELECT A-F ASSIGN TO ADD",
            "I-O-CONTROL.",
            "    APPLY WRITE-ONLY ON A-F.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD A-F.",
            "01 A-REC PIC X(80).",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    assert _selects(result) == [("A-F", "ADD")]
    assert _sections(result) == {"FILE": ["A-REC"]}
    _assert_assumed_period(result, "I-O-CONTROL")


@pytest.mark.parametrize(
    ("previous", "header", "following"),
    [
        ("FILE", "WORKING-STORAGE", "WS-FS"),
        ("FILE", "LOCAL-STORAGE", "LS-A"),
        ("FILE", "LINKAGE", "LK-A"),
        ("WORKING-STORAGE", "LOCAL-STORAGE", "LS-A"),
        ("WORKING-STORAGE", "LINKAGE", "LK-A"),
        ("LOCAL-STORAGE", "LINKAGE", "LK-A"),
    ],
)
def test_data_item_without_period_before_section_header(previous, header, following):
    if previous == "FILE":
        lines = [
            *_FILE_CONTROL,
            "    SELECT IN-F ASSIGN TO INDD.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD IN-F.",
            "01 IN-REC PIC X(80)",
        ]
        last = "IN-REC"
    else:
        lines = [*_HEAD, "DATA DIVISION.", f"{previous} SECTION.", "01 PREV-A PIC X"]
        last = "PREV-A"
    lines += [
        f"{header} SECTION.",
        f"01 {following} PIC X(10).",
        "PROCEDURE DIVISION.",
        "    GOBACK.",
    ]
    result = parse_cobol(_program(*lines))
    assert result.success, result.errors
    assert _sections(result) == {previous: [last], header: [following]}
    _assert_assumed_period(result, f"{header} SECTION")


@pytest.mark.parametrize("mode", list(ErrorRecoveryMode))
def test_linkage_items_stay_in_linkage(mode):
    """The issue's LINKAGE variant, under both recovery modes: LK-A used to
    land in WORKING-STORAGE and the USING parameter read as undeclared."""
    source = _program(
        *_HEAD,
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-A PIC X",
        "LINKAGE SECTION.",
        "01 LK-A PIC X(10).",
        "PROCEDURE DIVISION USING LK-A.",
        "    GOBACK.",
    )
    result = CobolParser(error_recovery=mode).parse(source)
    assert _sections(result) == {"WORKING-STORAGE": ["WS-A"], "LINKAGE": ["LK-A"]}
    _assert_assumed_period(result, "LINKAGE SECTION")


def test_group_member_without_period_before_section_header():
    result = parse_cobol(
        _program(
            *_HEAD,
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 WS-G.",
            "   05 WS-A PIC X VALUE 'A'",
            "LINKAGE SECTION.",
            "01 LK-A PIC X(10).",
            "PROCEDURE DIVISION USING LK-A.",
            "    GOBACK.",
        )
    )
    assert _sections(result) == {"WORKING-STORAGE": ["WS-G"], "LINKAGE": ["LK-A"]}
    _assert_assumed_period(result, "LINKAGE SECTION")


def test_condition_name_without_period_before_section_header():
    result = parse_cobol(
        _program(
            *_HEAD,
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC X.",
            "   88 WS-YES VALUE 'Y'",
            "LINKAGE SECTION.",
            "01 LK-A PIC X(10).",
            "PROCEDURE DIVISION USING LK-A.",
            "    GOBACK.",
        )
    )
    assert _sections(result) == {"WORKING-STORAGE": ["WS-A"], "LINKAGE": ["LK-A"]}
    _assert_assumed_period(result, "LINKAGE SECTION")


@pytest.mark.parametrize("header", ["REPORT", "SCREEN"])
def test_data_item_without_period_before_report_or_screen_section(header):
    result = parse_cobol(
        _program(
            *_HEAD,
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC X VALUE 'A'",
            f"{header} SECTION.",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    assert _sections(result)["WORKING-STORAGE"] == ["WS-A"]
    _assert_assumed_period(result, f"{header} SECTION")


def test_data_item_without_period_before_procedure_division():
    result = parse_cobol(
        _program(
            *_HEAD,
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC X",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    assert result.success, result.errors
    assert _sections(result) == {"WORKING-STORAGE": ["WS-A"]}
    _assert_assumed_period(result, "PROCEDURE DIVISION")


def test_record_without_period_before_next_fd():
    result = parse_cobol(
        _program(
            *_FILE_CONTROL,
            "    SELECT A-F ASSIGN TO ADD.",
            "    SELECT B-F ASSIGN TO BDD.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD A-F.",
            "01 A-REC PIC X(80)",
            "FD B-F.",
            "01 B-REC PIC X(40).",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    index = ProgramLayoutIndex.build(result.ast)
    assert index.record_for_file("A-F").name == "A-REC"
    assert index.record_for_file("B-F").name == "B-REC"
    _assert_assumed_period(result, "FD")


def test_file_status_clause_is_not_a_file_section_header():
    """``FILE`` alone (``FILE STATUS``) must not end a SELECT entry."""
    result = parse_cobol(
        _program(
            *_FILE_CONTROL,
            "    SELECT IN-F ASSIGN TO INDD",
            "      FILE STATUS IS WS-FS.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD IN-F.",
            "01 IN-REC PIC X(80).",
            "WORKING-STORAGE SECTION.",
            "01 WS-FS PIC XX.",
            "PROCEDURE DIVISION.",
            "    GOBACK.",
        )
    )
    assert result.success, result.errors
    assert not result.warnings
    (select,) = result.ast.find_all_by_type("SelectStatement")
    assert select.file_status == "WS-FS"
