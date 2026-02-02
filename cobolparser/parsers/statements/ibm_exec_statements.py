"""EXEC SQL and EXEC CICS statement parsers for IBM Enterprise COBOL.

Support for embedded SQL and CICS statements in COBOL procedures.
"""

from ...core.interfaces import IStatementParser, ITokenStream
from ...models.statements import CobolStatement
from ...models.ast_base import ASTNode, SourceLocation
from ...lexer import TokenType


class ExecSqlStatementParser(IStatementParser):
    """Parser for EXEC SQL statements (embedded SQL in COBOL).
    
    Handles IBM COBOL embedded SQL blocks that contain SQL statements
    within EXEC SQL...END-EXEC blocks in procedure divisions.
    
    Example:
        EXEC SQL
            SELECT * FROM TABLE
        END-EXEC.
    """
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next tokens are EXEC SQL."""
        try:
            token = token_stream.peek(0)
            if not token:
                return False
            
            # Check if first token is EXEC
            if not (token.type == TokenType.IDENTIFIER and 
                   token.value and 
                   token.value.upper() == "EXEC"):
                return False
            
            # Check if next token is SQL
            next_token = token_stream.peek(1)
            if not next_token:
                return False
            
            return bool(next_token.type == TokenType.IDENTIFIER and 
                       next_token.value and 
                       next_token.value.upper() == "SQL")
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> ASTNode:
        """Parse an EXEC SQL statement.
        
        Simplified implementation that skips to END-EXEC.
        """
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)
        
        # Skip SQL keyword
        if not token_stream.is_empty():
            token_stream.consume()
        
        # Parse SQL content - skip until END-EXEC
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            if (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == "END-EXEC"):
                token_stream.consume()
                break
            
            token_stream.consume()
        
        # Create a simple AST node for EXEC SQL
        class ExecSqlStatement(ASTNode):
            def __init__(self, location):
                super().__init__("EXEC_SQL", location)
            
            def to_dict(self):
                return {
                    "node_type": self.node_type,
                    "location": self.location.to_dict(),
                }
        
        return ExecSqlStatement(start_location)


class ExecCicsStatementParser(IStatementParser):
    """Parser for EXEC CICS statements (CICS transactions in COBOL).
    
    Handles IBM COBOL CICS transaction processing blocks within
    EXEC CICS...END-EXEC blocks in procedure divisions.
    
    Example:
        EXEC CICS
            RECEIVE INTO CICS-BUFFER
        END-EXEC.
    """
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next tokens are EXEC CICS."""
        try:
            token = token_stream.peek(0)
            if not token:
                return False
            
            # Check if first token is EXEC
            if not (token.type == TokenType.IDENTIFIER and 
                   token.value and 
                   token.value.upper() == "EXEC"):
                return False
            
            # Check if next token is CICS
            next_token = token_stream.peek(1)
            if not next_token:
                return False
            
            return bool(next_token.type == TokenType.IDENTIFIER and 
                       next_token.value and 
                       next_token.value.upper() == "CICS")
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> ASTNode:
        """Parse an EXEC CICS statement.
        
        Simplified implementation that skips to END-EXEC.
        """
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)
        
        # Skip CICS keyword
        if not token_stream.is_empty():
            token_stream.consume()
        
        # Parse CICS content - skip until END-EXEC
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            if (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == "END-EXEC"):
                token_stream.consume()
                break
            
            token_stream.consume()
        
        # Create a simple AST node for EXEC CICS
        class ExecCicsStatement(ASTNode):
            def __init__(self, location):
                super().__init__("EXEC_CICS", location)
            
            def to_dict(self):
                return {
                    "node_type": self.node_type,
                    "location": self.location.to_dict(),
                }
        
        return ExecCicsStatement(start_location)
