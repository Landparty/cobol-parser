"""Stop statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import StopStatement
from ._utils import consume_period, matches_keyword


class StopStatementParser(IStatementParser):
    """Parser for STOP statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.STOP, "STOP")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> StopStatement:
        """Parse a STOP statement."""
        start_token = token_stream.consume()
        if not start_token:
            # Return empty statement if no token
            from ...models.ast_base import SourceLocation

            return StopStatement(SourceLocation(0, 0))

        # Create statement
        from ...models.ast_base import SourceLocation

        location = getattr(start_token, "location", None) or SourceLocation(0, 0)
        stmt = StopStatement(location)

        # Parse STOP type: STOP RUN or STOP "literal" (or STOP <numeric>)
        if not token_stream.is_empty():
            next_token = token_stream.peek()
            if next_token and next_token.value:
                if next_token.value.upper() == "RUN":
                    stmt.stop_type = "RUN"
                    token_stream.consume()  # consume RUN
                elif next_token.type.name in (
                    "STRING_LITERAL",
                    "NUMERIC_LITERAL",
                    # 1-49 lex as LEVEL_NUMBER: ``STOP 12`` is a literal too.
                    "LEVEL_NUMBER",
                    "FIGURATIVE_CONSTANT",  # STOP ZERO / STOP QUOTE (OBNC1M)
                ):
                    stmt.stop_type = next_token.value
                    token_stream.consume()  # consume literal

        # Optional RETURNING / GIVING return-code (STOP RUN RETURNING x). The
        # operand was previously left in the stream and dropped.
        if not token_stream.is_empty():
            nxt = token_stream.peek()
            if nxt and nxt.value and nxt.value.upper() in ("RETURNING", "GIVING"):
                token_stream.consume()  # consume RETURNING/GIVING
                if not token_stream.is_empty():
                    val = token_stream.peek()
                    if (
                        val
                        and val.value
                        and val.type
                        in (
                            TokenType.IDENTIFIER,
                            TokenType.NUMERIC_LITERAL,
                            # ``RETURNING 8``: 1-49 lex as LEVEL_NUMBER. Left
                            # in the stream, ``8.`` became a phantom paragraph
                            # that took the rest of the real one with it.
                            TokenType.LEVEL_NUMBER,
                        )
                    ):
                        stmt.returning = val.value
                        token_stream.consume()

        # Consume the sentence period so it is not re-parsed as a phantom
        # empty paragraph named "." by the procedure-division parser.
        consume_period(token_stream)

        return stmt
