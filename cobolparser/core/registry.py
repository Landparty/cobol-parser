"""Statement parser registry for dynamic statement parser dispatch.

This module provides registration and lookup of statement parsers to support:
- Pluggable statement parser architecture
- Reduced parser.py complexity by extracting statement parsing
- Extensible statement type recognition
- First-match strategy for statement parsing

The StatementParserRegistry maintains an ordered list of statement parsers
and searches them using first-match strategy - the first parser whose
matches() method returns True is used to parse the statement.

Dispatch is uncached: every lookup asks the parsers in order. A result
cache keyed on the next few tokens used to sit here, but a parser's
``matches()`` may look further ahead than any fixed key covers, and on the
shared registry the key (which held identifiers) grew with every distinct
statement opening a long-running process saw. Measured over the 571 sample
and NIST programs it saved about 2% of parse time and nothing end to end,
so it was removed rather than widened.
"""

import logging
import warnings

from .interfaces import IStatementParser, ITokenStream

logger = logging.getLogger(__name__)


class StatementParserRegistry:
    """Statement parser registry using IStatementParser interface.

    Provides registration, matching, and dispatch of statement parsers
    to support the extracted statement parser architecture. This is the
    new, preferred registry implementation for IStatementParser instances.

    Uses first-match strategy: The first parser whose matches() method
    returns True is used to parse the statement. Parser order matters.

    The registry holds no per-statement state, so a lookup's result depends
    only on the parser list and the token stream, never on what was parsed
    before (``ProcedureDivisionParser`` shares one registry across parses).

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

    def find_parser(self, token_stream: ITokenStream) -> IStatementParser | None:
        """Find a parser for the current token stream position.

        Uses first-match strategy: Returns the first registered parser
        whose matches() method returns True for the current token stream.

        Args:
            token_stream: The token stream to find a parser for

        Returns:
            First matching parser, or None if no parser matches
        """
        first_token = token_stream.peek()
        if first_token is None:
            return None

        for parser in self._parsers:
            try:
                if parser.matches(token_stream):
                    return parser
            except RecursionError:
                # Nesting too deep to parse (#375). Trying the next parser
                # would drop the statement with only a warning; let it reach
                # the statement loop, which records it as an error.
                raise
            except Exception as e:
                logger.debug(
                    "Parser %s.matches() raised %s: %s",
                    parser.__class__.__name__,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                warnings.warn(
                    f"Parser {parser.__class__.__name__}.matches() raised "
                    f"{type(e).__name__}: {e}",
                    RuntimeWarning,
                    stacklevel=2,
                )
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

    def __len__(self) -> int:
        """Return the number of registered parsers."""
        return len(self._parsers)

    def __repr__(self) -> str:
        """Return string representation of registry."""
        parser_names = [type(p).__name__ for p in self._parsers]
        return f"StatementParserRegistry({len(self._parsers)} parsers: {', '.join(parser_names)})"
