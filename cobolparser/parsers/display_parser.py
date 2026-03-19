from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import DisplayStatement
from ..lexer import TokenType

class DisplayStatementParser(StatementParser):
    """Parser for DISPLAY statements."""
    token_type = TokenType.DISPLAY

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token:
            if token.type == TokenType.DISPLAY or (
                token.type == TokenType.IDENTIFIER and token.value.upper() == "DISPLAY"
            ):
                return True
        
        # Recovery: Check if previous token was DISPLAY (handled by legacy dispatcher)
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.DISPLAY or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "DISPLAY"
            ):
                return True
        
        return False
    
    def parse(self, stream: TokenStream, context: ParseContext) -> DisplayStatement:
        start_token = stream.peek()
        # If we are at DISPLAY, consume it.
        if start_token and (start_token.type == TokenType.DISPLAY or 
                           (start_token.type == TokenType.IDENTIFIER and start_token.value and start_token.value.upper() == "DISPLAY")):
             start_token = stream.advance()
        else:
             # Assume previous was valid based on can_parse recovery
             start_token = stream.peek(-1)
        
        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location
        
        stmt = DisplayStatement(start_token_loc)
        
        stream.skip_whitespace_and_comments()
        
        # Collect display items until period or next statement
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                stream.advance() # Consume period
                break
            
            # Additional termination checks (e.g. End of Scope)
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-DISPLAY":
                stream.advance() # Consume terminator
                break
                
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "UPON":
                stream.advance()  # UPON
                stream.skip_whitespace_and_comments()
                if not stream.is_at_end:
                     # Helper to consume device name
                     device = stream.advance()
                     if device and device.value:
                         stmt.set_output_device(device.value)
                break
                
            if token.type in (TokenType.STRING_LITERAL, TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                advanced_token = stream.advance()
                val = advanced_token.value if advanced_token and advanced_token.value else ""
                if token.type == TokenType.STRING_LITERAL:
                    val = f'"{val}"'
                stmt.add_display_item(val)
            else:
                # Stop parsing if we hit something unknown (could be next verb)
                # But we need to be careful not to consume it if it's the start of next statement.
                # However, original parser might skip unknowns?
                # Let's assume standard behavior: break on unknown
                break
            
            stream.skip_whitespace_and_comments()
        
        return stmt
