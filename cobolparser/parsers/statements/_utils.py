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
        TokenType.PERFORM,
        TokenType.DISPLAY,
        TokenType.MOVE,
        TokenType.IF,
        TokenType.EVALUATE,
        TokenType.ACCEPT,
        TokenType.CALL,
        TokenType.COMPUTE,
        TokenType.INSPECT,
        TokenType.READ,
        TokenType.WRITE,
        TokenType.OPEN,
        TokenType.CLOSE,
        TokenType.STOP,
        TokenType.ADD,
        TokenType.SUBTRACT,
        TokenType.MULTIPLY,
        TokenType.DIVIDE,
    }
)

STATEMENT_KEYWORDS: frozenset = frozenset(
    {
        "PERFORM",
        "DISPLAY",
        "MOVE",
        "IF",
        "EVALUATE",
        "ACCEPT",
        "CALL",
        "COMPUTE",
        "INSPECT",
        "READ",
        "WRITE",
        "OPEN",
        "CLOSE",
        "STOP",
        "ADD",
        "SUBTRACT",
        "MULTIPLY",
        "DIVIDE",
    }
)


# ---------------------------------------------------------------------------
# Whitespace helpers
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
