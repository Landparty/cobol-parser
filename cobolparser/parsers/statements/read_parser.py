"""Read statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import IOReadStatement  # noqa: F401 used via factory
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from cobolparser.parsers.statements._utils import skip_whitespace, collect_clause_stmts


class ReadStatementParser(IStatementParser):
    """Parser for READ statements.

    Supports:
    - READ file-name [NEXT|FIRST|LAST|PREVIOUS|CURRENT]
    - READ file-name [INTO target]
    - READ file-name [KEY IS key-name]
    - READ file-name [WITH [NO] LOCK]
    - READ file-name [AT END stmts] [NOT AT END stmts] [END-READ]
    - READ file-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-READ]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is READ keyword."""
        try:
            token = token_stream.peek()
            return bool(token and token.type == TokenType.READ)
        except Exception:
            return False

    def parse(self, token_stream: ITokenStream) -> IOReadStatement:
        """Parse a READ statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IOReadStatement,
            factory.create(
                IOReadStatement,
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

        # Optional access mode: NEXT, FIRST, LAST, PREVIOUS, CURRENT
        token = token_stream.peek()
        if token and token.type == TokenType.NEXT:
            stmt.set_access_mode("NEXT")
            token_stream.consume()
            skip_whitespace(token_stream)
        elif token and token.type == TokenType.IDENTIFIER and token.value:
            val = token.value.upper()
            if val in ("FIRST", "LAST", "PREVIOUS", "CURRENT"):
                stmt.set_access_mode(val)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Optional RECORD keyword (consumed, ignored)
        token = token_stream.peek()
        if token and token.type == TokenType.RECORD:
            token_stream.consume()
            skip_whitespace(token_stream)

        # Optional INTO clause
        token = token_stream.peek()
        if token and token.type == TokenType.INTO:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_into(token.value)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Optional KEY IS clause (may be tokenized as KEY_IS or KEY + IS)
        token = token_stream.peek()
        if token and token.type in (TokenType.KEY_IS, TokenType.KEY):
            token_stream.consume()
            skip_whitespace(token_stream)
            # If KEY (not KEY_IS), consume optional IS keyword
            if token.type == TokenType.KEY:
                nxt = token_stream.peek()
                if nxt and nxt.type == TokenType.IS:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                elif nxt and nxt.type == TokenType.IDENTIFIER and nxt.value and nxt.value.upper() == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_key(token.value)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Optional WITH [NO] LOCK
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "WITH":
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "NO":
                token_stream.consume()
                skip_whitespace(token_stream)
                # Consume LOCK
                token = token_stream.peek()
                if token and token.type == TokenType.LOCK:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=False, with_nowait=True)
            elif token and token.type == TokenType.LOCK:
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=True)
            elif token and token.type == TokenType.WITH_LOCK:
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.set_lock_mode(with_lock=True)

        # Optional AT END clause
        token = token_stream.peek()
        if token and token.type == TokenType.AT:
            token_stream.consume()
            skip_whitespace(token_stream)
            # Consume END keyword
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END":
                token_stream.consume()
                skip_whitespace(token_stream)
            clause_stmts = collect_clause_stmts(
                token_stream, {"END-READ", "NOT", "END_READ"}
            )
            stmt.set_at_end_clause(clause_stmts)

        # Optional NOT AT END clause
        token = token_stream.peek()
        if token and token.type == TokenType.NOT:
            # Peek ahead to confirm NOT AT END (not NOT INVALID KEY)
            saved = token_stream.peek()
            token_stream.consume()
            skip_whitespace(token_stream)
            next_tok = token_stream.peek()
            if next_tok and next_tok.type == TokenType.AT:
                token_stream.consume()
                skip_whitespace(token_stream)
                # Consume END
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-READ", "INVALID", "NOT"}
                )
                stmt.set_not_at_end_clause(clause_stmts)
            elif next_tok and next_tok.type == TokenType.INVALID:
                # NOT INVALID KEY — fall through handled below after re-peeking
                # We already consumed NOT, so handle INVALID KEY now
                token_stream.consume()  # INVALID
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-READ", "NOT"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)
            # else: consumed NOT unexpectedly, continue

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
                token_stream, {"END-READ", "NOT"}
            )
            stmt.set_invalid_key_clause(clause_stmts)

        # Optional NOT INVALID KEY clause (if not already parsed above)
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
                    token_stream, {"END-READ"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)

        # Consume END-READ or PERIOD
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-READ":
            token_stream.consume()
            skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
