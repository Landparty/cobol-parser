"""Structured error types for COBOL parser with detailed context."""

from typing import Optional

# Single canonical ParseError lives in cobolparser._errors to avoid circular
# imports between cobolparser.plugins.core and cobolparser.core.
from cobolparser._errors import ParseError  # noqa: F401


class TokenMismatch(ParseError):
    """Raised when an expected token doesn't match the actual token.

    Attributes:
        expected: The expected token value
        actual: The actual token value found
        token_value: The raw text of the offending token (may include type info)
    """

    def __init__(
        self,
        expected: str,
        actual: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        column: Optional[int] = None,
        token_value: Optional[str] = None,
    ):
        self.expected = expected
        self.actual = actual
        self.token_value = token_value if token_value is not None else actual
        message = f"Expected '{expected}', got '{actual}'"
        super().__init__(message, file_path, line_number, column)


class UnexpectedEndOfInput(ParseError):
    """Raised when token stream ends prematurely."""

    def __init__(
        self,
        expected: Optional[str] = None,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
    ):
        message = "Unexpected end of input"
        if expected:
            message += f" (expected: {expected})"
        super().__init__(message, file_path, line_number)


class DivisionNotFoundError(ParseError):
    """Raised when an unknown COBOL division is encountered."""

    def __init__(
        self,
        division_name: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        column: Optional[int] = None,
    ):
        self.division_name = division_name
        message = f"Unknown division: {division_name}"
        super().__init__(message, file_path, line_number, column)


class UnknownStatementError(ParseError):
    """Raised when statement parser registry cannot match a statement."""

    def __init__(
        self,
        token_value: Optional[str] = None,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        column: Optional[int] = None,
    ):
        self.token_value = token_value
        message = "Unknown or unrecognized statement"
        if token_value:
            message += f": {token_value}"
        super().__init__(message, file_path, line_number, column)


class ValidationError(ParseError):
    """Raised when AST node validation fails."""

    def __init__(
        self,
        node_type: str,
        issue: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        column: Optional[int] = None,
    ):
        self.node_type = node_type
        self.issue = issue
        message = f"Validation error in {node_type}: {issue}"
        super().__init__(message, file_path, line_number, column)
