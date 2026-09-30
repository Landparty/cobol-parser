"""STRING and UNSTRING statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import StringStatement, UnstringStatement
from ._utils import (
    collect_clause_stmts,
    consume_optional_qualifiers,
    consume_period,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    peek_past_noise,
    previous_meaningful_token,
    skip_whitespace,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)
from ._utils import (
    token_value_upper as _val,
)

#: Values that end an ON OVERFLOW / NOT ON OVERFLOW clause body, on top of
#: `collect_clause_stmts`'s own period/NOT/INVALID/scope-terminator stops.
_OVERFLOW_CLAUSE_STOP = {"END-STRING", "END-UNSTRING"}


def _parse_overflow_stmts(token_stream: ITokenStream) -> list:
    """Parse imperative statements in an ON OVERFLOW / NOT ON OVERFLOW clause.

    Delegates to the shared `collect_clause_stmts` helper (also used for
    READ/WRITE/DELETE/REWRITE's INVALID KEY / ON SIZE ERROR bodies) instead
    of a bespoke loop that gave up on the *entire* clause body at the first
    token no registered parser accepted -- `collect_clause_stmts` skips one
    token and retries, matching how every other conditional-clause body in
    this codebase recovers from an unrecognized token.
    """
    return collect_clause_stmts(token_stream, _OVERFLOW_CLAUSE_STOP)


def _handler_ended_sentence(token_stream: ITokenStream) -> bool:
    """Whether a nested handler statement just consumed the sentence's
    period (``ON OVERFLOW GO TO P3.``): the STRING/UNSTRING ends there too.
    Without this the loop ran on into the next paragraph header and
    reported it as a missing-period statement."""
    prev = previous_meaningful_token(token_stream)
    return prev is not None and prev.type == TokenType.PERIOD


def _starts_overflow_phrase(token_stream: ITokenStream) -> bool:
    """Whether the stream is at ``[NOT] [ON] OVERFLOW`` -- this statement's
    own handler phrase.

    Any other ``ON`` / ``NOT`` belongs to an enclosing statement: a STRING in
    a READ's ``AT END`` is followed by the READ's ``NOT AT END``, one in a
    CALL's ``ON EXCEPTION`` by ``NOT ON EXCEPTION``. Consuming that word here
    left ``AT END`` / ``EXCEPTION`` to be read as operands, and the enclosing
    handler's statements were folded into the wrong branch.
    """
    token, offset = peek_past_noise(token_stream, 0)
    if token is not None and _val(token) == "NOT":
        token, offset = peek_past_noise(token_stream, offset + 1)
    if token is not None and _val(token) == "ON":
        token, offset = peek_past_noise(token_stream, offset + 1)
    return token is not None and _val(token) == "OVERFLOW"


def _consume_operand(token_stream: ITokenStream) -> str | None:
    """Consume one STRING/UNSTRING operand: a literal, or an identifier with
    its subscript / reference modification / OF-IN qualifier chain folded in
    (``A(1:2)``, ``D(3:5)``, ``WS-T(I)``). Returns None -- consuming nothing
    -- at a period or end of stream. Reading a single token here silently
    truncated every subscripted or reference-modified operand and left the
    ``(I)`` tokens to be misread as further operands."""
    token = token_stream.peek()
    if not token or token.type == TokenType.PERIOD:
        return None
    token_stream.consume()
    value = token.value or ""
    if token.type == TokenType.IDENTIFIER:
        value = consume_optional_qualifiers(token_stream, value)
    return value


#: Token types a DELIMITED [BY] delimiter may take.
_DELIMITER_TOKEN_TYPES = frozenset(
    {
        TokenType.IDENTIFIER,
        TokenType.STRING_LITERAL,
        TokenType.NUMERIC_LITERAL,
        TokenType.FIGURATIVE_CONSTANT,
    }
)
#: Clause words that can never be a delimiter operand.
_DELIMITER_STOP_WORDS = frozenset(
    {
        "INTO",
        "WITH",
        "POINTER",
        "TALLYING",
        "ON",
        "NOT",
        "OVERFLOW",
        "DELIMITED",
        "END-STRING",
        "END-UNSTRING",
    }
)


def _next_is_delimiter(token_stream: ITokenStream) -> bool:
    """True when the next token can be a ``DELIMITED [BY]`` operand.

    ``BY`` is optional, so after ``DELIMITED`` (and after an optional
    ``BY``) the delimiter is only consumed when it really is an operand --
    a malformed ``DELIMITED INTO X`` must leave ``INTO`` for its own clause.
    """
    token = token_stream.peek()
    return bool(
        token
        and token.type in _DELIMITER_TOKEN_TYPES
        and _val(token) not in _DELIMITER_STOP_WORDS
        and not is_statement_boundary(token)
    )


class StringStatementParser(IStatementParser):
    """Parser for STRING statements.

    Syntax:
        STRING source-1 [DELIMITED BY delim-1] ...
            INTO target
            [WITH POINTER pointer-var]
            [ON OVERFLOW statements]
            [NOT ON OVERFLOW statements]
        [END-STRING]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.STRING, "STRING")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> StringStatement:
        start = token_stream.consume()
        stmt = StringStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if val == "END-STRING":
                token_stream.consume()
                skip_whitespace(token_stream)
                consume_period(token_stream)
                break
            if is_statement_boundary(token):
                # No period / END-STRING terminator before the next statement:
                # stop rather than swallow it (audit 2026-07-06 H2).
                break
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                # A missing period on this STRING followed by what looks
                # like the next paragraph/section header (H9): stop instead
                # of folding it into the operand list. Disambiguated by
                # indentation (Area A vs Area B) so an operand that merely
                # wraps onto its own continuation line -- legitimate for any
                # operand in the list, not just the first -- isn't misread
                # as a boundary and dropped.
                warn_paragraph_boundary_swallowed(token_stream)
                break
            if val == "DELIMITED":
                token_stream.consume()
                skip_whitespace(token_stream)
                # ``BY`` is optional (``DELIMITED SIZE``, ``DELIMITED ","``).
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "BY":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                if _next_is_delimiter(token_stream):
                    delimiter = _consume_operand(token_stream)
                    if delimiter is not None:
                        stmt.add_delimiter(delimiter)
            elif val == "INTO":
                token_stream.consume()
                skip_whitespace(token_stream)
                target = _consume_operand(token_stream)
                if target is not None:
                    stmt.set_into_target(target)
            elif val in ("WITH", "POINTER"):
                # ``WITH`` is optional: a bare ``POINTER I`` is the same
                # clause (previously POINTER and I both became operands).
                if val == "WITH":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "POINTER":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    pointer = _consume_operand(token_stream)
                    if pointer is not None:
                        stmt.set_pointer_variable(pointer)
            elif val in ("ON", "NOT") and not _starts_overflow_phrase(token_stream):
                # An enclosing statement's phrase (``NOT AT END``, ``NOT ON
                # EXCEPTION``, ...): this statement ends here.
                break
            elif val == "ON":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_on_overflow_clause(overflow_stmts)
            elif val == "NOT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "ON":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_not_on_overflow_clause(overflow_stmts)
            elif val == "OVERFLOW":
                # Standalone OVERFLOW (without ON prefix)
                token_stream.consume()
                skip_whitespace(token_stream)
                overflow_stmts = _parse_overflow_stmts(token_stream)
                if overflow_stmts:
                    stmt.set_on_overflow_clause(overflow_stmts)
            elif token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.FIGURATIVE_CONSTANT,
            ):
                operand = _consume_operand(token_stream)
                if operand is not None:
                    stmt.add_operand(operand)
            else:
                token_stream.consume()

            skip_whitespace(token_stream)
            if _handler_ended_sentence(token_stream):
                break

        return stmt


class UnstringStatementParser(IStatementParser):
    """Parser for UNSTRING statements.

    Syntax:
        UNSTRING source DELIMITED BY [ALL] delim [OR [ALL] delim] ...
            INTO target-1 [DELIMITER IN d1] [COUNT IN c1] ...
            [WITH POINTER pointer-var]
            [TALLYING IN tally-var]
            [ON OVERFLOW statements]
            [NOT ON OVERFLOW statements]
        [END-UNSTRING]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.UNSTRING, "UNSTRING")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> UnstringStatement:
        start = token_stream.consume()
        stmt = UnstringStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        # Source identifier (subscript / reference modification folded in)
        source = _consume_operand(token_stream)
        if source is not None:
            stmt.set_source(source)
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if val == "END-UNSTRING":
                token_stream.consume()
                skip_whitespace(token_stream)
                consume_period(token_stream)
                break
            if is_statement_boundary(token):
                # No period / END-UNSTRING terminator before the next
                # statement: stop rather than swallow it (audit 2026-07-06 H2).
                break
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                # A missing period on this UNSTRING followed by what looks
                # like the next paragraph/section header (H9): stop instead
                # of silently discarding it in this clause dispatch loop.
                warn_paragraph_boundary_swallowed(token_stream)
                break
            if val == "DELIMITED":
                token_stream.consume()
                skip_whitespace(token_stream)
                # ``BY`` is optional (``DELIMITED "," OR ALL SPACE``).
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "BY":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                # Optional ALL delimiter [OR [ALL] delimiter ...]
                while True:
                    nxt = token_stream.peek()
                    is_all = bool(nxt and _val(nxt) == "ALL")
                    if is_all:
                        token_stream.consume()
                        skip_whitespace(token_stream)
                    if not _next_is_delimiter(token_stream):
                        break
                    delimiter = _consume_operand(token_stream)
                    if delimiter is None:
                        break
                    stmt.add_delimiter(delimiter, all_occurrences=is_all)
                    skip_whitespace(token_stream)
                    nxt = token_stream.peek()
                    if nxt and _val(nxt) == "OR":
                        token_stream.consume()
                        skip_whitespace(token_stream)
                    else:
                        break
            elif val == "INTO":
                token_stream.consume()
                skip_whitespace(token_stream)
                self._parse_into_targets(token_stream, stmt, start_column)
            elif val in ("WITH", "POINTER"):
                # ``WITH`` is optional: a bare ``POINTER I`` is the same clause.
                if val == "WITH":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "POINTER":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    pointer = _consume_operand(token_stream)
                    if pointer is not None:
                        stmt.set_pointer_variable(pointer)
            elif val == "TALLYING":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "IN":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    tally = _consume_operand(token_stream)
                    if tally is not None:
                        stmt.set_tallying_variable(tally)
            elif val in ("ON", "NOT") and not _starts_overflow_phrase(token_stream):
                # An enclosing statement's phrase (``NOT AT END``, ``NOT ON
                # EXCEPTION``, ...): this statement ends here.
                break
            elif val == "ON":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_on_overflow_clause(overflow_stmts)
            elif val == "NOT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "ON":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_not_on_overflow_clause(overflow_stmts)
            else:
                token_stream.consume()

            skip_whitespace(token_stream)
            if _handler_ended_sentence(token_stream):
                break

        return stmt

    @staticmethod
    def _parse_into_targets(
        token_stream: ITokenStream,
        stmt: UnstringStatement,
        reference_column: int | None = None,
    ) -> None:
        """Parse INTO target-1 [DELIMITER IN d1] [COUNT IN c1] ..."""
        current_target: str | None = None
        current_delim_var: str | None = None
        current_count_var: str | None = None

        while not token_stream.is_empty():
            tgt = token_stream.peek()
            if not tgt:
                break
            tval = _val(tgt)
            if tgt.type == TokenType.PERIOD or tval in (
                "WITH",
                "TALLYING",
                "ON",
                "NOT",
                "END-UNSTRING",
            ):
                break
            if tval == "DELIMITER":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IN":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                current_delim_var = _consume_operand(token_stream)
            elif tval == "COUNT":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IN":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                current_count_var = _consume_operand(token_stream)
            elif tgt.type == TokenType.IDENTIFIER and is_statement_boundary(tgt):
                # A following statement's verb that lexes as a plain
                # IDENTIFIER (e.g. PURGE/RAISE/RESUME have no dedicated
                # TokenType) must not be folded into the INTO target list.
                break
            elif (
                tgt.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, reference_column)
            ):
                # A missing period on this UNSTRING followed by what looks
                # like the next paragraph/section header (H9): stop instead
                # of folding it into the INTO target list -- for any target
                # in the list, not just the first, so a target that merely
                # wraps onto its own continuation line isn't dropped. The
                # outer clause dispatch loop in parse() re-checks this same
                # token and owns the warning, so this just needs to break,
                # not warn.
                break
            elif tgt.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                # Flush previous target if any
                if current_target is not None:
                    stmt.add_into_target(
                        current_target, current_delim_var, current_count_var
                    )
                    current_delim_var = None
                    current_count_var = None
                current_target = _consume_operand(token_stream)
            elif tgt.type == TokenType.COMMA:
                # A comma between INTO targets (normal COBOL style) is a
                # separator, not a terminator -- skip it and keep collecting
                # targets rather than ending the list here.
                token_stream.consume()
            else:
                break
            skip_whitespace(token_stream)

        # Flush last target
        if current_target is not None:
            stmt.add_into_target(current_target, current_delim_var, current_count_var)
