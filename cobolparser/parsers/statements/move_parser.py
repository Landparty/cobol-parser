"""Move statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    consume_optional_subscript,
    get_parse_context,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    report_parse_error,
    skip_whitespace,
    try_consume_keyword,
    warn_paragraph_boundary_swallowed,
)

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import MoveStatement

# Union of the canonical statement-start sets (single source of truth in
# _utils.py — covers every registered statement verb, including EXEC/EXECUTE)
# with MOVE-specific clause/scope boundaries that aren't statement starts
# themselves (ELSE/WHEN/END-xxx, and the AT/INVALID/NOT clause-boundary
# keywords inside IO statement bodies). Without the canonical sets, a MOVE
# with no trailing period immediately followed by a statement type missing
# from a hand-rolled local list (e.g. EXEC SQL) would silently swallow that
# statement's leading tokens as bogus MOVE targets.
_STOP_TOKEN_TYPES: frozenset = STATEMENT_TOKEN_TYPES | frozenset(
    getattr(TokenType, name)
    for name in (
        "GO",
        "ELSE",
        "WHEN",
        "END_IF",
        "END_EVALUATE",
        "END_PERFORM",
        # Clause boundaries inside IO statements (AT END / INVALID KEY):
        # a MOVE in a clause body must not devour the next clause's keywords.
        "NOT",
        "INVALID",
        "AT",
    )
    if hasattr(TokenType, name)
)

_STOP_KEYWORDS: frozenset = STATEMENT_KEYWORDS | frozenset(
    {
        "END-MOVE",
        "ON",
        "RETURNING",
        "GIVING",
        "END-IF",
        "ELSE",
        "THEN",
    }
)


class MoveStatementParser(IStatementParser):
    """Parser for MOVE statements using IStatementParser interface.

    Supports:
    - MOVE source TO target [target]*
    - MOVE CORRESPONDING source TO target
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.MOVE, "MOVE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> MoveStatement:
        """Parse a MOVE statement."""
        start_token = token_stream.consume()
        start_column = getattr(getattr(start_token, "location", None), "column", None)
        factory = get_factory()
        stmt = cast(
            MoveStatement,
            factory.create(
                MoveStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )
        context = get_parse_context(token_stream)

        # Skip whitespace
        skip_whitespace(token_stream)

        # Check for CORRESPONDING or CORR
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            if token.value.upper() in ("CORRESPONDING", "CORR"):
                stmt.set_corresponding(True)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Parse source operand
        source = self._parse_source(token_stream)
        stmt.set_source(source)

        skip_whitespace(token_stream)

        # Expect TO keyword. Its absence (e.g. `MOVE A` or `MOVE A B.`) is a
        # syntax error — COBOL requires TO between the source and its targets.
        # (A missing *source* is deliberately not flagged here: `MOVE TO x`
        # can arise from stray `REPLACE`/`COPY ... REPLACING` pseudo-text
        # (`==MOVE==`) leaking a bare verb with no source, so flagging it
        # would fault otherwise-valid programs.)
        if not try_consume_keyword(token_stream, TokenType.TO, "TO"):
            report_parse_error(
                context,
                "MOVE statement requires TO before its target(s)",
                stmt.location,
            )
            return stmt

        skip_whitespace(token_stream)

        # Parse targets - only collect one target unless we have more TO keywords
        target_count = 0

        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token or token.type == TokenType.PERIOD:
                if token and token.type == TokenType.PERIOD:
                    token_stream.consume()
                break

            # Stop at keywords - check by TokenType first
            if token.type in _STOP_TOKEN_TYPES:
                break

            # Also check for keywords by value for non-statement types
            if token.type == TokenType.IDENTIFIER and token.value:
                val_upper = token.value.upper()
                if val_upper in _STOP_KEYWORDS or val_upper in SCOPE_TERMINATORS:
                    break

            # A missing period on this MOVE followed by what looks like the
            # next paragraph/section header (H9): stop instead of folding it
            # into the target list. That heuristic alone over-fires: COBOL's
            # MOVE grammar guarantees an operand immediately follows TO (and
            # any target after it may just as legitimately wrap onto its own
            # continuation line), so a perfectly ordinary line-wrapped target
            # (`MOVE A TO\n    B.` or `MOVE A TO B\n    C.`) was misread as a
            # new paragraph whenever the wrapped name wasn't in
            # known_data_names -- e.g. declared via an unexpanded COPY member
            # -- dropping that target instead of collecting it (or, for the
            # first target, leaving the MOVE with none at all and a spurious
            # "requires at least one target after TO" error). Disambiguated
            # by indentation, for every target position, not just the first:
            # a genuine paragraph/section header is dedented back to Area A
            # relative to the MOVE statement's own column, whereas a wrapped
            # continuation-line operand stays at or deeper than it (Area B).
            # A truly missing target immediately followed by a real, dedented
            # next paragraph is therefore still caught here instead of being
            # silently absorbed as the MOVE's target.
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(token_stream)
                break

            # Parse target - only collect IDENTIFIERs. A trailing
            # ``(subscript[, subscript]...)`` group (e.g. a table reference
            # like ``TBL (3, 5, 2)``) is folded into the target string via
            # consume_optional_subscript, matching how ADD/SUBTRACT/COMPUTE
            # targets and the arithmetic GIVING clause already do -- without
            # this, the subscript tokens fall to the `else` branch below and
            # are silently discarded, losing which table element was set.
            if token.type == TokenType.IDENTIFIER:
                parts: list[str] = [token.value] if token.value else []
                token_stream.consume()
                consume_optional_subscript(token_stream, parts)
                target_name = " ".join(p for p in parts if p)
                if target_name:
                    stmt.add_target(target_name)
                target_count += 1
            else:
                # Skip non-identifier tokens (operators, comparisons, etc)
                token_stream.consume()

        # A MOVE that reached TO but collected no receiving field (e.g.
        # `MOVE A TO.` or a stream truncated right after TO) is invalid.
        if target_count == 0:
            report_parse_error(
                context,
                "MOVE statement requires at least one target after TO",
                stmt.location,
            )

        return stmt

    def _parse_source(self, token_stream: ITokenStream) -> str:
        """Parse source operand until TO keyword is found."""
        source_parts = []
        paren_depth = 0

        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token:
                break

            # Check for TO keyword (only if not in parens)
            if paren_depth == 0:
                if token.type == TokenType.TO or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "TO"
                ):
                    break

            # Handle parentheses
            if token.type == TokenType.LEFT_PAREN:
                paren_depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                paren_depth = max(0, paren_depth - 1)

            # Stop at period if not in parens
            if paren_depth == 0 and token.type == TokenType.PERIOD:
                break

            # Get token value. A typed literal (X"41", Z"...", N"...")
            # keeps its original prefixed text in raw_value -- re-quoting
            # only the content would silently turn the one-byte hex literal
            # X"41" into the two-character text literal "41".
            if token.type == TokenType.STRING_LITERAL:
                if token.raw_value:
                    source_parts.append(token.raw_value)
                else:
                    source_parts.append(f'"{token.value}"')
            elif token.value:
                source_parts.append(token.value)

            token_stream.consume()

        return _join_source_parts(source_parts)


def _join_source_parts(parts: list[str]) -> str:
    """Join collected source tokens back into readable COBOL text.

    A bare ``"".join`` corrupted every multi-word source (``MOVE WS-A OF
    WS-GRP`` became ``WS-AOFWS-GRP``; ``FUNCTION UPPER-CASE(WS-X)`` became
    ``FUNCTIONUPPER-CASE(WS-X)``), while a bare ``" ".join`` would space out
    subscripts. Words are space-separated; parens/commas follow the
    subscript-aware convention ``_consume_arithmetic_target`` established:
    no space before ``(``, none after ``(`` or before ``)``/``,``, so
    ``TABLE (1, 2)`` renders as ``TABLE(1, 2)``. A reference-modification
    colon joins tight on both sides (``WS-X(2:3)``, never ``WS-X(2 : 3)``
    -- the spaced form is not what the source said and breaks any consumer
    that re-parses the text). Single-token sources are returned unchanged.
    """
    out = ""
    prev_part: str | None = None
    # Tracks whether `prev_part` was itself a leading unary sign (one that
    # starts a fresh operand: at the very start of the source, right after
    # an opening paren, right after a ref-mod colon, or right after a comma
    # between subscripts) so the digit that follows it glues on with no
    # space even when the sign itself got a space (e.g. after a comma:
    # "WS-TAB(WS-I, -1)").
    prev_was_leading_sign = False
    for part in parts:
        if not part:
            continue
        is_sign = part in ("-", "+")
        is_leading_sign = is_sign and prev_part in (None, "(", ",", ":")
        if (
            not out
            or part in ("(", ")", ",", ":")
            or prev_part in ("(", ":")
            or prev_was_leading_sign
        ):
            out += part
        else:
            out += " " + part
        prev_was_leading_sign = is_leading_sign
        prev_part = part
    return out
