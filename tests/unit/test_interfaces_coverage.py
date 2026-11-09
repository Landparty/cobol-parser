"""Tests for ParseContext and core interface coverage.

Targets uncovered lines in core/interfaces.py (52.94%):
  - ParseContext: current_section, current_division, parse_nested_statement, error
  - ITokenStream: context property getter/setter
"""

from unittest.mock import MagicMock

from cobolparser.core.interfaces import ITokenStream, ParseContext


class TestParseContext:
    """Cover ParseContext delegation and nested parsing."""

    def test_current_section_delegation(self):
        host = MagicMock()
        host.current_section = "WORKING-STORAGE"
        ctx = ParseContext(host)
        assert ctx.current_section == "WORKING-STORAGE"

    def test_current_section_missing_attr(self):
        host = object()  # no current_section attribute
        ctx = ParseContext(host)
        assert ctx.current_section is None

    def test_current_division_delegation(self):
        host = MagicMock()
        host.current_division = "DATA"
        ctx = ParseContext(host)
        assert ctx.current_division == "DATA"

    def test_current_division_missing_attr(self):
        host = object()
        ctx = ParseContext(host)
        assert ctx.current_division is None

    def test_error_with_token_location(self):
        """error() extracts location from token.location."""
        host = MagicMock()
        host.create_error.return_value = "err_obj"
        token = MagicMock()
        token.location = "loc_obj"

        ctx = ParseContext(host)
        ctx.error("bad thing", token)

        host.create_error.assert_called_once_with("bad thing", "loc_obj")
        host.add_error.assert_called_once_with("err_obj")

    def test_error_with_token_line_column(self):
        """error() uses token directly if it has line/column but no location attr."""
        host = MagicMock()
        host.create_error.return_value = "err_obj"
        token = MagicMock(spec=["line", "column"])
        token.line = 5
        token.column = 10

        ctx = ParseContext(host)
        ctx.error("problem", token)

        host.create_error.assert_called_once_with("problem", token)
        host.add_error.assert_called_once_with("err_obj")

    def test_error_no_token(self):
        """error() passes None location when no token provided."""
        host = MagicMock()
        host.create_error.return_value = "err_obj"

        ctx = ParseContext(host)
        ctx.error("generic error")

        host.create_error.assert_called_once_with("generic error", None)

    def test_error_host_without_create_error(self):
        """error() is a no-op when host lacks create_error."""
        host = object()
        ctx = ParseContext(host)
        # Should not raise
        ctx.error("ignored")


class TestITokenStreamContextProperty:
    """Cover the default ITokenStream.context property."""

    def test_context_getter_returns_none(self):
        """Default ITokenStream.context returns None."""

        # We need a concrete subclass to test the default implementation
        class DummyStream(ITokenStream):
            def peek(self, offset=0):
                return None

            def consume(self):
                raise StopIteration

            def expect(self, value):
                raise StopIteration

            def is_empty(self):
                return True

            def skip_whitespace_and_comments(self):
                pass

        stream = DummyStream()
        assert stream.context is None

    def test_context_setter_is_noop(self):
        """Default ITokenStream.context setter does nothing."""

        class DummyStream(ITokenStream):
            def peek(self, offset=0):
                return None

            def consume(self):
                raise StopIteration

            def expect(self, value):
                raise StopIteration

            def is_empty(self):
                return True

            def skip_whitespace_and_comments(self):
                pass

        stream = DummyStream()
        stream.context = "something"  # should not raise
        assert stream.context is None  # still None (default no-op setter)
