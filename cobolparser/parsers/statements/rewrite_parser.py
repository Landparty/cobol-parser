"""Rewrite statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    consume_end_keyword_and_period,
    create_statement,
    matches_keyword,
    parse_invalid_key_clauses,
    skip_whitespace,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IORewriteStatement


class RewriteStatementParser(IStatementParser):
    """Parser for REWRITE statements.

    Supports:
    - REWRITE record-name [FROM source]
    - REWRITE record-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-REWRITE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.REWRITE, "REWRITE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IORewriteStatement:
        """Parse a REWRITE statement."""
        stmt, _ = create_statement(token_stream, IORewriteStatement)

        skip_whitespace(token_stream)

        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_record_name(token.value)
            token_stream.consume()
        else:
            return stmt

        skip_whitespace(token_stream)

        # Optional FROM clause (REWRITE rec FROM data / FROM 'literal')
        token = token_stream.peek()
        if token and token.type == TokenType.FROM:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
            ):
                stmt.set_from(token.value or "")
                token_stream.consume()
                skip_whitespace(token_stream)

        parse_invalid_key_clauses(token_stream, stmt, "END-REWRITE")
        consume_end_keyword_and_period(token_stream, "END-REWRITE")

        return stmt
