"""Delete statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import collect_clause_stmts, skip_whitespace

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
        """Check if next token is DELETE keyword."""
        try:
            token = token_stream.peek()
            return bool(token and token.type == TokenType.DELETE)
        except Exception:
            return False

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> IODeleteStatement:
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

        # Optional INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.INVALID:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.KEY:
                token_stream.consume()
                skip_whitespace(token_stream)
            clause_stmts = collect_clause_stmts(
                token_stream, {"END-DELETE"}
            )
            stmt.set_invalid_key_clause(clause_stmts)

        # Optional NOT INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.NOT:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.INVALID:
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-DELETE"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)

        # Consume END-DELETE or PERIOD
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-DELETE":
            token_stream.consume()
            skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
