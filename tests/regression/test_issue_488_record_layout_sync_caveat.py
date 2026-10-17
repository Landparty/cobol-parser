"""Issue #488: MCP ``record_layout`` built its answer from
``compute_record_layout`` alone, which never flags ``SYNCHRONIZED`` slack, so
offsets after an unaligned SYNC item came back exact with no caveat (B at 1,
C at 5, where IBM places B at 4).  ``data-items`` flagged them.  Both MCP
tools now carry the same ``offset_ambiguous`` flags and an
``incomplete-analysis`` caveat with the reason.
"""

from __future__ import annotations

from pathlib import Path

from cobolparser.config.project import ProjectConfig
from cobolparser.mcp import CobolTools, Workspace

D1 = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. D1.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-REC.\n"
    "           05  A    PIC X.\n"
    "           05  B    PIC S9(9) COMP SYNC.\n"
    "           05  C    PIC X(3).\n"
    "       01  OTHER-REC.\n"
    "           05  D    PIC X(2).\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY WS-REC OTHER-REC.\n"
)


def _tools(tmp_path: Path) -> CobolTools:
    (tmp_path / "d1.cbl").write_text(D1)
    return CobolTools(Workspace(tmp_path, ProjectConfig()))


def _sync_caveats(result: dict) -> list[dict]:
    return [
        c
        for c in result["caveats"]
        if c["kind"] == "incomplete-analysis" and "SYNCHRONIZED" in c["detail"]
    ]


def test_record_layout_flags_offsets_after_unaligned_sync(tmp_path: Path) -> None:
    result = _tools(tmp_path).record_layout("d1.cbl", "WS-REC")
    (record,) = result["answer"]["records"]
    fields = {field["name"]: field for field in record["fields"]}
    assert "offset_ambiguous" not in fields["A"]
    assert fields["B"]["offset_ambiguous"] is True
    assert fields["C"]["offset_ambiguous"] is True
    (caveat,) = _sync_caveats(result)
    assert caveat["detail"].startswith("WS-REC.B:")


def test_record_layout_of_an_aligned_record_has_no_caveat(tmp_path: Path) -> None:
    result = _tools(tmp_path).record_layout("d1.cbl", "OTHER-REC")
    assert _sync_caveats(result) == []


def test_explain_symbol_says_why_the_offset_is_ambiguous(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    result = tools.explain_symbol("d1.cbl", "C")
    assert len(_sync_caveats(result)) == 1
    other = tools.explain_symbol("d1.cbl", "D")
    assert _sync_caveats(other) == []


def test_a_partial_level_88_caveat_does_not_cast_doubt_on_offsets(
    tmp_path: Path,
) -> None:
    # A level-88 THRU range listed only in part is about condition_values;
    # its caveat must not tell the reader the offsets may be short.
    (tmp_path / "r.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. R.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  RNG-REC.\n"
        "           05  N    PIC 9(5).\n"
        "               88  N-OK VALUE 1 THRU 99999.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY RNG-REC.\n"
    )
    tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
    for result in (
        tools.record_layout("r.cbl", "RNG-REC"),
        tools.explain_symbol("r.cbl", "N"),
    ):
        partial = [c for c in result["caveats"] if "only part" in c["detail"]]
        assert partial
        assert all("offset" not in c["effect"] for c in partial)
