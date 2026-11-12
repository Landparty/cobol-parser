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
from dataclasses import dataclass
from typing import Any

from ..._literals import is_quoted_literal
from ..._vocabulary import FIGURATIVE_CONSTANTS
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
    # MF / GnuCOBOL spell it EQUALS too; every multi-word form below
    # (`NOT EQUALS`, `GREATER OR EQUALS`) already accepted it, the bare
    # relation did not and fell back to an operand-less COMPARISON node.
    "EQUALS": "EQUAL",
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

# A plausible COBOL data/condition name: a user-defined word of letters,
# digits and hyphens with at least one letter, not starting or ending with
# a hyphen. Used to tell a bare condition-name (level-88 style ``IF
# END-OF-FILE``) apart from stray literals in the fallback path. A word may
# start with a digit (``88-EXP-TXN-AVANCE``, ``1000-READ``): requiring a
# leading letter left such a condition an empty COMPARISON, so two different
# ones compared equal and lint reported a false duplicate-branch.
_IDENTIFIER_RE = re.compile(
    r"^(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$"
)

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

#: Attribute set on a relation whose operator a leading ``NOT`` was folded
#: into (``NOT A = 1`` built as ``A NOT_EQUAL 1``): the operator as written,
#: before the fold. An abbreviated leg after it repeats *that* operator --
#: IBM defines ``NOT a = b OR c`` as ``(NOT a = b) OR (a = c)`` (#329).
_WRITTEN_OPERATOR_ATTR = "_abbreviation_operator"

# Figurative constants that can stand alone as the object of a relation
# (``IF A = 1 OR SPACES``); a bare one of these after AND/OR is a literal
# leg of an abbreviated combined condition, never a condition-name.
_FIGURATIVE_WORDS = FIGURATIVE_CONSTANTS
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


@dataclass(frozen=True)
class ConditionSymbols:
    """What the already-parsed DATA DIVISION says about a bare name (#562).

    The PROCEDURE DIVISION is parsed after the DATA DIVISION, so the
    condition builder can tell a level-88 condition-name from an ordinary
    data item: the leg ``WS-B`` of ``IF A = 'X' OR WS-B`` is an abbreviated
    relation (``A = WS-B``) when WS-B is a plain data item, and a
    condition-name test when it is a level-88 name. Both sets hold
    upper-cased names; a name in neither (an unexpanded COPY member, a
    SPECIAL-NAMES switch condition) keeps the CONDITION_NAME reading.
    """

    data_names: frozenset[str] = frozenset()
    condition_names: frozenset[str] = frozenset()

    def is_data_reference(self, tokens: list[str]) -> bool:
        """True when *tokens* is one reference (``name [OF|IN q]...
        [(subscripts)]``) to a declared data item that is not also a
        level-88 condition-name anywhere in the program."""
        if not tokens or not _is_condition_name_reference(
            tokens, [t.upper() for t in tokens]
        ):
            return False
        name = tokens[0].upper()
        return name in self.data_names and name not in self.condition_names


def condition_symbols(context: Any) -> ConditionSymbols | None:
    """The :class:`ConditionSymbols` a statement parser's ParseContext
    carries, or None when there is no context (a standalone parse)."""
    if context is None:
        return None
    data_names = getattr(context, "known_data_names", None)
    condition_names = getattr(context, "condition_names", None)
    if not isinstance(data_names, frozenset) or not data_names:
        return None
    return ConditionSymbols(
        data_names=data_names,
        condition_names=(
            condition_names if isinstance(condition_names, frozenset) else frozenset()
        ),
    )


def typed_literal_prefix(token: Token) -> str:
    """The upper-cased type prefix of a typed STRING_LITERAL token (``X``,
    ``Z``, ``N``, ``NX``, ``G``, ``U``, ``UX``, ...) or ``""``.

    The lexer keeps a typed literal's content in ``value`` and its source
    text in ``raw_value`` (``X'00'``); the prefix is what precedes the
    first quote of ``raw_value``.
    """
    raw = token.raw_value
    if token.type != TokenType.STRING_LITERAL or not raw:
        return ""
    for index, ch in enumerate(raw):
        if ch in "\"'":
            prefix = raw[:index].upper()
            return prefix if prefix.isalpha() else ""
    return ""


_UNSIGNED_NUMBER_RE = re.compile(r"^(?:\d+(?:[.,]\d+)?|[.,]\d+)$")


def join_operand(parts: list[str]) -> str:
    """*parts* joined with spaces, a sign token folded into the number it
    signs (#747): the lexer splits ``+100`` into ``+`` and ``100``, and
    ``"+ 100"`` reads as text rather than as a signed literal. Only a sign
    that leads the operand or follows ``(`` is a sign; ``A - 1`` keeps its
    binary minus.
    """
    out: list[str] = []
    for part in parts:
        if (
            out
            and out[-1] in ("+", "-")
            and (len(out) == 1 or out[-2] == "(")
            and _UNSIGNED_NUMBER_RE.match(part)
        ):
            out[-1] += part
        else:
            out.append(part)
    return " ".join(out).strip()


def condition_token_text(token: Token) -> str:
    """Text for one condition token, re-quoting string literals.

    The lexer's read_string_literal() strips quote characters when
    building Token.value, so a STRING_LITERAL token's .value alone is
    indistinguishable from an identifier once collected into a flat
    condition-token list. Re-wrap it here, at the one point the token
    type is still known, rather than guessing from the rendered text
    later. A typed literal keeps its prefix (#331): ``X'0000'`` is two
    bytes, and re-quoted bare it read as the four characters ``'0000'``.
    """
    if token.type == TokenType.STRING_LITERAL:
        value = (token.value or "").replace("'", "''")
        return f"{typed_literal_prefix(token)}'{value}'"
    return token.value or str(token.type)


def build_condition_expression(
    tokens: list[str],
    location: SourceLocation,
    *,
    subject: ConditionalExpression | None = None,
    symbols: ConditionSymbols | None = None,
) -> CobolExpression | None:
    """Convert a flat list of condition token strings into an expression tree.

    Handles simple comparisons (LHS op RHS), NOT-prefixed operators,
    compound conditions joined by AND / OR, and -- structurally since M12 --
    class conditions (``A IS NUMERIC``), sign conditions (``A IS
    POSITIVE``), and bare condition-names.

    *subject* is the relation an abbreviated combined condition would
    repeat the subject (and operator) of: the relation to the left of the
    AND/OR this leg follows. It is threaded through the recursion so a leg
    nested under a further AND/OR, or inside parentheses, still expands --
    ``A = 1 OR 2 AND 3`` is ``A = 1 OR (A = 2 AND A = 3)``, and ``A = 1 OR
    (2 AND 3)`` the same; expanding only the whole right-hand leg left both
    with two operand-less COMPARISON nodes.

    *symbols* (from the parsed DATA DIVISION) lets a bare data-name leg
    expand like a literal one: ``A = B OR C`` is ``A = B OR A = C`` when C
    is a plain data item, not a level-88 condition-name (#562).
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
    # becomes the tree root) and AND stays nested beneath it. Every
    # top-level occurrence is split in one pass and the legs folded from the
    # left, so the tree is left-associative, matching COBOL's left-to-right
    # evaluation. Parenthesised sub-conditions are skipped here and resolved
    # by the recursive call, e.g. (A OR B) AND C keeps AND as the root.
    # One pass, not one recursion per operator: a chain of ~1,000 terms hit
    # Python's recursion limit and the whole IF was dropped (#375).
    for logical_op in ("OR", "AND"):
        indexes = find_top_level_operators(cleaned, logical_op)
        if not indexes:
            continue
        bounds = [-1, *indexes, len(cleaned)]
        legs: list[CobolExpression] = []
        for start, end in zip(bounds, bounds[1:], strict=False):
            # ``IF A = 1 OR 2`` / ``IF A > 1 AND < 5``: an abbreviated
            # combined relation condition repeats the subject (and, for a
            # bare literal, the operator) of the relation before it -- the
            # rightmost relation of the legs to its left, or, when those are
            # abbreviated all the way down, the one handed in.
            leg_subject = (_rightmost_relation(legs[-1]) if legs else None) or subject
            leg = build_condition_expression(
                cleaned[start + 1 : end], location, subject=leg_subject, symbols=symbols
            )
            if leg is None:
                break
            legs.append(leg)
        else:
            return _fold_logical(logical_op, legs, location)

    # A leaf under an AND/OR: expand the abbreviated forms (a leg that
    # starts with a relational operator, a bare literal, ``NOT literal``)
    # against the relation to the left. Anything else is left alone.
    if subject is not None:
        cleaned = _expand_abbreviated_condition(subject, cleaned, symbols)

    # Leading NOT: ``NOT A = 1``, ``NOT (A = 1 AND B = 2)``, ``NOT FLAG-ON``.
    # NOT binds tighter than AND/OR, so this runs after the split above
    # (``NOT A = 1 AND B = 2`` negates only the first relation). The
    # negation is folded into a simple relation / class / sign condition's
    # operator and wrapped as a unary LogicalExpression("NOT") otherwise.
    # Previously the word was swallowed into the left operand text
    # (``left_operand="NOT ( A"``).
    if len(cleaned) > 1 and cleaned[0].upper() == "NOT":
        inner = build_condition_expression(cleaned[1:], location, symbols=symbols)
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
        lhs = join_operand(left_parts) if left_parts else None
        rhs = join_operand(right_parts) if right_parts else None
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
            if not hasattr(expr, _WRITTEN_OPERATOR_ATTR):
                setattr(expr, _WRITTEN_OPERATOR_ATTR, expr.operator)
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


#: Up to this many legs, an AND/OR chain is the left-deep tree it always
#: was. A longer one is folded pairwise so the tree stays O(log n) deep:
#: every walker over it (``to_dict``, rendering, the analyzers) recurses on
#: depth, and a left-deep chain of ~1,000 terms overflowed them (#375).
_MAX_LEFT_DEEP_LEGS = 64


def _fold_logical(
    operator: str, legs: list[CobolExpression], location: SourceLocation
) -> CobolExpression:
    """Join *legs* (at least two) with *operator*, left to right."""

    def join(left: CobolExpression, right: CobolExpression) -> CobolExpression:
        logical = LogicalExpression(operator, location)
        logical.set_left_condition(left)
        logical.set_right_condition(right)
        return logical

    if len(legs) <= _MAX_LEFT_DEEP_LEGS:
        tree = legs[0]
        for leg in legs[1:]:
            tree = join(tree, leg)
        return tree
    # AND / OR are associative, so pairing neighbours keeps the meaning and
    # the left-to-right order of the legs.
    level = legs
    while len(level) > 1:
        paired = [join(a, b) for a, b in zip(level[::2], level[1::2], strict=False)]
        if len(level) % 2:
            paired.append(level[-1])
        level = paired
    return level[0]


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
    if tok.startswith(("'", '"')) or is_quoted_literal(tok):
        return True
    if _NUMERIC_LITERAL_RE.match(tok):
        return True
    return tok.upper() in _FIGURATIVE_WORDS


def _expand_abbreviated_condition(
    subject: ConditionalExpression,
    rest: list[str],
    symbols: ConditionSymbols | None = None,
) -> list[str]:
    """Rebuild one leg of an AND/OR when it has no subject of its own.

    COBOL's abbreviated combined relation condition lets the subject -- and
    the operator -- of the preceding relation be omitted: ``A = 1 OR 2 OR
    3`` means ``A = 1 OR A = 2 OR A = 3`` and ``A > 1 AND < 5`` means ``A >
    1 AND A < 5``. Two shapes are expanded: a leg that *starts with a
    relational operator*, optionally after ``IS`` (subject prepended) and a
    leg that is *one bare literal* (subject and operator prepended; ``NOT
    literal`` negates the operator). A bare identifier expands the same way
    only when *symbols* says it is a declared data item that is not a
    level-88 condition-name (#562); otherwise it is left alone -- without
    a symbol table it is indistinguishable from a condition-name (``A = 1
    OR FLAG-ON``), and the CONDITION_NAME reading is the one the analyzers
    resolve. Anything else is returned unchanged.
    *subject* is the relation the leg repeats -- see
    :func:`build_condition_expression`.
    """
    if not rest:
        return rest
    if not isinstance(subject.left_operand, str):
        return rest
    # The relation's operator as written: a leading NOT negates only its own
    # relation, never the legs that abbreviate it (#329).
    operator = getattr(subject, _WRITTEN_OPERATOR_ATTR, subject.operator)
    if len(rest) > 1 and rest[0].upper() == "IS":
        # ``A > 1 AND IS < 5``: the optional IS that opens a relational
        # operator survives cleaning when the leg has no subject before it.
        nxt = rest[1].upper()
        if nxt == "NOT" or nxt in COMPARISON_OPS or nxt in _RELATIONAL_OPERATORS:
            rest = rest[1:]
    first = rest[0].upper()
    if first in COMPARISON_OPS or first in _RELATIONAL_OPERATORS:
        return [subject.left_operand, *rest]
    if _is_literal_leg(rest):
        return [subject.left_operand, operator, *rest]
    if first == "NOT" and _is_literal_leg(rest[1:]):
        return [subject.left_operand, _NEGATED_RELATIONAL[operator], *rest[1:]]
    if symbols is not None:
        # The written operator (#329) for a data-name leg too (#562).
        if symbols.is_data_reference(rest):
            return [subject.left_operand, operator, *rest]
        if first == "NOT" and symbols.is_data_reference(rest[1:]):
            return [
                subject.left_operand,
                _NEGATED_RELATIONAL[operator],
                *rest[1:],
            ]
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

    user_class = _build_user_class_or_omitted(cleaned, upper, location)
    if user_class is not None:
        return user_class

    if (
        _is_condition_name_reference(cleaned, upper)
        and upper[0] != "NOT"
        and upper[0] not in _CLASS_SIGN_WORDS
    ):
        # A qualified / subscripted condition-name (``CN1 (1)``, ``EOF-SW OF
        # IN-REC``) is as much a condition-name as a bare one; only the
        # single-token form was recognised, the rest fell back to an
        # operand-less COMPARISON node.
        expr = ConditionalExpression("CONDITION_NAME", location)
        expr.set_left_operand(" ".join(cleaned))
        return expr

    return None


def _build_user_class_or_omitted(
    cleaned: list[str], upper: list[str], location: SourceLocation
) -> ConditionalExpression | None:
    """``operand [IS] [NOT] OMITTED`` and ``operand IS [NOT] class-name`` (#539).

    A class-name is defined in SPECIAL-NAMES (``CLASS VALID-CODE IS 'A'
    THRU 'F'``), which this builder cannot see, so the class form is
    recognised by its shape: an ``IS`` after a data reference, then an
    optional ``NOT`` and one COBOL word that is not a relational word.
    Nothing else in COBOL is spelled ``operand IS word``. The operand must
    itself be one data reference (``name [OF q]... [(subscripts)]``).
    Without the ``IS`` (``IF X VALID-CODE``) the class form is not
    recognised -- it is indistinguishable here from a stray token.
    """
    if len(cleaned) < 2 or not _IDENTIFIER_RE.match(cleaned[-1]):
        return None
    word = upper[-1]
    if word in _CLASS_SIGN_WORDS or word in _RELATIONAL_WORDS:
        return None
    rest, rest_upper = cleaned[:-1], upper[:-1]
    negated = bool(rest_upper) and rest_upper[-1] == "NOT"
    if negated:
        rest, rest_upper = rest[:-1], rest_upper[:-1]
    has_is = bool(rest_upper) and rest_upper[-1] == "IS"
    if has_is:
        rest, rest_upper = rest[:-1], rest_upper[:-1]
    if word != "OMITTED" and not has_is:
        return None
    if not rest or not _is_condition_name_reference(rest, rest_upper):
        return None
    if word in _FIGURATIVE_WORDS or word in ("TRUE", "FALSE"):
        return None
    operator = f"IS NOT {word}" if negated else f"IS {word}"
    expr = ConditionalExpression(operator, location)
    expr.set_left_operand(" ".join(rest))
    return expr


def _is_condition_name_reference(cleaned: list[str], upper: list[str]) -> bool:
    """``name [{OF|IN} name]... [( subscripts )]`` and nothing else."""
    if not cleaned or not _IDENTIFIER_RE.match(cleaned[0]):
        return False
    i = 1
    while (
        i + 1 < len(cleaned)
        and upper[i] in ("OF", "IN")
        and _IDENTIFIER_RE.match(cleaned[i + 1])
    ):
        i += 2
    if i == len(cleaned):
        return True
    if cleaned[i] != "(" or cleaned[-1] != ")":
        return False
    depth = 0
    for j in range(i, len(cleaned)):
        if cleaned[j] == "(":
            depth += 1
        elif cleaned[j] == ")":
            depth -= 1
            if depth == 0 and j != len(cleaned) - 1:
                return False
    return depth == 0


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


def find_top_level_operators(tokens: list[str], op: str) -> list[int]:
    """Indexes of every ``op`` token outside any parentheses, in order."""
    depth = 0
    found: list[int] = []
    for i, tok in enumerate(tokens):
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif depth == 0 and tok.upper() == op:
            found.append(i)
    return found
