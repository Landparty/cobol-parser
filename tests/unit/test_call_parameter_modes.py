"""Test suite for parameter passing modes (T016).

Tests FR-003 and FR-004: Parameter passing modes (BY REFERENCE, BY CONTENT, BY VALUE).
Covers all three modes and default behavior.
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.call_parser import CallStatementParser


class TestCallParameterModes:
    """Test parameter passing modes (US-2, FR-003, FR-004)."""

    def test_by_reference_mode(self):
        """Test BY REFERENCE parameter passing mode (FR-003)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "PROCESS", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 21)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 24)),
            Token(TokenType.IDENTIFIER, "WS-PARAM", SourceLocation(1, 34)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 43)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert len(call_stmt.using_parameters) == 1
        assert call_stmt.using_parameters[0].name == "WS-PARAM"
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"

    def test_by_content_mode(self):
        """Test BY CONTENT parameter passing mode (FR-003)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "PROCESS", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 21)),
            Token(TokenType.IDENTIFIER, "CONTENT", SourceLocation(1, 24)),
            Token(TokenType.IDENTIFIER, "WS-PARAM", SourceLocation(1, 32)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 41)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.using_parameters[0].passing_mode == "CONTENT"

    def test_by_value_mode(self):
        """Test BY VALUE parameter passing mode (FR-004)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "INCREMENT", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 17)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 23)),
            Token(TokenType.IDENTIFIER, "VALUE", SourceLocation(1, 26)),
            Token(TokenType.IDENTIFIER, "WS-COUNT", SourceLocation(1, 32)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 41)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.using_parameters[0].passing_mode == "VALUE"

    def test_default_mode_no_explicit_mode(self):
        """Test default mode (BY REFERENCE) when no mode specified (FR-003)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "PROCESS", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "WS-PARAM", SourceLocation(1, 21)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 30)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"

    def test_mixed_parameter_modes(self):
        """Test mixed parameter passing modes in single CALL (FR-003, FR-004)."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "MIXED", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 13)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 19)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 22)),
            Token(TokenType.IDENTIFIER, "P1", SourceLocation(1, 32)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 35)),
            Token(TokenType.IDENTIFIER, "CONTENT", SourceLocation(1, 38)),
            Token(TokenType.IDENTIFIER, "P2", SourceLocation(1, 46)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 49)),
            Token(TokenType.IDENTIFIER, "VALUE", SourceLocation(1, 52)),
            Token(TokenType.IDENTIFIER, "P3", SourceLocation(1, 58)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 61)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert len(call_stmt.using_parameters) == 3
        assert call_stmt.using_parameters[0].passing_mode == "REFERENCE"
        assert call_stmt.using_parameters[1].passing_mode == "CONTENT"
        assert call_stmt.using_parameters[2].passing_mode == "VALUE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
