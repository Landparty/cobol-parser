"""UNLOCK statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IOUnlockStatement
from ._utils import skip_whitespace


class UnlockStatementParser(IStatementParser):
    """Parser for UNLOCK statements.

    Syntax: UNLOCK file-name [RECORD | RECORDS]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.UNLOCK:
            return True
        return (
            token.type == TokenType.IDENTIFIER
            and token.value is not None
            and token.value.upper() == "UNLOCK"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOUnlockStatement:
        start = token_stream.consume()
        stmt = IOUnlockStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        # File name
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
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
