"""Arithmetic statement parsers implementing IStatementParser interface.

Supports ADD, SUBTRACT, MULTIPLY, DIVIDE, and COMPUTE statements with proper
parsing of operands, targets, expressions, and error handling clauses. The
binary-form parsers (ADD/SUBTRACT/MULTIPLY/DIVIDE) share their operand and
target plumbing through helpers in :mod:`_utils`.
"""

from typing import Any, Protocol, TypeVar, cast

from ...core.ast_factory import create_node
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import ASTNode, SourceLocation
from ...models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ...models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
    FunctionCall,
)
from ._utils import (
    ARITHMETIC_OPERAND_TOKEN_TYPES,
    CONTROL_FLOW_BOUNDARIES,
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    _skip_newlines,
    consume_keyword_and_operand,
    consume_optional_qualifiers,
    consume_signed_numeric,
    get_parse_context,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    parse_arithmetic_operands,
    parse_size_error_clauses,
    peek_value_upper,
    report_or_raise,
    skip_whitespace,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)


class _BinaryArithmeticNode(Protocol):
    """Structural protocol for the binary-form arithmetic AST nodes.

    MULTIPLY and DIVIDE share this shape but don't inherit from a common
    intermediate class, so a Protocol lets the shared helper type-check
    without giving up the concrete return type each parser exposes.
    """

    def add_operand(self, value: str) -> None: ...

    def set_target(self, value: str) -> None: ...

    def set_giving(self, value: str) -> None: ...

    def set_rounded(self, value: bool = ...) -> None: ...


_ArithT = TypeVar("_ArithT", bound=_BinaryArithmeticNode)


class AddStatementParser(IStatementParser):
    """Parser for ADD statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.ADD, "ADD")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> AddStatement:
        """Parse an ADD statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        start_column = token_column(start_token)
        stmt: AddStatement = create_node(AddStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) in ("CORRESPONDING", "CORR"):
            token_stream.consume()
            stmt.set_corresponding(True)
            skip_whitespace(token_stream)

        operands, separator = parse_arithmetic_operands(token_stream, {"TO", "GIVING"})
        for operand in operands:
            stmt.add_operand(operand)

        if not operands:
            report_or_raise(
                ctx, "ADD statement requires at least one operand", start_loc
            )

        if separator == "TO":
            token_stream.consume()  # consume TO
            _skip_newlines(token_stream)
            target = _consume_arithmetic_target(token_stream)
            if target:
                stmt.set_target(target)
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                _consume_additional_arithmetic_targets(token_stream, stmt, start_column)
            else:
                report_or_raise(
                    ctx, "ADD ... TO requires a target identifier", start_loc
                )
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                _consume_additional_giving_targets(token_stream, stmt, start_column)
        elif separator == "GIVING":
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                _consume_additional_giving_targets(token_stream, stmt, start_column)
            else:
                report_or_raise(
                    ctx, "ADD ... GIVING requires a target identifier", start_loc
                )
        else:
            report_or_raise(ctx, "ADD statement missing TO or GIVING clause", start_loc)

        parse_size_error_clauses(token_stream, stmt, "END-ADD")
        return stmt


class SubtractStatementParser(IStatementParser):
    """Parser for SUBTRACT statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SUBTRACT, "SUBTRACT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SubtractStatement:
        """Parse a SUBTRACT statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        start_column = token_column(start_token)
        stmt: SubtractStatement = create_node(SubtractStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) in ("CORRESPONDING", "CORR"):
            token_stream.consume()
            stmt.set_corresponding(True)
            skip_whitespace(token_stream)

        operands, separator = parse_arithmetic_operands(
            token_stream, {"FROM", "GIVING"}
        )
        for operand in operands:
            stmt.add_operand(operand)

        if not operands:
            report_or_raise(
                ctx, "SUBTRACT statement requires at least one operand", start_loc
            )

        if separator == "FROM":
            # Consume FROM keyword; target may be an identifier, figurative
            # constant (ZERO), numeric literal (FROM 100 GIVING Y), or
            # sign-prefixed numeric (FROM -1000000 GIVING Y).
            _skip_newlines(token_stream)
            if peek_value_upper(token_stream) == "FROM":
                token_stream.consume()  # consume FROM
            _skip_newlines(token_stream)
            tok = token_stream.peek()
            target_set = False
            if tok and tok.type in (TokenType.MINUS, TokenType.PLUS):
                # Sign-prefixed FROM target: e.g. FROM -1000000 GIVING Y
                next_tok = token_stream.peek(1)
                if (
                    next_tok
                    and next_tok.type
                    in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)
                    and next_tok.value
                ):
                    sign = tok.value or ""
                    token_stream.consume()
                    stmt.set_target(sign + next_tok.value)
                    token_stream.consume()
                    target_set = True
                else:
                    report_or_raise(
                        ctx, "SUBTRACT ... FROM requires a target identifier", start_loc
                    )
            elif tok and tok.type == TokenType.IDENTIFIER and tok.value:
                # Identifier targets may carry a subscript group (e.g.
                # ``FROM VARIABLE (H, I, 1)``); reuse the same helper ADD's
                # TO target and COMPUTE's targets already use so it isn't
                # dropped as an unparsed trailing token.
                target = _consume_arithmetic_target(token_stream)
                if target:
                    stmt.set_target(target)
                    target_set = True
            elif (
                tok
                and tok.type
                in (
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                    TokenType.FIGURATIVE_CONSTANT,
                )
                and tok.value
            ):
                stmt.set_target(tok.value)
                token_stream.consume()
                target_set = True
            else:
                report_or_raise(
                    ctx, "SUBTRACT ... FROM requires a target identifier", start_loc
                )
            if target_set:
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                # SUBTRACT allows multiple FROM targets, each individually
                # ROUNDED: ``FROM b [ROUNDED], c [ROUNDED] ...``.
                _consume_additional_arithmetic_targets(token_stream, stmt, start_column)
            # SUBTRACT a FROM b GIVING c: the 3-operand form stores the
            # result in c instead of back into b (mirrors ADD's TO branch,
            # which already checks for a trailing GIVING the same way).
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                _consume_additional_giving_targets(token_stream, stmt, start_column)
        elif separator == "GIVING":
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
                if _consume_optional_rounded(token_stream):
                    stmt.set_rounded(True)
                _consume_additional_giving_targets(token_stream, stmt, start_column)
            else:
                report_or_raise(
                    ctx, "SUBTRACT ... GIVING requires a target identifier", start_loc
                )
        else:
            report_or_raise(
                ctx, "SUBTRACT statement missing FROM or GIVING clause", start_loc
            )

        parse_size_error_clauses(token_stream, stmt, "END-SUBTRACT")
        return stmt


class MultiplyStatementParser(IStatementParser):
    """Parser for MULTIPLY statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.MULTIPLY, "MULTIPLY")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> MultiplyStatement:
        """Parse a MULTIPLY statement."""
        return _parse_binary_arithmetic(
            token_stream,
            verb="MULTIPLY",
            separator="BY",
            node_class=MultiplyStatement,
        )


class DivideStatementParser(IStatementParser):
    """Parser for DIVIDE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.DIVIDE, "DIVIDE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> DivideStatement:
        """Parse a DIVIDE statement."""
        return _parse_binary_arithmetic(
            token_stream,
            verb="DIVIDE",
            separator=("BY", "INTO"),
            node_class=DivideStatement,
        )


def _parse_binary_arithmetic(
    token_stream: ITokenStream,
    *,
    verb: str,
    separator: str | tuple[str, ...],
    node_class: type[_ArithT],
) -> _ArithT:
    """Shared parser for the ``MULTIPLY x BY y [GIVING z]`` shape.

    Used by MULTIPLY (separator ``BY``) and DIVIDE (separator ``BY`` or
    ``INTO``). Reports missing operands or missing separator via the parse
    context so COLLECT_ALL mode surfaces them.
    """
    start_token = token_stream.consume()
    start_loc = token_location(start_token)
    start_column = token_column(start_token)
    stmt = cast(_ArithT, create_node(cast(type[ASTNode], node_class), start_loc))
    ctx = get_parse_context(token_stream)

    separators = (separator,) if isinstance(separator, str) else separator

    first_operand = _consume_arithmetic_operand(token_stream)
    if first_operand is not None:
        stmt.add_operand(first_operand)
    else:
        report_or_raise(ctx, f"{verb} statement requires an operand", start_loc)

    # Skip NEWLINEs between the first operand and the separator keyword: the
    # COBOL source may place BY/INTO on the continuation line.
    _skip_newlines(token_stream)
    upper = peek_value_upper(token_stream)
    if upper in separators:
        token_stream.consume()
        if verb == "DIVIDE" and upper is not None:
            # BY vs INTO inverts dividend/divisor order; record it so
            # consumers (const_fold, to_dict/to_json readers) can evaluate
            # the statement instead of treating every DIVIDE as opaque.
            cast(DivideStatement, stmt).set_division_mode(upper)
        second_operand = _consume_arithmetic_operand(token_stream)
        if second_operand is not None:
            stmt.add_operand(second_operand)
        else:
            report_or_raise(
                ctx,
                f"{verb} {upper} requires a second operand",
                start_loc,
            )
    else:
        report_or_raise(
            ctx,
            f"{verb} statement missing {'/'.join(separators)} clause",
            start_loc,
        )

    giving = consume_keyword_and_operand(token_stream, "GIVING")
    if giving:
        stmt.set_giving(giving)
    elif second_operand is not None:
        # Format 1 (no GIVING): MULTIPLY/DIVIDE overwrite the second operand
        # in place, so -- unlike format 2, where it's just a multiplicand/
        # divisor left untouched -- it really is a result target. Track it
        # via set_target (add_operand above already recorded it in
        # .operands; set_target's _add_unique_operand no-ops on the
        # duplicate) so it participates in the same target/targets/ROUNDED
        # machinery ADD/SUBTRACT's TO/FROM already use, instead of only ever
        # appearing as an untyped operand string.
        stmt.set_target(second_operand)

    # ROUNDED is legal here whether or not GIVING was present (e.g. both
    # ``DIVIDE x BY y GIVING z ROUNDED`` and ``DIVIDE x INTO y ROUNDED``).
    # Left unconsumed, it stays in the stream and gets misread by the
    # paragraph-boundary lookahead as a new paragraph header.
    if _consume_optional_rounded(token_stream):
        stmt.set_rounded(True)

    if giving:
        # GIVING accepts a comma/space-separated list of result targets,
        # each optionally ROUNDED (``GIVING z, w ROUNDED``).
        _consume_additional_giving_targets(token_stream, stmt, start_column)
    elif second_operand is not None:
        # Format 1 accepts a comma/space-separated target list too:
        # ``BY id-2 [ROUNDED], id-3 [ROUNDED] ...`` /
        # ``INTO id-2 [ROUNDED], id-3 [ROUNDED] ...``.
        _consume_additional_arithmetic_targets(token_stream, stmt, start_column)

    # REMAINDER is DIVIDE-only (``DIVIDE x INTO y GIVING z REMAINDER r``,
    # or the non-standard-but-tolerated ``DIVIDE x INTO y REMAINDER r``
    # without GIVING); MULTIPLY has no such clause.
    if verb == "DIVIDE":
        remainder = consume_keyword_and_operand(token_stream, "REMAINDER")
        if remainder:
            cast(DivideStatement, stmt).set_remainder(remainder)

    parse_size_error_clauses(token_stream, stmt, f"END-{verb}")
    return stmt


def _consume_arithmetic_operand(stream: ITokenStream) -> str | None:
    """Consume an IDENTIFIER / NUMERIC_LITERAL / LEVEL_NUMBER operand if present.

    Leading NEWLINE tokens are skipped so operands written on a continuation
    line after a separator keyword (``BY``/``INTO``/``=``) are still found.

    Also handles:
    * Sign-prefixed numeric literals: ``-1.3``, ``+0.5``, ``-3`` (LEVEL_NUMBER).
    * Subscripted identifiers: ``TABLE1 (INDEX1)`` → ``"TABLE1 ( INDEX1 )"``.
    * Qualified identifiers: ``QUAL OF PARENT IN HIGHER`` — OF/IN consumed.
    """
    _skip_newlines(stream)
    token = stream.peek()
    if token is None:
        return None

    # Sign-prefixed numeric literal: MINUS/PLUS followed by a number
    # (single/double-digit numbers tokenize as LEVEL_NUMBER, so the shared
    # helper accepts both -- and tolerates a line break between the sign
    # and its digits).
    signed = consume_signed_numeric(stream)
    if signed is not None:
        return signed

    if token and token.type in ARITHMETIC_OPERAND_TOKEN_TYPES and token.value:
        value = token.value
        stream.consume()

        # Consume an optional subscript group and/or OF/IN qualifier chain
        # for IDENTIFIER operands -- e.g. ``TABLE1 (INDEX1)``, ``QUAL OF
        # PARENT``, ``QUAL OF PARENT (IDX)``, or a chain split across a
        # continuation line like ``NAME\n    IN GROUP-48 IN GROUP-47 ...``.
        if token.type == TokenType.IDENTIFIER:
            value = consume_optional_qualifiers(stream, value)

        return value
    return None


def _consume_arithmetic_target(stream: ITokenStream) -> str | None:
    """Consume an IDENTIFIER target, including any subscript group and/or
    OF/IN qualifier chain.

    Distinct from :func:`_consume_arithmetic_operand`: COBOL targets must be
    data items, not literals or level numbers. ``COMPUTE 1 = A`` is therefore
    rejected. A trailing ``(subscript[, subscript]...)`` group and/or
    ``OF``/``IN`` qualifier chain is folded into the returned string so
    subscripted/qualified references like ``WS-T(I, J)`` and ``QUAL OF
    PARENT`` (including a chain split across a continuation line) survive
    intact instead of leaking unconsumed tokens into the following clause.
    """
    _skip_newlines(stream)
    token = stream.peek()
    if not (token and token.type == TokenType.IDENTIFIER and token.value):
        return None

    value = token.value
    stream.consume()

    # Optional subscript group and/or OF/IN qualifier chain.
    return consume_optional_qualifiers(stream, value)


def _consume_optional_rounded(stream: ITokenStream) -> bool:
    """Consume a trailing ROUNDED keyword if present, skipping NEWLINEs first.

    Shared by every arithmetic verb that accepts ROUNDED (ADD/SUBTRACT's
    TO/FROM/GIVING targets -- each individually -- and MULTIPLY/DIVIDE's
    single GIVING target via :func:`_parse_binary_arithmetic`) so ROUNDED
    detection isn't left unconsumed to be misread by the paragraph-boundary
    lookahead. Returns ``True`` if ROUNDED was found and consumed.
    """
    _skip_newlines(stream)
    if peek_value_upper(stream) == "ROUNDED":
        stream.consume()
        return True
    return False


#: GIVING/REMAINDER have no dedicated TokenType (see e.g.
#: consume_keyword_and_operand), so they lex as plain IDENTIFIERs and must be
#: excluded by value here or ``_consume_additional_arithmetic_targets`` would
#: swallow them as a bogus target -- REMAINDER matters for MULTIPLY/DIVIDE's
#: format-1 (no GIVING) multi-target list, which this helper also serves (see
#: _parse_binary_arithmetic): ``DIVIDE x INTO y REMAINDER r`` (the
#: tolerated-without-GIVING form) must stop the target list at REMAINDER, not
#: swallow it as a second target name. Safe to share with ADD/SUBTRACT's
#: TO/FROM list too since REMAINDER is a COBOL reserved word and can never be
#: a real data-name there. ON/NOT/END-ADD/END-SUBTRACT already have dedicated
#: TokenTypes (or are covered by SCOPE_TERMINATORS/STATEMENT_KEYWORDS/
#: CONTROL_FLOW_BOUNDARIES), so ``_consume_arithmetic_target``'s IDENTIFIER
#: check already stops on those without help from this set.
_ADDITIONAL_TARGET_STOP_KEYWORDS: frozenset[str] = (
    frozenset({"GIVING", "REMAINDER", "SIZE"})
    | STATEMENT_KEYWORDS
    | CONTROL_FLOW_BOUNDARIES
    | SCOPE_TERMINATORS
)


def _consume_additional_arithmetic_targets(
    stream: ITokenStream, stmt: Any, reference_column: int | None = None
) -> None:
    """Consume further TO/FROM targets after the first, each optionally ROUNDED.

    COBOL allows a comma- or space-separated target list -- ``TO id-2
    [ROUNDED], id-3 [ROUNDED] ...`` -- for both ADD's TO clause and
    SUBTRACT's FROM clause. *stmt* must already have its first target set via
    :meth:`ArithmeticStatement.set_target`; this only adds the rest.
    """
    while True:
        _skip_newlines(stream)
        if peek_value_upper(stream) == ",":
            stream.consume()
            _skip_newlines(stream)
        if peek_value_upper(stream) in _ADDITIONAL_TARGET_STOP_KEYWORDS:
            break
        # A missing period on this statement followed by the next paragraph/
        # section header (H9): stop instead of folding the header into the
        # target list -- without this, `ADD A TO B` with no trailing period
        # would swallow a following `NEXT-PARA.` as a bogus extra target and
        # the paragraph would vanish from the AST entirely. Disambiguated by
        # indentation (Area A vs Area B) so a target that merely wraps onto
        # its own continuation line -- legitimate for any target in the
        # list, not just the first -- isn't misread as a boundary and
        # dropped.
        if looks_like_paragraph_boundary(stream) and looks_dedented_relative_to(
            stream, reference_column
        ):
            warn_paragraph_boundary_swallowed(stream)
            break
        extra_target = _consume_arithmetic_target(stream)
        if extra_target is None:
            break
        stmt.set_target(extra_target)
        if _consume_optional_rounded(stream):
            stmt.set_rounded(True)


#: GIVING may itself be followed by further comma/space-separated targets
#: (``GIVING id-3 [ROUNDED] [id-4 [ROUNDED]] ...``); REMAINDER (DIVIDE-only)
#: must stop the list rather than being swallowed as a bogus extra target.
_ADDITIONAL_GIVING_STOP_KEYWORDS: frozenset[str] = (
    frozenset({"REMAINDER", "SIZE"})
    | STATEMENT_KEYWORDS
    | CONTROL_FLOW_BOUNDARIES
    | SCOPE_TERMINATORS
)


def _consume_additional_giving_targets(
    stream: ITokenStream, stmt: Any, reference_column: int | None = None
) -> None:
    """Consume further GIVING targets after the first, each optionally ROUNDED.

    COBOL allows a comma- or space-separated GIVING target list --
    ``GIVING id-3 [ROUNDED] [id-4 [ROUNDED]] ...`` -- for ADD, SUBTRACT,
    MULTIPLY, and DIVIDE alike. *stmt* must already have its first GIVING
    target set via :meth:`ArithmeticStatement.set_giving`; this only adds
    the rest.
    """
    while True:
        _skip_newlines(stream)
        if peek_value_upper(stream) == ",":
            stream.consume()
            _skip_newlines(stream)
        if peek_value_upper(stream) in _ADDITIONAL_GIVING_STOP_KEYWORDS:
            break
        # Same H9-pattern guard as _consume_additional_arithmetic_targets:
        # don't swallow a following paragraph header as a bogus extra
        # GIVING target when this statement's period is missing, but only
        # once dedentation also confirms it (Area A vs Area B) -- a GIVING
        # target that merely wraps onto its own continuation line is
        # legitimate for any target in the list, not just the first.
        if looks_like_paragraph_boundary(stream) and looks_dedented_relative_to(
            stream, reference_column
        ):
            warn_paragraph_boundary_swallowed(stream)
            break
        extra_giving = _consume_arithmetic_target(stream)
        if extra_giving is None:
            break
        stmt.set_giving(extra_giving)
        if _consume_optional_rounded(stream):
            stmt.set_rounded(True)


class _ExpressionSyntaxError(Exception):
    """Internal signal: a COMPUTE token sequence is not tree-parseable.

    Never escapes :func:`build_compute_expression_tree` -- tree building is
    strictly best-effort (M12) and must not introduce errors or warnings
    where the raw-string path produced none.
    """


_EXPR_BINARY_OPS = ("+", "-", "*", "/", "**")


def _split_top_level_commas(tokens: list[str]) -> list[list[str]]:
    """Split a token list on commas that sit outside any parentheses."""
    parts: list[list[str]] = [[]]
    depth = 0
    for tok in tokens:
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        if tok == "," and depth == 0:
            parts.append([])
        else:
            parts[-1].append(tok)
    return parts


class _ExpressionTreeParser:
    """Recursive-descent precedence parser over COMPUTE expression tokens.

    Input is the flat list of token *strings* the COMPUTE parser already
    collects for the raw expression string, so the tree is guaranteed to be
    derived from exactly the same tokens. Grammar (COBOL precedence, loosest
    to tightest):

        expression := term   (("+" | "-") term)*        left-associative
        term       := unary  (("*" | "/") unary)*       left-associative
        unary      := ("+" | "-")* power                "-" -> NEGATE node
        power      := primary ("**" unary)?             right-associative
        primary    := "(" expression ")"
                    | "FUNCTION" name ["(" args ")"]    -> FunctionCall
                    | identifier ["(" subscripts ")"]   -> leaf string
                    | literal                           -> leaf string

    Leaves are plain strings (identifiers -- subscript groups folded in as
    ``"A ( I )"``, mirroring ``_consume_arithmetic_operand`` -- and
    literals); interior nodes are :class:`ArithmeticExpression` (operator
    ``+ - * / **`` or unary ``NEGATE`` with only ``right_operand`` set) and
    :class:`FunctionCall`.
    """

    def __init__(self, tokens: list[str], location: SourceLocation) -> None:
        self._tokens = tokens
        self._pos = 0
        self._location = location

    def parse(self) -> CobolExpression:
        """Parse the full token list into a single expression node."""
        node = self._parse_full()
        if isinstance(node, CobolExpression):
            return node
        # Single operand (e.g. COMPUTE X = A): wrap the leaf so the
        # attribute is uniformly a CobolExpression.
        leaf = CobolExpression("OPERAND", self._location)
        leaf.operands = [node]
        return leaf

    def _parse_full(self) -> str | CobolExpression:
        node = self._parse_expression()
        if self._pos != len(self._tokens):
            raise _ExpressionSyntaxError(f"trailing token {self._peek()!r}")
        return node

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> str:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _binary(
        self,
        operator: str,
        left: str | CobolExpression,
        right: str | CobolExpression,
    ) -> ArithmeticExpression:
        node = ArithmeticExpression(operator, self._location)
        node.set_left_operand(left)
        node.set_right_operand(right)
        return node

    def _parse_expression(self) -> str | CobolExpression:
        node = self._parse_term()
        while self._peek() in ("+", "-"):
            op = self._advance()
            node = self._binary(op, node, self._parse_term())
        return node

    def _parse_term(self) -> str | CobolExpression:
        node = self._parse_unary()
        while self._peek() in ("*", "/"):
            op = self._advance()
            node = self._binary(op, node, self._parse_unary())
        return node

    def _parse_unary(self) -> str | CobolExpression:
        tok = self._peek()
        if tok == "+":
            self._advance()
            return self._parse_unary()
        if tok == "-":
            self._advance()
            node = ArithmeticExpression("NEGATE", self._location)
            node.set_right_operand(self._parse_unary())
            return node
        return self._parse_power()

    def _parse_power(self) -> str | CobolExpression:
        node = self._parse_primary()
        while self._peek() == "**":
            self._advance()
            # Left-associative, like every other COBOL binary operator:
            # IBM evaluates operators of the same precedence left to right,
            # so ``2 ** 3 ** 2`` is ``(2 ** 3) ** 2 == 64``, not ``2 ** 9``.
            # The exponent may itself carry a sign (``2 ** -3``), hence the
            # signed-primary parse on the right -- which deliberately does
            # NOT absorb a further ``**`` of its own.
            node = self._binary("**", node, self._parse_signed_primary())
        return node

    def _parse_signed_primary(self) -> str | CobolExpression:
        """A primary with any number of leading unary signs, for the
        right-hand side of ``**`` -- ``_parse_unary`` minus its descent into
        ``_parse_power``, so exponentiation chains stay left-associative."""
        tok = self._peek()
        if tok == "+":
            self._advance()
            return self._parse_signed_primary()
        if tok == "-":
            self._advance()
            node = ArithmeticExpression("NEGATE", self._location)
            node.set_right_operand(self._parse_signed_primary())
            return node
        return self._parse_primary()

    def _parse_primary(self) -> str | CobolExpression:
        tok = self._peek()
        if tok is None:
            raise _ExpressionSyntaxError("unexpected end of expression")
        if tok == "(":
            self._advance()
            node = self._parse_expression()
            if self._peek() != ")":
                raise _ExpressionSyntaxError("missing closing parenthesis")
            self._advance()
            return node
        if tok.upper() == "FUNCTION":
            return self._parse_function_call()
        if tok in _EXPR_BINARY_OPS or tok in (")", ","):
            raise _ExpressionSyntaxError(f"unexpected token {tok!r}")
        self._advance()
        # Subscripted identifier: fold "NAME ( I [, J] )" into the leaf
        # string, mirroring _consume_arithmetic_operand's "TABLE1 ( INDEX1 )"
        # shape (COBOL has no implicit multiplication, so IDENTIFIER "("
        # can only be a subscript/reference-modification group here).
        if tok[:1].isalpha() and self._peek() == "(":
            group = self._consume_balanced_group()
            return " ".join([tok, *group])
        return tok

    def _consume_balanced_group(self) -> list[str]:
        """Consume a balanced ``( ... )`` group, parens included."""
        parts: list[str] = []
        depth = 0
        while True:
            tok = self._peek()
            if tok is None:
                raise _ExpressionSyntaxError("unbalanced parentheses")
            parts.append(self._advance())
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                if depth == 0:
                    return parts

    def _parse_function_call(self) -> FunctionCall:
        self._advance()  # FUNCTION keyword
        name = self._peek()
        if name is None or name in _EXPR_BINARY_OPS or name in ("(", ")", ","):
            raise _ExpressionSyntaxError("FUNCTION requires a function name")
        self._advance()
        call = FunctionCall(name, self._location)
        if self._peek() == "(":
            group = self._consume_balanced_group()
            for arg_tokens in _split_top_level_commas(group[1:-1]):
                if not arg_tokens:
                    continue
                argument: str | CobolExpression
                try:
                    argument = _ExpressionTreeParser(
                        arg_tokens, self._location
                    )._parse_full()
                except _ExpressionSyntaxError:
                    # Space-separated argument lists (FUNCTION MAX(A B))
                    # and other shapes the grammar doesn't cover degrade
                    # to the raw joined string, never to a failure.
                    argument = " ".join(arg_tokens)
                call.add_argument(argument)
        return call


def build_compute_expression_tree(
    tokens: list[str], location: SourceLocation
) -> CobolExpression | None:
    """Best-effort structural parse of COMPUTE expression tokens (M12).

    Returns ``None`` for any token sequence the precedence parser does not
    understand (including the unbalanced-parentheses case already reported
    by the COMPUTE parser itself, see H2) -- the caller keeps the raw
    joined string either way, so failure here never adds an error or
    warning that the pre-M12 parser did not produce.

    ``**`` reaches this function as two adjacent ``"*"`` tokens (the lexer
    emits two MULTIPLY_OP tokens); they are re-merged before parsing.
    """
    cleaned: list[str] = []
    for tok in tokens:
        if not tok or not tok.strip():
            continue  # drop NEWLINE/empty tokens kept in the raw string
        if tok == "*" and cleaned and cleaned[-1] == "*":
            cleaned[-1] = "**"
            continue
        cleaned.append(tok)
    if not cleaned:
        return None
    try:
        return _ExpressionTreeParser(cleaned, location).parse()
    except Exception:
        # Strictly fail-soft: any surprise (grammar gap, odd token) leaves
        # expression_tree as None with the raw string untouched.
        return None


class ComputeStatementParser(IStatementParser):
    """Parser for COMPUTE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.COMPUTE, "COMPUTE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ComputeStatement:
        """Parse a COMPUTE statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        start_column = token_column(start_token)
        stmt: ComputeStatement = create_node(ComputeStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

        # Parse target identifiers: COMPUTE {identifier [ROUNDED]}... =
        # (literals/level-numbers are not valid here).
        target = _consume_arithmetic_target(token_stream)
        if target is None:
            report_or_raise(
                ctx, "COMPUTE statement requires a target identifier", start_loc
            )
        stmt.add_target(target)

        # Additional targets and per-target ROUNDED phrases, up to '='. COMPUTE
        # only records whether ROUNDED appeared at all (not which target it
        # modified), matching ADD/SUBTRACT/MULTIPLY/DIVIDE's single `rounded`
        # flag -- previously this branch consumed and discarded the keyword.
        while True:
            if _consume_optional_rounded(token_stream):
                stmt.set_rounded(True)
                continue
            if peek_value_upper(token_stream) == ",":
                # A comma between targets (`COMPUTE A, B = ...`) is a
                # separator, not a terminator -- skip it and keep collecting
                # targets. Without this, the comma was left unconsumed and
                # the subsequent `=` check failed outright ("COMPUTE
                # statement missing '=' operator"), a harder failure than
                # the warned/silent drops this bug class usually produces.
                token_stream.consume()
                _skip_newlines(token_stream)
                continue
            extra_target = _consume_arithmetic_target(token_stream)
            if extra_target is None:
                break
            stmt.add_target(extra_target)

        # Check for =
        token = token_stream.peek()
        if token and token.value == "=":
            token_stream.consume()
        else:
            report_or_raise(ctx, "COMPUTE statement missing '=' operator", start_loc)

        # Parse expression (collect all tokens until terminator)
        expr_tokens: list[str] = []
        paren_depth = 0
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            # Cheap checks first: token type tests, parenthesis counting.
            # Only fall back to the ``.upper()`` keyword test at paren depth
            # zero when the token could plausibly be ``ON``/``NOT``/
            # ``END-COMPUTE`` (i.e. has a value).
            tok_type = token.type
            if tok_type == TokenType.LEFT_PAREN:
                paren_depth += 1
            elif tok_type == TokenType.RIGHT_PAREN:
                paren_depth -= 1
            elif paren_depth == 0:
                if tok_type == TokenType.PERIOD:
                    break
                if token.value:
                    upper = token.value.upper()
                    if upper in ("ON", "NOT", "END-COMPUTE"):
                        break
                    # Without this check, a COMPUTE with no trailing period
                    # immediately followed by another statement (e.g. a
                    # multi-line CALL), or nested inside a clause body ending
                    # in a scope terminator (e.g. ``READ ... AT END COMPUTE
                    # ... END-READ``), has those tokens silently swallowed
                    # into the expression string — mirrors the stop set
                    # parse_arithmetic_operands() uses for ADD/SUBTRACT/
                    # MULTIPLY/DIVIDE.
                    if (
                        upper in STATEMENT_KEYWORDS
                        or upper in CONTROL_FLOW_BOUNDARIES
                        or upper in SCOPE_TERMINATORS
                    ):
                        break
                if (
                    tok_type == TokenType.IDENTIFIER
                    and looks_like_paragraph_boundary(token_stream)
                    and looks_dedented_relative_to(token_stream, start_column)
                ):
                    # A missing period on this COMPUTE followed by what looks
                    # like the next paragraph/section header (H9): stop
                    # instead of folding it into the expression string.
                    # Disambiguated by indentation (Area A vs Area B) so an
                    # expression term that merely wraps onto its own
                    # continuation line isn't misread as a boundary and
                    # dropped from the expression.
                    warn_paragraph_boundary_swallowed(token_stream)
                    break

            # Unbalanced parentheses (a stray '(' with no matching ')')
            # otherwise leave paren_depth != 0 for the rest of the token
            # stream, which disables the paren_depth == 0 boundary checks
            # above for good -- a following well-formed statement (e.g.
            # DISPLAY) would then be silently folded into the expression
            # string instead of stopping the COMPUTE. A token that
            # unambiguously begins a new COBOL statement can never
            # legitimately appear inside an arithmetic expression, so this
            # check applies regardless of paren_depth.
            if paren_depth != 0 and is_statement_boundary(token):
                break

            expr_tokens.append(token.value if token.value else "")
            token_stream.consume()

        if expr_tokens:
            # ``**`` lexes as two adjacent MULTIPLY_OP tokens; re-merge them
            # so the serialized text reads ``2 ** 3``, not ``2 * * 3`` (which
            # is not valid COBOL and misreads as a double multiply) -- the
            # same merge build_compute_expression_tree already applies.
            merged_tokens: list[str] = []
            for tok in expr_tokens:
                if tok == "*" and merged_tokens and merged_tokens[-1] == "*":
                    merged_tokens[-1] = "**"
                    continue
                merged_tokens.append(tok)
            expr_tokens = merged_tokens
            expr_str = " ".join(expr_tokens).strip()
            stmt.set_expression(expr_str)
            # M12: additionally attach a structural tree parsed from the
            # exact same tokens. Best-effort only -- on failure the tree
            # stays None and the raw string above is unaffected.
            stmt.set_expression_tree(
                build_compute_expression_tree(expr_tokens, start_loc)
            )
        else:
            report_or_raise(ctx, "COMPUTE statement missing expression", start_loc)

        if paren_depth != 0:
            report_or_raise(
                ctx,
                "COMPUTE statement has unbalanced parentheses in expression",
                start_loc,
            )

        parse_size_error_clauses(token_stream, stmt, "END-COMPUTE")
        return stmt
