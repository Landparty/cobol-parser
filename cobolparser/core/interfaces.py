from typing import Protocol, Optional, TYPE_CHECKING
from .token_stream import TokenStream
from ..models.statements import CobolStatement
from ..lexer import Token, TokenType
from ..plugins.core import ParseError
from ..models.ast_base import SourceLocation

if TYPE_CHECKING:
    from ..models.program import CobolDivision, CobolSection
    from .registry import StatementRegistry

class ParserHost(Protocol):
    """Interface for the main parser provided to plugins."""
    current_section: Optional["CobolSection"]
    current_division: Optional["CobolDivision"]
    
    def add_error(self, error: ParseError) -> None: ...
    def add_warning(self, message: str) -> None: ...
    def create_error(self, message: str, location: Optional['SourceLocation'] = None) -> ParseError: ...

class ParseContext:
    """Shared context during parsing."""
    def __init__(self, host: ParserHost, registry: "StatementRegistry"):
        self.host = host
        self.registry = registry
        self.parser = host  # Expose parser for nested statement parsing

    @property
    def current_section(self) -> Optional["CobolSection"]:
        return self.host.current_section

    @property
    def current_division(self) -> Optional["CobolDivision"]:
        return self.host.current_division

    def parse_nested_statement(self, stream: TokenStream = None) -> Optional[CobolStatement]:
        """Delegate back to main parser to parse a child statement."""
        # Always use the direct parser method, not the stream-based registry
        if hasattr(self.host, 'parse_statement'):
            return self.host.parse_statement()
        return None
        
    def error(self, message: str, token: Optional[Token] = None):
        """Report an error in a standardized way."""
        loc = token.location if token else None
        err = self.host.create_error(message, loc)
        self.host.add_error(err)

class StatementParser(Protocol):
    """Interface for statement-specific parsers."""
    
    def can_parse(self, stream: TokenStream) -> bool:
        """Return True if this parser handles the current token."""
        ...
    
    def parse(self, stream: TokenStream, context: ParseContext) -> CobolStatement:
        """Parse and return the statement."""
        ...
