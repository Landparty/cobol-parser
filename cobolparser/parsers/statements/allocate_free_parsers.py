"""ALLOCATE and FREE statement parsers (IBM Enterprise dynamic storage).

Neither verb has a dedicated lexer ``TokenType`` -- both lex as plain
``IDENTIFIER`` tokens and are recognized only by value, the same mechanism
already used for other reserved-but-untyped verbs (PURGE, RESUME, ...). This
keeps them from ever being reserved globally: a data item legitimately named
``ALLOCATE`` or ``FREE`` is unaffected everywhere except a genuine
statement-start position, which is exactly where ``matches_keyword`` and the
``STATEMENT_KEYWORDS`` boundary set already look.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import AllocateStatement, FreeStatement
from ._utils import (
    consume_period,
    is_statement_boundary,
    peek_token,
    skip_whitespace,
    token_location,
    token_value_upper,
)


def _matches_bare_verb(token_stream: ITokenStream, keyword: str) -> bool:
    """True when the next token is a plain IDENTIFIER equal to *keyword*.

    ALLOCATE/FREE have no dedicated ``TokenType`` (see module docstring), so
    unlike :func:`matches_keyword` -- which would need a real, distinct
    ``TokenType`` to fall back on -- this checks the token's *value* only.
    """
    token = peek_token(token_stream)
    return bool(
        token
        and token.type == TokenType.IDENTIFIER
        and token.value
        and token.value.upper() == keyword
    )


class AllocateStatementParser(IStatementParser):
    """Parser for ALLOCATE statements (dynamic storage acquisition).

    Syntax:
        ALLOCATE {identifier-1 CHARACTERS | identifier-2}
            [INITIALIZED]
            [RETURNING identifier-3]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return _matches_bare_verb(token_stream, "ALLOCATE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> AllocateStatement:
        start = token_stream.consume()
        stmt = AllocateStatement(token_location(start))
        skip_whitespace(token_stream)

        # First operand: either a byte-count (identifier or literal) followed
        # by CHARACTERS, or the name of a BASED data item.
        token = token_stream.peek()
        if token and token.type in (
            TokenType.IDENTIFIER,
            TokenType.NUMERIC_LITERAL,
            TokenType.LEVEL_NUMBER,
        ):
            operand = token.value or ""
            token_stream.consume()
            skip_whitespace(token_stream)

            nxt = token_stream.peek()
            if nxt and token_value_upper(nxt) == "CHARACTERS":
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.set_size_expr(operand)
            else:
                stmt.set_data_item(operand)

        # Optional INITIALIZED
        token = token_stream.peek()
        if token and token_value_upper(token) == "INITIALIZED":
            token_stream.consume()
            stmt.set_initialized(True)
            skip_whitespace(token_stream)

        # Optional RETURNING identifier-3
        token = token_stream.peek()
        if token and token_value_upper(token) == "RETURNING":
            token_stream.consume()
            skip_whitespace(token_stream)
            target = token_stream.peek()
            if target and target.type == TokenType.IDENTIFIER and target.value:
                stmt.set_returning_target(target.value)
                token_stream.consume()
                skip_whitespace(token_stream)

        consume_period(token_stream)
        return stmt


class FreeStatementParser(IStatementParser):
    """Parser for FREE statements (dynamic storage release).

    Syntax: FREE identifier-1 [identifier-2] ...
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return _matches_bare_verb(token_stream, "FREE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> FreeStatement:
        start = token_stream.consume()
        stmt = FreeStatement(token_location(start))
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.COMMA:
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type != TokenType.IDENTIFIER or is_statement_boundary(token):
                break
            stmt.add_pointer_name(token.value or "")
            token_stream.consume()
            skip_whitespace(token_stream)

        consume_period(token_stream)
        return stmt
