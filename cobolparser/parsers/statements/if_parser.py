"""If statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import IfStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class IfStatementParser(IStatementParser):
    """Parser for IF statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is IF keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.IF or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "IF"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> IfStatement:
        """Parse an IF statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(IfStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(start_token.location if start_token else SourceLocation(0, 0))
        
        # Simplified parsing - just skip to END-IF or period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            if (token.type == TokenType.IDENTIFIER and token.value and 
                token.value.upper() == "END-IF"):
                token_stream.consume()
                break
            
            token_stream.consume()
        
        return stmt
