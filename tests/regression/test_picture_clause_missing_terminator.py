"""Regression test: a PICTURE clause with no terminating period, immediately
followed by what looks like the next data item's own `level-number data-name`
header, used to be silently absorbed into the picture pattern instead of
ending the clause.

`parse_picture_clause`'s token-collection loop treats a NEWLINE as "more
picture pattern may follow" unconditionally -- correct for legitimate
multi-line PICTURE clauses (see test_value_picture_clause_continuation.py),
but wrong when the period was simply lost. The lexer types every 1-2 digit
integer as TokenType.LEVEL_NUMBER regardless of context, and LEVEL_NUMBER is
one of the token types the picture-pattern loop happily collects -- so a bare
level number belonging to the *next* data item (`05  bariable`) got appended
to the previous item's pattern, and the following IDENTIFIER (the next
item's name) went with it. The next item's own node -- along with all of its
children -- vanished from the AST entirely, with `result.success == True`
and `result.warnings == []`: no signal at all.

The most common real-world trigger is fixed-format column-72 truncation:
`normalize_fixed_format` extracts only columns 8-72 (matching GnuCOBOL's own
column-72 truncation semantics, confirmed empirically against GnuCOBOL 3.2
in Docker -- a source file with the same shape fails to compile there with
"group item cannot have PICTURE clause" / "syntax error, unexpected Literal"
rather than silently accepting it), so a terminating period placed at column
73+ is silently dropped from the normalized text, leaving the PICTURE clause
with no period at all. But the underlying parser bug is not fixed-format
specific -- it reproduces with plain free-form source missing a period too
(see TestFreeFormMissingPeriod below).

Fix: the picture-pattern loop's NEWLINE branch now looks ahead past the
newline; if it finds a LEVEL_NUMBER that cannot legally be more picture
pattern -- either its value contains a digit other than 0/9 (the only two
digit-shaped PICTURE symbols), or it's immediately followed by an
IDENTIFIER (a named or FILLER data item) -- it stops the clause there
instead of consuming the newline, and records a ParseResult.warnings entry,
consistent with the "dropped-content signal" contract other silent-drop
fixes in this codebase already use. The digit-content signal additionally
covers an *anonymous* next item (no data-name at all, e.g. a bare
`05  REDEFINES ...`), which a name-shaped lookahead alone would miss.
"""

from __future__ import annotations

from cobolparser import parse_cobol


def _item_by_name(result, name: str):
    for item in result.ast.find_all_by_type("CobolDataItem"):
        if item.name == name:
            return item
    raise AssertionError(
        f"no data item named {name!r}; parsed names: "
        f"{[i.name for i in result.ast.find_all_by_type('CobolDataItem')]}"
    )


def _child_data_item_names(item) -> set[str]:
    return {
        getattr(c, "name", None)
        for c in item.children
        if type(c).__name__ == "CobolDataItem"
    }


_FIXED_FORMAT_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RECORD.
           05  VARIABLE                             PIC X(08).
           05  Variable-name
                  REDEFINES  VARIABLE                          PIC 9(08).
           05  bariable
                  REDEFINES  VARIABLE.
               10  BARIABLE-B1  PIC X(04).
               10  BARIABLE-B2  PIC X(04).
       PROCEDURE DIVISION.
           STOP RUN.
"""


class TestFixedFormatColumnTruncation:
    def test_terminating_period_lands_at_column_73(self):
        # Sanity check on the fixture itself: the period after PIC 9(08)
        # must sit at column 73 (past the traditional Area B boundary) for
        # this to actually exercise normalize_fixed_format's truncation.
        line = _FIXED_FORMAT_SRC.splitlines()[7]
        assert line.index(".", line.index("9(08)")) + 1 == 73

    def test_next_item_is_not_dropped(self):
        result = parse_cobol(_FIXED_FORMAT_SRC, filename="test.cob")
        assert result.ast is not None
        names = {item.name for item in result.ast.find_all_by_type("CobolDataItem")}
        assert "bariable" in names
        assert "BARIABLE-B1" in names
        assert "BARIABLE-B2" in names

    def test_children_are_attached_to_the_recovered_item_not_the_sibling(self):
        # The original defect didn't just drop `bariable` -- its own
        # children got misattached to the *preceding* item (`Variable-name`)
        # instead. Presence alone (test_next_item_is_not_dropped) doesn't
        # catch a regression that recovers the item but re-parents its
        # children wrongly, so check parentage explicitly.
        result = parse_cobol(_FIXED_FORMAT_SRC, filename="test.cob")
        ws_record = _item_by_name(result, "WS-RECORD")
        variable_name = _item_by_name(result, "Variable-name")
        bariable = _item_by_name(result, "bariable")
        assert _child_data_item_names(ws_record) == {
            "VARIABLE",
            "Variable-name",
            "bariable",
        }
        assert _child_data_item_names(variable_name) == set()
        assert _child_data_item_names(bariable) == {"BARIABLE-B1", "BARIABLE-B2"}

    def test_previous_item_picture_is_not_corrupted(self):
        result = parse_cobol(_FIXED_FORMAT_SRC, filename="test.cob")
        items = {
            item.name: item for item in result.ast.find_all_by_type("CobolDataItem")
        }
        pattern = items["Variable-name"].picture_clause.pattern
        assert "bariable" not in pattern
        assert pattern == "9(08)"

    def test_dropped_content_is_signaled_via_warnings(self):
        result = parse_cobol(_FIXED_FORMAT_SRC, filename="test.cob")
        assert result.warnings, "missing terminating period must not be silent"


_FREE_FORM_PREFIX = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
"""

_FREE_FORM_SUFFIX = """\
PROCEDURE DIVISION.
MAIN-PARA.
    STOP RUN.
"""


class TestFreeFormMissingPeriod:
    """Same bug, no fixed-format columns involved: a plain missing period
    in free-form source triggers the identical picture-pattern-loop defect.
    """

    def test_next_item_is_not_dropped(self):
        src = (
            _FREE_FORM_PREFIX
            + "01  WS-RECORD.\n"
            + "    05  VARIABLE PIC X(08).\n"
            + "    05  VARIABLE-NAME REDEFINES VARIABLE PIC 9(08)\n"
            + "    05  BARIABLE REDEFINES VARIABLE.\n"
            + "        10  BARIABLE-B1  PIC X(04).\n"
            + "        10  BARIABLE-B2  PIC X(04).\n"
            + _FREE_FORM_SUFFIX
        )
        result = parse_cobol(src, filename="test.cob", free_form=True)
        assert result.ast is not None
        names = {item.name for item in result.ast.find_all_by_type("CobolDataItem")}
        assert "BARIABLE" in names
        assert "BARIABLE-B1" in names
        assert "BARIABLE-B2" in names
        assert result.warnings


class TestAnonymousNextItem:
    """The next item may have no data-name at all (anonymous, distinct from
    FILLER). A lookahead keyed only on "LEVEL_NUMBER followed by
    IDENTIFIER" misses this shape entirely -- `05  REDEFINES ...` has no
    IDENTIFIER after the level number, just a clause keyword. This class
    pins the grammar-based fallback: a LEVEL_NUMBER value containing any
    digit other than 0/9 (here, the '5' in "05") can never be legal
    PICTURE content, so it is treated as a new item regardless of what
    follows it.
    """

    _SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RECORD.
           05  VARIABLE                             PIC X(08).
           05  Variable-name
                  REDEFINES  VARIABLE                          PIC 9(08).
           05  REDEFINES  VARIABLE.
               10  BARIABLE-B1  PIC X(04).
               10  BARIABLE-B2  PIC X(04).
       PROCEDURE DIVISION.
           STOP RUN.
"""

    def test_anonymous_item_is_not_dropped(self):
        result = parse_cobol(self._SRC, filename="test.cob")
        assert result.ast is not None
        variable_name = _item_by_name(result, "Variable-name")
        assert variable_name.picture_clause.pattern == "9(08)"
        anonymous_items = [
            item
            for item in result.ast.find_all_by_type("CobolDataItem")
            if item.name.startswith("ANONYMOUS-")
        ]
        assert len(anonymous_items) == 1, [
            i.name for i in result.ast.find_all_by_type("CobolDataItem")
        ]
        anonymous_item = anonymous_items[0]
        assert anonymous_item.redefines == "VARIABLE"
        assert _child_data_item_names(anonymous_item) == {
            "BARIABLE-B1",
            "BARIABLE-B2",
        }
        assert _child_data_item_names(variable_name) == set()
        assert result.warnings
