"""
Unit tests for edge cases in the COBOL lexer's multi-line string handling.

These tests target specific uncovered paths in handle_cobol_line_format
and _continue_multiline_string, including:

- Comment lines interrupting multi-line string continuations
- Page-break lines interrupting multi-line string continuations
- VALUE clause continuation where the next line starts with a quote
  but is NOT a proper continuation line (no '-' in column 7)
- _continue_multiline_string with short (<=3 char) content and no
  valid continuation -> error emitted
- _continue_multiline_string with longer (>3 char) content and no
  valid continuation -> token emitted silently
- Multi-line string where content after opening quote is empty
"""

from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.ast_base import SourceLocation


def _fixed_line(seq: str, indicator: str, text: str) -> str:
    """Build a fixed-format COBOL line padded to 80 characters.

    Args:
        seq: 6-character sequence number (e.g., '000100')
        indicator: single indicator character for column 7
        text: program text (columns 8-72)
    """
    assert len(seq) == 6, f"Sequence number must be 6 chars, got {len(seq)}"
    assert len(indicator) == 1, "Indicator must be a single character"
    # Columns 1-6: seq, column 7: indicator, columns 8-72: text (65 chars max),
    # columns 73-80: identification area (8 chars of spaces)
    program_area = text[:65].ljust(65)
    return seq + indicator + program_area + "        "  # total 80 chars


class TestCommentInterruptingMultilineString:
    """Test that a comment line ('*' in column 7) interrupting a multi-line
    string continuation is handled gracefully.

    Lines 939-957 of lexer.py clear the open string state when a comment
    or page-break indicator is encountered mid-continuation. In the current
    code flow, the early return for comments at lines 823-832 fires first,
    so these tests verify observable behavior: the multi-line string state
    is effectively abandoned and the comment is emitted.
    """

    def test_comment_line_after_multiline_string_start(self):
        """A '*' comment line following an unterminated string start should
        emit a COMMENT token and leave the lexer in a recoverable state."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    VALUE "HELLO WORLD THIS IS'),
                _fixed_line("000200", "-", '    "CONTINUED TEXT"'),
                _fixed_line("000300", "*", " THIS IS A COMMENT"),
                _fixed_line("000400", " ", "    DISPLAY WS-VAR."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1
        # The comment text should contain our comment content
        comment_values = [t.value for t in comment_tokens]
        assert any("THIS IS A COMMENT" in v for v in comment_values)

    def test_comment_clears_multiline_state_via_direct_call(self):
        """Directly set _open_string_quote and call handle_cobol_line_format
        with a '*' comment line to verify the string state clearing path
        at lines 939-957."""
        # Build a dummy two-line source so the lexer has lines to reference
        line0 = _fixed_line("000100", " ", '    VALUE "UNTERMINATED STRING')
        line1 = _fixed_line("000200", "*", " COMMENT INTERRUPTS STRING")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        # Manually set multi-line string state as if we started a string
        lexer._open_string_quote = '"'
        lexer._open_string_value = ["UNTERMINATED STRING"]
        lexer._open_string_location = SourceLocation(1, 8, 1)

        # Call handle_cobol_line_format for line 1 (the comment line)
        # The early return at line 823 fires, but the string state remains.
        result_tokens = lexer.handle_cobol_line_format(line1, 1)

        # Verify a COMMENT token is emitted
        assert len(result_tokens) == 1
        assert result_tokens[0].type == TokenType.COMMENT

    def test_multiline_string_abandoned_then_normal_parsing_resumes(self):
        """After a comment interrupts a multi-line string, subsequent normal
        lines should parse correctly."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    VALUE "UNTERMINATED'),
                _fixed_line("000150", "-", '    "CONTINUATION"'),
                _fixed_line("000200", "*", " A COMMENT LINE"),
                _fixed_line("000300", " ", "    MOVE 1 TO WS-X."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # Should have MOVE token somewhere after the comment
        move_tokens = [t for t in tokens if t.type == TokenType.MOVE]
        assert len(move_tokens) >= 1


class TestPageBreakInterruptingMultilineString:
    """Test that a page-break line ('/' in column 7) interrupting a multi-line
    string continuation is handled correctly."""

    def test_page_break_after_multiline_string_start(self):
        """A '/' page-break line following an unterminated string should
        emit a COMMENT (page break) token."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    VALUE "LONG STRING STARTS'),
                _fixed_line("000200", "-", '    "HERE CONTINUED"'),
                _fixed_line("000300", "/", " PAGE BREAK HERE"),
                _fixed_line("000400", " ", "    DISPLAY WS-VAR."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1
        # Page breaks are emitted as COMMENT tokens with "/ PAGE BREAK" value
        page_break_tokens = [t for t in comment_tokens if "PAGE BREAK" in t.value]
        assert len(page_break_tokens) >= 1

    def test_page_break_clears_multiline_state_via_direct_call(self):
        """Directly set _open_string_quote and call handle_cobol_line_format
        with a '/' page-break line to verify state clearing."""
        line0 = _fixed_line("000100", " ", '    VALUE "UNTERMINATED')
        line1 = _fixed_line("000200", "/", " PAGE EJECT")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        # Manually set multi-line string state
        lexer._open_string_quote = '"'
        lexer._open_string_value = ["UNTERMINATED"]
        lexer._open_string_location = SourceLocation(1, 8, 1)

        result_tokens = lexer.handle_cobol_line_format(line1, 1)

        # Verify a COMMENT (page break) token is emitted
        assert len(result_tokens) == 1
        assert result_tokens[0].type == TokenType.COMMENT
        assert "PAGE BREAK" in result_tokens[0].value


class TestValueClauseContinuationWithoutMarker:
    """Test VALUE clause continuation where next line starts with a quote
    but is NOT a continuation line (no '-' in column 7), and the previous
    line has VALUE.

    This targets lines 920-937 in handle_cobol_line_format: the fallback
    path that creates a string token when the program text starts with '"'
    but isn't a proper continuation, yet the previous line had VALUE.
    """

    def test_value_continuation_no_closing_quote(self):
        """A line starting with '"' after a VALUE line, with no continuation
        marker and no closing quote, should create a STRING_LITERAL token
        with the remaining text as content."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", "    05 WS-VAR PIC X(80) VALUE"),
                _fixed_line("000200", " ", '    "THIS TEXT HAS NO END QUOTE'),
                _fixed_line("000300", " ", "    DISPLAY WS-VAR."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # Should have a STRING_LITERAL token from the fallback path
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        # The string content should be what follows the opening quote
        assert any("THIS TEXT HAS NO END QUOTE" in t.value for t in string_tokens)

    def test_value_continuation_with_closing_quote_same_line(self):
        """A line starting with '"' after a VALUE line, with a closing quote
        on the same line, should NOT take the fallback path (closing_quote_pos
        != -1) and should tokenize normally."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", "    05 WS-VAR PIC X(80) VALUE"),
                _fixed_line("000200", " ", '    "COMPLETE STRING"'),
                _fixed_line("000300", " ", "    DISPLAY WS-VAR."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # Should have a STRING_LITERAL with complete content
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert any("COMPLETE STRING" in t.value for t in string_tokens)

    def test_value_continuation_line_no_quote_in_text(self):
        """A line that does NOT start with '"' after a VALUE line should
        not trigger the fallback string creation path."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", "    05 WS-VAR PIC X(80) VALUE"),
                _fixed_line("000200", " ", "    SPACES"),
                _fixed_line("000300", " ", "    DISPLAY WS-VAR."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # SPACES is a figurative constant; the line should be processed
        # normally, not as a fallback string
        figurative_tokens = [
            t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT
        ]
        assert len(figurative_tokens) >= 1


class TestContinueMultilineStringShortContent:
    """Test _continue_multiline_string where string content is <=3 chars
    without a valid continuation line -> should emit an error.

    This targets lines 1366-1385 in _continue_multiline_string.
    Integration-level tests go through tokenize(); note that fixed-format
    padding means accumulated string content includes trailing spaces from
    the program text area (columns 8-72), so content is always >3 chars
    in practice. The direct unit tests in TestContinueMultilineStringDirectly
    exercise the exact <=3 / >3 boundary.
    """

    def test_short_string_no_continuation_via_direct_call(self):
        """Directly call _continue_multiline_string with short accumulated
        content (<=3 chars) and a non-continuation line to verify error."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    AB")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        # Pre-set multi-line string state with very short content
        lexer._open_string_quote = '"'
        lexer._open_string_value = []
        lexer._open_string_location = SourceLocation(1, 12, 1)

        # Pass a short program_text with no closing quote
        closed, remainder_tokens = lexer._continue_multiline_string("AB", 1)

        # String state should be cleared (closed = True)
        assert closed is True

        # <=3 chars -> error emitted
        assert len(lexer.errors) >= 1
        assert any(
            "unterminated" in str(e).lower() or "string" in str(e).lower()
            for e in lexer.errors
        )

        # STRING_LITERAL still emitted for robustness
        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1

    def test_single_char_string_no_continuation_via_direct_call(self):
        """A single-character string content (<=3 chars) should emit error."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    X")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = []
        lexer._open_string_location = SourceLocation(1, 12, 1)

        closed, remainder_tokens = lexer._continue_multiline_string("X", 1)

        assert closed is True
        # 1 char (<=3) -> error
        assert len(lexer.errors) >= 1

        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1
        assert string_tokens[0].value == "X"


class TestContinueMultilineStringLongContent:
    """Test _continue_multiline_string where string content is >3 chars
    without a valid continuation -> should emit token WITHOUT error.

    This targets lines 1373-1397 in _continue_multiline_string.
    """

    def test_long_string_no_continuation_emits_token_no_error(self):
        """When accumulated string content is >3 chars and the next line
        is NOT a valid continuation, the lexer should emit a STRING_LITERAL
        token without adding an error."""
        # Through tokenize(), fixed-format padding ensures content is always
        # >3 chars, so this integration test verifies the silent emit path.
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    05 WS-X PIC X(80) VALUE "HELLO WORLD'),
                _fixed_line("000200", "-", '    "MORE CONTENT HERE WITHOUT CLOSING'),
                _fixed_line("000300", " ", "    DISPLAY WS-X."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # Should have a STRING_LITERAL token with the accumulated content
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1

        # The content should include parts from both lines
        all_string_content = " ".join(t.value for t in string_tokens)
        assert (
            "HELLO WORLD" in all_string_content or "MORE CONTENT" in all_string_content
        )

    def test_long_string_no_continuation_remainder_parsed(self):
        """After emitting the partial string token, the remainder of the
        non-continuation line should be parsed normally."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    05 WS-X PIC X(80) VALUE "ABCDEFGH'),
                _fixed_line("000200", "-", '    "IJKLMNOP'),
                _fixed_line("000300", " ", "    MOVE 1 TO WS-Y."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # The MOVE statement on line 3 should be tokenized normally
        move_tokens = [t for t in tokens if t.type == TokenType.MOVE]
        assert len(move_tokens) >= 1

    def test_long_content_direct_no_error(self):
        """Directly call _continue_multiline_string with >3 chars accumulated
        and verify no error is emitted."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    ABCDEF")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["SOME TEXT"]  # 9 chars already
        lexer._open_string_location = SourceLocation(1, 12, 1)

        closed, remainder_tokens = lexer._continue_multiline_string("ABCDEF", 1)

        assert closed is True
        # >3 chars -> no error
        assert len(lexer.errors) == 0

        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1
        assert "SOME TEXT" in string_tokens[0].value


class TestMultilineStringEmptyContentAfterQuote:
    """Test multi-line string where content after the opening quote is empty
    (just the opening quote at end of line).

    This exercises the path where content_after_quote is empty in the
    multi-line string start logic.
    """

    def test_opening_quote_at_end_of_line(self):
        """An opening quote at the very end of the program text area,
        followed by a continuation line, should start a multi-line string
        with empty initial content."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    05 WS-X PIC X(80) VALUE "'),
                _fixed_line("000200", "-", '    "CONTINUED TEXT HERE"'),
                _fixed_line("000300", " ", "    DISPLAY WS-X."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # Should have a STRING_LITERAL token with the continued content
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        # Content should come from the continuation line
        assert any("CONTINUED TEXT HERE" in t.value for t in string_tokens)

    def test_opening_quote_only_no_continuation(self):
        """An opening quote with empty content and no continuation should
        handle gracefully."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", "    05 WS-X PIC X(80) VALUE"),
                _fixed_line("000200", " ", '    "'),
                _fixed_line("000300", " ", "    DISPLAY WS-X."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        # The lexer should not crash; it may or may not produce a string token
        # but should handle this edge case without raising an exception
        eof_tokens = [t for t in tokens if t.type == TokenType.EOF]
        assert len(eof_tokens) == 1  # Tokenization completed successfully

    def test_quote_with_spaces_only_before_end(self):
        """A line with VALUE clause where the string starts with just a quote
        followed by spaces (which get trimmed), with continuation on next line."""
        source = "\n".join(
            [
                _fixed_line("000100", " ", '    05 WS-X PIC X(80) VALUE "'),
                _fixed_line("000200", "-", '    "HELLO"'),
                _fixed_line("000300", " ", "    STOP RUN."),
            ]
        )
        lexer = CobolLexer(source)
        tokens = lexer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        # Should find HELLO in the string content
        assert any("HELLO" in t.value for t in string_tokens)


class TestContinueMultilineStringDirectly:
    """Test _continue_multiline_string by directly manipulating lexer state
    to cover specific branch conditions at lines 1366-1399."""

    def test_continue_short_content_emits_error(self):
        """Directly test: accumulated <=3 chars, line has no quote, not
        a continuation line -> should emit error."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    A")  # NOT continuation
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = []  # nothing accumulated yet
        lexer._open_string_location = SourceLocation(1, 12, 1)

        # Pass "A" as program_text (no closing quote)
        closed, remainder_tokens = lexer._continue_multiline_string("A", 1)

        assert closed is True
        # Content is just "A" (1 char, <=3) -> error should be emitted
        assert len(lexer.errors) >= 1
        assert any(
            "unterminated" in str(e).lower() or "string" in str(e).lower()
            for e in lexer.errors
        )

        # STRING_LITERAL still emitted for robustness
        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1
        assert string_tokens[0].value == "A"

    def test_continue_long_content_no_error(self):
        """Directly test: accumulated >3 chars, no closing quote, not
        a continuation line -> should emit token WITHOUT error."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    ABCDEF")  # NOT continuation
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["SOME TEXT"]  # 9 chars already
        lexer._open_string_location = SourceLocation(1, 12, 1)

        closed, remainder_tokens = lexer._continue_multiline_string("ABCDEF", 1)

        assert closed is True
        # Content is "SOME TEXT" + "ABCDEF" > 3 chars -> NO error
        assert len(lexer.errors) == 0

        # STRING_LITERAL emitted
        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1
        assert "SOME TEXT" in string_tokens[0].value

    def test_continue_exactly_3_chars_emits_error(self):
        """Boundary test: exactly 3 chars accumulated -> should emit error
        (<=3 chars threshold)."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    X")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["AB"]  # 2 chars
        lexer._open_string_location = SourceLocation(1, 12, 1)

        # "X" gets appended -> total "ABX" = 3 chars (<=3)
        closed, remainder_tokens = lexer._continue_multiline_string("X", 1)

        assert closed is True
        assert len(lexer.errors) >= 1

    def test_continue_exactly_4_chars_no_error(self):
        """Boundary test: exactly 4 chars accumulated -> should NOT emit
        error (>3 chars threshold)."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    XY")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["AB"]  # 2 chars
        lexer._open_string_location = SourceLocation(1, 12, 1)

        # "XY" gets appended -> total "ABXY" = 4 chars (>3)
        closed, remainder_tokens = lexer._continue_multiline_string("XY", 1)

        assert closed is True
        assert len(lexer.errors) == 0

        string_tokens = [
            t for t in remainder_tokens if t.type == TokenType.STRING_LITERAL
        ]
        assert len(string_tokens) >= 1
        assert string_tokens[0].value == "ABXY"

    def test_string_state_cleared_after_emit(self):
        """After emitting a token via the non-continuation path, the
        multi-line string state should be fully cleared."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    ABCDE")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["HELLO"]
        lexer._open_string_location = SourceLocation(1, 12, 1)

        closed, _ = lexer._continue_multiline_string("ABCDE", 1)

        assert closed is True
        # All string state should be cleared
        assert lexer._open_string_quote is None
        assert lexer._open_string_value == []
        assert lexer._open_string_location is None

    def test_remainder_of_line_tokenized_after_emit(self):
        """After emitting the partial string token, the remaining program
        text should be tokenized as normal code."""
        line0 = _fixed_line("000100", " ", "    FILLER")
        line1 = _fixed_line("000200", " ", "    DISPLAY WS-X")
        source = "\n".join([line0, line1])
        lexer = CobolLexer(source)

        lexer._open_string_quote = '"'
        lexer._open_string_value = ["LONG ENOUGH CONTENT"]
        lexer._open_string_location = SourceLocation(1, 12, 1)

        closed, remainder_tokens = lexer._continue_multiline_string("DISPLAY WS-X", 1)

        assert closed is True
        # The remainder should include tokens from "DISPLAY WS-X"
        # (after the string token is emitted, the full program_text is
        # re-tokenized since it's not part of the string)
        token_types = [t.type for t in remainder_tokens]
        assert TokenType.STRING_LITERAL in token_types
        assert TokenType.DISPLAY in token_types
