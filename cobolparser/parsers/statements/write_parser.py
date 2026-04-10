"""Write statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import skip_whitespace

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IOWriteStatement


class WriteStatementParser(IStatementParser):
    """Parser for WRITE statements using IStatementParser interface.

    Supports:
    - WRITE record-name
    - WRITE record-name FROM source-data
    - WRITE record-name [FROM source] [BEFORE/AFTER ADVANCING [n LINES|PAGE]]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is WRITE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            if token.type == TokenType.WRITE:
                return True
            return False
        except Exception:
            return False

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOWriteStatement:
        """Parse a WRITE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IOWriteStatement,
            factory.create(
                IOWriteStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        # Skip whitespace
        skip_whitespace(token_stream)

        # Parse record name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            record_name = token.value
            stmt.set_record_name(record_name)
            token_stream.consume()
        else:
            # Missing record name - just return what we have
            return stmt

        skip_whitespace(token_stream)

        # Check for FROM clause: lexer emits TokenType.FROM for "FROM"
        token = token_stream.peek()
        if token and (
            token.type == TokenType.FROM
            or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "FROM"
            )
        ):
            token_stream.consume()
            skip_whitespace(token_stream)

            # Parse FROM source
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                source = token.value
                stmt.set_from(source)
                token_stream.consume()

            skip_whitespace(token_stream)

        # Check for ADVANCING clause: BEFORE/AFTER ADVANCING [n] [LINES|LINE|PAGE]
        # Lexer emits TokenType.BEFORE / TokenType.AFTER for these keywords.
        token = token_stream.peek()
        is_before_after = token and (
            token.type in (TokenType.BEFORE, TokenType.AFTER)
            or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in ("BEFORE", "AFTER")
            )
        )
        if is_before_after and token is not None:
            advancing_mode = (token.value or "").upper()
            token_stream.consume()
            skip_whitespace(token_stream)

            # Expect ADVANCING keyword
            token = token_stream.peek()
            if token and (
                token.type == TokenType.ADVANCING
                or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "ADVANCING"
                )
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                stmt.advancing_mode = advancing_mode

                # Consume optional count (numeric literal or level number)
                token = token_stream.peek()
                if token and token.type in (
                    TokenType.LEVEL_NUMBER,
                    TokenType.NUMERIC_LITERAL,
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)

                # Consume optional LINES / LINE / PAGE
                token = token_stream.peek()
                if token and (
                    token.type == TokenType.LINES
                    or (
                        token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() in ("LINE", "PAGE")
                    )
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)

        # Skip whitespace and consume period if present
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
