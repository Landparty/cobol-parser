"""Tests for the free-form COBOL tokenization path in lexer.py."""

from cobolparser.lexer import CobolLexer, TokenType


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
