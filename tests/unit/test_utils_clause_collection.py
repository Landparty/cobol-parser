"""Tests for _utils.py clause collection and nested statement dispatch.

Targets uncovered lines in parsers/statements/_utils.py (80.95%):
  - collect_clause_stmts boundary detection (lines 97-114)
  - report_parse_error with active context (line 136-137)
  - try_parse_nested_statement dispatch (lines 155-174)
"""

from unittest.mock import MagicMock

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements._utils import (
    collect_clause_stmts,
    get_parse_context,
    report_parse_error,
    skip_whitespace,
    try_parse_nested_statement,
)


def _make_token(ttype, value, line=1, col=1):
    return Token(ttype, value, SourceLocation(line, col))


class TestCollectClauseStmts:
    """Cover collect_clause_stmts boundary detection (lines 97-114)."""

    def test_stops_at_period(self):
        """Stops collecting at PERIOD token."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "DISPLAY"),
            _make_token(TokenType.STRING_LITERAL, "HELLO"),
            _make_token(TokenType.PERIOD, "."),
        ]
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []
        # Should have consumed tokens up to but not including period
        token = stream.peek()
        assert token is not None
        assert token.type == TokenType.PERIOD

    def test_stops_at_not(self):
        """Stops collecting at NOT token."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "DISPLAY"),
            _make_token(TokenType.NOT, "NOT"),
            _make_token(TokenType.IDENTIFIER, "MORE"),
        ]
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []
        token = stream.peek()
        assert token is not None
        assert token.type == TokenType.NOT

    def test_stops_at_invalid(self):
        """Stops collecting at INVALID token."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "DISPLAY"),
            _make_token(TokenType.INVALID, "INVALID"),
        ]
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []
        token = stream.peek()
        assert token is not None
        assert token.type == TokenType.INVALID

    def test_stops_at_custom_stop_token(self):
        """Stops collecting at stop_at identifier."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "DISPLAY"),
            _make_token(TokenType.STRING_LITERAL, "MSG"),
            _make_token(TokenType.IDENTIFIER, "END-READ"),
        ]
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []
        token = stream.peek()
        assert token is not None
        assert token.value == "END-READ"

    def test_empty_stream(self):
        """Empty stream returns empty list."""
        tokens = []
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []

    def test_consumes_all_non_boundary_tokens(self):
        """Consumes tokens that aren't boundaries until stream is exhausted."""
        tokens = [
            _make_token(TokenType.IDENTIFIER, "DISPLAY"),
            _make_token(TokenType.STRING_LITERAL, "HELLO"),
            _make_token(TokenType.IDENTIFIER, "WORLD"),
        ]
        stream = TokenStream(tokens)
        result = collect_clause_stmts(stream, {"END-READ"})
        assert result == []
        assert stream.is_empty()


class TestSkipWhitespace:
    """Cover skip_whitespace function."""

    def test_skips_newlines(self):
        tokens = [
            _make_token(TokenType.NEWLINE, "\n"),
            _make_token(TokenType.NEWLINE, "\n"),
            _make_token(TokenType.IDENTIFIER, "HELLO"),
        ]
        stream = TokenStream(tokens)
        skip_whitespace(stream)
        token = stream.peek()
        assert token is not None
        assert token.value == "HELLO"

    def test_skips_continuation(self):
        tokens = [
            _make_token(TokenType.CONTINUATION, "-"),
            _make_token(TokenType.IDENTIFIER, "HELLO"),
        ]
        stream = TokenStream(tokens)
        skip_whitespace(stream)
        token = stream.peek()
        assert token is not None
        assert token.value == "HELLO"

    def test_no_whitespace(self):
        tokens = [_make_token(TokenType.IDENTIFIER, "HELLO")]
        stream = TokenStream(tokens)
        skip_whitespace(stream)
        token = stream.peek()
        assert token.value == "HELLO"


class TestReportParseError:
    """Cover report_parse_error with and without context (line 136-137)."""

    def test_report_with_context(self):
        """Calls context.error() when context is available."""
        mock_context = MagicMock()
        loc = SourceLocation(1, 1)
        report_parse_error(mock_context, "test error", loc)
        mock_context.error.assert_called_once_with("test error", loc)

    def test_report_without_context(self):
        """Does nothing when context is None."""
        report_parse_error(None, "test error", SourceLocation(1, 1))
        # Should not raise


class TestGetParseContext:
    """Cover get_parse_context function."""

    def test_returns_context_attr(self):
        stream = MagicMock()
        stream.context = "ctx"
        result = get_parse_context(stream)
        assert result == "ctx"

    def test_returns_underscore_context(self):
        stream = MagicMock()
        stream.context = None
        stream._context = "fallback"
        result = get_parse_context(stream)
        assert result == "fallback"

    def test_returns_none(self):
        stream = MagicMock()
        stream.context = None
        # MagicMock will auto-create _context, so delete it
        del stream._context
        result = get_parse_context(stream)
        assert result is None


class TestTryParseNestedStatement:
    """Cover try_parse_nested_statement dispatch (lines 155-174)."""

    def test_no_registry_returns_none(self):
        """Returns None when stream has no registry (line 161)."""
        stream = MagicMock()
        stream._registry = None
        stream.registry = None
        stream.get_registry = None
        result = try_parse_nested_statement(stream)
        assert result is None

    def test_registry_via_get_registry(self):
        """Finds registry via get_registry() method (line 159)."""
        mock_parser = MagicMock()
        mock_parser.parse = MagicMock(return_value="parsed")

        mock_registry = MagicMock()
        mock_registry.find_parser = MagicMock(return_value=mock_parser)

        stream = MagicMock()
        stream._registry = None
        stream.registry = None
        stream.get_registry = MagicMock(return_value=mock_registry)

        result = try_parse_nested_statement(stream)
        assert result == "parsed"

    def test_registry_find_returns_none(self):
        """Returns None when registry finds no parser (line 169)."""
        mock_registry = MagicMock()
        mock_registry.find_parser = MagicMock(return_value=None)

        stream = MagicMock()
        stream._registry = mock_registry
        result = try_parse_nested_statement(stream)
        assert result is None

    def test_exclude_self(self):
        """Returns None when found parser is exclude_self (line 170-171)."""
        myself = MagicMock()
        mock_registry = MagicMock()
        mock_registry.find_parser = MagicMock(return_value=myself)

        stream = MagicMock()
        stream._registry = mock_registry
        result = try_parse_nested_statement(stream, exclude_self=myself)
        assert result is None

    def test_exception_returns_none(self):
        """Returns None when exception occurs (line 173-174)."""
        stream = MagicMock()
        stream._registry = MagicMock()
        stream._registry.find_parser = MagicMock(side_effect=RuntimeError("fail"))
        result = try_parse_nested_statement(stream)
        assert result is None

    def test_find_parser_not_callable(self):
        """Returns None when find_parser is not callable (line 164-165)."""
        mock_registry = MagicMock()
        mock_registry.find_parser = "not_callable"

        stream = MagicMock()
        stream._registry = mock_registry
        result = try_parse_nested_statement(stream)
        assert result is None
