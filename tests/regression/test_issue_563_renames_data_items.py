"""``data-items`` and MCP ``record_layout`` place level-66 RENAMES items (#563).

``compute_program_data_items`` walked only the 01/77 trees, so a RENAMES item
had no entry and no ``unresolved`` line, and ``record_layout`` answered
``found: false`` with no caveat -- "not modelled" read as "does not exist".
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.generators.data.layout_offsets import compute_program_data_items
from cobolparser.mcp import CobolTools, Workspace


def _source(*renames: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. RN.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 R.",
        "   05 A PIC X(3).",
        "   05 B PIC X(4).",
        "   05 C PIC 9(5) COMP-3.",
        "   05 D PIC X(2).",
        *renames,
        "01 OTHER-REC PIC X(5).",
        "PROCEDURE DIVISION.",
        "    DISPLAY A",
        "    GOBACK.",
    )
    return "".join(f"       {line}\n" for line in lines)


SOURCE = _source(
    "66 R-AB RENAMES A THRU B.",
    "66 R-BC RENAMES B THROUGH C.",
    "66 R-C RENAMES C.",
)


def _data_items(source: str) -> dict:
    result = parse_cobol(source)
    assert result.success, result.errors
    return compute_program_data_items(result.ast)


def test_data_items_places_each_renames_item():
    data = _data_items(SOURCE)
    renames = {item["name"]: item for item in data["items"] if item["level"] == 66}
    assert {
        name: (
            item["qualified_name"],
            item["parent_qualified_name"],
            item["byte_offset"],
            item["byte_length"],
            item["is_group"],
            item["picture"],
            item["usage"],
        )
        for name, item in renames.items()
    } == {
        "R-AB": ("R.R-AB", "R", 0, 7, True, None, "DISPLAY"),
        "R-BC": ("R.R-BC", "R", 3, 7, True, None, "DISPLAY"),
        "R-C": ("R.R-C", "R", 7, 3, False, "9(5)", "COMP-3"),
    }
    assert data["unresolved"] == []


def test_unplaceable_renames_is_unresolved():
    data = _data_items(_source("66 R-X RENAMES D THRU A."))
    assert not [item for item in data["items"] if item["level"] == 66]
    assert data["unresolved"] == ["R-X: the RENAMES range D THRU A could not be placed"]


def test_mcp_record_layout_answers_renames(tmp_path: Path):
    (tmp_path / "RN.cbl").write_text(SOURCE)
    tools = CobolTools(Workspace(tmp_path))
    result = tools.record_layout("RN.cbl", "R-AB")
    answer = result["answer"]
    assert answer["found"] is True
    (record,) = answer["records"]
    assert (record["level"], record["renames"]) == (66, "R")
    assert (record["byte_offset"], record["byte_length"]) == (0, 7)
    assert record["declared_at"]["line"] == 10
    assert [f["name"] for f in record["fields"]] == ["A", "B"]
    assert result["caveats"] == []

    (single,) = tools.record_layout("RN.cbl", "R-C")["answer"]["records"]
    assert (single["picture"], single["usage"]) == ("9(5)", "COMP-3")


def test_mcp_record_layout_caveats_an_unplaceable_renames(tmp_path: Path):
    # Declared but not placeable: found: false alone would read as "no such
    # item", which is what the issue reported.
    (tmp_path / "RN.cbl").write_text(_source("66 R-X RENAMES D THRU A."))
    result = CobolTools(Workspace(tmp_path)).record_layout("RN.cbl", "R-X")
    assert result["answer"]["found"] is False
    assert [c["kind"] for c in result["caveats"]] == ["incomplete-analysis"]
    assert "R-X" in result["caveats"][0]["detail"]


def test_mcp_explain_symbol_layout_matches(tmp_path: Path):
    (tmp_path / "RN.cbl").write_text(SOURCE)
    result = CobolTools(Workspace(tmp_path)).explain_symbol("RN.cbl", "R-BC")
    (symbol,) = result["answer"]["symbols"]
    assert symbol["layout"]["byte_offset"] == 3
    assert symbol["layout"]["byte_length"] == 7
