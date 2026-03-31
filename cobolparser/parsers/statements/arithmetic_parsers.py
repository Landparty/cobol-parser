"""Arithmetic statement parsers implementing IStatementParser interface.

Supports ADD, SUBTRACT, MULTIPLY, DIVIDE, and COMPUTE statements with proper
parsing of operands, targets, expressions, and error handling clauses.
"""

from typing import Any, Optional, Union
from ...core.interfaces import IStatementParser, ITokenStream
from ...models.statements import (
    AddStatement,
    SubtractStatement,
    MultiplyStatement,
    DivideStatement,
    ComputeStatement,
    DisplayStatement,
    MoveStatement,
)
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


class AddStatementParser(IStatementParser):
    """Parser for ADD statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is ADD keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.ADD or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "ADD"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> AddStatement:
        """Parse an ADD statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = AddStatement(start_loc)
        
        # Parse operands until TO or GIVING
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            if token_val_upper in ("TO", "GIVING"):
                break
            
            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)
            
            token_stream.consume()
        
        # Check for TO or GIVING
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper == "TO":
                token_stream.consume()  # Skip TO
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    token_stream.consume()
                # After TO, check for GIVING
                token = token_stream.peek()
                if token and token.value and token.value.upper() == "GIVING":
                    token_stream.consume()  # Skip GIVING
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_giving(token.value)
                        token_stream.consume()
            elif token_val_upper == "GIVING":
                token_stream.consume()  # Skip GIVING
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    token_stream.consume()
        
        # Check for ON SIZE ERROR or NOT ON SIZE ERROR
        AddStatementParser._parse_size_error_clauses(token_stream, stmt)
        
        return stmt
    
    @staticmethod
    def _skip_to_period(token_stream: ITokenStream) -> None:
        """Skip tokens until period."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()
    
    @staticmethod
    def _parse_size_error_clauses(token_stream: ITokenStream, stmt: Any) -> None:
        """Parse ON SIZE ERROR or NOT ON SIZE ERROR clauses with nested statements."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            
            # Skip NEWLINE and other non-code tokens
            if token.type == TokenType.NEWLINE:
                token_stream.consume()
                continue
            
            if token.value:
                token_upper = token.value.upper()
                if token_upper == "ON":
                    token_stream.consume()
                    next_token = token_stream.peek()
                    # Skip NEWLINEs before SIZE
                    while next_token and next_token.type == TokenType.NEWLINE:
                        token_stream.consume()
                        next_token = token_stream.peek()
                    
                    if next_token and next_token.value and next_token.value.upper() == "SIZE":
                        token_stream.consume()
                        next_token = token_stream.peek()
                        # Skip NEWLINEs before ERROR
                        while next_token and next_token.type == TokenType.NEWLINE:
                            token_stream.consume()
                            next_token = token_stream.peek()
                        
                        if next_token and next_token.value and next_token.value.upper() == "ERROR":
                            token_stream.consume()
                            nested = AddStatementParser._parse_nested_statements(token_stream)
                            stmt.set_on_size_error_clause(nested)
                elif token_upper == "NOT":
                    token_stream.consume()
                    next_token = token_stream.peek()
                    # Skip NEWLINEs before ON
                    while next_token and next_token.type == TokenType.NEWLINE:
                        token_stream.consume()
                        next_token = token_stream.peek()
                    
                    if next_token and next_token.value and next_token.value.upper() == "ON":
                        token_stream.consume()
                        next_token = token_stream.peek()
                        # Skip NEWLINEs before SIZE
                        while next_token and next_token.type == TokenType.NEWLINE:
                            token_stream.consume()
                            next_token = token_stream.peek()
                        
                        if next_token and next_token.value and next_token.value.upper() == "SIZE":
                            token_stream.consume()
                            next_token = token_stream.peek()
                            # Skip NEWLINEs before ERROR
                            while next_token and next_token.type == TokenType.NEWLINE:
                                token_stream.consume()
                                next_token = token_stream.peek()
                            
                            if next_token and next_token.value and next_token.value.upper() == "ERROR":
                                token_stream.consume()
                                nested = AddStatementParser._parse_nested_statements(token_stream)
                                stmt.set_not_on_size_error_clause(nested)
                else:
                    break
            else:
                token_stream.consume()
    
    @staticmethod
    def _parse_nested_statements(token_stream: ITokenStream) -> list:
        """Parse nested statements within ON SIZE ERROR clause."""
        nested: list = []
        
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            
            # Skip NEWLINE tokens
            if token.type == TokenType.NEWLINE:
                token_stream.consume()
                continue
            
            if token.value:
                token_upper = token.value.upper()
                
                if token_upper == "DISPLAY":
                    start = token_stream.consume()
                    start_loc = start.location if start else SourceLocation(0, 0)
                    display_stmt = DisplayStatement(start_loc)
                    # Collect DISPLAY items
                    while not token_stream.is_empty():
                        t = token_stream.peek()
                        if not t:
                            break
                        if t.type == TokenType.NEWLINE:
                            token_stream.consume()
                            continue
                        if t.type == TokenType.PERIOD or (t.value and t.value.upper() in ("MOVE", "DISPLAY")):
                            break
                        if t.type in (TokenType.STRING_LITERAL, TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                            display_stmt.add_display_item(t.value)
                        token_stream.consume()
                    nested.append(display_stmt)
                    
                elif token_upper == "MOVE":
                    start = token_stream.consume()
                    start_loc = start.location if start else SourceLocation(0, 0)
                    move_stmt = MoveStatement(start_loc)
                    # Parse MOVE source TO target
                    while not token_stream.is_empty():
                        t = token_stream.peek()
                        if not t:
                            break
                        if t.type == TokenType.NEWLINE:
                            token_stream.consume()
                            continue
                        if t.type == TokenType.PERIOD:
                            break
                        if t.value and t.value.upper() == "TO":
                            token_stream.consume()
                            target_token = token_stream.peek()
                            # Skip NEWLINEs before target
                            while target_token and target_token.type == TokenType.NEWLINE:
                                token_stream.consume()
                                target_token = token_stream.peek()

                            if target_token and target_token.type == TokenType.IDENTIFIER:
                                move_stmt.add_target(target_token.value)
                                token_stream.consume()
                            break
                        if t.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL, TokenType.STRING_LITERAL):
                            move_stmt.add_operand(t.value)
                        token_stream.consume()
                    nested.append(move_stmt)
                else:
                    token_stream.consume()
            else:
                token_stream.consume()
        
        return nested


class SubtractStatementParser(IStatementParser):
    """Parser for SUBTRACT statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is SUBTRACT keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.SUBTRACT or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "SUBTRACT"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> SubtractStatement:
        """Parse a SUBTRACT statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = SubtractStatement(start_loc)
        
        # Parse operands until FROM or GIVING
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            if token_val_upper in ("FROM", "GIVING"):
                break
            
            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)
            
            token_stream.consume()
        
        # Check for FROM or GIVING
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper == "FROM":
                token_stream.consume()  # Skip FROM
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    token_stream.consume()
            elif token_val_upper == "GIVING":
                token_stream.consume()  # Skip GIVING
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    token_stream.consume()
        
        self._skip_to_period(token_stream)
        return stmt
    
    @staticmethod
    def _skip_to_period(token_stream: ITokenStream) -> None:
        """Skip tokens until period."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()


class MultiplyStatementParser(IStatementParser):
    """Parser for MULTIPLY statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is MULTIPLY keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.MULTIPLY or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "MULTIPLY"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> MultiplyStatement:
        """Parse a MULTIPLY statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = MultiplyStatement(start_loc)
        
        # Parse first operand
        token = token_stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            token_stream.consume()
        
        # Check for BY
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "BY":
            token_stream.consume()  # Skip BY
            token = token_stream.peek()
            if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)
                token_stream.consume()
        
        # Check for GIVING
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            token_stream.consume()  # Skip GIVING
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                token_stream.consume()
        
        self._skip_to_period(token_stream)
        return stmt
    
    @staticmethod
    def _skip_to_period(token_stream: ITokenStream) -> None:
        """Skip tokens until period."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()


class DivideStatementParser(IStatementParser):
    """Parser for DIVIDE statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is DIVIDE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.DIVIDE or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "DIVIDE"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> DivideStatement:
        """Parse a DIVIDE statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = DivideStatement(start_loc)
        
        # Parse first operand
        token = token_stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            token_stream.consume()
        
        # Check for BY or INTO
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper in ("BY", "INTO"):
                token_stream.consume()  # Skip BY/INTO
                token = token_stream.peek()
                if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                    stmt.add_operand(token.value)
                    token_stream.consume()
        
        # Check for GIVING
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            token_stream.consume()  # Skip GIVING
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                token_stream.consume()
        
        self._skip_to_period(token_stream)
        return stmt
    
    @staticmethod
    def _skip_to_period(token_stream: ITokenStream) -> None:
        """Skip tokens until period."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()


class ComputeStatementParser(IStatementParser):
    """Parser for COMPUTE statements using IStatementParser interface."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is COMPUTE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.COMPUTE or
                    (token.type == TokenType.IDENTIFIER and token.value and 
                     token.value.upper() == "COMPUTE"))
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream, context: Optional[Any] = None) -> ComputeStatement:
        """Parse a COMPUTE statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = ComputeStatement(start_loc)
        
        # Parse target variable(s)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.add_target(token.value)
            token_stream.consume()
        
        # Skip ROUNDED if present
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "ROUNDED":
            token_stream.consume()
        
        # Check for =
        token = token_stream.peek()
        if token and token.value == "=":
            token_stream.consume()  # Skip =
        
        # Parse expression (collect all tokens until terminator)
        expr_tokens = []
        paren_depth = 0
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Stop at terminators
            if paren_depth == 0 and (
                token.type == TokenType.PERIOD
                or token_val_upper in ("ON", "NOT", "END-COMPUTE")
            ):
                break
            
            if token.type == TokenType.LEFT_PAREN:
                paren_depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                paren_depth -= 1
            
            expr_tokens.append(token.value if token.value else "")
            token_stream.consume()
        
        if expr_tokens:
            expr_str = " ".join(expr_tokens).strip()
            stmt.set_expression(expr_str)

        AddStatementParser._parse_size_error_clauses(token_stream, stmt)
        return stmt
    
    @staticmethod
    def _skip_to_period(token_stream: ITokenStream) -> None:
        """Skip tokens until period."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                if token:
                    token_stream.consume()
                break
            token_stream.consume()
