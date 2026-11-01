"""EXEC SQL and EXEC CICS statement parsers for IBM Enterprise COBOL.

Support for embedded SQL and CICS statements in COBOL procedures.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...dialects.ibm_enterprise import IBMEnterpriseCobol
from ...lexer import TokenType
from ...models.ast_base import ASTNode, SourceLocation
from ...models.sql_statements import parse_exec_sql
from ...models.statements.base import CobolStatement
from ._utils import (
    _NOISE_TOKEN_TYPES,
    collect_exec_sql_text,
    peek_token,
    skip_whitespace,
)

# The EXEC DLI command words, read from the dialect so the two cannot drift
# apart again (#481): this copy had lost ROLB / LOAD / SCHD and kept the
# non-command XDLT.
_IMS_CALL_TYPES = IBMEnterpriseCobol.EXEC_DLI_COMMANDS


def _skip_quoted(text: str, start: int) -> int:
    """Return the index just past the quoted literal opening at ``text[start]``.

    Handles doubled-quote escapes (``'IT''S'``). If the literal is
    unterminated, returns ``len(text)``.
    """
    quote = text[start]
    i = start + 1
    n = len(text)
    while i < n:
        if text[i] == quote:
            if i + 1 < n and text[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _read_paren_group(text: str, start: int) -> tuple[str, int]:
    """Read a balanced ``(...)`` group starting at ``text[start] == '('``.

    Returns ``(inner_text, index_after_close)``. Nested parentheses and
    quoted literals (which may contain unbalanced parens) are handled.
    The inner text is whitespace-normalized and spaces adjacent to
    parentheses are removed so ``FROM ( WS-DATA ( 1:10 ) )`` yields
    ``WS-DATA(1:10)``.
    """
    depth = 0
    i = start
    n = len(text)
    inner_start = start + 1
    while i < n:
        ch = text[i]
        if ch in "'\"":
            i = _skip_quoted(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                inner = text[inner_start:i]
                return _normalize_arg_text(inner), i + 1
        i += 1
    # Unterminated group: take everything to end of text.
    return _normalize_arg_text(text[inner_start:]), n


def _normalize_arg_text(text: str) -> str:
    """Collapse whitespace and remove spaces adjacent to parentheses."""
    collapsed = " ".join(text.split())
    return collapsed.replace(" (", "(").replace("( ", "(").replace(" )", ")").strip()


def _parse_cics_options(text: str) -> dict[str, str | None]:
    """Parse a CICS option list into ``{OPTION: argument-or-None}``.

    *text* is the joined token text following the CICS command (e.g.
    ``"MAP ( 'MAP1' ) MAPSET ( 'SET1' ) ERASE"``). Each option keyword maps
    to the text inside its parenthesized argument, or ``None`` for flag
    options like ERASE / NOHANDLE. Nested parentheses and quoted literals
    inside arguments are preserved. Insertion order follows source order.
    """
    options: dict[str, str | None] = {}
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch in "()":
            i += 1
            continue
        if ch in "'\"":
            i = _skip_quoted(text, i)
            continue
        # Read an option keyword (or bare operand word).
        j = i
        while j < n and not text[j].isspace() and text[j] not in "()'\"":
            j += 1
        word = text[i:j].upper()
        i = j
        # Skip whitespace between the keyword and a possible argument list.
        k = i
        while k < n and text[k].isspace():
            k += 1
        if k < n and text[k] == "(":
            arg, i = _read_paren_group(text, k)
            options[word] = arg
        else:
            options[word] = None
    return options


def _is_single_literal(argument: str) -> bool:
    """True when *argument* is exactly one quoted literal (``'X'``, ``"X"``)."""
    text = argument.strip()
    if len(text) < 2 or text[0] not in "'\"" or text[-1] != text[0]:
        return False
    return _skip_quoted(text, 0) == len(text)


def _parse_ims_arguments(text: str) -> list[str]:
    """Split EXEC IMS / EXEC DLI text into top-level positional arguments.

    Each argument is either a bare word (PCB name, I/O area, SSA name) or a
    keyword with its parenthesized argument reattached (``PCB(1)``,
    ``SEGMENT(EMPLOYEE)``, ``WHERE(EMPID=:WS-ID)``). Nested parentheses and
    quoted literals are kept inside their argument.
    """
    arguments: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            inner, i = _read_paren_group(text, i)
            arguments.append(f"({inner})")
            continue
        if ch == ")":
            i += 1
            continue
        if ch in "'\"":
            end = _skip_quoted(text, i)
            arguments.append(text[i:end])
            i = end
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in "()'\"":
            j += 1
        word = text[i:j]
        i = j
        k = i
        while k < n and text[k].isspace():
            k += 1
        if k < n and text[k] == "(":
            inner, i = _read_paren_group(text, k)
            arguments.append(f"{word}({inner})")
        else:
            arguments.append(word)
    return arguments


def _exec_interface_token(token_stream: ITokenStream) -> Any | None:
    """The token naming the interface after EXEC (SQL / CICS / DLI / IMS).

    Looks past line breaks: ``EXEC`` alone on a line is ordinary layout, and
    a fixed ``peek(1)`` there saw the NEWLINE, so the block matched no EXEC
    parser and was split into stray statements.
    """
    offset = 1
    token = peek_token(token_stream, offset)
    while token is not None and token.type in _NOISE_TOKEN_TYPES:
        offset += 1
        token = peek_token(token_stream, offset)
    return token


class ExecCicsStatement(CobolStatement):
    """AST node for EXEC CICS statements.

    A :class:`CobolStatement` (``statement_type`` ``"EXEC CICS"``) so it is
    returned by ``CobolProgram.get_all_statements()`` like every other
    PROCEDURE DIVISION statement -- it used to extend ``ASTNode`` directly,
    which silently hid every CICS command from that walk (and from any
    analyzer built on it) with ``errors=0, warnings=0``. ``node_type`` stays
    ``"EXEC_CICS"`` and ``to_dict()`` keeps its historical shape, so
    ``find_all_by_type("EXEC_CICS")`` and JSON consumers are unaffected.
    """

    def __init__(self, location: SourceLocation) -> None:
        super().__init__("EXEC CICS", location)
        self.node_type = "EXEC_CICS"
        self._cics_command: str = ""
        self.cics_text: str = ""
        #: Structured option list: option keyword -> argument text inside the
        #: parentheses, or None for flag options (ERASE, NOHANDLE, ...).
        #: Insertion order matches source order.
        self.options: dict[str, str | None] = {}
        #: Option keywords whose argument is one quoted literal
        #: (``PROGRAM('X')``), as opposed to a data-name (``PROGRAM(WS-X)``).
        #: ``options`` holds both unquoted, so this is the only way to tell
        #: them apart. Not part of ``to_dict()``.
        self.literal_options: set[str] = set()

    @property
    def cics_command(self) -> str:
        """The CICS command verb (SEND, RECEIVE, LINK, ...)."""
        return self._cics_command

    @cics_command.setter
    def cics_command(self, value: str) -> None:
        self._cics_command = value

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_type": self.node_type,
            "cics_command": self.cics_command,
            "cics_text": self.cics_text,
            "options": dict(self.options),
            "location": self.location.to_dict(),
        }
        # Set by DynamicCallAnalyzer on LINK / XCTL / LOAD PROGRAM(data-name):
        # the programs the operand can hold, as on a dynamic CALL.
        possible = self.get_metadata("possible_values")
        if possible is not None:
            result["possible_values"] = list(possible)
            if self.get_metadata("possible_values_incomplete"):
                result["possible_values_incomplete"] = True
        return result


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
        next_token = _exec_interface_token(token_stream)
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

        # Skip SQL keyword (possibly on the next line)
        skip_whitespace(token_stream)
        if not token_stream.is_empty():
            token_stream.consume()

        sql_text = collect_exec_sql_text(token_stream, sql=True)
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
        next_token = _exec_interface_token(token_stream)
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

        # Skip CICS keyword (possibly on the next line)
        skip_whitespace(token_stream)
        if not token_stream.is_empty():
            token_stream.consume()

        stmt = ExecCicsStatement(start_location)

        # Skip whitespace / newline tokens before the CICS command -- the
        # idiomatic layout (and this class's own docstring example) puts the
        # command verb on the line after ``EXEC CICS``.
        while not token_stream.is_empty():
            pk = token_stream.peek(0)
            if pk and pk.value and not pk.value.strip():
                token_stream.consume()
            else:
                break

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
        quoted: list[str] = []
        stmt.cics_text = collect_exec_sql_text(token_stream, quoted_text=quoted)

        # Structured option list (MAP('M1'), MAPSET('S1'), ERASE, ...)
        stmt.options = _parse_cics_options(stmt.cics_text)
        stmt.literal_options = {
            option
            for option, argument in _parse_cics_options("".join(quoted)).items()
            if argument is not None and _is_single_literal(argument)
        }

        return stmt


class ExecImsStatement(CobolStatement):
    """AST node for EXEC IMS / EXEC DLI statements.

    A :class:`CobolStatement` for the same reason as
    :class:`ExecCicsStatement` above; ``node_type`` stays ``"EXEC_IMS"``.
    """

    def __init__(self, location: SourceLocation) -> None:
        super().__init__("EXEC IMS", location)
        self.node_type = "EXEC_IMS"
        self._ims_command: str = ""
        self.ims_call_type: str = "UNKNOWN"
        self.ims_text: str = ""
        #: Positional arguments following the function code: PCB reference,
        #: I/O area, SSAs, or DLI keyword options with their parenthesized
        #: argument reattached (e.g. ``PCB(1)``, ``SEGMENT(EMPLOYEE)``).
        self.arguments: list[str] = []

    @property
    def ims_command(self) -> str:
        """The DL/I function code (GU, GN, ISRT, ...)."""
        return self._ims_command

    @ims_command.setter
    def ims_command(self, value: str) -> None:
        self._ims_command = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "ims_command": self.ims_command,
            "ims_call_type": self.ims_call_type,
            "ims_text": self.ims_text,
            "arguments": list(self.arguments),
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

        next_token = _exec_interface_token(token_stream)
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

        # Skip IMS / DLI keyword (possibly on the next line)
        skip_whitespace(token_stream)
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

        # Structured positional arguments (PCB name, I/O area, SSAs, ...)
        stmt.arguments = _parse_ims_arguments(stmt.ims_text)

        return stmt
