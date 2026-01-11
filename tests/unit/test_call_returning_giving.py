"""Test suite for CALL statement parsing - Phase 2 Implementation.

This module implements test coverage for CALL statement RETURNING/GIVING 
mutual exclusivity (FR-006a) - the critical blocking issue resolved in T014.

Tests use unit-level token manipulation following baseline test patterns.
"""

import pytest
from cobolparser.parser import CobolParser, TokenType, Token, SourceLocation
from cobolparser.models.statements import CallStatement, CallParameter


class TestCallReturningGiving:
    """Test RETURNING and GIVING clauses (US-3, FR-005, FR-006, FR-006a)."""

    def test_returning_only(self):
        """Test CALL with RETURNING clause only."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "CALCULATOR", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 19)),
            Token(TokenType.IDENTIFIER, "WS-RESULT", SourceLocation(1, 29)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 39)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert call_stmt.returning_parameter == "WS-RESULT"
        assert call_stmt.giving_parameter is None

    def test_giving_only(self):
        """Test CALL with GIVING clause only (IBM extension)."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "PROCESSOR", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "GIVING", SourceLocation(1, 18)),
            Token(TokenType.IDENTIFIER, "WS-OUTPUT", SourceLocation(1, 25)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 35)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert call_stmt.giving_parameter == "WS-OUTPUT"
        assert call_stmt.returning_parameter is None

    def test_neither_returning_nor_giving(self):
        """Test CALL with neither RETURNING nor GIVING."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "WORKER", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 14)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert call_stmt.returning_parameter is None
        assert call_stmt.giving_parameter is None

    def test_returning_with_using_clause(self):
        """Test CALL with both USING and RETURNING clauses."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "ADD", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 18)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 21)),
            Token(TokenType.IDENTIFIER, "WS-INPUT", SourceLocation(1, 31)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 40)),
            Token(TokenType.IDENTIFIER, "WS-RESULT", SourceLocation(1, 50)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 60)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        assert len(call_stmt.using_parameters) == 1
        assert call_stmt.using_parameters[0].name == "WS-INPUT"
        assert call_stmt.returning_parameter == "WS-RESULT"

    def test_returning_and_giving_mutually_exclusive(self):
        """Test that RETURNING and GIVING are mutually exclusive (FR-006a - CRITICAL TEST)."""
        parser = CobolParser()
        parser.tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "FUNC", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 13)),
            Token(TokenType.IDENTIFIER, "WS-RESULT", SourceLocation(1, 23)),
            Token(TokenType.IDENTIFIER, "GIVING", SourceLocation(1, 33)),
            Token(TokenType.IDENTIFIER, "WS-OUTPUT", SourceLocation(1, 40)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 50)),
            Token(TokenType.EOF, "", SourceLocation(2, 1))
        ]
        parser.current_token_index = 0
        parser.current_token = parser.tokens[0]
        
        call_stmt = parser.parse_call_statement()
        
        assert call_stmt is not None
        # Parser should collect error for mutually exclusive clauses
        assert len(parser.errors) > 0
        error_messages = [str(err) for err in parser.errors]
        assert any("mutually exclusive" in msg for msg in error_messages), \
            f"Expected 'mutually exclusive' error, got: {error_messages}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
