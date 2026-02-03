"""Evaluate statement parser implementing IStatementParser interface."""

from typing import Optional, Any
from ...core.interfaces import IStatementParser, ITokenStream
from ...models.statements import EvaluateStatement, WhenClause
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class EvaluateStatementParser(IStatementParser):
    """Parser for EVALUATE statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is EVALUATE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return (token.type == TokenType.EVALUATE or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "EVALUATE"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> EvaluateStatement:
        """Parse an EVALUATE statement."""
        try:
            start_token = token_stream.consume()
            if not start_token:
                raise Exception("Expected EVALUATE keyword")
            
            # Create statement
            stmt = EvaluateStatement(start_token.location if hasattr(start_token, 'location') else SourceLocation(0, 0))
            
            # Parse subjects (identifier or expression before WHEN/ALSO)
            while not token_stream.is_empty():
                token = token_stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Stop at WHEN or OTHER
                if token_val_upper in ("WHEN", "OTHER"):
                    break
                
                # Stop at END-EVALUATE
                if token_val_upper == "END-EVALUATE":
                    break
                
                # Collect subject tokens until WHEN or ALSO
                if token_val_upper == "ALSO":
                    token_stream.consume()  # skip ALSO
                    continue
                
                # Add subject (identifier)
                if token.type == TokenType.IDENTIFIER or token.type == TokenType.STRING_LITERAL:
                    subject_value = token.value if token.value else ""
                    stmt.subjects.append(subject_value)
                    token_stream.consume()
                else:
                    token_stream.consume()
            
            # Parse WHEN clauses
            while not token_stream.is_empty():
                token = token_stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Check for WHEN/WHEN OTHER
                if token_val_upper == "WHEN":
                    when_location = token.location if hasattr(token, 'location') else SourceLocation(0, 0)
                    token_stream.consume()  # skip WHEN
                    
                    # Check if it's WHEN OTHER
                    next_token = token_stream.peek()
                    if next_token and next_token.value and next_token.value.upper() == "OTHER":
                        token_stream.consume()  # skip OTHER
                        stmt.default_when = WhenClause([], when_location)
                        # Parse statements until next WHEN or END-EVALUATE
                        statements = self._skip_clause_statements(token_stream)
                        if statements:
                            for s in statements:
                                stmt.default_when.add_statement(s)
                    else:
                        # Parse selectors for WHEN clause
                        selectors = self._parse_selectors(token_stream)
                        when_clause = WhenClause(selectors, when_location)
                        stmt.when_clauses.append(when_clause)
                        # Parse statements until next WHEN or END-EVALUATE
                        statements = self._skip_clause_statements(token_stream)
                        if statements:
                            for s in statements:
                                when_clause.add_statement(s)
                elif token_val_upper == "END-EVALUATE":
                    token_stream.consume()  # skip END-EVALUATE
                    break
                else:
                    token_stream.consume()
            
            return stmt
        except Exception as e:
            # Return empty statement on error
            return EvaluateStatement(SourceLocation(0, 0))
    
    def _parse_selectors(self, token_stream: ITokenStream) -> list:
        """Parse selector list for a WHEN clause, handling ALSO for multiple subjects and conditions."""
        selectors = []
        current_selector = None
        
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Stop at WHEN, END-EVALUATE, or statement keywords
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break
            
            if self._is_statement_keyword(token_val_upper):
                break
            
            # Handle ALSO separator (move to next selector)
            if token_val_upper == "ALSO":
                # Save pending selector if any
                if current_selector is not None:
                    selectors.append(current_selector)
                    current_selector = None
                token_stream.consume()  # skip ALSO
                continue
            
            # Handle ANY keyword as a special selector
            if token_val_upper == "ANY":
                if current_selector is not None:
                    selectors.append(current_selector)
                selectors.append({"type": "Any"})
                current_selector = None
                token_stream.consume()
                continue
            
            # Accept identifiers, literals, and numbers for selector start
            token_type_name = token.type.name if hasattr(token.type, 'name') else str(token.type)
            numeric_types = ("NUMERIC_LITERAL", "LEVEL_NUMBER", "FLOAT_LITERAL")
            
            if token.type == TokenType.IDENTIFIER or \
               token.type == TokenType.STRING_LITERAL or \
               token_type_name in numeric_types:
                
                # Start building a selector
                selector_value = token.value
                selector_tokens = [selector_value]
                token_stream.consume()
                
                # Check for THRU for ranges
                next_token = token_stream.peek()
                if next_token and next_token.value and next_token.value.upper() == "THRU":
                    token_stream.consume()  # skip THRU
                    # Get end value
                    end_token = token_stream.peek()
                    if end_token:
                        end_value = end_token.value
                        token_stream.consume()
                        current_selector = {
                            "type": "Range",
                            "start": selector_value,
                            "end": end_value
                        }
                    continue
                
                # Check for operators (=, <, >, <=, >=, <>, AND, OR) for conditions
                if next_token and next_token.value:
                    next_val_upper = next_token.value.upper()
                    if next_val_upper in ("=", "<", ">", "<=", ">=", "<>", "AND", "OR", "NOT"):
                        # This is a condition - collect all tokens until ALSO/WHEN/END-EVALUATE
                        condition_text = selector_value
                        condition_operator = None
                        while not token_stream.is_empty():
                            t = token_stream.peek()
                            if not t:
                                break
                            tv_upper = t.value.upper() if t.value else ""
                            
                            # Stop at ALSO, WHEN, END-EVALUATE
                            if tv_upper in ("ALSO", "WHEN", "END-EVALUATE"):
                                break
                            
                            # Stop at statement keywords
                            if self._is_statement_keyword(tv_upper):
                                break
                            
                            # Track AND/OR as the main operator
                            if tv_upper in ("AND", "OR"):
                                condition_operator = tv_upper
                            
                            condition_text += " " + (t.value if t.value else "")
                            token_stream.consume()
                        
                        current_selector = {
                            "type": "Condition",
                            "text": condition_text.strip()
                        }
                        if condition_operator:
                            current_selector["operator"] = condition_operator
                        continue
                
                # Determine type for simple selector
                if token.type == TokenType.STRING_LITERAL:
                    selector_type = "Literal"
                elif token_type_name in numeric_types:
                    selector_type = "Literal"
                else:
                    selector_type = "Identifier"
                
                current_selector = {
                    "type": selector_type,
                    "value": selector_value
                }
            else:
                # Skip unrecognized tokens (like NEWLINE)
                token_stream.consume()
        
        # Save final selector if any
        if current_selector is not None:
            selectors.append(current_selector)
        
        return selectors
    
    def _skip_clause_statements(self, token_stream: ITokenStream) -> Optional[list]:
        """Parse statements within WHEN clause until next WHEN or END-EVALUATE.
        
        Returns list of parsed statements, or None if no statements found.
        """
        statements = []
        
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Stop at WHEN or END-EVALUATE
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break
            
            # Try to parse a nested statement if registry is available
            nested_stmt = self._try_parse_nested_statement(token_stream)
            if nested_stmt:
                statements.append(nested_stmt)
            else:
                # Skip token if can't parse
                if token.type == TokenType.PERIOD:
                    token_stream.consume()
                    break
                token_stream.consume()
        
        return statements if statements else None
    
    def _try_parse_nested_statement(self, stream: ITokenStream) -> Optional[Any]:
        """Try to parse a nested statement using registry if available."""
        try:
            # Check if stream has access to a registry
            if hasattr(stream, '_registry'):
                registry = stream._registry
            elif hasattr(stream, 'registry'):
                registry = stream.registry
            elif hasattr(stream, 'get_registry'):
                registry = stream.get_registry()
            else:
                return None
            
            # Try to find a parser for current statement
            if hasattr(registry, 'find_parser'):
                parser = registry.find_parser(stream)
                if parser:
                    return parser.parse(stream)
        except Exception:
            pass
        
        return None
    
    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check if word is a known statement keyword."""
        keywords = {
            "DISPLAY", "MOVE", "IF", "PERFORM", "EVALUATE",
            "CALL", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
            "ACCEPT", "STOP", "EXIT", "GO", "GOBACK", "PERFORM",
            "RETURN", "OPEN", "CLOSE", "READ", "WRITE", "DELETE",
        }
        return word.upper() in keywords
