"""If statement parser implementing IStatementParser interface."""

from typing import Optional, List, Any
from ...core.interfaces import IStatementParser, ITokenStream, ParseContext
from ...core.ast_factory import get_factory
from ...models.statements import IfStatement, CobolExpression
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from cobolparser.parsers.statements._utils import skip_whitespace, get_parse_context, report_parse_error, try_parse_nested_statement


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
        """Parse an IF statement with nested statement support.
        
        Supports:
        - IF condition statement [ELSE statement] [END-IF]
        - IF condition THEN statement [ELSE statement] [END-IF]
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(IfStatement, start_token.location if start_token else SourceLocation(0, 0))
        context = get_parse_context(token_stream)
        
        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(start_token.location if start_token else SourceLocation(0, 0))
        
        skip_whitespace(token_stream)
        
        # Parse condition tokens - stop at THEN or statement keyword
        condition_tokens: List[str] = []
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or not token.value:
                break
            
            token_upper = token.value.upper()
            
            # Stop at explicit THEN
            if token_upper == "THEN":
                break
            
            # Stop at statement keywords (implicit THEN)
            if self._is_statement_keyword(token_upper):
                break
            
            # Stop at ELSE or END-IF
            if token_upper in ("ELSE", "END-IF"):
                break
            
            # Stop at period
            if token.type == TokenType.PERIOD:
                break
            
            # Add token to condition
            condition_tokens.append(token.value)
            token_stream.consume()
        
        # Create condition expression
        if condition_tokens:
            condition_text = " ".join(condition_tokens).strip()
            condition_expr = CobolExpression("COMPARISON", start_token.location if start_token else SourceLocation(0, 0))
            condition_expr._metadata["value"] = condition_text
            stmt.set_condition(condition_expr)
        else:
            report_parse_error(
                context,
                "IF statement requires a condition before the THEN branch",
                start_token.location if start_token else SourceLocation(0, 0),
            )
        
        skip_whitespace(token_stream)
        
        # Skip explicit THEN keyword if present
        if not token_stream.is_empty():
            token = token_stream.peek()
            if token and token.value and token.value.upper() == "THEN":
                token_stream.consume()
                skip_whitespace(token_stream)
        
        # Parse THEN branch statements until ELSE, END-IF, or period
        period_found = False
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            
            if token_stream.is_empty():
                break
            
            token = token_stream.peek()
            if not token:
                break
            
            token_upper = token.value.upper() if token.value else ""
            
            # End of THEN branch at ELSE
            if token_upper == "ELSE":
                token_stream.consume()
                skip_whitespace(token_stream)
                period_found = False  # Reset for ELSE branch
                break
            
            # End of IF statement at END-IF
            if token_upper == "END-IF":
                token_stream.consume()
                self._try_consume_period(token_stream)
                return stmt
            
            # End of IF statement at period (when not in a multi-line block)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            
            # If we already found a period terminating the previous statement,
            # don't parse more (this means inline IF)
            if period_found:
                break
            
            # Try to parse nested statement
            nested_stmt = try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_then_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                skip_whitespace(token_stream)
                if previous_token and previous_token.type == TokenType.PERIOD:
                    return stmt
                if not token_stream.is_empty():
                    next_token = token_stream.peek()
                    if next_token and next_token.type == TokenType.PERIOD:
                        period_found = True
            else:
                # Couldn't parse - stop trying to parse statements in this branch
                break
        
        # Parse ELSE branch statements until END-IF or period
        period_found = False
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            
            if token_stream.is_empty():
                break
            
            token = token_stream.peek()
            if not token:
                break
            
            token_upper = token.value.upper() if token.value else ""
            
            # End of IF statement at END-IF
            if token_upper == "END-IF":
                token_stream.consume()
                self._try_consume_period(token_stream)
                return stmt
            
            # End of IF statement at period
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            
            # If we already found a period terminating the previous statement,
            # don't parse more (this means inline IF-ELSE)
            if period_found:
                break
            
            # Try to parse nested statement
            nested_stmt = try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_else_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                skip_whitespace(token_stream)
                if previous_token and previous_token.type == TokenType.PERIOD:
                    return stmt
                if not token_stream.is_empty():
                    next_token = token_stream.peek()
                    if next_token and next_token.type == TokenType.PERIOD:
                        period_found = True
            else:
                # Couldn't parse - stop trying to parse statements in this branch
                break
        
        return stmt
    
    def _is_statement_keyword(self, token_upper: str) -> bool:
        """Check if token is a COBOL statement keyword."""
        statement_keywords = {
            "MOVE", "DISPLAY", "CALL", "PERFORM", "IF", "EVALUATE",
            "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
            "ACCEPT", "READ", "WRITE", "OPEN", "CLOSE",
            "STOP", "GO", "ENTRY", "EXEC", "EXIT",
            "SEARCH", "STRING", "UNSTRING", "INSPECT",
            "ALTER", "CONTINUE", "INITIATE", "TERMINATE",
            "MERGE", "SORT", "RELEASE", "RETURN"
        }
        return token_upper in statement_keywords
    
    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        if not stream.is_empty():
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()
    
    @staticmethod
    def _previous_meaningful_token(stream: ITokenStream):
        """Return the last non-whitespace token consumed by the stream."""
        offset = -1
        while True:
            token = stream.peek(offset)
            if token is None:
                return None
            if token.type.name not in ('WHITESPACE', 'COMMENT', 'NEWLINE', 'CONTINUATION'):
                return token
            offset -= 1

