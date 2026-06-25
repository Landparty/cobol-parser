"""Start statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    consume_end_keyword_and_period,
    consume_key_is,
    create_statement,
    matches_keyword,
    parse_invalid_key_clauses,
    skip_whitespace,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOStartStatement

# Key conditions recognized as IDENTIFIER tokens
_KEY_CONDITIONS = {
    "EQUAL",
    "EQUALS",
    "GREATER",
    "LESS",
    "NOT",
    "FIRST",
    "LAST",
}

# Comparison operator identifiers
_COMPARISON_OPS = {"EQUAL", "EQUALS", "GREATER", "LESS"}


class StartStatementParser(IStatementParser):
    """Parser for START statements.

    Supports:
    - START file-name [KEY IS|EQUAL|NOT LESS THAN|GREATER THAN|...] [INVALID KEY stmts] [END-START]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.START, "START")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOStartStatement:
        """Parse a START statement."""
        stmt, _ = create_statement(token_stream, IOStartStatement)

        skip_whitespace(token_stream)

        # Parse file name (required)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.set_file_name(token.value)
            token_stream.consume()
        else:
            return stmt

        skip_whitespace(token_stream)

        # Optional KEY clause (may be tokenized as KEY_IS or KEY + IS)
        if consume_key_is(token_stream):
            # Parse condition: EQUAL, GREATER, LESS, NOT LESS, GREATER THAN OR EQUAL, etc.
            condition_parts = []
            token = token_stream.peek()
            if token and token.type == TokenType.NOT:
                condition_parts.append("NOT")
                token_stream.consume()
                skip_whitespace(token_stream)

            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER and token.value:
                val = token.value.upper()
                if val in _COMPARISON_OPS or val in ("THAN", "TO"):
                    condition_parts.append(val)
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    # Parse THAN or TO
                    token = token_stream.peek()
                    if (
                        token
                        and token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() in ("THAN", "TO")
                    ):
                        condition_parts.append(token.value.upper())
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        # Optional OR EQUAL
                        token = token_stream.peek()
                        if (
                            token
                            and token.type == TokenType.IDENTIFIER
                            and token.value
                            and token.value.upper() == "OR"
                        ):
                            token_stream.consume()
                            skip_whitespace(token_stream)
                            token = token_stream.peek()
                            if (
                                token
                                and token.type == TokenType.IDENTIFIER
                                and token.value
                                and token.value.upper() in ("EQUAL", "EQUALS")
                            ):
                                condition_parts.append("OR EQUAL")
                                token_stream.consume()
                                skip_whitespace(token_stream)

            if condition_parts:
                stmt.set_key_condition(" ".join(condition_parts))

        parse_invalid_key_clauses(token_stream, stmt, "END-START")
        consume_end_keyword_and_period(token_stream, "END-START")

        return stmt
