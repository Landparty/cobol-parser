"""Close statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import CloseStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from cobolparser.parsers.statements._utils import skip_whitespace


class CloseStatementParser(IStatementParser):
    """Parser for CLOSE statements.

    Supports:
    - CLOSE file-name [REEL|UNIT|WITH NO REWIND|WITH LOCK]...
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is CLOSE keyword."""
        try:
            token = token_stream.peek()
            return bool(token and token.type == TokenType.CLOSE)
        except Exception:
            return False

    def parse(self, token_stream: ITokenStream) -> CloseStatement:
        """Parse a CLOSE statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            CloseStatement,
            factory.create(
                CloseStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        skip_whitespace(token_stream)

        # Parse one or more file names with options
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type != TokenType.IDENTIFIER:
                break

            file_name = token.value
            token_stream.consume()
            skip_whitespace(token_stream)

            reel = False
            unit = False
            no_rewind = False
            with_lock = False

            # Parse per-file options
            token = token_stream.peek()
            if token and token.type == TokenType.REEL:
                reel = True
                token_stream.consume()
                skip_whitespace(token_stream)
            elif token and token.type == TokenType.IDENTIFIER and token.value:
                val = token.value.upper()
                if val == "UNIT":
                    unit = True
                    token_stream.consume()
                    skip_whitespace(token_stream)
                elif val == "WITH":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER and token.value:
                        inner = token.value.upper()
                        if inner == "NO":
                            token_stream.consume()
                            skip_whitespace(token_stream)
                            token = token_stream.peek()
                            if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "REWIND":
                                token_stream.consume()
                                skip_whitespace(token_stream)
                            no_rewind = True
                        elif inner == "LOCK":
                            token_stream.consume()
                            skip_whitespace(token_stream)
                            with_lock = True
                    elif token and token.type == TokenType.LOCK:
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        with_lock = True

            stmt.add_file(
                file_name,
                reel=reel,
                unit=unit,
                no_rewind=no_rewind,
                with_lock=with_lock,
            )

        # Consume period if present
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
