"""If statement parser implementing IStatementParser interface."""

from typing import Optional, List, Any
from ...core.interfaces import IStatementParser, ITokenStream, ParseContext
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
        """Parse an IF statement with nested statement support.
        
        Supports:
        - IF condition statement [ELSE statement] [END-IF]
        - IF condition THEN statement [ELSE statement] [END-IF]
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(IfStatement, start_token.location if start_token else SourceLocation(0, 0))
        context = self._get_context(token_stream)
        
        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(start_token.location if start_token else SourceLocation(0, 0))
        
        self._skip_whitespace(token_stream)
        
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
            self._report_error(
                context,
                "IF statement requires a condition before the THEN branch",
                start_token.location if start_token else SourceLocation(0, 0),
            )
        
        self._skip_whitespace(token_stream)
        
        # Skip explicit THEN keyword if present
        if not token_stream.is_empty():
            token = token_stream.peek()
            if token and token.value and token.value.upper() == "THEN":
                token_stream.consume()
                self._skip_whitespace(token_stream)
        
        # Parse THEN branch statements until ELSE, END-IF, or period
        period_found = False
        while not token_stream.is_empty():
            self._skip_whitespace(token_stream)
            
            if token_stream.is_empty():
                break
            
            token = token_stream.peek()
            if not token:
                break
            
            token_upper = token.value.upper() if token.value else ""
            
            # End of THEN branch at ELSE
            if token_upper == "ELSE":
                token_stream.consume()
                self._skip_whitespace(token_stream)
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
            nested_stmt = self._try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_then_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                self._skip_whitespace(token_stream)
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
            self._skip_whitespace(token_stream)
            
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
            nested_stmt = self._try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_else_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                self._skip_whitespace(token_stream)
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
    
    def _skip_whitespace(self, stream: ITokenStream) -> None:
        """Skip whitespace and comment tokens."""
        try:
            while not stream.is_empty():
                token = stream.peek()
                if not token or token.type.name not in ('WHITESPACE', 'COMMENT', 'NEWLINE', 'CONTINUATION'):
                    break
                stream.consume()
        except Exception:
            pass
    
    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        if not stream.is_empty():
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()
    
    def _try_parse_nested_statement(self, stream: ITokenStream) -> Optional[Any]:
        """Try to parse a nested statement using registry available on stream.
        
        The registry is attached to the stream by ProcedureDivisionParser as _registry.
        """
        try:
            # Get next token to check what we're about to parse
            token = stream.peek()
            if not token:
                return None
            
            # Try to get registry from stream attributes
            registry = None
            
            # Check for _registry (set by ProcedureDivisionParser)
            if hasattr(stream, '_registry'):
                registry = stream._registry  # type: ignore[attr-defined]
            # Check for registry property/method
            elif hasattr(stream, 'registry'):
                registry = stream.registry  # type: ignore[attr-defined]
            # Check for get_registry method
            elif hasattr(stream, 'get_registry') and callable(stream.get_registry):
                registry = stream.get_registry()  # type: ignore[attr-defined]
            
            if not registry:
                return None
            
            # Find appropriate parser from registry
            if hasattr(registry, 'find_parser') and callable(registry.find_parser):
                parser = registry.find_parser(stream)
                # Avoid infinite recursion by checking that we didn't get self
                if parser and parser != self:
                    return parser.parse(stream)
        except Exception:
            # Silently fail - if we can't parse nested statement, just skip it
            pass
        
        return None

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

    @staticmethod
    def _get_context(stream: ITokenStream) -> Optional[ParseContext]:
        """Return the active parse context if one is attached to the stream."""
        context = getattr(stream, '_parse_context', None)
        if context is None:
            context = getattr(stream, '_context', None)
        return context

    @staticmethod
    def _report_error(
        context: Optional[ParseContext],
        message: str,
        location: SourceLocation,
    ) -> None:
        """Report a parser error through the active parse context."""
        if context:
            context.error(message, location)

