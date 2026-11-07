"""
Base classes for COBOL statement and expression AST nodes.
"""

from collections.abc import Iterable, Iterator
from typing import Any, Literal, NamedTuple, Union

from ..ast_base import ASTNode, SourceLocation


def _serialize_operand(operand: Any) -> Any:
    """Serialize a binary-expression operand to a dict or passthrough value."""
    return operand.to_dict() if isinstance(operand, ASTNode) else operand


# ---------------------------------------------------------------------------
# Nested statement bodies: the one list of clause attributes
# ---------------------------------------------------------------------------
#
# Every statement attribute that holds a nested body of statements is named
# here, and nowhere else. Analyzers walk nested statements through
# ``CobolStatement.iter_clause_bodies()`` / ``iter_child_statements()`` or the
# module-level ``walk_statements()``; none keeps its own attribute list. Ten
# private copies used to drift (one missed ``not_at_eop_clause``, several
# missed RECEIVE's ``NO DATA`` / ``WITH DATA``, one never entered SEARCH WHEN
# bodies), the same drift behind the old paragraph-swallow bugs. A statement
# node that gains a new clause body adds its attribute here, and
# ``tests/unit/models/test_statement_bodies.py`` fails until it does.

#: IF's two arms.
BRANCH_BODY_ATTRS: tuple[str, ...] = ("then_statements", "else_statements")

#: An inline ``PERFORM ... END-PERFORM`` body.
LOOP_BODY_ATTRS: tuple[str, ...] = ("inline_statements",)

#: Conditional handler bodies, as (positive, negative) pairs: the two
#: outcomes of one runtime test (an exception, end of file, an overflow, a
#: missing message), so a pair with either side written is one decision.
HANDLER_CLAUSE_PAIRS: tuple[tuple[str, str], ...] = (
    ("at_end_clause", "not_at_end_clause"),
    ("invalid_key_clause", "not_invalid_key_clause"),
    ("at_eop_clause", "not_at_eop_clause"),
    ("on_size_error", "not_on_size_error"),
    ("on_overflow", "not_on_overflow"),
    ("on_exception", "not_on_exception"),
    ("no_data_clause", "with_data_clause"),
)

#: Every handler body attribute, flattened from :data:`HANDLER_CLAUSE_PAIRS`.
HANDLER_CLAUSE_ATTRS: tuple[str, ...] = tuple(
    attr for pair in HANDLER_CLAUSE_PAIRS for attr in pair
)

#: The COBOL phrase each handler body is written with.
HANDLER_CLAUSE_PHRASES: dict[str, str] = {
    "at_end_clause": "AT END",
    "not_at_end_clause": "NOT AT END",
    "invalid_key_clause": "INVALID KEY",
    "not_invalid_key_clause": "NOT INVALID KEY",
    "at_eop_clause": "AT END-OF-PAGE",
    "not_at_eop_clause": "NOT AT END-OF-PAGE",
    "on_size_error": "ON SIZE ERROR",
    "not_on_size_error": "NOT ON SIZE ERROR",
    "on_overflow": "ON OVERFLOW",
    "not_on_overflow": "NOT ON OVERFLOW",
    "on_exception": "ON EXCEPTION",
    "not_on_exception": "NOT ON EXCEPTION",
    "no_data_clause": "NO DATA",
    "with_data_clause": "WITH DATA",
}

#: Attributes whose value is a WHEN arm (EVALUATE's ``WhenClause`` nodes,
#: SEARCH's ``{"condition", "statements"}`` dicts) or a list of them, rather
#: than a statement list.
WHEN_ARM_ATTRS: tuple[str, ...] = ("when_clauses", "default_when")

#: Attributes whose value is itself a ``list[CobolStatement]`` (or None).
STATEMENT_LIST_ATTRS: tuple[str, ...] = (
    BRANCH_BODY_ATTRS + LOOP_BODY_ATTRS + HANDLER_CLAUSE_ATTRS
)

#: Every attribute that holds a nested statement body, in any shape.
NESTED_BODY_ATTRS: tuple[str, ...] = STATEMENT_LIST_ATTRS + WHEN_ARM_ATTRS

BodyKind = Literal["branch", "loop", "handler"]


class ClauseBody(NamedTuple):
    """One nested statement body of a statement.

    *attr* is the attribute it came from; *kind* is ``"branch"`` (an IF arm,
    an EVALUATE / SEARCH WHEN arm, WHEN OTHER), ``"loop"`` (an inline
    PERFORM body) or ``"handler"`` (AT END, INVALID KEY, ON SIZE ERROR, ...).
    For a ``when_clauses`` arm, *position* is its 1-based position and *clause*
    the ``WhenClause`` / SEARCH WHEN dict; for ``default_when``, *clause* is
    the WHEN OTHER ``WhenClause``.
    """

    attr: str
    kind: BodyKind
    statements: list["CobolStatement"]
    position: int | None = None
    clause: Any = None


def _when_arm_statements(clause: Any) -> list["CobolStatement"]:
    """The statements of one WHEN arm, whichever shape it has."""
    if isinstance(clause, dict):
        body = clause.get("statements")
    else:
        body = getattr(clause, "statements", None)
    return body if isinstance(body, list) else []


def iter_clause_bodies(
    statement: Any,
    *,
    include_handlers: bool = True,
    include_loops: bool = True,
    include_empty: bool = False,
) -> Iterator[ClauseBody]:
    """Every nested statement body of *statement*, in source order.

    IF THEN / ELSE, the inline PERFORM body, each handler body, then each
    WHEN arm and WHEN OTHER. (A statement holds one handler family at most,
    and SEARCH writes AT END before its WHENs, so this is source order.)
    Works on any object: a node without these attributes yields nothing.

    *include_handlers* / *include_loops* leave out handler bodies / inline
    PERFORM bodies for a walker that treats them separately. An empty body
    list (an IF with no ELSE, a WHEN with no statement) is skipped unless
    *include_empty*; an attribute that is None or absent never yields.
    """
    for attr in BRANCH_BODY_ATTRS:
        yield from _list_body(statement, attr, "branch", include_empty)
    if include_loops:
        for attr in LOOP_BODY_ATTRS:
            yield from _list_body(statement, attr, "loop", include_empty)
    if include_handlers:
        for attr in HANDLER_CLAUSE_ATTRS:
            yield from _list_body(statement, attr, "handler", include_empty)
    when_clauses = getattr(statement, "when_clauses", None)
    if isinstance(when_clauses, list):
        for position, clause in enumerate(when_clauses, start=1):
            body = _when_arm_statements(clause)
            if body or include_empty:
                yield ClauseBody("when_clauses", "branch", body, position, clause)
    default_when = getattr(statement, "default_when", None)
    if default_when is not None:
        body = _when_arm_statements(default_when)
        if body or include_empty:
            yield ClauseBody("default_when", "branch", body, None, default_when)


def _list_body(
    statement: Any, attr: str, kind: BodyKind, include_empty: bool
) -> Iterator[ClauseBody]:
    value = getattr(statement, attr, None)
    if isinstance(value, list) and (value or include_empty):
        yield ClauseBody(attr, kind, value)


def walk_statements(
    statements: Iterable[Any],
    *,
    include_handlers: bool = True,
    include_loops: bool = True,
) -> Iterator[Any]:
    """Every statement in *statements* and, depth first, every statement
    nested in their clause bodies (:func:`iter_clause_bodies`), in source
    order. Iterative, so nesting depth never meets the recursion limit; a
    node reached twice (a shared list) is yielded once."""
    stack: list[Any] = list(reversed(list(statements)))
    seen: set[int] = set()
    while stack:
        stmt = stack.pop()
        if id(stmt) in seen:
            continue
        seen.add(id(stmt))
        yield stmt
        nested: list[Any] = []
        for body in iter_clause_bodies(
            stmt, include_handlers=include_handlers, include_loops=include_loops
        ):
            nested.extend(body.statements)
        stack.extend(reversed(nested))


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

    def iter_clause_bodies(
        self,
        *,
        include_handlers: bool = True,
        include_loops: bool = True,
        include_empty: bool = False,
    ) -> Iterator[ClauseBody]:
        """This statement's nested statement bodies; see the module-level
        :func:`iter_clause_bodies`."""
        return iter_clause_bodies(
            self,
            include_handlers=include_handlers,
            include_loops=include_loops,
            include_empty=include_empty,
        )

    def iter_child_statements(
        self, *, include_handlers: bool = True, include_loops: bool = True
    ) -> Iterator["CobolStatement"]:
        """The statements directly nested in this statement's clause bodies
        (not their own nested ones), in source order."""
        for body in iter_clause_bodies(
            self, include_handlers=include_handlers, include_loops=include_loops
        ):
            yield from body.statements

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
    """AST node for logical expressions (AND, OR, NOT).

    ``AND`` / ``OR`` are binary: both ``left_condition`` and
    ``right_condition`` are set. ``NOT`` is unary: the negated condition is
    ``left_condition`` and ``right_condition`` stays ``None`` (``to_dict()``
    emits ``"right_condition": null``). The parser only builds a ``NOT``
    node for a negation it cannot fold into the operand itself -- ``NOT A =
    1`` becomes ``NOT_EQUAL`` directly, the way ``A NOT = 1`` always has;
    ``NOT (A = 1 AND B = 2)`` and ``NOT FLAG-ON`` get the wrapper.
    """

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
