"""
Data manipulation statement AST nodes (MOVE, DISPLAY, STRING, UNSTRING).
"""

from typing import Dict, Any, List, Optional
from ..ast_base import SourceLocation
from .base import CobolStatement


class MoveStatement(CobolStatement):
    """AST node for MOVE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("MOVE", location)
        self.source: Optional[str] = None
        self.targets: List[str] = []
        self.is_corresponding: bool = False

    def set_source(self, source: str) -> None:
        """Set the source operand for the MOVE."""
        self.source = source
        if source not in self.operands:
            self.operands.insert(0, source)

    def add_target(self, target: str) -> None:
        """Add a target operand for the MOVE."""
        self.targets.append(target)
        if target not in self.operands:
            self.operands.append(target)

    def set_corresponding(self, is_corresponding: bool = True) -> None:
        """Set whether this is a MOVE CORRESPONDING statement."""
        self.is_corresponding = is_corresponding

    def to_dict(self) -> Dict[str, Any]:
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
        self.display_items: List[str] = []
        self.output_device: Optional[str] = None

    def add_display_item(self, item: str) -> None:
        """Add an item to display."""
        self.display_items.append(item)
        self.operands.append(item)

    def set_output_device(self, device: str) -> None:
        """Set the output device (UPON clause)."""
        self.output_device = device

    def to_dict(self) -> Dict[str, Any]:
        """Convert DISPLAY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {"display_items": self.display_items, "output_device": self.output_device}
        )
        return result


class StringStatement(CobolStatement):
    """AST node for STRING statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("STRING", location)
        self.on_overflow: Optional[List["CobolStatement"]] = None
        self.not_on_overflow: Optional[List["CobolStatement"]] = None
        self.operands: List[str] = []
        self.into_target: Optional[str] = None
        self.pointer_variable: Optional[str] = None
        self.delimiters: List[str] = []

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

    def set_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.operands:
            result["operands"] = self.operands
        if self.delimiters:
            result["delimiters"] = self.delimiters
        if self.into_target:
            result["into_target"] = self.into_target
        if self.pointer_variable:
            result["pointer_variable"] = self.pointer_variable
        if self.on_overflow:
            result["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.not_on_overflow:
            result["not_on_overflow"] = [s.to_dict() for s in self.not_on_overflow]
        return result


class UnstringStatement(CobolStatement):
    """AST node for UNSTRING statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("UNSTRING", location)
        self.on_overflow: Optional[List["CobolStatement"]] = None
        self.not_on_overflow: Optional[List["CobolStatement"]] = None
        self.source_operand: Optional[str] = None
        self.delimiters: List[str] = []
        self.into_targets: List[Dict[str, Any]] = []
        self.pointer_variable: Optional[str] = None

    def set_source(self, source: str) -> None:
        """Set the UNSTRING source operand."""
        self.source_operand = source

    def add_delimiter(self, delimiter: str) -> None:
        """Add a DELIMITED BY delimiter."""
        self.delimiters.append(delimiter)

    def add_into_target(self, target: str, delimiter_var: Optional[str] = None, count_var: Optional[str] = None) -> None:
        """Add an INTO target with optional DELIMITER IN and COUNT IN variables."""
        into_info = {
            "target": target,
            "delimiter_var": delimiter_var,
            "count_var": count_var
        }
        self.into_targets.append(into_info)

    def set_pointer_variable(self, variable: str) -> None:
        """Set the WITH POINTER variable."""
        self.pointer_variable = variable

    def set_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.source_operand:
            result["source_operand"] = self.source_operand
        if self.delimiters:
            result["delimiters"] = self.delimiters
        if self.into_targets:
            result["into_targets"] = self.into_targets
        if self.pointer_variable:
            result["pointer_variable"] = self.pointer_variable
        if self.on_overflow:
            result["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.not_on_overflow:
            result["not_on_overflow"] = [s.to_dict() for s in self.not_on_overflow]
        return result
