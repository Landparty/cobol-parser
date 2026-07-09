"""
Data manipulation statement AST nodes (MOVE, DISPLAY, STRING, UNSTRING,
INITIALIZE, SET, INSPECT).
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class MoveStatement(CobolStatement):
    """AST node for MOVE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("MOVE", location)
        self.source: str | None = None
        self.targets: list[str] = []
        self.is_corresponding: bool = False

    def set_source(self, source: str) -> None:
        """Set the source operand for the MOVE."""
        self.source = source
        self._add_unique_operand(source, front=True)

    def add_target(self, target: str) -> None:
        """Add a target operand for the MOVE."""
        self.targets.append(target)
        self._add_unique_operand(target)

    def set_corresponding(self, is_corresponding: bool = True) -> None:
        """Set whether this is a MOVE CORRESPONDING statement."""
        self.is_corresponding = is_corresponding

    def to_dict(self) -> dict[str, Any]:
        """Convert MOVE statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "source": self.source,
                "targets": self.targets,
                "is_corresponding": self.is_corresponding,
            }
        )
        return result


class DisplayStatement(CobolStatement):
    """AST node for DISPLAY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("DISPLAY", location)
        self.display_items: list[str] = []
        self.output_device: str | None = None
        self.with_no_advancing: bool = False
        self.at_line: int | None = None
        self.at_column: int | None = None

    def add_display_item(self, item: str) -> None:
        """Add an item to display."""
        self.display_items.append(item)
        self.operands.append(item)

    def set_output_device(self, device: str) -> None:
        """Set the output device (UPON clause)."""
        self.output_device = device

    def set_no_advancing(self, no_advancing: bool = True) -> None:
        """Set the WITH NO ADVANCING flag (suppresses the implicit newline)."""
        self.with_no_advancing = no_advancing

    def set_position(self, line: int | None = None, column: int | None = None) -> None:
        """Set the AT LINE/COLUMN screen position."""
        self.at_line = line
        self.at_column = column

    def to_dict(self) -> dict[str, Any]:
        """Convert DISPLAY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "display_items": self.display_items,
                "output_device": self.output_device,
                "with_no_advancing": self.with_no_advancing,
                "at_line": self.at_line,
                "at_column": self.at_column,
            }
        )
        return result


class StringStatement(CobolStatement):
    """AST node for STRING statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("STRING", location)
        self.on_overflow: list[CobolStatement] | None = None
        self.not_on_overflow: list[CobolStatement] | None = None
        self.operands: list[str] = []
        self.into_target: str | None = None
        self.pointer_variable: str | None = None
        self.delimiters: list[str] = []

    def add_operand(self, operand: str) -> None:
        """Add a STRING operand."""
        self.operands.append(operand)

    def set_into_target(self, target: str) -> None:
        """Set the INTO target variable."""
        self.into_target = target

    def set_pointer_variable(self, variable: str) -> None:
        """Set the WITH POINTER variable."""
        self.pointer_variable = variable

    def add_delimiter(self, delimiter: str) -> None:
        """Add a DELIMITED BY delimiter."""
        self.delimiters.append(delimiter)

    def set_on_overflow_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("on_overflow", statements)

    def set_not_on_overflow_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_on_overflow", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.operands:
            result["operands"] = self.operands
        if self.delimiters:
            result["delimiters"] = self.delimiters
        if self.into_target:
            result["into_target"] = self.into_target
        if self.pointer_variable:
            result["pointer_variable"] = self.pointer_variable
        result.update(
            self._serialize_clauses("on_overflow", "not_on_overflow", omit_empty=True)
        )
        return result


class UnstringStatement(CobolStatement):
    """AST node for UNSTRING statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("UNSTRING", location)
        self.on_overflow: list[CobolStatement] | None = None
        self.not_on_overflow: list[CobolStatement] | None = None
        self.source_operand: str | None = None
        self.delimiters: list[str] = []
        self.into_targets: list[dict[str, Any]] = []
        self.pointer_variable: str | None = None

    def set_source(self, source: str) -> None:
        """Set the UNSTRING source operand."""
        self.source_operand = source

    def add_delimiter(self, delimiter: str) -> None:
        """Add a DELIMITED BY delimiter."""
        self.delimiters.append(delimiter)

    def add_into_target(
        self,
        target: str,
        delimiter_var: str | None = None,
        count_var: str | None = None,
    ) -> None:
        """Add an INTO target with optional DELIMITER IN and COUNT IN variables."""
        into_info = {
            "target": target,
            "delimiter_var": delimiter_var,
            "count_var": count_var,
        }
        self.into_targets.append(into_info)

    def set_pointer_variable(self, variable: str) -> None:
        """Set the WITH POINTER variable."""
        self.pointer_variable = variable

    def set_on_overflow_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("on_overflow", statements)

    def set_not_on_overflow_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_on_overflow", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.source_operand:
            result["source_operand"] = self.source_operand
        if self.delimiters:
            result["delimiters"] = self.delimiters
        if self.into_targets:
            result["into_targets"] = self.into_targets
        if self.pointer_variable:
            result["pointer_variable"] = self.pointer_variable
        result.update(
            self._serialize_clauses("on_overflow", "not_on_overflow", omit_empty=True)
        )
        return result


class InitializeStatement(CobolStatement):
    """AST node for INITIALIZE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("INITIALIZE", location)
        self.targets: list[str] = []
        self.replacing_clauses: list[dict[str, str]] = []
        self.with_filler: bool = False

    def add_target(self, target: str) -> None:
        self.targets.append(target)
        self._add_unique_operand(target)

    def add_replacing_clause(self, category: str, by_value: str) -> None:
        self.replacing_clauses.append(
            {"category": category.upper(), "by_value": by_value}
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "targets": self.targets,
                "replacing_clauses": self.replacing_clauses,
                "with_filler": self.with_filler,
            }
        )
        return result


class SetStatement(CobolStatement):
    """AST node for SET statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("SET", location)
        self.set_type: str | None = None  # TO, UP_BY, DOWN_BY, TRUE, FALSE
        self.targets: list[str] = []
        self.value: str | None = None

    def set_set_type(self, set_type: str) -> None:
        self.set_type = set_type.upper()

    def add_target(self, target: str) -> None:
        self.targets.append(target)
        self._add_unique_operand(target)

    def set_value(self, value: str) -> None:
        self.value = value
        self._add_unique_operand(value)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "set_type": self.set_type,
                "targets": self.targets,
                "value": self.value,
            }
        )
        return result


class InspectStatement(CobolStatement):
    """AST node for INSPECT statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("INSPECT", location)
        self.target: str | None = None
        self.inspect_type: str | None = None  # TALLYING, REPLACING, CONVERTING
        self.tallying_clauses: list[dict[str, Any]] = []
        self.replacing_clauses: list[dict[str, Any]] = []
        self.converting_from: str | None = None
        self.converting_to: str | None = None

    def set_target(self, target: str) -> None:
        self.target = target
        self._add_unique_operand(target)

    def set_inspect_type(self, inspect_type: str) -> None:
        self.inspect_type = inspect_type.upper()

    def add_tallying_clause(
        self,
        counter: str,
        for_type: str,
        value: str | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.tallying_clauses.append(
            {
                "counter": counter,
                "for_type": for_type.upper(),
                "value": value,
                "before": before,
                "after": after,
            }
        )

    def add_replacing_clause(
        self,
        replace_type: str,
        from_value: str,
        to_value: str,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.replacing_clauses.append(
            {
                "replace_type": replace_type.upper(),
                "from_value": from_value,
                "to_value": to_value,
                "before": before,
                "after": after,
            }
        )

    def set_converting(self, from_value: str, to_value: str) -> None:
        self.converting_from = from_value
        self.converting_to = to_value

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "inspect_type": self.inspect_type,
            }
        )
        if self.tallying_clauses:
            result["tallying_clauses"] = self.tallying_clauses
        if self.replacing_clauses:
            result["replacing_clauses"] = self.replacing_clauses
        if self.converting_from:
            result["converting_from"] = self.converting_from
            result["converting_to"] = self.converting_to
        return result
