"""SET statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import SetStatement
from ._utils import skip_whitespace


def _val(token: Any) -> str:
    return token.value.upper() if token and token.value else ""


def _strip_period(value: str) -> str:
    """Strip trailing period from numeric literal values like '1.'."""
    if value.endswith(".") and len(value) > 1:
        return value[:-1]
    return value


class SetStatementParser(IStatementParser):
    """Parser for SET statements.

    Syntax:
        SET identifier-1 [identifier-2 ...] TO value
        SET identifier UP BY value
        SET identifier DOWN BY value
        SET condition-name TO TRUE
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.SET:
            return True
        return token.type == TokenType.IDENTIFIER and _val(token) == "SET"

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SetStatement:
        start = token_stream.consume()
        stmt = SetStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        # Collect targets until TO/UP/DOWN/period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            if val in ("TO", "UP", "DOWN"):
                break
            if token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                token_stream.consume()
                # Skip ADDRESS and OF keywords
                if val in ("ADDRESS", "OF"):
                    pass
                else:
                    stmt.add_target(token.value or "")
            else:
                break
            skip_whitespace(token_stream)

        # Parse the action: TO, UP BY, DOWN BY
        token = token_stream.peek()
        if not token:
            return stmt

        val = _val(token)
        if val == "TO":
            token_stream.consume()
            skip_whitespace(token_stream)
            v = token_stream.peek()
            if v:
                vv = _val(v)
                if vv == "TRUE":
                    stmt.set_set_type("TRUE")
                    token_stream.consume()
                elif vv == "FALSE":
                    stmt.set_set_type("FALSE")
                    token_stream.consume()
                elif v.type != TokenType.PERIOD:
                    stmt.set_set_type("TO")
                    token_stream.consume()
                    stmt.set_value(_strip_period(v.value or ""))
        elif val == "UP":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "BY":
                token_stream.consume()
                skip_whitespace(token_stream)
            stmt.set_set_type("UP_BY")
            v = token_stream.peek()
            if v and v.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_value(_strip_period(v.value or ""))
        elif val == "DOWN":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "BY":
                token_stream.consume()
                skip_whitespace(token_stream)
            stmt.set_set_type("DOWN_BY")
            v = token_stream.peek()
            if v and v.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_value(_strip_period(v.value or ""))

        skip_whitespace(token_stream)
        # Consume period
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
