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
        self.rounded: bool = False  # For ROUNDED clause

    def set_target(self, target: str) -> None:
        """Set target for TO clause (result stored in target)."""
        self.target = target
        self._add_unique_operand(target)

    def set_giving(self, giving: str) -> None:
        """Set result variable for GIVING clause."""
        self.giving = giving
        self._add_unique_operand(giving)

    def set_rounded(self, rounded: bool = True) -> None:
        """Set whether the ROUNDED clause was present."""
        self.rounded = rounded

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
        if self.rounded:
            result["rounded"] = self.rounded
        result.update(
            self._serialize_clauses(
                "on_size_error", "not_on_size_error", omit_empty=True
            )
        )
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
        # M12: structural decomposition of the expression. `expression`
        # stays the raw space-joined token string for backward
        # compatibility; this holds the precedence-parsed tree (or None
        # when the token sequence could not be decomposed).
        self.expression_tree: CobolExpression | None = None
        self.on_size_error: list[CobolStatement] | None = None
        self.not_on_size_error: list[CobolStatement] | None = None

    def add_target(self, target: str) -> None:
        """Add a target variable for the computation."""
        self.targets.append(target)
        self._add_unique_operand(target)

    def set_expression(self, expression: Union[str, "CobolExpression"]) -> None:
        """Set the arithmetic expression for the computation.

        Args:
            expression: Either a string expression or a CobolExpression object
        """
        self.expression = expression
        # Only add as child if it's an ASTNode object, not a string
        if isinstance(expression, ASTNode):
            self.add_child(expression)

    def set_expression_tree(self, tree: "CobolExpression | None") -> None:
        """Attach the structural expression tree for this COMPUTE (M12).

        Additive to :meth:`set_expression` -- the raw string is unchanged.
        ``None`` (tree could not be built from the token sequence) leaves
        the attribute unset without error.
        """
        self.expression_tree = tree
        if isinstance(tree, ASTNode):
            self.add_child(tree)

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
                "expression_tree": (
                    self.expression_tree.to_dict() if self.expression_tree else None
                ),
            }
        )
        result.update(
            self._serialize_clauses(
                "on_size_error", "not_on_size_error", omit_empty=True
            )
        )
        return result
