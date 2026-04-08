"""
Base classes for COBOL statement and expression AST nodes.
"""

from typing import Any, Union

from ..ast_base import ASTNode, SourceLocation


class CobolStatement(ASTNode):
    """Base class for COBOL statement AST nodes."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__("Statement", location)
        self.statement_type = statement_type
        self.operands: list[str] = []

    @property
    def sql_type(self) -> str | None:
        """Return SQL type if this is an SQL statement, None otherwise."""
        return None

    @property
    def cics_command(self) -> str | None:
        """Return CICS command if this is a CICS statement, None otherwise."""
        return None

    @property
    def ims_command(self) -> str | None:
        """Return IMS command if this is an IMS statement, None otherwise."""
        return None

    def add_operand(self, operand: str) -> None:
        """Add an operand to the statement."""
        self.operands.append(operand)

    def to_dict(self) -> dict[str, Any]:
        """Convert statement to dictionary representation."""
        return {
            "node_type": self.node_type,
            "statement_type": self.statement_type,
            "operands": self.operands,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class CobolExpression(ASTNode):
    """Base class for COBOL expression AST nodes."""

    def __init__(self, expression_type: str, location: SourceLocation):
        super().__init__("Expression", location)
        self.expression_type = expression_type
        self.operands: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        """Convert expression to dictionary representation."""
        return {
            "node_type": self.node_type,
            "expression_type": self.expression_type,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class ArithmeticExpression(CobolExpression):
    """AST node for arithmetic expressions."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("ARITHMETIC", location)
        self.operator = operator
        self.left_operand: str | CobolExpression | None = None
        self.right_operand: str | CobolExpression | None = None

    def set_left_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the left operand of the expression."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def set_right_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the right operand of the expression."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def to_dict(self) -> dict[str, Any]:
        """Convert arithmetic expression to dictionary representation."""
        result = super().to_dict()

        left_dict = (
            self.left_operand.to_dict()
            if isinstance(self.left_operand, CobolExpression)
            else self.left_operand
        )
        right_dict = (
            self.right_operand.to_dict()
            if isinstance(self.right_operand, CobolExpression)
            else self.right_operand
        )

        result.update(
            {
                "operator": self.operator,
                "left_operand": left_dict,
                "right_operand": right_dict,
            }
        )
        return result


class ConditionalExpression(CobolExpression):
    """AST node for conditional expressions."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("COMPARISON", location)
        self.operator = operator
        self.left_operand: str | CobolExpression | None = None
        self.right_operand: str | CobolExpression | None = None

    def set_left_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the left operand of the condition."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def set_right_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the right operand of the condition."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def to_dict(self) -> dict[str, Any]:
        """Convert conditional expression to dictionary representation."""
        result = super().to_dict()

        left_dict = (
            self.left_operand.to_dict()
            if isinstance(self.left_operand, CobolExpression)
            else self.left_operand
        )
        right_dict = (
            self.right_operand.to_dict()
            if isinstance(self.right_operand, CobolExpression)
            else self.right_operand
        )

        result.update(
            {
                "operator": self.operator,
                "left_operand": left_dict,
                "right_operand": right_dict,
                "condition_type": self.expression_type,
            }
        )
        return result


class LogicalExpression(CobolExpression):
    """AST node for logical expressions (AND, OR, NOT)."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("LOGICAL", location)
        self.operator = operator
        self.left_condition: CobolExpression | None = None
        self.right_condition: CobolExpression | None = None

    def set_left_condition(self, condition: "CobolExpression") -> None:
        """Set the left condition of the logical expression."""
        self.left_condition = condition
        self.add_child(condition)

    def set_right_condition(self, condition: "CobolExpression") -> None:
        """Set the right condition of the logical expression."""
        self.right_condition = condition
        self.add_child(condition)

    def to_dict(self) -> dict[str, Any]:
        """Convert logical expression to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "operator": self.operator,
                "left_condition": (
                    self.left_condition.to_dict() if self.left_condition else None
                ),
                "right_condition": (
                    self.right_condition.to_dict() if self.right_condition else None
                ),
            }
        )
        return result


class FunctionCall(CobolExpression):
    """AST node for COBOL function calls."""

    def __init__(self, function_name: str, location: SourceLocation):
        super().__init__("FUNCTION", location)
        self.function_name = function_name
        self.function_type = "INTRINSIC"  # INTRINSIC or USER_DEFINED
        self.arguments: list[str | CobolExpression] = []

    def add_argument(self, argument: Union[str, "CobolExpression"]) -> None:
        """Add an argument to the function call."""
        self.arguments.append(argument)
        if isinstance(argument, CobolExpression):
            self.add_child(argument)

    def set_function_type(self, func_type: str) -> None:
        """Set the function type (INTRINSIC or USER_DEFINED)."""
        self.function_type = func_type

    def to_dict(self) -> dict[str, Any]:
        """Convert function call to dictionary representation."""
        result = super().to_dict()

        args_dict: list[Any] = []
        for arg in self.arguments:
            if isinstance(arg, CobolExpression):
                args_dict.append(arg.to_dict())
            else:
                args_dict.append(arg)

        result.update(
            {
                "function_name": self.function_name,
                "function_type": self.function_type,
                "arguments": args_dict,
            }
        )
        return result
