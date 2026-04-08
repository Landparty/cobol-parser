"""Tests for lexer edge case coverage.

Targets uncovered lines in lexer.py (77.05%):
  - read_string_literal() with quote doubling escape sequences
  - read_numeric_literal() with scientific notation (E-notation)
  - Fixed-form string continuation across comment lines
  - Free-form unterminated string handling
  - _compress_doubled_quotes() COBOL escape sequences
  - _try_single_line_string() unterminated detection
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType


class TestReadStringLiteralQuoteDoubling:
    """Cover read_string_literal with doubled quote escape."""

    def test_doubled_single_quotes(self):
        """COBOL string 'DON''T' should produce DON'T."""
        lexer = CobolLexer("DISPLAY 'DON''T PANIC'.", free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert "DON'T PANIC" == string_tokens[0].value

    def test_doubled_double_quotes(self):
        """COBOL string with doubled double-quotes should compress to single."""
        source = 'DISPLAY "SAY ""HELLO""".'
        lexer = CobolLexer(source, free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert 'SAY "HELLO"' == string_tokens[0].value


class TestReadNumericLiteralScientific:
    """Cover read_numeric_literal with E-notation."""

    def test_scientific_notation_positive_exponent(self):
        lexer = CobolLexer("MOVE 1.5E+3 TO WS-NUM.", free_form=True)
        tokens = lexer.tokenize()
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens) >= 1
        assert "1.5E+3" == numeric_tokens[0].value

    def test_scientific_notation_negative_exponent(self):
        lexer = CobolLexer("MOVE 2.7E-5 TO WS-NUM.", free_form=True)
        tokens = lexer.tokenize()
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens) >= 1
        assert "2.7E-5" == numeric_tokens[0].value

    def test_scientific_notation_no_sign(self):
        lexer = CobolLexer("MOVE 3E2 TO WS-NUM.", free_form=True)
        tokens = lexer.tokenize()
        numeric_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert len(numeric_tokens) >= 1
        assert "3E2" == numeric_tokens[0].value


class TestUnterminatedStringHandling:
    """Cover unterminated string handling via direct method calls."""

    def test_read_string_from_text_unterminated_short(self):
        """Short unterminated strings produce errors via read_string_from_text."""
        lexer = CobolLexer("", free_form=True)
        tok, pos = lexer.read_string_from_text("'X", 0, 0, 0)
        assert tok.type == TokenType.STRING_LITERAL
        assert len(lexer.errors) >= 1

    def test_read_string_from_text_unterminated_long(self):
        """Longer unterminated strings are permissive (multi-line compat)."""
        lexer = CobolLexer("", free_form=True)
        tok, pos = lexer.read_string_from_text(
            "'THIS IS A LONG STRING VALUE WITHOUT CLOSING", 0, 0, 0
        )
        assert tok.type == TokenType.STRING_LITERAL
        assert tok.value == "THIS IS A LONG STRING VALUE WITHOUT CLOSING"

    def test_try_single_line_string_unterminated(self):
        """_try_single_line_string returns unterminated flag."""
        lexer = CobolLexer("", free_form=True)
        tok, pos, unterminated = lexer._try_single_line_string("'HELLO", 0, 0, 0)
        assert tok is None
        assert unterminated is True

    def test_try_single_line_string_terminated(self):
        """_try_single_line_string returns token for terminated string."""
        lexer = CobolLexer("", free_form=True)
        tok, pos, unterminated = lexer._try_single_line_string("'HELLO'", 0, 0, 0)
        assert tok is not None
        assert tok.value == "HELLO"
        assert unterminated is False

    def test_try_single_line_string_doubled_quotes(self):
        """_try_single_line_string handles doubled quote escaping."""
        lexer = CobolLexer("", free_form=True)
        tok, pos, unterminated = lexer._try_single_line_string("'DON''T'", 0, 0, 0)
        assert tok is not None
        assert tok.value == "DON'T"
        assert unterminated is False


class TestCompressDoubledQuotes:
    """Cover _compress_doubled_quotes utility method."""

    def test_compress_doubled_delimiter(self):
        lexer = CobolLexer("", free_form=True)
        result = lexer._compress_doubled_quotes("DON''T", "'")
        assert result == "DON'T"

    def test_compress_doubled_double_in_double_string(self):
        lexer = CobolLexer("", free_form=True)
        result = lexer._compress_doubled_quotes('SAY ""HELLO""', '"')
        assert result == 'SAY "HELLO"'

    def test_compress_doubled_single_in_double_string(self):
        """Special case: doubled single quotes inside double-quoted string."""
        lexer = CobolLexer("", free_form=True)
        result = lexer._compress_doubled_quotes("IT''S", '"')
        assert result == "IT'S"

    def test_no_quotes_returns_unchanged(self):
        lexer = CobolLexer("", free_form=True)
        result = lexer._compress_doubled_quotes("HELLO WORLD", "'")
        assert result == "HELLO WORLD"


class TestReadIdentifierKeywordLookup:
    """Cover read_identifier keyword and figurative constant branches."""

    def test_figurative_constant_spaces(self):
        lexer = CobolLexer("MOVE SPACES TO WS-X.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1
        assert fig_tokens[0].value.upper() == "SPACES"

    def test_figurative_constant_zeros(self):
        lexer = CobolLexer("MOVE ZEROS TO WS-X.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

    def test_level_number_tokenized(self):
        lexer = CobolLexer("01 WS-RECORD PIC X(10).", free_form=True)
        tokens = lexer.tokenize()
        level_tokens = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
        assert len(level_tokens) >= 1
        assert level_tokens[0].value == "01"


class TestFixedFormStringContinuation:
    """Cover fixed-form string continuation edge cases."""

    def test_comment_interrupting_multiline_string(self):
        """A comment line between continuation lines clears string state."""
        lines = [
            "000010 IDENTIFICATION DIVISION.                                         ",
            "000020 PROGRAM-ID. TEST.                                                ",
            "000030 PROCEDURE DIVISION.                                              ",
            "000040     DISPLAY 'HELLO                                               ",
            "000050*    THIS IS A COMMENT                                            ",
            "000060     DISPLAY 'WORLD'.                                             ",
            "000070     STOP RUN.                                                    ",
        ]
        source = "\n".join(lines)
        result = parse_cobol(source)
        assert result.ast is not None


class TestInvalidCharacterHandling:
    """Cover unknown character error reporting in free-form lexer."""

    def test_invalid_character_recorded(self):
        """Characters like @ that COBOL doesn't use produce lexer errors."""
        lexer = CobolLexer("MOVE @INVALID TO X.", free_form=True)
        lexer.tokenize()
        # The lexer should record an error for '@'
        assert any("Invalid character" in str(e) for e in lexer.errors)


class TestSkipWhitespace:
    """Cover skip_whitespace method."""

    def test_whitespace_skipped_between_tokens(self):
        lexer = CobolLexer("MOVE     WS-A   TO   WS-B.", free_form=True)
        tokens = lexer.tokenize()
        identifiers = [
            t
            for t in tokens
            if t.type == TokenType.IDENTIFIER or t.type in (TokenType.MOVE,)
        ]
        assert len(identifiers) >= 1
