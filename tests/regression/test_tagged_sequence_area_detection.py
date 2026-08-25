"""Regression tests: a change-tracking tag in columns 1-6 must not flip a
fixed-format program to free-form.

``_detect_fixed_format`` used to count a line as fixed-format evidence only
when its sequence area (columns 1-6) was blank or all digits. Shops that stamp
a change-tracking ticket id there instead (``SAPR24``, ``28486``, ``GART``,
``JSINT`` -- a real, widespread mainframe convention) fell below the 60%
threshold, so the whole program was classified free-form,
``normalize_fixed_format`` never ran, and the tag text reached the lexer as
code. The visible symptom was a stray identifier/number token before the first
division:

    line 1, column 1: No recognizable COBOL division found near 'SAPR24'

The fix adds a second rule that also counts a *tag-like* sequence area, gated
on an Area A division header to corroborate. These tests pin both halves: the
tagged program now parses, and genuine free-form source is still detected as
free-form (the gate is what prevents rule 2 from dragging it in).
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.parser import _detect_fixed_format

_TAGS = ("SAPR24", "28486 ", "GART  ", "JSINT ")

_BODY = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. HY09001.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01  WS-A  PIC X(10).",
    "01  WS-B  PIC X(10).",
    "PROCEDURE DIVISION.",
    "MAIN-PARA.",
    "    MOVE SPACES TO WS-A.",
    "    STOP RUN.",
]


def _tagged(body: list[str] | None = None) -> str:
    """Render *body* as fixed-format with a change tag in columns 1-6."""
    lines = body if body is not None else _BODY
    return "\n".join(
        f"{_TAGS[i % len(_TAGS)]:<6} {line}" for i, line in enumerate(lines)
    )


def _blank_seq(body: list[str] | None = None) -> str:
    lines = body if body is not None else _BODY
    return "\n".join(f"       {line}" for line in lines)


class TestDetection:
    def test_tagged_sequence_area_detected_as_fixed(self):
        assert _detect_fixed_format(_tagged()) is True

    def test_blank_sequence_area_still_detected_as_fixed(self):
        assert _detect_fixed_format(_blank_seq()) is True

    def test_numeric_sequence_area_still_detected_as_fixed(self):
        numbered = "\n".join(
            f"{i * 100:06d} {line}" for i, line in enumerate(_BODY, start=1)
        )
        assert _detect_fixed_format(numbered) is True

    def test_genuine_free_form_still_detected_as_free_form(self):
        assert _detect_fixed_format("\n".join(_BODY)) is False

    def test_free_form_six_letter_verbs_not_dragged_in_by_relaxed_rule(self):
        """The tag rule alone would match these; the Area A gate rejects them.

        Each line's first six characters are a COBOL verb followed by a blank
        column 7 -- structurally indistinguishable from a tagged sequence area
        without the corroborating division-header anchor.
        """
        source = "\n".join(
            [
                "ACCEPT WS-A",
                "SEARCH WS-T",
                "DELETE WS-F",
                "DIVIDE WS-A BY WS-B",
                "UNLOCK WS-F",
                "CANCEL WS-P",
                "RETURN WS-R",
                "COMMIT WS-C",
                "INVOKE WS-I",
                "STRING WS-S",
            ]
        )
        assert _detect_fixed_format(source) is False

    def test_tagged_without_area_a_header_stays_conservative(self):
        """No division header in the code area -> the relaxed rule abstains."""
        fragment = _tagged(["MOVE SPACES TO WS-A.", "ADD 1 TO WS-B.", "STOP RUN."])
        assert _detect_fixed_format(fragment) is False

    def test_banner_comments_before_the_header_do_not_block_the_anchor(self):
        """The anchor scan must skip comment lines, not stop at them.

        Real programs open with a banner block; a comment line's columns 8+
        can say anything, so it is neither an anchor nor a reason to give up.
        """
        banner = [
            "SAPR24*****************************",
            "28486 * HY09001 - BANNER COMMENT   *",
            "GART  *****************************",
        ]
        source = "\n".join(banner) + "\n" + _tagged()
        assert _detect_fixed_format(source) is True

    def test_short_lines_do_not_break_the_anchor_scan(self):
        """A line too short to hold a code area is skipped, not indexed into."""
        source = "\n".join(["SAP", "28486", ""]) + "\n" + _tagged()
        assert _detect_fixed_format(source) is True


class TestParsing:
    def test_tagged_program_parses_without_errors(self):
        result = parse_cobol(_tagged(), filename="HY09001.cbl")
        assert result.errors == []
        assert result.success
        assert result.ast.program_name == "HY09001"

    @pytest.mark.parametrize("tag", _TAGS)
    def test_no_tag_text_reaches_the_ast(self, tag):
        result = parse_cobol(_tagged(), filename="HY09001.cbl")
        assert tag.strip() not in result.ast.to_json()

    def test_wrapped_multi_target_move_survives_tagged_layout(self):
        """The real-world shape: one MOVE, several receiving fields, wrapped."""
        body = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. HY09001.",
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01  DAT-SAI  PIC X(02).",
            "01  DAT-MMI  PIC X(02).",
            "01  DAT-JJI  PIC X(02).",
            "PROCEDURE DIVISION.",
            "MAIN-PARA.",
            "    MOVE '?' TO DAT-SAI",
            "                DAT-MMI",
            "                DAT-JJI.",
            "    STOP RUN.",
        ]
        result = parse_cobol(_tagged(body), filename="HY09001.cbl")
        assert result.errors == []
        moves = result.ast.find_all_by_type("MoveStatement")
        assert len(moves) == 1
        assert moves[0].targets == ["DAT-SAI", "DAT-MMI", "DAT-JJI"]

    def test_forced_fixed_overrides_a_declining_detector(self):
        """``preprocess_fixed=True`` is the escape hatch for layouts the
        heuristic will not infer -- here a sequence area with an internal
        space, which the tag pattern deliberately rejects."""
        source = "\n".join(
            f"{'AB 2' + str(i % 10):<6} {line}" for i, line in enumerate(_BODY)
        )
        assert _detect_fixed_format(source) is False
        assert parse_cobol(source, filename="x.cbl").errors != []

        forced = parse_cobol(source, filename="x.cbl", preprocess_fixed=True)
        assert forced.errors == []
        assert forced.ast.program_name == "HY09001"

    def test_forced_free_form_disables_normalization(self):
        """``preprocess_fixed=False`` + ``free_form=True`` must not strip
        columns, even on source the detector would now call fixed."""
        result = parse_cobol(
            _tagged(), filename="x.cbl", free_form=True, preprocess_fixed=False
        )
        assert result.errors != []
