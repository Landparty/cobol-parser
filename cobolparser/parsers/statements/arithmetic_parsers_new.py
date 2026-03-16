"""Arithmetic statement parsers implementing IStatementParser interface.

Supports ADD, SUBTRACT, MULTIPLY, DIVIDE, and COMPUTE statements.
"""

from ...core.interfaces import IStatementParser, ITokenStream
from ...models.statements import (
    AddStatement,
    SubtractStatement,
    MultiplyStatement,
    DivideStatement,
    ComputeStatement,
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
    
    def parse(self, token_stream: ITokenStream) -> AddStatement:
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
    
    def parse(self, token_stream: ITokenStream) -> SubtractStatement:
        """Parse a SUBTRACT statement."""
        start_token = token_stream.consume()
        start_loc = start_token.location if start_token else SourceLocation(0, 0)
        stmt = SubtractStatement(start_loc)
        
        # Parse operands until FROM or GIVING
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else "
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
    
    def parse(self, token_stream: ITokenStream) -> MultiplyStatement:
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
    
    def parse(self, token_stream: ITokenStream) -> DivideStatement:
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
    
    def parse(self, token_stream: ITokenStream) -> ComputeStatement:
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
