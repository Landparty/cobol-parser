"""Optional-keyword forms that used to lose data (issue #405).

Each form leaves out a keyword the IBM Enterprise COBOL diagram does not
underline, and before 2026-10-14 the parser dropped information as a result:

* ``XML PARSE x PROCEDURE IS p`` (PROCESSING left out) kept ``PROCEDURE`` and
  ``p`` as operands, so dead-code reported the processing procedure as dead.
* SORT/MERGE: a bare ``DUPLICATES`` and a bare ``SEQUENCE alphabet`` were
  ignored or folded into the key list, and ``KEY IS k`` dropped every key
  without a diagnostic.
* SPECIAL-NAMES: ``C01 TOP-PAGE`` / ``UPSI-0 ON SW0-ON`` (IS left out) and
  ``SYMBOLIC NUL 1`` (IS/ARE left out) left no entry at all.
"""

import pytest

from cobolparser import DeadCodeAnalyzer, parse_cobol
from cobolparser.models.statements import (
    MergeStatement,
    SortStatement,
    XmlJsonStatement,
)


def _program(special_names: str = "", procedure: str = "CONTINUE") -> str:
    # Fixed format: a long statement is split at "|" so nothing reaches
    # column 73.
    procedure = procedure.replace("|", "\n               ")
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPTKW.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           {special_names or "DECIMAL-POINT IS COMMA"}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X1                  PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           {procedure}.
           STOP RUN.
       XP.
           CONTINUE.
"""


def _only(result, cls):
    found = [s for s in result.ast.get_all_statements() if isinstance(s, cls)]
    assert len(found) == 1, found
    return found[0]


def _special_names(result) -> dict:
    for div in result.ast.children:
        if getattr(div, "division_name", None) == "ENVIRONMENT":
            section = div.get_section_by_name("CONFIGURATION")
            return (section.get_metadata("special_names") if section else None) or {}
    return {}


# --- XML PARSE --------------------------------------------------------------


@pytest.mark.parametrize(
    "keywords", ["PROCEDURE IS", "PROCEDURE", "PROCESSING PROCEDURE"]
)
def test_xml_parse_procedure_with_or_without_processing(keywords: str) -> None:
    result = parse_cobol(
        _program(procedure=f"XML PARSE X1 {keywords} XP|ON EXCEPTION CONTINUE END-XML")
    )
    assert result.success, result.errors
    stmt = _only(result, XmlJsonStatement)
    assert stmt.to_dict()["processing_procedure"] == "XP"
    assert "PROCEDURE" not in stmt.operands
    assert "XP" not in stmt.operands


def test_xml_parse_without_processing_procedure_is_not_dead() -> None:
    result = parse_cobol(
        _program(procedure="XML PARSE X1 PROCEDURE IS XP THRU XP END-XML")
    )
    dead = {item.name for item in DeadCodeAnalyzer().analyze(result.ast).dead_items}
    assert "XP" not in dead


# --- SORT / MERGE -----------------------------------------------------------


def test_sort_bare_duplicates() -> None:
    result = parse_cobol(
        _program(procedure="SORT SF ASCENDING SK1 DUPLICATES USING F1 GIVING F2")
    )
    stmt = _only(result, SortStatement)
    assert stmt.duplicates_in_order is True
    assert stmt.keys == [{"field": "SK1", "order": "ASCENDING"}]
    assert stmt.using_files == ["F1"] and stmt.giving_files == ["F2"]


def test_sort_with_duplicates_in_order_still_works() -> None:
    result = parse_cobol(
        _program(
            procedure="SORT SF ON ASCENDING KEY SK1 WITH DUPLICATES IN ORDER"
            "|USING F1 GIVING F2"
        )
    )
    stmt = _only(result, SortStatement)
    assert stmt.duplicates_in_order is True
    assert stmt.using_files == ["F1"]


@pytest.mark.parametrize(
    "phrase", ["SEQUENCE NATIVE", "SEQUENCE IS NATIVE", "COLLATING SEQUENCE NATIVE"]
)
def test_sort_collating_sequence_with_or_without_collating(phrase: str) -> None:
    result = parse_cobol(
        _program(procedure=f"SORT SF ASCENDING SK1 {phrase}|USING F1 GIVING F2")
    )
    stmt = _only(result, SortStatement)
    assert stmt.collating_sequence == "NATIVE"
    assert stmt.keys == [{"field": "SK1", "order": "ASCENDING"}]
    assert stmt.using_files == ["F1"]


def test_merge_bare_sequence() -> None:
    result = parse_cobol(
        _program(
            procedure="MERGE SF ASCENDING SK1 SEQUENCE NATIVE|USING F1 F3 GIVING F2"
        )
    )
    stmt = _only(result, MergeStatement)
    assert stmt.collating_sequence == "NATIVE"
    assert stmt.keys == [{"field": "SK1", "order": "ASCENDING"}]
    assert stmt.using_files == ["F1", "F3"]


def test_sort_key_is() -> None:
    result = parse_cobol(
        _program(
            procedure="SORT SF ON ASCENDING KEY IS SK1|ON DESCENDING KEY IS SK2"
            "|USING F1 GIVING F2"
        )
    )
    stmt = _only(result, SortStatement)
    assert stmt.keys == [
        {"field": "SK1", "order": "ASCENDING"},
        {"field": "SK2", "order": "DESCENDING"},
    ]
    assert not any("no sort keys" in w for w in result.warnings)


def test_merge_key_is() -> None:
    result = parse_cobol(
        _program(procedure="MERGE SF ON ASCENDING KEY IS SK1 USING F1 F3 GIVING F2")
    )
    assert _only(result, MergeStatement).keys == [
        {"field": "SK1", "order": "ASCENDING"}
    ]


@pytest.mark.parametrize(
    "procedure",
    ["SORT SF USING F1 GIVING F2", "MERGE SF USING F1 F3 GIVING F2"],
)
def test_file_sort_or_merge_without_keys_warns(procedure: str) -> None:
    result = parse_cobol(_program(procedure=procedure))
    assert any("no sort keys were recorded" in w for w in result.warnings)


def test_table_sort_without_keys_does_not_warn() -> None:
    # A table SORT may omit its keys (they come from the OCCURS KEY clause).
    result = parse_cobol(_program(procedure="SORT X1"))
    assert not any("no sort keys" in w for w in result.warnings)


# --- SPECIAL-NAMES ----------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("C01 TOP-PAGE", [{"environment_name": "C01", "mnemonic_name": "TOP-PAGE"}]),
        ("SYSOUT PRT", [{"environment_name": "SYSOUT", "mnemonic_name": "PRT"}]),
        (
            "UPSI-0 SW0 ON SW0-ON OFF SW0-OFF",
            [
                {
                    "environment_name": "UPSI-0",
                    "mnemonic_name": "SW0",
                    "on_status": "SW0-ON",
                    "off_status": "SW0-OFF",
                }
            ],
        ),
        ("UPSI-0 ON SW0-ON", [{"environment_name": "UPSI-0", "on_status": "SW0-ON"}]),
        (
            "UPSI-0 OFF SW0-OFF",
            [{"environment_name": "UPSI-0", "off_status": "SW0-OFF"}],
        ),
        (
            "C01 IS TOP-PAGE C02 P2",
            [
                {"environment_name": "C01", "mnemonic_name": "TOP-PAGE"},
                {"environment_name": "C02", "mnemonic_name": "P2"},
            ],
        ),
        (
            "C01 TOP-PAGE CONSOLE IS CRT",
            [
                {"environment_name": "C01", "mnemonic_name": "TOP-PAGE"},
                {"environment_name": "CONSOLE", "mnemonic_name": "CRT"},
            ],
        ),
    ],
)
def test_mnemonic_entry_without_is(body: str, expected: list[dict]) -> None:
    result = parse_cobol(_program(special_names=body))
    assert result.success, result.errors
    assert _special_names(result).get("mnemonic_definitions") == expected


def test_unknown_word_without_is_is_not_a_mnemonic_entry() -> None:
    # Only a known environment-name can start an entry with IS left out.
    result = parse_cobol(_program(special_names="MY-DEVICE PRT"))
    assert "mnemonic_definitions" not in _special_names(result)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("SYMBOLIC CHARACTERS NUL 1", [("NUL", 1, None)]),
        ("SYMBOLIC NUL SOH 1 2", [("NUL", 1, None), ("SOH", 2, None)]),
        (
            "ALPHABET AL IS EBCDIC SYMBOLIC NUL 1 IN AL",
            [("NUL", 1, "AL")],
        ),
        ("SYMBOLIC NUL 1 SOH IS 2", [("NUL", 1, None), ("SOH", 2, None)]),
    ],
)
def test_symbolic_characters_without_is(body: str, expected: list[tuple]) -> None:
    result = parse_cobol(_program(special_names=body))
    entries = _special_names(result).get("symbolic_characters", [])
    assert [(e["name"], e["ordinal"], e["alphabet"]) for e in entries] == expected


def test_symbolic_without_is_followed_by_mnemonic_entry() -> None:
    result = parse_cobol(_program(special_names="SYMBOLIC NUL 1 C01 TOP-PAGE"))
    names = _special_names(result)
    assert [e["name"] for e in names["symbolic_characters"]] == ["NUL"]
    assert names["mnemonic_definitions"] == [
        {"environment_name": "C01", "mnemonic_name": "TOP-PAGE"}
    ]
