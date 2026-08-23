"""Regression coverage for OCCURS/INDEXED BY clause shapes found failing in
a real mainframe corpus retry ("Unparsed token 'TIMES'/'INDEX' ... clause
not fully supported").

Four independent gaps, all in the OCCURS clause walk (pure-Python
``data_clauses._parse_occurs_clause`` and its Cython mirror in
``_data_fast.pyx`` -- both fixed identically):

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
