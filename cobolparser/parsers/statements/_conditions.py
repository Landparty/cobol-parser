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

#: Relational words after which a ``TO`` / ``THAN`` connective is dropped.
_RELATIONAL_WORDS = frozenset(
    {
        "EQUAL",
        "EQUALS",
        "GREATER",
        "LESS",
        "=",
        ">",
        "<",
        "NOT_EQUAL",
        "GREATER_OR_EQUAL",
        "LESS_OR_EQUAL",
    }
)

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

# Resolved relational operator names, and each one's negation. Used both to
# fold a leading ``NOT`` into a simple relation (``NOT A = 1`` is ``A NOT =
# 1``, which the cleaning pass already spells NOT_EQUAL) and to expand the
# ``NOT literal`` leg of an abbreviated combined condition.
_NEGATED_RELATIONAL = {
    "EQUAL": "NOT_EQUAL",
    "NOT_EQUAL": "EQUAL",
    "GREATER": "LESS_OR_EQUAL",
    "LESS_OR_EQUAL": "GREATER",
    "LESS": "GREATER_OR_EQUAL",
    "GREATER_OR_EQUAL": "LESS",
}
_RELATIONAL_OPERATORS = frozenset(_NEGATED_RELATIONAL)

# Figurative constants that can stand alone as the object of a relation
# (``IF A = 1 OR SPACES``); a bare one of these after AND/OR is a literal
# leg of an abbreviated combined condition, never a condition-name.
_FIGURATIVE_WORDS = frozenset(
    {
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


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
        value = (token.value or "").replace("'", "''")
        return f"'{value}'"
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
        # ``EQUAL TO`` / ``GREATER THAN`` / ``LESS THAN``: the connective is
        # noise that otherwise leaks into the right-hand operand text
        # (``IF A EQUAL TO B`` used to record right_operand ``"TO B"``).
        # ``cleaned`` keeps the source's case, so compare upper-cased:
        # lower-case source (``if a equal to b``) otherwise kept ``to b``
        # as the right operand and split ``greater or equal`` into an OR.
        if (
            tok in ("TO", "THAN")
            and cleaned
            and cleaned[-1].upper() in _RELATIONAL_WORDS
        ):
            i += 1
            continue
        # ``GREATER [THAN] OR EQUAL [TO]`` / ``LESS [THAN] OR EQUAL [TO]`` is
        # one operator, not an OR of two conditions.
        if (
            tok == "OR"
            and cleaned
            and cleaned[-1].upper() in ("GREATER", "LESS")
            and i + 1 < len(tokens)
            and tokens[i + 1].upper() in ("EQUAL", "EQUALS")
        ):
            cleaned[-1] = (
                "GREATER_OR_EQUAL"
                if cleaned[-1].upper() == "GREATER"
                else "LESS_OR_EQUAL"
            )
            i += 2
            if i < len(tokens) and tokens[i].upper() == "TO":
                i += 1
            continue
        if tok == "NOT" and i + 1 < len(tokens):
            # Resolve the whole operator after NOT before negating it:
            # ``NOT GREATER THAN OR EQUAL TO`` / ``NOT >=`` / ``NOT < =`` is
            # the negation of GREATER_OR_EQUAL / LESS_OR_EQUAL (i.e. LESS /
            # GREATER), not ``NOT GREATER`` followed by an OR or a stray
            # ``=`` in the right-hand operand.
            matched = _match_relational_operator(tokens, i + 1)
            if matched is not None:
                op, i = matched
                cleaned.append(_NEGATED_RELATIONAL[op])
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
            # ``IF A = 1 OR 2`` / ``IF A > 1 AND < 5``: an abbreviated
            # combined relation condition repeats the subject (and, for a
            # bare literal, the operator) of the relation before it.
            right_tokens = _expand_abbreviated_condition(left_expr, cleaned[idx + 1 :])
            right_expr = build_condition_expression(right_tokens, location)
            if left_expr and right_expr:
                logical = LogicalExpression(logical_op, location)
                logical.set_left_condition(left_expr)
                logical.set_right_condition(right_expr)
                return logical

    # Leading NOT: ``NOT A = 1``, ``NOT (A = 1 AND B = 2)``, ``NOT FLAG-ON``.
    # NOT binds tighter than AND/OR, so this runs after the split above
    # (``NOT A = 1 AND B = 2`` negates only the first relation). The
    # negation is folded into a simple relation / class / sign condition's
    # operator and wrapped as a unary LogicalExpression("NOT") otherwise.
    # Previously the word was swallowed into the left operand text
    # (``left_operand="NOT ( A"``).
    if len(cleaned) > 1 and cleaned[0].upper() == "NOT":
        inner = build_condition_expression(cleaned[1:], location)
        if inner is not None and not _is_raw_fallback(inner):
            return _negate_condition(inner, location)

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


def _match_relational_operator(tokens: list[str], start: int) -> tuple[str, int] | None:
    """Match one relational operator at ``tokens[start]``.

    Returns ``(resolved_operator, index_after_operator)`` or ``None``.
    Recognises ``GREATER|LESS [THAN] [OR EQUAL [TO]]``, ``EQUAL[S] [TO]``,
    and the symbols ``>``, ``<``, ``=``, ``>=``, ``<=`` -- the two-character
    ones also when the lexer split them (or the source spaced them) into
    two tokens (``> =``). Trailing ``THAN``/``TO`` noise words are consumed.
    """
    n = len(tokens)
    if start >= n:
        return None
    tok = tokens[start].upper()
    j = start + 1
    if tok in ("GREATER", "LESS"):
        if j < n and tokens[j].upper() == "THAN":
            j += 1
        if (
            j + 1 < n
            and tokens[j].upper() == "OR"
            and tokens[j + 1].upper() in ("EQUAL", "EQUALS")
        ):
            j += 2
            if j < n and tokens[j].upper() == "TO":
                j += 1
            return ("GREATER_OR_EQUAL" if tok == "GREATER" else "LESS_OR_EQUAL"), j
        return ("GREATER" if tok == "GREATER" else "LESS"), j
    if tok in ("EQUAL", "EQUALS"):
        if j < n and tokens[j].upper() == "TO":
            j += 1
        return "EQUAL", j
    if tok in (">", "<"):
        if j < n and tokens[j] == "=":
            return ("GREATER_OR_EQUAL" if tok == ">" else "LESS_OR_EQUAL"), j + 1
        return ("GREATER" if tok == ">" else "LESS"), j
    if tok in (">=", "<="):
        return ("GREATER_OR_EQUAL" if tok == ">=" else "LESS_OR_EQUAL"), j
    if tok == "=":
        return "EQUAL", j
    return None


def _is_raw_fallback(expr: CobolExpression) -> bool:
    """True for the catch-all ``COMPARISON`` node the builder emits when it
    cannot decompose a condition (only ``metadata["raw_condition"]`` set)."""
    return (
        isinstance(expr, ConditionalExpression)
        and expr.operator == "COMPARISON"
        and expr.left_operand is None
    )


def _negate_condition(
    expr: CobolExpression, location: SourceLocation
) -> CobolExpression:
    """Apply a leading ``NOT`` to an already-built condition."""
    if isinstance(expr, ConditionalExpression):
        if expr.operator in _NEGATED_RELATIONAL:
            expr.operator = _NEGATED_RELATIONAL[expr.operator]
            return expr
        if expr.operator.startswith("IS NOT "):
            expr.operator = "IS " + expr.operator[len("IS NOT ") :]
            return expr
        if expr.operator.startswith("IS "):
            expr.operator = "IS NOT " + expr.operator[len("IS ") :]
            return expr
    negated = LogicalExpression("NOT", location)
    negated.set_left_condition(expr)
    return negated


def _rightmost_relation(expr: CobolExpression | None) -> ConditionalExpression | None:
    """The relation condition an abbreviated leg would repeat the subject of:
    the rightmost relational leaf of *expr* (through NOT wrappers)."""
    if isinstance(expr, LogicalExpression):
        if expr.operator == "NOT":
            return _rightmost_relation(expr.left_condition)
        return _rightmost_relation(expr.right_condition)
    if (
        isinstance(expr, ConditionalExpression)
        and expr.operator in _RELATIONAL_OPERATORS
        and isinstance(expr.left_operand, str)
    ):
        return expr
    return None


def _is_literal_leg(tokens: list[str]) -> bool:
    """True when *tokens* is exactly one literal: a re-quoted string, a
    (possibly sign-split) number, or a figurative constant."""
    if len(tokens) == 2 and tokens[0] in ("+", "-"):
        return bool(_NUMERIC_LITERAL_RE.match(tokens[1]))
    if len(tokens) != 1:
        return False
    tok = tokens[0]
    if tok.startswith(("'", '"')):
        return True
    if _NUMERIC_LITERAL_RE.match(tok):
        return True
    return tok.upper() in _FIGURATIVE_WORDS


def _expand_abbreviated_condition(
    left_expr: CobolExpression | None, rest: list[str]
) -> list[str]:
    """Rebuild the right leg of an AND/OR when it has no subject of its own.

    COBOL's abbreviated combined relation condition lets the subject -- and
    the operator -- of the preceding relation be omitted: ``A = 1 OR 2 OR
    3`` means ``A = 1 OR A = 2 OR A = 3`` and ``A > 1 AND < 5`` means ``A >
    1 AND A < 5``. Two shapes are expanded: a leg that *starts with a
    relational operator* (subject prepended) and a leg that is *one bare
    literal* (subject and operator prepended; ``NOT literal`` negates the
    operator). A bare identifier is left alone: without a symbol table it
    is indistinguishable from a level-88 condition-name (``A = 1 OR
    FLAG-ON``), and the CONDITION_NAME reading is the one the analyzers
    resolve. Anything else is returned unchanged.
    """
    if not rest:
        return rest
    subject = _rightmost_relation(left_expr)
    if subject is None or not isinstance(subject.left_operand, str):
        return rest
    first = rest[0].upper()
    if first in COMPARISON_OPS or first in _RELATIONAL_OPERATORS:
        return [subject.left_operand, *rest]
    if _is_literal_leg(rest):
        return [subject.left_operand, subject.operator, *rest]
    if first == "NOT" and _is_literal_leg(rest[1:]):
        return [subject.left_operand, _NEGATED_RELATIONAL[subject.operator], *rest[1:]]
    return rest


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
