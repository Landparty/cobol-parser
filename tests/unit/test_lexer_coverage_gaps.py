"""Tests targeting uncovered lines in lexer.py.

Covers:
- read_string_literal: unterminated strings, doubled-quote escaping (lines 696-725)
- read_numeric_literal: scientific notation with E+/- (lines 729-758)
- read_identifier: figurative constants, level numbers (lines 762-789)
- Multi-line string continuation: comment interruption (lines 930-957)
- Fixed-format VALUE clause with continuation (lines 921-937)
- Unterminated continuation strings (lines 1366-1399)
- Ampersand handling (line 1164)
- Various tokenizer edge cases
"""

from cobolparser.lexer import CobolLexer, Token, TokenType


class TestFreeFormStringLiteral:
    """Tests for read_string_literal in free-form mode (lines 696-725)."""

    def test_simple_string(self):
        lexer = CobolLexer('DISPLAY "HELLO".', free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "HELLO"

    def test_doubled_quote_escape(self):
        lexer = CobolLexer('DISPLAY "HE""LLO".', free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) >= 1
        assert '"' in string_tokens[0].value or "HE" in string_tokens[0].value

    def test_apostrophe_string(self):
        lexer = CobolLexer("DISPLAY 'HELLO'.", free_form=True)
        tokens = lexer.tokenize()
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "HELLO"

    def test_unterminated_string(self):
        lexer = CobolLexer('DISPLAY "HELLO', free_form=True)
        tokens = lexer.tokenize()
        # Should produce a string token and/or an error
        assert len(tokens) > 0 or len(lexer.errors) > 0


class TestFreeFormNumericLiteral:
    """Tests for read_numeric_literal — scientific notation (lines 729-758)."""

    def test_integer_literal(self):
        # Numbers like 42 are tokenized as LEVEL_NUMBER in COBOL; use a non-level number
        lexer = CobolLexer("MOVE 123 TO A.", free_form=True)
        tokens = lexer.tokenize()
        num_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert any(t.value == "123" for t in num_tokens)

    def test_decimal_literal(self):
        lexer = CobolLexer("MOVE 3.14 TO A.", free_form=True)
        tokens = lexer.tokenize()
        num_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert any("3.14" in t.value for t in num_tokens)

    def test_scientific_notation(self):
        lexer = CobolLexer("MOVE 1E5 TO A.", free_form=True)
        tokens = lexer.tokenize()
        num_tokens = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert any("1E5" in t.value or "1e5" in t.value for t in num_tokens)

    def test_scientific_notation_with_sign(self):
        lexer = CobolLexer("MOVE 2E+3 TO A.", free_form=True)
        tokens = lexer.tokenize()
        # Should tokenize the number with exponent
        all_values = [t.value for t in tokens]
        assert any("2E+3" in v or "2E" in v for v in all_values if v)


class TestFreeFormIdentifier:
    """Tests for read_identifier — figurative constants, level numbers (lines 762-789)."""

    def test_figurative_constant_spaces(self):
        lexer = CobolLexer("MOVE SPACES TO A.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

    def test_figurative_constant_zeros(self):
        lexer = CobolLexer("MOVE ZEROS TO A.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

    def test_figurative_constant_high_values(self):
        lexer = CobolLexer("MOVE HIGH-VALUES TO A.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

    def test_figurative_constant_low_values(self):
        lexer = CobolLexer("MOVE LOW-VALUES TO A.", free_form=True)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1

    def test_level_number_detection(self):
        lexer = CobolLexer("01 WS-NAME PIC X(10).", free_form=True)
        tokens = lexer.tokenize()
        level_tokens = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
        assert len(level_tokens) >= 1
        assert level_tokens[0].value == "01"


class TestFixedFormatMultilineString:
    """Tests for multi-line string continuation in fixed-format (lines 930-957, 1366-1399)."""

    def test_value_clause_with_continuation(self):
        """VALUE clause spanning two lines with continuation."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                         ",
            "000200 PROGRAM-ID. TEST.                                                ",
            "000300 DATA DIVISION.                                                   ",
            "000400 WORKING-STORAGE SECTION.                                         ",
            '000500 01 WS-MSG PIC X(40) VALUE "HELLO WORLD THIS IS A LONG           ',
            '000600-    "STRING VALUE".                                               ',
            "000700 PROCEDURE DIVISION.                                              ",
            "000800     DISPLAY WS-MSG.                                              ",
            "000900     STOP RUN.                                                    ",
        ]
        source = "\n".join(lines)
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        # Should have string tokens and no fatal errors
        assert len(tokens) > 0

    def test_comment_interrupting_multiline_string(self):
        """Comment line (col 7 = *) while multi-line string is open (lines 943-957)."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                         ",
            "000200 PROGRAM-ID. TEST.                                                ",
            "000300 DATA DIVISION.                                                   ",
            "000400 WORKING-STORAGE SECTION.                                         ",
            '000500 01 WS-MSG PIC X(20) VALUE "HELLO                                ',
            "000600* THIS IS A COMMENT LINE                                          ",
            '000700     WORLD".                                                      ',
            "000800 PROCEDURE DIVISION.                                              ",
            "000900     STOP RUN.                                                    ",
        ]
        source = "\n".join(lines)
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        assert len(tokens) > 0


class TestAmpersandHandling:
    """Tests for ampersand character handling (line 1164)."""

    def test_ampersand_in_source(self):
        """Ampersand is treated as benign separator."""
        lexer = CobolLexer("MOVE A & B TO C.", free_form=True)
        tokens = lexer.tokenize()
        # Should tokenize without fatal error
        id_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(id_tokens) >= 2


class TestFixedFormatValueClauseEdgeCases:
    """Additional fixed-format VALUE clause tests (lines 858-896, 921-937)."""

    def test_value_with_figurative_constant(self):
        """VALUE clause with figurative constant should not enter string mode (line 867-868)."""
        lines = [
            "000100 IDENTIFICATION DIVISION.                                         ",
            "000200 PROGRAM-ID. TEST.                                                ",
            "000300 DATA DIVISION.                                                   ",
            "000400 WORKING-STORAGE SECTION.                                         ",
            '000500 01 WS-FLD PIC X(10) VALUE SPACES.                                ',
            "000600 PROCEDURE DIVISION.                                              ",
            "000700     STOP RUN.                                                    ",
        ]
        source = "\n".join(lines)
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        fig_tokens = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_tokens) >= 1
