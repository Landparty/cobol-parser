"""INITIALIZE and INSPECT statement parsers implementing IStatementParser."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import InitializeStatement, InspectStatement
from ._utils import (
    consume_period,
    is_statement_boundary,
    matches_keyword,
    skip_whitespace,
    token_location,
)
from ._utils import token_value_upper as _val

_REPLACING_CATEGORIES = frozenset(
    {
        "ALPHABETIC",
        "ALPHANUMERIC",
        "ALPHANUMERIC-EDITED",
        "NATIONAL",
        "NATIONAL-EDITED",
        "NUMERIC",
        "NUMERIC-EDITED",
        "DBCS",
        "EGCS",
    }
)


class InitializeStatementParser(IStatementParser):
    """Parser for INITIALIZE statements.

    Syntax:
        INITIALIZE identifier-1 [identifier-2 ...]
            [REPLACING {category} [DATA] BY {value} ...]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.INITIALIZE, "INITIALIZE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InitializeStatement:
        start = token_stream.consume()
        stmt = InitializeStatement(token_location(start))
        skip_whitespace(token_stream)

        # Collect target identifiers
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            if val in ("REPLACING", "WITH"):
                break
            if token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                token_stream.consume()
                stmt.add_target(token.value or "")
            else:
                break
            skip_whitespace(token_stream)

        # Optional WITH FILLER clause
        token = token_stream.peek()
        if token and _val(token) == "WITH":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "FILLER":
                token_stream.consume()
                stmt.with_filler = True
                skip_whitespace(token_stream)

        # Optional REPLACING clauses
        token = token_stream.peek()
        if token and _val(token) == "REPLACING":
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_replacing(token_stream, stmt)

        consume_period(token_stream)
        return stmt

    def _parse_replacing(self, ts: ITokenStream, stmt: InitializeStatement) -> None:
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                break
            if val in _REPLACING_CATEGORIES:
                category = val
                ts.consume()
                skip_whitespace(ts)
                # Optional DATA keyword
                nxt = ts.peek()
                if nxt and _val(nxt) == "DATA":
                    ts.consume()
                    skip_whitespace(ts)
                # Expect BY
                nxt = ts.peek()
                if nxt and _val(nxt) == "BY":
                    ts.consume()
                    skip_whitespace(ts)
                # Value
                nxt = ts.peek()
                if nxt and nxt.type != TokenType.PERIOD:
                    ts.consume()
                    stmt.add_replacing_clause(category, nxt.value or "")
                skip_whitespace(ts)
            else:
                break


class InspectStatementParser(IStatementParser):
    """Parser for INSPECT statements.

    Syntax:
        INSPECT identifier TALLYING ...
        INSPECT identifier REPLACING ...
        INSPECT identifier CONVERTING from TO to
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.INSPECT, "INSPECT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InspectStatement:
        start = token_stream.consume()
        stmt = InspectStatement(token_location(start))
        skip_whitespace(token_stream)

        # Target identifier
        token = token_stream.peek()
        if token and token.type not in (TokenType.PERIOD, None):
            token_stream.consume()
            stmt.set_target(token.value or "")
        skip_whitespace(token_stream)

        # Determine type
        token = token_stream.peek()
        if not token:
            return stmt

        val = _val(token)
        if val == "TALLYING":
            stmt.set_inspect_type("TALLYING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_tallying(token_stream, stmt)
        elif val == "REPLACING":
            stmt.set_inspect_type("REPLACING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_replacing(token_stream, stmt)
        elif val == "CONVERTING":
            stmt.set_inspect_type("CONVERTING")
            token_stream.consume()
            skip_whitespace(token_stream)
            self._parse_converting(token_stream, stmt)

        # Consume to period
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD:
                token_stream.consume()
                break
            # Check for REPLACING after TALLYING
            if _val(t) == "REPLACING" and stmt.inspect_type == "TALLYING":
                stmt.set_inspect_type("TALLYING_REPLACING")
                token_stream.consume()
                skip_whitespace(token_stream)
                self._parse_replacing(token_stream, stmt)
                continue
            # No trailing period before the next statement: stop rather than
            # swallow it (audit 2026-07-06 H2). Without this, the loop ran to
            # the next period and ate every intervening statement.
            if is_statement_boundary(t):
                break
            token_stream.consume()
            skip_whitespace(token_stream)

        return stmt

    def _parse_tallying(self, ts: ITokenStream, stmt: InspectStatement) -> None:
        """Parse TALLYING clauses: counter FOR {CHARACTERS|ALL|LEADING} [value] ..."""
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            val = _val(token)
            if val == "REPLACING":
                break

            if token.type != TokenType.IDENTIFIER:
                break

            # Counter name
            counter = token.value or ""
            ts.consume()
            skip_whitespace(ts)

            # Expect FOR
            nxt = ts.peek()
            if not nxt or _val(nxt) != "FOR":
                # Put counter in as a basic clause
                stmt.add_tallying_clause(counter, "CHARACTERS")
                break
            ts.consume()
            skip_whitespace(ts)

            # Parse FOR type
            nxt = ts.peek()
            if not nxt:
                break
            for_type = _val(nxt)
            if for_type in ("CHARACTERS", "ALL", "LEADING"):
                ts.consume()
                skip_whitespace(ts)

                value = None
                if for_type != "CHARACTERS":
                    v = ts.peek()
                    if v and v.type in (
                        TokenType.IDENTIFIER,
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                    ):
                        ts.consume()
                        value = v.value
                        skip_whitespace(ts)

                # Optional BEFORE/AFTER INITIAL
                before = None
                after = None
                p = ts.peek()
                pv = _val(p) if p else ""
                if pv in ("BEFORE", "AFTER"):
                    ba_type = pv
                    ts.consume()
                    skip_whitespace(ts)
                    p = ts.peek()
                    if p and _val(p) == "INITIAL":
                        ts.consume()
                        skip_whitespace(ts)
                    p = ts.peek()
                    if p and p.type in (
                        TokenType.IDENTIFIER,
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                    ):
                        ts.consume()
                        if ba_type == "BEFORE":
                            before = p.value
                        else:
                            after = p.value
                        skip_whitespace(ts)

                stmt.add_tallying_clause(counter, for_type, value, before, after)
            else:
                break

    def _parse_replacing(self, ts: ITokenStream, stmt: InspectStatement) -> None:
        """Parse REPLACING clauses."""
        while not ts.is_empty():
            token = ts.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            val = _val(token)
            if val in ("CHARACTERS", "ALL", "LEADING", "FIRST"):
                replace_type = val
                ts.consume()
                skip_whitespace(ts)

                from_value = ""
                if replace_type == "CHARACTERS":
                    from_value = "CHARACTERS"
                else:
                    v = ts.peek()
                    if v and v.type in (
                        TokenType.IDENTIFIER,
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                    ):
                        ts.consume()
                        from_value = v.value or ""
                        skip_whitespace(ts)

                # Expect BY
                nxt = ts.peek()
                to_value = ""
                if nxt and _val(nxt) == "BY":
                    ts.consume()
                    skip_whitespace(ts)
                    v = ts.peek()
                    if v and v.type in (
                        TokenType.IDENTIFIER,
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                    ):
                        ts.consume()
                        to_value = v.value or ""
                        skip_whitespace(ts)

                # Optional BEFORE/AFTER INITIAL
                before = None
                after = None
                p = ts.peek()
                pv = _val(p) if p else ""
                if pv in ("BEFORE", "AFTER"):
                    ba_type = pv
                    ts.consume()
                    skip_whitespace(ts)
                    p = ts.peek()
                    if p and _val(p) == "INITIAL":
                        ts.consume()
                        skip_whitespace(ts)
                    p = ts.peek()
                    if p and p.type in (
                        TokenType.IDENTIFIER,
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                    ):
                        ts.consume()
                        if ba_type == "BEFORE":
                            before = p.value
                        else:
                            after = p.value
                        skip_whitespace(ts)

                stmt.add_replacing_clause(
                    replace_type, from_value, to_value, before, after
                )
            else:
                break

    def _parse_converting(self, ts: ITokenStream, stmt: InspectStatement) -> None:
        """Parse CONVERTING from TO to."""
        token = ts.peek()
        if token and token.type in (
            TokenType.IDENTIFIER,
            TokenType.STRING_LITERAL,
        ):
            from_val = token.value or ""
            ts.consume()
            skip_whitespace(ts)

            nxt = ts.peek()
            if nxt and _val(nxt) == "TO":
                ts.consume()
                skip_whitespace(ts)
                to_tok = ts.peek()
                if to_tok and to_tok.type in (
                    TokenType.IDENTIFIER,
                    TokenType.STRING_LITERAL,
                ):
                    ts.consume()
                    stmt.set_converting(from_val, to_tok.value or "")
