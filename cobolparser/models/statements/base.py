"""
Base classes for COBOL statement and expression AST nodes.
"""

from typing import Any, Union

from ..ast_base import ASTNode, SourceLocation


def _serialize_operand(operand: Any) -> Any:
    """Serialize a binary-expression operand to a dict or passthrough value."""
    return operand.to_dict() if isinstance(operand, ASTNode) else operand


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
        """Add an operand to the statement (allowing duplicates)."""
        self.operands.append(operand)

    def _add_unique_operand(self, operand: str, *, front: bool = False) -> None:
        """Add an operand only if not already present.

        Consolidates the ``if x not in self.operands: self.operands.append(x)``
        (or ``insert(0, x)``) idiom repeated across the statement model layer.

        Args:
            operand: The operand to add.
            front: When True, insert at the front of the list instead of
                appending (preserves ``insert(0, ...)`` ordering semantics).
        """
        if operand not in self.operands:
            if front:
                self.operands.insert(0, operand)
            else:
                self.operands.append(operand)

    def _set_clause(self, attr: str, statements: list["CobolStatement"]) -> None:
        """Set a clause attribute and register its statements as children."""
        setattr(self, attr, statements)
        for stmt in statements:
            self.add_child(stmt)

    def _serialize_clauses(
        self, *names: str, omit_empty: bool = False
    ) -> dict[str, Any]:
        """Serialize one or more clause-list attributes to dicts.

        For each attribute name, produces ``[s.to_dict() for s in (value or [])]``.
        When ``omit_empty`` is True, a key is skipped entirely if its list is
        empty or None.
        """
        result: dict[str, Any] = {}
        for name in names:
            value = getattr(self, name) or []
            if omit_empty and not value:
                continue
            result[name] = [s.to_dict() for s in value]
        return result

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
        # M12: optional structural decomposition of a raw condition. Used by
        # the PERFORM parser: `until_condition` remains the historical
        # CobolExpression("CONDITION") whose operands hold the raw joined
        # string, while `condition_tree` carries the ConditionalExpression /
        # LogicalExpression tree built from the same tokens.
        self.condition_tree: CobolExpression | None = None

    def set_condition_tree(self, tree: "CobolExpression") -> None:
        """Attach a structural decomposition of this raw condition (M12).

        The raw ``operands`` string is left untouched for backward
        compatibility; the tree is additive and also registered as a child
        so generic AST traversal reaches it.
        """
        self.condition_tree = tree
        self.add_child(tree)

    def to_dict(self) -> dict[str, Any]:
        """Convert expression to dictionary representation."""
        result: dict[str, Any] = {
            "node_type": self.node_type,
            "expression_type": self.expression_type,
            "operands": self.operands,
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }
        # Additive key: only present when a structural tree was attached, so
        # dict output for all pre-M12 shapes stays byte-identical.
        if self.condition_tree is not None:
            result["condition_tree"] = self.condition_tree.to_dict()
        return result


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
        result.update(
            {
                "operator": self.operator,
                "left_operand": _serialize_operand(self.left_operand),
                "right_operand": _serialize_operand(self.right_operand),
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
        result.update(
            {
                "operator": self.operator,
                "left_operand": _serialize_operand(self.left_operand),
                "right_operand": _serialize_operand(self.right_operand),
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
