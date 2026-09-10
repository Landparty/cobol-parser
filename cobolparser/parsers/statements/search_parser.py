"""SEARCH statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import SearchStatement
from ._conditions import condition_token_text
from ._utils import (
    LITERAL_TOKEN_TYPES,
    STATEMENT_KEYWORDS,
    bare_end_starts_at_end_clause,
    matches_keyword,
    skip_statement_separators,
    skip_whitespace,
    token_location,
    try_parse_nested_statement,
)
from ._utils import (
    token_value_upper as _val,
)


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
        return matches_keyword(token_stream, TokenType.SEARCH, "SEARCH")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SearchStatement:
        start = token_stream.consume()
        stmt = SearchStatement(token_location(start))
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

        # Parse AT END and WHEN clauses
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
                p = token_stream.peek()
                if p and p.type == TokenType.PERIOD:
                    token_stream.consume()
                break
            if val == "AT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "END":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    # Parse AT END nested statements
                    at_end_stmts = self._parse_nested_statements(token_stream)
                    if at_end_stmts:
                        stmt.set_at_end_clause(at_end_stmts)
            elif bare_end_starts_at_end_clause(token_stream):
                # ``SEARCH T END stmts WHEN ...`` -- AT is optional.
                token_stream.consume()  # END
                skip_whitespace(token_stream)
                at_end_stmts = self._parse_nested_statements(token_stream)
                if at_end_stmts:
                    stmt.set_at_end_clause(at_end_stmts)
            elif val == "WHEN":
                token_stream.consume()
                skip_whitespace(token_stream)
                # Collect condition text until statement keyword
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
                    if t.type not in LITERAL_TOKEN_TYPES and tv in STATEMENT_KEYWORDS:
                        break
                    token_stream.consume()
                    # Re-quote string literals so ``= 'X'`` and ``= X`` stay
                    # distinguishable in the recorded condition text.
                    cond_parts.append(condition_token_text(t))
                    skip_whitespace(token_stream)
                # Parse nested statements after condition
                when_stmts = self._parse_nested_statements(token_stream)
                stmt.add_when_clause(" ".join(cond_parts), when_stmts)
            else:
                token_stream.consume()
            skip_whitespace(token_stream)

        return stmt

    @staticmethod
    def _parse_nested_statements(token_stream: ITokenStream) -> list:
        """Parse nested imperative statements until a WHEN/END-SEARCH/period boundary."""
        stmts: list = []
        while not token_stream.is_empty():
            skip_statement_separators(token_stream)
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD or val in (
                "WHEN",
                "END-SEARCH",
                "AT",
            ):
                break
            nested = try_parse_nested_statement(token_stream)
            if nested:
                stmts.append(nested)
            else:
                break
        return stmts
