"""Unit tests for StatementParserRegistry.

Tests cover:
- Parser registration (add, insert, clear)
- First-match dispatch strategy
- Error handling
- Edge cases (empty registry, no match, multiple matches)
"""

from unittest.mock import Mock

import pytest

from cobolparser.core import ITokenStream, StatementParserRegistry


class MockStatementParser:
    """Mock statement parser for testing."""

    def __init__(self, name: str, should_match: bool = False, parse_result=None):
        """Initialize mock parser.

        Args:
            name: Name for this parser
            should_match: Whether matches() should return True
            parse_result: What parse() should return
        """
        self.name = name
        self.should_match = should_match
        self.parse_result = parse_result or Mock()
        self.matches_called = False
        self.parse_called = False

    def matches(self, token_stream: ITokenStream) -> bool:
        """Mock matches method."""
        self.matches_called = True
        return self.should_match

    def parse(self, token_stream: ITokenStream) -> object:
        """Mock parse method."""
        self.parse_called = True
        return self.parse_result

    def __repr__(self) -> str:
        return f"MockParser({self.name})"


class TestStatementParserRegistryInitialization:
    """Test StatementParserRegistry initialization."""

    def test_empty_registry_on_creation(self):
        """Test that a new registry is empty."""
        registry = StatementParserRegistry()
        assert len(registry) == 0
        assert registry.get_all_parsers() == []

    def test_registry_str_representation(self):
        """Test string representation of empty registry."""
        registry = StatementParserRegistry()
        repr_str = repr(registry)
        assert "StatementParserRegistry" in repr_str
        assert "0 parsers" in repr_str


class TestStatementParserRegistryRegistration:
    """Test parser registration functionality."""

    def test_register_single_parser(self):
        """Test registering a single parser."""
        registry = StatementParserRegistry()
        parser = MockStatementParser("display_parser")

        registry.register(parser)

        assert len(registry) == 1
        assert parser in registry.get_all_parsers()

    def test_register_multiple_parsers(self):
        """Test registering multiple parsers."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")
        parser3 = MockStatementParser("parser3")

        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)

        assert len(registry) == 3
        parsers = registry.get_all_parsers()
        assert parser1 in parsers
        assert parser2 in parsers
        assert parser3 in parsers

    def test_register_preserves_order(self):
        """Test that parser order is preserved on registration."""
        registry = StatementParserRegistry()
        parsers = [MockStatementParser(f"parser{i}") for i in range(5)]

        for parser in parsers:
            registry.register(parser)

        registered = registry.get_all_parsers()
        assert registered == parsers

    def test_register_with_position(self):
        """Test inserting parser at specific position."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")
        parser3 = MockStatementParser("parser3")

        registry.register(parser1)
        registry.register(parser3)
        registry.register(parser2, position=1)  # Insert between 1 and 3

        registered = registry.get_all_parsers()
        assert registered == [parser1, parser2, parser3]

    def test_register_invalid_parser_raises_type_error(self):
        """Test that registering invalid parser raises TypeError."""
        registry = StatementParserRegistry()

        # Create object without spec - no methods at all
        class InvalidParser:
            pass

        invalid_parser = InvalidParser()

        with pytest.raises(TypeError, match="implement IStatementParser"):
            registry.register(invalid_parser)

    def test_register_parser_without_matches_raises_type_error(self):
        """Test that parser must have parse and matches methods."""
        registry = StatementParserRegistry()

        # Object with only parse method, missing matches
        class PartialParser:
            def parse(self, stream):
                pass

        partial_parser = PartialParser()

        with pytest.raises(TypeError):
            registry.register(partial_parser)


class TestStatementParserRegistryDispatch:
    """Test parser finding and dispatch (first-match strategy)."""

    def test_find_parser_single_match(self):
        """Test finding parser when only one matches."""
        registry = StatementParserRegistry()
        parser = MockStatementParser("display", should_match=True)
        registry.register(parser)

        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        assert found is parser
        assert parser.matches_called

    def test_find_parser_no_match_returns_none(self):
        """Test find_parser returns None when no parser matches."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1", should_match=False)
        parser2 = MockStatementParser("parser2", should_match=False)
        registry.register(parser1)
        registry.register(parser2)

        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        assert found is None
        assert parser1.matches_called
        assert parser2.matches_called

    def test_find_parser_first_match_strategy(self):
        """Test that first matching parser is returned (first-match strategy)."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1", should_match=True)
        parser2 = MockStatementParser("parser2", should_match=True)
        parser3 = MockStatementParser("parser3", should_match=True)

        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)

        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        # First-match strategy: should return parser1
        assert found is parser1
        assert parser1.matches_called
        # Parser2 and parser3 should not be called due to first-match
        assert not parser2.matches_called
        assert not parser3.matches_called

    def test_find_parser_skips_non_matching_parsers(self):
        """Test that non-matching parsers are skipped until match found."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1", should_match=False)
        parser2 = MockStatementParser("parser2", should_match=False)
        parser3 = MockStatementParser("parser3", should_match=True)

        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)

        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        assert found is parser3
        assert parser1.matches_called
        assert parser2.matches_called
        assert parser3.matches_called

    def test_find_parser_empty_registry(self):
        """Test finding parser in empty registry returns None."""
        registry = StatementParserRegistry()
        mock_stream = Mock(spec=ITokenStream)

        found = registry.find_parser(mock_stream)

        assert found is None

    def test_find_parser_handles_exception_in_matches(self):
        """Test that exceptions in matches() are handled gracefully."""
        registry = StatementParserRegistry()

        # Parser that raises exception in matches()
        bad_parser = Mock()
        bad_parser.matches = Mock(side_effect=Exception("Error in matches"))
        bad_parser.parse = Mock()

        # Good parser that matches
        good_parser = MockStatementParser("good", should_match=True)

        registry.register(bad_parser)
        registry.register(good_parser)

        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        # Should skip the bad parser and return the good one
        assert found is good_parser


class TestStatementParserRegistryUnregister:
    """Test parser unregistration."""

    def test_unregister_existing_parser(self):
        """Test unregistering an existing parser."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")

        registry.register(parser1)
        registry.register(parser2)
        assert len(registry) == 2

        result = registry.unregister(parser1)

        assert result is True
        assert len(registry) == 1
        assert parser1 not in registry.get_all_parsers()
        assert parser2 in registry.get_all_parsers()

    def test_unregister_non_existing_parser(self):
        """Test unregistering a parser that's not in registry."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")

        registry.register(parser1)

        result = registry.unregister(parser2)

        assert result is False
        assert len(registry) == 1


class TestStatementParserRegistryClear:
    """Test clearing the registry."""

    def test_clear_removes_all_parsers(self):
        """Test that clear removes all parsers."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")
        parser3 = MockStatementParser("parser3")

        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)
        assert len(registry) == 3

        registry.clear()

        assert len(registry) == 0
        assert registry.get_all_parsers() == []

    def test_clear_empty_registry(self):
        """Test clearing an already empty registry."""
        registry = StatementParserRegistry()

        registry.clear()

        assert len(registry) == 0


class TestStatementParserRegistryIntrospection:
    """Test registry introspection methods."""

    def test_len_returns_parser_count(self):
        """Test that len() returns parser count."""
        registry = StatementParserRegistry()
        assert len(registry) == 0

        for i in range(5):
            registry.register(MockStatementParser(f"parser{i}"))

        assert len(registry) == 5

    def test_get_all_parsers_returns_copy(self):
        """Test that get_all_parsers returns independent list."""
        registry = StatementParserRegistry()
        parser1 = MockStatementParser("parser1")
        parser2 = MockStatementParser("parser2")

        registry.register(parser1)
        registry.register(parser2)

        parsers = registry.get_all_parsers()
        parsers.append(MockStatementParser("extra"))  # Modify returned list

        # Registry should still have only 2 parsers
        assert len(registry) == 2
        assert len(registry.get_all_parsers()) == 2


class TestStatementParserRegistryIntegration:
    """Integration tests for realistic usage patterns."""

    def test_register_and_dispatch_flow(self):
        """Test realistic register-then-dispatch workflow."""
        registry = StatementParserRegistry()

        # Register parsers in priority order
        display_parser = MockStatementParser("DISPLAY", should_match=False)
        move_parser = MockStatementParser("MOVE", should_match=False)
        perform_parser = MockStatementParser("PERFORM", should_match=True)

        registry.register(display_parser)
        registry.register(move_parser)
        registry.register(perform_parser)

        # Dispatch
        mock_stream = Mock(spec=ITokenStream)
        found = registry.find_parser(mock_stream)

        assert found is perform_parser
        assert not display_parser.parse_called
        assert not move_parser.parse_called
        assert not perform_parser.parse_called

        # Parse
        found.parse(mock_stream)
        assert perform_parser.parse_called

    def test_multiple_dispatch_calls(self):
        """Every lookup consults matches(): the registry keeps no result cache.

        A cached result keyed on the next few tokens made dispatch depend on
        what was parsed before whenever a parser looked further ahead than
        the key, so each call must ask the parsers afresh.
        """
        registry = StatementParserRegistry()
        parser = MockStatementParser("test", should_match=True)
        registry.register(parser)

        tok0 = Mock()
        tok0.type = "MOVE_TYPE"
        tok0.value = "MOVE"
        tok1 = Mock()
        tok1.type = "ID_TYPE"
        tok1.value = "SRC"
        mock_stream = Mock(spec=ITokenStream)
        mock_stream.peek.side_effect = lambda offset=0: tok0 if offset == 0 else tok1

        for _ in range(2):
            parser.matches_called = False
            assert registry.find_parser(mock_stream) is parser
            assert parser.matches_called, "matches() must be called on every lookup"

    def test_dispatch_does_not_depend_on_earlier_lookups(self):
        """Regression: a parser that looks past the third token.

        The old cache key covered the first token, the second and the first
        meaningful one after it. Two streams that agree on those but differ
        at peek(3) got whichever parser the first lookup had cached.
        """

        class DeepLookaheadParser:
            def __init__(self, word: str):
                self.word = word

            def matches(self, stream: ITokenStream) -> bool:
                t3 = stream.peek(3)
                return t3 is not None and getattr(t3, "value", "") == self.word

            def parse(self, stream, context=None):
                return Mock()

        def make_stream(fourth: str) -> Mock:
            toks = []
            for value in ("VERB", "A", "B", fourth):
                tok = Mock()
                tok.type = "ID_TYPE"
                tok.value = value
                toks.append(tok)
            stream = Mock(spec=ITokenStream)
            stream.peek.side_effect = lambda offset=0: (
                toks[offset] if offset < len(toks) else None
            )
            return stream

        first = DeepLookaheadParser("X")
        second = DeepLookaheadParser("Y")
        registry = StatementParserRegistry()
        registry.register(first)
        registry.register(second)

        assert registry.find_parser(make_stream("X")) is first
        assert registry.find_parser(make_stream("Y")) is second
        assert registry.find_parser(make_stream("Z")) is None

    def test_recursion_error_in_matches_propagates(self):
        """A RecursionError is not a "does not match" (#375).

        Swallowing it fell through to the next parser, so a statement nested
        too deeply was dropped with only a warning.
        """

        class TooDeep:
            def matches(self, stream):
                raise RecursionError("maximum recursion depth exceeded")

            def parse(self, stream, context=None):
                return Mock()

        fallback = MockStatementParser("fallback", should_match=True)
        registry = StatementParserRegistry()
        registry.register(TooDeep())
        registry.register(fallback)

        with pytest.raises(RecursionError):
            registry.find_parser(Mock(spec=ITokenStream))
        assert not fallback.matches_called

    def test_exec_sql_vs_exec_cics_dispatch(self):
        """Regression: EXEC SQL and EXEC CICS share the same first token.

        The two parsers must never be confused, whichever was looked up first.
        """

        class SecondTokenParser:
            """Matches only when peek(1).value equals a given keyword."""

            def __init__(self, keyword: str):
                self.keyword = keyword
                self.matches_called = False

            def matches(self, stream: ITokenStream) -> bool:
                self.matches_called = True
                t1 = stream.peek(1)
                return t1 is not None and getattr(t1, "value", "") == self.keyword

            def parse(self, stream, context=None):
                return Mock()

        sql_parser = SecondTokenParser("SQL")
        cics_parser = SecondTokenParser("CICS")

        registry = StatementParserRegistry()
        registry.register(sql_parser)
        registry.register(cics_parser)

        def make_exec_stream(second_kw: str) -> Mock:
            exec_tok = Mock()
            exec_tok.type = "EXEC_TYPE"
            exec_tok.value = "EXEC"
            second_tok = Mock()
            second_tok.type = "ID_TYPE"
            second_tok.value = second_kw
            stream = Mock(spec=ITokenStream)
            stream.peek.side_effect = lambda offset=0: (
                exec_tok if offset == 0 else second_tok if offset == 1 else None
            )
            return stream

        sql_stream = make_exec_stream("SQL")
        cics_stream = make_exec_stream("CICS")

        # First lookup — EXEC SQL
        found = registry.find_parser(sql_stream)
        assert found is sql_parser

        # Second lookup — EXEC CICS must not return the SQL parser
        found = registry.find_parser(cics_stream)
        assert found is cics_parser

        # Repeated lookups keep returning the correct parsers
        assert registry.find_parser(sql_stream) is sql_parser
        assert registry.find_parser(cics_stream) is cics_parser
