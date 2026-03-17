"""Perform statement parser implementing IStatementParser interface."""

from typing import Optional, Any
from ...core.interfaces import IStatementParser, ITokenStream, ParseContext
from ...core.ast_factory import get_factory
from ...models.statements import PerformStatement, CobolExpression
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class PerformStatementParser(IStatementParser):
    """Parser for PERFORM statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is PERFORM keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.PERFORM or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "PERFORM"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> PerformStatement:
        """Parse a PERFORM statement.
        
        Supports:
        - PERFORM paragraph-name
        - PERFORM paragraph-name THRU paragraph-name
        - PERFORM UNTIL condition
        - PERFORM TIMES
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        - Inline PERFORM blocks with nested statements
        """
        # Consume PERFORM keyword
        start_token = token_stream.consume()
        factory = get_factory()
        
        # Create statement with source location
        location = start_token.location if start_token else SourceLocation(0, 0)
        stmt = factory.create(PerformStatement, location)
        context = self._get_context(token_stream)
        
        # Skip whitespace/comments if possible
        self._skip_whitespace(token_stream)
        
        # Try to get the next meaningful token (peek without consuming)
        try:
            token = token_stream.peek()
        except Exception:
            # End of stream
            return stmt
        
        if not token:
            self._report_error(context, "PERFORM statement requires a target paragraph or inline clause", location)
            return stmt

        if token.type == TokenType.PERIOD:
            self._report_error(context, "PERFORM statement requires a target paragraph or inline clause", location)
            token_stream.consume()
            return stmt
        
        # Check for VARYING clause (inline PERFORM VARYING)
        if token.type == TokenType.VARYING:
            self._parse_varying_clause(token_stream, stmt)
            return stmt
        
        # Check for TEST clause (WITH TEST BEFORE/AFTER)
        if token.type == TokenType.WITH:
            try:
                token_stream.consume()  # Skip WITH
                token = token_stream.peek()
                if token and token.type == TokenType.TEST:
                    token_stream.consume()  # Skip TEST
                    token = token_stream.peek()
                    if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                        val = token.type.name  # "BEFORE" or "AFTER"
                        stmt.set_test_timing(val)
                        token_stream.consume()
                        token = token_stream.peek()
            except Exception:
                pass
                self._skip_whitespace(token_stream)
                token = token_stream.peek()
        
        # Check for UNTIL clause (inline PERFORM UNTIL)
        if token and token.type == TokenType.UNTIL:
            self._parse_until_clause(token_stream, stmt)
            return stmt
        
        # Check for TIMES clause (inline PERFORM n TIMES)
        # Check for numeric literals: TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER, or numeric IDENTIFIER
        if token and (token.type == TokenType.NUMERIC_LITERAL or 
                      token.type == TokenType.LEVEL_NUMBER or
                      (token.type == TokenType.IDENTIFIER and token.value and token.value.isdigit())):
            try:
                times_count = int(token.value)
                token_stream.consume()
                token = token_stream.peek()
                # Check for TIMES keyword: TokenType.TIMES or IDENTIFIER "TIMES"
                if token and (token.type == TokenType.TIMES or 
                             (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("TIMES", "TIME"))):
                    token_stream.consume()
                    stmt.set_times_clause(times_count)
                    # Parse inline statements until END-PERFORM
                    self._parse_inline_statements(token_stream, stmt)
                    return stmt
            except (ValueError, Exception):
                pass
            
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
        
        # Simple PERFORM paragraph-name
        if token and token.type == TokenType.IDENTIFIER:
            paragraph = token.value
            stmt.set_target_paragraph(paragraph)
            try:
                token_stream.consume()
                token = token_stream.peek()
            except Exception:
                token = None
            
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            
            # Check for THRU clause
            if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "THRU":
                try:
                    token_stream.consume()  # Skip THRU
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_thru_paragraph(token.value)
                        token_stream.consume()
                        token = token_stream.peek()
                    else:
                        self._report_error(
                            context,
                            "PERFORM THRU requires an ending paragraph name",
                            location,
                        )
                except Exception:
                    pass
                
                self._skip_whitespace(token_stream)
                token = token_stream.peek()
            
            # Check for TIMES clause after paragraph name (can be numeric or variable)
            if token and token.type == TokenType.IDENTIFIER:
                times_value = token.value
                times_consumed = token_stream.consume()
                token = token_stream.peek()
                
                # Check if  followed by TIMES keyword
                if token and (token.type == TokenType.TIMES or 
                             (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("TIMES", "TIME"))):
                    # Can be numeric (int) or variable (string)
                    try:
                        times_count = int(times_value)
                    except ValueError:
                        times_count = times_value  # Keep as variable name string
                    
                    token_stream.consume()  # Skip TIMES keyword
                    stmt.set_times_clause(times_count)
                    token = token_stream.peek()
            elif token and (token.type == TokenType.NUMERIC_LITERAL or 
                           token.type == TokenType.LEVEL_NUMBER):
                try:
                    times_count = int(token.value)
                    token_stream.consume()
                    token = token_stream.peek()
                    if token and (token.type == TokenType.TIMES or 
                                 (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("TIMES", "TIME"))):
                        token_stream.consume()
                        stmt.set_times_clause(times_count)
                        token = token_stream.peek()
                except (ValueError, Exception):
                    pass
            
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            
            # Check for WITH TEST clause after paragraph name (WITH TEST BEFORE/AFTER)
            if token and token.type == TokenType.WITH:
                try:
                    token_stream.consume()  # Skip WITH
                    token = token_stream.peek()
                    if token and token.type == TokenType.TEST:
                        token_stream.consume()  # Skip TEST
                        token = token_stream.peek()
                        if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                            val = token.type.name  # "BEFORE" or "AFTER"
                            stmt.set_test_timing(val)
                            token_stream.consume()
                            token = token_stream.peek()
                except Exception:
                    pass
                
                self._skip_whitespace(token_stream)
                token = token_stream.peek()
            
            # Check for UNTIL clause after paragraph name
            if token and token.type == TokenType.UNTIL:
                try:
                    self._parse_until_condition_only(token_stream, stmt)
                except Exception:
                    pass
        
        # Expect period or END-PERFORM
        try:
            token = token_stream.peek()
            if token and token.type == TokenType.PERIOD:
                token_stream.consume()
            elif token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-PERFORM":
                token_stream.consume()
        except Exception:
            pass
        
        return stmt

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
    
    def _parse_varying_clause(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse VARYING clause for PERFORM statement."""
        try:
            stream.consume()  # Skip VARYING
            self._skip_whitespace(stream)
            
            # Get variable name
            token = stream.peek()
            if not token or token.type != TokenType.IDENTIFIER:
                return
            
            variable_name = token.value
            stream.consume()
            self._skip_whitespace(stream)
            
            # Expect FROM
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "FROM":
                return
            stream.consume()
            self._skip_whitespace(stream)
            
            # Get FROM value
            token = stream.peek()
            if not token or not token.value:
                return
            from_value = token.value
            stream.consume()
            self._skip_whitespace(stream)
            
            # Expect BY
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "BY":
                return
            stream.consume()
            self._skip_whitespace(stream)
            
            # Get BY value
            token = stream.peek()
            if not token or not token.value:
                return
            by_value = token.value
            stream.consume()
            self._skip_whitespace(stream)
            
            # Check for WITH TEST clause (before UNTIL)
            token = stream.peek()
            if token and token.type == TokenType.WITH:
                try:
                    stream.consume()  # Skip WITH
                    token = stream.peek()
                    if token and token.type == TokenType.TEST:
                        stream.consume()  # Skip TEST
                        token = stream.peek()
                        if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                            val = token.type.name  # "BEFORE" or "AFTER"
                            stmt.set_test_timing(val)
                            stream.consume()
                            token = stream.peek()
                except Exception:
                    pass
                
                self._skip_whitespace(stream)
                token = stream.peek()
            
            # Parse UNTIL condition
            token = stream.peek()
            if token and token.type == TokenType.UNTIL:
                self._parse_until_conditional(stream, stmt)
                # Now set the varying clause with the collected values and the until condition
                until_condition = stmt.until_condition
                if until_condition:
                    stmt.set_varying_clause(variable_name, from_value, by_value, until_condition)
            else:
                # Parse inline statements without UNTIL
                self._parse_inline_statements(stream, stmt)
        except Exception:
            pass
    
    def _parse_until_clause(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse UNTIL clause for inline PERFORM."""
        try:
            stream.consume()  # Skip UNTIL
            self._skip_whitespace(stream)
            
            # Parse condition - collect tokens until we hit a statement keyword
            # Statement keywords include PERFORM, DISPLAY, MOVE, IF, EVALUATE, etc.
            STATEMENT_TOKEN_TYPES = {
                TokenType.PERFORM, TokenType.DISPLAY, TokenType.MOVE, TokenType.IF, 
                TokenType.EVALUATE, TokenType.ACCEPT, TokenType.CALL, TokenType.COMPUTE,
                TokenType.INSPECT, TokenType.READ, TokenType.WRITE, TokenType.OPEN, 
                TokenType.CLOSE, TokenType.STOP
            }
            
            condition_tokens = []
            while True:
                token = stream.peek()
                if not token:
                    break
                
                # Check if we've hit a statement keyword (by TokenType)
                if token.type in STATEMENT_TOKEN_TYPES:
                    break
                
                # Check for END-PERFORM
                if token.type == TokenType.END_PERFORM:
                    break
                
                # Check for period
                if token.type == TokenType.PERIOD:
                    break
                
                condition_tokens.append(token.value or str(token.type))
                stream.consume()
            
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                # Create CobolExpression for the condition and set it on the statement
                location = SourceLocation(0, 0)  # Default location; ideally would be from first token
                condition_expr = CobolExpression("CONDITION", location)
                condition_expr.operands = [condition_str]  # Store the condition string as operand
                stmt.set_until_clause(condition_expr)
            
            # Parse inline statements
            self._parse_inline_statements(stream, stmt)
        except Exception:
            pass
    
    def _parse_until_conditional(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse UNTIL condition for VARYING clause."""
        try:
            stream.consume()  # Skip UNTIL
            self._skip_whitespace(stream)
            
            # Collect condition tokens - stop at statement keywords
            STATEMENT_TOKEN_TYPES = {
                TokenType.PERFORM, TokenType.DISPLAY, TokenType.MOVE, TokenType.IF, 
                TokenType.EVALUATE, TokenType.ACCEPT, TokenType.CALL, TokenType.COMPUTE,
                TokenType.INSPECT, TokenType.READ, TokenType.WRITE, TokenType.OPEN, 
                TokenType.CLOSE, TokenType.STOP, TokenType.END_PERFORM
            }
            
            condition_tokens = []
            while True:
                token = stream.peek()
                if not token:
                    break
                # Stop at period, END-PERFORM, or statement keywords
                if (token.type == TokenType.PERIOD or 
                    (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-PERFORM") or
                    token.type in STATEMENT_TOKEN_TYPES or
                    (token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("DISPLAY", "MOVE", "IF", "CALL", "PERFORM", "EVALUATE"))):
                    break
                
                condition_tokens.append(token.value or str(token.type))
                stream.consume()
            
            # Create CobolExpression for the condition and store it
            # This will be used in set_varying_clause call
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                location = SourceLocation(0, 0)  # Default location
                condition_expr = CobolExpression("CONDITION", location)
                condition_expr.operands = [condition_str]
                # Store the condition on the statement (varies will be set when set_varying_clause is called)
                stmt.until_condition = condition_expr
            
            # Parse inline statements
            self._parse_inline_statements(stream, stmt)
        except Exception:
            pass
    
    def _parse_until_condition_only(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse just the UNTIL condition after paragraph name."""
        try:
            if stream.peek() and stream.peek().value and stream.peek().value.upper() == "UNTIL":
                stream.consume()
            
            self._skip_whitespace(stream)
            
            # Parse condition (simplified)
            condition_tokens = []
            while True:
                token = stream.peek()
                if not token:
                    break
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break
                if (token.type == TokenType.IDENTIFIER and token.value and 
                    token.value.upper() == "END-PERFORM"):
                    stream.consume()
                    break
                
                condition_tokens.append(token.value or str(token.type))
                stream.consume()
            
            # Create CobolExpression for the condition and set it on statement
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                location = SourceLocation(0, 0)  # Default location
                condition_expr = CobolExpression("CONDITION", location)
                condition_expr.operands = [condition_str]
                stmt.set_until_clause(condition_expr)
        except Exception:
            pass
    
    def _parse_inline_statements(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse inline statements within PERFORM ... END-PERFORM block."""
        try:
            self._skip_whitespace(stream)
            
            # Parse statements until END-PERFORM or PERIOD
            while not stream.is_empty():
                self._skip_whitespace(stream)
                token = stream.peek()
                
                if not token:
                    break
                
                # Check for END-PERFORM
                if token.type == TokenType.END_PERFORM or (
                    token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-PERFORM"
                ):
                    stream.consume()
                    # Skip optional period
                    self._try_consume_period(stream)
                    break
                
                # Check for PERIOD (inline PERFORM without END-PERFORM)
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break
                
                # Try to parse nested statement
                nested_stmt = self._try_parse_nested_statement(stream)
                if nested_stmt:
                    stmt.add_inline_statement(nested_stmt)
                else:
                    # Can't parse, skip token
                    stream.consume()
        except Exception:
            pass
    
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


