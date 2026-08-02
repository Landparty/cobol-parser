"""Move statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    consume_optional_subscript,
    get_parse_context,
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
        # (A missing *source* is deliberately not flagged here: `MOVE TO x` is
        # indistinguishable from stray `*>`-comment text that the preprocessor
        # does not yet strip, so flagging it would fault valid programs.)
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
            # into the target list.
            if token.type == TokenType.IDENTIFIER and looks_like_paragraph_boundary(
                token_stream
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

            # Get token value
            if token.type == TokenType.STRING_LITERAL:
                source_parts.append(f'"{token.value}"')
            elif token.value:
                source_parts.append(token.value)

            token_stream.consume()

        return "".join(source_parts) if source_parts else ""
