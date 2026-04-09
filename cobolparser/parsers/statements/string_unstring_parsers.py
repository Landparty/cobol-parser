"""STRING and UNSTRING statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import StringStatement, UnstringStatement
from ._utils import STATEMENT_KEYWORDS, skip_whitespace, try_parse_nested_statement


def _val(token: Any) -> str:
    return token.value.upper() if token and token.value else ""


def _consume_period(token_stream: ITokenStream) -> None:
    if not token_stream.is_empty():
        t = token_stream.peek()
        if t and t.type == TokenType.PERIOD:
            token_stream.consume()


def _parse_overflow_stmts(token_stream: ITokenStream) -> list:
    """Parse imperative statements in an ON OVERFLOW / NOT ON OVERFLOW clause."""
    stmts: list = []
    while not token_stream.is_empty():
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if not token:
            break
        val = _val(token)
        if token.type == TokenType.PERIOD or val in (
            "END-STRING",
            "END-UNSTRING",
            "NOT",
        ):
            break
        if val in STATEMENT_KEYWORDS:
            nested = try_parse_nested_statement(token_stream)
            if nested:
                stmts.append(nested)
            else:
                break
        else:
            break
    return stmts


class StringStatementParser(IStatementParser):
    """Parser for STRING statements.

    Syntax:
        STRING source-1 [DELIMITED BY delim-1] ...
            INTO target
            [WITH POINTER pointer-var]
            [ON OVERFLOW statements]
            [NOT ON OVERFLOW statements]
        [END-STRING]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.STRING:
            return True
        return token.type == TokenType.IDENTIFIER and _val(token) == "STRING"

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> StringStatement:
        start = token_stream.consume()
        stmt = StringStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if val == "END-STRING":
                token_stream.consume()
                skip_whitespace(token_stream)
                _consume_period(token_stream)
                break
            if val == "DELIMITED":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "BY":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    d = token_stream.peek()
                    if d and d.type != TokenType.PERIOD:
                        token_stream.consume()
                        stmt.add_delimiter(d.value or "")
            elif val == "INTO":
                token_stream.consume()
                skip_whitespace(token_stream)
                tgt = token_stream.peek()
                if tgt and tgt.type != TokenType.PERIOD:
                    token_stream.consume()
                    stmt.set_into_target(tgt.value or "")
            elif val == "WITH":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "POINTER":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    pv = token_stream.peek()
                    if pv and pv.type != TokenType.PERIOD:
                        token_stream.consume()
                        stmt.set_pointer_variable(pv.value or "")
            elif val == "ON":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_on_overflow_clause(overflow_stmts)
            elif val == "NOT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "ON":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_not_on_overflow_clause(overflow_stmts)
            elif val == "OVERFLOW":
                # Standalone OVERFLOW (without ON prefix)
                token_stream.consume()
                skip_whitespace(token_stream)
                overflow_stmts = _parse_overflow_stmts(token_stream)
                if overflow_stmts:
                    stmt.set_on_overflow_clause(overflow_stmts)
            elif token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
            ):
                token_stream.consume()
                stmt.add_operand(token.value or "")
            else:
                token_stream.consume()

            skip_whitespace(token_stream)

        return stmt


class UnstringStatementParser(IStatementParser):
    """Parser for UNSTRING statements.

    Syntax:
        UNSTRING source DELIMITED BY [ALL] delim [OR [ALL] delim] ...
            INTO target-1 [DELIMITER IN d1] [COUNT IN c1] ...
            [WITH POINTER pointer-var]
            [TALLYING IN tally-var]
            [ON OVERFLOW statements]
            [NOT ON OVERFLOW statements]
        [END-UNSTRING]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        token = token_stream.peek()
        if not token:
            return False
        if token.type == TokenType.UNSTRING:
            return True
        return token.type == TokenType.IDENTIFIER and _val(token) == "UNSTRING"

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> UnstringStatement:
        start = token_stream.consume()
        stmt = UnstringStatement(
            start.location if hasattr(start, "location") else SourceLocation(0, 0)
        )
        skip_whitespace(token_stream)

        # Source identifier
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_source(token.value or "")
        skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)

            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if val == "END-UNSTRING":
                token_stream.consume()
                skip_whitespace(token_stream)
                _consume_period(token_stream)
                break
            if val == "DELIMITED":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "BY":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    # Optional ALL
                    nxt = token_stream.peek()
                    if nxt and _val(nxt) == "ALL":
                        token_stream.consume()
                        skip_whitespace(token_stream)
                    d = token_stream.peek()
                    if d and d.type != TokenType.PERIOD:
                        token_stream.consume()
                        stmt.add_delimiter(d.value or "")
            elif val == "INTO":
                token_stream.consume()
                skip_whitespace(token_stream)
                self._parse_into_targets(token_stream, stmt)
            elif val == "WITH":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "POINTER":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    pv = token_stream.peek()
                    if pv and pv.type != TokenType.PERIOD:
                        token_stream.consume()
                        stmt.set_pointer_variable(pv.value or "")
            elif val == "ON":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_on_overflow_clause(overflow_stmts)
            elif val == "NOT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "ON":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "OVERFLOW":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    overflow_stmts = _parse_overflow_stmts(token_stream)
                    if overflow_stmts:
                        stmt.set_not_on_overflow_clause(overflow_stmts)
            else:
                token_stream.consume()

            skip_whitespace(token_stream)

        return stmt

    @staticmethod
    def _parse_into_targets(
        token_stream: ITokenStream, stmt: UnstringStatement
    ) -> None:
        """Parse INTO target-1 [DELIMITER IN d1] [COUNT IN c1] ..."""
        current_target: str | None = None
        current_delim_var: str | None = None
        current_count_var: str | None = None

        while not token_stream.is_empty():
            tgt = token_stream.peek()
            if not tgt:
                break
            tval = _val(tgt)
            if tgt.type == TokenType.PERIOD or tval in (
                "WITH",
                "TALLYING",
                "ON",
                "NOT",
                "END-UNSTRING",
            ):
                break
            if tval == "DELIMITER":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IN":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and n.type != TokenType.PERIOD:
                    token_stream.consume()
                    current_delim_var = n.value or ""
            elif tval == "COUNT":
                token_stream.consume()
                skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and _val(n) == "IN":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                n = token_stream.peek()
                if n and n.type != TokenType.PERIOD:
                    token_stream.consume()
                    current_count_var = n.value or ""
            elif tgt.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                # Flush previous target if any
                if current_target is not None:
                    stmt.add_into_target(
                        current_target, current_delim_var, current_count_var
                    )
                    current_delim_var = None
                    current_count_var = None
                token_stream.consume()
                current_target = tgt.value or ""
            else:
                break
            skip_whitespace(token_stream)

        # Flush last target
        if current_target is not None:
            stmt.add_into_target(current_target, current_delim_var, current_count_var)
