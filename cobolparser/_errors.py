"""Canonical ParseError definition with zero cobolparser-internal dependencies.

Both ``cobolparser.plugins.core`` and ``cobolparser.core.exceptions`` import
from this module so that all ParseError instances share one class hierarchy,
regardless of which import path was used.
"""

from typing import Any, Optional, Union


class ParseError(Exception):
    """Base class for all parsing errors with context information.

    Supports two calling conventions so that legacy code using the
    ``ParseError(message, line_int, column_int)`` style and structured code
    using ``ParseError(message, file_path, line_number, column)`` both produce
    instances of the same unified class.

    Attributes:
        message: Description of the error
        file_path: Optional source file path
        line_number: Optional line number in source
        column: Optional column number in source
    """

    def __init__(
        self,
        message: str,
        file_path_or_line: Union[str, int, None] = None,
        line_number_or_col: Optional[int] = None,
        column_or_location: Any = None,
        location: Any = None,
        *,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        self.message = message

        if isinstance(file_path_or_line, int):
            # Legacy calling convention: ParseError(message, line_int, col_int[, location])
            self.file_path: Optional[str] = None
            self.line_number: Optional[int] = file_path_or_line
            self.column: Optional[int] = line_number_or_col
            if column_or_location is not None and not isinstance(column_or_location, int):
                location = column_or_location
        else:
            # Structured calling convention: ParseError(message, file_path, line_number, column)
            self.file_path = file_path_or_line  # type: ignore[assignment]
            self.line_number = line_number_or_col
            self.column = (
                column_or_location if isinstance(column_or_location, int) else None
            )

        # Keyword overrides
        if file_path is not None:
            self.file_path = file_path
        if line_number is not None:
            self.line_number = line_number
        if line is not None:
            self.line_number = line
        if column is not None:
            self.column = column

        # SourceLocation object
        if location is not None:
            if hasattr(location, "line") and self.line_number is None:
                try:
                    self.line_number = int(location.line)
                except (TypeError, ValueError):
                    pass
            if hasattr(location, "column") and self.column is None:
                try:
                    self.column = int(location.column)
                except (TypeError, ValueError):
                    pass

        super().__init__(str(self))

    @property
    def line(self) -> int:
        """Alias for line_number (backward compat with plugins.core.ParseError)."""
        return self.line_number or 0

    @line.setter
    def line(self, value: Any) -> None:
        try:
            self.line_number = int(value)
        except (TypeError, ValueError):
            self.line_number = 0

    def __str__(self) -> str:
        """Format error message with location information."""
        line_valid = self.line_number is not None and self.line_number > 0
        if self.file_path:
            location = f"{self.file_path}"
            if line_valid:
                location += f":{self.line_number}"
                if self.column:
                    location += f":{self.column}"
            return f"{location}: {self.message}"
        elif line_valid:
            location_str = f"line {self.line_number}"
            if self.column:
                location_str += f", column {self.column}"
            return f"{location_str}: {self.message}"
        return f"Parse error: {self.message}"
