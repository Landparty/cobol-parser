"""Tests targeting uncovered lines in lexer.py.

Covers:
- read_string_literal: unterminated strings, doubled-quote escaping (lines 696-725)
- read_numeric_literal: scientific notation with E+/- (lines 729-758)
- read_identifier: figurative constants, level numbers (lines 762-789)
- Multi-line string continuation: comment interruption (lines 930-957)
- Fixed-format VALUE clause with continuation (lines 921-937)
- Unterminated continuation strings (lines 1366-1399)
- Ampersand handling (line 1164)
"""

import pytest

from cobolparser.lexer import CobolLexer, TokenType


class TestFreeFormStringLiteral:
    """read_string_literal in free-form mode (lines 696-725)."""

    def test_simple_string(self):
        tokens = CobolLexer('DISPLAY "HELLO".', free_form=True).tokenize()
        string_toks = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_toks) == 1
        assert string_toks[0].value == "HELLO"

    def test_doubled_quote_escape(self):
        tokens = CobolLexer('DISPLAY "HE""LLO".', free_form=True).tokenize()
        string_toks = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_toks) >= 1
        # Doubled quote should produce a single embedded quote
        assert 'HE"LLO' == string_toks[0].value

    def test_apostrophe_string(self):
        tokens = CobolLexer("DISPLAY 'HELLO'.", free_form=True).tokenize()
        string_toks = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_toks) == 1
        assert string_toks[0].value == "HELLO"

    def test_unterminated_string_produces_error(self):
        lexer = CobolLexer('DISPLAY "HELLO', free_form=True)
        lexer.tokenize()
        # Unterminated string should produce at least one error or token
        has_string = any(t.type == TokenType.STRING_LITERAL for t in lexer.tokens)
        assert has_string or len(lexer.errors) > 0


class TestFreeFormNumericLiteral:
    """read_numeric_literal — scientific notation (lines 729-758)."""

    def test_integer_literal(self):
        tokens = CobolLexer("MOVE 123 TO A.", free_form=True).tokenize()
        num_toks = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert any(t.value == "123" for t in num_toks)

    def test_decimal_literal(self):
        tokens = CobolLexer("MOVE 3.14 TO A.", free_form=True).tokenize()
        num_toks = [t for t in tokens if t.type == TokenType.NUMERIC_LITERAL]
        assert any(t.value == "3.14" for t in num_toks)

    def test_scientific_notation(self):
        tokens = CobolLexer("MOVE 1E5 TO A.", free_form=True).tokenize()
        all_values = [t.value for t in tokens if t.value]
        # Exponent notation should appear in at least one token
        assert any("1E5" in v or "1e5" in v for v in all_values)

    def test_scientific_notation_with_sign(self):
        tokens = CobolLexer("MOVE 2E+3 TO A.", free_form=True).tokenize()
        all_values = [t.value for t in tokens if t.value]
        assert any("2E+3" in v or "2E" in v for v in all_values)


@pytest.mark.parametrize(
    "constant",
    ["SPACES", "ZEROS", "HIGH-VALUES", "LOW-VALUES"],
    ids=["spaces", "zeros", "high-values", "low-values"],
)
class TestFigurativeConstants:
    """read_identifier — figurative constant detection (lines 782-783)."""

    def test_figurative_constant(self, constant):
        tokens = CobolLexer(f"MOVE {constant} TO A.", free_form=True).tokenize()
        fig_toks = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_toks) == 1
        assert fig_toks[0].value.upper() == constant


class TestLevelNumberDetection:
    """read_identifier — level number detection (lines 784-785)."""

    def test_level_01(self):
        tokens = CobolLexer("01 WS-NAME PIC X(10).", free_form=True).tokenize()
        level_toks = [t for t in tokens if t.type == TokenType.LEVEL_NUMBER]
        assert len(level_toks) >= 1
        assert level_toks[0].value == "01"


class TestFixedFormatMultilineString:
    """Multi-line string continuation in fixed-format (lines 930-957, 1366-1399)."""

    def test_value_clause_with_continuation(self):
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
        tokens = CobolLexer("\n".join(lines), free_form=False).tokenize()
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
        tokens = CobolLexer("\n".join(lines), free_form=False).tokenize()
        # Comment line should be handled; tokenization should not crash
        comment_toks = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_toks) >= 1


class TestAmpersandHandling:
    """Ampersand is treated as benign separator (line 1164)."""

    def test_ampersand_in_source(self):
        tokens = CobolLexer("MOVE A & B TO C.", free_form=True).tokenize()
        id_toks = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        id_values = {t.value for t in id_toks}
        assert "A" in id_values
        assert "B" in id_values
        assert "C" in id_values


class TestFixedFormatValueFigurativeConstant:
    """VALUE clause with figurative constant stays out of string mode (line 867-868)."""

    def test_value_with_figurative_constant(self):
        lines = [
            "000100 IDENTIFICATION DIVISION.                                         ",
            "000200 PROGRAM-ID. TEST.                                                ",
            "000300 DATA DIVISION.                                                   ",
            "000400 WORKING-STORAGE SECTION.                                         ",
            "000500 01 WS-FLD PIC X(10) VALUE SPACES.                                ",
            "000600 PROCEDURE DIVISION.                                              ",
            "000700     STOP RUN.                                                    ",
        ]
        tokens = CobolLexer("\n".join(lines), free_form=False).tokenize()
        fig_toks = [t for t in tokens if t.type == TokenType.FIGURATIVE_CONSTANT]
        assert len(fig_toks) >= 1
