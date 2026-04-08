"""Canonical ParseError definition with zero cobolparser-internal dependencies.

Both ``cobolparser.plugins.core`` and ``cobolparser.core.exceptions`` import
from this module so that all ParseError instances share one class hierarchy,
regardless of which import path was used.
"""

from typing import Any


class ParseError(Exception):
    """Base class for all parsing errors with context information.

    Attributes:
        message: Description of the error
        file_path: Optional source file path
        line_number: Optional line number in source
        column: Optional column number in source
    """

    def __init__(
        self,
        message: str,
        *,
        file_path: str | None = None,
        line_number: int | None = None,
        column: int | None = None,
        location: Any = None,
    ) -> None:
        self.message = message
        self.code: str | None = None
        self.file_path = file_path
        self.line_number = line_number
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
