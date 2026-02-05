"""Stop statement parser implementing IStatementParser interface."""

from ...core.interfaces import IStatementParser, ITokenStream
from ...models.statements import StopStatement


class StopStatementParser(IStatementParser):
    """Parser for STOP statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is STOP keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            token_val_upper = token.value.upper() if token.value else ""
            return token_val_upper == "STOP"
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> StopStatement:
        """Parse a STOP statement."""
        start_token = token_stream.consume()
        if not start_token:
            # Return empty statement if no token
            from ...models.ast_base import SourceLocation
            return StopStatement(SourceLocation(0, 0))
        
        # Create statement
        from ...models.ast_base import SourceLocation
        location = getattr(start_token, 'location', None) or SourceLocation(0, 0)
        stmt = StopStatement(location)
        
        # Parse STOP type: STOP RUN or STOP "literal"
        if not token_stream.is_empty():
            next_token = token_stream.peek()
            if next_token and next_token.value:
                if next_token.value.upper() == "RUN":
                    stmt.stop_type = "RUN"
                    token_stream.consume()  # consume RUN
                elif next_token.type.name == "STRING_LITERAL":
                    stmt.stop_type = next_token.value
                    token_stream.consume()  # consume literal
        
        return stmt
