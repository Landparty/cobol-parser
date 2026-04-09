"""SEARCH statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import SearchStatement
from ._utils import skip_whitespace


def _val(token: Any) -> str:
    return token.value.upper() if token and token.value else ""


class SearchStatementParser(IStatementParser):
    """Parser for SEARCH statements.

    Syntax:
        SEARCH table-name [VARYING identifier]
            [AT END imperative-statement]
            WHEN condition imperative-statement
            ...
        END-SEARCH

        SEARCH ALL table-name
            [AT END imperative-statement]
            WHEN condition imperative-statement
        END-SEARCH
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.SEARCH:
            return True
        return token.type == TokenType.IDENTIFIER and _val(token) == "SEARCH"

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SearchStatement:
        start = token_stream.consume()
        stmt = SearchStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        # Check for ALL
        token = token_stream.peek()
        if token and _val(token) == "ALL":
            token_stream.consume()
            stmt.set_metadata("is_search_all", True)
            skip_whitespace(token_stream)

        # Table name
        token = token_stream.peek()
        if token and token.type != TokenType.PERIOD:
            token_stream.consume()
            stmt.set_table_name(token.value or "")
        skip_whitespace(token_stream)

        # Optional VARYING
        token = token_stream.peek()
        if token and _val(token) == "VARYING":
            token_stream.consume()
            skip_whitespace(token_stream)
            var_token = token_stream.peek()
            if var_token and var_token.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_varying_variable(var_token.value or "")
            skip_whitespace(token_stream)

        # Parse AT END and WHEN clauses — simplified: consume to period/END-SEARCH
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            val = _val(token)
            if val == "END-SEARCH":
                token_stream.consume()
                skip_whitespace(token_stream)
                # Consume trailing period
                p = token_stream.peek()
                if p and p.type == TokenType.PERIOD:
                    token_stream.consume()
                break
            if val == "WHEN":
                token_stream.consume()
                skip_whitespace(token_stream)
                # Collect condition text until next WHEN/END-SEARCH/period
                cond_parts: list[str] = []
                while not token_stream.is_empty():
                    t = token_stream.peek()
                    if not t:
                        break
                    tv = _val(t)
                    if t.type == TokenType.PERIOD or tv in (
                        "WHEN",
                        "END-SEARCH",
                        "AT",
                    ):
                        break
                    token_stream.consume()
                    cond_parts.append(t.value or "")
                    skip_whitespace(token_stream)
                stmt.add_when_clause(" ".join(cond_parts), [])
            else:
                token_stream.consume()
            skip_whitespace(token_stream)

        return stmt
