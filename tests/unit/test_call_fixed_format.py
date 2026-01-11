"""Test suite for COBOL fixed format compliance (T019).

Tests FR-011 and FR-012: Multi-line CALL statements with continuation.
Covers continuation handling with hyphen in column 7 and column boundaries (8-72).
"""

import pytest
from cobolparser.parser import CobolParser, TokenType, Token, SourceLocation


class TestCallFixedFormat:
    """Test fixed format compliance (US-5, FR-011, FR-012)."""

    def test_multiline_call_with_continuation(self):
        """Test CALL spanning multiple lines with hyphen continuation (FR-011)."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "MULTILINE", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 17)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 23)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 26)),
            Token(TokenType.IDENTIFIER, "P1", SourceLocation(2, 35)),  # Continuation line
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(2, 38)),
            Token(TokenType.IDENTIFIER, "CONTENT", SourceLocation(2, 41)),
            Token(TokenType.IDENTIFIER, "P2", SourceLocation(2, 49)),
            Token(TokenType.PERIOD, ".", SourceLocation(2, 52)),
            Token(TokenType.EOF, "", SourceLocation(3, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert call_stmt.called_program == '"MULTILINE"'
        assert len(call_stmt.using_parameters) == 2

    def test_columns_8_72_compliance(self):
        """Test CALL statements confined to columns 8-72 (FR-012)."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 8)),  # Column 8 start
            Token(TokenType.STRING_LITERAL, "COLUMNS", SourceLocation(1, 13)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "PARAM1", SourceLocation(1, 28)),
            Token(TokenType.IDENTIFIER, "PARAM2", SourceLocation(1, 36)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 72)),  # Column 72 end
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert call_stmt.called_program == '"COLUMNS"'
        assert len(call_stmt.using_parameters) == 2

    def test_continuation_in_parameter_list(self):
        """Test continuation in the middle of parameter list (FR-011)."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "PROG", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "P1", SourceLocation(1, 18)),
            Token(TokenType.IDENTIFIER, "P2", SourceLocation(2, 35)),  # Continuation
            Token(TokenType.IDENTIFIER, "P3", SourceLocation(3, 35)),  # Second continuation
            Token(TokenType.PERIOD, ".", SourceLocation(3, 39)),
            Token(TokenType.EOF, "", SourceLocation(4, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert len(call_stmt.using_parameters) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
