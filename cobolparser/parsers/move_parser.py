from typing import Optional, List
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import MoveStatement
from ..lexer import TokenType
from ..plugins.core import ParseError

class MoveStatementParser(StatementParser):
    """Parser for MOVE statements."""
    token_type = TokenType.MOVE

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token:
            if token.type == TokenType.MOVE or (
                token.type == TokenType.IDENTIFIER and token.value.upper() == "MOVE"
            ):
                return True
        
        # Recovery: Check if previous token was MOVE (handled by legacy dispatcher)
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.MOVE or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "MOVE"
            ):
                return True
        
        return False
    
    def parse(self, stream: TokenStream, context: ParseContext) -> MoveStatement:
        start_token = stream.peek()
        # If we are at MOVE, consume it.
        if start_token and (start_token.type == TokenType.MOVE or 
                           (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "MOVE")):
             start_token = stream.advance()
        else:
             # Assume previous was valid based on can_parse recovery
             start_token = stream.peek(-1)
        
        if not start_token:
            start_token = stream.peek() or stream.peek(-1)
            if not start_token:
                # Fatal: no location available
                from ..models.ast_base import SourceLocation
                start_token_loc = SourceLocation(0, 0)
            else:
                start_token_loc = start_token.location
        else:
            start_token_loc = start_token.location
        
        stmt = MoveStatement(start_token_loc)
        stream.skip_whitespace_and_comments()
        
        # Check for CORRESPONDING
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("CORRESPONDING", "CORR"):
             stmt.set_corresponding(True)
             stream.advance()
             stream.skip_whitespace_and_comments()

        # Parse Source Operand
        source_operand = ""
        paren_depth = 0
        
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            
            # Check for TO keyword (if not inside parens)
            if paren_depth == 0:
                if (token.type == TokenType.TO or 
                   (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "TO")):
                    break
            
            # Handle parentheses for subscripts/refmods
            if token.type == TokenType.LEFT_PAREN:
                paren_depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                paren_depth -= 1
            
            # Stop if we hit something that looks like a new statement (and paren_depth is 0)
            if paren_depth == 0 and token.type in (TokenType.PERIOD, TokenType.MOVE, TokenType.IF):
                 # Error case: Missing TO
                 break

            val = token.value if token.value else ""
            if token.type == TokenType.STRING_LITERAL:
                val = f'"{val}"'
            source_operand += val
            stream.advance()
            
            # Add space if next token needs separation (simplified logic)
            # COBOL source reconstruction is tricky, we might just concatenation logic similar to legacy
            # For now, just append. Legacy did: source_operand += tokens[i].value
            
        stmt.set_source(source_operand)
        stream.skip_whitespace_and_comments()
        
        # Expect TO
        found_to = False
        if stream.match(TokenType.TO):
             found_to = True
        elif stream.match(TokenType.IDENTIFIER):
             t = stream.peek()
             if t and t.value and t.value.upper() == "TO":
                 found_to = True
        
        if not found_to:
            # Error expected TO
            context.error("Expected TO keyword", stream.peek())
        else:
            stream.advance() # Consume TO

        stream.skip_whitespace_and_comments()
        
        # Parse Targets
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            
            if token.type == TokenType.PERIOD:
                stream.advance()
                break
            
            # Terminators
            if token.type in (TokenType.END_IF, TokenType.END_PERFORM, TokenType.END_EVALUATE, TokenType.ELSE, TokenType.WHEN):
                break
                
            # Legacy parser stopped at problematic tokens
            if token.type in (TokenType.LEVEL_NUMBER, TokenType.ASSIGN):
                break
            
            # If it's a keyword that starts a new statement, break
            # Check a few common verbs
            if token.type in (TokenType.MOVE, TokenType.DISPLAY, TokenType.CALL, TokenType.ADD, TokenType.SUBTRACT,
                              TokenType.IF, TokenType.PERFORM, TokenType.EVALUATE, TokenType.STOP, TokenType.EXIT,
                              TokenType.GO, TokenType.GOTO):
                 break

            # Consume target
            target_token = stream.advance()
            if target_token and target_token.value:
                target = target_token.value
                stmt.add_target(target)
            stream.skip_whitespace_and_comments()
            
            # Handle comma separator
            if stream.match(TokenType.COMMA):
                stream.advance()
                stream.skip_whitespace_and_comments()
                
        return stmt
