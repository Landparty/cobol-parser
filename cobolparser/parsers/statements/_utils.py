"""
Shared utilities for statement parsers.

Single source of truth for helpers that would otherwise be copy-pasted across
individual parser files.
"""

from __future__ import annotations

from typing import Any

from cobolparser.core.interfaces import ITokenStream, ParseContext
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.data import DisplayStatement, MoveStatement

# ---------------------------------------------------------------------------
# Token-type sets used by multiple parsers to detect statement boundaries
# ---------------------------------------------------------------------------

STATEMENT_TOKEN_TYPES: frozenset = frozenset(
    {
        TokenType.ACCEPT,
        TokenType.ADD,
        TokenType.ALTER,
        TokenType.CALL,
        TokenType.CANCEL,
        TokenType.CLOSE,
        TokenType.COMPUTE,
        TokenType.CONTINUE,
        TokenType.DELETE,
        TokenType.DISPLAY,
        TokenType.DIVIDE,
        TokenType.ENTRY,
        TokenType.EVALUATE,
        TokenType.EXEC,
        TokenType.EXIT,
        TokenType.GENERATE,
        TokenType.GOBACK,
        TokenType.IF,
        TokenType.INITIALIZE,
        TokenType.INSPECT,
        TokenType.MERGE,
        TokenType.MOVE,
        TokenType.MULTIPLY,
        TokenType.OPEN,
        TokenType.PERFORM,
        TokenType.READ,
        TokenType.RELEASE,
        TokenType.RETURN,
        TokenType.REWRITE,
        TokenType.SEARCH,
        TokenType.SET,
        TokenType.SORT,
        TokenType.START,
        TokenType.STOP,
        TokenType.STRING,
        TokenType.SUBTRACT,
        TokenType.UNLOCK,
        TokenType.UNSTRING,
        TokenType.USE,
        TokenType.WRITE,
    }
)

CONTROL_FLOW_BOUNDARIES: frozenset = frozenset(
    {
        "ELSE",
        "END-IF",
        "END-PERFORM",
        "END-EVALUATE",
        "END-SEARCH",
        "END-STRING",
        "END-UNSTRING",
        "WHEN",
    }
)

STATEMENT_KEYWORDS: frozenset = frozenset(
    {
        "ACCEPT",
        "ADD",
        "ALTER",
        "CALL",
        "CANCEL",
        "CLOSE",
        "COMPUTE",
        "CONTINUE",
        "DELETE",
        "DISPLAY",
        "DIVIDE",
        "ENTRY",
        "EVALUATE",
        "EXEC",
        "EXECUTE",
        "EXIT",
        "GENERATE",
        "GO",
        "GOBACK",
        "IF",
        "INITIALIZE",
        "INSPECT",
        "MERGE",
        "MOVE",
        "MULTIPLY",
        "OPEN",
        "PERFORM",
        "READ",
        "RELEASE",
        "RETURN",
        "REWRITE",
        "SEARCH",
        "SET",
        "SORT",
        "START",
        "STOP",
        "STRING",
        "SUBTRACT",
        "UNLOCK",
        "UNSTRING",
        "USE",
        "WRITE",
    }
)


# ---------------------------------------------------------------------------
# Token value helpers
# ---------------------------------------------------------------------------


def token_value_upper(token: Any) -> str:
    """Return the upper-cased value of *token*, or ``""`` if unavailable."""
    return token.value.upper() if token and token.value else ""


def token_location(token: Any) -> SourceLocation:
    """Return the source location of *token*, or a zero location if absent."""
    return token.location if token else SourceLocation(0, 0)


def matches_keyword(token_stream: ITokenStream, token_type: Any, keyword: str) -> bool:
    """Return True if the next token matches *token_type* or is an IDENTIFIER equal to *keyword*.

    This is the canonical implementation for statement-parser ``matches()`` methods
    that detect a single COBOL verb.  It avoids the repetitive try/except and
    dual-check pattern that would otherwise be copy-pasted across every parser.
    Returns False on any stream error so that the registry can safely probe each parser.
    """
    try:
        token = token_stream.peek()
        if not token:
            return False
        return token.type == token_type or (
            token.type == TokenType.IDENTIFIER
            and token.value is not None
            and token.value.upper() == keyword
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Whitespace / period helpers
# ---------------------------------------------------------------------------


def skip_whitespace(stream: ITokenStream) -> None:
    """Consume WHITESPACE, COMMENT, NEWLINE, and CONTINUATION tokens."""
    while not stream.is_empty():
        token = stream.peek()
        if not token or token.type not in (
            TokenType.WHITESPACE,
            TokenType.COMMENT,
            TokenType.NEWLINE,
            TokenType.CONTINUATION,
        ):
            break
        stream.consume()


def consume_period(stream: ITokenStream) -> None:
    """Consume a period token if it is the next non-empty token."""
    if not stream.is_empty():
        t = stream.peek()
        if t and t.type == TokenType.PERIOD:
            stream.consume()


def skip_to_period(stream: ITokenStream) -> None:
    """Skip (consume) tokens until a period is found, then consume it."""
    while not stream.is_empty():
        token = stream.peek()
        if not token or token.type == TokenType.PERIOD:
            if token:
                stream.consume()
            break
        stream.consume()


# ---------------------------------------------------------------------------
# Clause-token collector (used by IO statement parsers)
# ---------------------------------------------------------------------------


def collect_clause_stmts(stream: ITokenStream, stop_at: set) -> list:
    """Consume tokens belonging to a conditional clause until a boundary.

    Always returns an empty list — the tokens are discarded because full
    clause parsing is not yet implemented.  The boundary token is NOT consumed.
    """
    while not stream.is_empty():
        token = stream.peek()
        if not token:
            break
        if token.type == TokenType.PERIOD:
            break
        if token.type == TokenType.NOT:
            break
        if token.type == TokenType.INVALID:
            break
        if (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() in stop_at
        ):
            break
        stream.consume()
    return []


def parse_invalid_key_clauses(
    stream: ITokenStream,
    stmt: Any,
    end_keyword: str,
) -> None:
    """Parse optional INVALID KEY / NOT INVALID KEY clauses.

    Sets ``stmt.set_invalid_key_clause(...)`` and
    ``stmt.set_not_invalid_key_clause(...)`` when the corresponding clauses
    are present.  *end_keyword* is the scope terminator (e.g. ``"END-DELETE"``).
    """
    # INVALID KEY
    token = stream.peek()
    if token and token.type == TokenType.INVALID:
        stream.consume()
        skip_whitespace(stream)
        token = stream.peek()
        if token and token.type == TokenType.KEY:
            stream.consume()
            skip_whitespace(stream)
        clause_stmts = collect_clause_stmts(stream, {end_keyword})
        stmt.set_invalid_key_clause(clause_stmts)

    # NOT INVALID KEY
    token = stream.peek()
    if token and token.type == TokenType.NOT:
        stream.consume()
        skip_whitespace(stream)
        token = stream.peek()
        if token and token.type == TokenType.INVALID:
            stream.consume()
            skip_whitespace(stream)
            token = stream.peek()
            if token and token.type == TokenType.KEY:
                stream.consume()
                skip_whitespace(stream)
            clause_stmts = collect_clause_stmts(stream, {end_keyword})
            stmt.set_not_invalid_key_clause(clause_stmts)


def consume_end_keyword_and_period(
    stream: ITokenStream,
    end_keyword: str,
) -> None:
    """Consume an optional END-xxx scope terminator followed by a period."""
    skip_whitespace(stream)
    token = stream.peek()
    if (
        token
        and token.type == TokenType.IDENTIFIER
        and token.value
        and token.value.upper() == end_keyword
    ):
        stream.consume()
        skip_whitespace(stream)
    token = stream.peek()
    if token and token.type == TokenType.PERIOD:
        stream.consume()


# ---------------------------------------------------------------------------
# Parse-context helpers (used by IF / PERFORM / EVALUATE)
# ---------------------------------------------------------------------------


def get_parse_context(stream: ITokenStream) -> ParseContext | None:
    """Return the active parse context attached to *stream*, or None."""
    context = stream.context
    if context is None:
        context = getattr(stream, "_context", None)
    return context


def report_parse_error(
    context: ParseContext | None,
    message: str,
    location: SourceLocation,
) -> None:
    """Forward *message* to *context* if one is available."""
    if context:
        context.error(message, location)


# ---------------------------------------------------------------------------
# Nested-statement dispatch (used by IF / PERFORM / EVALUATE)
# ---------------------------------------------------------------------------


def try_parse_nested_statement(
    stream: ITokenStream,
    exclude_self: Any | None = None,
) -> Any | None:
    """Attempt to parse a nested statement via the registry on *stream*.

    Pass *exclude_self* (the calling parser instance) to prevent the registry
    from recursively dispatching back to the same parser.
    """
    try:
        registry = getattr(stream, "_registry", None) or getattr(
            stream, "registry", None
        )
        if registry is None and callable(getattr(stream, "get_registry", None)):
            registry = stream.get_registry()  # type: ignore[attr-defined]
        if registry is None:
            return None

        find = getattr(registry, "find_parser", None)
        if not callable(find):
            return None

        parser = find(stream)
        if parser is None:
            return None
        if exclude_self is not None and parser is exclude_self:
            return None
        return parser.parse(stream)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Arithmetic size-error clause parsing (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE)
# ---------------------------------------------------------------------------


def _skip_newlines(stream: ITokenStream) -> Any | None:
    """Consume NEWLINE tokens and return the next non-NEWLINE token."""
    token = stream.peek()
    while token and token.type == TokenType.NEWLINE:
        stream.consume()
        token = stream.peek()
    return token


def parse_size_error_clauses(stream: ITokenStream, stmt: Any) -> None:
    """Parse optional ON SIZE ERROR / NOT ON SIZE ERROR clauses.

    Calls ``stmt.set_on_size_error_clause()`` and
    ``stmt.set_not_on_size_error_clause()`` when the clauses are present and
    consumes the trailing period.  Used by ADD and COMPUTE statement parsers.
    """
    while not stream.is_empty():
        token = stream.peek()
        if not token or token.type == TokenType.PERIOD:
            if token:
                stream.consume()
            break

        if token.type == TokenType.NEWLINE:
            stream.consume()
            continue

        if not token.value:
            stream.consume()
            continue

        token_upper = token.value.upper()
        if token_upper == "ON":
            stream.consume()
            next_token = _skip_newlines(stream)
            if next_token and next_token.value and next_token.value.upper() == "SIZE":
                stream.consume()
                next_token = _skip_newlines(stream)
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "ERROR"
                ):
                    stream.consume()
                    stmt.set_on_size_error_clause(_parse_size_error_stmts(stream))
        elif token_upper == "NOT":
            stream.consume()
            next_token = _skip_newlines(stream)
            if next_token and next_token.value and next_token.value.upper() == "ON":
                stream.consume()
                next_token = _skip_newlines(stream)
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "SIZE"
                ):
                    stream.consume()
                    next_token = _skip_newlines(stream)
                    if (
                        next_token
                        and next_token.value
                        and next_token.value.upper() == "ERROR"
                    ):
                        stream.consume()
                        stmt.set_not_on_size_error_clause(
                            _parse_size_error_stmts(stream)
                        )
        else:
            break


# ---------------------------------------------------------------------------
# EXEC SQL / EXEC CICS block text collector
# ---------------------------------------------------------------------------

#: Token types that should be attached directly to the preceding token (no space).
_EXEC_SQL_NO_SPACE_BEFORE: frozenset[TokenType] = frozenset(
    {
        TokenType.COLON,
        TokenType.COMMA,
        TokenType.PERIOD,
        TokenType.SEMICOLON,
    }
)


def collect_exec_sql_text(stream: ITokenStream) -> str:
    """Collect the raw SQL text from a token stream up to (and consuming) END-EXEC.

    The stream must be positioned **after** the ``EXEC SQL`` keyword pair has
    already been consumed by the caller.

    Host-variable colons (e.g. ``:WS-NAME``) are preserved by attaching the
    identifier directly to the preceding colon token (no space inserted).
    Punctuation tokens (comma, period, semicolon) are similarly attached to
    avoid spurious spaces.

    Args:
        stream: Token stream positioned at the first SQL token after ``SQL``.

    Returns:
        The reconstructed SQL text as a single string, without leading/trailing
        whitespace.
    """
    sql_parts: list[str] = []
    prev_was_colon = False
    while not stream.is_empty():
        token = stream.peek(0)
        if not token:
            break

        is_end_exec = token.type == TokenType.END_EXEC or (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == "END-EXEC"
        )
        if is_end_exec:
            stream.consume()
            break

        if token.value:
            if prev_was_colon or token.type in _EXEC_SQL_NO_SPACE_BEFORE:
                if sql_parts:
                    sql_parts[-1] = sql_parts[-1] + token.value
                else:
                    sql_parts.append(token.value)
            else:
                sql_parts.append(token.value)
            prev_was_colon = token.type == TokenType.COLON
        stream.consume()

    return " ".join(sql_parts)


def _parse_size_error_stmts(stream: ITokenStream) -> list:
    """Parse imperative statements inside an ON SIZE ERROR / NOT ON SIZE ERROR clause.

    Handles DISPLAY and MOVE as inline mini-parsers; all other verbs are skipped.
    The trailing period (or next clause boundary) is NOT consumed.
    """
    nested: list = []

    while not stream.is_empty():
        token = stream.peek()
        if not token or token.type == TokenType.PERIOD:
            if token:
                stream.consume()
            break

        if token.type == TokenType.NEWLINE:
            stream.consume()
            continue

        if not token.value:
            stream.consume()
            continue

        token_upper = token.value.upper()

        if token_upper == "DISPLAY":
            start = stream.consume()
            start_loc = start.location if start else SourceLocation(0, 0)
            display_stmt = DisplayStatement(start_loc)
            while not stream.is_empty():
                t = stream.peek()
                if not t:
                    break
                if t.type == TokenType.NEWLINE:
                    stream.consume()
                    continue
                if t.type == TokenType.PERIOD or (
                    t.value and t.value.upper() in ("MOVE", "DISPLAY")
                ):
                    break
                if t.type in (
                    TokenType.STRING_LITERAL,
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                ):
                    display_stmt.add_display_item(t.value)
                stream.consume()
            nested.append(display_stmt)

        elif token_upper == "MOVE":
            start = stream.consume()
            start_loc = start.location if start else SourceLocation(0, 0)
            move_stmt = MoveStatement(start_loc)
            while not stream.is_empty():
                t = stream.peek()
                if not t:
                    break
                if t.type == TokenType.NEWLINE:
                    stream.consume()
                    continue
                if t.type == TokenType.PERIOD:
                    break
                if t.value and t.value.upper() == "TO":
                    stream.consume()
                    target_token = _skip_newlines(stream)
                    if target_token and target_token.type == TokenType.IDENTIFIER:
                        move_stmt.add_target(target_token.value)
                        stream.consume()
                    break
                if t.type in (
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.STRING_LITERAL,
                ):
                    move_stmt.add_operand(t.value)
                stream.consume()
            nested.append(move_stmt)
        else:
            stream.consume()

    return nested
