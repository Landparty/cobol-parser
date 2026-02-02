"""Test suite for basic CALL statement parsing (T015).

Tests FR-001 and FR-002: Basic CALL statements with literal and variable program names.
Covers both static and dynamic CALL variations.
"""

import pytest
from cobolparser.parser import CobolParser, TokenType, Token, SourceLocation
from cobolparser.models.program import CobolDivision


class TestCallBasicParsing:
    """Test basic CALL statement parsing (US-1, FR-001, FR-002)."""

    def test_call_with_literal_program_name(self):
        """Test static CALL with literal program name (FR-001)."""
        parser = CobolParser()
        # Create procedure division to add statement to
        proc_division = CobolDivision("PROCEDURE", SourceLocation(1, 1))
        parser.current_division = proc_division
        
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "SUBPROGRAM", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 18)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        
        call_stmt = parser.parse_sentence(tokens, SourceLocation(1, 1))
        
        assert call_stmt is not None
        assert call_stmt.called_program == '"SUBPROGRAM"'
        assert call_stmt.is_dynamic is False
        assert call_stmt.using_parameters == []

    def test_call_with_variable_program_name(self):
        """Test dynamic CALL with variable program name (FR-002)."""
        parser = CobolParser()
        # Create procedure division to add statement to
        proc_division = CobolDivision("PROCEDURE", SourceLocation(1, 1))
        parser.current_division = proc_division
        
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "WS-PROGRAM", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 17)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        
        call_stmt = parser.parse_sentence(tokens, SourceLocation(1, 1))
        
        assert call_stmt is not None
        assert call_stmt.called_program == "WS-PROGRAM"
        assert call_stmt.is_dynamic is True
        assert call_stmt.using_parameters == []

    def test_call_with_no_parameters(self):
        """Test CALL with no USING clause (FR-001, FR-002)."""
        parser = CobolParser()
        # Create procedure division to add statement to
        proc_division = CobolDivision("PROCEDURE", SourceLocation(1, 1))
        parser.current_division = proc_division
        
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "WORKER", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 14)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        
        call_stmt = parser.parse_sentence(tokens, SourceLocation(1, 1))
        
        assert call_stmt is not None
        assert call_stmt.using_parameters == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
