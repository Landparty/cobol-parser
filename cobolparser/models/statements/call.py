"""
CALL and ENTRY statement AST nodes.
"""

from dataclasses import dataclass
from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


@dataclass
class CallParameter:
    """Parameter passed to a CALL statement."""

    name: str
    passing_mode: str = "REFERENCE"  # REFERENCE, CONTENT, or VALUE


class CallStatement(CobolStatement):
    """AST node for CALL statements.

    Supports both static CALL statements (with literal program names) and
    dynamic CALL statements (using variables). For dynamic calls, the parser
    can track possible values through data flow analysis.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("CALL", location)
        self.called_program: str | None = None
        self.using_parameters: list[CallParameter] = []
        self.returning_parameter: str | None = None
        self.giving_parameter: str | None = None
        self.on_overflow: list[CobolStatement] | None = None
        self.on_exception: list[CobolStatement] | None = None
        self.not_on_exception: list[CobolStatement] | None = None
        self._is_dynamic: bool = False
        self._possible_values: list[str] = []

    def set_called_program(self, program_name: str, is_dynamic: bool = False) -> None:
        """Set the called program name and type."""
        self.called_program = program_name
        self._is_dynamic = is_dynamic
        self._add_unique_operand(program_name)

    def add_using_parameter(
        self, param_name: str, passing_mode: str = "REFERENCE"
    ) -> None:
        """Add a parameter to the USING clause."""
        param = CallParameter(param_name, passing_mode)
        self.using_parameters.append(param)
        self._add_unique_operand(param_name)

    def set_giving_parameter(self, param_name: str) -> None:
        """Set the GIVING parameter."""
        self.giving_parameter = param_name
        self._add_unique_operand(param_name)

    def set_returning_parameter(self, param_name: str) -> None:
        """Set the RETURNING parameter."""
        self.returning_parameter = param_name
        self._add_unique_operand(param_name)

    def set_is_dynamic(self, value: bool) -> None:
        """Set whether this is a dynamic CALL."""
        self._is_dynamic = value

    @property
    def is_dynamic(self) -> bool:
        """Check if this is a dynamic CALL."""
        return self._is_dynamic

    @property
    def possible_values(self) -> list[str]:
        """Get possible values for dynamic call target."""
        return list(self._possible_values)

    def add_possible_value(self, value: str) -> None:
        """Add a possible value for dynamic call."""
        if value not in self._possible_values:
            self._possible_values.append(value)

    def set_possible_values(self, values: list[str]) -> None:
        """Set all possible values."""
        self._possible_values = list(set(values))  # Deduplicate

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base = super().to_dict()
        base.update(
            {
                "called_program": self.called_program,
                "using_parameters": [
                    {"name": p.name, "mode": p.passing_mode}
                    for p in self.using_parameters
                ],
                "giving_parameter": self.giving_parameter,
                "returning_parameter": self.returning_parameter,
                "is_dynamic": self.is_dynamic,
                "possible_values": self.possible_values,
            }
        )
        # Add exception handlers if present
        base.update(
            self._serialize_clauses("on_overflow", "on_exception", omit_empty=True)
        )

        return base


class EntryStatement(CobolStatement):
    """AST node for ENTRY statements.

    ENTRY statements define alternate entry points into a program, commonly
    used in IMS programs. The syntax is:
        ENTRY literal-name [USING parameter-list]

    Example:
        ENTRY 'DLITCBL' USING LKPCB-IO LKPCB-ALT LKPCB-BPP100MA
    """

    def __init__(self, location: SourceLocation):
        super().__init__("ENTRY", location)
        self.entry_name: str | None = None
        self.using_parameters: list[str] = []

    def set_entry_name(self, name: str) -> None:
        """Set the entry point name (literal)."""
        self.entry_name = name
        self._add_unique_operand(name)

    def add_using_parameter(self, param_name: str) -> None:
        """Add a parameter to the USING clause."""
        self.using_parameters.append(param_name)
        self._add_unique_operand(param_name)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base = super().to_dict()
        base.update(
            {"entry_name": self.entry_name, "using_parameters": self.using_parameters}
        )
        return base
