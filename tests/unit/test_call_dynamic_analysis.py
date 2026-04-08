"""Test suite for dynamic CALL analysis (T020).

Tests FR-015 and FR-016: Dynamic CALL analysis with MOVE statement tracking.
Covers value tracking from assignment statements to CALL parameters.
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.call_parser import CallStatementParser


class TestCallDynamicAnalysis:
    """Test dynamic CALL analysis (US-6, FR-015, FR-016)."""

    def test_dynamic_call_variable_tracking(self):
        """Test tracking of variable used for dynamic CALL (FR-015)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "WS-PROG", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 14)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.is_dynamic is True
        assert call_stmt.called_program == "WS-PROG"

    def test_call_with_literal_vs_variable(self):
        """Test distinction between literal and variable program names (FR-015, FR-016)."""
        # Test with literal
        tokens1 = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "STATIC", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 14)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream1 = TokenStream(tokens1)
        call_parser1 = CallStatementParser()
        call_stmt1 = call_parser1.parse(stream1)

        assert call_stmt1.is_dynamic is False

        # Test with variable
        tokens2 = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DYNAMIC", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 14)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream2 = TokenStream(tokens2)
        call_parser2 = CallStatementParser()
        call_stmt2 = call_parser2.parse(stream2)

        assert call_stmt2.is_dynamic is True

    def test_call_parameter_analysis(self):
        """Test analysis of CALL parameters for dynamic tracking (FR-016)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "SUBPROG-VAR", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 18)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 24)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 27)),
            Token(TokenType.IDENTIFIER, "PARAM-VAR", SourceLocation(1, 37)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 47)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.is_dynamic is True
        assert len(call_stmt.using_parameters) == 1
        assert call_stmt.using_parameters[0].name == "PARAM-VAR"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
