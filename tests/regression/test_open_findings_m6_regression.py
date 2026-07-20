"""Regression tests for open-findings M6: tokenize/parse lexing divergence.

M6: ``parse_cobol()`` normalizes fixed-format source via
``normalize_fixed_format`` and lexes with ``free_form=True``, while
``tokenize_cobol()`` and the CLI ``tokenize`` subcommand used the lexer's own
internal fixed-format handler (``free_form=False``). The two paths disagreed
on token count/content for the same source (comment handling, continuation
merging, Area A/B slicing).

Fix: ``tokenize_cobol()`` and the CLI now route detected fixed-format source
through ``normalize_fixed_format`` + ``free_form=True`` lexing — the same
pipeline ``parse_cobol()`` uses — so all non-COMMENT tokens agree. Comment
lines (dropped by normalization) are re-emitted as COMMENT tokens so the
tokenize UX does not silently lose them.
"""

from cobolparser.lexer import CobolLexer, TokenType, tokenize_cobol
from cobolparser.preprocess import normalize_fixed_format

# Fixed-format sample exercising comment lines ('*' and '/'), a debug 'D'
# line, blank lines, and a literal continuation line ('-' in column 7).
FIXED_SOURCE = (
    "      * TOP COMMENT LINE\n"
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. M6DEMO.\n"
    "      / EJECT\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    '       01 WS-MSG PIC X(30) VALUE "HELLO CONTINUED\n'
    '      -    "WORLD".\n'
    "      * MID COMMENT\n"
    "\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           DISPLAY WS-MSG\n"
    "           STOP RUN.\n"
    "      * TRAILING COMMENT\n"
)


def _token_tuples(tokens):
    return [(t.type, t.value, t.location.line, t.location.column) for t in tokens]


def _parse_pipeline_tokens(source):
    """Tokens exactly as parse_cobol's pipeline lexes fixed-format source."""
    normalized = normalize_fixed_format(source.splitlines())
    lexer = CobolLexer(normalized, "m6.cbl", free_form=True)
    return lexer.tokenize()


class TestM6TokenizeParity:
    def test_non_comment_tokens_match_parse_pipeline(self):
        """tokenize_cobol() minus COMMENT tokens == normalize + free-form lex."""
        tokenize_tokens = tokenize_cobol(FIXED_SOURCE, "m6.cbl")
        parse_tokens = _parse_pipeline_tokens(FIXED_SOURCE)

        non_comment = [t for t in tokenize_tokens if t.type != TokenType.COMMENT]
        assert _token_tuples(non_comment) == _token_tuples(parse_tokens)

    def test_keep_comments_false_matches_parse_pipeline_exactly(self):
        """With keep_comments=False the streams are identical, byte for byte."""
        tokenize_tokens = tokenize_cobol(FIXED_SOURCE, "m6.cbl", keep_comments=False)
        parse_tokens = _parse_pipeline_tokens(FIXED_SOURCE)

        assert not any(t.type == TokenType.COMMENT for t in tokenize_tokens)
        assert _token_tuples(tokenize_tokens) == _token_tuples(parse_tokens)

    def test_comment_tokens_carry_correct_line_numbers(self):
        """COMMENT tokens keep their text and line up with the normalized
        coordinate system used by every other token in the stream."""
        tokens = tokenize_cobol(FIXED_SOURCE, "m6.cbl")
        comments = [t for t in tokens if t.type == TokenType.COMMENT]

        # Physical lines 1 ('*'), 4 ('/'), 9 ('*'), 15 ('*'). The continuation
        # (physical line 8) merges into line 7's logical line, so every line
        # after it shifts up by one in normalized coordinates: 9 -> 8, 15 -> 14.
        assert [(t.value, t.location.line) for t in comments] == [
            ("* TOP COMMENT LINE", 1),
            ("/ PAGE BREAK", 4),
            ("* MID COMMENT", 8),
            ("* TRAILING COMMENT", 14),
        ]

        # Comment lines are blank in the normalized text, so no other token
        # may share a COMMENT token's line.
        comment_lines = {t.location.line for t in comments}
        for token in tokens:
            if token.type not in (TokenType.COMMENT,):
                assert token.location.line not in comment_lines

    def test_comment_tokens_interleave_in_source_order(self):
        """COMMENT tokens appear at their original positions in the stream."""
        tokens = tokenize_cobol(FIXED_SOURCE, "m6.cbl")
        lines = [t.location.line for t in tokens if t.type != TokenType.EOF]
        assert lines == sorted(lines)

        # Trailing comment lands before EOF, at the very end of the stream.
        assert tokens[-1].type == TokenType.EOF
        assert tokens[-2].type == TokenType.COMMENT
        assert tokens[-2].value == "* TRAILING COMMENT"

    def test_continuation_literal_merged_like_parse(self):
        """The continued VALUE literal is one STRING token on both paths."""
        tokens = tokenize_cobol(FIXED_SOURCE, "m6.cbl")
        strings = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(strings) == 1
        assert strings[0].value == "HELLO CONTINUEDWORLD"

    def test_free_form_input_unchanged(self):
        """free_form=True bypasses detection/normalization entirely."""
        free_source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. FREEM6.\n"
            "PROCEDURE DIVISION.\n"
            "    DISPLAY 'HI'\n"
            "    STOP RUN.\n"
        )
        via_function = tokenize_cobol(free_source, "free.cbl", free_form=True)
        direct = CobolLexer(free_source, "free.cbl", free_form=True).tokenize()
        assert _token_tuples(via_function) == _token_tuples(direct)

    def test_non_fixed_source_keeps_legacy_behavior(self):
        """Source not detected as fixed-format still lexes as before."""
        source = "       IDENTIFICATION DIVISION."  # <3 lines: never "fixed"
        via_function = tokenize_cobol(source, "short.cbl")
        direct = CobolLexer(source, "short.cbl", free_form=False).tokenize()
        assert _token_tuples(via_function) == _token_tuples(direct)
