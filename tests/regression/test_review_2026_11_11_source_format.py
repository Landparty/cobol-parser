"""Source-format findings from a run over a private mainframe checkout (2026-11-11).

* A1 -- fixed-format copybooks read as free-form during a program parse.
  The member detector sampled only the first ten non-blank lines, so a
  banner whose lines carry something odd in columns 1-6 (a ``"`` in column
  3, a change note with blanks in it) outvoted the rest of the member; its
  comment lines were then parsed as code. Every non-blank line now votes,
  any valid column-7 indicator counts as fixed whatever columns 1-6 hold, a
  tie goes to the including program's format, ``source_format: fixed``
  reaches the members, and a member read as free-form under a fixed-format
  program draws a warning.
* A2 -- gen-data, decode, data-items and the MCP record tools had their own
  detector, which counted every change-tagged sequence area (``CGOGP1``,
  ``JR5295``) as a free-form vote and shifted every line seven columns. It
  is gone; they use the A1 detector.
* A3 -- a ``COPY`` indented into Area B after ``DATE-COMPILED.`` was
  swallowed as part of the comment-entry, so the member's ENVIRONMENT and
  DATA DIVISIONs were never parsed; the parse succeeded with no data items.
* A5 -- ``EJECT``, ``SKIP1-3`` and ``TITLE`` between two data entries drew
  a false "may be missing terminating period".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser._source_text.normalize import validate_copybook_content
from cobolparser._source_text.source_format import detect_member_fixed_format
from cobolparser.layout.copybook import parse_copybook_records
from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import expand_copybooks


def _rec(text: str, indicator: str = " ", seq: str = "      ") -> str:
    return (seq + indicator + text).ljust(72)[:72]


def _program(copy_line: str = "    COPY MEMBER.") -> str:
    lines = [
        _rec("IDENTIFICATION DIVISION."),
        _rec("PROGRAM-ID. FMTTEST."),
        _rec("DATA DIVISION."),
        _rec("WORKING-STORAGE SECTION."),
        _rec(copy_line),
        _rec("PROCEDURE DIVISION."),
        _rec("MAIN-PARA."),
        _rec("    GOBACK."),
    ]
    return "\n".join(lines) + "\n"


def _write(path: Path, records: list[str]) -> None:
    path.write_text("\n".join(records) + "\n", encoding="utf-8", newline="")


#: A member whose first ten lines are a banner with a ``"`` in column 3 and
#: data entries carrying the same mark: the old ten-line sampler judged it
#: free-form, and its comment lines became code.
_QUOTE_BANNER = [
    _rec("* MOVE THE TOTAL TO THE REPORT", "*", '  "   '),
    _rec("* COMPUTE THE NET AMOUNT", "*", '  "   '),
    _rec("01  SGP-REC.", " ", '  "   '),
    _rec("    05  SGP-A  PIC X(10).", " ", '  "   '),
    _rec("    05  SGP-B  PIC 9(5).", " ", '  "   '),
    _rec("    05  SGP-C  PIC X(3).", " ", '  "   '),
    _rec("    05  SGP-D  PIC X(3).", " ", '  "   '),
    _rec("    05  SGP-E  PIC X(3).", " ", '  "   '),
    _rec("    05  SGP-F  PIC X(3).", " ", '  "   '),
    _rec("    05  SGP-G  PIC X(3).", " ", '  "   '),
    _rec("* MULTIPLY THE RATE BY THE BASE"),
    _rec("    05  SGP-H  PIC X(3)."),
]

#: Change tags with blanks in them (``CR 12``), which neither the strict nor
#: the tagged sequence-area rule accepted.
_SPACED_TAGS = [
    _rec("01  CR-REC.", " ", "CR 12 "),
    _rec("    05  CR-A  PIC X(10).", " ", "CR 12 "),
    _rec("    05  CR-B  PIC 9(5).", " ", "CR 13 "),
    _rec("* MOVE IT", "*", "CR 13 "),
    _rec("    05  CR-C  PIC X(3).", " ", "CR 14 "),
]


class TestA1MemberDetector:
    @pytest.mark.parametrize("records", [_QUOTE_BANNER, _SPACED_TAGS])
    def test_member_with_odd_sequence_area_is_fixed(self, records: list[str]) -> None:
        assert detect_member_fixed_format("\n".join(records) + "\n")

    def test_free_form_member_stays_free(self) -> None:
        text = "01 FREE-REC.\n   05 FREE-A PIC X.\n   05 FREE-B PIC 9.\n"
        assert not detect_member_fixed_format(text)

    def test_level_in_column_one_over_indented_children_stays_free(self) -> None:
        text = (
            "01 REC.\n"
            "           05 A PIC X.\n"
            "           05 B PIC X.\n"
            "           05 C PIC X.\n"
        )
        assert not detect_member_fixed_format(text)

    def test_tie_follows_the_including_program(self) -> None:
        # One fixed vote, one free vote: no evidence either way.
        text = "       05  A  PIC X.\nMOVE-IT.\n"
        assert detect_member_fixed_format(text, default=True)
        assert not detect_member_fixed_format(text, default=False)

    @pytest.mark.parametrize("records", [_QUOTE_BANNER, _SPACED_TAGS])
    def test_program_parse_reads_member_comments_as_comments(
        self, tmp_path: Path, records: list[str]
    ) -> None:
        _write(tmp_path / "MEMBER.cpy", records)
        result = parse_cobol_with_expansion(
            _program(),
            "FMTTEST.cbl",
            copybook_paths=[str(tmp_path)],
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert result.errors == []
        names = {item.name for item in result.ast.find_all_by_type("DataItem")}
        assert {"SGP-H"} <= names or {"CR-C"} <= names
        assert not any("read as free-form" in w for w in result.warnings)

    def test_source_format_fixed_reaches_the_members(self, tmp_path: Path) -> None:
        # Every line's columns 1-6 hold a level number and the start of a
        # name: detected free-form, but the user said fixed.
        _write(
            tmp_path / "MEMBER.cpy",
            ["01 AB  01  FX-REC.", "01 AB      05  FX-A  PIC X."],
        )
        auto = expand_copybooks(_program(), [str(tmp_path)])
        assert any("read as free-form" in w for w in auto.statistics.warnings)
        forced = expand_copybooks(_program(), [str(tmp_path)], source_format="fixed")
        assert "FX-REC" in forced.expanded_source
        assert "01 AB" not in forced.expanded_source
        result = parse_cobol_with_expansion(
            _program(),
            "FMTTEST.cbl",
            copybook_paths=[str(tmp_path)],
            preprocess_fixed=True,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        names = {item.name for item in result.ast.find_all_by_type("DataItem")}
        assert {"FX-REC", "FX-A"} <= names


class TestA2StandaloneCopybook:
    def test_change_tags_do_not_shift_the_layout(self) -> None:
        # Shifted seven columns, the commented-out OLD-B line's ``*`` landed
        # in the code area and OLD-B became a 9-byte junk field.
        source = "\n".join(
            [
                _rec("01  TAG-REC.", " ", "CGOGP1"),
                _rec("    05  TAG-A  PIC X(10).", " ", "JR5295"),
                _rec("    05  OLD-B  PIC 9(9).", "*", "BNCPB1"),
                _rec("    05  TAG-B  PIC 9(5).", " ", "BNCPB1"),
            ]
        )
        (record,) = parse_copybook_records(source)
        assert record.name == "TAG-REC"
        assert [c.name for c in record.children] == ["TAG-A", "TAG-B"]

    def test_quote_banner_parses_like_the_program_parse(self) -> None:
        (record,) = parse_copybook_records("\n".join(_QUOTE_BANNER) + "\n")
        assert record.name == "SGP-REC"
        assert len(record.children) == 8

    def test_free_form_fragment_still_works(self) -> None:
        (record,) = parse_copybook_records("01 FREE-REC.\n   05 FREE-A PIC X(4).\n")
        assert record.name == "FREE-REC"


class TestA3CommentEntryCopy:
    @pytest.mark.parametrize(
        "between", [None, "    EJECT", "    SKIP1", "    TITLE 'X'"]
    )
    def test_area_b_copy_after_date_compiled_is_expanded(
        self, tmp_path: Path, between: str | None
    ) -> None:
        _write(
            tmp_path / "E1MDFRE1.cpy",
            [
                _rec("ENVIRONMENT DIVISION."),
                _rec("DATA DIVISION."),
                _rec("WORKING-STORAGE SECTION."),
                _rec("01  WS-A  PIC X(10)."),
            ],
        )
        lines = [
            _rec("IDENTIFICATION DIVISION."),
            _rec("PROGRAM-ID. MDFREA03."),
            _rec("DATE-COMPILED."),
        ]
        if between:
            lines.append(_rec(between))
        lines += [
            _rec("    COPY E1MDFRE1."),
            _rec("PROCEDURE DIVISION."),
            _rec("MAIN-PARA."),
            _rec("    MOVE 'X' TO WS-A."),
            _rec("    GOBACK."),
        ]
        result = parse_cobol_with_expansion(
            "\n".join(lines) + "\n",
            "MDFREA03.cbl",
            copybook_paths=[str(tmp_path)],
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        names = {item.name for item in result.ast.find_all_by_type("DataItem")}
        assert "WS-A" in names

    def test_data_division_in_a_comment_entry_warns(self) -> None:
        # A division header indented into a comment-entry stays prose (NIST
        # OBNC1M embeds a phony program that way), but when the program then
        # has no DATA DIVISION of its own the loss is reported.
        source = "\n".join(
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. NODATA."),
                _rec("DATE-COMPILED."),
                _rec("    DATA DIVISION."),
                _rec("    WORKING-STORAGE SECTION."),
                _rec("    01  WS-A  PIC X(10)."),
                _rec("PROCEDURE DIVISION."),
                _rec("MAIN-PARA."),
                _rec("    MOVE 'X' TO WS-A."),
                _rec("    GOBACK."),
            ]
        )
        result = parse_cobol(source)
        (warning,) = [w for w in result.warnings if "no DATA DIVISION" in w]
        assert "DATE-COMPILED comment-entry" in warning

    def test_no_warning_without_data_text_in_the_entry(self) -> None:
        source = "\n".join(
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. NODATA."),
                _rec("DATE-COMPILED. TODAY."),
                _rec("PROCEDURE DIVISION."),
                _rec("MAIN-PARA."),
                _rec("    MOVE 'X' TO WS-A."),
                _rec("    GOBACK."),
            ]
        )
        assert not any("no DATA DIVISION" in w for w in parse_cobol(source).warnings)

    def test_copy_mid_line_in_remarks_is_still_prose(self) -> None:
        source = "\n".join(
            [
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. T1."),
                _rec("REMARKS. SEE COPY PAYREC."),
                _rec("    THE COPY ABOVE IS PROSE."),
                _rec("PROCEDURE DIVISION."),
                _rec("MAIN-PARA."),
                _rec("    GOBACK."),
            ]
        )
        result = parse_cobol(source)
        assert result.errors == []
        assert not any("was not expanded" in w for w in result.warnings)


class TestA5ListingDirectives:
    @pytest.mark.parametrize(
        "directive", ["EJECT", "EJECT.", "SKIP1", "SKIP3", "TITLE 'PAGE TWO'"]
    )
    def test_no_missing_period_warning(self, directive: str) -> None:
        content = "\n".join(
            [
                " 01  A.",
                "     05  B  PIC X.",
                f"     {directive}",
                "     05  C  PIC X.",
            ]
        )
        warnings = validate_copybook_content(content, "M.cpy", indicator_position=0)
        assert not any("terminating period" in w for w in warnings)

    def test_real_missing_period_still_reported(self) -> None:
        content = " 01  A.\n     05  B  PIC X\n     EJECT\n     05  C  PIC X.\n"
        # The entry for B ends at EJECT with no period.
        warnings = validate_copybook_content(content, "M.cpy", indicator_position=0)
        assert any("Line 2" in w and "terminating period" in w for w in warnings)
