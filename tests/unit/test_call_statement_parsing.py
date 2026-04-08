from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.call_parser import CallStatementParser


class TestCallStatementParsing:
    """Test parsing of enhanced CALL statements."""

    def test_call_with_by_reference_content_value(self):
        """Test CALL with mixed parameter passing modes."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "SUBPROG", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "USING", SourceLocation(1, 15)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 21)),
            Token(TokenType.IDENTIFIER, "REFERENCE", SourceLocation(1, 24)),
            Token(TokenType.IDENTIFIER, "PARAM1", SourceLocation(1, 34)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 41)),
            Token(TokenType.IDENTIFIER, "CONTENT", SourceLocation(1, 44)),
            Token(TokenType.IDENTIFIER, "PARAM2", SourceLocation(1, 52)),
            Token(TokenType.IDENTIFIER, "BY", SourceLocation(1, 59)),
            Token(TokenType.IDENTIFIER, "VALUE", SourceLocation(1, 62)),
            Token(TokenType.IDENTIFIER, "PARAM3", SourceLocation(1, 68)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 75)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert len(call_stmt.using_parameters) == 3

        p1 = call_stmt.using_parameters[0]
        assert p1.name == "PARAM1"
        assert p1.passing_mode == "REFERENCE"

        p2 = call_stmt.using_parameters[1]
        assert p2.name == "PARAM2"
        assert p2.passing_mode == "CONTENT"

        p3 = call_stmt.using_parameters[2]
        assert p3.name == "PARAM3"
        assert p3.passing_mode == "VALUE"

    def test_call_with_returning(self):
        """Test CALL with RETURNING clause."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "FUNC", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "RETURNING", SourceLocation(1, 13)),
            Token(TokenType.IDENTIFIER, "RESULT-VAR", SourceLocation(1, 23)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 34)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.returning_parameter == "RESULT-VAR"

    def test_call_with_on_overflow(self):
        """Test CALL with ON OVERFLOW clause."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "SUB", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "ON", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "OVERFLOW", SourceLocation(1, 15)),
            Token(TokenType.DISPLAY, "DISPLAY", SourceLocation(1, 24)),
            Token(TokenType.STRING_LITERAL, "ERROR", SourceLocation(1, 32)),
            Token(TokenType.IDENTIFIER, "END-CALL", SourceLocation(1, 40)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 49)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        # Currently we don't parse the inner statements into the AST, but we should verify parsing succeeds
        assert call_stmt.called_program == "SUB"

    def test_call_with_on_exception(self):
        """Test CALL with ON EXCEPTION clause."""
        tokens = [
            Token(TokenType.CALL, "CALL", SourceLocation(1, 1)),
            Token(TokenType.STRING_LITERAL, "SUB", SourceLocation(1, 6)),
            Token(TokenType.IDENTIFIER, "ON", SourceLocation(1, 12)),
            Token(TokenType.IDENTIFIER, "EXCEPTION", SourceLocation(1, 15)),
            Token(TokenType.DISPLAY, "DISPLAY", SourceLocation(1, 25)),
            Token(TokenType.STRING_LITERAL, "ERROR", SourceLocation(1, 33)),
            Token(TokenType.IDENTIFIER, "END-CALL", SourceLocation(1, 41)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 50)),
            Token(TokenType.EOF, "", SourceLocation(2, 1)),
        ]
        stream = TokenStream(tokens)
        call_parser = CallStatementParser()
        call_stmt = call_parser.parse(stream)

        assert call_stmt is not None
        assert call_stmt.called_program == "SUB"
