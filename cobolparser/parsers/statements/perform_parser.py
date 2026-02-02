"""Perform statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import PerformStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class PerformStatementParser(IStatementParser):
    """Parser for PERFORM statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is PERFORM keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.PERFORM or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "PERFORM"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> PerformStatement:
        """Parse a PERFORM statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(PerformStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Simplified parsing - skip to period or END-PERFORM
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            if (token.type == TokenType.IDENTIFIER and token.value and 
                token.value.upper() == "END-PERFORM"):
                token_stream.consume()
                break
            
            token_stream.consume()
        
        return stmt
