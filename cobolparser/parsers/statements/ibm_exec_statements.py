"""EXEC SQL and EXEC CICS statement parsers for IBM Enterprise COBOL.

Support for embedded SQL and CICS statements in COBOL procedures.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import ASTNode, SourceLocation
from ...models.sql_statements import parse_exec_sql
from ._utils import collect_exec_sql_text, peek_token


class ExecCicsStatement(ASTNode):
    """AST node for EXEC CICS statements."""

    def __init__(self, location: SourceLocation) -> None:
        super().__init__("EXEC_CICS", location)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "location": self.location.to_dict(),
        }


class ExecSqlStatementParser(IStatementParser):
    """Parser for EXEC SQL statements (embedded SQL in COBOL).

    Handles IBM COBOL embedded SQL blocks that contain SQL statements
    within EXEC SQL...END-EXEC blocks in procedure divisions.

    Example:
        EXEC SQL
            SELECT * FROM TABLE
        END-EXEC.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next tokens are EXEC SQL.

        Uses :func:`peek_token` so the contract that ``matches()`` never raises
        is honored even for streams that throw on out-of-bounds peek.
        """
        token = peek_token(token_stream, 0)
        if not token:
            return False

        # Check if first token is EXEC (dedicated token type or identifier)
        is_exec = token.type == TokenType.EXEC or (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == "EXEC"
        )
        if not is_exec:
            return False

        # Check if next token is SQL
        next_token = peek_token(token_stream, 1)
        if not next_token:
            return False

        return bool(
            next_token.type == TokenType.SQL
            or (
                next_token.type == TokenType.IDENTIFIER
                and next_token.value
                and next_token.value.upper() == "SQL"
            )
        )

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> ASTNode:
        """Parse an EXEC SQL statement."""
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Skip SQL keyword
        if not token_stream.is_empty():
            token_stream.consume()

        sql_text = collect_exec_sql_text(token_stream)
        return parse_exec_sql(sql_text, start_location)


class ExecCicsStatementParser(IStatementParser):
    """Parser for EXEC CICS statements (CICS transactions in COBOL).

    Handles IBM COBOL CICS transaction processing blocks within
    EXEC CICS...END-EXEC blocks in procedure divisions.

    Example:
        EXEC CICS
            RECEIVE INTO CICS-BUFFER
        END-EXEC.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next tokens are EXEC CICS.

        Uses :func:`peek_token` so the contract that ``matches()`` never raises
        is honored even for streams that throw on out-of-bounds peek.
        """
        token = peek_token(token_stream, 0)
        if not token:
            return False

        # Check if first token is EXEC (dedicated token type or identifier)
        is_exec = token.type == TokenType.EXEC or (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == "EXEC"
        )
        if not is_exec:
            return False

        # Check if next token is CICS
        next_token = peek_token(token_stream, 1)
        if not next_token:
            return False

        return bool(
            next_token.type == TokenType.IDENTIFIER
            and next_token.value
            and next_token.value.upper() == "CICS"
        )

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> ASTNode:
        """Parse an EXEC CICS statement.

        Simplified implementation that skips to END-EXEC.
        """
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Skip CICS keyword
        if not token_stream.is_empty():
            token_stream.consume()

        # Parse CICS content - skip until END-EXEC
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            if (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "END-EXEC"
            ):
                token_stream.consume()
                break

            token_stream.consume()

        return ExecCicsStatement(start_location)
