"""Open statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import matches_keyword, skip_whitespace

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import IOOpenStatement

# Open modes recognized as IDENTIFIER tokens with these values
_OPEN_MODES = {"INPUT", "OUTPUT", "EXTEND"}
# I-O is also a mode but contains a hyphen


class OpenStatementParser(IStatementParser):
    """Parser for OPEN statements.

    Supports:
    - OPEN INPUT|OUTPUT|I-O|EXTEND file-name...
    - OPEN I-O file-name WITH REPOSITION (VSAM)
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.OPEN, "OPEN")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOOpenStatement:
        """Parse an OPEN statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IOOpenStatement,
            factory.create(
                IOOpenStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        skip_whitespace(token_stream)

        # Parse open mode: INPUT, OUTPUT, I-O, EXTEND
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            val = token.value.upper()
            if val in _OPEN_MODES or val == "I-O":
                stmt.set_open_mode(val)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Parse one or more file names
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            # Stop on WITH keyword (lexer emits TokenType.WITH)
            if token.type == TokenType.WITH:
                break
            if token.type == TokenType.IDENTIFIER and token.value:
                val = token.value.upper()
                # Stop at next open mode or WITH keyword
                if val in _OPEN_MODES or val == "I-O" or val == "WITH":
                    break
                # WITH REPOSITION for VSAM (when REPOSITION seen directly)
                if val == "REPOSITION":
                    token_stream.consume()
                    stmt.set_reposition(True)
                    skip_whitespace(token_stream)
                    continue
                # Otherwise it's a file name
                stmt.add_file(token.value)
                token_stream.consume()
                skip_whitespace(token_stream)
            else:
                break

        # Optional WITH REPOSITION
        # Lexer emits TokenType.WITH for "WITH" (not IDENTIFIER).
        token = token_stream.peek()
        if token and (
            token.type == TokenType.WITH
            or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "WITH"
            )
        ):
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "REPOSITION"
            ):
                token_stream.consume()
                stmt.set_reposition(True)
                skip_whitespace(token_stream)

        # Consume period if present
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
