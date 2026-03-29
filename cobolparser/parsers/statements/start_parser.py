"""Start statement parser implementing IStatementParser interface."""

from typing import cast
from ...core.interfaces import IStatementParser, ITokenStream
from ...core.ast_factory import get_factory
from ...models.statements import IOStartStatement
from ...models.ast_base import SourceLocation
from ...lexer import TokenType
from cobolparser.parsers.statements._utils import skip_whitespace, collect_clause_stmts

# Key conditions recognized as IDENTIFIER tokens
_KEY_CONDITIONS = {
    "EQUAL", "EQUALS", "GREATER", "LESS", "NOT",
    "FIRST", "LAST",
}

# Comparison operator identifiers
_COMPARISON_OPS = {"EQUAL", "EQUALS", "GREATER", "LESS"}


class StartStatementParser(IStatementParser):
    """Parser for START statements.

    Supports:
    - START file-name [KEY IS|EQUAL|NOT LESS THAN|GREATER THAN|...] [INVALID KEY stmts] [END-START]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is START keyword."""
        try:
            token = token_stream.peek()
            return bool(token and token.type == TokenType.START)
        except Exception:
            return False

    def parse(self, token_stream: ITokenStream) -> IOStartStatement:
        """Parse a START statement."""
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            IOStartStatement,
            factory.create(
                IOStartStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

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
        token = token_stream.peek()
        if token and token.type in (TokenType.KEY_IS, TokenType.KEY):
            consumed_key = token_stream.consume()
            skip_whitespace(token_stream)

            # If KEY (not KEY_IS), consume optional IS keyword
            if consumed_key.type == TokenType.KEY:
                nxt = token_stream.peek()
                if nxt and nxt.type == TokenType.IS:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                elif nxt and nxt.type == TokenType.IDENTIFIER and nxt.value and nxt.value.upper() == "IS":
                    token_stream.consume()
                    skip_whitespace(token_stream)

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
                    if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("THAN", "TO"):
                        condition_parts.append(token.value.upper())
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        # Optional OR EQUAL
                        token = token_stream.peek()
                        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "OR":
                            token_stream.consume()
                            skip_whitespace(token_stream)
                            token = token_stream.peek()
                            if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() in ("EQUAL", "EQUALS"):
                                condition_parts.append("OR EQUAL")
                                token_stream.consume()
                                skip_whitespace(token_stream)

            if condition_parts:
                stmt.set_key_condition(" ".join(condition_parts))

        # Optional INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.INVALID:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.KEY:
                token_stream.consume()
                skip_whitespace(token_stream)
            clause_stmts = collect_clause_stmts(
                token_stream, {"END-START"}
            )
            stmt.set_invalid_key_clause(clause_stmts)

        # Optional NOT INVALID KEY clause
        token = token_stream.peek()
        if token and token.type == TokenType.NOT:
            token_stream.consume()
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if token and token.type == TokenType.INVALID:
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.type == TokenType.KEY:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                clause_stmts = collect_clause_stmts(
                    token_stream, {"END-START"}
                )
                stmt.set_not_invalid_key_clause(clause_stmts)

        # Consume END-START or PERIOD
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-START":
            token_stream.consume()
            skip_whitespace(token_stream)
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
