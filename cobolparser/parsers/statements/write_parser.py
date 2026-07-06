"""Write statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    consume_end_keyword_and_period,
    create_statement,
    matches_keyword,
    parse_invalid_key_clauses,
    skip_whitespace,
    try_consume_keyword,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOWriteStatement


class WriteStatementParser(IStatementParser):
    """Parser for WRITE statements using IStatementParser interface.

    Supports:
    - WRITE record-name
    - WRITE record-name FROM source-data
    - WRITE record-name [FROM source] [BEFORE/AFTER ADVANCING [n LINES|PAGE]]
    - WRITE record-name [INVALID KEY stmts] [NOT INVALID KEY stmts] [END-WRITE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.WRITE, "WRITE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOWriteStatement:
        """Parse a WRITE statement."""
        stmt, _ = create_statement(token_stream, IOWriteStatement)

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
        if try_consume_keyword(token_stream, TokenType.FROM, "FROM"):
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
            if try_consume_keyword(token_stream, TokenType.ADVANCING, "ADVANCING"):
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
                # Lexer emits TokenType.LINES for "LINES" and TokenType.LINE for "LINE";
                # PAGE has no dedicated token type so it arrives as IDENTIFIER.
                token = token_stream.peek()
                if token and (
                    token.type in (TokenType.LINES, TokenType.LINE)
                    or (
                        token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() == "PAGE"
                    )
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)

        # Optional INVALID KEY / NOT INVALID KEY clauses
        skip_whitespace(token_stream)
        parse_invalid_key_clauses(token_stream, stmt, "END-WRITE")

        consume_end_keyword_and_period(token_stream, "END-WRITE")

        return stmt
