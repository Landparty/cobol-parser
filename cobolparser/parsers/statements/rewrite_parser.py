"""Rewrite statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    consume_end_keyword_and_period,
    parse_invalid_key_clauses,
    skip_whitespace,
)

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IORewriteStatement


class RewriteStatementParser(IStatementParser):
    """Parser for REWRITE statements.

    Supports:
    - REWRITE record-name [FROM source]
    - REWRITE record-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-REWRITE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is REWRITE keyword."""
        try:
            token = token_stream.peek()
            return bool(token and token.type == TokenType.REWRITE)
        except Exception:
            return False

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IORewriteStatement:
        """Parse a REWRITE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IORewriteStatement,
            factory.create(
                IORewriteStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        skip_whitespace(token_stream)

        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_record_name(token.value)
            token_stream.consume()
        else:
            return stmt

        skip_whitespace(token_stream)

        # Optional FROM clause (consume but no setter on this node)
        token = token_stream.peek()
        if token and token.type == TokenType.FROM:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                token_stream.consume()
                skip_whitespace(token_stream)

        parse_invalid_key_clauses(token_stream, stmt, "END-REWRITE")
        consume_end_keyword_and_period(token_stream, "END-REWRITE")

        return stmt
