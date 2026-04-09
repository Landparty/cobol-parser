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
