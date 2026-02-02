"""Structured error types for COBOL parser with detailed context."""

from typing import Optional
from dataclasses import dataclass


@dataclass
class ParseError(Exception):
    """Base class for all parsing errors with context information.
    
    Attributes:
        message: Description of the error
        file_path: Optional source file path
        line_number: Optional line number in source
        column: Optional column number in source
    """
    
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    
    def __str__(self) -> str:
        """Format error message with location information."""
        if self.file_path:
            location = f"{self.file_path}"
            if self.line_number:
                location += f":{self.line_number}"
                if self.column:
                    location += f":{self.column}"
            return f"{location}: {self.message}"
        elif self.line_number:
            location = f"line {self.line_number}"
            if self.column:
                location += f", column {self.column}"
            return f"{location}: {self.message}"
        return f"Parse error: {self.message}"
    
    def __init__(self, message: str, file_path: Optional[str] = None, 
                 line_number: Optional[int] = None, column: Optional[int] = None):
        self.message = message
        self.file_path = file_path
        self.line_number = line_number
        self.column = column
        super().__init__(str(self))


class TokenMismatch(ParseError):
    """Raised when an expected token doesn't match the actual token.
    
    Attributes:
        expected: The expected token value
        actual: The actual token value found
    """
    
    def __init__(self, expected: str, actual: str, file_path: Optional[str] = None,
                 line_number: Optional[int] = None, column: Optional[int] = None):
        self.expected = expected
        self.actual = actual
        message = f"Expected '{expected}', got '{actual}'"
        super().__init__(message, file_path, line_number, column)


class UnexpectedEndOfInput(ParseError):
    """Raised when token stream ends prematurely."""
    
    def __init__(self, expected: Optional[str] = None, file_path: Optional[str] = None,
                 line_number: Optional[int] = None):
        message = "Unexpected end of input"
        if expected:
            message += f" (expected: {expected})"
        super().__init__(message, file_path, line_number)


class DivisionNotFoundError(ParseError):
    """Raised when an unknown COBOL division is encountered."""
    
    def __init__(self, division_name: str, file_path: Optional[str] = None,
                 line_number: Optional[int] = None, column: Optional[int] = None):
        self.division_name = division_name
        message = f"Unknown division: {division_name}"
        super().__init__(message, file_path, line_number, column)


class UnknownStatementError(ParseError):
    """Raised when statement parser registry cannot match a statement."""
    
    def __init__(self, token_value: Optional[str] = None, file_path: Optional[str] = None,
                 line_number: Optional[int] = None, column: Optional[int] = None):
        self.token_value = token_value
        message = f"Unknown or unrecognized statement"
        if token_value:
            message += f": {token_value}"
        super().__init__(message, file_path, line_number, column)


class ValidationError(ParseError):
    """Raised when AST node validation fails."""
    
    def __init__(self, node_type: str, issue: str, file_path: Optional[str] = None,
                 line_number: Optional[int] = None, column: Optional[int] = None):
        self.node_type = node_type
        self.issue = issue
        message = f"Validation error in {node_type}: {issue}"
        super().__init__(message, file_path, line_number, column)
