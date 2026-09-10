"""Renders a COBOL condition expression tree back to human-readable text.

The IF/EVALUATE/PERFORM-UNTIL parsers (see ``parsers/statements/
_conditions.py`` and ``parsers/statements/perform_parser.py``) build a
structural ``ConditionalExpression``/``LogicalExpression`` tree for every
condition. Nothing outside the parser layer read that tree for its actual
operator/operand text before this module existed -- callers instead read
``expression_type`` (the node's type TAG, e.g. "COMPARISON", never the
condition itself). This module is the shared renderer that fixes that: it
walks the tree and reconstructs COBOL-like text ("WS-EOF-SW = 'Y'"), falling
back gracefully through raw-string sources for any node shape it doesn't
recognise structurally.
"""

from __future__ import annotations

from ...models.statements.base import (
    CobolExpression,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)

# ConditionalExpression.operator values that are genuine binary comparisons
# (see parsers/statements/_conditions.py's COMPARISON_OPS / _NEGATED_OPS) --
# mapped back to the symbol a human would have typed.
_COMPARISON_SYMBOLS: dict[str, str] = {
    "EQUAL": "=",
    "GREATER": ">",
    "LESS": "<",
    "GREATER_OR_EQUAL": ">=",
    "LESS_OR_EQUAL": "<=",
    "NOT_EQUAL": "<>",
}


def render_condition_text(expr: CobolExpression | None) -> str:
    """Render a condition expression tree as human-readable COBOL text.

    Falls back, in order, to: a structural condition_tree (ConditionalExpression
    or LogicalExpression built by the parser), the node's raw ``operands[0]``
    (the verbatim joined source string PERFORM UNTIL's wrapper node carries),
    ``metadata["raw_condition"]`` (the catch-all comparison wrapper
    ``_conditions.py`` builds when it can't structurally decompose a
    condition), then the node's own ``expression_type`` tag as a last
    resort -- so every caller gets *something*, even for a partially-built
    or synthetic node.
    """
    if expr is None:
        return ""

    if isinstance(expr, LogicalExpression):
        left = render_condition_text(expr.left_condition)
        if expr.right_condition is None:
            # Unary NOT: the negated condition is ``left_condition`` alone.
            return f"{expr.operator} ({left})" if left else expr.operator
        if isinstance(expr.left_condition, LogicalExpression):
            left = f"({left})"
        right = render_condition_text(expr.right_condition)
        if isinstance(expr.right_condition, LogicalExpression):
            right = f"({right})"
        return f"{left} {expr.operator} {right}".strip()

    if isinstance(expr, FunctionCall):
        args = ", ".join(_render_value(arg) for arg in expr.arguments)
        return f"{expr.function_name}({args})"

    if isinstance(expr, ConditionalExpression):
        text = _render_conditional(expr)
        if text is not None:
            return text

    if expr.operands:
        return expr.operands[0]
    raw = expr.get_metadata("raw_condition")
    if raw:
        return str(raw)
    return expr.expression_type


def _render_conditional(expr: ConditionalExpression) -> str | None:
    """Structural rendering for ConditionalExpression, or None to fall back."""
    symbol = _COMPARISON_SYMBOLS.get(expr.operator)
    if symbol is not None and expr.left_operand is not None:
        left = _render_value(expr.left_operand)
        right = (
            _render_value(expr.right_operand) if expr.right_operand is not None else ""
        )
        return f"{left} {symbol} {right}".strip()
    if expr.operator == "CONDITION_NAME" and expr.left_operand is not None:
        return _render_value(expr.left_operand)
    if expr.operator.startswith("IS") and expr.left_operand is not None:
        return f"{_render_value(expr.left_operand)} {expr.operator}"
    return None


def _render_value(operand: str | CobolExpression) -> str:
    """Render a single operand -- a raw string, or a nested expression."""
    if isinstance(operand, str):
        return operand
    return render_condition_text(operand)
