"""Regression tests for Area B–aware comment-entry termination in the
IDENTIFICATION DIVISION.

COBOL-74 comment-entry paragraphs (AUTHOR, INSTALLATION, SECURITY, REMARKS,
...) are pure documentation that ends only at the next entry starting in
Area A. NIST's OBNC1M deliberately embeds an *entire phony program* —
including its own ``IDENTIFICATION DIVISION.`` — inside a SECURITY
comment-entry, written wholly in Area B, to test exactly this rule.

``normalize_fixed_format`` preserves the Area A/B distinction as leading
indentation, so the IDENTIFICATION DIVISION parser's boundary checks
(``_at_comment_entry_aware_boundary``) treat a division keyword indented
deeper than the division's own header as comment text. Previously the phony
``ENVIRONMENT DIVISION.`` terminated the identification division early, the
phony divisions parsed as the real ones, and the phony ``IDENTIFICATION
DIVISION.`` spawned a bogus second program unit that failed with
"PROGRAM-ID is mandatory".

The relative-column comparison self-calibrates for free-form sources: a
following real division at the *same* indent as the IDENTIFICATION header is
still a boundary (see the control test).
"""

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode


def _parse(source: str):
    return parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)


class TestAreaBPhonyProgramInCommentEntry:
    """A phony program written in Area B inside a comment-entry is
    documentation, not structure."""

    def test_phony_divisions_in_area_b_do_not_end_identification(self) -> None:
        # Mirrors OBNC1M's shape: SECURITY comment-entry containing phony
        # division headers in Area B (source column 12+); the real divisions
        # resume in Area A (source column 8).
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID.
           AREABTST.
       SECURITY.
           NONE
           THE LINES WHICH FOLLOW ARE DOCUMENTATION ONLY
           ENVIRONMENT DIVISION.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01 PHONY-ITEM PICTURE X(10).
           PROCEDURE DIVISION.
           PHONY-PARA.
               STOP RUN.
           IDENTIFICATION DIVISION.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REAL PIC X(4) VALUE 'REAL'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-REAL.
           STOP RUN.
"""
        result = _parse(source)
        assert result.errors == [], [str(e) for e in result.errors]
        assert result.ast is not None
        assert result.ast.program_name == "AREABTST"
        # The phony IDENTIFICATION DIVISION must not spawn a second program
        # unit, and the real divisions must all be present exactly once.
        assert getattr(result.ast, "contained_programs", []) == []
        names = [d.to_dict().get("division_name") for d in result.ast.divisions]
        assert names == ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]

    def test_real_division_at_header_column_still_ends_identification(
        self,
    ) -> None:
        # Control: a genuine following division at the same indent as the
        # IDENTIFICATION header (Area A) is still a boundary — the
        # comment-entry awareness must not swallow real structure.
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CTRLTST.
       AUTHOR.
           A COMMENT ENTRY WITH TRAILING TEXT
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
        result = _parse(source)
        assert result.errors == [], [str(e) for e in result.errors]
        assert result.ast is not None
        assert result.ast.program_name == "CTRLTST"
        names = [d.to_dict().get("division_name") for d in result.ast.divisions]
        assert names == ["IDENTIFICATION", "DATA", "PROCEDURE"]
