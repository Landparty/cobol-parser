"""Preprocessing regressions fixed on 2026-09-28.

1. COPY ... REPLACING treats a separator comma / semicolon as a blank when
   comparing pseudo-text (IBM: "a separator comma or separator semicolon ...
   is considered to be a space").
2. ``>>SOURCE FORMAT IS FREE`` inside a fixed-format file switches the
   lines after it to free format (no column slicing) until
   ``>>SOURCE FORMAT IS FIXED`` switches back -- in the normalizer and
   through copybook expansion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol, parse_cobol_with_expansion
from cobolparser._source_directive import source_format_directive
from cobolparser.preprocess import (
    expand_copybooks,
    normalize_fixed_format,
    preprocess_conditional_compilation,
)
from cobolparser.preprocess.copy_statement_parser import apply_replacing_clauses
from cobolparser.preprocess.models import ReplacingClause

# --------------------------------------------------------------------------
# 1. COPY REPLACING: separator comma / semicolon == blank.


class TestCopyReplacingSeparators:
    @pytest.mark.parametrize("separator", [", ", "; ", " , ", " ; "])
    def test_source_separator_matches_a_blank_in_pseudo_text(self, separator):
        content = f"       05 A PIC X(3){separator}VALUE 'A'.\n"
        clauses = [ReplacingClause("X(3) VALUE", "X(5) VALUE")]
        assert apply_replacing_clauses(content, clauses) == (
            "       05 A PIC X(5) VALUE 'A'.\n"
        )

    def test_pseudo_text_separator_matches_a_blank_in_source(self):
        content = "       MOVE A B TO C.\n"
        clauses = [ReplacingClause("A, B", "X")]
        assert apply_replacing_clauses(content, clauses) == "       MOVE X TO C.\n"

    def test_comma_inside_a_word_is_not_a_separator(self):
        # Not followed by a blank, so not a separator comma.
        content = "       MOVE A,B TO C.\n"
        clauses = [ReplacingClause("A B", "X")]
        assert apply_replacing_clauses(content, clauses) == content

    def test_comma_inside_a_literal_is_still_compared(self):
        content = "       05 A PIC X(4) VALUE 'A, B'.\n"
        clauses = [ReplacingClause("'A B'", "'Z'")]
        assert apply_replacing_clauses(content, clauses) == content

    def test_through_copybook_expansion(self, tmp_path: Path):
        (tmp_path / "SEP.cpy").write_text("       05 SEP-F PIC X(3), VALUE 'A'.\n")
        expansion = expand_copybooks(
            "       COPY SEP REPLACING ==X(3) VALUE== BY ==X(5) VALUE==.\n",
            copybook_paths=[tmp_path],
        )
        assert "PIC X(5) VALUE 'A'" in expansion.expanded_source


# --------------------------------------------------------------------------
# 2. >>SOURCE FORMAT IS FREE / FIXED inside a fixed-format file.

IMPLS = [normalize_fixed_format]

LONG = (
    'DISPLAY "a free-format line running well past column seventy-two, '
    'which fixed format would cut".'
)

MIXED = (
    "000100 IDENTIFICATION DIVISION.\n"
    "000200 PROGRAM-ID. MIXED.\n"
    "000300 PROCEDURE DIVISION.\n"
    "000400     >>SOURCE FORMAT IS FREE\n"
    "MOVE 1 TO X.\n"
    f"{LONG}\n"
    "*> a free-format comment\n"
    "       >>SOURCE FIXED\n"
    "000700     DISPLAY 'B'.                                                 ID0007\n"
    "000800     STOP RUN.\n"
)


@pytest.mark.parametrize(
    "text, expected",
    [
        (">>SOURCE FORMAT IS FREE", "FREE"),
        (">>SOURCE FREE", "FREE"),
        ("  >> source format fixed  ", "FIXED"),
        (">>SOURCE FORMAT FIXED *> back", "FIXED"),
        (">>SOURCE IS FREE", "FREE"),
        (">>SOURCE FORMAT", None),
        (">>IF X DEFINED", None),
        ("MOVE 1 TO X", None),
    ],
)
def test_source_format_directive(text, expected):
    assert source_format_directive(text) == expected


class TestSourceFormatSwitch:
    @pytest.mark.parametrize("impl", IMPLS)
    def test_free_lines_are_not_sliced(self, impl):
        out = impl(MIXED).split("\n")
        assert out[3] == ""  # the directive record
        assert out[4] == "MOVE 1 TO X."
        assert out[5] == LONG
        assert out[6] == "*> a free-format comment"
        assert out[7] == ""  # >>SOURCE FIXED
        assert out[8] == "    DISPLAY 'B'."  # fixed again: cols 8-72
        assert out[9] == "    STOP RUN."

    @pytest.mark.parametrize("impl", IMPLS)
    def test_line_count_is_preserved(self, impl):
        assert impl(MIXED).count("\n") == MIXED.count("\n")

    @pytest.mark.parametrize("impl", IMPLS)
    def test_directive_in_the_indicator_column(self, impl):
        src = "      >>SOURCE FREE\nMOVE 1 TO X.\n"
        assert impl(src).split("\n")[:2] == ["", "MOVE 1 TO X."]

    @pytest.mark.parametrize("impl", IMPLS)
    def test_a_commented_directive_does_nothing(self, impl):
        src = "      *>>SOURCE FREE\n000200 MOVE 1 TO X.\n"
        assert impl(src).split("\n")[1] == "MOVE 1 TO X."

    @pytest.mark.parametrize("impl", IMPLS)
    def test_flushes_a_pending_logical_line(self, impl):
        src = "       MOVE 1\n       >>SOURCE FREE\n  TO X.\n"
        assert impl(src).split("\n")[:3] == ["MOVE 1", "", "  TO X."]

    def test_parse_reads_the_free_lines(self):
        result = parse_cobol(MIXED)
        assert result.errors == []
        assert result.warnings == []
        statements = result.ast.get_all_statements()
        assert [type(s).__name__ for s in statements] == [
            "MoveStatement",
            "DisplayStatement",
            "DisplayStatement",
            "StopStatement",
        ]
        assert [s.location.line for s in statements] == [5, 6, 9, 10]

    def test_through_copybook_expansion(self, tmp_path: Path):
        (tmp_path / "CP.cpy").write_text("       01 X PIC 9.\n")
        source = MIXED.replace(
            "000300 PROCEDURE DIVISION.\n",
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CP.\n"
            "000300 PROCEDURE DIVISION.\n",
        )
        expansion = expand_copybooks(
            source,
            copybook_paths=[tmp_path],
            preserve_source_locations=True,
            process_conditionals=True,
        )
        assert LONG in expansion.expanded_source
        assert not expansion.statistics.warnings
        lines = expansion.expanded_source.split("\n")
        assert expansion.source_location_map[9] == ("<main>", 9)
        assert LONG in lines[8]
        result = parse_cobol_with_expansion(
            source, "MIXED.cbl", copybook_paths=[tmp_path]
        )
        assert result.errors == []
        assert result.warnings == []
        lines_of = [s.location.line for s in result.ast.get_all_statements()]
        assert lines_of == [8, 9, 12, 13]

    def test_conditional_compilation_can_keep_the_directive(self):
        src = "       >>SOURCE FREE\n"
        warnings: list[str] = []
        kept = preprocess_conditional_compilation(
            src, warnings=warnings, keep_source_format_directives=True
        )
        assert kept.strip() == ">>SOURCE FREE"
        assert warnings == []
        assert preprocess_conditional_compilation(src).strip() == ""
