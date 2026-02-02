"""Integration tests for statement parser registry with Procedure Division.

Tests edge cases and end-to-end behavior of the registry-based statement
parsing architecture integrated into the Procedure Division parser.
"""

import pytest
from unittest.mock import Mock

from cobolparser.core import StatementParserRegistry
from cobolparser.core.registry import StatementParserRegistry
from cobolparser.parsers.statements import (
    DisplayStatementParser,
    MoveStatementParser,
    IfStatementParser,
    PerformStatementParser,
)
from cobolparser.lexer import CobolLexer, TokenType


class TestRegistryStatementDispatch:
    """Test statement dispatch through registry in realistic scenarios."""
    
    def test_display_statement_dispatch(self):
        """Test that DISPLAY statement finds correct parser through registry."""
        registry = StatementParserRegistry()
        display_parser = DisplayStatementParser()
        registry.register(display_parser)
        
        # Create mock token stream that will match DisplayStatementParser
        mock_stream = Mock()
        mock_token = Mock()
        mock_token.type = TokenType.DISPLAY
        mock_token.value = "DISPLAY"
        mock_stream.peek.return_value = mock_token
        
        # Find parser - should find DisplayStatementParser
        found_parser = registry.find_parser(mock_stream)
        assert found_parser is display_parser
    
    def test_multiple_parsers_first_match(self):
        """Test first-match strategy when multiple parsers match."""
        registry = StatementParserRegistry()
        
        # Create mock parsers
        parser1 = Mock()
        parser1.matches.return_value = False
        
        parser2 = Mock()
        parser2.matches.return_value = True
        
        parser3 = Mock()  # Should not be called
        parser3.matches.return_value = True
        
        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)
        
        mock_stream = Mock()
        
        # Find parser - should return parser2 first
        found = registry.find_parser(mock_stream)
        assert found is parser2
        
        # parser3 should not have been called
        parser3.matches.assert_not_called()
    
    def test_no_matching_parser_returns_none(self):
        """Test behavior when no parser matches statement."""
        registry = StatementParserRegistry()
        
        parser1 = Mock()
        parser1.matches.return_value = False
        
        parser2 = Mock()
        parser2.matches.return_value = False
        
        registry.register(parser1)
        registry.register(parser2)
        
        mock_stream = Mock()
        found = registry.find_parser(mock_stream)
        
        assert found is None
        assert parser1.matches.called
        assert parser2.matches.called
    
    def test_parser_exception_handling(self):
        """Test that parser exceptions don't break registry dispatch."""
        registry = StatementParserRegistry()
        
        # Bad parser that raises exception
        bad_parser = Mock()
        bad_parser.matches.side_effect = RuntimeError("Matching error")
        
        # Good parser
        good_parser = Mock()
        good_parser.matches.return_value = True
        
        registry.register(bad_parser)
        registry.register(good_parser)
        
        mock_stream = Mock()
        
        # Should skip bad parser and return good one
        found = registry.find_parser(mock_stream)
        assert found is good_parser


class TestRegistryEdgeCases:
    """Test edge cases in registry behavior."""
    
    def test_register_same_parser_twice(self):
        """Test registering the same parser instance twice."""
        registry = StatementParserRegistry()
        parser = DisplayStatementParser()
        
        registry.register(parser)
        registry.register(parser)
        
        assert len(registry) == 2
        assert registry.get_all_parsers()[0] is parser
        assert registry.get_all_parsers()[1] is parser
    
    def test_unregister_parser_removes_first_occurrence(self):
        """Test that unregister removes first occurrence if duplicate registered."""
        registry = StatementParserRegistry()
        parser = DisplayStatementParser()
        
        registry.register(parser)
        registry.register(parser)
        assert len(registry) == 2
        
        registry.unregister(parser)
        assert len(registry) == 1
    
    def test_register_with_invalid_position_appends(self):
        """Test that invalid position parameter appends parser."""
        registry = StatementParserRegistry()
        parser1 = DisplayStatementParser()
        parser2 = MoveStatementParser()
        
        registry.register(parser1)
        registry.register(parser2, position=100)  # Out of range
        
        parsers = registry.get_all_parsers()
        assert parsers[-1] is parser2
    
    def test_registry_clear_then_reuse(self):
        """Test that registry can be reused after clear."""
        registry = StatementParserRegistry()
        parser1 = DisplayStatementParser()
        parser2 = MoveStatementParser()
        
        registry.register(parser1)
        registry.clear()
        
        assert len(registry) == 0
        
        registry.register(parser2)
        assert len(registry) == 1
        assert registry.get_all_parsers()[0] is parser2


class TestStatementParserDispatching:
    """Test dispatch behavior with actual (simplified) statement parsers."""
    
    def test_display_parser_matches_display_keyword(self):
        """Test DisplayStatementParser.matches() with DISPLAY token."""
        parser = DisplayStatementParser()
        
        # Create mock token stream with DISPLAY  keyword
        mock_stream = Mock()
        mock_token = Mock()
        mock_token.type = TokenType.DISPLAY
        mock_stream.peek.return_value = mock_token
        
        assert parser.matches(mock_stream) is True
    
    def test_move_parser_matches_move_keyword(self):
        """Test MoveStatementParser.matches() with MOVE token."""
        parser = MoveStatementParser()
        
        mock_stream = Mock()
        mock_token = Mock()
        mock_token.type = TokenType.MOVE
        mock_stream.peek.return_value = mock_token
        
        assert parser.matches(mock_stream) is True
    
    def test_if_parser_matches_if_keyword(self):
        """Test IfStatementParser.matches() with IF token."""
        parser = IfStatementParser()
        
        mock_stream = Mock()
        mock_token = Mock()
        mock_token.type = TokenType.IF
        mock_stream.peek.return_value = mock_token
        
        assert parser.matches(mock_stream) is True
    
    def test_parser_doesnt_match_empty_stream(self):
        """Test that parsers don't match empty token stream."""
        parser = DisplayStatementParser()
        
        mock_stream = Mock()
        mock_stream.peek.return_value = None
        
        # Should return False, not raise exception
        assert parser.matches(mock_stream) is False
    
    def test_parser_handles_stream_exception(self):
        """Test parsers handle exceptions from token stream gracefully."""
        parser = DisplayStatementParser()
        
        mock_stream = Mock()
        mock_stream.peek.side_effect = Exception("Stream error")
        
        # Should return False on exception, not raise
        assert parser.matches(mock_stream) is False


class TestRegistryRepresentation:
    """Test string representation of registry."""
    
    def test_empty_registry_repr(self):
        """Test repr of empty registry."""
        registry = StatementParserRegistry()
        repr_str = repr(registry)
        
        assert "StatementParserRegistry" in repr_str
        assert "0 parsers" in repr_str
    
    def test_populated_registry_repr(self):
        """Test repr with registered parsers."""
        registry = StatementParserRegistry()
        parser1 = DisplayStatementParser()
        parser2 = MoveStatementParser()
        
        registry.register(parser1)
        registry.register(parser2)
        
        repr_str = repr(registry)
        assert "StatementParserRegistry" in repr_str
        assert "2 parsers" in repr_str
        assert "DisplayStatementParser" in repr_str
        assert "MoveStatementParser" in repr_str
    
    def test_registry_len(self):
        """Test len() function on registry."""
        registry = StatementParserRegistry()
        assert len(registry) == 0
        
        registry.register(DisplayStatementParser())
        assert len(registry) == 1
        
        registry.register(MoveStatementParser())
        assert len(registry) == 2


class TestRegistryIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    def test_registry_with_all_core_parsers(self):
        """Test registry with all core statement parsers registered."""
        registry = StatementParserRegistry()
        
        parsers = [
            DisplayStatementParser(),
            MoveStatementParser(),
            IfStatementParser(),
            PerformStatementParser(),
        ]
        
        for parser in parsers:
            registry.register(parser)
        
        assert len(registry) == 4
    
    def test_reregister_parser_at_different_position(self):
        """Test moving parser to different priority position."""
        registry = StatementParserRegistry()
        parser1 = DisplayStatementParser()
        parser2 = MoveStatementParser()
        parser3 = IfStatementParser()
        
        # Initial order: D, M, I
        registry.register(parser1)
        registry.register(parser2)
        registry.register(parser3)
        
        # Remove and re-register at different position
        registry.unregister(parser3)
        registry.register(parser3, position=0)  # Move to front
        
        parsers = registry.get_all_parsers()
        assert parsers[0] is parser3
        assert parsers[1] is parser1
        assert parsers[2] is parser2
