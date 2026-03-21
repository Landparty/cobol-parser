"""Rewrite statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import RewriteStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType


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

    def parse(self, token_stream: ITokenStream) -> RewriteStatement:
        """Parse a REWRITE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            RewriteStatement,
            factory.create(
                RewriteStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        self._skip_whitespace(token_stream)

        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_record_name(token.value)
            token_stream.consume()
        else:
            return stmt

        self._skip_whitespace(token_stream)

        # Optional FROM clause (consume but no setter on this node)
        token = token_stream.peek()
        if token and token.type == TokenType.FROM:
            token_stream.consume()
            self._skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
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
                token_stream, {"END-REWRITE"}
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
                    token_stream, {"END-REWRITE"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)

        # Consume END-REWRITE or PERIOD
        self._skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-REWRITE":
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
