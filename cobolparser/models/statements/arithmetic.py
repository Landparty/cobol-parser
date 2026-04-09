"""
Arithmetic statement AST nodes (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE).
"""

from typing import Any, Union

from ..ast_base import ASTNode, SourceLocation
from .base import CobolExpression, CobolStatement


class ArithmeticStatement(CobolStatement):
    """Base AST node for arithmetic statements (ADD, SUBTRACT, MULTIPLY, DIVIDE)."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__(statement_type, location)
        self.on_size_error: list[CobolStatement] | None = None
        self.not_on_size_error: list[CobolStatement] | None = None
        self.target: str | None = None  # For TO clause
        self.giving: str | None = None  # For GIVING clause

    def set_target(self, target: str) -> None:
        """Set target for TO clause (result stored in target)."""
        self.target = target
        if target not in self.operands:
            self.operands.append(target)

    def set_giving(self, giving: str) -> None:
        """Set result variable for GIVING clause."""
        self.giving = giving
        if giving not in self.operands:
            self.operands.append(giving)

    def set_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("on_size_error", statements)

    def set_not_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_on_size_error", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.target:
            result["target"] = self.target
        if self.giving:
            result["giving"] = self.giving
        if self.on_size_error:
            result["on_size_error"] = [s.to_dict() for s in self.on_size_error]
        if self.not_on_size_error:
            result["not_on_size_error"] = [s.to_dict() for s in self.not_on_size_error]
        return result


class AddStatement(ArithmeticStatement):
    """AST node for ADD statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("ADD", location)


class SubtractStatement(ArithmeticStatement):
    """AST node for SUBTRACT statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("SUBTRACT", location)


class MultiplyStatement(ArithmeticStatement):
    """AST node for MULTIPLY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("MULTIPLY", location)


class DivideStatement(ArithmeticStatement):
    """AST node for DIVIDE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("DIVIDE", location)


class ComputeStatement(CobolStatement):
    """AST node for COMPUTE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("COMPUTE", location)
        self.targets: list[str] = []
        self.expression: str | CobolExpression | None = None
        self.on_size_error: list[CobolStatement] | None = None
        self.not_on_size_error: list[CobolStatement] | None = None

    def add_target(self, target: str) -> None:
        """Add a target variable for the computation."""
        self.targets.append(target)
        if target not in self.operands:
            self.operands.append(target)

    def set_expression(self, expression: Union[str, "CobolExpression"]) -> None:
        """Set the arithmetic expression for the computation.

        Args:
            expression: Either a string expression or a CobolExpression object
        """
        self.expression = expression
        # Only add as child if it's an ASTNode object, not a string
        if isinstance(expression, ASTNode):
            self.add_child(expression)

    def set_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("on_size_error", statements)

    def set_not_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_on_size_error", statements)

    def to_dict(self) -> dict[str, Any]:
        """Convert COMPUTE statement to dictionary representation."""
        result = super().to_dict()

        # Handle expression which can be string or ASTNode
        expression_dict: dict[str, Any] | str | None = None
        if self.expression:
            if isinstance(self.expression, ASTNode):
                expression_dict = self.expression.to_dict()
            else:
                expression_dict = str(self.expression)

        result.update(
            {
                "targets": self.targets,
                "expression": expression_dict,
            }
        )
        if self.on_size_error:
            result["on_size_error"] = [s.to_dict() for s in self.on_size_error]
        if self.not_on_size_error:
            result["not_on_size_error"] = [s.to_dict() for s in self.not_on_size_error]
        return result
