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
        """Parse a CALL statement.
        
        Supports:
        - CALL "program-name"  (static)
        - CALL variable-name   (dynamic)
        - CALL ... USING parameters
        - CALL ... RETURNING variable
        - CALL ... GIVING variable
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(CallStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        try:
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            
            if not token:
                return stmt
            
            # Parse the program name (can be literal or identifier)
            is_dynamic = False
            if token.type == TokenType.STRING_LITERAL:
                # Static CALL with literal program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=False)
                token_stream.consume()
            elif token.type == TokenType.IDENTIFIER:
                # Dynamic CALL with variable program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=True)
                token_stream.consume()
            else:
                # Unknown token type, skip it
                token_stream.consume()
                return stmt
            
            # Parse optional USING and RETURNING clauses
            while not token_stream.is_empty():
                self._skip_whitespace(token_stream)
                token = token_stream.peek()
                
                if not token:
                    break
                
                if token.type == TokenType.PERIOD:
                    token_stream.consume()
                    break
                
                # Parse USING clause
                if token.type == TokenType.USING or (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "USING"):
                    token_stream.consume()
                    # Parse parameter list until RETURNING or GIVING or PERIOD
                    while not token_stream.is_empty():
                        self._skip_whitespace(token_stream)
                        token = token_stream.peek()
                        if not token or token.type == TokenType.PERIOD:
                            break
                        if token.type == TokenType.IDENTIFIER and token.value:
                            val_upper = token.value.upper()
                            if val_upper in ("RETURNING", "GIVING", "ON", "BY"):
                                break
                        if token.type == TokenType.IDENTIFIER:
                            stmt.add_using_parameter(token.value)
                        token_stream.consume()
                elif token.type == TokenType.RETURNING or (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "RETURNING"):
                    token_stream.consume()
                    self._skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_returning_parameter(token.value)
                        token_stream.consume()
                elif token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "GIVING":
                    token_stream.consume()
                    self._skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_giving_parameter(token.value)
                        token_stream.consume()
                else:
                    # Skip unknown tokens
                    token_stream.consume()
        except Exception:
            pass
        
        return stmt
    
    def _skip_whitespace(self, stream: ITokenStream) -> None:
        """Skip whitespace and newline tokens if possible."""
        try:
            while not stream.is_empty():
                token = stream.peek()
                if token and token.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                    stream.consume()
                else:
                    break
        except Exception:
            pass
