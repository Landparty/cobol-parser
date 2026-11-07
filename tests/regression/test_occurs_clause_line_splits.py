"""Regression coverage for OCCURS/INDEXED BY clause shapes found failing in
a real mainframe corpus retry ("Unparsed token 'TIMES'/'INDEX' ... clause
not fully supported").

Four independent gaps, all in the OCCURS clause walk
(``data_clauses._parse_occurs_clause``):

1. **Count on the line after OCCURS.** A long data name routinely pushes
   ``OCCURS`` to the end of its 72-column line, with ``40 TIMES INDEXED BY
   ...`` continuing on the next. The count read did not skip NEWLINEs, so
   a two-digit count on the next line -- which lexes as LEVEL_NUMBER --
   was misread by the caller's clause loop as a *new data item's level
   number*, fabricating a phantom item (e.g. ``ANONYMOUS-40-7``) while the
   real item silently recorded a table size of 0.
2. **Comma-separated INDEXED BY index names** (``INDEXED BY I1, I2``): the
   name loop broke on the comma, dropping every name after the first.
3. **INDEXED and BY straddling a line break**: the BY check did not skip
   NEWLINEs, so ``INDEXED`` at end-of-line dropped the whole clause.
4. **Bare INDEX usage** (``05 X INDEX.``): USAGE and IS are both optional
   in the grammar and INDEX is a reserved word, but only the ``USAGE [IS]
   INDEX`` spelling was recognized -- the bare form fell through to the
   unknown-clause branch as "Unparsed token 'INDEX'".
"""

from cobolparser import parse_cobol


def _pad80(seq: str, text: str, stamp: str = "00110000") -> str:
    # Realistic deck line: cols 1-6 sequence, col 7 indicator, cols 73-80 stamp.
    line = seq.ljust(6)[:6] + " " + text
    return line.ljust(72)[:72] + stamp


def _parse(data_lines: list[str]):
    hdr = [
        ("010100", "IDENTIFICATION DIVISION."),
        ("010200", "PROGRAM-ID. OCCTEST."),
        ("010300", "DATA DIVISION."),
        ("010400", "WORKING-STORAGE SECTION."),
    ]
    ftr = [
        ("020100", "PROCEDURE DIVISION."),
        ("020200", "    DISPLAY 'HI'."),
        ("020300", "    STOP RUN."),
    ]
    lines = [_pad80(s, t) for s, t in hdr] + data_lines + [_pad80(s, t) for s, t in ftr]
    result = parse_cobol("\n".join(lines) + "\n", filename="occtest.cbl")
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return result


def _occurs_of(result, name: str):
    for item in result.ast.find_all_by_type("CobolDataItem"):
        if item.name == name:
            occ = getattr(item, "occurs_clause", None)
            assert occ is not None, f"{name} lost its OCCURS clause"
            return occ
    raise AssertionError(f"data item {name} not found")


class TestOccursCountOnNextLine:
    def test_two_digit_count_after_line_break(self):
        # Two-digit count lexes as LEVEL_NUMBER: this was the phantom-item
        # shape (the 40 became a new item's level number).
        result = _parse(
            [
                _pad80("011000", "01  WS-TAB."),
                _pad80(
                    "011100", "    05  WS-VERY-LONG-ITEM-NAME-FIELD-X          OCCURS"
                ),
                _pad80("011200", "        40 TIMES INDEXED BY WS-IDX  PIC X(5)."),
            ]
        )
        occ = _occurs_of(result, "WS-VERY-LONG-ITEM-NAME-FIELD-X")
        assert occ.max_times == 40
        assert occ.index_names == ["WS-IDX"]
        # No phantom item fabricated from the count token.
        names = [i.name for i in result.ast.find_all_by_type("CobolDataItem")]
        assert not any(n.startswith("ANONYMOUS") for n in names), names

    def test_three_digit_count_after_line_break(self):
        # Three digits lex as NUMERIC_LITERAL -- same break, different token.
        result = _parse(
            [
                _pad80("011000", "01  WS-TAB."),
                _pad80(
                    "011100", "    05  WS-VERY-LONG-ITEM-NAME-FIELD-X          OCCURS"
                ),
                _pad80("011200", "        100 TIMES INDEXED BY WS-IDX  PIC X(5)."),
            ]
        )
        occ = _occurs_of(result, "WS-VERY-LONG-ITEM-NAME-FIELD-X")
        assert occ.max_times == 100

    def test_variable_occurs_split_around_to(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-CNT  PIC 999 VALUE 5."),
                _pad80("011100", "01  WS-TAB."),
                _pad80("011200", "    05  WS-ITEM  OCCURS 1 TO"),
                _pad80("011300", "        100 TIMES DEPENDING ON WS-CNT PIC X."),
            ]
        )
        occ = _occurs_of(result, "WS-ITEM")
        assert occ.min_times == 1
        assert occ.max_times == 100
        assert occ.depending_on == "WS-CNT"


class TestIndexedByShapes:
    def test_comma_separated_index_names(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-TAB."),
                _pad80(
                    "011100",
                    "    05  WS-ITEM  OCCURS 40 TIMES INDEXED BY I1, I2 PIC X.",
                ),
            ]
        )
        occ = _occurs_of(result, "WS-ITEM")
        assert occ.index_names == ["I1", "I2"]

    def test_indexed_and_by_straddling_line_break(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-TAB."),
                _pad80("011100", "    05  WS-ITEM  OCCURS 40 TIMES INDEXED"),
                _pad80("011200", "        BY WS-IDX  PIC X(5)."),
            ]
        )
        occ = _occurs_of(result, "WS-ITEM")
        assert occ.index_names == ["WS-IDX"]

    def test_comma_separated_ascending_key_names(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-TAB."),
                _pad80("011100", "    05  WS-GRP  OCCURS 40 TIMES"),
                _pad80("011200", "        ASCENDING KEY IS WS-K1, WS-K2"),
                _pad80("011300", "        INDEXED BY WS-IDX."),
                _pad80("011400", "        10  WS-K1  PIC X(3)."),
                _pad80("011500", "        10  WS-K2  PIC X(3)."),
            ]
        )
        occ = _occurs_of(result, "WS-GRP")
        assert occ.key_clauses == [
            {"direction": "ASCENDING", "keys": ["WS-K1", "WS-K2"]}
        ]
        assert occ.index_names == ["WS-IDX"]


class TestBareIndexUsage:
    def test_bare_index_usage_clause(self):
        result = _parse([_pad80("011000", "01  WS-I  INDEX.")])
        items = {i.name: i for i in result.ast.find_all_by_type("CobolDataItem")}
        assert items["WS-I"].usage == "INDEX"

    def test_is_index_usage_clause(self):
        result = _parse([_pad80("011000", "01  WS-I  IS INDEX.")])
        items = {i.name: i for i in result.ast.find_all_by_type("CobolDataItem")}
        assert items["WS-I"].usage == "INDEX"


class TestOccursMissingCountRecovery:
    """A `/code-review` pass on the line-split fix caught an error-recovery
    regression it introduced: with the count read unconditionally skipping
    NEWLINEs, a malformed ``OCCURS`` with *no count at all* consumed the
    next data item's own level number (a LEVEL_NUMBER token, exactly what
    the count read accepts) as the count -- fabricating a table size from
    the neighbor's level, overwriting the OCCURS item's PIC with the
    neighbor's, and deleting the neighbor from the AST outright. The read
    is now guarded (``_peek_count_token`` / ``_peek_count_pos``): a
    LEVEL_NUMBER reached only by crossing a line break counts only when
    the token after it reads like the OCCURS clause continuing."""

    def test_missing_count_does_not_swallow_next_item(self):
        source_lines = [
            _pad80("011000", "01  WS-TAB."),
            _pad80("011100", "    05  WS-ITEM  PIC X(5) OCCURS"),
            _pad80("011200", "    05  WS-NEXT  PIC X(3)."),
        ]
        hdr = [
            ("010100", "IDENTIFICATION DIVISION."),
            ("010200", "PROGRAM-ID. OCCTEST."),
            ("010300", "DATA DIVISION."),
            ("010400", "WORKING-STORAGE SECTION."),
        ]
        ftr = [
            ("020100", "PROCEDURE DIVISION."),
            ("020200", "    DISPLAY 'HI'."),
            ("020300", "    STOP RUN."),
        ]
        lines = (
            [_pad80(s, t) for s, t in hdr]
            + source_lines
            + [_pad80(s, t) for s, t in ftr]
        )
        # No _parse(): this deck is deliberately malformed, so warnings are
        # expected -- what must NOT happen is silent AST corruption.
        result = parse_cobol("\n".join(lines) + "\n", filename="occtest.cbl")
        items = {i.name: i for i in result.ast.find_all_by_type("CobolDataItem")}
        assert "WS-NEXT" in items, "next item swallowed as the OCCURS count"
        assert getattr(items["WS-NEXT"].picture_clause, "pattern", None) == "X(3)"
        assert getattr(items["WS-ITEM"].picture_clause, "pattern", None) == "X(5)"
        occ = getattr(items["WS-ITEM"], "occurs_clause", None)
        assert occ is None or occ.max_times in (0, None)


class TestDependingOnLineSplit:
    """`DEPENDING ON` at end of line with the variable on the next --
    the same 72-column split class as the count fix, caught one clause
    further down by the same review pass. Without the newline skips the
    clause silently degraded to a *fixed* OCCURS and the variable fell out
    as an unparsed token."""

    def test_variable_on_next_line(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-CNT  PIC 999 VALUE 5."),
                _pad80("011100", "01  WS-TAB."),
                _pad80("011200", "    05  WS-ITEM  OCCURS 1 TO 100 TIMES DEPENDING ON"),
                _pad80("011300", "        WS-CNT  PIC X."),
            ]
        )
        occ = _occurs_of(result, "WS-ITEM")
        assert occ.depending_on == "WS-CNT"
        assert occ.min_times == 1
        assert occ.max_times == 100


class TestSignClauseLineSplit:
    """``SIGN IS`` at end of line used to record the raw newline character
    as the sign clause (the direction read accepted any truthy token
    value); the read is now restricted to LEADING/TRAILING and each
    keyword may start a continuation line."""

    def test_direction_on_next_line(self):
        result = _parse(
            [
                _pad80("011000", "01  WS-AMT  PIC S9(5) SIGN IS"),
                _pad80("011100", "        LEADING SEPARATE."),
            ]
        )
        items = {i.name: i for i in result.ast.find_all_by_type("CobolDataItem")}
        assert items["WS-AMT"].sign_clause == "LEADING SEPARATE"
