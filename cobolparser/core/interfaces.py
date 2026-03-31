"""Abstract base classes and interfaces for COBOL parser components."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, Protocol, Any, Union

if TYPE_CHECKING:
    from ..lexer import Token
    from ..models.ast_base import ASTNode
    from .registry import StatementParserRegistry


class ITokenStream(ABC):
    """Minimal interface for token stream navigation."""

    @abstractmethod
    def peek(self, offset: int = 0) -> Optional["Token"]:
        """Look at token without consuming it.

        Args:
            offset: How many tokens ahead to peek (default: 0 = next token)

        Returns:
            The token at the specified position, or None if out of bounds
        """
        pass

    @abstractmethod
    def consume(self) -> "Token":
        """Consume and return the next token.
        
        Returns:
            The consumed token
            
        Raises:
            UnexpectedEndOfInput: If stream is exhausted
        """
        pass

    @abstractmethod
    def expect(self, value: str) -> "Token":
        """Expect a specific token value before consuming.
        
        Args:
            value: Expected token value (case-insensitive)
            
        Returns:
            The consumed token if it matches
            
        Raises:
            TokenMismatch: If next token doesn't match expected value
        """
        pass

    @abstractmethod
    def is_empty(self) -> bool:
        """Check if stream is exhausted.

        Returns:
            True if no more tokens, False otherwise
        """
        pass

    def skip_whitespace_and_comments(self) -> None:
        """Skip whitespace, comment, newline, and continuation tokens."""
        pass

    @property
    def context(self) -> Optional[Any]:
        """Optional parse context attached to this stream.

        Statement parsers read this to access shared parsing state such as
        the current host parser and nested-statement registry.  The default
        implementation returns None; TokenStream overrides it.
        """
        return None

    @context.setter
    def context(self, value: Optional[Any]) -> None:
        """Set the parse context attached to this stream."""
        pass


class IDivisionParser(ABC):
    """Interface for division-specific parsers."""

    @abstractmethod
    def parse(self, token_stream: ITokenStream) -> "ASTNode":
        """Parse the division from token stream.
        
        Args:
            token_stream: The token stream to parse from
            
        Returns:
            AST node representing the parsed division
            
        Raises:
            ParseError: If division cannot be parsed
        """
        pass

    @abstractmethod
    def can_parse(self, token_stream: ITokenStream) -> bool:
        """Check if this parser can handle the current division.
        
        Args:
            token_stream: The token stream to check
            
        Returns:
            True if parser can handle this division, False otherwise
        """
        pass


class IStatementParser(ABC):
    """Interface for statement-specific parsers."""

    @abstractmethod
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> "ASTNode":
        """Parse the statement from token stream.

        Args:
            token_stream: The token stream to parse from
            context: Optional parse context for nested parsing

        Returns:
            AST node representing the parsed statement

        Raises:
            ParseError: If statement cannot be parsed
        """
        pass

    @abstractmethod
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if this parser matches the current statement.
        
        Args:
            token_stream: The token stream to check
            
        Returns:
            True if parser can handle this statement, False otherwise
        """
        pass


# Parser host and context protocols

class ParserHost(Protocol):
    """Protocol for the main parser interface used by division and statement parsers."""
    
    @property
    def current_section(self) -> Optional[Any]:
        """Current COBOL section being parsed."""
        ...
    
    @property
    def current_division(self) -> Optional[Any]:
        """Current COBOL division being parsed."""
        ...
    
    def add_error(self, error: Any) -> None:
        """Add an error to the error list."""
        ...
    
    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        ...
    
    def create_error(self, message: str, location: Optional[Any] = None) -> Any:
        """Create a ParseError with optional location."""
        ...


class ParseContext:
    """Shared context passed to statement parsers during nested parsing operations."""
    
    def __init__(self, host: Any, registry: Optional["StatementParserRegistry"] = None):
        """Initialize parsing context.
        
        Args:
            host: The parser host with division/section context
            registry: Statement parser registry for nested statement parsing
        """
        self.host = host
        self.registry = registry
        self.parser = host
    
    @property
    def current_section(self) -> Optional[Any]:
        """Current COBOL section being parsed."""
        return self.host.current_section if hasattr(self.host, 'current_section') else None
    
    @property
    def current_division(self) -> Optional[Any]:
        """Current COBOL division being parsed."""
        return self.host.current_division if hasattr(self.host, 'current_division') else None
    
    def parse_nested_statement(self, stream: Optional[Any] = None) -> Optional[Any]:
        """Parse a nested statement using the registry.
        
        Args:
            stream: Optional token stream to parse from
            
        Returns:
            Parsed statement or None
        """
        if stream is not None and self.registry:
            if hasattr(stream, 'skip_whitespace_and_comments'):
                stream.skip_whitespace_and_comments()
            parser = self.registry.find_parser(stream)
            if parser:
                return parser.parse(stream, self)
            return None
        if hasattr(self.host, 'parse_statement'):
            return self.host.parse_statement()
        return None
    
    def error(self, message: str, token: Optional[Any] = None) -> None:
        """Report an error with optional token location."""
        loc = None
        if token is not None:
            if hasattr(token, 'location'):
                loc = token.location
            elif hasattr(token, 'line') and hasattr(token, 'column'):
                loc = token
        if hasattr(self.host, 'create_error'):
            err = self.host.create_error(message, loc)
            if hasattr(self.host, 'add_error'):
                self.host.add_error(err)
