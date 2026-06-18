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
from ...models.ast_base import ASTNode
from ...models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ._utils import (
    ARITHMETIC_OPERAND_TOKEN_TYPES,
    _skip_newlines,
    consume_keyword_and_operand,
    get_parse_context,
    matches_keyword,
    parse_arithmetic_operands,
    parse_size_error_clauses,
    peek_value_upper,
    report_or_raise,
    skip_to_period,
    token_location,
)


class _BinaryArithmeticNode(Protocol):
    """Structural protocol for the binary-form arithmetic AST nodes.

    MULTIPLY and DIVIDE share this shape but don't inherit from a common
    intermediate class, so a Protocol lets the shared helper type-check
    without giving up the concrete return type each parser exposes.
    """

    def add_operand(self, value: str) -> None: ...

    def set_giving(self, value: str) -> None: ...


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
        stmt: AddStatement = create_node(AddStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

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
            target = self._consume_identifier(token_stream)
            if target:
                stmt.set_target(target)
            else:
                report_or_raise(
                    ctx, "ADD ... TO requires a target identifier", start_loc
                )
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
        elif separator == "GIVING":
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
            else:
                report_or_raise(
                    ctx, "ADD ... GIVING requires a target identifier", start_loc
                )
        else:
            report_or_raise(ctx, "ADD statement missing TO or GIVING clause", start_loc)

        parse_size_error_clauses(token_stream, stmt)
        return stmt

    @staticmethod
    def _consume_identifier(stream: ITokenStream) -> str | None:
        _skip_newlines(stream)
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            value = token.value
            stream.consume()
            return value
        return None


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
        stmt: SubtractStatement = create_node(SubtractStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

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
            if tok and tok.type in (
                TokenType.MINUS, TokenType.PLUS
            ):
                # Sign-prefixed FROM target: e.g. FROM -1000000 GIVING Y
                next_tok = token_stream.peek(1)
                if next_tok and next_tok.type in (
                    TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER
                ) and next_tok.value:
                    sign = tok.value or ""
                    token_stream.consume()
                    stmt.set_target(sign + next_tok.value)
                    token_stream.consume()
                else:
                    report_or_raise(
                        ctx, "SUBTRACT ... FROM requires a target identifier", start_loc
                    )
            elif tok and tok.type in (
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
                TokenType.FIGURATIVE_CONSTANT,
            ) and tok.value:
                stmt.set_target(tok.value)
                token_stream.consume()
            else:
                report_or_raise(
                    ctx, "SUBTRACT ... FROM requires a target identifier", start_loc
                )
        elif separator == "GIVING":
            giving = consume_keyword_and_operand(token_stream, "GIVING")
            if giving:
                stmt.set_giving(giving)
            else:
                report_or_raise(
                    ctx, "SUBTRACT ... GIVING requires a target identifier", start_loc
                )
        else:
            report_or_raise(
                ctx, "SUBTRACT statement missing FROM or GIVING clause", start_loc
            )

        skip_to_period(token_stream)
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

    skip_to_period(token_stream)
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

    # Sign-prefixed numeric literal: MINUS/PLUS followed immediately by a number.
    # Single-digit numbers tokenize as LEVEL_NUMBER, so accept both.
    if token.type in (TokenType.MINUS, TokenType.PLUS):
        next_tok = stream.peek(1)
        if next_tok and next_tok.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER) and next_tok.value:
            sign = token.value or ""
            stream.consume()  # sign
            value = next_tok.value
            stream.consume()  # number
            return sign + value

    if token and token.type in ARITHMETIC_OPERAND_TOKEN_TYPES and token.value:
        value = token.value
        stream.consume()

        # Consume optional subscript group ``(...)`` for IDENTIFIER operands
        if token.type == TokenType.IDENTIFIER:
            next_tok = stream.peek()
            if next_tok and next_tok.type == TokenType.LEFT_PAREN:
                depth = 0
                parts: list[str] = [value]
                while not stream.is_empty():
                    t = stream.peek()
                    if not t:
                        break
                    if t.type == TokenType.LEFT_PAREN:
                        depth += 1
                        parts.append("(")
                    elif t.type == TokenType.RIGHT_PAREN:
                        depth -= 1
                        parts.append(")")
                    else:
                        parts.append(t.value if t.value else "")
                    stream.consume()
                    if depth == 0:
                        break
                value = " ".join(p for p in parts if p)

            # Consume optional subscript or OF/IN qualifier chain.
            # Loop handles both ``QUAL OF PARENT (IDX)`` and multi-line chains
            # like ``NAME\n    IN GROUP-48 IN GROUP-47 ...``.
            while not stream.is_empty():
                _skip_newlines(stream)  # qualifiers may span continuation lines
                qt = stream.peek()
                if qt and qt.type == TokenType.LEFT_PAREN:
                    # Subscript group — consume ``(...)``
                    depth = 0
                    while not stream.is_empty():
                        t = stream.peek()
                        if not t:
                            break
                        if t.type == TokenType.LEFT_PAREN:
                            depth += 1
                        elif t.type == TokenType.RIGHT_PAREN:
                            depth -= 1
                        stream.consume()
                        if depth == 0:
                            break
                elif qt and qt.type in (TokenType.OF, TokenType.IN):
                    stream.consume()  # consume OF/IN
                    _skip_newlines(stream)
                    qname = stream.peek()
                    if qname and qname.type == TokenType.IDENTIFIER and qname.value:
                        stream.consume()
                    else:
                        break
                else:
                    break

        return value
    return None


def _consume_arithmetic_target(stream: ITokenStream) -> str | None:
    """Consume an IDENTIFIER target, including any subscript group.

    Distinct from :func:`_consume_arithmetic_operand`: COBOL targets must be
    data items, not literals or level numbers. ``COMPUTE 1 = A`` is therefore
    rejected. A trailing ``(subscript[, subscript]...)`` group is folded into
    the returned string so subscripted references like ``WS-T(I, J)`` survive
    intact instead of leaking ``(...)`` tokens into the expression.
    """
    _skip_newlines(stream)
    token = stream.peek()
    if not (token and token.type == TokenType.IDENTIFIER and token.value):
        return None

    parts: list[str] = [token.value]
    stream.consume()

    # Optional subscript group: ``(...)``. Track paren depth so nested calls
    # like ``WS-T(FUNCTION FOO(I))`` are captured correctly.
    next_token = stream.peek()
    if next_token and next_token.type == TokenType.LEFT_PAREN:
        depth = 0
        while not stream.is_empty():
            t = stream.peek()
            if not t:
                break
            if t.type == TokenType.LEFT_PAREN:
                depth += 1
                parts.append("(")
            elif t.type == TokenType.RIGHT_PAREN:
                depth -= 1
                parts.append(")")
            else:
                parts.append(t.value if t.value else "")
            stream.consume()
            if depth == 0:
                break

    return " ".join(p for p in parts if p)


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
        stmt: ComputeStatement = create_node(ComputeStatement, start_loc)  # type: ignore[assignment]
        ctx = get_parse_context(token_stream)

        # Parse target identifier (literals/level-numbers are not valid here).
        target = _consume_arithmetic_target(token_stream)
        if target is None:
            report_or_raise(
                ctx, "COMPUTE statement requires a target identifier", start_loc
            )
        stmt.add_target(target)

        # Skip ROUNDED if present
        if peek_value_upper(token_stream) == "ROUNDED":
            token_stream.consume()

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
                if token.value and token.value.upper() in ("ON", "NOT", "END-COMPUTE"):
                    break

            expr_tokens.append(token.value if token.value else "")
            token_stream.consume()

        if expr_tokens:
            expr_str = " ".join(expr_tokens).strip()
            stmt.set_expression(expr_str)
        else:
            report_or_raise(ctx, "COMPUTE statement missing expression", start_loc)

        parse_size_error_clauses(token_stream, stmt)
        return stmt
