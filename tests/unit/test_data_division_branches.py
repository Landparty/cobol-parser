"""Tests targeting branch-coverage gaps in parsers/divisions/data.py.

Covers:
- Level 66 (RENAMES) items including THRU variant and malformed cases
- Level 77 standalone items
- Level 88 (condition name) items including THROUGH/THRU ranges and edge cases
- OCCURS DEPENDING ON (variable-length tables) and INDEXED BY
- LOCAL-STORAGE and LINKAGE sections
- FILLER items
- Anonymous (no-name) items
- REDEFINES clause
- OCCURS with fixed count and with INDEXED BY
- Malformed / recovery situations (no period, missing renames target)
- Multiple PICTURE pattern forms
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# ---------------------------------------------------------------------------
# Helper: parse with collect-all for error-recovery COBOL
# ---------------------------------------------------------------------------


def _parse(src: str):
    return parse_cobol(src, error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True)


def _assert_parsed(src: str):
    result = _parse(src)
    assert result.ast is not None
    return result


# ---------------------------------------------------------------------------
# Shared minimal wrapper around a DATA DIVISION snippet
# ---------------------------------------------------------------------------

_PREFIX = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
"""

_SUFFIX = """\
PROCEDURE DIVISION.
MAIN-PARA.
    STOP RUN.
"""


def _wrap(data_items: str) -> str:
    return _PREFIX + data_items + _SUFFIX


# ---------------------------------------------------------------------------
# Level 77 standalone items
# ---------------------------------------------------------------------------


class TestLevel77Items:
    def test_level_77_numeric(self):
        src = _wrap("77  WS-STANDALONE PIC 9(5) VALUE 0.\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        names = [i.name for i in items]
        assert "WS-STANDALONE" in names

    def test_level_77_alphanumeric(self):
        src = _wrap("77  WS-MSG PIC X(40) VALUE SPACES.\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "WS-MSG" for i in items)

    def test_level_77_comp3(self):
        src = _wrap("77  WS-AMT PIC S9(9)V99 COMP-3 VALUE ZERO.\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "WS-AMT" for i in items)


# ---------------------------------------------------------------------------
# Level 66 RENAMES items
# ---------------------------------------------------------------------------


class TestLevel66Renames:
    def test_level_66_basic_renames(self):
        src = _wrap(
            "01  WS-RECORD.\n"
            "    05  WS-FIELD-A PIC X(5).\n"
            "    05  WS-FIELD-B PIC X(5).\n"
            "66  WS-ALIAS RENAMES WS-FIELD-A.\n"
        )
        result = _assert_parsed(src)
        # Just verify parsing doesn't crash and returns an AST
        assert result.ast is not None

    def test_level_66_renames_through(self):
        src = _wrap(
            "01  WS-RECORD.\n"
            "    05  WS-PART-A PIC X(3).\n"
            "    05  WS-PART-B PIC X(3).\n"
            "    05  WS-PART-C PIC X(3).\n"
            "66  WS-ALIAS RENAMES WS-PART-A THROUGH WS-PART-C.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_66_renames_thru(self):
        src = _wrap(
            "01  WS-RECORD.\n"
            "    05  WS-PART-X PIC X(4).\n"
            "    05  WS-PART-Y PIC X(4).\n"
            "66  WS-XY RENAMES WS-PART-X THRU WS-PART-Y.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_66_missing_renames_keyword_skipped(self):
        """A 66 item without RENAMES should be skipped gracefully."""
        src = _wrap(
            "01  WS-RECORD.\n"
            "    05  WS-F PIC X(3).\n"
            "66  WS-BAD INVALID-CLAUSE WS-F.\n"
        )
        # Should not raise; result may have errors but ast should not be None
        result = _parse(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Level 88 condition-name items
# ---------------------------------------------------------------------------


class TestLevel88ConditionNames:
    def test_level_88_single_value(self):
        src = _wrap(
            "01  WS-STATUS PIC X.\n"
            "    88  WS-ACTIVE VALUE 'A'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_88_multiple_values(self):
        src = _wrap(
            "01  WS-CODE PIC X.\n"
            "    88  WS-YES VALUE 'Y' 'y'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_88_through_range(self):
        src = _wrap(
            "01  WS-GRADE PIC 9.\n"
            "    88  WS-HIGH-GRADE VALUE 7 THROUGH 9.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_88_thru_range(self):
        src = _wrap(
            "01  WS-SCORE PIC 99.\n"
            "    88  WS-PASS VALUE 50 THRU 100.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_88_value_is_keyword(self):
        """VALUE IS ... form."""
        src = _wrap(
            "01  WS-FLAG PIC X.\n"
            "    88  WS-ON VALUE IS 'T'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_level_88_value_are_keyword(self):
        """VALUE ARE ... form."""
        src = _wrap(
            "01  WS-STATE PIC 9.\n"
            "    88  WS-DONE VALUE ARE 9.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# OCCURS DEPENDING ON  (variable-length tables)
# ---------------------------------------------------------------------------


class TestOccursDependingOn:
    def test_occurs_depending_on_basic(self):
        src = _wrap(
            "01  WS-TABLE-SIZE PIC 9(3) VALUE 0.\n"
            "01  WS-TABLE.\n"
            "    05  WS-ENTRY OCCURS 1 TO 100 TIMES\n"
            "               DEPENDING ON WS-TABLE-SIZE.\n"
            "        10  WS-KEY PIC X(8).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        entry = next((i for i in items if i.name == "WS-ENTRY"), None)
        assert entry is not None
        assert entry.occurs_clause is not None
        assert entry.occurs_clause.depending_on == "WS-TABLE-SIZE"

    def test_occurs_depending_on_without_times_keyword(self):
        """OCCURS n TO m DEPENDING ON x (no TIMES keyword)."""
        src = _wrap(
            "01  WS-N PIC 9(2) VALUE 0.\n"
            "01  WS-VAR-TBL.\n"
            "    05  WS-ROW OCCURS 0 TO 50 DEPENDING ON WS-N.\n"
            "        10  WS-VAL PIC 9(5).\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_occurs_indexed_by(self):
        src = _wrap(
            "01  WS-IDX-TABLE.\n"
            "    05  WS-ITEM OCCURS 10 TIMES INDEXED BY WS-IDX.\n"
            "        10  WS-DATA PIC X(5).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        item = next((i for i in items if i.name == "WS-ITEM"), None)
        assert item is not None
        assert item.occurs_clause is not None

    def test_occurs_fixed_count(self):
        src = _wrap(
            "01  WS-ARRAY.\n"
            "    05  WS-EL OCCURS 5 TIMES PIC X(3).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        el = next((i for i in items if i.name == "WS-EL"), None)
        assert el is not None
        assert el.occurs_clause is not None
        assert el.occurs_clause.max_times == 5


# ---------------------------------------------------------------------------
# REDEFINES clause
# ---------------------------------------------------------------------------


class TestRedefinesClause:
    def test_redefines_basic(self):
        src = _wrap(
            "01  WS-ORIGINAL PIC X(4).\n"
            "01  WS-REDEFINED REDEFINES WS-ORIGINAL PIC 9(4).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        rd = next((i for i in items if i.name == "WS-REDEFINED"), None)
        assert rd is not None
        assert rd.redefines == "WS-ORIGINAL"

    def test_redefines_nested(self):
        src = _wrap(
            "01  WS-BASE.\n"
            "    05  WS-A PIC X(8).\n"
            "01  WS-OVERLAY REDEFINES WS-BASE.\n"
            "    05  WS-B1 PIC X(4).\n"
            "    05  WS-B2 PIC X(4).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        ov = next((i for i in items if i.name == "WS-OVERLAY"), None)
        assert ov is not None
        assert ov.redefines == "WS-BASE"


# ---------------------------------------------------------------------------
# FILLER items
# ---------------------------------------------------------------------------


class TestFillerItems:
    def test_filler_explicit(self):
        src = _wrap(
            "01  WS-REC.\n"
            "    05  FILLER PIC X(3) VALUE 'HDR'.\n"
            "    05  WS-DATA PIC X(10).\n"
        )
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "FILLER" for i in items)

    def test_filler_implicit_anonymous(self):
        """An item with no name becomes ANONYMOUS-level-line."""
        src = _wrap(
            "01  WS-REC.\n"
            "    05  PIC X(5).\n"
        )
        result = _assert_parsed(src)
        # Just verify parsing succeeds
        assert result.ast is not None


# ---------------------------------------------------------------------------
# LOCAL-STORAGE and LINKAGE sections
# ---------------------------------------------------------------------------


class TestAdditionalSections:
    def test_local_storage_section(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "LOCAL-STORAGE SECTION.\n"
            "01  LS-FIELD PIC X(10).\n"
            "PROCEDURE DIVISION.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_linkage_section(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "LINKAGE SECTION.\n"
            "01  LK-PARM PIC X(30).\n"
            "PROCEDURE DIVISION USING LK-PARM.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_multiple_sections(self):
        src = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01  WS-A PIC X.\n"
            "LOCAL-STORAGE SECTION.\n"
            "01  LS-B PIC 9.\n"
            "LINKAGE SECTION.\n"
            "01  LK-C PIC X(10).\n"
            "PROCEDURE DIVISION USING LK-C.\n"
            "    STOP RUN.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# USAGE clause variants
# ---------------------------------------------------------------------------


class TestUsageVariants:
    def test_usage_display(self):
        src = _wrap("01  WS-DISP PIC X(5) USAGE DISPLAY.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_usage_comp(self):
        src = _wrap("01  WS-COMP PIC 9(4) USAGE COMP.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_usage_comp_3_without_keyword(self):
        src = _wrap("01  WS-PKD PIC S9(7)V99 COMP-3.\n")
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_usage_binary(self):
        src = _wrap("01  WS-BIN PIC 9(9) USAGE BINARY.\n")
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# PICTURE clause variety
# ---------------------------------------------------------------------------


class TestPictureClauseVariants:
    def test_pic_with_sign_and_decimal(self):
        src = _wrap("01  WS-AMT PIC S9(7)V99 COMP-3.\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "WS-AMT" for i in items)

    def test_pic_display_edited(self):
        src = _wrap("01  WS-FMT PIC ZZZ,ZZ9.99.\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "WS-FMT" for i in items)

    def test_pic_all_nines(self):
        src = _wrap("01  WS-N PIC 9(9).\n")
        result = _assert_parsed(src)
        items = result.ast.find_all_by_type("DataItem")
        assert any(i.name == "WS-N" for i in items)
