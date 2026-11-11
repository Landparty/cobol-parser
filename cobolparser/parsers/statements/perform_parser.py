"""Perform statement parser implementing IStatementParser interface."""

import logging
from typing import Any, cast

from cobolparser.parsers.statements._conditions import (
    ConditionSymbols,
    build_condition_expression,
    condition_symbols,
    condition_token_text,
)
from cobolparser.parsers.statements._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    consume_optional_qualifiers,
    consume_procedure_qualifier,
    consume_value_operand,
    ends_at_paragraph_header,
    get_parse_context,
    is_bare_separator,
    is_statement_boundary,
    keyword_upper,
    matches_keyword,
    paren_depth_after,
    peek_past_noise,
    report_parse_error,
    skip_statement_separators,
    skip_whitespace,
    starts_negative_handler_phrase,
    try_parse_nested_statement,
)
from cobolparser.parsers.statements._utils import (
    is_procedure_name_token as _is_procedure_name_token,
)

from ...core.ast_factory import get_factory
from ...core.exceptions import ParseError, TokenMismatch, UnexpectedEndOfInput
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import Token, TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CobolExpression, PerformStatement

logger = logging.getLogger(__name__)

#: Layout tokens that never belong in an UNTIL condition (#347). The IF and
#: EVALUATE parsers drop them too; a trailing NEWLINE rendered as "\n" made
#: ``tokens[-1]`` something other than the condition's real last token, so a
#: bare condition-name, ``NOT cond``, a class test or an enclosing ``( ... )``
#: was no longer recognised when the condition ended at a line break.
_UNTIL_LAYOUT_TOKEN_TYPES = (
    TokenType.WHITESPACE,
    TokenType.NEWLINE,
    TokenType.CONTINUATION,
    TokenType.COMMENT,
)


def _make_until_condition_expression(
    condition_tokens: list[str], symbols: ConditionSymbols | None = None
) -> CobolExpression:
    """Build the UNTIL condition node from its collected token strings.

    Backward-compatible shape (M12): the returned node is still a
    ``CobolExpression("CONDITION")`` whose ``operands`` hold the single raw
    joined condition string -- exactly what every pre-M12 consumer reads.
    Additionally, the same tokens are decomposed with the IF parser's
    shared condition machinery and attached as ``condition_tree`` (a
    ConditionalExpression / LogicalExpression tree), so callers can walk
    the condition structurally. Tree building is best-effort and never
    fails the PERFORM parse.
    """
    # Second safeguard for #347: a layout token's text ("\n", spaces) that
    # reached here would defeat the shared condition machinery.
    condition_tokens = [t for t in condition_tokens if t and t.strip()]
    condition_str = " ".join(condition_tokens).strip()
    condition_expr = CobolExpression("CONDITION", SourceLocation(0, 0))
    condition_expr.operands = [condition_str]
    try:
        tree = build_condition_expression(
            list(condition_tokens), SourceLocation(0, 0), symbols=symbols
        )
    except Exception:
        # Strictly fail-soft: a condition the shared machinery cannot
        # handle keeps the raw string with no structural tree.
        tree = None
    if tree is not None:
        condition_expr.set_condition_tree(tree)
    return condition_expr


def _warn_stray_trailing_token(stream: ITokenStream, token: Token) -> None:
    """Record a warning for a token after a PERFORM target that is neither
    a TIMES clause nor the start of a new statement (H3).

    Previously this token was speculatively consumed as a candidate TIMES
    value and, once it turned out not to be one, discarded with no warning
    at all -- ``errors=0, warnings=0`` and ``times_count`` silently stayed
    ``None``.
    """
    value = token.value or "" if token is not None else ""
    if not value:
        return
    line = getattr(getattr(token, "location", None), "line", None)
    where = f" at line {line}" if line else ""
    context = get_parse_context(stream)
    host = getattr(context, "host", None) if context is not None else None
    add_warning = getattr(host, "add_warning", None)
    message = (
        f"PERFORM statement: unexpected token '{value}'{where} after the "
        "target paragraph skipped: not a valid TIMES clause; token discarded"
    )
    if callable(add_warning):
        add_warning(message)
    else:
        logger.warning(message)


def _warn_incomplete_varying_clause(
    stream: ITokenStream, stmt: PerformStatement
) -> None:
    """Record a warning when a PERFORM VARYING clause's FROM/BY/UNTIL
    sub-clause didn't fully parse, so ``varying_clause``/``until_condition``
    stay unset even though ``perform_type`` is (correctly) tagged "VARYING"
    via :meth:`PerformStatement.mark_varying`.

    Without this, a malformed VARYING clause would drop its data with zero
    trace -- ``varying_clause: null`` looks identical to "this PERFORM never
    had a VARYING clause" as opposed to "it had one, but it was malformed".
    """
    line = getattr(getattr(stmt, "location", None), "line", None)
    where = f" at line {line}" if line else ""
    context = get_parse_context(stream)
    host = getattr(context, "host", None) if context is not None else None
    add_warning = getattr(host, "add_warning", None)
    message = (
        f"PERFORM VARYING clause{where}: FROM/BY/UNTIL not fully recognized -- "
        "varying_clause left unset (perform_type is still recorded as "
        "'VARYING', not the default 'SIMPLE')"
    )
    if callable(add_warning):
        add_warning(message)
    else:
        logger.warning(message)


def _peek_past_optional_subscript(stream: ITokenStream, offset: int) -> Any:
    """Peek at the first meaningful token at/after *offset*, skipping the
    rest of a data reference: parenthesised subscript groups and ``OF`` /
    ``IN`` qualifiers.

    ``PERFORM P TABLE5-NUM (INDEX5) TIMES`` (NIST NC121M) and ``PERFORM P
    WS-CNT OF WS-CTL TIMES``: the TIMES lookahead must see past the count's
    subscript and qualifier chain, or the count is taken for a stray
    identifier (or, inline, for a paragraph name) and TIMES falls out as
    unparsed.
    """
    token, idx = peek_past_noise(stream, offset)
    while token is not None:
        if token.type == TokenType.LEFT_PAREN:
            depth = 0
            while token is not None:
                if token.type == TokenType.LEFT_PAREN:
                    depth += 1
                elif token.type == TokenType.RIGHT_PAREN:
                    depth -= 1
                    if depth == 0:
                        break
                idx += 1
                token = stream.peek(idx)
            if token is None:
                return None
            token, idx = peek_past_noise(stream, idx + 1)
        elif token.type in (TokenType.OF, TokenType.IN) or keyword_upper(token) in (
            "OF",
            "IN",
        ):
            _name, idx = peek_past_noise(stream, idx + 1)
            if _name is None:
                return None
            token, idx = peek_past_noise(stream, idx + 1)
        else:
            return token
    return None


def _is_times_word(token: Token | None) -> bool:
    """True when *token* is the TIMES keyword (or TIMES/TIME lexed as an
    IDENTIFIER) -- the lookahead that makes a preceding operand a count."""
    if not token:
        return False
    return token.type == TokenType.TIMES or bool(
        token.type == TokenType.IDENTIFIER
        and token.value
        and token.value.upper() in ("TIMES", "TIME")
    )


def _is_count_literal_token(token: Token) -> bool:
    """A numeric token that may be an inline ``PERFORM n TIMES`` count:
    NUMERIC_LITERAL, LEVEL_NUMBER, or an all-digit IDENTIFIER."""
    return (
        token.type == TokenType.NUMERIC_LITERAL
        or token.type == TokenType.LEVEL_NUMBER
        or bool(
            token.type == TokenType.IDENTIFIER and token.value and token.value.isdigit()
        )
    )


def _verb_column(stmt: PerformStatement) -> int | None:
    """The PERFORM verb's source column (where its statement node sits)."""
    return getattr(getattr(stmt, "location", None), "column", None)


class PerformStatementParser(IStatementParser):
    """Parser for PERFORM statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.PERFORM, "PERFORM")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> PerformStatement:
        """Parse a PERFORM statement.

        Supports:
        - PERFORM paragraph-name
        - PERFORM paragraph-name THRU paragraph-name
        - PERFORM UNTIL condition
        - PERFORM TIMES
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        - Inline PERFORM blocks with nested statements
        """
        # Consume PERFORM keyword
        start_token = token_stream.consume()
        factory = get_factory()

        # Create statement with source location
        location = start_token.location if start_token else SourceLocation(0, 0)
        stmt = cast(PerformStatement, factory.create(PerformStatement, location))
        context = get_parse_context(token_stream)

        # Skip whitespace/comments if possible
        skip_whitespace(token_stream)

        # Try to get the next meaningful token (peek without consuming)
        try:
            token = token_stream.peek()
        except UnexpectedEndOfInput:
            # End of stream
            return stmt

        if not token or token.type == TokenType.PERIOD:
            report_parse_error(
                context,
                "PERFORM statement requires a target paragraph or inline clause",
                location,
            )
            if token:
                token_stream.consume()
            return stmt

        if self._parse_inline_form(token_stream, stmt, token):
            return stmt
        token = token_stream.peek()

        # Simple PERFORM procedure-name (an identifier, or an all-digit
        # numeric paragraph name -- e.g. PERFORM 1000 THRU 1999)
        if token and _is_procedure_name_token(token):
            if self._parse_procedure_form(token_stream, stmt, token, context, location):
                return stmt

        self._consume_perform_end(token_stream)
        return stmt

    def _parse_inline_form(
        self, token_stream: ITokenStream, stmt: PerformStatement, first: Token
    ) -> bool:
        """Parse the inline forms (VARYING, [WITH TEST] UNTIL, ``n TIMES``)
        that start at *first*. True when one was parsed and *stmt* is
        complete; False leaves the stream at a possible procedure name."""
        # Check for VARYING clause (inline PERFORM VARYING)
        if first.type == TokenType.VARYING:
            self._parse_varying_clause(token_stream, stmt)
            return True

        # Check for TEST clause (WITH TEST BEFORE/AFTER)
        token: Token | None = first
        if first.type in (TokenType.WITH, TokenType.TEST):
            token = self._parse_test_phrase(token_stream, stmt, first)

        # ``PERFORM WITH TEST AFTER VARYING ...`` -- the TEST phrase may
        # precede VARYING in the inline form; previously only UNTIL was
        # looked for after it and the VARYING clause fell out as unparsed.
        if token and token.type == TokenType.VARYING:
            self._parse_varying_clause(token_stream, stmt)
            return True

        # Check for UNTIL clause (inline PERFORM UNTIL)
        if token and token.type == TokenType.UNTIL:
            self._parse_until_clause(token_stream, stmt)
            return True

        # Check for TIMES clause (inline PERFORM n TIMES)
        if token and _is_count_literal_token(token):
            if self._try_parse_inline_literal_times(token_stream, stmt, token):
                return True
            skip_whitespace(token_stream)
        return False

    def _parse_test_phrase(
        self, token_stream: ITokenStream, stmt: PerformStatement, token: Token
    ) -> Token | None:
        """Consume ``[WITH] TEST BEFORE|AFTER`` starting at *token* (WITH or
        TEST) into ``stmt.test_timing``; return the next meaningful token.

        WITH, TEST, and BEFORE/AFTER may each land on their own continuation
        line, so a skip_whitespace before every peek is required or the
        clause is silently left unconsumed (H3-style newline-intolerance
        bug).
        """
        current: Token | None = token
        try:
            if token.type == TokenType.WITH:
                token_stream.consume()  # Skip WITH (optional prefix)
                skip_whitespace(token_stream)
                current = token_stream.peek()
            if current and current.type == TokenType.TEST:
                token_stream.consume()  # Skip TEST
                skip_whitespace(token_stream)
                current = token_stream.peek()
                if current and current.type in (TokenType.BEFORE, TokenType.AFTER):
                    val = current.type.name  # "BEFORE" or "AFTER"
                    stmt.set_test_timing(val)
                    token_stream.consume()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass
        skip_whitespace(token_stream)
        return token_stream.peek()

    def _try_parse_inline_literal_times(
        self, token_stream: ITokenStream, stmt: PerformStatement, token: Token
    ) -> bool:
        """``PERFORM n TIMES <statements> END-PERFORM`` with a numeric count.

        The numeric token is only a TIMES count when TIMES/TIME actually
        follows -- checked via lookahead *before* consuming. COBOL also
        allows all-digit procedure names (PERFORM 1000 THRU 1999), so a
        numeric token with no TIMES after it must fall through to the
        procedure-name-target branch instead of being consumed as a failed
        TIMES count and lost. True when the inline form was parsed.
        """
        if not _is_times_word(peek_past_noise(token_stream, 1)[0]):
            return False
        try:
            times_count = int(token.value)
            token_stream.consume()  # the count
            skip_whitespace(token_stream)
            token_stream.consume()  # TIMES keyword
            stmt.set_times_clause(times_count)
            # Parse inline statements until END-PERFORM
            self._parse_inline_statements(token_stream, stmt)
            return True
        except (ValueError, TokenMismatch, UnexpectedEndOfInput):
            return False

    def _parse_procedure_form(
        self,
        token_stream: ITokenStream,
        stmt: PerformStatement,
        token: Token,
        context: Any,
        location: SourceLocation,
    ) -> bool:
        """Parse the forms that start with a procedure name (or an
        identifier TIMES count) at *token*. True when the inline
        ``identifier TIMES`` form was parsed and *stmt* is complete; False
        when the caller still consumes the terminating period/END-PERFORM.
        """
        # ``PERFORM counter-name TIMES`` -- an identifier count is as
        # standard as a literal one; previously the identifier was taken
        # as a paragraph name and TIMES fell out as an unparsed token.
        lookahead = _peek_past_optional_subscript(token_stream, 1)
        if token.type == TokenType.IDENTIFIER and _is_times_word(lookahead):
            token_stream.consume()  # the count identifier
            # ``PERFORM WS-CNT OF WS-CTL TIMES`` / ``PERFORM TBL-N (I)
            # TIMES``: the count is the whole data reference.
            count_name = consume_optional_qualifiers(token_stream, token.value or "")
            skip_whitespace(token_stream)
            token_stream.consume()  # TIMES keyword
            stmt.set_times_clause(count_name)
            self._parse_inline_statements(token_stream, stmt)
            return True

        stmt.set_target_paragraph(token.value)
        try:
            token_stream.consume()
            token_stream.peek()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

        skip_whitespace(token_stream)
        current = token_stream.peek()

        # ``PERFORM PAR-1A OF QUAL-SECTION-1`` -- a section-qualified
        # paragraph name (NIST NC208A). The qualifier is recorded as
        # metadata; the target keeps the bare paragraph name so
        # flow-graph lookups by name are unchanged.
        qualifier = consume_procedure_qualifier(token_stream)
        if qualifier:
            stmt.set_metadata("target_qualifier", qualifier)
            current = token_stream.peek()

        # Check for THRU clause (THROUGH is a standard COBOL synonym)
        if (
            current
            and current.type == TokenType.IDENTIFIER
            and current.value
            and current.value.upper() in ("THRU", "THROUGH")
        ):
            current = self._parse_thru_phrase(token_stream, stmt, context, location)

        self._parse_trailing_times(token_stream, stmt, current)

        skip_whitespace(token_stream)
        current = token_stream.peek()

        # Check for WITH TEST clause after paragraph name (WITH TEST
        # BEFORE/AFTER) -- see the newline-tolerance note in
        # _parse_test_phrase.
        if current and current.type in (TokenType.WITH, TokenType.TEST):
            current = self._parse_test_phrase(token_stream, stmt, current)

        self._parse_out_of_line_loop(token_stream, stmt, current)
        return False

    def _parse_thru_phrase(
        self,
        token_stream: ITokenStream,
        stmt: PerformStatement,
        context: Any,
        location: SourceLocation,
    ) -> Token | None:
        """Consume ``THRU|THROUGH procedure-name [OF section]`` (the stream
        is at THRU); return the next meaningful token."""
        try:
            token_stream.consume()  # Skip THRU/THROUGH
            # The end name may sit on a continuation line
            # (PERFORM name THRU\n    other-name), so newline and
            # whitespace tokens must be skipped before peeking it.
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and _is_procedure_name_token(token):
                stmt.set_thru_paragraph(token.value)
                token_stream.consume()
                # ``THRU P2 OF S1`` -- same qualifier form as the
                # target; previously left as an unparsed OF.
                thru_qualifier = consume_procedure_qualifier(token_stream)
                if thru_qualifier:
                    stmt.set_metadata("thru_qualifier", thru_qualifier)
            else:
                report_parse_error(
                    context,
                    "PERFORM THRU requires an ending paragraph name",
                    location,
                )
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

        skip_whitespace(token_stream)
        return token_stream.peek()

    def _parse_trailing_times(
        self,
        token_stream: ITokenStream,
        stmt: PerformStatement,
        token: Token | None,
    ) -> None:
        """Parse a TIMES clause after the target paragraph(s).

        The count can be numeric or variable. The candidate token is only a
        TIMES-clause value if it is actually followed by TIMES/TIME --
        checked via lookahead *before* consuming, so a token that turns out
        not to start a TIMES clause (e.g. a stray trailing identifier, or
        the next statement's leading token) is left in the stream instead of
        being silently discarded with no warning (H3).
        """
        if token and token.type == TokenType.IDENTIFIER:
            self._parse_trailing_identifier_times(token_stream, stmt, token)
        elif token and (
            token.type == TokenType.NUMERIC_LITERAL
            or token.type == TokenType.LEVEL_NUMBER
        ):
            self._parse_trailing_literal_times(token_stream, stmt, token)

    def _parse_trailing_identifier_times(
        self, token_stream: ITokenStream, stmt: PerformStatement, token: Token
    ) -> None:
        """``PERFORM P count TIMES`` with an identifier (or numeric
        IDENTIFIER) count, or a stray trailing identifier."""
        lookahead = _peek_past_optional_subscript(token_stream, 1)
        if _is_times_word(lookahead):
            times_value = token.value
            token_stream.consume()
            skip_whitespace(token_stream)
            # ``PERFORM P TABLE5-NUM (INDEX5) TIMES`` (NIST NC121M):
            # fold a subscript / qualifier chain into the count.
            times_value = consume_optional_qualifiers(token_stream, times_value)

            # Can be numeric (int) or variable (string)
            para_times_count: Any
            try:
                para_times_count = int(times_value)
            except ValueError:
                para_times_count = times_value  # Keep as variable name string

            token_stream.consume()  # Skip TIMES keyword
            stmt.set_times_clause(para_times_count)
        elif not is_statement_boundary(token):
            # Not a TIMES clause and not the start of a following
            # statement -- a bare trailing identifier here (e.g. a
            # typo) would otherwise be left for the caller to
            # misread as a new paragraph header (IDENTIFIER
            # immediately followed by PERIOD is indistinguishable
            # from a paragraph declaration at that point).
            _warn_stray_trailing_token(token_stream, token)
            token_stream.consume()

    def _parse_trailing_literal_times(
        self, token_stream: ITokenStream, stmt: PerformStatement, token: Token
    ) -> None:
        """``PERFORM P n TIMES`` with a numeric-literal count, or a stray
        trailing number."""
        if not _is_times_word(peek_past_noise(token_stream, 1)[0]):
            _warn_stray_trailing_token(token_stream, token)
            token_stream.consume()
            return
        try:
            num_times_count = int(token.value)
        except (ValueError, TypeError):
            return
        token_stream.consume()
        skip_whitespace(token_stream)
        token_stream.consume()  # Skip TIMES keyword
        stmt.set_times_clause(num_times_count)

    def _parse_out_of_line_loop(
        self,
        token_stream: ITokenStream,
        stmt: PerformStatement,
        token: Token | None,
    ) -> None:
        """Parse a VARYING or UNTIL phrase after the target paragraph(s)."""
        # Check for VARYING clause after paragraph name -- the
        # out-of-line form: PERFORM procedure-name-1 [THRU procedure-
        # name-2] [WITH TEST ...] VARYING id FROM x BY y UNTIL cond
        # [AFTER ...]. Previously unhandled here entirely: the VARYING
        # token matched neither the TIMES/WITH TEST/UNTIL branches nor
        # the trailing "period or END-PERFORM" check, so the whole
        # clause was left unconsumed for the top-level "unparsed
        # tokens" recovery to discard, and perform_type stayed the
        # default "SIMPLE" -- indistinguishable from a genuine plain
        # PERFORM to anything keyed off perform_type.
        if token and token.type == TokenType.VARYING:
            self._parse_out_of_line_varying_clause(token_stream, stmt)
        # Check for UNTIL clause after paragraph name
        elif token and token.type == TokenType.UNTIL:
            try:
                self._parse_until_condition_only(token_stream, stmt)
            except ParseError as exc:
                # A malformed UNTIL condition here must not abort the
                # whole PERFORM; the error is already recorded via
                # report_or_raise when applicable. Log at debug for
                # diagnosability (H4 -- these catches previously had no
                # trace at all).
                logger.debug(
                    "PERFORM UNTIL condition parse suppressed %r",
                    exc,
                    exc_info=True,
                )

    @staticmethod
    def _consume_perform_end(token_stream: ITokenStream) -> None:
        """Consume a terminating period or END-PERFORM, if present."""
        try:
            token = token_stream.peek()
            if token and token.type == TokenType.PERIOD:
                token_stream.consume()
            elif (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "END-PERFORM"
            ):
                token_stream.consume()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

    def _parse_varying_clause(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse VARYING clause for an inline PERFORM (no target paragraph;
        an imperative-statement body + END-PERFORM follows)."""
        try:
            self._parse_varying_header(stream, stmt)
            if stmt.varying_clause is None:
                _warn_incomplete_varying_clause(stream, stmt)

            # Parse the inline body (up to END-PERFORM or period)
            self._parse_inline_statements(stream, stmt)
        except ParseError as exc:
            # H4: VARYING/UNTIL body parse failures previously vanished with
            # no trace anywhere (no ParseResult.errors, no .warnings, no log
            # line). Log at debug so the failure is at least diagnosable.
            logger.debug(
                "PERFORM VARYING clause parse suppressed %r", exc, exc_info=True
            )

    def _parse_out_of_line_varying_clause(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse VARYING clause for an out-of-line PERFORM -- the target
        (and optional THRU) paragraph is already set on *stmt*. Unlike the
        inline form there is no imperative-statement body or END-PERFORM:
        the loop body is the target paragraph(s) themselves."""
        try:
            self._parse_varying_header(stream, stmt)
            if stmt.varying_clause is None:
                _warn_incomplete_varying_clause(stream, stmt)
        except ParseError as exc:
            logger.debug(
                "PERFORM VARYING clause (out-of-line) parse suppressed %r",
                exc,
                exc_info=True,
            )

    def _parse_varying_header(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse ``VARYING id FROM x BY y [WITH TEST ...] UNTIL cond
        [AFTER ...]`` and record it on *stmt*. Shared by the inline PERFORM
        VARYING form (dispatched directly on the VARYING keyword, no target
        paragraph) and the out-of-line form (target paragraph already set,
        VARYING appears after it).

        Marks ``stmt`` as a VARYING-form PERFORM (via ``mark_varying()``)
        immediately upon consuming the keyword, *before* attempting to parse
        FROM/BY/UNTIL -- so perform_type reflects the keyword's presence
        even if the rest of the clause is malformed or incomplete, rather
        than only becoming "VARYING" as a side effect of a fully successful
        sub-parse.
        """
        stream.consume()  # Skip VARYING
        stmt.mark_varying()
        skip_whitespace(stream)

        # Get variable name
        token = stream.peek()
        if not token or token.type != TokenType.IDENTIFIER:
            return

        variable_name = token.value
        stream.consume()
        skip_whitespace(stream)
        # ``VARYING PFM-F4-24-A (S1)`` (NIST NC201A): a subscripted loop
        # variable is legal; fold the subscript in instead of stranding it.
        variable_name = consume_optional_qualifiers(stream, variable_name)

        # Expect FROM
        token = stream.peek()
        if not token or not token.value or token.value.upper() != "FROM":
            return
        stream.consume()
        skip_whitespace(stream)

        # Get FROM value (may be sign-prefixed, e.g. FROM -1)
        from_value = consume_value_operand(stream)
        if from_value is None:
            return
        skip_whitespace(stream)

        # BY is optional in COBOL 2002 and GnuCOBOL; omitted, it is BY 1.
        by_value = self._consume_by_phrase(stream, stmt)
        if by_value is None:
            return

        # Check for WITH TEST clause (before UNTIL) -- see the
        # newline-tolerance note in _parse_test_phrase.
        token = stream.peek()
        if token and token.type == TokenType.WITH:
            self._parse_test_phrase(stream, stmt, token)

        # Parse UNTIL condition
        token = stream.peek()
        if token and token.type == TokenType.UNTIL:
            until_condition = self._collect_until_expression(stream, _verb_column(stmt))
            if until_condition:
                stmt.set_varying_clause(
                    variable_name, from_value, by_value, until_condition
                )

        # Parse AFTER dimensions (PERFORM VARYING ... AFTER ... — 2-D/3-D
        # table loops). Each AFTER phrase repeats var FROM x BY y [UNTIL c].
        self._parse_after_clauses(stream, stmt)

    def _consume_by_phrase(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> str | None:
        """The ``BY`` value of a VARYING/AFTER phrase, or ``None`` when BY is
        present but its operand is not. COBOL 2002 and GnuCOBOL make the
        phrase optional, with ``BY 1`` implied: that case returns ``"1"``
        and records ``by_implied`` on *stmt*'s metadata."""
        token = stream.peek()
        if not token or not token.value or token.value.upper() != "BY":
            stmt.set_metadata("by_implied", True)
            return "1"
        stream.consume()
        skip_whitespace(stream)
        # May be sign-prefixed: BY -1 is every countdown loop.
        by_value = consume_value_operand(stream)
        if by_value is not None:
            skip_whitespace(stream)
        return by_value

    def _parse_after_clauses(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse zero or more AFTER dimensions of a PERFORM VARYING clause."""
        while True:
            skip_whitespace(stream)
            token = stream.peek()
            if not token or not (
                token.type == TokenType.AFTER
                or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "AFTER"
                )
            ):
                return
            stream.consume()  # Skip AFTER
            skip_whitespace(stream)

            # Variable name
            token = stream.peek()
            if not token or token.type != TokenType.IDENTIFIER:
                return
            variable_name = token.value
            stream.consume()
            skip_whitespace(stream)

            # Expect FROM
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "FROM":
                stmt.add_after_clause(variable_name, "", "")
                return
            stream.consume()
            skip_whitespace(stream)
            from_value = consume_value_operand(stream)
            if from_value is None:
                stmt.add_after_clause(variable_name, "", "")
                return
            skip_whitespace(stream)

            by_value = self._consume_by_phrase(stream, stmt)
            if by_value is None:
                stmt.add_after_clause(variable_name, from_value, "")
                return

            # Optional UNTIL condition for this dimension
            until_condition = None
            token = stream.peek()
            if token and token.type == TokenType.UNTIL:
                until_condition = self._collect_until_expression(
                    stream, _verb_column(stmt)
                )
            stmt.add_after_clause(variable_name, from_value, by_value, until_condition)

    def _collect_until_condition_tokens(
        self,
        stream: ITokenStream,
        for_varying: bool = False,
        verb_column: int | None = None,
    ) -> list:
        """Consume tokens forming a UNTIL condition and return them as strings.

        When *for_varying* is True, also stops on IDENTIFIER tokens whose value
        matches known statement keywords (extra guard needed for VARYING context).
        *verb_column* is the PERFORM's own column, for the missing-period
        check (:func:`ends_at_paragraph_header`).
        """
        tokens: list = []
        paren_depth = 0
        while True:
            token = stream.peek()
            if not token:
                break
            if token.type in _UNTIL_LAYOUT_TOKEN_TYPES:
                stream.consume()
                continue
            # A separator comma/semicolon is a space (#386).
            if is_bare_separator(token, paren_depth):
                stream.consume()
                continue
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.END_PERFORM:
                break
            # Any other scope terminator (END-IF, END-EVALUATE, ...) closes
            # the statement this PERFORM is nested in, never the condition.
            # keyword_upper: UNTIL X = "END-IF" compares against a literal.
            word = keyword_upper(token)
            if word in SCOPE_TERMINATORS:
                break
            # AFTER starts the next dimension of a PERFORM VARYING ... AFTER
            # loop — stop without consuming so the whole AFTER phrase isn't
            # absorbed into the condition string. Only applies in the
            # VARYING context (for_varying=True): a plain PERFORM UNTIL has
            # no AFTER clause of its own, so gating this on for_varying
            # avoids truncating a condition that happens to reference an
            # AFTER-named identifier or reserved word elsewhere.
            if for_varying and word == "AFTER":
                break
            if token.type in STATEMENT_TOKEN_TYPES:
                break
            if ends_at_paragraph_header(stream, verb_column):
                break
            if starts_negative_handler_phrase(stream):
                # An enclosing READ's ``NOT AT END`` (CALL's ``NOT ON
                # EXCEPTION``, ...) ends this PERFORM, not the condition.
                break
            if for_varying and (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in STATEMENT_KEYWORDS
            ):
                break
            paren_depth = paren_depth_after(token, paren_depth)
            tokens.append(condition_token_text(token))
            stream.consume()
        return tokens

    def _parse_until_clause(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse UNTIL clause for an inline PERFORM."""
        try:
            stream.consume()  # Skip UNTIL
            skip_whitespace(stream)
            condition_tokens = self._collect_until_condition_tokens(
                stream, verb_column=_verb_column(stmt)
            )
            if condition_tokens:
                stmt.set_until_clause(
                    _make_until_condition_expression(
                        condition_tokens, condition_symbols(get_parse_context(stream))
                    )
                )
            self._parse_inline_statements(stream, stmt)
        except ParseError as exc:
            # H4: previously silent -- see _parse_varying_clause above.
            logger.debug(
                "PERFORM UNTIL inline clause parse suppressed %r", exc, exc_info=True
            )

    def _collect_until_expression(
        self, stream: ITokenStream, verb_column: int | None = None
    ) -> CobolExpression | None:
        """Consume an UNTIL keyword + condition and return it as an expression.

        Unlike :meth:`_parse_until_clause`, this does NOT parse the inline
        body — the caller decides what follows (an AFTER dimension may
        intervene in PERFORM VARYING ... AFTER ... loops).
        """
        try:
            stream.consume()  # Skip UNTIL
            skip_whitespace(stream)
            condition_tokens = self._collect_until_condition_tokens(
                stream, for_varying=True, verb_column=verb_column
            )
            if condition_tokens:
                return _make_until_condition_expression(
                    condition_tokens, condition_symbols(get_parse_context(stream))
                )
        except ParseError as exc:
            # H4: previously silent -- see _parse_varying_clause above.
            logger.debug(
                "PERFORM VARYING ... AFTER UNTIL expression parse suppressed %r",
                exc,
                exc_info=True,
            )
        return None

    def _parse_until_condition_only(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse just the UNTIL condition after paragraph name."""
        try:
            _ut = stream.peek()
            if _ut and _ut.value and _ut.value.upper() == "UNTIL":
                stream.consume()

            skip_whitespace(stream)

            # Parse condition (simplified)
            condition_tokens = []
            paren_depth = 0
            while True:
                token = stream.peek()
                if not token:
                    break
                if token.type in _UNTIL_LAYOUT_TOKEN_TYPES:
                    stream.consume()
                    continue
                # A separator comma/semicolon is a space (#386).
                if is_bare_separator(token, paren_depth):
                    stream.consume()
                    continue
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break
                # An out-of-line PERFORM owns no scope terminator: END-IF /
                # END-EVALUATE / END-PERFORM / ... here closes the statement
                # this PERFORM is nested in. Swallowing it into the condition
                # text re-nested every statement up to the next period into
                # that IF arm / WHEN / inline PERFORM body -- a top-level
                # STOP RUN after ``IF c PERFORM p UNTIL d END-IF`` read as
                # conditional, so the flow graph invented a fall-through out
                # of a paragraph that always stops. keyword_upper: a literal
                # spelled like one (UNTIL X = "END-IF") is condition content.
                if keyword_upper(token) in SCOPE_TERMINATORS:
                    break
                if (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-PERFORM"
                ):
                    stream.consume()
                    break
                # No trailing period / END-PERFORM before the next statement:
                # stop rather than swallow it. Unlike _collect_until_condition_
                # tokens (used by the inline PERFORM VARYING/UNTIL forms), this
                # loop previously had no boundary check at all, so `PERFORM
                # para UNTIL cond` with no trailing period consumed every
                # remaining token in the program -- including unrelated
                # statements -- into the condition string.
                if token.type in STATEMENT_TOKEN_TYPES:
                    break
                if (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() in STATEMENT_KEYWORDS
                ):
                    break
                if ends_at_paragraph_header(stream, _verb_column(stmt)):
                    break
                if starts_negative_handler_phrase(stream):
                    # ``READ ... AT END PERFORM p UNTIL c NOT AT END ...``:
                    # the READ's handler phrase, not more condition. It was
                    # read into the condition text and the handler was lost.
                    break

                paren_depth = paren_depth_after(token, paren_depth)
                condition_tokens.append(condition_token_text(token))
                stream.consume()

            # Create CobolExpression for the condition and set it on statement
            if condition_tokens:
                stmt.set_until_clause(
                    _make_until_condition_expression(
                        condition_tokens, condition_symbols(get_parse_context(stream))
                    )
                )
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

    def _parse_inline_statements(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse inline statements within PERFORM ... END-PERFORM block."""
        try:
            skip_whitespace(stream)

            # Parse statements until END-PERFORM or PERIOD
            while not stream.is_empty():
                skip_statement_separators(stream)
                token = stream.peek()

                if not token:
                    break

                # Check for END-PERFORM
                if token.type == TokenType.END_PERFORM or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-PERFORM"
                ):
                    stream.consume()
                    # Skip optional period
                    self._try_consume_period(stream)
                    break

                # Check for PERIOD (inline PERFORM without END-PERFORM)
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break

                # Try to parse nested statement
                nested_stmt = try_parse_nested_statement(stream)
                if nested_stmt:
                    stmt.add_inline_statement(nested_stmt)
                else:
                    # Can't parse, skip token
                    stream.consume()
        except ParseError as exc:
            # H4: previously silent -- an inline PERFORM body statement that
            # raised left inline_statements incomplete with zero trace
            # anywhere (no ParseResult.errors, no .warnings, no log line).
            logger.debug(
                "PERFORM inline statement body parse suppressed %r", exc, exc_info=True
            )

    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        try:
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass
