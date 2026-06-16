"""EXEC SQL and EXEC CICS statement parsers for IBM Enterprise COBOL.

Support for embedded SQL and CICS statements in COBOL procedures.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import ASTNode, SourceLocation
from ...models.sql_statements import parse_exec_sql
from ._utils import collect_exec_sql_text, peek_token

_IMS_CALL_TYPES = frozenset(
    {"GU", "GN", "GNP", "ISRT", "REPL", "DLET", "CHKP", "ROLLB", "TERM", "XRST", "XDLT"}
)


class ExecCicsStatement(ASTNode):
    """AST node for EXEC CICS statements."""

    def __init__(self, location: SourceLocation) -> None:
        super().__init__("EXEC_CICS", location)
        self.cics_command: str = ""
        self.cics_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "cics_command": self.cics_command,
            "cics_text": self.cics_text,
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
            next_token.type == TokenType.CICS
            or (
                next_token.type == TokenType.IDENTIFIER
                and next_token.value
                and next_token.value.upper() == "CICS"
            )
        )

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> ASTNode:
        """Parse an EXEC CICS statement."""
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Skip CICS keyword
        if not token_stream.is_empty():
            token_stream.consume()

        stmt = ExecCicsStatement(start_location)

        # Capture command name (first non-whitespace token after EXEC CICS)
        cmd_token = token_stream.peek(0)
        if (
            cmd_token
            and cmd_token.value
            and cmd_token.value.upper() not in ("END-EXEC", "")
        ):
            stmt.cics_command = cmd_token.value.upper()
            token_stream.consume()

        # Collect remaining CICS text until END-EXEC
        stmt.cics_text = collect_exec_sql_text(token_stream)

        return stmt


class ExecImsStatement(ASTNode):
    """AST node for EXEC IMS / EXEC DLI statements."""

    def __init__(self, location: SourceLocation) -> None:
        super().__init__("EXEC_IMS", location)
        self.ims_command: str = ""
        self.ims_call_type: str = "UNKNOWN"
        self.ims_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "ims_command": self.ims_command,
            "ims_call_type": self.ims_call_type,
            "ims_text": self.ims_text,
            "location": self.location.to_dict(),
        }


class ExecImsStatementParser(IStatementParser):
    """Parser for EXEC IMS / EXEC DLI statements (IMS DL/I calls in COBOL).

    Handles IBM COBOL IMS Database Manager call blocks within
    EXEC IMS...END-EXEC or EXEC DLI...END-EXEC blocks.

    Example:
        EXEC IMS
            GU SEGMENT-NAME
        END-EXEC.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next tokens are EXEC IMS or EXEC DLI."""
        token = peek_token(token_stream, 0)
        if not token:
            return False

        is_exec = token.type == TokenType.EXEC or (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == "EXEC"
        )
        if not is_exec:
            return False

        next_token = peek_token(token_stream, 1)
        if not next_token:
            return False

        return bool(
            next_token.type == TokenType.IDENTIFIER
            and next_token.value
            and next_token.value.upper() in {"IMS", "DLI"}
        )

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> ASTNode:
        """Parse an EXEC IMS / EXEC DLI statement."""
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Skip IMS / DLI keyword
        if not token_stream.is_empty():
            token_stream.consume()

        stmt = ExecImsStatement(start_location)

        # Skip whitespace / newline tokens before the IMS command
        while not token_stream.is_empty():
            pk = token_stream.peek(0)
            if pk and pk.value and not pk.value.strip():
                token_stream.consume()
            else:
                break

        # Capture IMS command (GU, GN, GNP, ISRT, REPL, DLET, …)
        cmd_token = token_stream.peek(0)
        if (
            cmd_token
            and cmd_token.value
            and cmd_token.value.strip()
            and cmd_token.value.upper() not in ("END-EXEC",)
        ):
            cmd = cmd_token.value.upper()
            stmt.ims_command = cmd
            if cmd in _IMS_CALL_TYPES:
                stmt.ims_call_type = cmd
            token_stream.consume()

        # Collect remaining text until END-EXEC
        stmt.ims_text = collect_exec_sql_text(token_stream)

        return stmt
