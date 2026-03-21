"""Delete statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import DeleteStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


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

    def parse(self, token_stream: ITokenStream) -> DeleteStatement:
        """Parse a DELETE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            DeleteStatement,
            factory.create(
                DeleteStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        self._skip_whitespace(token_stream)

        # Parse file name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_file_name(token.value)
            token_stream.consume()
        else:
            return stmt

        self._skip_whitespace(token_stream)

        # Optional RECORD keyword
        token = token_stream.peek()
        if token and token.type == TokenType.RECORD:
            token_stream.consume()
            self._skip_whitespace(token_stream)

        # Optional INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.INVALID:
            token_stream.consume()
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.KEY:
                token_stream.consume()
                self._skip_whitespace(token_stream)
            clause_stmts = self._collect_clause_stmts(
                token_stream, {"END-DELETE"}
            )
            stmt.set_invalid_key_clause(clause_stmts)

        # Optional NOT INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.NOT:
            token_stream.consume()
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.INVALID:
                token_stream.consume()
                self._skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    self._skip_whitespace(token_stream)
                clause_stmts = self._collect_clause_stmts(
                    token_stream, {"END-DELETE"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)

        # Consume END-DELETE or PERIOD
        self._skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-DELETE":
            token_stream.consume()
            self._skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt

    def _collect_clause_stmts(self, token_stream: ITokenStream, stop_at: set) -> list:
        """Consume clause tokens until a boundary. Returns empty list."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.NOT:
                break
            if token.type == TokenType.INVALID:
                break
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in stop_at:
                break
            token_stream.consume()
        return []

    def _skip_whitespace(self, token_stream: ITokenStream) -> None:
        """Skip whitespace and newline tokens."""
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or token.type not in (
                TokenType.WHITESPACE,
                TokenType.COMMENT,
                TokenType.NEWLINE,
            ):
                break
            token_stream.consume()
