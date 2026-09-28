"""Regression tests for the 2026-09-28 accelerator / fixed-format audit.

Each class covers one finding and runs against both implementations it
touches: the pure-Python normalizer and whichever one the package exposes
(the Cython ``_preprocess_fast`` when compiled), and the DATA DIVISION clause
loop with and without the Cython ``_data_fast`` helper.
"""

from __future__ import annotations

import json

import pytest

import cobolparser.parsers.divisions.data_clauses as data_clauses
from cobolparser import parse_cobol, parse_cobol_with_expansion
from cobolparser.preprocess import _normalize_fixed_format_pure, normalize_fixed_format
from cobolparser.preprocess.copy_statement_parser import normalize_continuation_lines

NORMALIZERS = [
    pytest.param(_normalize_fixed_format_pure, id="pure"),
    pytest.param(normalize_fixed_format, id="package"),
]

# ``fast`` only differs from ``pure`` when the extension is compiled; it is
# still run otherwise (both then take the pure-Python loop).
DATA_PATHS = [pytest.param(True, id="fast"), pytest.param(False, id="pure")]


@pytest.fixture
def data_path(request, monkeypatch):
    monkeypatch.setattr(
        data_clauses,
        "_HAS_DATA_FAST",
        bool(request.param and data_clauses._fast_data_item_clauses is not None),
    )
    return request.param


def _prog(*ws: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + "".join(line + "\n" for line in ws)
        + "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _items(result) -> dict[str, dict]:
    out = {}
    for item in result.ast.find_all_by_type("CobolDataItem"):
        out[item.name] = item.to_dict()
    return out


def _to_72(record: str) -> str:
    return " " * (72 - len(record))


# ---------------------------------------------------------------------------
# 1. _data_fast: an OCCURS count past INT_MAX raised OverflowError
# ---------------------------------------------------------------------------


class TestOccursCountBeyondCInt:
    """The compiled clause loop held OCCURS counts in C ``int``s. ``int()`` of
    a count past 2**31-1 then raised ``OverflowError`` -- not one of the
    ``TypeError``/``ValueError`` the loop guards against -- and the division
    loop recovered by abandoning the whole DATA DIVISION: every item gone,
    one "value too large to convert to int" error at line 1. The pure-Python
    walker keeps the count as a Python int."""

    SRC = _prog(
        "       01 WS-T.",
        "          05 WS-E PIC X OCCURS 3000000000 TIMES.",
        "          05 WS-F PIC X OCCURS 1 TO 2147483648 TIMES DEPENDING ON WS-N.",
        "       01 WS-N PIC 9(10).",
    )

    @pytest.mark.parametrize("data_path", DATA_PATHS, indirect=True)
    def test_large_counts_keep_the_division(self, data_path):
        result = parse_cobol(self.SRC)
        assert result.errors == []
        items = _items(result)
        assert set(items) == {"WS-T", "WS-E", "WS-F", "WS-N"}
        assert items["WS-E"]["occurs_clause"]["max_times"] == 3000000000
        assert items["WS-F"]["occurs_clause"]["min_times"] == 1
        assert items["WS-F"]["occurs_clause"]["max_times"] == 2147483648

    def test_fast_and_pure_agree(self, monkeypatch):
        dumps = []
        for fast in (True, False):
            monkeypatch.setattr(
                data_clauses,
                "_HAS_DATA_FAST",
                fast and data_clauses._fast_data_item_clauses is not None,
            )
            dumps.append(json.dumps(parse_cobol(self.SRC).ast.to_dict(), default=str))
        assert dumps[0] == dumps[1]


# ---------------------------------------------------------------------------
# 2. A continued literal on a record shorter than column 72
# ---------------------------------------------------------------------------


class TestShortRecordContinuedLiteral:
    """A literal left open at end of line runs through column 72, blanks
    included (the M5 rule). A record whose trailing blanks were stripped --
    by an editor, a file transfer: most copies of a deck kept off the
    mainframe -- stops short of column 72, but the columns it lost are still
    blanks inside the literal. They were dropped, so the same program read
    ``'ERROR: NOTFOUND'`` stripped and ``'ERROR: NOT FOUND'`` unstripped."""

    OPENER = "           DISPLAY 'ERROR: CUSTOMER NOT "
    CONT = "      -    'FOUND'."

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_stripped_record_reads_like_the_full_width_one(self, normalize):
        full = normalize([self.OPENER.ljust(72), self.CONT])
        stripped = normalize([self.OPENER.rstrip(), self.CONT])
        assert stripped == full
        assert "'ERROR: CUSTOMER NOT" + _to_72(self.OPENER.rstrip()) + "FOUND'" in full

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_every_short_record_of_a_multi_record_literal_is_padded(self, normalize):
        lines = [
            '       01  WS-A PIC X(200) VALUE "ABC',
            '      -    "DEF',
            '      -    "GHI".',
        ]
        want = (
            '01  WS-A PIC X(200) VALUE "ABC'
            + _to_72(lines[0])
            + "DEF"
            + _to_72(lines[1])
            + 'GHI".\n\n\n'
        )
        assert normalize(lines) == want
        assert normalize([line.ljust(72) for line in lines[:2]] + lines[2:]) == want

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_comment_between_the_pieces_still_pays_the_pad(self, normalize):
        lines = [
            '       01  WS-A PIC X(80) VALUE "ABC',
            "      * interrupting comment",
            '      -    "DEF".',
        ]
        assert normalize(lines) == (
            '01  WS-A PIC X(80) VALUE "ABC' + _to_72(lines[0]) + 'DEF".\n\n\n'
        )

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_no_pad_without_a_continuation(self, normalize):
        # Nothing resumes the literal, so nothing is owed: an unterminated
        # literal cut off by a comment keeps its historical text.
        lines = ['           DISPLAY "oops', "      * end of program"]
        assert normalize(lines) == '    DISPLAY "oops\n\n'

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_literal_ending_in_column_72_needs_no_pad(self, normalize):
        opener = ("       01  WS-A PIC X(10) VALUE" + ' "ABCDE'.rjust(41))[:72]
        assert len(opener) == 72
        out = normalize([opener, '      -    "FGHIJ".'])
        assert '"ABCDEFGHIJ"' in out

    def test_parse_and_expansion_agree(self, tmp_path):
        (tmp_path / "CPY1.cpy").write_text("       01  CPY-ITEM PIC X.\n")
        opener = "       01  WS-MSG PIC X(60) VALUE 'ERROR: CUSTOMER NOT"
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY CPY1.",
            opener,
            "      -    'FOUND'.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        ]
        src = "\n".join(lines) + "\n"
        want = '"ERROR: CUSTOMER NOT' + _to_72(opener) + 'FOUND"'
        direct = parse_cobol(src.replace("       COPY CPY1.\n", ""))
        expanded = parse_cobol_with_expansion(src, "t.cbl", [str(tmp_path)])
        assert _items(direct)["WS-MSG"]["value_clause"] == want
        assert _items(expanded)["WS-MSG"]["value_clause"] == want

    def test_expander_pads_each_record_it_merges(self):
        first = "       01  WS-A PIC X(200) VALUE 'ABC"
        second = "      -    'DEF"
        src = first + "\n" + second + "\n      -    'GHI'.\n"
        assert normalize_continuation_lines(src) == (
            first + _to_72(first) + "DEF" + _to_72(second) + "GHI'.\n"
        )


# ---------------------------------------------------------------------------
# 3. `*>` floating comments inside a data description entry
# ---------------------------------------------------------------------------


class TestFloatingCommentInDataEntry:
    """A ``*>`` floating comment (Enterprise COBOL 6.x) can end any line of a
    data description entry, including one that breaks between a clause
    keyword and its operand. The sub-clause readers skipped line breaks but
    not COMMENT tokens, so the operand after the comment was dropped as an
    "unparsed token" -- or, for ``OCCURS *> ...`` / ``10 TIMES``, read as a
    phantom data item with level number 10. Both clause loops did it."""

    @pytest.mark.parametrize("data_path", DATA_PATHS, indirect=True)
    def test_indexed_by_after_a_comment(self, data_path):
        result = parse_cobol(
            _prog(
                "       01 WS-T.",
                "          05 WS-E PIC X OCCURS 10 TIMES *> one per region",
                "                  INDEXED BY IX.",
            )
        )
        assert result.warnings == []
        occurs = _items(result)["WS-E"]["occurs_clause"]
        assert occurs["max_times"] == 10
        assert occurs["index_names"] == ["IX"]

    @pytest.mark.parametrize("data_path", DATA_PATHS, indirect=True)
    def test_occurs_count_after_a_comment_is_not_a_level_number(self, data_path):
        result = parse_cobol(
            _prog(
                "       01 WS-T.",
                "          05 WS-E PIC X OCCURS *> sized for the worst case",
                "                  10 TIMES DEPENDING ON WS-N.",
                "       01 WS-N PIC 99.",
            )
        )
        assert result.warnings == []
        items = _items(result)
        assert set(items) == {"WS-T", "WS-E", "WS-N"}
        occurs = items["WS-E"]["occurs_clause"]
        assert (occurs["max_times"], occurs["depending_on"]) == (10, "WS-N")

    @pytest.mark.parametrize("data_path", DATA_PATHS, indirect=True)
    def test_picture_and_value_operands_after_a_comment(self, data_path):
        result = parse_cobol(
            _prog(
                "       01 WS-A PIC *> customer name",
                "              X(10) VALUE *> blank until read",
                "              SPACES.",
                "       01 WS-B REDEFINES *> same bytes",
                "              WS-A PIC 9(10).",
            )
        )
        assert result.warnings == []
        items = _items(result)
        assert items["WS-A"]["picture_clause"]["pattern"] == "X(10)"
        assert items["WS-A"]["value_clause"] == "SPACES"
        assert items["WS-B"]["redefines"] == "WS-A"
