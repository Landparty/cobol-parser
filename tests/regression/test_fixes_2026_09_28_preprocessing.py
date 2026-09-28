"""Preprocessing regressions fixed on 2026-09-28.

1. COPY ... REPLACING treats a separator comma / semicolon as a blank when
   comparing pseudo-text (IBM: "a separator comma or separator semicolon ...
   is considered to be a space").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.preprocess import expand_copybooks
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
