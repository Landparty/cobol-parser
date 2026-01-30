"""Unit tests for multi-line string literal support in COBOL lexer.

This test suite follows TDD principles to drive the implementation of
multi-line string literal handling in fixed-format COBOL.
"""

import pytest
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.plugins.core import DialectType


class TestMultiLineStringLiterals:
    """Test cases for multi-line string literal support in fixed-format COBOL."""
    
    def test_single_line_string_baseline(self):
        """Baseline: Single-line string should work correctly."""
        source = '       01  X PIC X(10) VALUE "HELLO".'
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        # Find the string literal token
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "HELLO"
        assert len(lexer.errors) == 0
    
    def test_two_line_continuation_simple(self):
        """Two-line string with continuation indicator."""
        source = '''       01  X PIC X(42) VALUE
      -    "OFFICIAL COBOL COMPILER VALIDATION SYSTEM".'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        # Should produce single STRING_LITERAL token
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "OFFICIAL COBOL COMPILER VALIDATION SYSTEM"
        assert len(lexer.errors) == 0, f"Unexpected errors: {lexer.errors}"
    
    def test_three_line_continuation(self):
        """Three-line string continuation."""
        source = '''       01  X PIC X(60) VALUE
      -    "FIRST PART
      -     SECOND PART".'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        # Should merge all three lines
        assert "FIRST PART" in string_tokens[0].value
        assert "SECOND PART" in string_tokens[0].value
        assert len(lexer.errors) == 0
    
    def test_continuation_with_apostrophes(self):
        """Test with apostrophes instead of quotes."""
        source = """       01  X PIC X(20) VALUE
      -    'CONTINUED STRING'."""
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "CONTINUED STRING"
        assert len(lexer.errors) == 0
    
    def test_doubled_quotes_in_multiline(self):
        """Escaped quotes (doubled) across lines."""
        source = '''       01  X PIC X(30) VALUE
      -    "STRING WITH ""QUOTED"" WORD".'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        # Doubled quotes should be preserved as single quotes in the value
        assert '"QUOTED"' in string_tokens[0].value or 'QUOTED' in string_tokens[0].value
        assert len(lexer.errors) == 0
    
    def test_real_world_ix103a_line_241(self):
        """Actual case from IX103A.CBL line 241-243."""
        # Note: Line 243 doesn't have '-' in column 7, but the string starts there
        source = '''024100     02  FILLER                    PIC X(42)    VALUE             IX1034.2
024200     "OFFICIAL COBOL COMPILER VALIDATION SYSTEM".                 IX1034.2'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        # Should handle this case (even without proper continuation indicator)
        assert len(string_tokens) >= 1
        # Should not have "Unterminated string literal" error
        unterminated_errors = [e for e in lexer.errors if "Unterminated" in str(e)]
        assert len(unterminated_errors) == 0, f"Should not have unterminated errors: {unterminated_errors}"
    
    def test_real_world_ix103a_line_311(self):
        """Actual case from IX103A.CBL line 311-313 (proper continuation)."""
        source = '''031100     02 FILLER  PIC IS X(65)    VALUE IS "************************IX1034.2
031200-    "*****************************************".                 IX1034.2'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        # Should merge the two parts
        assert "************************" in string_tokens[0].value
        assert "*****************************************" in string_tokens[0].value
        assert len(lexer.errors) == 0
    
    def test_string_ending_at_column_72(self):
        """String that ends exactly at column 72 (boundary condition)."""
        # Create a string that fills exactly to column 72
        # Columns: 1-6 (seq), 7 (ind), 8-72 (text) = 65 chars of text
        source = '       01  X PIC X(50) VALUE "' + 'A' * 35 + '".'
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert len(string_tokens[0].value) == 35
    
    def test_malformed_missing_continuation_indicator(self):
        """Missing '-' in column 7 should be handled gracefully."""
        source = '''       01  X PIC X(20) VALUE "START
           NO CONTINUATION INDICATOR".'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        # This is malformed, but lexer should handle it gracefully
        # Either by treating as two separate strings or reporting a clear error
        # The key is not to crash
        assert tokens is not None
    
    def test_multiple_strings_on_same_line(self):
        """Multiple string literals on the same line."""
        source = '       01  X PIC X(10) VALUE "HELLO".\n       01  Y PIC X(10) VALUE "WORLD".'
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 2
        assert string_tokens[0].value == "HELLO"
        assert string_tokens[1].value == "WORLD"
    
    def test_empty_string_literal(self):
        """Empty string literal."""
        source = '       01  X PIC X(10) VALUE "".'
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == ""
    
    def test_continuation_with_leading_spaces(self):
        """Continuation line with leading spaces in the string content."""
        source = '''       01  X PIC X(30) VALUE
      -    "    INDENTED TEXT".'''
        lexer = CobolLexer(source, free_form=False)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        # Leading spaces in the string should be preserved
        assert string_tokens[0].value.startswith("    ")


class TestFreeFormStringLiterals:
    """Ensure free-form COBOL string handling still works."""
    
    def test_free_form_single_line(self):
        """Free-form single-line string should work."""
        source = '01 X PIC X(10) VALUE "HELLO".'
        lexer = CobolLexer(source, free_form=True)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "HELLO"
    
    def test_free_form_no_continuation_support(self):
        """Free-form doesn't use continuation indicators."""
        source = 'DISPLAY "HELLO WORLD".'
        lexer = CobolLexer(source, free_form=True)
        tokens = lexer.tokenize()
        
        string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(string_tokens) == 1
        assert string_tokens[0].value == "HELLO WORLD"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
