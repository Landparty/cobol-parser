"""Move statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import MoveStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class MoveStatementParser(IStatementParser):
    """Parser for MOVE statements using IStatementParser interface.
    
    Refactored to support registry-based statement parsing.
    """
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is MOVE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.MOVE or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "MOVE"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> MoveStatement:
        """Parse a MOVE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(MoveStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Parse: MOVE source [TO target]+ | MOVE CORRESPONDING source TO target
        # Simplified for now - just parse basic structure
        self._skip_whitespace(token_stream)
        
        # Collect tokens until period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()
        
        return stmt
    
    @staticmethod
    def _skip_whitespace(token_stream: ITokenStream) -> None:
        """Skip whitespace tokens."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type not in (TokenType.WHITESPACE, 
                                               TokenType.COMMENT, 
                                               TokenType.NEWLINE):
                break
            token_stream.consume()
