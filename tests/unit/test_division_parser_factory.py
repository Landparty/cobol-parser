"""Unit tests for division parser factory and base class.

Tests cover:
- Factory registration and parser lifecycle
- First-match strategy for parser selection
- Error handling for unknown divisions
- Base parser class functionality
"""

import pytest
from typing import Dict, Any

from cobolparser.parsers.divisions import (
    DivisionParserFactory,
    DivisionType,
    BaseDivisionParser,
    get_default_factory,
    reset_default_factory,
)
from cobolparser.core.exceptions import DivisionNotFoundError
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation, ASTNode


class MockDivisionNode(ASTNode):
    """Concrete AST node for testing."""
    
    def __init__(self, start_location: SourceLocation, content: Dict[str, Any]):
        super().__init__("MockDivision", start_location)
        self.content = content
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "node_type": self.node_type,
            "location": self.location.to_dict(),
            "content": self.content,
        }


class MockDivisionParser(BaseDivisionParser):
    """Mock division parser for testing."""
    
    division_name = "MOCK"
    division_keywords = ("TEST",)
    
    def parse_division(self, token_stream):
        """Mock implementation."""
        return {"mock": True}
    
    def _create_ast_node(self, division_token, division_content, start_location):
        """Return a minimal AST node."""
        return MockDivisionNode(start_location, division_content)


class TestDivisionParserFactory:
    """Tests for DivisionParserFactory."""
    
    def test_factory_creation(self):
        """Factory can be created with empty registry."""
        factory = DivisionParserFactory()
        assert len(factory.get_registered_divisions()) == 0
    
    def test_register_parser(self):
        """Parser can be registered."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        assert len(factory.get_registered_divisions()) == 1
        assert DivisionType.IDENTIFICATION in factory.get_registered_divisions()
    
    def test_register_parser_invalid_class(self):
        """Registering non-class raises TypeError."""
        factory = DivisionParserFactory()
        
        with pytest.raises(TypeError):
            factory.register_parser(DivisionType.IDENTIFICATION, "not a class")
    
    def test_register_parser_invalid_interface(self):
        """Registering class without IDivisionParser raises ValueError."""
        class NotAParser:
            pass
        
        factory = DivisionParserFactory()
        
        with pytest.raises(ValueError):
            factory.register_parser(DivisionType.IDENTIFICATION, NotAParser)
    
    def test_get_parser_creates_instance(self):
        """Getting parser creates instance on first access."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        parser1 = factory.get_parser(DivisionType.IDENTIFICATION)
        parser2 = factory.get_parser(DivisionType.IDENTIFICATION)
        
        assert parser1 is not None
        assert parser1 is parser2  # Same instance (cached)
    
    def test_get_parser_unregistered_division(self):
        """Getting unregistered parser returns None."""
        factory = DivisionParserFactory()
        
        parser = factory.get_parser(DivisionType.DATA)
        assert parser is None
    
    def test_find_parser_by_token_stream(self):
        """Factory finds correct parser by token stream."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        # Create token stream starting with MOCK keyword
        tokens = [
            Token(TokenType.IDENTIFIER, "MOCK", SourceLocation(1, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 5)),
        ]
        stream = TokenStream(tokens)
        
        parser = factory.find_parser(stream)
        assert parser is not None
        assert isinstance(parser, MockDivisionParser)
    
    def test_find_parser_no_match(self):
        """Factory returns None when no parser matches."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        # Create token stream with unmatched keyword
        tokens = [
            Token(TokenType.IDENTIFIER, "UNKNOWN", SourceLocation(1, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 8)),
        ]
        stream = TokenStream(tokens)
        
        parser = factory.find_parser(stream)
        assert parser is None
    
    def test_find_parser_empty_stream(self):
        """Factory returns None for empty stream."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        stream = TokenStream([])
        parser = factory.find_parser(stream)
        assert parser is None
    
    def test_parse_division_success(self):
        """Factory can parse division successfully."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        tokens = [
            Token(TokenType.IDENTIFIER, "MOCK", SourceLocation(1, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 5)),
        ]
        stream = TokenStream(tokens)
        
        ast_node = factory.parse_division(stream)
        assert ast_node is not None
        assert ast_node.node_type == "MockDivision"
    
    def test_parse_division_no_parser(self):
        """Parsing with no matching parser raises DivisionNotFoundError."""
        factory = DivisionParserFactory()
        
        tokens = [
            Token(TokenType.IDENTIFIER, "UNKNOWN", SourceLocation(1, 1)),
        ]
        stream = TokenStream(tokens)
        
        with pytest.raises(DivisionNotFoundError):
            factory.parse_division(stream)
    
    def test_parse_division_empty_stream(self):
        """Parsing empty stream raises DivisionNotFoundError."""
        factory = DivisionParserFactory()
        stream = TokenStream([])
        
        with pytest.raises(DivisionNotFoundError):
            factory.parse_division(stream)
    
    def test_reset_instances(self):
        """Resetting instances clears cached parser instances."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        
        parser1 = factory.get_parser(DivisionType.IDENTIFICATION)
        factory.reset_instances()
        parser2 = factory.get_parser(DivisionType.IDENTIFICATION)
        
        assert parser1 is not parser2  # Different instances after reset
    
    def test_clear_registry(self):
        """Clearing registry removes all parsers."""
        factory = DivisionParserFactory()
        factory.register_parser(DivisionType.IDENTIFICATION, MockDivisionParser)
        factory.register_parser(DivisionType.DATA, MockDivisionParser)
        
        assert len(factory.get_registered_divisions()) == 2
        
        factory.clear_registry()
        
        assert len(factory.get_registered_divisions()) == 0


class TestBaseDivisionParser:
    """Tests for BaseDivisionParser."""
    
    def test_parser_requires_division_name(self):
        """Parser without division_name raises ValueError."""
        class BadParser(BaseDivisionParser):
            division_name = None
            
            def parse_division(self, token_stream):
                return {}
            
            def _create_ast_node(self, division_token, division_content, start_location):
                return None
        
        with pytest.raises(ValueError):
            BadParser()
    
    def test_can_parse_checks_division_keyword(self):
        """can_parse() checks if token matches division keyword."""
        parser = MockDivisionParser()
        
        # Stream starting with MOCK keyword
        tokens = [
            Token(TokenType.IDENTIFIER, "MOCK", SourceLocation(1, 1)),
        ]
        stream = TokenStream(tokens)
        
        assert parser.can_parse(stream) is True
    
    def test_can_parse_checks_alternative_keyword(self):
        """can_parse() accepts alternative keywords."""
        parser = MockDivisionParser()
        
        # Stream starting with TEST keyword (alternative)
        tokens = [
            Token(TokenType.IDENTIFIER, "TEST", SourceLocation(1, 1)),
        ]
        stream = TokenStream(tokens)
        
        assert parser.can_parse(stream) is True
    
    def test_can_parse_case_insensitive(self):
        """can_parse() is case-insensitive."""
        parser = MockDivisionParser()
        
        # Stream with lowercase keyword
        tokens = [
            Token(TokenType.IDENTIFIER, "mock", SourceLocation(1, 1)),
        ]
        stream = TokenStream(tokens)
        
        assert parser.can_parse(stream) is True
    
    def test_can_parse_returns_false_for_wrong_keyword(self):
        """can_parse() returns False for non-matching keyword."""
        parser = MockDivisionParser()
        
        tokens = [
            Token(TokenType.IDENTIFIER, "OTHER", SourceLocation(1, 1)),
        ]
        stream = TokenStream(tokens)
        
        assert parser.can_parse(stream) is False
    
    def test_can_parse_empty_stream(self):
        """can_parse() returns False for empty stream."""
        parser = MockDivisionParser()
        stream = TokenStream([])
        
        assert parser.can_parse(stream) is False
    
    def test_parse_consumes_division_keyword(self):
        """parse() consumes the division keyword token."""
        parser = MockDivisionParser()
        
        tokens = [
            Token(TokenType.IDENTIFIER, "MOCK", SourceLocation(1, 1)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 5)),
        ]
        stream = TokenStream(tokens)
        
        parser.parse(stream)
        
        # After parsing, stream should be empty or at next content
        assert stream.is_empty() or stream.peek(0).value != "MOCK"
    
    def test_parse_handles_optional_division_keyword(self):
        """parse() handles optional 'DIVISION' keyword after division name."""
        parser = MockDivisionParser()
        
        tokens = [
            Token(TokenType.IDENTIFIER, "MOCK", SourceLocation(1, 1)),
            Token(TokenType.IDENTIFIER, "DIVISION", SourceLocation(1, 6)),
            Token(TokenType.PERIOD, ".", SourceLocation(1, 15)),
        ]
        stream = TokenStream(tokens)
        
        parser.parse(stream)
        
        # Should successfully parse
        assert stream.is_empty()


class TestDefaultFactory:
    """Tests for default factory singleton."""
    
    def test_get_default_factory_returns_singleton(self):
        """get_default_factory() returns same instance."""
        reset_default_factory()
        
        factory1 = get_default_factory()
        factory2 = get_default_factory()
        
        assert factory1 is factory2
    
    def test_reset_default_factory_creates_new_instance(self):
        """reset_default_factory() creates new instance."""
        factory1 = get_default_factory()
        reset_default_factory()
        factory2 = get_default_factory()
        
        assert factory1 is not factory2
