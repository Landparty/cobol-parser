"""Open statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    create_statement,
    matches_keyword,
    skip_whitespace,
    try_consume_keyword,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
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
        stmt, _ = create_statement(token_stream, IOOpenStatement)

        skip_whitespace(token_stream)

        # Parse open mode: INPUT, OUTPUT, I-O, EXTEND
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            val = token.value.upper()
            if val in _OPEN_MODES or val == "I-O":
                stmt.set_open_mode(val)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Parse one or more file names, possibly across several mode groups
        # (OPEN INPUT FILE-A OUTPUT FILE-B ...). `open_mode` keeps the first
        # group's mode; files from every group are collected.
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
                if val == "WITH":
                    break
                # A subsequent open mode starts a new mode group: consume it
                # and keep collecting its file names.
                if val in _OPEN_MODES or val == "I-O":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    continue
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
        if try_consume_keyword(token_stream, TokenType.WITH, "WITH"):
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
