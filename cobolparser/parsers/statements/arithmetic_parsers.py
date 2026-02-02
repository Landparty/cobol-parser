"""Arithmetic statement parsers implementing IStatementParser interface.

Supports ADD, SUBTRACT, MULTIPLY, DIVIDE, and COMPUTE statements.
"""

from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
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
        factory = get_factory()
        stmt = factory.create(AddStatement, start_token.location if start_token else SourceLocation(0, 0))
        self._skip_to_period(token_stream)
        return stmt if isinstance(stmt, AddStatement) else AddStatement(start_token.location if start_token else SourceLocation(0, 0))
    
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
        factory = get_factory()
        stmt = factory.create(SubtractStatement, start_token.location if start_token else SourceLocation(0, 0))
        self._skip_to_period(token_stream)
        return stmt if isinstance(stmt, SubtractStatement) else SubtractStatement(start_token.location if start_token else SourceLocation(0, 0))
    
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
        factory = get_factory()
        stmt = factory.create(MultiplyStatement, start_token.location if start_token else SourceLocation(0, 0))
        self._skip_to_period(token_stream)
        return stmt if isinstance(stmt, MultiplyStatement) else MultiplyStatement(start_token.location if start_token else SourceLocation(0, 0))
    
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
        factory = get_factory()
        stmt = factory.create(DivideStatement, start_token.location if start_token else SourceLocation(0, 0))
        self._skip_to_period(token_stream)
        return stmt if isinstance(stmt, DivideStatement) else DivideStatement(start_token.location if start_token else SourceLocation(0, 0))
    
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
        factory = get_factory()
        stmt = factory.create(ComputeStatement, start_token.location if start_token else SourceLocation(0, 0))
        self._skip_to_period(token_stream)
        return stmt if isinstance(stmt, ComputeStatement) else ComputeStatement(start_token.location if start_token else SourceLocation(0, 0))
    
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
