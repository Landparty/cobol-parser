"""ACCEPT statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOAcceptStatement
from ._utils import (
    is_statement_boundary,
    matches_keyword,
    skip_whitespace,
    token_location,
)


class AcceptStatementParser(IStatementParser):
    """Parser for ACCEPT statements.

    Syntax:
        ACCEPT identifier [FROM source]
        ACCEPT identifier FROM DATE/TIME/DAY/DAY-OF-WEEK
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.ACCEPT, "ACCEPT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOAcceptStatement:
        start = token_stream.consume()
        loc = token_location(start)
        factory = get_factory()
        stmt = factory.create(IOAcceptStatement, loc)
        if not isinstance(stmt, IOAcceptStatement):
            stmt = IOAcceptStatement(loc)
        skip_whitespace(token_stream)

        # Target identifier. Guard against a missing operand: if the next
        # token already starts a new statement (no operand was given), do not
        # consume it as the target — that silently destroyed the following
        # statement's verb.
        token = token_stream.peek()
        if (
            token
            and token.type not in (TokenType.PERIOD, None)
            and not is_statement_boundary(token)
        ):
            token_stream.consume()
            stmt.set_target(token.value or "")

        skip_whitespace(token_stream)

        # Optional FROM clause
        token = token_stream.peek()
        if token and (
            token.type == TokenType.FROM
            or (token.value and token.value.upper() == "FROM")
        ):
            token_stream.consume()
            skip_whitespace(token_stream)

            src = token_stream.peek()
            if src and src.type != TokenType.PERIOD and not is_statement_boundary(src):
                token_stream.consume()
                from_parts = [src.value or ""]
                skip_whitespace(token_stream)
                # FROM ENVIRONMENT names the environment variable with a
                # following literal or identifier; capture it as the
                # statement's environment_name (contract field) instead of
                # dropping it (string literal) or folding it into
                # from_source (identifier).
                if (src.value or "").upper() == "ENVIRONMENT":
                    name_tok = token_stream.peek()
                    if (
                        name_tok
                        and name_tok.value
                        and name_tok.type
                        in (TokenType.STRING_LITERAL, TokenType.IDENTIFIER)
                        and not is_statement_boundary(name_tok)
                    ):
                        token_stream.consume()
                        stmt.set_environment_name(name_tok.value.strip("\"'"))
                        skip_whitespace(token_stream)
                # Capture a trailing format phrase (e.g. ACCEPT x FROM DATE
                # YYYYMMDD / FROM DAY YYYYDDD). Without this the format word
                # was left in the stream and re-parsed as a phantom paragraph.
                nxt = token_stream.peek()
                while (
                    nxt
                    and nxt.type == TokenType.IDENTIFIER
                    and not is_statement_boundary(nxt)
                ):
                    token_stream.consume()
                    from_parts.append(nxt.value or "")
                    skip_whitespace(token_stream)
                    nxt = token_stream.peek()
                stmt.set_from(" ".join(p for p in from_parts if p))

        skip_whitespace(token_stream)

        # Extended ACCEPT clauses (M3b): AT positioning, SECURE, NO-ECHO,
        # TIMEOUT, AUTO-SKIP, UPPER, optionally introduced by WITH and in
        # any order/combination (grammar shapes taken from
        # examples/cobol/shamrice/accept.cbl and accept-secure.cbl -- only
        # the combined-numeric AT form is handled here since that's the
        # only form confirmed in real ACCEPT usage; DISPLAY additionally
        # supports the AT LINE/COLUMN keyword form since DISPLAY's own
        # corpus usage is also 100% numeric and that form is speculative
        # IBM-grammar coverage there, not corpus-driven).
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.WITH:
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type == TokenType.AT:
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.isdigit():
                    token_stream.consume()
                    line, column = divmod(int(num.value), 100)
                    stmt.set_position(line, column)
                skip_whitespace(token_stream)
                continue
            if token.type == TokenType.IDENTIFIER and token.value:
                upper_value = token.value.upper()
                if upper_value == "SECURE":
                    token_stream.consume()
                    stmt.set_secure(True)
                    skip_whitespace(token_stream)
                    continue
                if upper_value == "NO-ECHO":
                    token_stream.consume()
                    stmt.set_no_echo(True)
                    skip_whitespace(token_stream)
                    continue
                if upper_value == "AUTO-SKIP":
                    token_stream.consume()
                    stmt.set_auto_skip(True)
                    skip_whitespace(token_stream)
                    continue
                if upper_value == "UPPER":
                    token_stream.consume()
                    stmt.set_upper(True)
                    skip_whitespace(token_stream)
                    continue
                if upper_value == "TIMEOUT":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    num = token_stream.peek()
                    if num and num.value and num.value.isdigit():
                        token_stream.consume()
                        stmt.set_timeout(int(num.value))
                    skip_whitespace(token_stream)
                    continue
            # Unrecognized clause token: stop rather than silently
            # consuming (matches the rest of this file's convention).
            break

        # Consume period if present
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
