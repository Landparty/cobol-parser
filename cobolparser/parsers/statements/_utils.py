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
        TokenType.CHAIN,
        TokenType.CLOSE,
        TokenType.COMMIT,
        TokenType.COMPUTE,
        TokenType.CONTINUE,
        TokenType.DELETE,
        TokenType.DISABLE,
        TokenType.DISPLAY,
        TokenType.DIVIDE,
        TokenType.EJECT,
        TokenType.ENABLE,
        TokenType.ENTER,
        TokenType.ENTRY,
        TokenType.EVALUATE,
        TokenType.EXAMINE,
        TokenType.EXEC,
        TokenType.EXECUTE,
        TokenType.EXHIBIT,
        TokenType.EXIT,
        TokenType.GENERATE,
        TokenType.GOBACK,
        TokenType.GOTO,
        TokenType.IF,
        TokenType.INITIALIZE,
        TokenType.INITIATE,
        TokenType.INSPECT,
        TokenType.INVOKE,
        TokenType.MERGE,
        TokenType.MOVE,
        TokenType.MULTIPLY,
        TokenType.NEXT,
        TokenType.NOTE,
        TokenType.OPEN,
        TokenType.PERFORM,
        TokenType.READ,
        TokenType.READY,
        TokenType.RECEIVE,
        TokenType.RECOVER,
        TokenType.RELEASE,
        TokenType.RESET,
        TokenType.RETURN,
        TokenType.REWRITE,
        TokenType.ROLLBACK,
        TokenType.SEARCH,
        TokenType.SEND,
        TokenType.SERVICE,
        TokenType.SET,
        TokenType.SKIP1,
        TokenType.SKIP2,
        TokenType.SKIP3,
        TokenType.SORT,
        TokenType.START,
        TokenType.STOP,
        TokenType.STRING,
        TokenType.SUBTRACT,
        TokenType.SUPPRESS,
        TokenType.TERMINATE,
        TokenType.TRANSFORM,
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

#: Token types whose value is literal content, never a keyword -- a string
#: literal spelled like a verb (``"IF"``, ``"STOP"``) must never be mistaken
#: for a statement boundary by a value-based keyword check.
LITERAL_TOKEN_TYPES: frozenset = frozenset(
    {
        TokenType.STRING_LITERAL,
        TokenType.NUMERIC_LITERAL,
        TokenType.LEVEL_NUMBER,
        TokenType.FIGURATIVE_CONSTANT,
    }
)

#: COBOL's optional separators. A comma or semicolon followed by a space is
#: syntactically equivalent to a space anywhere outside a PICTURE string or
#: literal (``PERFORM A, GO TO B.`` / ``CALL "X" USING A; ON OVERFLOW ...``);
#: statement-list loops skip them via :func:`skip_statement_separators`
#: instead of reporting them as "unparsed tokens".
SEPARATOR_TOKEN_TYPES: frozenset = frozenset({TokenType.COMMA, TokenType.SEMICOLON})

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
        "END-RECEIVE",
        "END-RETURN",
        "END-REWRITE",
        "END-SEARCH",
        "END-START",
        "END-STRING",
        "END-SUBTRACT",
        "END-UNSTRING",
        "END-WRITE",
        # XML/JSON GENERATE/PARSE scope terminators: a statement nested in
        # one of their ON EXCEPTION bodies must stop at them, not mistake
        # them for a paragraph header (2026-09-02, handler bodies parsed).
        "END-XML",
        "END-JSON",
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
        "CHAIN",
        "CLOSE",
        "COMMIT",
        "COMPUTE",
        "CONTINUE",
        "DELETE",
        "DISABLE",
        "DISPLAY",
        "DIVIDE",
        "EJECT",
        "ENABLE",
        "ENTER",
        "ENTRY",
        "EVALUATE",
        "EXAMINE",
        "EXEC",
        "EXECUTE",
        "EXHIBIT",
        "EXIT",
        "FREE",
        "GENERATE",
        "GO",
        "GOBACK",
        "GOTO",
        "IF",
        "INITIALIZE",
        "INITIATE",
        "INSPECT",
        "INVOKE",
        "JSON",
        "MERGE",
        "MOVE",
        "MULTIPLY",
        "NEXT",
        "NOTE",
        "OPEN",
        "PERFORM",
        "PURGE",
        "RAISE",
        "READ",
        "READY",
        "RECEIVE",
        "RECOVER",
        "RELEASE",
        "RESET",
        "RESUME",
        "RETURN",
        "REWRITE",
        "ROLLBACK",
        "SEARCH",
        "SEND",
        "SERVICE",
        "SET",
        "SKIP1",
        "SKIP2",
        "SKIP3",
        "SORT",
        "START",
        "STOP",
        "STRING",
        "SUBTRACT",
        "SUPPRESS",
        "TERMINATE",
        "TRANSFORM",
        "UNLOCK",
        "UNSTRING",
        "USE",
        "WRITE",
        "XML",
    }
)


# Reserved COBOL clause-continuation words that the lexer does not tokenize
# with a dedicated TokenType (unlike e.g. WITH/ON/FROM/TO/BY, which already
# have their own TokenType and so can never reach looks_like_paragraph_
# boundary's IDENTIFIER check at all) -- these lex as plain TokenType.
# IDENTIFIER but, being reserved words, can never legally be a paragraph
# name or an unrecognized verb, so they must never be misread as either.
# Sourced from the clause vocabularies of the statement parsers the H9 fix
# wired looks_like_paragraph_boundary into (DISPLAY, MOVE, COMPUTE,
# STRING/UNSTRING, INSPECT). Guards the layout IBM/GnuCOBOL style guides
# recommend: a multi-clause ``STRING a DELIMITED BY SIZE b DELIMITED BY
# SIZE c`` with each ``DELIMITED BY SIZE`` clause on its own continuation
# line, where every ``DELIMITED`` past the first would otherwise be at risk
# of being misread as a new statement.
CLAUSE_CONTINUATION_KEYWORDS: frozenset = frozenset(
    {
        "ALL",
        "COLUMN",
        "CONVERTING",
        "COUNT",
        "DELIMITED",
        "DELIMITER",
        "FILLER",
        "FUNCTION",
        "GIVING",
        "INITIAL",
        "OVERFLOW",
        "POINTER",
        "ROUNDED",
        "TALLYING",
    }
)

# DB2/SQL special registers that real COBOL programs legitimately reference
# (DISPLAY SQLCODE, IF SQLCODE NOT = 0, ...) without any WORKING-STORAGE
# declaration -- the SQL precompiler provides them, so they are never a
# "declared DATA DIVISION name" the way looks_like_paragraph_boundary's
# known_data_names cross-check expects. Deliberately narrow: only the two
# special registers commonly referenced bare (unsubscripted); array members
# like SQLERRD(3)/SQLWARN0 are followed by a token other than a clean
# line-start period and are not affected by this heuristic.
SQL_SPECIAL_REGISTERS: frozenset = frozenset({"SQLCODE", "SQLSTATE"})

# COBOL special registers: the compiler supplies them, so -- like SQLCODE
# above -- they are referenced without any DATA DIVISION declaration and
# never reach known_data_names, yet a register is a reserved word and can
# never name a paragraph. ``MOVE 0`` / ``TO`` / ``RETURN-CODE.`` with each
# word on its own line at the verb's column read as a MOVE with no target
# followed by a paragraph named RETURN-CODE (issue #390). LENGTH / ADDRESS
# (``LENGTH OF x``) are never followed by a bare period, so the shape check
# already passes them; they are listed for completeness.
SPECIAL_REGISTERS: frozenset = frozenset(
    {
        "ADDRESS",
        "DEBUG-ITEM",
        "JSON-CODE",
        "JSON-STATUS",
        "LENGTH",
        "LINAGE-COUNTER",
        "RETURN-CODE",
        "SHIFT-IN",
        "SHIFT-OUT",
        "SORT-CONTROL",
        "SORT-CORE-SIZE",
        "SORT-FILE-SIZE",
        "SORT-MESSAGE",
        "SORT-MODE-SIZE",
        "SORT-RETURN",
        "TALLY",
        "WHEN-COMPILED",
        "XML-CODE",
        "XML-EVENT",
        "XML-INFORMATION",
        "XML-NAMESPACE",
        "XML-NAMESPACE-PREFIX",
        "XML-NNAMESPACE",
        "XML-NNAMESPACE-PREFIX",
        "XML-NTEXT",
        "XML-TEXT",
    }
)

# Reserved words that end a statement's operand list (``STOP RUN``, ``EXIT
# PROGRAM``, ``SET flag TO TRUE``, ``NEXT SENTENCE``, ...) yet lex as plain
# IDENTIFIERs, so a statement wrapped one word per line puts them alone on a
# line before a period -- the paragraph-header shape. A reserved word can
# never be a paragraph name. DECLARATIVES / FACTORY / OBJECT are left out on
# purpose: each really does open a new structural unit at that shape.
NON_PARAGRAPH_RESERVED_WORDS: frozenset = frozenset(
    {
        "DOWN",
        "EXCEPTION",
        "FALSE",
        "METHOD",
        "OFF",
        "PARAGRAPH",
        "PROGRAM",
        "REMOVAL",
        "RUN",
        "SECTION",
        "SELF",
        "SENTENCE",
        "SIZE",
        "SUPER",
        "TRUE",
        "UP",
    }
)

# First Area B column of fixed-format source once normalize_fixed_format has
# dropped columns 1-7: old column 8 (Area A) becomes column 1, so old column
# 12 -- the start of Area B -- becomes column 5.
NORMALIZED_AREA_B_COLUMN = 5


# ---------------------------------------------------------------------------
# Token value helpers
# ---------------------------------------------------------------------------


def token_value_upper(token: Token | None) -> str:
    """Return the upper-cased value of *token*, or ``""`` if unavailable."""
    return token.value.upper() if token and token.value else ""


def keyword_upper(token: Token | None) -> str:
    """Like :func:`token_value_upper`, but ``""`` for a literal token.

    The lexer strips a string literal's quotes, so ``IF X = "ELSE"`` hands
    a condition collector a token whose *value* is ``ELSE``. Comparing
    ``keyword_upper(token)`` against clause keywords (THEN / ELSE / END-IF /
    WHEN / ALSO / AFTER / scope terminators) keeps such a literal as
    condition content instead of a clause boundary.
    """
    if token is None or token.type in LITERAL_TOKEN_TYPES:
        return ""
    return token_value_upper(token)


def token_location(token: Token | None) -> SourceLocation:
    """Return the source location of *token*, or a zero location if absent."""
    return token.location if token else SourceLocation(0, 0)


def token_column(token: Token | None) -> int | None:
    """Return the source column of *token*, or ``None`` when either the
    token or its location is absent.

    The single home for the ``getattr(getattr(token, "location", None),
    "column", None)`` incantation every statement parser's H9 dedent guard
    needs for its verb token -- pass the result to
    :func:`looks_dedented_relative_to`.
    """
    return getattr(getattr(token, "location", None), "column", None)


def is_procedure_name_token(token: Token | None) -> bool:
    """True if *token* can name a procedure: an identifier, or an all-digit
    numeric token. COBOL permits all-digit paragraph/section names, and
    ``PERFORM 1000 THRU 1999`` numbering is idiomatic in THRU-style code;
    the lexer emits those names as NUMERIC_LITERAL (or LEVEL_NUMBER for 1-2
    digit values), never IDENTIFIER. Shared by every statement that can
    target a paragraph by name (PERFORM, GO TO, ALTER).
    """
    if token is None or not token.value:
        return False
    if token.type == TokenType.IDENTIFIER:
        return True
    return (
        token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)
        and token.value.isdigit()
    )


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
    # A literal can never begin a statement: ``IF X = "IF"``, ``STRING "STOP"
    # DELIMITED BY SIZE`` and ``DISPLAY "MOVE"`` all carry a verb's spelling
    # inside quotes, and the lexer hands that spelling back as the literal's
    # value. Without this guard the value-based checks below misread the
    # literal as the next statement's verb and truncate the current one.
    if token.type in LITERAL_TOKEN_TYPES:
        return False
    if token.type in STATEMENT_TOKEN_TYPES:
        return True
    value = token_value_upper(token)
    return (
        value in STATEMENT_KEYWORDS
        or value in SCOPE_TERMINATORS
        or value in CONTROL_FLOW_BOUNDARIES
    )


def looks_like_paragraph_boundary(token_stream: ITokenStream) -> bool:
    """Detect the next paragraph/section header swallowed by a missing period.

    An operand-collection loop with no boundary awareness (DISPLAY's item
    list, MOVE's target list, COMPUTE's expression capture, ...) has no way
    to distinguish a legitimate trailing operand from a following paragraph
    name once the current statement's own period is missing -- both are just
    "IDENTIFIER then PERIOD". :func:`is_statement_boundary` only catches
    *known* verbs lexed as plain identifiers (PURGE, RESUME, ...); an
    ordinary user-defined paragraph name isn't in that set. See
    reports/open-findings.md H9.

    This resolves the ambiguity the way COBOL itself does: a paragraph name
    stands alone at the start of its own source line, whereas a trailing
    operand normally continues the line the verb or a preceding operand is
    on. So the current token counts as a boundary only when *all* of:

    * it is an IDENTIFIER, not a reserved statement verb;
    * it is not one of :data:`CLAUSE_CONTINUATION_KEYWORDS` (reserved COBOL
      clause words -- ``DELIMITED``, ``TALLYING``, ``POINTER``, ... -- that
      the lexer does not give a dedicated TokenType, so they reach this
      check as plain IDENTIFIERs even though a reserved word can never
      legally be a paragraph name) or :data:`SQL_SPECIAL_REGISTERS`
      (``SQLCODE``/``SQLSTATE``, which real programs reference without a
      WORKING-STORAGE declaration), :data:`SPECIAL_REGISTERS`
      (``RETURN-CODE``, ``TALLY``, ... -- likewise never declared) or
      :data:`NON_PARAGRAPH_RESERVED_WORDS` (``RUN``, ``TRUE``, ...);
    * it starts a new source line relative to the previously consumed token;
    * when the source was fixed-format, it starts in Area A -- a paragraph
      header must, so a token in Area B is an operand whatever it is named;
    * it is immediately followed by a period or SECTION -- required because
      a continuation-line operand named by an *unexpanded* COPY member is
      not in ``known_data_names``, and without this shape check it would be
      misread as a boundary, truncating the statement;
    * it is not a name declared in the DATA DIVISION -- excluded so a
      genuinely wrapped continuation-line operand (``DISPLAY\\n    WS-X.``)
      is not misread as a paragraph header just because it opens its line.

    A bare trailing operand that happens to sit on its own line but is not a
    real paragraph name (e.g. an undeclared identifier from an unexpanded
    COPY) will still be misclassified -- this is an inherent ambiguity of
    missing-period recovery, not something a purely syntactic check can
    resolve, so the DATA DIVISION cross-check is a best-effort narrowing,
    not a guarantee.
    """
    token = token_stream.peek(0)
    if token is None or token.type != TokenType.IDENTIFIER or not token.value:
        return False
    value_upper = token.value.upper()
    if (
        value_upper in STATEMENT_KEYWORDS
        or value_upper in CLAUSE_CONTINUATION_KEYWORDS
        or value_upper in SQL_SPECIAL_REGISTERS
        or value_upper in SPECIAL_REGISTERS
        or value_upper in NON_PARAGRAPH_RESERVED_WORDS
    ):
        return False

    prev = previous_meaningful_token(token_stream)
    prev_line = getattr(getattr(prev, "location", None), "line", None)
    cur_line = getattr(getattr(token, "location", None), "line", None)
    if prev_line is None or cur_line is None or prev_line == cur_line:
        return False

    context = get_parse_context(token_stream)
    if _in_fixed_format_area_b(context, token):
        return False

    # The candidate must be immediately followed by a period or SECTION —
    # the bare paragraph-header shape. This deliberately under-detects
    # (an unknown verb followed by its own operands is not caught), but
    # dropping it is a proven real-world regression: a continuation-line
    # operand whose name comes from an *unexpanded* COPY member is not in
    # known_data_names, so without this shape check it is misread as a
    # boundary and the statement is truncated (caught by mocky-mock's
    # copybook fixtures: `COMPUTE X =` / newline / `ORD-AMOUNT ...`).
    offset = 1
    nxt = token_stream.peek(offset)
    while nxt is not None and nxt.type in (
        TokenType.WHITESPACE,
        TokenType.COMMENT,
        TokenType.NEWLINE,
        TokenType.CONTINUATION,
    ):
        offset += 1
        nxt = token_stream.peek(offset)
    if nxt is None:
        return False
    is_period = nxt.type == TokenType.PERIOD
    is_section = bool(nxt.value) and nxt.value.upper() == "SECTION"
    if not (is_period or is_section):
        return False

    known_data_names = context.known_data_names if context else frozenset()
    return value_upper not in known_data_names


def _in_fixed_format_area_b(context: ParseContext | None, token: Token) -> bool:
    """True when the parse normalized fixed-format source and *token* starts
    in Area B, where no paragraph or section header can begin. Free-form
    source has no areas, so this never fires there."""
    host = getattr(context, "host", None) if context else None
    if getattr(host, "source_is_fixed_format", False) is not True:
        return False
    col = token_column(token)
    return col is not None and col >= NORMALIZED_AREA_B_COLUMN


def looks_dedented_relative_to(
    token_stream: ITokenStream, reference_column: int | None
) -> bool:
    """True when the token at the stream's current position starts at a
    shallower column than *reference_column*.

    Used to tell a genuine paragraph/section header (dedented back to Area A)
    apart from an operand that merely continues the statement's own line
    (Area B, deeper indentation) once :func:`looks_like_paragraph_boundary`
    has already confirmed the token has the bare "IDENTIFIER then period/SECTION"
    shape both share. *reference_column* is normally the statement's own verb
    column; missing location info (either side) defaults to True (dedented) --
    the conservative "treat as boundary" behavior this call replaces.

    A token at the SAME column as the verb also counts as dedented: at
    equal columns the indentation signal cannot distinguish the two
    readings, and treating the token as an operand there silently swallows
    the next paragraph out of the AST with no diagnostic (real decks do
    write statements flush in Area A alongside their headers), whereas
    treating it as a boundary at worst truncates one operand list WITH the
    :func:`warn_paragraph_boundary_swallowed` warning attached -- the same
    visible, pre-guard behavior. Only a strictly deeper token (the normal
    continuation-line layout) is treated as an operand.

    Every operand-collection loop that calls :func:`looks_like_paragraph_boundary`
    must AND it with this check, not just for the loop's first operand: a
    second-or-later operand sitting on its own continuation line (same or
    deeper column than the verb) is exactly as legitimate as the first one,
    and skipping the dedent check once at least one operand has already been
    collected silently truncates the operand list (see reports/open-findings.md).
    """
    token = token_stream.peek(0)
    col = token_column(token)
    if reference_column is None or col is None:
        return True
    return bool(col <= reference_column)


def warn_paragraph_boundary_swallowed(token_stream: ITokenStream) -> None:
    """Record a warning when :func:`looks_like_paragraph_boundary` stops an
    operand-collection loop early instead of consuming what looks like the
    next paragraph/section header. See reports/open-findings.md H9.
    """
    token = token_stream.peek(0)
    value = (token.value or "") if token is not None else ""
    line = getattr(getattr(token, "location", None), "line", None) if token else None
    where = f" at line {line}" if line else ""
    message = (
        f"Statement missing its terminating period{where}: '{value}' looks "
        "like the start of the next paragraph/section rather than a "
        "trailing operand -- treated as a new paragraph boundary instead "
        "of being consumed"
    )
    context = get_parse_context(token_stream)
    host = getattr(context, "host", None) if context else None
    add_warning = getattr(host, "add_warning", None)
    if callable(add_warning):
        add_warning(message)


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


def skip_statement_separators(stream: ITokenStream) -> None:
    """Consume layout tokens *and* stray ``,`` / ``;`` separators.

    For use at the top of a statement-list loop (paragraph bodies, IF/ELSE
    branches, inline PERFORM bodies, handler clauses), where a comma or
    semicolon between two statements is a plain COBOL separator with no
    meaning. Not for operand lists -- there the individual parsers decide
    what a comma separates.
    """
    while not stream.is_empty():
        skip_whitespace(stream)
        token = stream.peek()
        if token is None or token.type not in SEPARATOR_TOKEN_TYPES:
            break
        stream.consume()


def matches_word(
    stream: ITokenStream, word: str, token_type: Any | None = None
) -> bool:
    """Return True if the next token is *word* (case-insensitive).

    Like :func:`matches_keyword`, but safe for verbs the lexer has no
    dedicated ``TokenType`` for (PURGE, RAISE, RESUME, VALIDATE, TITLE ...):
    a dedicated *token_type* matches by type, otherwise only an IDENTIFIER
    whose value is *word* matches -- ``matches_keyword(stream,
    TokenType.IDENTIFIER, word)`` would accept *any* identifier.
    """
    token = peek_token(stream)
    if not token:
        return False
    if token_type is not None and token.type == token_type:
        return True
    return token.type == TokenType.IDENTIFIER and token_value_upper(token) == word


#: Token types accepted as a plain operand by :func:`collect_operands`.
_OPERAND_TOKEN_TYPES: frozenset = frozenset(
    {
        TokenType.IDENTIFIER,
        TokenType.STRING_LITERAL,
        TokenType.NUMERIC_LITERAL,
        TokenType.LEVEL_NUMBER,
        TokenType.FIGURATIVE_CONSTANT,
    }
)


def collect_operands(
    stream: ITokenStream,
    *,
    stop_at: frozenset | set | None = None,
    max_items: int | None = None,
    start_column: int | None = None,
) -> list[str]:
    """Consume a run of operands (data-names, literals, figurative constants).

    Stops -- without consuming the boundary -- at the sentence period, any
    statement/scope boundary (:func:`is_statement_boundary`), a value in
    *stop_at*, a token that cannot be an operand, or (when *start_column* is
    given) what looks like the next paragraph header after a missing period
    (the same H9 heuristic the DISPLAY/SET parsers apply). Separator commas
    and semicolons between operands are skipped. Identifiers have a trailing
    subscript and/or ``OF``/``IN`` qualifier chain folded in; string
    literals are re-quoted exactly as DISPLAY's item list does; signed
    numerics (``-1``) are recomposed.
    """
    from cobolparser._literals import quote_literal

    stop_words = {w.upper() for w in (stop_at or ())}
    operands: list[str] = []
    while not stream.is_empty():
        if max_items is not None and len(operands) >= max_items:
            break
        skip_whitespace(stream)
        token = stream.peek()
        if token is None or token.type == TokenType.PERIOD:
            break
        if token.type in SEPARATOR_TOKEN_TYPES:
            stream.consume()
            continue
        signed = consume_signed_numeric(stream)
        if signed is not None:
            operands.append(signed)
            continue
        if token_value_upper(token) in stop_words:
            break
        if token.type not in _OPERAND_TOKEN_TYPES:
            break
        if token.type == TokenType.IDENTIFIER:
            if is_statement_boundary(token):
                break
            if (
                start_column is not None
                and looks_like_paragraph_boundary(stream)
                and looks_dedented_relative_to(stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(stream)
                break
        stream.consume()
        value = token.value or ""
        if token.type == TokenType.STRING_LITERAL:
            value = token.raw_value if token.raw_value else quote_literal(value)
        elif token.type == TokenType.IDENTIFIER:
            value = consume_optional_qualifiers(stream, value)
        operands.append(value)
    return operands


def consume_procedure_qualifier(stream: ITokenStream) -> str | None:
    """Consume a trailing ``OF section`` / ``IN section`` procedure-name
    qualifier if one follows; return the section name, else ``None``.

    Only claims the OF/IN when a plain identifier follows it, so a dangling
    qualifier is left in the stream exactly as :func:`consume_optional_
    qualifiers` leaves a dangling data-name qualifier.
    """
    look, idx = peek_past_noise(stream, 0)
    if look is None or look.type not in (TokenType.OF, TokenType.IN):
        return None
    name, _ = peek_past_noise(stream, idx + 1)
    if not (name and name.type == TokenType.IDENTIFIER and name.value):
        return None
    skip_whitespace(stream)
    stream.consume()  # OF / IN
    skip_whitespace(stream)
    stream.consume()  # section name
    skip_whitespace(stream)
    return name.value


def bare_end_starts_at_end_clause(stream: ITokenStream) -> bool:
    """True if the next token is a bare ``END`` opening an ``[AT] END`` clause.

    ``AT`` is optional in READ / RETURN / SEARCH's ``AT END`` phrase. A bare
    ``END`` is only taken as that clause when it is *not* the start of an
    ``END PROGRAM`` / ``END DIVISION`` marker, so a period-less READ at the
    very end of a program cannot swallow the program terminator.
    """
    token = stream.peek()
    if (
        token is None
        or token.type != TokenType.IDENTIFIER
        or token_value_upper(token) != "END"
    ):
        return False
    lookahead, _ = peek_past_noise(stream, 1)
    return not (
        lookahead
        and lookahead.value
        and lookahead.value.upper() in ("PROGRAM", "DIVISION")
    )


#: Words that, after ``NOT``, open a conditional statement's negative handler
#: phrase: ``NOT [AT] END``, ``NOT INVALID [KEY]``, ``NOT [ON] EXCEPTION`` /
#: ``OVERFLOW`` / ``SIZE ERROR``, ``NOT [AT] END-OF-PAGE``. All reserved, so
#: ``NOT`` in front of one is never a condition's negation.
_NEGATIVE_HANDLER_WORDS = frozenset(
    {
        "AT",
        "END",
        "INVALID",
        "ON",
        "EXCEPTION",
        "OVERFLOW",
        "SIZE",
        "END-OF-PAGE",
        "EOP",
    }
)


def starts_negative_handler_phrase(stream: ITokenStream) -> bool:
    """True if the stream is at ``NOT`` opening a handler phrase.

    A statement with no such phrase of its own (INSPECT, SORT, a PERFORM
    UNTIL condition, ...) nested in another statement's handler is followed
    by the enclosing statement's ``NOT AT END`` / ``NOT INVALID KEY`` / ``NOT
    ON EXCEPTION`` / ``NOT ON SIZE ERROR``. Its clause loop must stop there:
    consuming the phrase lost the enclosing handler and folded its
    statements into the wrong branch, silently.
    """
    token = stream.peek()
    if token is None or token.type in LITERAL_TOKEN_TYPES:
        return False
    if token_value_upper(token) != "NOT":
        return False
    following, _ = peek_past_noise(stream, 1)
    return (
        following is not None
        and following.type not in LITERAL_TOKEN_TYPES
        and token_value_upper(following) in _NEGATIVE_HANDLER_WORDS
    )


def consume_period(stream: ITokenStream) -> None:
    """Consume a period token if it is the next non-empty token."""
    if not stream.is_empty():
        t = stream.peek()
        if t and t.type == TokenType.PERIOD:
            stream.consume()


#: Token types that carry no statement meaning between two meaningful
#: tokens (same set skip_whitespace consumes). Shared by every
#: non-destructive lookahead in this package -- keep it the single home
#: for this set so a new noise token type cannot desynchronize one
#: lookahead from the others.
_NOISE_TOKEN_TYPES = (
    TokenType.WHITESPACE,
    TokenType.COMMENT,
    TokenType.NEWLINE,
    TokenType.CONTINUATION,
)


def peek_past_noise(stream: ITokenStream, offset: int) -> tuple[Token | None, int]:
    """Return the first non-noise token at or after *offset*, and its offset.

    Non-destructive: nothing is consumed, so a lookahead that turns out not
    to match leaves the stream untouched for the caller.
    """
    token = stream.peek(offset)
    while token is not None and token.type in _NOISE_TOKEN_TYPES:
        offset += 1
        token = stream.peek(offset)
    return token, offset


def consume_signed_numeric(stream: ITokenStream) -> str | None:
    """Consume a sign-prefixed numeric literal (``-1``, ``+2``) if present.

    The lexer emits a signed literal as two tokens -- MINUS/PLUS, then the
    number (which for one/two digits is a LEVEL_NUMBER token, not
    NUMERIC_LITERAL) -- so every single-token value read that meets one
    captures only the sign and strands the digits. This is the shared home
    for the recomposition: PERFORM VARYING/AFTER's FROM/BY values, SET's
    TO/UP BY/DOWN BY values, and the arithmetic verbs' operands all hit
    the same split (``BY -1`` is every countdown loop).

    Returns the composed value (e.g. ``"-1"``) when the next token is a
    sign followed -- possibly across a line break, since a 72-column deck
    can wrap between the sign and its digits -- by a numeric token, and
    ``None`` (consuming nothing) otherwise. The lookahead past
    WHITESPACE/COMMENT/NEWLINE/CONTINUATION tokens is non-destructive, so
    a sign that turns out not to prefix a number is left untouched for
    the caller.
    """
    token = stream.peek()
    if not token or token.type not in (TokenType.MINUS, TokenType.PLUS):
        return None
    next_tok, offset = peek_past_noise(stream, 1)
    if not (
        next_tok
        and next_tok.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)
        and next_tok.value
    ):
        return None
    sign = token.value or ""
    for _ in range(offset + 1):
        stream.consume()
    return sign + next_tok.value


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
        if token.type not in _NOISE_TOKEN_TYPES:
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
        skip_statement_separators(stream)
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
    # ``START F ; INVALID KEY`` -- a separator before the clause is plain
    # punctuation (NIST IX208A/RL205A write it that way).
    skip_statement_separators(stream)
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

    # NOT INVALID KEY. The NOT is only this clause's when INVALID follows:
    # ``READ ... INVALID KEY DELETE F2 NOT INVALID KEY`` is fine, but a
    # nested statement's ``NOT`` in front of an enclosing CALL's ``ON
    # EXCEPTION`` / READ's ``AT END`` was consumed and discarded here, so the
    # enclosing handler could no longer be recognized.
    token = stream.peek()
    following, _ = peek_past_noise(stream, 1)
    if (
        token
        and token.type == TokenType.NOT
        and following is not None
        and following.type == TokenType.INVALID
    ):
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
        # surfaced via the parse context when report_or_raise pre-records
        # it into host.errors before raising). Exceptions that bypass
        # report_or_raise entirely -- e.g. TokenMismatch/UnexpectedEndOfInput
        # raised directly by token_stream.expect() -- would otherwise vanish
        # with only this DEBUG line; surface those as a warning so a caller
        # checking ParseResult.warnings isn't blind to the failure (M9).
        logger.debug("try_parse_nested suppressed %r", exc, exc_info=True)
        if not getattr(exc, "_already_recorded", False):
            context = get_parse_context(stream)
            host = getattr(context, "host", None) if context else None
            add_warning = getattr(host, "add_warning", None)
            if callable(add_warning):
                add_warning(f"Nested statement parse failed and was skipped: {exc}")
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
    punctuation. An IDENTIFIER operand also folds a trailing
    ``(subscript)`` group and/or ``OF``/``IN`` qualifier chain into the
    same result entry via :func:`consume_optional_qualifiers` (e.g. ``ADD
    QUAL OF GROUP-A TO ...`` yields the single addend ``"QUAL OF
    GROUP-A"``, not a bare ``"QUAL"`` followed by a spurious separate
    ``"GROUP-A"`` addend). Stops without consuming the boundary when any of
    these occur:

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
        if (
            upper
            and token.type not in LITERAL_TOKEN_TYPES
            and (upper in STATEMENT_KEYWORDS or upper in CONTROL_FLOW_BOUNDARIES)
        ):
            # Don't devour the next statement when this one is malformed.
            return operands, ""
        # A sign-prefixed numeric addend (``ADD -1 TO WS-X`` -- the same
        # two-token MINUS/PLUS + number split every other value-reading
        # path recomposes) must go through consume_signed_numeric here
        # too, or the fall-through consume below silently drops the sign
        # and records a sign-inverted operand.
        signed = consume_signed_numeric(stream)
        if signed is not None:
            operands.append(signed)
            continue
        if token.type in ARITHMETIC_OPERAND_TOKEN_TYPES and token.value:
            value = token.value
            stream.consume()
            if token.type == TokenType.IDENTIFIER:
                value = consume_optional_qualifiers(stream, value)
            operands.append(value)
            continue
        stream.consume()
    return operands, ""


def _looks_like_statement_boundary(token: Token) -> bool:
    """True if *token* can never legally appear inside a subscript's parens.

    A period, an arithmetic scope terminator, or a real statement/control-
    flow keyword can never be part of a subscript expression -- used to stop
    :func:`consume_optional_subscript`'s paren-depth loop before it runs
    past the current statement.
    """
    if token.type in ARITHMETIC_OPERAND_STOP_TYPES:
        return True
    if token.type in LITERAL_TOKEN_TYPES:
        return False
    upper = token.value.upper() if token.value else ""
    return bool(upper) and (
        upper in STATEMENT_KEYWORDS or upper in CONTROL_FLOW_BOUNDARIES
    )


def consume_optional_subscript(stream: ITokenStream, parts: list[str]) -> None:
    """Consume a trailing ``(...)`` subscript group, appending it to *parts*.

    If the next token is not ``LEFT_PAREN``, *parts* is left untouched. Paren
    depth is tracked so a nested call like ``WS-T(FUNCTION FOO(I))`` is
    captured correctly. Shared by every target-consuming helper that must
    fold a subscript group into its result string instead of leaving it to
    be dropped as an unparsed trailing token -- directly by
    :func:`consume_optional_qualifiers` below (which also folds a trailing
    ``OF``/``IN`` qualifier chain, and backs COMPUTE/ADD/SUBTRACT targets,
    MULTIPLY/DIVIDE operands, the arithmetic ``GIVING`` clause, and
    DIVIDE's ``REMAINDER`` clause).

    An unclosed ``(`` (missing ``)``) stops at the first token that could
    never legally appear inside a subscript (see
    :func:`_looks_like_statement_boundary`) rather than running to end of
    stream looking for a ``)`` that was never there -- without this, a
    malformed addend like ``ADD TBL (IDX TO C.`` would devour every
    following statement (including the closing ``.`` and everything past
    it) while hunting for a matching paren.
    """
    next_token = stream.peek()
    if not (next_token and next_token.type == TokenType.LEFT_PAREN):
        return
    depth = 0
    while not stream.is_empty():
        t = stream.peek()
        if not t:
            break
        if depth > 0 and _looks_like_statement_boundary(t):
            break
        if t.type == TokenType.LEFT_PAREN:
            depth += 1
            parts.append("(")
        elif t.type == TokenType.RIGHT_PAREN:
            depth -= 1
            parts.append(")")
        else:
            parts.append(t.value if t.value else "")
        stream.consume()
        if depth == 0:
            break


def consume_optional_qualifiers(stream: ITokenStream, value: str) -> str:
    """Fold a trailing ``(...)`` subscript and/or ``OF``/``IN`` qualifier
    chain onto *value*, returning the combined string.

    Handles ``TABLE1 (INDEX1)``, ``QUAL OF PARENT``, ``QUAL OF PARENT
    (IDX)``, and a qualifier chain spanning a continuation line (e.g.
    ``NAME\\n    IN GROUP-48 IN GROUP-47``) -- COBOL places no limit on how
    many OF/IN hops a qualified reference may carry, and each hop may itself
    be followed by a subscript once it resolves to a table element. Shared
    by every identifier-consuming helper that must fold subscripts/
    qualifiers into its result string instead of leaving them to be dropped
    as unparsed trailing tokens: :func:`_consume_arithmetic_target` and
    :func:`_consume_arithmetic_operand` (``arithmetic_parsers.py``, backing
    COMPUTE/ADD/SUBTRACT targets and MULTIPLY/DIVIDE operands),
    :func:`consume_keyword_and_operand` below (the ``GIVING``/``REMAINDER``
    clauses), :func:`parse_arithmetic_operands` above (ADD's/SUBTRACT's
    addend list), and MOVE's target (``move_parser.py``).

    A dangling ``OF``/``IN`` with no identifier following it (a malformed
    qualifier, e.g. ``ADD A OF TO B.``) is left untouched in the stream
    rather than consumed and discarded -- the lookahead below confirms an
    identifier is actually there *before* consuming the keyword, so a
    caller further up the chain sees the same unconsumed ``OF``/``IN`` an
    unqualified reference would have left behind, instead of it vanishing
    with no trace.
    """
    parts: list[str] = [value]
    while not stream.is_empty():
        # qualifiers/subscripts may span a continuation line, which in
        # fixed-format source carries a leading CONTINUATION token
        # (column-7 '-'), not just NEWLINE -- skip_whitespace (not the
        # narrower _skip_newlines) covers both, mirroring
        # consume_keyword_and_operand's own rationale below.
        skip_whitespace(stream)
        token = stream.peek()
        if not token:
            break
        if token.type == TokenType.LEFT_PAREN:
            consume_optional_subscript(stream, parts)
            continue
        if token.type in (TokenType.OF, TokenType.IN):
            # Confirm a real identifier follows *before* consuming OF/IN --
            # peek() doesn't skip noise tokens, so scan past those
            # non-destructively first.
            lookahead, _ = peek_past_noise(stream, 1)
            if not (
                lookahead and lookahead.type == TokenType.IDENTIFIER and lookahead.value
            ):
                break
            qualifier_kw = token.value
            stream.consume()  # consume OF/IN
            skip_whitespace(stream)
            qname = stream.consume()
            parts.append(qualifier_kw)
            parts.append(qname.value or "")
            continue
        break
    return " ".join(p for p in parts if p)


def literal_operand_text(token: Token) -> str:
    """A consumed operand token's text, a string literal kept quoted.

    The lexer hands a ``STRING_LITERAL`` over decoded -- delimiters stripped
    -- so an operand recorded as bare ``token.value`` made the literal
    ``'A'`` indistinguishable from the data item ``A`` (and ``X'00'`` from
    the two characters ``00``). A typed literal keeps its original prefixed
    spelling from ``raw_value``; any other is re-quoted by
    :func:`~cobolparser._literals.quote_literal` -- the convention MOVE and
    DISPLAY already follow. Every other token's value is returned as is.
    """
    from cobolparser._literals import quote_literal

    if token.type == TokenType.STRING_LITERAL:
        return token.raw_value or quote_literal(token.value)
    return token.value or ""


def consume_value_operand(stream: ITokenStream) -> str | None:
    """Consume one value operand (a literal or data name) if present.

    A single token in the common case, with two real-deck extensions: a
    *signed* numeric literal (``BY -1`` is how every countdown loop is
    written) lexes as two tokens -- MINUS/PLUS then the number, possibly
    split across a 72-column line break -- and is recomposed by
    :func:`consume_signed_numeric`; a subscripted or qualified data-name
    value (``FROM WS-TAB-VAL(I)``, ``TO WS-START OF WS-CTL``) has its
    trailing tokens folded in by :func:`consume_optional_qualifiers`, which
    would otherwise strand them in the stream to be dropped as unparsed
    trailing tokens. Shared by PERFORM VARYING/AFTER's ``FROM``/``BY``
    values and SET's ``TO``/``UP BY``/``DOWN BY`` values. Returns the
    composed value, or ``None`` (consuming nothing) when no value token is
    present.
    """
    signed = consume_signed_numeric(stream)
    if signed is not None:
        return signed
    token = stream.peek()
    if not token or not token.value:
        return None
    value = literal_operand_text(token)
    stream.consume()
    if token.type == TokenType.IDENTIFIER:
        value = consume_optional_qualifiers(stream, value)
    return value


def consume_from_operand(stream: ITokenStream) -> str | None:
    """Consume the sending operand of ``WRITE``/``REWRITE ... FROM``.

    ``FROM identifier-1 | literal-1``: a data name (subscript / OF-IN chain
    folded in), or any literal -- a quoted one kept quoted (a typed literal
    such as ``X"41"`` in its original spelling), a numeric one (``1``-``49``
    lex as LEVEL_NUMBER, a sign is its own token), or a figurative constant
    with an optional ``ALL`` (``FROM SPACES``, ``FROM ALL "*"``). Returns the
    operand text, or ``None`` (consuming nothing) when no operand follows.
    """
    from cobolparser._literals import quote_literal

    signed = consume_signed_numeric(stream)
    if signed is not None:
        return signed
    token = stream.peek()
    if not token or not token.value:
        return None
    if token.type == TokenType.IDENTIFIER:
        stream.consume()
        return consume_optional_qualifiers(stream, token.value)
    prefix = ""
    if token.type == TokenType.FIGURATIVE_CONSTANT and token.value.upper() == "ALL":
        following = peek_token(stream, 1)
        if following is not None and following.type in (
            TokenType.STRING_LITERAL,
            TokenType.FIGURATIVE_CONSTANT,
        ):
            stream.consume()
            prefix = "ALL "
            token = following
    if token.type == TokenType.STRING_LITERAL:
        stream.consume()
        return prefix + (token.raw_value or quote_literal(token.value))
    if token.type in (
        TokenType.NUMERIC_LITERAL,
        TokenType.LEVEL_NUMBER,
        TokenType.FIGURATIVE_CONSTANT,
    ):
        stream.consume()
        return prefix + token.value
    return None


def consume_keyword_and_operand(
    stream: ITokenStream,
    keyword: str,
) -> str | None:
    """Consume *keyword* and the following IDENTIFIER, returning its value.

    WHITESPACE/COMMENT/NEWLINE/CONTINUATION tokens before the keyword itself
    are also skipped (not just between the keyword and its operand): a
    clause like `SUBTRACT A FROM B\\n    GIVING C` puts GIVING on its own
    continuation line, which is ordinary free-form COBOL layout, not a
    statement boundary -- and in fixed-format source that continuation line
    can carry a leading CONTINUATION token (column-7 `-`), not just NEWLINE,
    so `skip_whitespace` (not the narrower `_skip_newlines`) is used here.
    Skipping unconditionally is safe because none of these token types carry
    clause-boundary meaning elsewhere in this parser (only PERIOD/scope-
    terminator tokens do), and every other optional-clause lookahead in this
    module already tolerates them.

    The same tokens between the keyword and the identifier are also skipped
    so that COBOL line continuations don't break clause recognition.

    A trailing ``(subscript[, subscript]...)`` group and/or ``OF``/``IN``
    qualifier chain on the operand is folded into the returned string via
    :func:`consume_optional_qualifiers` (e.g. ``GIVING RESULT (H, I, 1)``
    -> ``"RESULT ( H , I , 1 )"``, ``GIVING RESULT-F OF GROUP-A`` ->
    ``"RESULT-F OF GROUP-A"``) -- a GIVING/REMAINDER target is a data item
    just like an ADD/SUBTRACT ``TO``/``FROM`` target and may equally be
    table-subscripted or qualified.

    Returns ``None`` if the keyword is not present at the current position or
    if no identifier follows it. The keyword check is case-insensitive.
    """
    skip_whitespace(stream)
    if peek_value_upper(stream) != keyword.upper():
        return None
    stream.consume()
    skip_whitespace(stream)
    token = stream.peek()
    if token and token.type == TokenType.IDENTIFIER and token.value:
        value = token.value
        stream.consume()
        return consume_optional_qualifiers(stream, value)
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


def parse_size_error_clauses(
    stream: ITokenStream, stmt: Any, end_keyword: str | None = None
) -> None:
    """Parse optional ON SIZE ERROR / NOT ON SIZE ERROR clauses.

    Calls ``stmt.set_on_size_error_clause()`` and
    ``stmt.set_not_on_size_error_clause()`` when the clauses are present and
    consumes the trailing period. Used by ADD, SUBTRACT, MULTIPLY, DIVIDE, and
    COMPUTE statement parsers.

    *end_keyword* is the verb's explicit scope terminator (``"END-ADD"``,
    ``"END-COMPUTE"``, ...). When present in the token stream at this point --
    with or without a preceding ON/NOT ON SIZE ERROR clause -- it is consumed
    along with an optional trailing period. Without this, the terminator (an
    IDENTIFIER token with no dedicated TokenType) was left unconsumed and the
    procedure division's paragraph-boundary lookahead misread it as a new
    paragraph header, silently reparenting every statement that followed it.
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
        # ``ON`` is optional in every SIZE ERROR phrase (``ADD A TO B SIZE
        # ERROR ...`` / ``NOT SIZE ERROR ...`` are standard COBOL). Previously
        # a bare SIZE ERROR was not recognised here at all, so the handler
        # body escaped to the enclosing paragraph as free-standing statements
        # with no error and no warning.
        if token_upper in ("ON", "SIZE"):
            if token_upper == "ON":
                stream.consume()
                next_token = _skip_newlines(stream)
                if not (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "SIZE"
                ):
                    continue
            stream.consume()  # SIZE
            next_token = _skip_newlines(stream)
            if next_token and next_token.value and next_token.value.upper() == "ERROR":
                stream.consume()
                stmt.set_on_size_error_clause(_parse_size_error_stmts(stream))
        elif token_upper == "NOT":
            # Only claim NOT when it really opens ``NOT [ON] SIZE ERROR``:
            # an arithmetic statement inside a CALL handler is followed by
            # the CALL's own ``NOT ON EXCEPTION``, which must be left alone.
            look, idx = peek_past_noise(stream, 1)
            if look and look.value and look.value.upper() == "ON":
                look, _ = peek_past_noise(stream, idx + 1)
            if not (look and look.value and look.value.upper() == "SIZE"):
                break
            stream.consume()  # NOT
            next_token = _skip_newlines(stream)
            if next_token and next_token.value and next_token.value.upper() == "ON":
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
                    stmt.set_not_on_size_error_clause(_parse_size_error_stmts(stream))
        elif end_keyword is not None and token_upper == end_keyword:
            stream.consume()
            skip_whitespace(stream)
            consume_period(stream)
            break
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

#: (previous token type, current token type) pairs that the lexer produces
#: for a two-character relational/concatenation operator it has no dedicated
#: token for -- ``>=``, ``<=``, ``<>``, ``!=``, ``¬=`` all lex as two
#: single-char tokens (GREATER/LESS + ASSIGN, LESS + GREATER, BANG + ASSIGN,
#: or NOT_SIGN + ASSIGN), and ``||`` (SQL string concatenation) lexes as two
#: PIPE tokens. Rejoining them with ``" ".join`` would corrupt
#: ``WHERE SALARY >= :WS-ID`` into ``"...SALARY > =:WS-ID..."`` (or turn
#: ``COL1 || COL2`` into ``COL1 | | COL2``).
_EXEC_SQL_SPLIT_RELOP_PAIRS: frozenset[tuple[TokenType, TokenType]] = frozenset(
    {
        (TokenType.GREATER, TokenType.ASSIGN),  # >=
        (TokenType.LESS, TokenType.ASSIGN),  # <=
        (TokenType.LESS, TokenType.GREATER),  # <>
        (TokenType.BANG, TokenType.ASSIGN),  # !=
        (TokenType.NOT_SIGN, TokenType.ASSIGN),  # ¬=
        (TokenType.PIPE, TokenType.PIPE),  # ||
    }
)


def _is_split_relational_operator(prev_token: Token | None, token: Token) -> bool:
    """Return True if *token* immediately abuts *prev_token* forming
    ``>=``/``<=``/``<>``/``!=``/``¬=``/``||``.

    Column adjacency (same line, ``token``'s column immediately following the
    end of ``prev_token``'s value) is used rather than a bare value check so
    that a legitimately space-separated ``>`` ... ``=`` pair elsewhere in the
    text is not mistakenly fused -- e.g. host code that never actually splits
    a relational operator across whitespace still round-trips unchanged, and
    only the lexer's own artifact of tokenizing ``>=`` as two chars is
    repaired here.
    """
    if prev_token is None:
        return False
    if (prev_token.type, token.type) not in _EXEC_SQL_SPLIT_RELOP_PAIRS:
        return False
    prev_loc = prev_token.location
    cur_loc = token.location
    if prev_loc is None or cur_loc is None or prev_loc.line != cur_loc.line:
        return False
    prev_value = prev_token.value or ""
    return cur_loc.column == prev_loc.column + len(prev_value)


def _follows_qualifier_period(prev_token: Token | None, token: Token) -> bool:
    """Return True if *token* is glued to a preceding qualifier period.

    ``BANK.ACCOUNT`` lexes as ``BANK`` ``.`` ``ACCOUNT``; the period already
    attaches to ``BANK``, and without this the name after it got a space
    (``BANK. ACCOUNT``), so the table extractor read the schema ``BANK`` as a
    table of its own. Same column-adjacency rule as
    :func:`_is_split_relational_operator`: ``T. X`` written with a space keeps it.
    """
    if prev_token is None or prev_token.type != TokenType.PERIOD:
        return False
    prev_loc = prev_token.location
    cur_loc = token.location
    if prev_loc is None or cur_loc is None or prev_loc.line != cur_loc.line:
        return False
    return cur_loc.column == prev_loc.column + len(prev_token.value or "")


def _sql_literal_text(token: Token) -> str:
    """Render a STRING_LITERAL token back as SQL source text.

    The lexer hands a literal over with its delimiters stripped, so without
    this ``WHERE B = 'X:Y'`` reached the SQL model as ``WHERE B = X:Y`` and
    ``:Y`` was reported as a host variable (``'FROM T9'`` likewise became a
    table). A typed literal (``X'C1'``) keeps its original text; any other is
    re-delimited with the SQL string delimiter, embedded quotes doubled.
    """
    if token.raw_value:
        return token.raw_value
    return "'" + (token.value or "").replace("'", "''") + "'"


def _starts_sql_comment(token: Token, next_token: Token | None) -> bool:
    """True when *token* and *next_token* are the two abutting ``-`` of ``--``.

    The lexer has no token for an SQL line comment; it hands ``--`` over as
    two MINUS tokens in adjacent columns (a real subtraction of a negative,
    ``A - -1``, is written with a blank between them).
    """
    if next_token is None:
        return False
    if token.type != TokenType.MINUS or next_token.type != TokenType.MINUS:
        return False
    loc, next_loc = token.location, next_token.location
    if loc is None or next_loc is None or loc.line != next_loc.line:
        return False
    return next_loc.column == loc.column + 1


def _abutting_pair(
    token: Token, next_token: Token | None, first: TokenType, second: TokenType
) -> bool:
    """True when *token* / *next_token* are *first* / *second* in adjacent columns."""
    if next_token is None or token.type != first or next_token.type != second:
        return False
    loc, next_loc = token.location, next_token.location
    if loc is None or next_loc is None or loc.line != next_loc.line:
        return False
    return next_loc.column == loc.column + len(token.value or "")


def _is_end_exec(token: Token) -> bool:
    return token.type == TokenType.END_EXEC or bool(
        token.type == TokenType.IDENTIFIER
        and token.value
        and token.value.upper() == "END-EXEC"
    )


def collect_exec_sql_text(
    stream: ITokenStream, sql: bool = False, quoted_text: list[str] | None = None
) -> str:
    """Collect the raw SQL text from a token stream up to (and consuming) END-EXEC.

    The stream must be positioned **after** the ``EXEC SQL`` keyword pair has
    already been consumed by the caller.

    With *sql* true (EXEC SQL blocks), string literals keep their quotes
    (:func:`_sql_literal_text`) and ``--`` line comments are dropped up to the
    end of their line, so neither text inside a literal nor text inside a
    comment can be read as a host variable or a table. EXEC CICS / EXEC DLI
    text is collected as before (their option values are read unquoted).

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

        quoted_text: When given (EXEC CICS), the same text with each string
            literal re-quoted is appended to it -- the returned text keeps its
            historical unquoted shape, and this one tells ``PROGRAM('X')``
            from ``PROGRAM(X)``.

    Returns:
        The reconstructed SQL text as a single string, without leading/trailing
        whitespace.
    """
    sql_parts: list[str] = []
    quoted_parts: list[str] = []
    prev_was_colon = False
    prev_token: Token | None = None
    terminated = False
    first_token = stream.peek(0)
    while not stream.is_empty():
        token = stream.peek(0)
        if not token:
            break

        if _is_end_exec(token):
            stream.consume()
            terminated = True
            break

        if sql and _starts_sql_comment(token, peek_token(stream, 1)):
            # Drop the comment, but not the newline ending it nor an END-EXEC.
            while not stream.is_empty():
                pending = stream.peek(0)
                if (
                    pending is None
                    or pending.type == TokenType.NEWLINE
                    or _is_end_exec(pending)
                ):
                    break
                stream.consume()
            continue

        if sql and _abutting_pair(
            token, peek_token(stream, 1), TokenType.DIVIDE_OP, TokenType.MULTIPLY_OP
        ):
            # A bracketed ``/* ... */`` comment: dropped like ``--``, since
            # the token-joined text (``/ *``) is no longer recognisable as
            # one and its words read as host variables and tables. It may
            # span lines; it never swallows END-EXEC.
            stream.consume()
            stream.consume()
            while not stream.is_empty():
                pending = stream.peek(0)
                if pending is None or _is_end_exec(pending):
                    break
                if _abutting_pair(
                    pending,
                    peek_token(stream, 1),
                    TokenType.MULTIPLY_OP,
                    TokenType.DIVIDE_OP,
                ):
                    stream.consume()
                    stream.consume()
                    break
                stream.consume()
            continue

        if token.value or (sql and token.type == TokenType.STRING_LITERAL):
            text = (
                _sql_literal_text(token)
                if sql and token.type == TokenType.STRING_LITERAL
                else token.value
            )
            no_space_before = (
                prev_was_colon
                or token.type in _EXEC_SQL_NO_SPACE_BEFORE
                or _is_split_relational_operator(prev_token, token)
                or _follows_qualifier_period(prev_token, token)
            )
            quoted = (
                _sql_literal_text(token)
                if token.type == TokenType.STRING_LITERAL
                else text
            )
            if no_space_before:
                if sql_parts:
                    sql_parts[-1] = sql_parts[-1] + text
                    quoted_parts[-1] = quoted_parts[-1] + quoted
                else:
                    sql_parts.append(text)
                    quoted_parts.append(quoted)
            else:
                sql_parts.append(text)
                quoted_parts.append(quoted)
            prev_was_colon = token.type == TokenType.COLON
            prev_token = token
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

    if quoted_text is not None:
        quoted_text.append(" ".join(quoted_parts))
    return " ".join(sql_parts)


def _parse_size_error_stmts(stream: ITokenStream) -> list:
    """Parse imperative statements inside an ON SIZE ERROR / NOT ON SIZE ERROR clause.

    Dispatches every verb through the statement registry attached to *stream*
    (the same mechanism as :func:`collect_clause_stmts` for IO clause bodies),
    so a handler body may contain any statement — PERFORM, ADD, IF, CALL, ...
    — not just DISPLAY and MOVE. The clause ends at a period (consumed), at
    ``NOT`` (the start of the NOT ON SIZE ERROR clause, not consumed), at any
    scope terminator / control-flow boundary (not consumed), or when a nested
    parser consumed the sentence period itself. Tokens no registered parser
    accepts are consumed one at a time so the loop always progresses.
    """
    nested: list = []

    while not stream.is_empty():
        token = stream.peek()
        if not token or token.type == TokenType.PERIOD:
            if token:
                stream.consume()
            break

        if (
            token.type == TokenType.NEWLINE
            or token.type in SEPARATOR_TOKEN_TYPES
            or not token.value
        ):
            stream.consume()
            continue

        token_upper = token.value.upper()
        if (
            token.type == TokenType.NOT
            or token_upper in SCOPE_TERMINATORS
            or token_upper in CONTROL_FLOW_BOUNDARIES
        ):
            break

        parsed = try_parse_nested_statement(stream)
        if parsed is None:
            stream.consume()
            continue
        nested.append(parsed)
        prev = previous_meaningful_token(stream)
        if prev is not None and prev.type == TokenType.PERIOD:
            break

    return nested
