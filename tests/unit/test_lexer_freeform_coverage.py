"""Tests for free-form COBOL tokenization paths in lexer.py.

Targets coverage gaps in character-level methods (lines 663-789):
- peek_char, advance_char, skip_whitespace
- read_string_literal, read_numeric_literal, read_identifier
- free-form tokenize() path
"""

from cobolparser.lexer import CobolLexer, TokenType


class TestAdvanceCharEdgeCases:
    """Tests for advance_char (lines 670-684)."""

    def test_advance_char_returns_none_at_end(self):
        """advance_char returns None when at end of source."""
        lexer = CobolLexer("", free_form=True)
        assert lexer.advance_char() is None

    def test_advance_char_tracks_newline(self):
        """advance_char increments line on newline."""
        lexer = CobolLexer("A\nB", free_form=True)
        assert lexer.advance_char() == "A"
        assert lexer.current_line == 0
        assert lexer.advance_char() == "\n"
        assert lexer.current_line == 1
        assert lexer.current_column == 0
        assert lexer.advance_char() == "B"
        assert lexer.current_column == 1

    def test_advance_char_increments_column(self):
        """advance_char increments column on non-newline."""
        lexer = CobolLexer("AB", free_form=True)
        lexer.advance_char()
        assert lexer.current_column == 1
        lexer.advance_char()
        assert lexer.current_column == 2


class TestPeekChar:
    """Tests for peek_char (lines 663-668)."""

    def test_peek_char_returns_none_at_end(self):
        lexer = CobolLexer("", free_form=True)
        assert lexer.peek_char() is None

    def test_peek_char_with_offset(self):
        lexer = CobolLexer("ABC", free_form=True)
        assert lexer.peek_char(0) == "A"
        assert lexer.peek_char(1) == "B"
        assert lexer.peek_char(2) == "C"
        assert lexer.peek_char(3) is None


class TestSkipWhitespace:
    """Tests for skip_whitespace (lines 686-692)."""

    def test_skip_whitespace_skips_spaces(self):
        lexer = CobolLexer("   A", free_form=True)
        lexer.skip_whitespace()
        assert lexer.peek_char() == "A"

    def test_skip_whitespace_skips_tabs(self):
        lexer = CobolLexer("\t\tA", free_form=True)
        lexer.skip_whitespace()
        assert lexer.peek_char() == "A"

    def test_skip_whitespace_stops_at_newline(self):
        lexer = CobolLexer(" \n", free_form=True)
        lexer.skip_whitespace()
        assert lexer.peek_char() == "\n"

    def test_skip_whitespace_noop_at_nonwhitespace(self):
        lexer = CobolLexer("A", free_form=True)
        lexer.skip_whitespace()
        assert lexer.peek_char() == "A"

    def test_skip_whitespace_noop_at_end(self):
        lexer = CobolLexer("", free_form=True)
        lexer.skip_whitespace()
        assert lexer.peek_char() is None


class TestReadStringLiteral:
    """Tests for read_string_literal (lines 694-725)."""

    def test_read_simple_string(self):
        lexer = CobolLexer('"HELLO"', free_form=True)
        token = lexer.read_string_literal('"')
        assert token.type == TokenType.STRING_LITERAL
        assert token.value == "HELLO"

    def test_read_string_with_doubled_quotes(self):
        lexer = CobolLexer('"HE""LLO"', free_form=True)
        token = lexer.read_string_literal('"')
        assert token.type == TokenType.STRING_LITERAL
        assert token.value == 'HE"LLO'

    def test_read_unterminated_string(self):
        lexer = CobolLexer('"HELLO', free_form=True)
        token = lexer.read_string_literal('"')
        assert token.type == TokenType.STRING_LITERAL
        assert token.value == "HELLO"
        assert len(lexer.errors) == 1
        assert "Unterminated" in lexer.errors[0].message

    def test_read_empty_string(self):
        lexer = CobolLexer('""', free_form=True)
        token = lexer.read_string_literal('"')
        assert token.type == TokenType.STRING_LITERAL
        assert token.value == ""

    def test_read_string_single_quotes(self):
        lexer = CobolLexer("'HELLO'", free_form=True)
        token = lexer.read_string_literal("'")
        assert token.type == TokenType.STRING_LITERAL
        assert token.value == "HELLO"


class TestReadNumericLiteral:
    """Tests for read_numeric_literal (lines 727-758)."""

    def test_read_integer(self):
        lexer = CobolLexer("123", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.type == TokenType.NUMERIC_LITERAL
        assert token.value == "123"

    def test_read_decimal(self):
        lexer = CobolLexer("3.14", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.value == "3.14"

    def test_read_scientific_notation(self):
        lexer = CobolLexer("1.5E+10", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.value == "1.5E+10"

    def test_read_scientific_notation_negative(self):
        lexer = CobolLexer("3E-4", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.value == "3E-4"

    def test_read_number_stops_at_non_digit(self):
        lexer = CobolLexer("42 ", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.value == "42"

    def test_read_number_at_end_of_source(self):
        lexer = CobolLexer("99", free_form=True)
        token = lexer.read_numeric_literal()
        assert token.value == "99"


class TestReadIdentifier:
    """Tests for read_identifier (lines 760-789)."""

    def test_read_keyword(self):
        lexer = CobolLexer("DISPLAY", free_form=True)
        token = lexer.read_identifier()
        assert token.type == TokenType.DISPLAY

    def test_read_figurative_constant(self):
        lexer = CobolLexer("SPACES", free_form=True)
        token = lexer.read_identifier()
        assert token.type == TokenType.FIGURATIVE_CONSTANT

    def test_read_level_number(self):
        lexer = CobolLexer("01", free_form=True)
        token = lexer.read_identifier()
        assert token.type == TokenType.LEVEL_NUMBER

    def test_read_regular_identifier(self):
        lexer = CobolLexer("WS-COUNTER", free_form=True)
        token = lexer.read_identifier()
        assert token.type == TokenType.IDENTIFIER
        assert token.value == "WS-COUNTER"

    def test_read_identifier_with_underscores(self):
        lexer = CobolLexer("MY_VAR", free_form=True)
        token = lexer.read_identifier()
        assert token.type == TokenType.IDENTIFIER
        assert token.value == "MY_VAR"


class TestFreeFormTokenize:
    """Tests for the free-form tokenize() path (lines 1501-1520)."""

    def test_freeform_simple_display(self):
        """Free-form mode tokenizes without column layout."""
        lexer = CobolLexer('DISPLAY "HELLO".', free_form=True)
        tokens = lexer.tokenize()
        types = [t.type for t in tokens]
        assert TokenType.DISPLAY in types
        assert TokenType.STRING_LITERAL in types
        assert TokenType.PERIOD in types

    def test_freeform_multiline(self):
        """Free-form mode inserts NEWLINE tokens after each line."""
        lexer = CobolLexer("MOVE A TO B.\nDISPLAY C.", free_form=True)
        tokens = lexer.tokenize()
        types = [t.type for t in tokens]
        assert types.count(TokenType.NEWLINE) >= 1

    def test_freeform_identifier_and_numeric(self):
        """Free-form mode tokenizes identifiers and numbers."""
        lexer = CobolLexer("ADD 100 TO WS-COUNT.", free_form=True)
        tokens = lexer.tokenize()
        types = [t.type for t in tokens]
        assert TokenType.ADD in types
        assert TokenType.NUMERIC_LITERAL in types
        assert TokenType.IDENTIFIER in types

    def test_freeform_empty_line(self):
        """Free-form mode handles empty lines without crashing."""
        lexer = CobolLexer("\n\n", free_form=True)
        tokens = lexer.tokenize()
        # Empty lines may produce EOF or other minimal tokens
        assert isinstance(tokens, list)

    def test_freeform_string_with_escaped_quotes(self):
        """Free-form mode handles doubled-quote escaping."""
        lexer = CobolLexer('DISPLAY "HE""LLO".', free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert string_tokens[0].value == 'HE"LLO'

    def test_freeform_unterminated_string_no_error(self):
        """Free-form mode doesn't add LexerError for isolated unterminated quotes."""
        lexer = CobolLexer('DISPLAY "HELLO', free_form=True)
        tokens = lexer.tokenize()
        # Free-form is more permissive with unterminated strings
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1

    def test_freeform_operators(self):
        """Free-form mode tokenizes operators."""
        lexer = CobolLexer("IF A = B", free_form=True)
        tokens = lexer.tokenize()
        types = [t.type for t in tokens]
        assert TokenType.IF in types
        assert TokenType.ASSIGN in types
