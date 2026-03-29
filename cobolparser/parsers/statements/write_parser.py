"""Write statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import WriteStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from cobolparser.parsers.statements._utils import skip_whitespace


class WriteStatementParser(IStatementParser):
    """Parser for WRITE statements using IStatementParser interface.
    
    Supports:
    - WRITE record-name
    - WRITE record-name FROM source-data
    - WRITE record-name [FROM source] [BEFORE/AFTER ADVANCING]
    """
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is WRITE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            if token.type == TokenType.WRITE:
                return True
            return False
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> WriteStatement:
        """Parse a WRITE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(WriteStatement, factory.create(WriteStatement, start_token.location if start_token else SourceLocation(0, 0)))
        
        # Skip whitespace
        skip_whitespace(token_stream)
        
        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            record_name = token.value
            stmt.set_record_name(record_name)
            token_stream.consume()
        else:
            # Missing record name - just return what we have
            return stmt
        
        skip_whitespace(token_stream)
        
        # Check for FROM clause
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "FROM":
            token_stream.consume()
            skip_whitespace(token_stream)
            
            # Parse FROM source
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                source = token.value
                stmt.set_from(source)
                token_stream.consume()
            
            skip_whitespace(token_stream)
        
        # Check for ADVANCING clause (BEFORE/AFTER ADVANCING)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            val_upper = token.value.upper()
            if val_upper in ("BEFORE", "AFTER"):
                advancing_mode = val_upper
                token_stream.consume()
                skip_whitespace(token_stream)
                
                # Expect ADVANCING keyword
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "ADVANCING":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    
                    # The advancing clause may have LINES or LINES n or PAGE or CHANNEL, etc
                    # For now, just store the mode
                    if advancing_mode:
                        stmt.advancing_mode = advancing_mode
        
        # Skip whitespace and consume period if present
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()
        
        return stmt
    