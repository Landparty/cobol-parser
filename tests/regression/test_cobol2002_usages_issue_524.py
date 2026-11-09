"""COBOL 2002 USAGE words and unknown USAGE words (#524).

``FLOAT-SHORT`` / ``FLOAT-LONG`` / ``BINARY-LONG`` / a typo such as ``USAGE
IS COMPX`` were stored silently and sized 0 bytes by ``data-items`` but 9 by
``gen-data``, so the record length and every later offset disagreed with no
warning. The known words now get their real sizes in both paths; any other
word gets a parse warning and is reported as unresolved by both.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.encoding import EncodingOptions, encoding_caveats
from cobolparser.layout.offsets import compute_program_data_items


def _program(*fields: str) -> str:
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. U2002.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01  R.",
        "    05  A  PIC X(2).",
        *fields,
        "    05  B  PIC X(2).",
        "PROCEDURE DIVISION.",
        "    STOP RUN.",
    ]
    return "".join(f"       {line}\n" for line in lines)


def _items(source: str) -> tuple[dict[str, dict], list[str], list[str]]:
    result = parse_cobol(source)
    assert result.success, result.errors
    report = compute_program_data_items(result.ast)
    by_name = {i["name"]: i for i in report["items"]}
    return by_name, report["unresolved"], result.warnings


def _image_length(source: str) -> tuple[int, list[str]]:
    options = DataGeneratorOptions(rows=2, seed=1).for_record_image()
    dataset = CopybookDataGenerator(options).generate_from_source(source)
    length = dataset.record_length()
    # The encoder writes exactly the length the layout predicts.
    assert len(dataset.to_records(EncodingOptions())) == 2 * length
    return length, encoding_caveats(dataset.fields)


@pytest.mark.parametrize(
    "usage, size",
    [
        ("FLOAT-SHORT", 4),
        ("FLOAT-LONG", 8),
        ("FLOAT-EXTENDED", 16),
        ("BINARY-CHAR", 1),
        ("BINARY-SHORT", 2),
        ("BINARY-LONG", 4),
        ("BINARY-DOUBLE", 8),
        ("BINARY-LONG UNSIGNED", 4),
    ],
)
def test_known_cobol2002_usages_are_sized_alike(usage: str, size: int) -> None:
    source = _program(f"    05  H  USAGE {usage}.")
    items, unresolved, warnings = _items(source)
    assert warnings == []
    assert unresolved == []
    assert items["H"]["byte_length"] == size
    assert items["B"]["byte_offset"] == 2 + size
    assert items["R"]["byte_length"] == 4 + size
    length, _ = _image_length(source)
    assert length == 4 + size


def test_the_issue_record() -> None:
    source = _program("    05  H  USAGE FLOAT-SHORT.", "    05  F  USAGE FLOAT-LONG.")
    items, unresolved, warnings = _items(source)
    assert (warnings, unresolved) == ([], [])
    assert items["R"]["byte_length"] == 16
    assert items["B"]["byte_offset"] == 14
    length, caveats = _image_length(source)
    assert length == 16
    # Encoded as floats like COMP-1 / COMP-2, with their caveat.
    assert any("IEEE 754" in c and "R.H" in c for c in caveats)


def test_unmodelled_bytes_are_a_caveat() -> None:
    _, caveats = _image_length(_program("    05  H  USAGE BINARY-LONG."))
    assert any("not modelled" in c and "BINARY-LONG" in c for c in caveats)


def test_unknown_usage_warns_and_is_unresolved_in_both_paths() -> None:
    source = _program("    05  H  PIC 9(3) USAGE IS COMPX.")
    items, unresolved, warnings = _items(source)
    assert any("Unsupported USAGE 'COMPX'" in w for w in warnings)
    assert any("R.H" in u and "COMPX" in u for u in unresolved)
    assert items["H"]["offset_ambiguous"] is True
    assert items["B"]["offset_ambiguous"] is True
    assert items["A"]["offset_ambiguous"] is False
    _, caveats = _image_length(source)
    assert any("unsupported USAGE" in c and "COMPX" in c for c in caveats)


@pytest.mark.parametrize(
    "clause, size",
    [
        ("FLOAT-SHORT", 4),
        ("FLOAT-LONG", 8),
        ("FLOAT-EXTENDED", 16),
        ("BINARY-CHAR UNSIGNED", 1),
        ("BINARY-SHORT", 2),
        ("BINARY-LONG SIGNED", 4),
        ("BINARY-DOUBLE", 8),
    ],
)
def test_usage_keyword_is_optional(clause: str, size: int) -> None:
    # ``USAGE [IS]`` is optional: ``05 H BINARY-LONG.`` is the same item.
    source = _program(f"    05  H  {clause}.")
    items, unresolved, warnings = _items(source)
    assert (warnings, unresolved) == ([], [])
    assert items["H"]["usage"] == clause.split()[0]
    assert items["B"]["byte_offset"] == 2 + size
    length, _ = _image_length(source)
    assert length == 4 + size
