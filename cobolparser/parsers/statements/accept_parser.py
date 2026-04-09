"""ACCEPT statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IOAcceptStatement
from ._utils import skip_whitespace


class AcceptStatementParser(IStatementParser):
    """Parser for ACCEPT statements.

    Syntax:
        ACCEPT identifier [FROM source]
        ACCEPT identifier FROM DATE/TIME/DAY/DAY-OF-WEEK
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.ACCEPT:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and token.value is not None
            and token.value.upper() == "ACCEPT"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOAcceptStatement:
        start = token_stream.consume()
        stmt = IOAcceptStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        # Target identifier
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_target(token.value or "")

        skip_whitespace(token_stream)

        # Optional FROM clause
        token = token_stream.peek()
        if token and (
            token.type == TokenType.FROM
            or (token.value and token.value.upper() == "FROM")
        ):
            token_stream.consume()
            skip_whitespace(token_stream)

            src = token_stream.peek()
            if src and src.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_from(src.value or "")

        skip_whitespace(token_stream)

        # Consume period if present
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
