"""Shared COBOL condition-expression machinery (M12).

Converts a flat list of condition token strings -- as collected by the IF
and PERFORM parsers -- into a structural expression tree built from
:class:`ConditionalExpression` / :class:`LogicalExpression` nodes.

This logic originally lived on :class:`IfStatementParser`; it was factored
out so PERFORM UNTIL conditions can be decomposed with the exact same
machinery instead of being stored as a single raw joined string (finding
M12). The IF parser's methods now delegate here.
"""

import re

from ...lexer import Token, TokenType
from ...models.ast_base import SourceLocation
from ...models.statements.base import (
    CobolExpression,
    ConditionalExpression,
    LogicalExpression,
)

COMPARISON_OPS = {
    "=": "EQUAL",
    "EQUAL": "EQUAL",
    ">": "GREATER",
    "GREATER": "GREATER",
    "<": "LESS",
    "LESS": "LESS",
    ">=": "GREATER_OR_EQUAL",
    "<=": "LESS_OR_EQUAL",
    "<>": "NOT_EQUAL",
}

# Two-character symbolic operators the lexer tokenizes as two separate
# single-character tokens (never as one combined token) -- recombined during
# the cleaning pass so the comparison scan below sees them whole.
_COMPOUND_SYMBOL_OPS = frozenset({">=", "<=", "<>"})

# Multi-word NOT-prefixed operators normalised during the cleaning pass.
_NEGATED_OPS = {
    "NOT EQUAL": "NOT_EQUAL",
    "NOT =": "NOT_EQUAL",
    "NOT LESS": "GREATER_OR_EQUAL",
    "NOT <": "GREATER_OR_EQUAL",
    "NOT GREATER": "LESS_OR_EQUAL",
    "NOT >": "LESS_OR_EQUAL",
}

# Class-condition and sign-condition keywords (IBM Enterprise COBOL).
# ``A IS [NOT] <word>`` conditions on these get a structured node instead
# of only a metadata raw_condition string (M12).
_CLASS_SIGN_WORDS = {
    "NUMERIC",
    "ALPHABETIC",
    "ALPHABETIC-UPPER",
    "ALPHABETIC-LOWER",
    "DBCS",
    "KANJI",
    "POSITIVE",
    "NEGATIVE",
    "ZERO",
    "ZEROS",
    "ZEROES",
}

# A plausible COBOL data/condition name: letter followed by letters,
# digits, or hyphens. Used to tell a bare condition-name (level-88 style
# ``IF END-OF-FILE``) apart from stray literals in the fallback path.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


def condition_token_text(token: Token) -> str:
    """Text for one condition token, re-quoting string literals.

    The lexer's read_string_literal() strips quote characters when
    building Token.value, so a STRING_LITERAL token's .value alone is
    indistinguishable from an identifier once collected into a flat
    condition-token list. Re-wrap it here, at the one point the token
    type is still known, rather than guessing from the rendered text
    later.
    """
    if token.type == TokenType.STRING_LITERAL:
        return f"'{token.value}'"
    return token.value or str(token.type)


def build_condition_expression(
    tokens: list[str], location: SourceLocation
) -> CobolExpression | None:
    """Convert a flat list of condition token strings into an expression tree.

    Handles simple comparisons (LHS op RHS), NOT-prefixed operators,
    compound conditions joined by AND / OR, and -- structurally since M12 --
    class conditions (``A IS NUMERIC``), sign conditions (``A IS
    POSITIVE``), and bare condition-names.
    """
    # Normalise multi-word operators ("NOT LESS", "NOT EQUAL", etc.) and
    # two-character symbolic operators the lexer emits as separate
    # single-character tokens (">=", "<=", "<>" -- confirmed empirically:
    # the lexer never produces a combined ">=" token, so without this pass
    # the scan below saw a bare ">" and silently swallowed the trailing "="
    # into the right-hand operand text instead of recognising
    # GREATER_OR_EQUAL/LESS_OR_EQUAL/NOT_EQUAL).
    cleaned: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].upper()
        if tok == "NOT" and i + 1 < len(tokens):
            nxt = tokens[i + 1].upper()
            combined = _NEGATED_OPS.get(f"NOT {nxt}")
            if combined:
                cleaned.append(combined)
                i += 2
                continue
        if i + 1 < len(tokens):
            pair = tok + tokens[i + 1].upper()
            if pair in _COMPOUND_SYMBOL_OPS:
                cleaned.append(pair)
                i += 2
                continue
        cleaned.append(tokens[i])
        i += 1

    # Drop a fully-enclosing pair of parentheses so ( X ) recurses as X.
    cleaned = strip_enclosing_parens(cleaned)

    # Split on the lowest-precedence logical operator at the top paren
    # level. COBOL binds AND tighter than OR, so OR is split first (it
    # becomes the tree root) and AND stays nested beneath it. Split on the
    # rightmost operator so the tree is left-associative, matching COBOL's
    # left-to-right evaluation. Parenthesised sub-conditions are skipped
    # here and resolved by the recursive call, e.g. (A OR B) AND C keeps
    # AND as the root.
    for logical_op in ("OR", "AND"):
        idx = find_top_level_operator(cleaned, logical_op)
        if idx is not None:
            left_expr = build_condition_expression(cleaned[:idx], location)
            right_expr = build_condition_expression(cleaned[idx + 1 :], location)
            if left_expr and right_expr:
                logical = LogicalExpression(logical_op, location)
                logical.set_left_condition(left_expr)
                logical.set_right_condition(right_expr)
                return logical

    # Simple comparison: find the first comparison operator token
    upper_cleaned = [t.upper() for t in cleaned]
    op_idx = None
    resolved_op = None
    for idx, tok in enumerate(upper_cleaned):
        if tok in COMPARISON_OPS:
            op_idx = idx
            resolved_op = COMPARISON_OPS[tok]
            break
        if tok in ("NOT_EQUAL", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"):
            op_idx = idx
            resolved_op = tok
            break

    if op_idx is not None and resolved_op:
        left_parts = [t for t in cleaned[:op_idx] if t.upper() != "IS"]
        right_parts = cleaned[op_idx + 1 :]
        lhs = " ".join(left_parts).strip() if left_parts else None
        rhs = " ".join(right_parts).strip() if right_parts else None
        if lhs:
            expr = ConditionalExpression(resolved_op, location)
            expr.set_left_operand(lhs)
            if rhs:
                expr.set_right_operand(rhs)
            return expr

    # M12: class conditions, sign conditions, and bare condition-names get
    # a structured node. metadata.raw_condition is still populated exactly
    # as the historical raw fallback did, for backward compatibility.
    structured = _build_unary_condition(cleaned, location)
    if structured is not None:
        structured._metadata["raw_condition"] = " ".join(cleaned)
        return structured

    # Fallback: wrap entire token list as a raw comparison node
    if cleaned:
        expr = ConditionalExpression("COMPARISON", location)
        expr._metadata["raw_condition"] = " ".join(cleaned)
        return expr

    return None


def _build_unary_condition(
    cleaned: list[str], location: SourceLocation
) -> ConditionalExpression | None:
    """Structured node for a class/sign condition or bare condition-name.

    Recognises ``operand [IS] [NOT] <class-or-sign-word>`` (e.g. ``WS-A IS
    NUMERIC``, ``WS-B NOT POSITIVE``) and single-token condition-names
    (level-88 style ``END-OF-FILE``). Returns ``None`` for anything else so
    the caller keeps the historical raw-string fallback.
    """
    if not cleaned:
        return None
    upper = [t.upper() for t in cleaned]

    if len(cleaned) >= 2 and upper[-1] in _CLASS_SIGN_WORDS:
        class_word = upper[-1]
        rest = cleaned[:-1]
        rest_upper = upper[:-1]
        negated = False
        if rest_upper and rest_upper[-1] == "NOT":
            negated = True
            rest = rest[:-1]
            rest_upper = rest_upper[:-1]
        operand_parts = [t for t, u in zip(rest, rest_upper, strict=True) if u != "IS"]
        if operand_parts:
            operator = f"IS NOT {class_word}" if negated else f"IS {class_word}"
            expr = ConditionalExpression(operator, location)
            expr.set_left_operand(" ".join(operand_parts))
            return expr
        return None

    if (
        len(cleaned) == 1
        and _IDENTIFIER_RE.match(cleaned[0])
        and upper[0] != "NOT"
        and upper[0] not in _CLASS_SIGN_WORDS
    ):
        expr = ConditionalExpression("CONDITION_NAME", location)
        expr.set_left_operand(cleaned[0])
        return expr

    return None


def strip_enclosing_parens(tokens: list[str]) -> list[str]:
    """Strip pair(s) of parentheses that wrap the whole token list.

    ``( A OR B )`` -> ``A OR B`` and ``(( A ))`` -> ``A`` , but a pair that
    closes before the end is left untouched: ``( A ) OR ( B )`` and
    ``( A OR B ) AND C`` keep their parentheses so the split logic can see
    the top-level operator. Unbalanced input is returned unchanged.
    """
    while len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")":
        depth = 0
        encloses = True
        for i, tok in enumerate(tokens):
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                # Opening paren closes before the final token -> it does
                # not enclose the whole expression.
                if depth == 0 and i != len(tokens) - 1:
                    encloses = False
                    break
        if encloses and depth == 0:
            tokens = tokens[1:-1]
        else:
            break
    return tokens


def find_top_level_operator(tokens: list[str], op: str) -> int | None:
    """Index of the rightmost ``op`` token outside any parentheses.

    Returns the rightmost match so the resulting tree is left-associative.
    Operators nested inside parentheses are ignored. Returns ``None`` when
    no top-level occurrence exists.
    """
    depth = 0
    found: int | None = None
    for i, tok in enumerate(tokens):
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif depth == 0 and tok.upper() == op:
            found = i
    return found
