"""Factory for creating and managing division parsers.

This module provides the DivisionParserFactory which is responsible for:
- Registering division parsers
- Determining which parser should handle a given token stream
- Creating division parser instances
- Managing the registry of available parsers
"""

from enum import Enum

from cobolparser.core.exceptions import DivisionNotFoundError
from cobolparser.core.interfaces import IDivisionParser, ITokenStream
from cobolparser.models.ast_base import ASTNode


class DivisionType(Enum):
    """Enumeration of COBOL division types."""

    IDENTIFICATION = "IDENTIFICATION"
    ENVIRONMENT = "ENVIRONMENT"
    DATA = "DATA"
    PROCEDURE = "PROCEDURE"


class DivisionParserFactory:
    """Factory for creating and managing COBOL division parsers.

    Uses the Factory pattern with a registry to:
    - Register division parser classes for each division type
    - Determine which parser should handle a token stream (first-match strategy)
    - Create parser instances on demand
    - Provide centralized control over division parsing

    The factory maintains order of parsers - the first parser that reports
    it can parse (via can_parse()) will be used.
    """

    def __init__(self) -> None:
        """Initialize the division parser factory with empty registry."""
        self._parser_registry: dict[DivisionType, type[IDivisionParser]] = {}
        self._parser_instances: dict[DivisionType, IDivisionParser] = {}
        self._parser_order: list[DivisionType] = []

    def register_parser(
        self,
        division_type: DivisionType,
        parser_class: type[IDivisionParser],
        instantiate: bool = True,
    ) -> None:
        """Register a division parser for a specific division type.

        Args:
            division_type: The division type this parser handles
            parser_class: The parser class (must implement IDivisionParser)
            instantiate: Whether to create an instance immediately

        Raises:
            ValueError: If parser_class doesn't implement IDivisionParser
            TypeError: If parser_class is not a class
        """
        if not isinstance(parser_class, type):
            raise TypeError(f"parser_class must be a class, got {type(parser_class)}")

        if not issubclass(parser_class, IDivisionParser):
            raise ValueError(
                f"{parser_class.__name__} does not implement IDivisionParser"
            )

        self._parser_registry[division_type] = parser_class
        self._parser_order.append(division_type)

        if instantiate:
            self._parser_instances[division_type] = parser_class()

    def get_parser(self, division_type: DivisionType) -> IDivisionParser | None:
        """Get a parser instance for a specific division type.

        Creates the instance if not already created.

        Args:
            division_type: The division type to get parser for

        Returns:
            Parser instance for the division type, or None if not registered
        """
        if division_type not in self._parser_registry:
            return None

        if division_type not in self._parser_instances:
            parser_class = self._parser_registry[division_type]
            self._parser_instances[division_type] = parser_class()

        return self._parser_instances[division_type]

    def find_parser(self, token_stream: ITokenStream) -> IDivisionParser | None:
        """Find a parser that can handle the current token stream.

        Uses first-match strategy: checks each registered parser in order
        and returns the first one that reports it can parse the stream.

        Args:
            token_stream: Token stream to find parser for

        Returns:
            Parser instance that can handle this stream, or None if none found
        """
        if token_stream.is_empty():
            return None

        for division_type in self._parser_order:
            parser = self.get_parser(division_type)
            if parser and parser.can_parse(token_stream):
                return parser

        return None

    def parse_division(self, token_stream: ITokenStream) -> "ASTNode":
        """Parse a division using the appropriate registered parser.

        Finds the correct parser and uses it to parse the division.

        Args:
            token_stream: Token stream to parse

        Returns:
            Parsed division AST node

        Raises:
            DivisionNotFoundError: If no parser can handle the token stream
        """
        if token_stream.is_empty():
            raise DivisionNotFoundError(
                "Cannot parse division: token stream is empty", None
            )

        parser = self.find_parser(token_stream)
        if parser is None:
            first_token = token_stream.peek(0)
            token_value = first_token.value if first_token else "EOF"
            raise DivisionNotFoundError(f"Unknown division type: {token_value}")

        return parser.parse(token_stream)

    def get_registered_divisions(self) -> list[DivisionType]:
        """Get list of registered division types in order.

        Returns:
            List of DivisionType enums in registration order
        """
        return list(self._parser_order)

    def reset_instances(self) -> None:
        """Reset all parser instances (recreate on next access).

        Useful for testing and state management.
        """
        self._parser_instances.clear()

    def clear_registry(self) -> None:
        """Clear the entire parser registry.

        Use with caution - effectively disables all division parsing
        until new parsers are registered.
        """
        self._parser_registry.clear()
        self._parser_instances.clear()
        self._parser_order.clear()


# Global singleton instance (optional, for convenience)
_default_factory: DivisionParserFactory | None = None


def get_default_factory() -> DivisionParserFactory:
    """Get or create the default division parser factory instance.

    Returns:
        Singleton DivisionParserFactory instance
    """
    global _default_factory
    if _default_factory is None:
        _default_factory = DivisionParserFactory()
    return _default_factory


def reset_default_factory() -> None:
    """Reset the default factory instance (for testing).

    This clears the singleton and allows a fresh factory to be created.
    """
    global _default_factory
    _default_factory = None
