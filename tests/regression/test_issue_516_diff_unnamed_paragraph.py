"""diff compares the unnamed leading paragraph (#516).

Statements before the first paragraph header -- or in a PROCEDURE DIVISION
with no header at all -- sit in a ``CobolParagraph`` named ``''``, which
``ProgramDiffer`` skipped, so a logic change there diffed as "No structural
changes". It is now compared as ``(PROCEDURE DIVISION)``.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import UNNAMED_PARAGRAPH, ProgramDiffer


def _program(*procedure: str) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. P1.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 A PIC 9.",
        "PROCEDURE DIVISION.",
        *procedure,
    )
    return "".join(f"       {line}\n" for line in lines)


def _diff(old: str, new: str):
    return ProgramDiffer().diff(parse_cobol(old).ast, parse_cobol(new).ast)


LEADING = _program(
    "    MOVE 1 TO A",
    "    PERFORM P-ONE",
    "    STOP RUN.",
    "P-ONE.",
    "    DISPLAY A.",
)
NO_HEADER = _program("    MOVE 1 TO A", "    DISPLAY A", "    STOP RUN.")


def test_edit_before_the_first_paragraph_is_reported():
    report = _diff(LEADING, LEADING.replace("MOVE 1", "MOVE 2"))
    kinds = {(c.kind, c.symbol) for c in report.changes}
    assert ("move-source-changed", UNNAMED_PARAGRAPH) in kinds
    assert ("paragraph-body-changed", UNNAMED_PARAGRAPH) in kinds


def test_edit_in_a_program_with_no_paragraph_header_is_reported():
    report = _diff(NO_HEADER, NO_HEADER.replace("MOVE 1", "MOVE 2"))
    assert "No structural changes" not in report.to_text()
    assert {c.symbol for c in report.changes} == {UNNAMED_PARAGRAPH}


def test_identical_programs_still_diff_clean():
    assert _diff(LEADING, LEADING).changes == []
    assert _diff(NO_HEADER, NO_HEADER).changes == []


def test_adding_a_header_reads_as_a_rename():
    named = _program(
        "MAIN-PARA.",
        "    MOVE 1 TO A",
        "    PERFORM P-ONE",
        "    STOP RUN.",
        "P-ONE.",
        "    DISPLAY A.",
    )
    (change,) = _diff(LEADING, named).changes
    assert change.kind == "paragraph-renamed"
    assert change.old == UNNAMED_PARAGRAPH
    assert change.new == "MAIN-PARA"
