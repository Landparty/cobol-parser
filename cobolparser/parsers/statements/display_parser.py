"""Display statement parser implementing IStatementParser interface.

Refactored to implement the IStatementParser interface for registry-based
statement parsing in the extracted statement parser architecture.

Uses ASTNodeFactory for validated node creation.
"""

from typing import Optional
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import DisplayStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from ._utils import skip_whitespace


class DisplayStatementParser(IStatementParser):
    """Parser for DISPLAY statements.
    
    Implements IStatementParser for registry-based dispatch. Parses DISPLAY
    statements in PROCEDURE DIVISION, collecting output items and optional
    output device specifications.
    
    Example COBOL:
        DISPLAY "Hello World".
        DISPLAY item-1 UPON CONSOLE.
    """
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if this parser can handle the current statement.
        
        Matches if the next token is DISPLAY keyword.
        
        Args:
            token_stream: The token stream to check
            
        Returns:
            True if next token is DISPLAY, False otherwise
        """
        try:
            token = token_stream.peek()
            if not token:
                return False
            
            # Check for DISPLAY keyword (by type or identifier value)
            if token.type == TokenType.DISPLAY:
                return True
            
            if token.type == TokenType.IDENTIFIER and token.value:
                return token.value.upper() == "DISPLAY"
            
            return False
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> DisplayStatement:
        """Parse a DISPLAY statement from the token stream.
        
        Consumes tokens starting from DISPLAY keyword through statement terminator
        (period or END-DISPLAY), building a DisplayStatement AST node.
        
        Args:
            token_stream: The token stream to parse from
            
        Returns:
            DisplayStatement AST node
            
        Raises:
            UnexpectedEndOfInput: If stream ends unexpectedly
            ParseError: If invalid DISPLAY syntax encountered
        """
        # Consume DISPLAY keyword
        start_token = token_stream.consume()
        start_location = start_token.location if start_token else SourceLocation(0, 0)
        
        # Use factory for validated node creation
        factory = get_factory()
        stmt = factory.create(DisplayStatement, start_location)
        
        # Type guard: ensure stmt is a DisplayStatement
        if not isinstance(stmt, DisplayStatement):
            stmt = DisplayStatement(start_location)
        
        # Skip whitespace
        skip_whitespace(token_stream)
        
        # Parse display items and optional output device
        while not token_stream.is_empty():
            token = token_stream.peek()
            
            if not token:
                break
            
            # Check for period (statement terminator)
            if token.type == TokenType.PERIOD:
                token_stream.consume()  # Consume period
                break
            
            # Check for END-DISPLAY (explicit terminator)
            if self._is_keyword(token, "END-DISPLAY"):
                token_stream.consume()
                break
            
            # Check for UPON (output device specification)
            if self._is_keyword(token, "UPON"):
                token_stream.consume()  # Consume UPON
                skip_whitespace(token_stream)
                
                device_token = token_stream.peek()
                if device_token:
                    token_stream.consume()
                    stmt.set_output_device(device_token.value or "")
                break
            
            # Collect display item
            if token.type in (TokenType.STRING_LITERAL, TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                item_token = token_stream.consume()
                
                # Format string literals
                item_value = item_token.value or ""
                if token.type == TokenType.STRING_LITERAL:
                    item_value = f'"{item_value}"'
                
                stmt.add_display_item(item_value)
            else:
                # Unknown token - probably next statement, stop parsing
                break
            
            skip_whitespace(token_stream)
        
        return stmt if isinstance(stmt, DisplayStatement) else DisplayStatement(start_location)
    
    @staticmethod
    def _is_keyword(token, keyword: str) -> bool:
        """Check if token is a specific keyword (case-insensitive).
        
        Args:
            token: Token to check
            keyword: Keyword name to match
            
        Returns:
            True if token matches keyword
        """
        if not token or not hasattr(token, 'value'):
            return False
        
        return (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == keyword.upper())
    
