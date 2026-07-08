"""UNLOCK statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOUnlockStatement
from ._utils import (
    is_statement_boundary,
    matches_keyword,
    skip_whitespace,
    token_location,
)


class UnlockStatementParser(IStatementParser):
    """Parser for UNLOCK statements.

    Syntax: UNLOCK file-name [RECORD | RECORDS]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.UNLOCK, "UNLOCK")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOUnlockStatement:
        start = token_stream.consume()
        loc = token_location(start)
        factory = get_factory()
        stmt = factory.create(IOUnlockStatement, loc)
        if not isinstance(stmt, IOUnlockStatement):
            stmt = IOUnlockStatement(loc)
        skip_whitespace(token_stream)

        # File name. Guard against a missing operand: if the next token
        # already starts a new statement, do not consume its verb as the
        # file name (that silently destroyed the following statement).
        token = token_stream.peek()
        if (
            token
            and token.type not in (TokenType.PERIOD, None)
            and not is_statement_boundary(token)
        ):
            token_stream.consume()
            stmt.set_file_name(token.value or "")

        skip_whitespace(token_stream)

        # Optional RECORD/RECORDS
        token = token_stream.peek()
        if token and token.value and token.value.upper() in ("RECORD", "RECORDS"):
            token_stream.consume()
            stmt.set_record_scope("RECORD")

        skip_whitespace(token_stream)

        # Consume period
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
