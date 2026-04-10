"""Statement parser registry for dynamic statement parser dispatch.

This module provides registration and lookup of statement parsers to support:
- Pluggable statement parser architecture
- Reduced parser.py complexity by extracting statement parsing
- Extensible statement type recognition
- First-match strategy for statement parsing

The StatementParserRegistry maintains an ordered list of statement parsers
and searches them using first-match strategy - the first parser whose
matches() method returns True is used to parse the statement.

Dispatch is accelerated by a (token_type, token_value) result cache that is
invalidated whenever parsers are registered or unregistered.
"""

from typing import Optional

from .interfaces import IStatementParser, ITokenStream


class StatementParserRegistry:
    """Statement parser registry using IStatementParser interface.

    Provides registration, matching, and dispatch of statement parsers
    to support the extracted statement parser architecture. This is the
    new, preferred registry implementation for IStatementParser instances.

    Uses first-match strategy: The first parser whose matches() method
    returns True is used to parse the statement. Parser order matters.

    Dispatch is accelerated by a result cache keyed on the first token's
    (type, normalized_value) pair.  The cache is invalidated automatically
    on every register() / unregister() / clear() call, so it is always
    consistent with the current parser list.

    Example:
        registry = StatementParserRegistry()
        registry.register(DisplayStatementParser())
        registry.register(MoveStatementParser())

        # Find a parser for current token stream
        parser = registry.find_parser(token_stream)
        if parser:
            ast_node = parser.parse(token_stream)
    """

    def __init__(self) -> None:
        """Initialize the statement parser registry."""
        self._parsers: list[IStatementParser] = []
        # Cache: (token_type, token_value_upper | None) -> matched parser | None
        self._dispatch_cache: dict[tuple, Optional[IStatementParser]] = {}

    def register(self, parser: IStatementParser, position: int | None = None) -> None:
        """Register a statement parser.

        Parsers are checked in registration order during find_parser().
        First parser to match (matches() returns True) is used.

        Args:
            parser: Statement parser implementing IStatementParser
            position: Optional position to insert parser (default: append to end)

        Raises:
            TypeError: If parser doesn't implement IStatementParser
        """
        if not hasattr(parser, "parse") or not hasattr(parser, "matches"):
            raise TypeError("Parser must implement IStatementParser interface")

        if position is not None:
            self._parsers.insert(position, parser)
        else:
            self._parsers.append(parser)
        self._dispatch_cache.clear()

    def find_parser(self, token_stream: ITokenStream) -> IStatementParser | None:
        """Find a parser for the current token stream position.

        Uses first-match strategy: Returns the first registered parser
        whose matches() method returns True for the current token stream.
        Results are cached by the first token's (type, value) pair to
        avoid redundant linear scans on hot paths.

        Args:
            token_stream: The token stream to find a parser for

        Returns:
            First matching parser, or None if no parser matches
        """
        first_token = token_stream.peek()
        if first_token is None:
            return None

        # Build cache key from the first token
        token_val = first_token.value.upper() if first_token.value else None
        cache_key = (first_token.type, token_val)

        if cache_key in self._dispatch_cache:
            return self._dispatch_cache[cache_key]

        matched: IStatementParser | None = None
        for parser in self._parsers:
            try:
                if parser.matches(token_stream):
                    matched = parser
                    break
            except Exception as e:
                import warnings

                warnings.warn(
                    f"Parser {parser.__class__.__name__}.matches() raised "
                    f"{type(e).__name__}: {e}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

        self._dispatch_cache[cache_key] = matched
        return matched

    def unregister(self, parser: IStatementParser) -> bool:
        """Remove a registered parser.

        Args:
            parser: The parser to remove

        Returns:
            True if parser was removed, False if not found
        """
        try:
            self._parsers.remove(parser)
            self._dispatch_cache.clear()
            return True
        except ValueError:
            return False

    def get_all_parsers(self) -> list[IStatementParser]:
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
        self._dispatch_cache.clear()

    def __len__(self) -> int:
        """Return the number of registered parsers."""
        return len(self._parsers)

    def __repr__(self) -> str:
        """Return string representation of registry."""
        parser_names = [type(p).__name__ for p in self._parsers]
        return f"StatementParserRegistry({len(self._parsers)} parsers: {', '.join(parser_names)})"
