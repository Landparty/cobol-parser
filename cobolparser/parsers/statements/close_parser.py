"""Close statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    create_statement,
    is_statement_boundary,
    matches_keyword,
    skip_whitespace,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOCloseStatement


class CloseStatementParser(IStatementParser):
    """Parser for CLOSE statements.

    Supports:
    - CLOSE file-name [REEL|UNIT|WITH NO REWIND|WITH LOCK]...
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.CLOSE, "CLOSE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOCloseStatement:
        """Parse a CLOSE statement."""
        stmt, _ = create_statement(token_stream, IOCloseStatement)

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
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be folded into the file-name list when CLOSE has no trailing
            # period.
            if is_statement_boundary(token):
                break

            file_name = token.value
            token_stream.consume()
            skip_whitespace(token_stream)

            reel = False
            unit = False
            no_rewind = False
            with_lock = False

            # Parse per-file options. These can combine (e.g. REEL WITH NO
            # REWIND), so this must loop and keep applying options until
            # none match, rather than stopping after the first one.
            while True:
                token = token_stream.peek()
                if token and token.type == TokenType.REEL:
                    reel = True
                    token_stream.consume()
                    skip_whitespace(token_stream)
                elif token and (
                    token.type == TokenType.UNIT
                    or (
                        token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() == "UNIT"
                    )
                ):
                    unit = True
                    token_stream.consume()
                    skip_whitespace(token_stream)
                elif token and (
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
                    if token and (
                        token.type == TokenType.NO
                        or (
                            token.type == TokenType.IDENTIFIER
                            and token.value
                            and token.value.upper() == "NO"
                        )
                    ):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        # Consume REWIND (lexer maps "REWIND" to TokenType.NO_REWIND)
                        token = token_stream.peek()
                        if token and token.type == TokenType.NO_REWIND:
                            token_stream.consume()
                            skip_whitespace(token_stream)
                        elif (
                            token
                            and token.type == TokenType.IDENTIFIER
                            and token.value
                            and token.value.upper() == "REWIND"
                        ):
                            token_stream.consume()
                            skip_whitespace(token_stream)
                        no_rewind = True
                    elif token and (
                        token.type == TokenType.LOCK
                        or (
                            token.type == TokenType.IDENTIFIER
                            and token.value
                            and token.value.upper() == "LOCK"
                        )
                    ):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        with_lock = True
                else:
                    break

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
