"""Additional coverage for parsers/statements/call_parser.py.

Targets branches not exercised by the existing CALL test suite:
  - NOT ON EXCEPTION handler body parsing
  - NOT not followed by ON EXCEPTION (graceful break)
  - missing program name when the stream ends right after CALL
  - statement-keyword identifier terminating the CALL clause loop
  - statement-keyword identifier terminating a USING parameter list
  - nested-statement parsing with no registry / on ParseError
"""

from cobolparser.core.exceptions import ParseError
from cobolparser.core.interfaces import IStatementParser
from cobolparser.core.registry import StatementParserRegistry
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.call_parser import CallStatementParser
from cobolparser.parsers.statements.display_parser import DisplayStatementParser

L = SourceLocation(1, 1)


def _stream(tokens, with_registry=True):
    stream = TokenStream(tokens)
    if with_registry:
        registry = StatementParserRegistry()
        registry.register(DisplayStatementParser())
        stream._registry = registry
    return stream


class _RecordingContext:
    """Minimal ParseContext stand-in capturing emitted errors."""

    def __init__(self):
        self.errors: list[str] = []

    def error(self, message, location):
        self.errors.append(message)


class TestNotOnException:
    def test_not_on_exception_body_parsed(self):
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "SVC", L),
            Token(TokenType.IDENTIFIER, "NOT", L),
            Token(TokenType.IDENTIFIER, "ON", L),
            Token(TokenType.IDENTIFIER, "EXCEPTION", L),
            Token(TokenType.DISPLAY, "DISPLAY", L),
            Token(TokenType.STRING_LITERAL, "OK", L),
            Token(TokenType.IDENTIFIER, "END-CALL", L),
            Token(TokenType.PERIOD, ".", L),
            Token(TokenType.EOF, "", L),
        ]
        stmt = CallStatementParser().parse(_stream(tokens))
        assert stmt.not_on_exception is not None
        assert len(stmt.not_on_exception) == 1

    def test_not_without_on_exception_breaks(self):
        """A bare NOT not followed by ON EXCEPTION ends the clause loop."""
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.IDENTIFIER, "NOT", L),
            Token(TokenType.IDENTIFIER, "FOO", L),
            Token(TokenType.PERIOD, ".", L),
            Token(TokenType.EOF, "", L),
        ]
        stmt = CallStatementParser().parse(_stream(tokens))
        assert stmt.called_program == "P"
        assert stmt.not_on_exception is None


class TestMissingProgramName:
    def test_stream_ends_after_call_reports_error(self):
        """Stream ending right after CALL reports a missing-program error."""
        ctx = _RecordingContext()
        stream = TokenStream([Token(TokenType.CALL, "CALL", L)])
        stream.context = ctx
        stmt = CallStatementParser().parse(stream, ctx)
        assert stmt.called_program is None
        assert any("program name" in e for e in ctx.errors)


class TestClauseTermination:
    def test_statement_keyword_identifier_terminates_call(self):
        """An identifier that is a statement keyword ends the CALL clause."""
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.IDENTIFIER, "MOVE", L),
            Token(TokenType.EOF, "", L),
        ]
        stmt = CallStatementParser().parse(_stream(tokens))
        assert stmt.called_program == "P"

    def test_statement_keyword_terminates_using_list(self):
        """A statement-keyword identifier ends a USING parameter list."""
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.USING, "USING", L),
            Token(TokenType.IDENTIFIER, "WS-A", L),
            Token(TokenType.IDENTIFIER, "PERFORM", L),
            Token(TokenType.EOF, "", L),
        ]
        stmt = CallStatementParser().parse(_stream(tokens))
        names = [p.name for p in stmt.using_parameters]
        assert names == ["WS-A"]


class TestNestedStatementParsing:
    def test_nested_without_registry(self):
        """ON EXCEPTION body with no registry consumes tokens without crashing."""
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.IDENTIFIER, "ON", L),
            Token(TokenType.IDENTIFIER, "EXCEPTION", L),
            Token(TokenType.IDENTIFIER, "SOMETHING", L),
            Token(TokenType.IDENTIFIER, "END-CALL", L),
            Token(TokenType.EOF, "", L),
        ]
        stmt = CallStatementParser().parse(_stream(tokens, with_registry=False))
        assert stmt.called_program == "P"

    def test_nested_stream_ends_inside_handler(self):
        """ON EXCEPTION body that runs out of tokens terminates cleanly."""
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.IDENTIFIER, "ON", L),
            Token(TokenType.IDENTIFIER, "EXCEPTION", L),
        ]
        stream = TokenStream(tokens)
        stream._registry = StatementParserRegistry()
        stmt = CallStatementParser().parse(stream)
        assert stmt.called_program == "P"

    def test_nested_parser_error_is_swallowed(self):
        """A nested parser raising ParseError advances the stream, no crash."""

        class _Boom(IStatementParser):
            def matches(self, ts):
                tok = ts.peek()
                return bool(tok and tok.value == "BOOM")

            def parse(self, ts, context=None):
                raise ParseError("boom")

        registry = StatementParserRegistry()
        registry.register(_Boom())
        tokens = [
            Token(TokenType.CALL, "CALL", L),
            Token(TokenType.STRING_LITERAL, "P", L),
            Token(TokenType.IDENTIFIER, "ON", L),
            Token(TokenType.IDENTIFIER, "EXCEPTION", L),
            Token(TokenType.IDENTIFIER, "BOOM", L),
            Token(TokenType.IDENTIFIER, "END-CALL", L),
            Token(TokenType.EOF, "", L),
        ]
        stream = TokenStream(tokens)
        stream._registry = registry
        stmt = CallStatementParser().parse(stream)
        assert stmt.called_program == "P"
