"""If statement parser implementing IStatementParser interface."""

from typing import Optional, List, Any
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import IfStatement, CobolExpression
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
        """Parse an IF statement with nested statement support."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(IfStatement, start_token.location if start_token else SourceLocation(0, 0))
        
        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(start_token.location if start_token else SourceLocation(0, 0))
        
        # Skip whitespace/comments if possible
        self._skip_whitespace(token_stream)
        
        # Parse condition until THEN or newline
        cond_tokens = []
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            # Check for end of condition
            if token.type == TokenType.NEWLINE or (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "THEN"):
                break
            
            if token.value:
                cond_tokens.append(token.value)
            token_stream.consume()
        
        # Create condition expression
        if cond_tokens:
            condition_text = " ".join(cond_tokens).strip()
            condition_expr = CobolExpression("COMPARISON", start_token.location if start_token else SourceLocation(0, 0))
            condition_expr._metadata["value"] = condition_text
            stmt.set_condition(condition_expr)
        
        # Skip THEN keyword if present
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "THEN":
            token_stream.consume()
        
        self._skip_whitespace(token_stream)
        
        # Parse THEN branch statements until ELSE or END-IF
        while not token_stream.is_empty():
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            
            if not token:
                break
            
            # Check for ELSE
            if self._is_keyword(token, "ELSE"):
                token_stream.consume()
                break
            
            # Check for END-IF
            if self._is_keyword(token, "END-IF"):
                token_stream.consume()
                # Skip optional period
                self._try_consume_period(token_stream)
                return stmt
            
            # Try to parse nested statement
            nested_stmt = self._try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_then_statement(nested_stmt)
            else:
                # Can't parse as statement, skip this token
                token_stream.consume()
        
        self._skip_whitespace(token_stream)
        
        # Parse ELSE branch statements until END-IF
        while not token_stream.is_empty():
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            
            if not token:
                break
            
            # Check for END-IF
            if self._is_keyword(token, "END-IF"):
                token_stream.consume()
                # Skip optional period
                self._try_consume_period(token_stream)
                return stmt
            
            # Try to parse nested statement
            nested_stmt = self._try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_else_statement(nested_stmt)
            else:
                # Can't parse as statement, skip this token
                token_stream.consume()
        
        return stmt
    
    def _skip_whitespace(self, stream: ITokenStream) -> None:
        """Skip whitespace and comment tokens if possible."""
        try:
            # Try to use stream's skip_whitespace method if available
            if hasattr(stream, 'skip_whitespace_and_comments'):
                stream.skip_whitespace_and_comments()
            else:
                # Manual skip
                while not stream.is_empty():
                    token = stream.peek()
                    if not token or token.type.name not in ('WHITESPACE', 'COMMENT', 'NEWLINE', 'CONTINUATION'):
                        break
                    stream.consume()
        except Exception:
            pass
    
    def _is_keyword(self, token: Any, keyword: str) -> bool:
        """Check if token represents a specific keyword."""
        if not token or not token.value:
            return False
        return token.value.upper() == keyword.upper()
    
    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        try:
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()
        except Exception:
            pass
    
    def _try_parse_nested_statement(self, stream: ITokenStream) -> Optional[Any]:
        """Try to parse a nested statement using registry if available."""
        try:
            # Check if stream has access to a registry
            # This is duck typing - if the stream has a way to get the registry, use it
            if hasattr(stream, '_registry'):
                registry = stream._registry
            elif hasattr(stream, 'registry'):
                registry = stream.registry
            elif hasattr(stream, 'get_registry'):
                registry = stream.get_registry()
            else:
                # No registry available
                return None
            
            # Try to find a parser for current statement
            if hasattr(registry, 'find_parser'):
                parser = registry.find_parser(stream)
                if parser:
                    return parser.parse(stream)
        except Exception:
            pass
        
        return None

