"""
Shared utilities for statement parsers.

Single source of truth for helpers that would otherwise be copy-pasted across
individual parser files.
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn, TypeVar, cast

from cobolparser._errors import ParseError
from cobolparser.core.ast_factory import get_factory
from cobolparser.core.interfaces import ITokenStream, ParseContext
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.statements.data import DisplayStatement, MoveStatement
from cobolparser.plugins.core import ErrorRecoveryMode

logger = logging.getLogger(__name__)

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

#: Explicit scope terminators (END-xxx). These can never begin a statement or
#: act as an operand, so operand/parameter collection loops must stop on them
#: rather than swallow them (e.g. ``CALL "X" USING WS-AMT END-READ``).
SCOPE_TERMINATORS: frozenset = frozenset(
    {
        "END-ACCEPT",
        "END-ADD",
        "END-CALL",
        "END-COMPUTE",
        "END-DELETE",
        "END-DISPLAY",
        "END-DIVIDE",
        "END-EVALUATE",
        "END-EXEC",
        "END-IF",
        "END-MULTIPLY",
        "END-PERFORM",
        "END-READ",
        "END-RETURN",
        "END-REWRITE",
        "END-SEARCH",
        "END-START",
        "END-STRING",
        "END-SUBTRACT",
        "END-UNSTRING",
        "END-WRITE",
    }
)

STATEMENT_KEYWORDS: frozenset = frozenset(
    {
        "ACCEPT",
        "ADD",
        "ALLOCATE",
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
        "EXHIBIT",
        "EXIT",
        "FREE",
        "GENERATE",
        "GO",
        "GOBACK",
        "IF",
        "INITIALIZE",
        "INSPECT",
        "INVOKE",
        "JSON",
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
        "XML",
    }
)


# ---------------------------------------------------------------------------
# Token value helpers
# ---------------------------------------------------------------------------


def token_value_upper(token: Token | None) -> str:
    """Return the upper-cased value of *token*, or ``""`` if unavailable."""
    return token.value.upper() if token and token.value else ""


def token_location(token: Token | None) -> SourceLocation:
    """Return the source location of *token*, or a zero location if absent."""
    return token.location if token else SourceLocation(0, 0)


def is_statement_boundary(token: Token | None) -> bool:
    """Return True if *token* begins a new statement or closes an enclosing scope.

    A statement or clause-collection loop that has no explicit terminator (e.g.
    the sentence period) must *stop* — rather than consume — when it reaches
    such a token, or it silently swallows the statement that follows. This
    consolidates the four-way check (:data:`STATEMENT_TOKEN_TYPES` /
    :data:`STATEMENT_KEYWORDS` / :data:`SCOPE_TERMINATORS` /
    :data:`CONTROL_FLOW_BOUNDARIES`) that the MOVE / arithmetic parsers already
    perform inline, so the INSPECT / STRING / UNSTRING parsers share one source
    of truth. It is intentionally *not* used for EXEC SQL/CICS/IMS text
    collection: embedded SQL legitimately contains COBOL statement keywords
    (SET, DELETE, CALL, OPEN, CLOSE, UPDATE), which this predicate would
    misread as a boundary.
    """
    if token is None:
        return False
    if token.type in STATEMENT_TOKEN_TYPES:
        return True
    value = token_value_upper(token)
    return (
        value in STATEMENT_KEYWORDS
        or value in SCOPE_TERMINATORS
        or value in CONTROL_FLOW_BOUNDARIES
    )


_StmtT = TypeVar("_StmtT", bound=ASTNode)


def create_statement(
    stream: ITokenStream, node_class: type[_StmtT]
) -> tuple[_StmtT, Token | None]:
    """Consume the leading verb token and factory-create its statement node.

    Returns ``(stmt, start_token)`` where *stmt* is created via the shared
    :func:`get_factory` at the start token's location (falling back to a zero
    location when the stream is exhausted). This collapses the identical
    ~8-line preamble shared by the IO statement parsers.
    """
    start_token = stream.consume()
    factory = get_factory()
    stmt = cast(
        _StmtT,
        factory.create(
            node_class,
            start_token.location if start_token else SourceLocation(0, 0),
        ),
    )
    return stmt, start_token


def peek_token(token_stream: ITokenStream, offset: int = 0) -> Token | None:
    """Safely peek into the stream, returning ``None`` on any failure.

    Used by the ``matches()`` probes in the registry, whose contract is to
    never raise: a broken or third-party stream implementation must result in
    ``False`` rather than a stack trace bubbling up through ``find_parser``.
    """
    try:
        return token_stream.peek(offset)
    except Exception as exc:
        # The probe contract is to never raise; emit at debug level so a
        # misbehaving stream implementation can still be diagnosed.
        logger.debug("peek_token(offset=%d) suppressed %r", offset, exc, exc_info=True)
        return None


def peek_value_upper(token_stream: ITokenStream, offset: int = 0) -> str:
    """Return upper-cased value of the token at ``peek(offset)``, or ``""``."""
    token = peek_token(token_stream, offset)
    return token.value.upper() if token and token.value else ""


def peek_value(token_stream: ITokenStream, offset: int = 0) -> str:
    """Return raw value of the token at ``peek(offset)``, or ``""``."""
    token = peek_token(token_stream, offset)
    return token.value if token and token.value else ""


def matches_keyword(token_stream: ITokenStream, token_type: Any, keyword: str) -> bool:
    """Return True if the next token matches *token_type* or is an IDENTIFIER equal to *keyword*.

    This is the canonical implementation for statement-parser ``matches()`` methods
    that detect a single COBOL verb.  It avoids the repetitive try/except and
    dual-check pattern that would otherwise be copy-pasted across every parser.
    Returns False on stream exhaustion so the registry can safely probe each parser.
    """
    token = peek_token(token_stream)
    if not token:
        return False
    return token.type == token_type or (
        token.type == TokenType.IDENTIFIER
        and token.value is not None
        and token.value.upper() == keyword
    )


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


# ---------------------------------------------------------------------------
# Clause-token collector (used by IO statement parsers)
# ---------------------------------------------------------------------------


def previous_meaningful_token(stream: ITokenStream) -> Token | None:
    """Return the last non-whitespace token consumed from *stream*, or None."""
    offset = -1
    while True:
        token = stream.peek(offset)
        if token is None:
            return None
        if token.type not in (
            TokenType.WHITESPACE,
            TokenType.COMMENT,
            TokenType.NEWLINE,
            TokenType.CONTINUATION,
        ):
            return token
        offset -= 1


def collect_clause_stmts(stream: ITokenStream, stop_at: set) -> list:
    """Parse the imperative statements of a conditional IO clause body.

    Dispatches through the statement registry attached to *stream* (the same
    mechanism IF/PERFORM/EVALUATE use for nested statements) until a clause
    boundary: a period, NOT / INVALID (the start of the next clause), a value
    in *stop_at*, or any scope terminator / control-flow boundary.  The
    boundary token is NOT consumed.  A nested statement that consumed the
    statement-terminating period ends the clause.  Tokens that no registered
    parser accepts are consumed one at a time so the loop always progresses.
    """
    stmts: list = []
    while not stream.is_empty():
        skip_whitespace(stream)
        token = stream.peek()
        if not token:
            break
        if token.type in (TokenType.PERIOD, TokenType.NOT, TokenType.INVALID):
            break
        value = token_value_upper(token)
        if (
            value in stop_at
            or value in SCOPE_TERMINATORS
            or value in CONTROL_FLOW_BOUNDARIES
        ):
            break
        nested = try_parse_nested_statement(stream)
        if nested is None:
            stream.consume()
            continue
        stmts.append(nested)
        prev = previous_meaningful_token(stream)
        if prev is not None and prev.type == TokenType.PERIOD:
            break
    return stmts


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


def try_consume_keyword(stream: ITokenStream, token_type: Any, keyword: str) -> bool:
    """Consume the next token if it is *token_type* or IDENTIFIER==*keyword*.

    Mirrors :func:`matches_keyword`'s dual type-or-identifier check. On a match
    the token is consumed and trailing whitespace skipped, and ``True`` is
    returned; otherwise the stream is left untouched and ``False`` is returned.
    *keyword* is matched case-insensitively against the upper-cased value.
    """
    token = stream.peek()
    if token and (
        token.type == token_type
        or (
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == keyword.upper()
        )
    ):
        stream.consume()
        skip_whitespace(stream)
        return True
    return False


def consume_key_is(stream: ITokenStream) -> bool:
    """Consume an optional ``KEY [IS]`` clause prefix.

    Handles both the ``KEY_IS`` single-token form and the ``KEY`` + optional
    ``IS`` form (where ``IS`` may arrive as a dedicated token or as an
    IDENTIFIER). Whitespace is skipped after each consumed token. Returns
    ``True`` if a KEY/KEY_IS token was present and consumed, ``False``
    otherwise (leaving the stream untouched). Shared by READ and START.
    """
    token = stream.peek()
    if not token or token.type not in (TokenType.KEY_IS, TokenType.KEY):
        return False
    stream.consume()
    skip_whitespace(stream)
    # If KEY (not KEY_IS), consume optional IS keyword.
    if token.type == TokenType.KEY:
        nxt = stream.peek()
        if nxt and nxt.type == TokenType.IS:
            stream.consume()
            skip_whitespace(stream)
        elif (
            nxt
            and nxt.type == TokenType.IDENTIFIER
            and nxt.value
            and nxt.value.upper() == "IS"
        ):
            stream.consume()
            skip_whitespace(stream)
    return True


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


def get_error_recovery_mode(
    context: ParseContext | None,
) -> ErrorRecoveryMode | None:
    """Return the host parser's ``error_recovery`` mode, if reachable."""
    if context is None:
        return None
    host = getattr(context, "host", None)
    if host is None:
        return None
    mode = getattr(host, "error_recovery", None)
    if isinstance(mode, ErrorRecoveryMode):
        return mode
    return None


def report_parse_error(
    context: ParseContext | None,
    message: str,
    location: SourceLocation,
) -> None:
    """Forward *message* to *context* if one is available."""
    if context:
        context.error(message, location)


def report_or_raise(
    context: ParseContext | None,
    message: str,
    location: SourceLocation | None = None,
) -> NoReturn:
    """Record a statement-level parse error and raise it.

    Always raises a ``ParseError`` so the enclosing division parser drives
    recovery uniformly: in ``FAIL_FAST`` it re-raises to short-circuit the
    parse, in ``COLLECT_ALL`` it records and skips to the next statement.

    The error is also appended to ``host.errors`` **before** the raise so
    diagnostics survive even when the raised exception is swallowed by
    :func:`try_parse_nested_statement` (which can hide nested-arithmetic
    failures inside IF/EVALUATE/PERFORM clauses). The raised exception is
    tagged with ``_already_recorded = True`` so the division-level handler
    can dedupe instead of adding it a second time.
    """
    line = getattr(location, "line", None) if location is not None else None
    column = getattr(location, "column", None) if location is not None else None
    err = ParseError(message, line_number=line, column=column, location=location)

    if context is not None:
        host = getattr(context, "host", None)
        if host is not None and hasattr(host, "add_error"):
            host.add_error(err)
            err._already_recorded = True  # type: ignore[attr-defined]

    raise err


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

    Any exception from a nested parse is swallowed here so a malformed inner
    statement does not abort the surrounding clause; the error is already
    reported via the parse context when statement parsers use
    :func:`report_or_raise`. This wide net is intentional — callers depend on
    the helper never raising during exploratory nested-statement dispatch.
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
    except Exception as exc:
        # Exploratory nested dispatch must never raise (the real error is
        # surfaced via the parse context); log at debug for diagnosability.
        logger.debug("try_parse_nested suppressed %r", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Arithmetic-statement shared helpers
# ---------------------------------------------------------------------------

#: Token types that may legally appear as an arithmetic operand.
#:
#: ``LEVEL_NUMBER`` is included because the lexer eagerly classifies bare
#: integers 01-99 as level numbers regardless of context, so ``ADD 1 TO A``
#: would otherwise lose its first operand. ``FIGURATIVE_CONSTANT`` is
#: included because ZERO/ZEROS/SPACES/etc. are valid COBOL operands anywhere
#: a literal is allowed, including arithmetic statements (e.g. ``MULTIPLY A
#: BY ZERO GIVING B``); the SUBTRACT ``FROM`` target already special-cased
#: this token type, so this keeps the shared operand set consistent with it.
ARITHMETIC_OPERAND_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.IDENTIFIER,
        TokenType.NUMERIC_LITERAL,
        TokenType.LEVEL_NUMBER,
        TokenType.FIGURATIVE_CONSTANT,
    }
)


#: Tokens that close an arithmetic-operand run regardless of value.
#:
#: PERIOD ends the statement; the rest are scope terminators that may follow
#: an arithmetic verb. Without this set, an operand run would walk past the
#: period of a malformed statement (e.g. ``ADD A.``) and devour subsequent
#: statements while looking for ``TO``/``GIVING``.
ARITHMETIC_OPERAND_STOP_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.PERIOD,
        TokenType.END_IF,
        TokenType.END_PERFORM,
        TokenType.END_EVALUATE,
    }
)


def parse_arithmetic_operands(
    stream: ITokenStream,
    stop_keywords: set[str] | frozenset[str],
) -> tuple[list[str], str]:
    """Consume tokens as arithmetic operands until a separator or boundary.

    Tokens of type IDENTIFIER, NUMERIC_LITERAL, or LEVEL_NUMBER are appended
    to the result; other intermediate tokens (commas, newlines, whitespace)
    are silently consumed so the parser is tolerant of incidental
    punctuation. Stops without consuming the boundary when any of these
    occur:

    * stream exhaustion;
    * a token whose upper-cased value is in *stop_keywords* (the expected
      separator, e.g. ``TO``/``GIVING``/``BY``/``FROM``);
    * a token in :data:`ARITHMETIC_OPERAND_STOP_TYPES` (period or scope
      terminator), which terminates the statement;
    * a token whose upper-cased value is a known statement keyword from
      :data:`STATEMENT_KEYWORDS` or a control-flow boundary from
      :data:`CONTROL_FLOW_BOUNDARIES`, so a malformed statement does not
      eat the next statement during recovery.

    Returns:
        A tuple ``(operands, stop_keyword)`` where ``stop_keyword`` is the
        upper-cased value of the token that ended the operand run, or
        ``""`` if the stream was exhausted or terminated on a non-keyword
        boundary token (period, scope terminator).
    """
    operands: list[str] = []
    while not stream.is_empty():
        token = stream.peek()
        if not token:
            break
        if token.type in ARITHMETIC_OPERAND_STOP_TYPES:
            return operands, ""
        upper = token.value.upper() if token.value else ""
        if upper in stop_keywords:
            return operands, upper
        if upper and (upper in STATEMENT_KEYWORDS or upper in CONTROL_FLOW_BOUNDARIES):
            # Don't devour the next statement when this one is malformed.
            return operands, ""
        if token.type in ARITHMETIC_OPERAND_TOKEN_TYPES and token.value:
            operands.append(token.value)
        stream.consume()
    return operands, ""


def consume_keyword_and_operand(
    stream: ITokenStream,
    keyword: str,
) -> str | None:
    """Consume *keyword* and the following IDENTIFIER, returning its value.

    Whitespace and NEWLINE tokens between the keyword and the identifier are
    skipped so that COBOL line continuations don't break clause recognition.

    Returns ``None`` if the keyword is not present at the current position or
    if no identifier follows it. The keyword check is case-insensitive.
    """
    if peek_value_upper(stream) != keyword.upper():
        return None
    stream.consume()
    _skip_newlines(stream)
    token = stream.peek()
    if token and token.type == TokenType.IDENTIFIER and token.value:
        value = token.value
        stream.consume()
        return value
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

    ``END-EXEC`` is the *mandatory* delimiter of an embedded EXEC block. If it
    is never found (the stream is exhausted first), the block is malformed and
    this collector would otherwise silently swallow the entire remainder of the
    program as SQL text. Unlike INSPECT/STRING/UNSTRING, an EXEC block cannot be
    bounded by a statement-keyword heuristic — embedded SQL/CICS/IMS text
    legitimately contains COBOL keywords (SET, DELETE, UPDATE, CALL, OPEN,
    CLOSE) — so the only safe response to a missing ``END-EXEC`` is to surface a
    parse error. When a parse context is reachable off *stream* (the procedure
    division attaches one via ``_attach_context``), an "unterminated EXEC block"
    error is recorded so the failure is visible instead of ``errors=0``.

    Args:
        stream: Token stream positioned at the first SQL token after ``SQL``.

    Returns:
        The reconstructed SQL text as a single string, without leading/trailing
        whitespace.
    """
    sql_parts: list[str] = []
    prev_was_colon = False
    terminated = False
    first_token = stream.peek(0)
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
            terminated = True
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

    if not terminated:
        context = get_parse_context(stream)
        if context is not None:
            report_parse_error(
                context,
                "Unterminated EXEC block: missing END-EXEC "
                "(the rest of the program was consumed as embedded text)",
                token_location(first_token),
            )

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
                # Stop at a period, the start of a NOT ON SIZE ERROR clause,
                # or any other statement/scope/control-flow boundary keyword
                # (e.g. END-SUBTRACT, ELSE) — otherwise the clause boundary
                # gets silently swallowed as a bogus display item.
                if (
                    t.type == TokenType.PERIOD
                    or t.type == TokenType.NOT
                    or (
                        t.type != TokenType.STRING_LITERAL
                        and t.value
                        and (
                            t.value.upper() in STATEMENT_KEYWORDS
                            or t.value.upper() in SCOPE_TERMINATORS
                            or t.value.upper() in CONTROL_FLOW_BOUNDARIES
                        )
                    )
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
            # Any other verb is skipped one token at a time (documented
            # limitation — DISPLAY/MOVE are the only inline mini-parsers).
            # But NOT (the start of NOT ON SIZE ERROR) and any scope/
            # control-flow boundary (END-SUBTRACT, ELSE, WHEN, ...) must NOT
            # be swallowed here, or the enclosing clause boundary silently
            # vanishes along with everything after it.
            if (
                token.type == TokenType.NOT
                or token_upper in SCOPE_TERMINATORS
                or token_upper in CONTROL_FLOW_BOUNDARIES
            ):
                break
            stream.consume()

    return nested
