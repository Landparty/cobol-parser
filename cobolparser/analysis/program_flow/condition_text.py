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

    # Check for condition_tree on CobolExpression wrapper nodes
    # (e.g., PERFORM UNTIL wraps the condition in a CobolExpression with
    # a condition_tree attribute containing the structural tree).
    if hasattr(expr, "condition_tree") and expr.condition_tree is not None:
        tree_text = render_condition_text(expr.condition_tree)
        if tree_text and tree_text != expr.expression_type:
            return tree_text

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
        left = _render_value(expr.left_operand, expr.right_operand)
        right = (
            _render_value(expr.right_operand, expr.left_operand)
            if expr.right_operand is not None
            else ""
        )
        return f"{left} {symbol} {right}".strip()
    if expr.operator == "CONDITION_NAME" and expr.left_operand is not None:
        return _render_value(expr.left_operand)
    if expr.operator.startswith("IS") and expr.left_operand is not None:
        return f"{_render_value(expr.left_operand)} {expr.operator}"
    return None


def _render_value(
    operand: str | CobolExpression, partner: str | CobolExpression | None = None
) -> str:
    """Render a single operand -- a raw string, or a nested expression.

    The partner operand is used to decide if this operand needs quotes (i.e.,
    if it's a string literal being compared with an identifier).
    """
    if isinstance(operand, str):
        # Heuristic: if it's a single character that's not a digit, and it's
        # being compared with an identifier (not a number), add quotes.
        # This handles common string literals like 'Y', 'N' from parsed COBOL.
        if len(operand) == 1 and not operand.isdigit():
            # Check if partner looks like a number or identifier
            partner_str = str(partner) if partner is not None else ""
            # If partner is all digits, assume this operand is also numeric
            # If partner has hyphens, it's likely an identifier, so this could be a string literal
            if partner_str and not partner_str.replace("-", "").isdigit():
                # Partner has non-digit/non-hyphen chars, likely an identifier
                return f"'{operand}'"
        return operand
    return render_condition_text(operand)
