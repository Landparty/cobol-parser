"""
Arithmetic statement AST nodes (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE).
"""

from typing import Any, Union

from ..ast_base import ASTNode, SourceLocation
from .base import CobolExpression, CobolStatement

#: The rounding modes of ``ROUNDED MODE IS mode`` (IBM Enterprise COBOL 6.x,
#: COBOL 2002).
ROUNDING_MODES: frozenset[str] = frozenset(
    {
        "AWAY-FROM-ZERO",
        "NEAREST-AWAY-FROM-ZERO",
        "NEAREST-EVEN",
        "NEAREST-TOWARD-ZERO",
        "PROHIBITED",
        "TOWARD-GREATER",
        "TOWARD-LESSER",
        "TRUNCATION",
    }
)


class _Rounding:
    """Per-receiver ROUNDED bookkeeping shared by the arithmetic nodes (#517).

    ``rounded`` stays the backward-compatible "ROUNDED appeared on some
    receiver" flag; ``rounded_targets`` names the receivers that carry it, in
    source order, and ``rounding_modes`` the ``ROUNDED MODE IS mode`` of
    those that name one. ``COMPUTE B ROUNDED C = ...`` and ``COMPUTE B C
    ROUNDED = ...`` store different values, so they must not share an AST.
    """

    rounded: bool
    rounded_targets: list[str]
    rounding_modes: dict[str, str]

    def _init_rounding(self) -> None:
        self.rounded = False  # True if ROUNDED appeared on any target
        self.rounded_targets = []
        self.rounding_modes = {}

    def set_rounded(
        self, rounded: bool = True, target: str | None = None, mode: str | None = None
    ) -> None:
        """Record ROUNDED (on *target*, with ``MODE IS`` *mode* when given)."""
        self.rounded = rounded
        if rounded and target is not None:
            if target not in self.rounded_targets:
                self.rounded_targets.append(target)
            if mode:
                self.rounding_modes[target] = mode

    def rounding_of(self, receiver: str) -> str:
        """The rounding phrase on *receiver*: ``""``, ``"ROUNDED"`` or
        ``"ROUNDED MODE IS mode"``. A node built without per-receiver
        information (``rounded`` set, no ``rounded_targets``) reports
        ``"ROUNDED"`` for every receiver, as before."""
        if not self.rounded:
            return ""
        if self.rounded_targets and receiver not in self.rounded_targets:
            return ""
        mode = self.rounding_modes.get(receiver)
        return f"ROUNDED MODE IS {mode}" if mode else "ROUNDED"

    def _rounding_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.rounded:
            result["rounded"] = self.rounded
        if self.rounded_targets:
            result["rounded_targets"] = list(self.rounded_targets)
        if self.rounding_modes:
            result["rounding_modes"] = dict(self.rounding_modes)
        return result


class ArithmeticStatement(_Rounding, CobolStatement):
    """Base AST node for arithmetic statements (ADD, SUBTRACT, MULTIPLY, DIVIDE)."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__(statement_type, location)
        self.on_size_error: list[CobolStatement] | None = None
        self.not_on_size_error: list[CobolStatement] | None = None
        self.target: str | None = None  # First/primary target (back-compat)
        self.targets: list[str] = []  # All TO/FROM targets, in order
        self.giving: str | None = None  # First/primary GIVING target (back-compat)
        self.givings: list[str] = []  # All GIVING targets, in order
        self._init_rounding()
        self.is_corresponding: bool = False  # For CORRESPONDING/CORR clause
        # The operands written before TO/FROM/GIVING, duplicates kept, in
        # source order -- set by the ADD/SUBTRACT parsers. ``operands`` cannot
        # answer "which names are addends": ``set_target``/``set_giving``
        # skip a name already present, so ``ADD A B GIVING B`` and
        # ``ADD A GIVING B`` both leave ``[A, B]`` there. ``None`` when the
        # node was built some other way. Not serialized.
        self.source_operands: list[str] | None = None

    def set_target(self, target: str) -> None:
        """Add a TO/FROM target (result stored in target).

        COBOL allows multiple comma/space-separated targets after TO/FROM
        (``ADD A TO B, C``); ``target`` keeps holding the first one for
        backward compatibility with single-target callers, while ``targets``
        accumulates the full ordered list.
        """
        if self.target is None:
            self.target = target
        self.targets.append(target)
        self._add_unique_operand(target)

    def set_corresponding(self, is_corresponding: bool = True) -> None:
        """Set whether this is an ADD/SUBTRACT CORRESPONDING statement."""
        self.is_corresponding = is_corresponding

    def set_giving(self, giving: str) -> None:
        """Add a GIVING result target (result stored in giving).

        COBOL allows a comma/space-separated list of GIVING targets
        (``ADD A TO B GIVING C, D``); ``giving`` keeps holding the first one
        for backward compatibility with single-target callers, while
        ``givings`` accumulates the full ordered list.
        """
        if self.giving is None:
            self.giving = giving
        self.givings.append(giving)
        self._add_unique_operand(giving)

    def set_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("on_size_error", statements)

    def set_not_on_size_error_clause(self, statements: list["CobolStatement"]) -> None:
        self._set_clause("not_on_size_error", statements)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.target:
            result["target"] = self.target
        if self.targets:
            result["targets"] = self.targets
        if self.giving:
            result["giving"] = self.giving
        if self.givings:
            result["givings"] = self.givings
        result.update(self._rounding_dict())
        if self.is_corresponding:
            result["is_corresponding"] = self.is_corresponding
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
        self.remainder: str | None = None  # For REMAINDER clause
        #: ``"BY"`` or ``"INTO"`` -- the two forms invert dividend/divisor
        #: order (``DIVIDE a BY b`` computes a/b; ``DIVIDE a INTO b``
        #: computes b/a), so without this no consumer could evaluate a
        #: DIVIDE from the AST at all. ``None`` only when the separator was
        #: missing/unparsable.
        self.division_mode: str | None = None

    def set_division_mode(self, mode: str) -> None:
        """Record which separator keyword (BY or INTO) the source used."""
        self.division_mode = mode

    def set_remainder(self, remainder: str) -> None:
        """Set the REMAINDER clause's target identifier."""
        self.remainder = remainder
        self._add_unique_operand(remainder)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.remainder:
            result["remainder"] = self.remainder
        if self.division_mode:
            result["division_mode"] = self.division_mode
        return result


class ComputeStatement(_Rounding, CobolStatement):
    """AST node for COMPUTE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("COMPUTE", location)
        self.targets: list[str] = []
        self._init_rounding()
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
        result.update(self._rounding_dict())
        result.update(
            self._serialize_clauses(
                "on_size_error", "not_on_size_error", omit_empty=True
            )
        )
        return result
