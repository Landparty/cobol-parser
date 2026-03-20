"""Statement parser registry for dynamic statement parser dispatch.

This module provides registration and lookup of statement parsers to support:
- Pluggable statement parser architecture
- Reduced parser.py complexity by extracting statement parsing
- Extensible statement type recognition
- First-match strategy for statement parsing

The StatementParserRegistry maintains an ordered list of statement parsers
and searches them using first-match strategy - the first parser whose
matches() method returns True is used to parse the statement.
"""

from typing import Dict, Type, Optional, List, Union
from .interfaces import StatementParser, IStatementParser, ITokenStream
from ..lexer import TokenType


class StatementRegistry:
    """Registry that maps tokens to their corresponding parsers.

    Uses a token-type dispatch map for O(1) lookup of candidate parsers,
    falling back to linear scan only for parsers without a declared token type.
    """

    def __init__(self):
        """Initialize the statement registry."""
        self._parsers: List[StatementParser] = []
        self._token_map: Dict[TokenType, List[StatementParser]] = {}
        self._untyped_parsers: List[StatementParser] = []

    def register(self, parser: StatementParser) -> None:
        """Register a statement parser.

        If the parser has a `token_type` attribute, it is indexed for fast
        dispatch. Otherwise it goes into the fallback linear scan list.

        Args:
            parser: The parser to register (must implement can_parse())
        """
        self._parsers.append(parser)

        # Build token dispatch map from parser's token_type attribute
        token_type = getattr(parser, 'token_type', None)
        if token_type is not None:
            if token_type not in self._token_map:
                self._token_map[token_type] = []
            self._token_map[token_type].append(parser)
        else:
            self._untyped_parsers.append(parser)

    def get_parser(self, stream) -> Optional[StatementParser]:
        """Get a parser for the current token stream position.

        First tries O(1) token-type dispatch, then falls back to
        linear scan of untyped parsers.

        Args:
            stream: TokenStream to find parser for

        Returns:
            First matching parser or None if no parser matches
        """
        # Fast path: try token-type dispatch
        token = stream.peek() if stream and not stream.is_empty() else None
        if token is not None and token.type in self._token_map:
            for parser in self._token_map[token.type]:
                if hasattr(parser, 'can_parse') and parser.can_parse(stream):
                    return parser

        # Slow path: check untyped parsers
        for parser in self._untyped_parsers:
            if hasattr(parser, 'can_parse') and parser.can_parse(stream):
                return parser

        # Final fallback: check all parsers (handles text-match parsers)
        if token is not None and token.type not in self._token_map:
            for parser in self._parsers:
                if hasattr(parser, 'can_parse') and parser.can_parse(stream):
                    return parser

        return None


class StatementParserRegistry:
    """Statement parser registry using IStatementParser interface.
    
    Provides registration, matching, and dispatch of statement parsers
    to support the extracted statement parser architecture. This is the
    new, preferred registry implementation for IStatementParser instances.
    
    Uses first-match strategy: The first parser whose matches() method
    returns True is used to parse the statement. Parser order matters.
    
    Example:
        registry = StatementParserRegistry()
        registry.register(DisplayStatementParser())
        registry.register(MoveStatementParser())
        
        # Find a parser for current token stream
        parser = registry.find_parser(token_stream)
        if parser:
            ast_node = parser.parse(token_stream)
    """
    
    def __init__(self):
        """Initialize the statement parser registry."""
        self._parsers: List[IStatementParser] = []
    
    def register(self, parser: IStatementParser, position: Optional[int] = None) -> None:
        """Register a statement parser.
        
        Parsers are checked in registration order during find_parser().
        First parser to match (matches() returns True) is used.
        
        Args:
            parser: Statement parser implementing IStatementParser
            position: Optional position to insert parser (default: append to end)
            
        Raises:
            TypeError: If parser doesn't implement IStatementParser
        """
        if not hasattr(parser, 'parse') or not hasattr(parser, 'matches'):
            raise TypeError(f"Parser must implement IStatementParser interface")
        
        if position is not None:
            self._parsers.insert(position, parser)
        else:
            self._parsers.append(parser)
    
    def find_parser(self, token_stream: ITokenStream) -> Optional[IStatementParser]:
        """Find a parser for the current token stream position.
        
        Uses first-match strategy: Returns the first registered parser
        whose matches() method returns True for the current token stream.
        
        Args:
            token_stream: The token stream to find a parser for
            
        Returns:
            First matching parser, or None if no parser matches
        """
        for parser in self._parsers:
            try:
                if parser.matches(token_stream):
                    return parser
            except Exception:
                # Parser matching failed - continue to next parser
                continue
        return None
    
    def unregister(self, parser: IStatementParser) -> bool:
        """Remove a registered parser.
        
        Args:
            parser: The parser to remove
            
        Returns:
            True if parser was removed, False if not found
        """
        try:
            self._parsers.remove(parser)
            return True
        except ValueError:
            return False
    
    def get_all_parsers(self) -> List[IStatementParser]:
        """Get all registered parsers in order.
        
        Warning: Use only for debugging/introspection. For actual
        parsing, use find_parser() instead.
        
        Returns:
            List of all registered parsers in order
        """
        return list(self._parsers)
    
    def clear(self) -> None:
        """Clear all registered parsers.
        
        Warning: This removes all parsers from the registry. Use with care.
        """
        self._parsers.clear()
    
    def __len__(self) -> int:
        """Return the number of registered parsers."""
        return len(self._parsers)
    
    def __repr__(self) -> str:
        """Return string representation of registry."""
        parser_names = [type(p).__name__ for p in self._parsers]
        return f"StatementParserRegistry({len(self._parsers)} parsers: {', '.join(parser_names)})"
