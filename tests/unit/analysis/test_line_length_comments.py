"""The ``line-length`` lint rule and comments.

Text that the compiler reads as a comment cannot be cut by column 72 or lost
past column 80 in a way that changes the program, so the rule does not
report it: comment lines (``*`` and ``/`` in column 7), inline ``*>``
comments, and the comment-entries of the IDENTIFICATION DIVISION's
``AUTHOR.``, ``INSTALLATION.``, ``DATE-WRITTEN.``, ``DATE-COMPILED.``,
``SECURITY.`` and ``REMARKS.`` paragraphs. Program text on the same lines,
or after the entry ends, is still checked.
"""

from __future__ import annotations

from typing import Any

from cobolparser.analysis.lint import line_length_findings

SEQ = "000100"


def _fixed(area: str, indicator: str = " ") -> str:
    """A fixed-format line: sequence area, indicator, then *area* from col 8."""
    return SEQ + indicator + area


def _at_72(code: str, tail: str) -> str:
    """*code* (from column 8) padded so its last character sits in column 72,
    then *tail* from column 73."""
    assert len(code) == 65, len(code)
    return _fixed(code) + tail


def _findings(*lines: str) -> list[Any]:
    return line_length_findings("T.cbl", "\n".join(lines) + "\n")


def _kinds(findings: list[Any]) -> list[tuple[int, str]]:
    return [(f.origin_line, f.kind) for f in findings]


HEADER = (_fixed("IDENTIFICATION DIVISION."), _fixed("PROGRAM-ID. T."))
TRAILER = (_fixed("PROCEDURE DIVISION."), _fixed("    STOP RUN."))


class TestCommentLines:
    def test_star_comment_past_column_80(self) -> None:
        assert _findings(*HEADER, _fixed("x" * 90, "*"), *TRAILER) == []

    def test_slash_comment_past_column_80(self) -> None:
        assert _findings(*HEADER, _fixed("x" * 90, "/"), *TRAILER) == []

    def test_word_across_72_in_a_comment_line(self) -> None:
        line = _fixed("x" * 65, "*") + "YYYY"
        assert _findings(*HEADER, line, *TRAILER) == []


class TestInlineComments:
    def test_inline_comment_past_column_80(self) -> None:
        line = _fixed("    DISPLAY 'A'." + " " * 10 + "*> " + "x" * 70)
        assert _findings(*HEADER, *TRAILER[:1], line) == []

    def test_word_across_72_inside_an_inline_comment(self) -> None:
        line = _at_72("    DISPLAY 'A'. *> " + "x" * 45, "YYYY")
        assert _findings(*HEADER, *TRAILER[:1], line) == []

    def test_star_greater_inside_a_literal_is_not_a_comment(self) -> None:
        line = _fixed("    DISPLAY 'A *> B'." + " " * 60 + "OVERFLOW")
        assert _kinds(_findings(*HEADER, *TRAILER[:1], line)) == [
            (4, "LINE_PAST_COLUMN_80")
        ]

    def test_code_cut_before_an_inline_comment_is_still_reported(self) -> None:
        line = _at_72("    MOVE ABCDEFGHIJ TO " + "X" * 42, "YZ *> note")
        assert _kinds(_findings(*HEADER, *TRAILER[:1], line)) == [
            (4, "TEXT_PAST_COLUMN_72")
        ]


class TestCommentEntries:
    def test_author_entry_cut_at_72(self) -> None:
        line = _at_72("AUTHOR. " + "A" * 57, "BBBB")
        assert _findings(*HEADER, line, *TRAILER) == []

    def test_author_entry_past_column_80(self) -> None:
        line = _fixed("AUTHOR. JOHN O'BRIEN, " + "X" * 70)
        assert _findings(*HEADER, line, *TRAILER) == []

    def test_remarks_continued_in_area_b(self) -> None:
        lines = (
            *HEADER,
            _fixed("REMARKS."),
            _at_72(
                "    THIS PROGRAM DOES A LONG THING" + " WORD" * 6 + "X", "MOREWORD"
            ),
            _fixed("x" * 70, "*"),
            _fixed("    " + "WORDS " * 15),
            *TRAILER,
        )
        assert _findings(*lines) == []

    def test_every_comment_paragraph(self) -> None:
        names = (
            "AUTHOR",
            "INSTALLATION",
            "DATE-WRITTEN",
            "DATE-COMPILED",
            "SECURITY",
            "REMARKS",
        )
        lines = [_at_72(f"{name}. ".ljust(20) + "Z" * 45, "CUTWORD") for name in names]
        assert _findings(*HEADER, *lines, *TRAILER) == []

    def test_code_after_the_entry_is_still_checked(self) -> None:
        lines = (
            *HEADER,
            _fixed("AUTHOR. " + "A" * 80),
            _fixed("ENVIRONMENT DIVISION."),
            _fixed("DATA DIVISION."),
            _fixed("WORKING-STORAGE SECTION."),
            _at_72("01  WS-A PIC X(40) VALUE 'ABCDEFGHI" + "J" * 30, "KLM'."),
            *TRAILER,
        )
        assert _kinds(_findings(*lines)) == [(7, "TEXT_PAST_COLUMN_72")]

    def test_author_outside_the_identification_division_is_code(self) -> None:
        lines = (
            *HEADER,
            _fixed("PROCEDURE DIVISION."),
            _fixed("AUTHOR. " + "A" * 80),
            _fixed("    STOP RUN."),
        )
        assert _kinds(_findings(*lines)) == [
            (4, "LINE_PAST_COLUMN_80"),
            (4, "TEXT_PAST_COLUMN_72"),
        ]
