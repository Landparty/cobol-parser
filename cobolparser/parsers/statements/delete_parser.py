"""Delete statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    consume_end_keyword_and_period,
    matches_keyword,
    parse_invalid_key_clauses,
    skip_whitespace,
)

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IODeleteStatement


class DeleteStatementParser(IStatementParser):
    """Parser for DELETE statements.

    Supports:
    - DELETE file-name RECORD [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-DELETE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.DELETE, "DELETE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IODeleteStatement:
        """Parse a DELETE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IODeleteStatement,
            factory.create(
                IODeleteStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        skip_whitespace(token_stream)

        # Parse file name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_file_name(token.value)
            token_stream.consume()
        else:
            return stmt

        skip_whitespace(token_stream)

        # Optional RECORD keyword
        token = token_stream.peek()
        if token and token.type == TokenType.RECORD:
            token_stream.consume()
            skip_whitespace(token_stream)

        parse_invalid_key_clauses(token_stream, stmt, "END-DELETE")
        consume_end_keyword_and_period(token_stream, "END-DELETE")

        return stmt
