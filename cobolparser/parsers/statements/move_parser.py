"""Move statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    matches_keyword,
    skip_whitespace,
    try_consume_keyword,
)

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import MoveStatement

_STOP_TOKEN_TYPES: frozenset = frozenset(
    getattr(TokenType, name)
    for name in (
        "MOVE",
        "DISPLAY",
        "CALL",
        "ADD",
        "SUBTRACT",
        "MULTIPLY",
        "DIVIDE",
        "IF",
        "PERFORM",
        "EVALUATE",
        "STOP",
        "EXIT",
        "GO",
        "ELSE",
        "WHEN",
        "END_IF",
        "END_EVALUATE",
        "END_PERFORM",
    )
    if hasattr(TokenType, name)
)

_STOP_KEYWORDS: frozenset = frozenset(
    {
        "MOVE",
        "DISPLAY",
        "CALL",
        "ADD",
        "SUBTRACT",
        "MULTIPLY",
        "DIVIDE",
        "IF",
        "PERFORM",
        "EVALUATE",
        "STOP",
        "GO",
        "ENTRY",
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

        # Expect TO keyword
        if not try_consume_keyword(token_stream, TokenType.TO, "TO"):
            # Missing TO, but continue parsing
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
                if val_upper in _STOP_KEYWORDS:
                    break

            # Parse target - only collect IDENTIFIERs
            if token.type == TokenType.IDENTIFIER:
                target_name = token.value
                if target_name:
                    stmt.add_target(target_name)
                target_count += 1
                token_stream.consume()
            else:
                # Skip non-identifier tokens (operators, comparisons, etc)
                token_stream.consume()

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
