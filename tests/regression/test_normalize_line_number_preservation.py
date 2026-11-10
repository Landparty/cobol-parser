"""Regression coverage for line-number preservation through preprocessing.

Audit finding (2026-07-08): ``normalize_fixed_format`` and
``preprocess_conditional_compilation`` both dropped certain physical lines
(blank lines, comment lines, ``>>DEFINE``/``>>IF``/``>>ELSE``/``>>END-IF``
directive lines, and lines inside a skipped ``>>IF`` block) from their output
entirely instead of emitting an empty placeholder. Every real COBOL program
contains blank/comment lines, so this silently shifted every subsequent
lexer/parser error and warning location by however many such lines preceded
it — a "clean" parse could report an error several lines away from where the
actual problem was.

Issue #123 (2026-08-10): the 2026-07-08 fix above was incomplete. It made
the "short physical line" and "comment physical line" branches always emit
an empty placeholder, but ``flush_parts()`` -- which appends the *previous*
logical line's merged text -- still only appended when that text was
non-empty (``if combined: result.append(combined)``). A physical line that
takes neither the short-line nor the comment-line early-continue (i.e. it is
full-width with a blank, non-comment indicator column) but whose extracted
program-text (columns 8-72) is itself entirely blank falls through to the
generic "start a new logical line" branch, buffers an empty string, and is
then silently dropped the next time ``flush_parts()`` runs -- one line lost
per such physical line, with no placeholder at all.

This exact line shape never occurs in a plain fixed-format parse (a blank
physical line is always short; a `*`-comment line always has a non-blank
indicator), so the original fix's tests never exercised it. It does occur
routinely once copybook expansion is involved:
``copy_statement_parser.remove_comment_lines`` blanks a `*`-comment line to
an all-spaces string of the *same length* (preserving the physical line
count for its own purposes) before ``CobolParser._parse_core`` re-runs
``normalize_fixed_format`` on the already-expanded source -- at which point
the former comment line has no indicator left to recognize, so it takes the
buggy generic path instead of the (already-fixed) comment-line path. Traced
from a `program-flow` `location.line` that drifted backward from a
paragraph's real source line by exactly one per full-line comment anywhere
earlier in the file, but only in files with at least one `COPY` statement.
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.preprocess import (
    normalize_fixed_format,
    preprocess_conditional_compilation,
)


class TestNormalizeFixedFormatPreservesLineNumbers:
    LINES = [
        "000100 IDENTIFICATION DIVISION.\n",
        "000200 PROGRAM-ID. TEST.\n",
        "000300\n",  # blank line
        "000400*A COMMENT LINE\n",  # comment line
        "000500 PROCEDURE DIVISION.\n",
        "000600 MAIN-PARA.\n",
        "000700     DISPLAY WS-A.\n",
        "000800     DISPLAY WS-B.\n",
        "000900     MOVE BOGUS ~~~ TO WS-A.\n",
    ]

    def test_error_reports_true_physical_line(self):
        source = "".join(self.LINES)
        result = parse_cobol(
            source, filename="probe.cbl", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )
        bad_char_warnings = [w for w in result.warnings if "'~'" in w]
        assert bad_char_warnings
        # The bad token is on physical line 9; without the fix it reported
        # line 7 (shifted by the dropped blank + comment line).
        assert all("line 9)" in w for w in bad_char_warnings)

    def test_output_line_count_matches_input(self):
        out = normalize_fixed_format(self.LINES)
        assert out.count("\n") == len(self.LINES)

    def test_blank_and_comment_lines_become_empty_placeholders(self):
        out = normalize_fixed_format(self.LINES)
        out_lines = out.split("\n")
        assert out_lines[2] == ""  # blank source line
        assert out_lines[3] == ""  # comment source line


class TestConditionalCompilationPreservesLineNumbers:
    def test_directive_and_skipped_lines_become_blank_placeholders(self):
        source = (
            ">>DEFINE DEBUG\n"
            ">>IF DEBUG IS DEFINED\n"
            "       DISPLAY 'D'.\n"
            ">>ELSE\n"
            "       DISPLAY 'NOT-D'.\n"
            ">>END-IF\n"
            "       DISPLAY 'AFTER'.\n"
        )
        out = preprocess_conditional_compilation(source)
        out_lines = out.split("\n")
        assert len(out_lines) == len(source.splitlines())
        assert "DISPLAY 'D'." in out_lines[2]
        assert out_lines[4] == ""  # DISPLAY 'NOT-D' was in the skipped ELSE arm
        assert "DISPLAY 'AFTER'." in out_lines[6]

    def test_error_location_after_conditional_block_is_accurate(self):
        source = (
            ">>DEFINE DEBUG\n"
            ">>IF DEBUG IS DEFINED\n"
            "       DISPLAY 'D'.\n"
            ">>END-IF\n"
            "       MOVE BOGUS ~~~ TO WS-A.\n"
        )
        preprocessed = preprocess_conditional_compilation(source)
        # The preprocessed text is already free-form (leading directive lines
        # blanked out), so parse it as such rather than re-slicing it into
        # fixed-format columns.
        result = parse_cobol(
            preprocessed,
            filename="probe.cbl",
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            free_form=True,
        )
        bad_char_warnings = [w for w in result.warnings if "'~'" in w]
        assert bad_char_warnings
        assert all("line 5)" in w for w in bad_char_warnings)


class TestLexerLineStartQuoteWhitespaceParity:
    """What counts as "whitespace only before this quote" on a continuation
    line: only " "/"\\t". A broader definition (str.strip(): "\\v", "\\f",
    NBSP) once classified the same line differently in a since-removed
    compiled lexer."""

    # A form-feed (page-eject control byte, plausible EBCDIC/ASCII transcoding
    # leftover) precedes an open quote on a fixed-format continuation line.
    SOURCE = (
        "       01 WS-A PIC X(20) VALUE 'ABC\n"
        "      -\x0c'DEF'.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )

    def test_form_feed_before_continuation_quote(self):
        lexer = CobolLexer(self.SOURCE, free_form=False)
        tokens = lexer.tokenize()
        assert not lexer.errors
        literals = [t.value for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert literals == ["ABCDEF"]


class TestNormalizeFixedFormatPreservesFullWidthBlankLines:
    """Issue #123 root cause, isolated from copybook expansion entirely.

    A physical line long enough to have a real (blank, non-comment)
    indicator column, whose program-text (columns 8-72) is itself entirely
    blank, must still occupy exactly one slot in the output -- the same
    guarantee already covered above for short/blank and `*`-comment lines.
    This shape is what a former `*`-comment line becomes once
    ``copy_statement_parser.remove_comment_lines`` blanks it (indicator
    included) ahead of a second ``normalize_fixed_format`` pass over
    copybook-expanded source.
    """

    # Two consecutive full-width blank lines back to back is the case that
    # tips over `flush_parts()`'s `if combined:` guard: the first blank
    # line's own (empty) buffer is only appended on the *next* flush, and
    # an empty buffer looks indistinguishable from "nothing to flush".
    LINES = [
        "000100 IDENTIFICATION DIVISION.\n",
        "000200 PROGRAM-ID. TEST.\n",
        "000300 PROCEDURE DIVISION.\n",
        "000400 MAIN-PARA.\n",
        "000500     DISPLAY WS-A.\n",
        " " * 80 + "\n",  # full-width blank, NOT a short line
        " " * 80 + "\n",  # full-width blank, NOT a short line
        "000800     DISPLAY WS-B.\n",
    ]

    def test_output_line_count_matches_input(self):
        out = normalize_fixed_format(self.LINES)
        assert out.count("\n") == len(self.LINES)

    def test_full_width_blank_lines_become_empty_placeholders(self):
        out_lines = normalize_fixed_format(self.LINES).split("\n")
        assert out_lines[5] == ""
        assert out_lines[6] == ""
        assert "DISPLAY WS-B" in out_lines[7]


class TestCopybookCommentDriftIssue123:
    """End-to-end reproduction of GitHub issue #123: `program-flow`
    `location.line` drifted backward from a paragraph's real source line by
    one per full-line comment anywhere earlier in the file, but only when a
    `COPY` statement preceded it.

    https://github.com/Landparty/cobol-parser/issues/123
    """

    COPYBOOK = (
        "       01  WS-MINI-FIELD           PIC X(5).\n"
        "       01  WS-MINI-COUNT           PIC 9(3).\n"
    )

    @staticmethod
    def _paragraph_lines(source: str, copybook_dir) -> dict:
        from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
        from cobolparser.parser import parse_cobol_with_expansion

        result = parse_cobol_with_expansion(
            source, filename="probe.cbl", copybook_paths=[str(copybook_dir)]
        )
        assert result.ast is not None, result.errors
        report = ProgramFlowAnalyzer().analyze(result.ast)
        return {node.name: node.location.line for node in report.nodes}

    def test_comments_after_copy_do_not_drift_paragraph_lines(self, tmp_path):
        (tmp_path / "MINI.cpy").write_text(self.COPYBOOK)
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TESTPROG3.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY MINI.\n"
            "       01  WS-OTHER                PIC X(1).\n"
            "\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           PERFORM 1000-FIRST\n"
            "           STOP RUN.\n"
            "      * comment one\n"
            "      * comment two\n"
            "      * comment three\n"
            "       1000-FIRST.\n"
            "           DISPLAY 'ONE'.\n"
        )
        lines = self._paragraph_lines(source, tmp_path)

        # In the real source, 1000-FIRST is 6 physical lines after
        # 0000-MAIN (PERFORM, STOP RUN, 3 comments, then the paragraph
        # header). Copybook expansion shifts both paragraphs by the same
        # constant offset, so this delta must be preserved regardless of
        # the comments between them. Without the fix it collapsed to 3
        # (one line silently lost per comment).
        assert lines["1000-FIRST"] - lines["0000-MAIN"] == 6

    def test_comments_vs_blank_lines_after_copy_report_identically(self, tmp_path):
        """Blank lines never drifted (per the issue report); comment lines
        must now behave the same way -- same paragraph offsets either way.
        """
        (tmp_path / "MINI.cpy").write_text(self.COPYBOOK)
        header = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TESTPROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY MINI.\n"
            "       01  WS-OTHER                PIC X(1).\n"
            "\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           PERFORM 1000-FIRST\n"
            "           STOP RUN.\n"
        )
        footer = "       1000-FIRST.\n           DISPLAY 'ONE'.\n"

        comments_source = header + "      * c1\n      * c2\n      * c3\n" + footer
        blanks_source = header + "\n\n\n" + footer

        comments_lines = self._paragraph_lines(comments_source, tmp_path)
        blanks_lines = self._paragraph_lines(blanks_source, tmp_path)

        assert comments_lines == blanks_lines

    def test_comments_inside_copybook_do_not_drift_paragraph_lines(self, tmp_path):
        """The comment-blanking that triggers the bug is not specific to
        the main source file -- a copybook's own comment lines go through
        the same `remove_comment_lines` + re-normalize path.

        Both copybook comments sit *above* both paragraphs here, so a
        delta-only assertion (`1000-FIRST - 0000-MAIN`) would pass even
        without the fix -- dropping both copybook comment lines shifts
        both paragraphs by the same amount, leaving their distance apart
        unchanged. Pin the absolute reported lines instead.
        """
        (tmp_path / "MINI.cpy").write_text(
            "      * field one comment\n"
            "       01  WS-MINI-FIELD           PIC X(5).\n"
            "      * field two comment\n"
            "       01  WS-MINI-COUNT           PIC 9(3).\n"
        )
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TESTPROG.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY MINI.\n"
            "       01  WS-OTHER                PIC X(1).\n"
            "\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           PERFORM 1000-FIRST\n"
            "           STOP RUN.\n"
            "       1000-FIRST.\n"
            "           DISPLAY 'ONE'.\n"
        )
        lines = self._paragraph_lines(source, tmp_path)
        # Without the fix, both copybook comments are dropped (no
        # placeholder), shifting both paragraphs to line 11 / 14.
        assert lines["0000-MAIN"] == 13
        assert lines["1000-FIRST"] == 16
