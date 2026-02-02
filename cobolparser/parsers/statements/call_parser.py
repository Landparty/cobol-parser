"""Call statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import CallStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class CallStatementParser(IStatementParser):
    """Parser for CALL statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is CALL keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.CALL or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "CALL"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> CallStatement:
        """Parse a CALL statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(CallStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Simplified parsing - skip to period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()
        
        return stmt
