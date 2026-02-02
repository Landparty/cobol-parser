"""Evaluate statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import EvaluateStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class EvaluateStatementParser(IStatementParser):
    """Parser for EVALUATE statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is EVALUATE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.EVALUATE or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "EVALUATE"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> EvaluateStatement:
        """Parse an EVALUATE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(EvaluateStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Simplified parsing - skip to END-EVALUATE or period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            if (token.type == TokenType.IDENTIFIER and token.value and 
                token.value.upper() == "END-EVALUATE"):
                token_stream.consume()
                break
            
            token_stream.consume()
        
        return stmt
