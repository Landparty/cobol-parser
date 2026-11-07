"""Regression coverage for 'V'/'v' in the fixed-format indicator column
(column 7) being treated as a comment line by ``normalize_fixed_format``.

Found via a real shop's change-control convention: a short version tag
(e.g. ``V97``, ``TFEC``) is stamped into Area A with 'V' in column 7 of its
own line, matching the shape of existing indicator markers like '*'/'/'
(comments) and 'D'/'d' (debug lines) but recognized by neither
``normalize_fixed_format`` nor the free-form lexer. The un-normalized
Area-A text (e.g. ``74C``, ``74A``) then reached the lexer as live source
and surfaced as "Unparsed tokens" parse errors.

Standard fixed-format COBOL never puts live code in column 7 (it is
reserved for '*'/'/'/'-'/'D'/'d'), so treating 'V'/'v' as a comment
indicator too is unambiguous with real source -- mirrors the existing
``debug_lines_as_comments`` precedent (M4) for 'D'/'d', including a
``version_tag_lines_as_comments=False`` opt-out for callers that need
V-lines compiled as code.
"""

from cobolparser import TokenType, parse_cobol, tokenize_cobol
from cobolparser.preprocess import (
    normalize_fixed_format,
)
from cobolparser.preprocess.copy_statement_parser import is_comment_line

IMPLS = [("normalize", normalize_fixed_format)]


def _line(indicator: str, text: str) -> str:
    # cols 1-6 seq area, col 7 indicator, cols 8+ text
    return " " * 6 + indicator + text


class TestVersionTagLineHandling:
    def test_v_line_is_dropped_by_default(self):
        lines = [
            _line(" ", "       DISPLAY 'BEFORE'."),
            _line("V", "    74C"),
            _line(" ", "       DISPLAY 'AFTER'."),
        ]
        for name, impl in IMPLS:
            out = impl(lines)
            assert "74C" not in out, name
            assert "BEFORE" in out, name
            assert "AFTER" in out, name

    def test_lowercase_v_line_is_dropped_by_default(self):
        lines = [
            _line(" ", "       DISPLAY 'BEFORE'."),
            _line("v", "    74A"),
        ]
        for name, impl in IMPLS:
            out = impl(lines)
            assert "74A" not in out, name

    def test_v_line_kept_as_code_when_opted_in(self):
        lines = [
            _line(" ", "       DISPLAY 'BEFORE'."),
            _line("V", "    74C"),
        ]
        for name, impl in IMPLS:
            out = impl(lines, version_tag_lines_as_comments=False)
            assert "74C" in out, name

    def test_line_numbering_preserved_across_v_lines(self):
        # A dropped V-line must still emit a blank placeholder so later
        # lines keep their true line number (same contract as '*'/'D').
        lines = [
            _line(" ", "       DISPLAY 'ONE'."),
            _line("V", "    74C"),
            _line("V", "    74A"),
            _line(" ", "       DISPLAY 'TWO'."),
        ]
        for name, impl in IMPLS:
            out = impl(lines)
            assert out.count("\n") == len(lines), name

    def test_is_comment_line_recognizes_v_and_lowercase_v(self):
        assert is_comment_line(_line("V", "    74C"))
        assert is_comment_line(_line("v", "    74A"))


class TestVersionTagLineEndToEndParse:
    """The screenshot's exact reproducing shape: V-tag lines interleaved
    with real PROCEDURE DIVISION statements used to surface as "Unparsed
    tokens" -- now parse cleanly."""

    def _padded(self, indicator: str, text: str) -> str:
        return _line(indicator, text).ljust(72)

    def test_program_with_version_tag_lines_parses_error_free(self):
        source = (
            "\n".join(
                [
                    self._padded(" ", "       IDENTIFICATION DIVISION."),
                    self._padded(" ", "       PROGRAM-ID. VTAGTEST."),
                    self._padded(" ", "       PROCEDURE DIVISION."),
                    self._padded(" ", "       MAIN-PARA."),
                    self._padded("V", "    74C"),
                    self._padded(" ", "           DISPLAY 'HELLO'."),
                    self._padded("V", "    74A"),
                    self._padded(" ", "           STOP RUN."),
                ]
            )
            + "\n"
        )
        result = parse_cobol(source, filename="vtagtest.cbl")
        assert result.success, result.errors
        assert result.errors == []


class TestVersionTagCommentTokenPreservation:
    """``tokenize_cobol(..., keep_comments=True)`` reconstructs COMMENT
    tokens for lines normalize_fixed_format blanked out, by re-scanning the
    physical lines and pairing each blank normalized line with the physical
    comment/blank line that produced it, in order (``_fixed_format_comment_tokens``
    in ``lexer.py``). That rescan originally only recognized '*'/'D'/'d' (plus
    '/' for page breaks) -- a V-line produced a blank placeholder in the
    normalized text (via normalize_fixed_format) but no matching entry in the
    rescan's placeholder list, desynchronizing every later pairing by one: the
    next real comment after a V-line was misattributed to the V-line's own
    (earlier) line number, and its own placeholder was silently dropped."""

    def _padded(self, indicator: str, text: str) -> str:
        return _line(indicator, text).ljust(72)

    def test_v_line_comment_and_following_real_comment_keep_own_line_numbers(self):
        source = (
            "\n".join(
                [
                    self._padded(" ", "       IDENTIFICATION DIVISION."),
                    self._padded(" ", "       PROGRAM-ID. VTAGTEST."),
                    self._padded(" ", "       PROCEDURE DIVISION."),
                    self._padded("V", "    74C"),
                    self._padded("*", "  A REAL COMMENT"),
                    self._padded(" ", "           DISPLAY 'HELLO'."),
                    self._padded(" ", "           STOP RUN."),
                ]
            )
            + "\n"
        )
        tokens = tokenize_cobol(source, keep_comments=True)
        comments = [t for t in tokens if t.type == TokenType.COMMENT]
        assert [(t.location.line, t.value.strip()) for t in comments] == [
            (4, "V    74C"),
            (5, "*  A REAL COMMENT"),
        ]
