"""Regression tests for two DATA DIVISION gaps found via end-to-end parsing.

1. ``PictureClause._parse_pattern`` had no branch for the ``N`` (national)
   PICTURE symbol, so ``PIC N(10)`` fell through to the alphanumeric
   fallback -- which only counted ``9``/``X`` characters -- and defaulted
   ``size`` to 1 instead of 10 (and under-counted any enclosing group's
   ``calculated_size`` as a result).

2. ``parse_usage_clause`` never consumed an optional ``IS`` after ``USAGE``,
   unlike the PICTURE/VALUE/SIGN clause parsers in the same file. Writing
   ``USAGE IS <keyword>`` left the ``IS`` token unconsumed, which none of
   the usage branches matched, so the clause silently fell back to the
   ``DISPLAY`` default (with spurious "Unparsed token" warnings), except
   for POINTER/PROCEDURE-POINTER/FUNCTION-POINTER, which were accidentally
   rescued by an unrelated bare-POINTER fallback elsewhere (still with a
   spurious warning). Separately, ``USAGE DISPLAY-1`` (no ``IS`` at all)
   was dropped because ``DISPLAY-1`` lexes as its own ``TokenType.DISPLAY_1``
   token, which ``parse_usage_clause`` never checked.
"""

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause


def _parse_working_storage(items_cobol: str):
    """Wrap bare data items in a minimal valid COBOL program and parse it."""
    source = textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        {items_cobol}
        PROCEDURE DIVISION.
        STOP RUN.
        """)
    return parse_cobol(source, filename="test.cbl")


def _find_item(result, name: str):
    """Find the first data item with the given name in the parsed AST."""
    items = result.ast.find_all_by_type("DataItem")
    for item in items:
        if hasattr(item, "name") and item.name.upper() == name.upper():
            return item
    return None


# ---------------------------------------------------------------------------
# Bug 1: PIC N (national) symbol
# ---------------------------------------------------------------------------


class TestPictureNationalSymbol:
    def test_pic_n_repeat_factor_size(self):
        """PIC N(10) is a national field: 10 single-width character positions."""
        pic = PictureClause("N(10)", SourceLocation(1, 1))
        assert pic.size == 10

    def test_pic_n_bare_size(self):
        """A bare PIC N is a single national character position."""
        pic = PictureClause("N", SourceLocation(1, 1))
        assert pic.size == 1

    def test_pic_n_end_to_end(self):
        result = _parse_working_storage("01  WS-NAT3  PIC N(10).")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-NAT3")
        assert item is not None
        assert item.picture_clause is not None
        assert item.picture_clause.size == 10
        assert item.calculate_size() == 10

    def test_pic_n_in_group_item_updates_group_size(self):
        """A PIC N(5) child's corrected size must roll up into the group total."""
        result = _parse_working_storage(textwrap.dedent("""\
                01  WS-GROUP.
                    05  WS-NAT5  PIC N(5).
                    05  WS-NUM   PIC 9(3).
                """))
        assert result.success
        assert not result.errors
        assert not result.warnings

        group = _find_item(result, "WS-GROUP")
        assert group is not None
        assert group.is_group_item()
        assert group.calculate_size() == 8  # 5 (national) + 3 (numeric)

        nat_item = _find_item(result, "WS-NAT5")
        assert nat_item is not None
        assert nat_item.picture_clause.size == 5


# ---------------------------------------------------------------------------
# Bug 2: USAGE clause IS-handling and DISPLAY-1
# ---------------------------------------------------------------------------


class TestUsageClauseGaps:
    def test_usage_is_national(self):
        result = _parse_working_storage("01  WS-NAT2  PIC N(10) USAGE IS NATIONAL.")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-NAT2")
        assert item is not None
        assert item.usage == "NATIONAL"

    def test_usage_is_index(self):
        result = _parse_working_storage("01  WS-IDX2  USAGE IS INDEX.")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-IDX2")
        assert item is not None
        assert item.usage == "INDEX"

    def test_usage_is_pointer(self):
        result = _parse_working_storage("01  WS-PTR2  USAGE IS POINTER.")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-PTR2")
        assert item is not None
        assert item.usage == "POINTER"

    def test_usage_display_1_no_is(self):
        result = _parse_working_storage("01  WS-D1  USAGE DISPLAY-1.")
        assert result.success
        assert not result.errors
        item = _find_item(result, "WS-D1")
        assert item is not None
        assert item.usage == "DISPLAY-1"

    def test_usage_national_without_is_still_works(self):
        """No-IS form must keep working (regression guard)."""
        result = _parse_working_storage("01  WS-NAT1  PIC N(4) USAGE NATIONAL.")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-NAT1")
        assert item is not None
        assert item.usage == "NATIONAL"

    def test_usage_index_without_is_still_works(self):
        """No-IS form must keep working (regression guard)."""
        result = _parse_working_storage("01  WS-IDX1  USAGE INDEX.")
        assert result.success
        assert not result.errors
        assert not result.warnings
        item = _find_item(result, "WS-IDX1")
        assert item is not None
        assert item.usage == "INDEX"
