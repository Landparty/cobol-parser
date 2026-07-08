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

Also pins that the Cython ``_preprocess_fast``/``_lexer_fast`` accelerated
paths stay behaviorally identical to the pure-Python fallback for these
cases (a divergence here means the compiled build silently behaves
differently from the non-accelerated build).
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, _CobolLexerPure
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.preprocess import (
    _normalize_fixed_format_pure,
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
        "000900     MOVE BOGUS !!! TO WS-A.\n",
    ]

    def test_error_reports_true_physical_line(self):
        source = "".join(self.LINES)
        result = parse_cobol(
            source, filename="probe.cbl", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )
        assert result.errors
        # The bad token is on physical line 9; without the fix it reported
        # line 7 (shifted by the dropped blank + comment line).
        assert all(e.line_number == 9 for e in result.errors)

    def test_output_line_count_matches_input(self):
        out = normalize_fixed_format(self.LINES)
        assert out.count("\n") == len(self.LINES)

    def test_blank_and_comment_lines_become_empty_placeholders(self):
        out = normalize_fixed_format(self.LINES)
        out_lines = out.split("\n")
        assert out_lines[2] == ""  # blank source line
        assert out_lines[3] == ""  # comment source line

    def test_cython_and_pure_python_agree(self):
        """The compiled fast-path must not diverge from the fallback."""
        assert normalize_fixed_format(self.LINES) == _normalize_fixed_format_pure(
            self.LINES
        )


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
            "       MOVE BOGUS !!! TO WS-A.\n"
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
        bad_char_errors = [e for e in result.errors if "Invalid character" in str(e)]
        assert bad_char_errors
        assert all(e.line_number == 5 for e in bad_char_errors)


class TestLexerLineStartQuoteWhitespaceParity:
    """Cython/pure-Python must agree on what counts as "whitespace only
    before this quote" — the pure-Python check only treats " "/"\\t" as
    whitespace, while an earlier Cython implementation used str.strip(),
    a broader definition (e.g. "\\v", "\\f", NBSP) that could classify the
    same line differently, silently diverging from the fallback path."""

    # A form-feed (page-eject control byte, plausible EBCDIC/ASCII transcoding
    # leftover) precedes an open quote on a fixed-format continuation line.
    SOURCE = (
        "       01 WS-A PIC X(20) VALUE 'ABC\n"
        "      -\x0c'DEF'.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )

    def test_fast_and_pure_lexers_agree(self):
        fast_tokens = CobolLexer(self.SOURCE, free_form=False).tokenize()
        pure_tokens = _CobolLexerPure(self.SOURCE, free_form=False).tokenize()

        assert len(fast_tokens) == len(pure_tokens)
        for i, (ft, pt) in enumerate(zip(fast_tokens, pure_tokens, strict=True)):
            assert (
                ft.type == pt.type
            ), f"Token[{i}] type mismatch: {ft.type} vs {pt.type}"
            assert (
                ft.value == pt.value
            ), f"Token[{i}] value mismatch: {ft.value!r} vs {pt.value!r}"
