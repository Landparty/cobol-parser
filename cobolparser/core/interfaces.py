"""Abstract base classes and interfaces for COBOL parser components."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, Protocol, Any

if TYPE_CHECKING:
    from ..lexer import Token
    from ..models.ast_base import ASTNode
    from .registry import StatementRegistry


class ITokenStream(ABC):
    """Minimal interface for token stream navigation."""

    @abstractmethod
    def peek(self, offset: int = 0) -> "Token":
        """Look at token without consuming it.
        
        Args:
            offset: How many tokens ahead to peek (default: 0 = next token)
            
        Returns:
            The token at the specified position
            
        Raises:
            UnexpectedEndOfInput: If offset exceeds remaining tokens
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
    def parse(self, token_stream: ITokenStream) -> "ASTNode":
        """Parse the statement from token stream.
        
        Args:
            token_stream: The token stream to parse from
            
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


# Backward compatibility support for existing codebase

class ParserHost(Protocol):
    """Backward compatibility protocol for main parser interface."""
    
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
    """Backward compatibility context class for statement parsing.
    
    Provides shared context during nested parsing operations.
    """
    
    def __init__(self, host: Any, registry: Optional["StatementRegistry"] = None):
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
            parser = self.registry.get_parser(stream)
            if parser:
                return parser.parse(stream, self)
            return None
        if hasattr(self.host, 'parse_statement'):
            return self.host.parse_statement()
        return None
    
    def error(self, message: str, token: Optional[Any] = None) -> None:
        """Report an error with optional token location."""
        loc = token.location if token else None
        if hasattr(self.host, 'create_error'):
            err = self.host.create_error(message, loc)
            if hasattr(self.host, 'add_error'):
                self.host.add_error(err)


class StatementParser(Protocol):
    """Backward compatibility: legacy interface for statement parsers (Protocol).
    
    This matches the duck-typing pattern used by StatementRegistry.
    New code should implement IStatementParser instead.
    """
    
    def can_parse(self, stream) -> bool:
        """Return True if this parser handles the current token."""
        ...
    
    def parse(self, stream, context=None):
        """Parse and return the statement."""
        ...
