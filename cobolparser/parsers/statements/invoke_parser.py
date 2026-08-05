"""INVOKE statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import InvokeStatement
from ._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    consume_period,
    matches_keyword,
    skip_whitespace,
    token_location,
    token_value_upper,
)


class InvokeStatementParser(IStatementParser):
    """Parser for INVOKE statements (Object-Oriented COBOL method calls).

    Syntax:
        INVOKE object-identifier-1 {identifier-2 | literal-1}
            [USING [BY REFERENCE|BY CONTENT|BY VALUE] {identifier-3 | literal-2} ...]
            [RETURNING identifier-4]
        [END-INVOKE]

    ``object-identifier-1`` is commonly ``SELF``, ``SUPER``, or a data item
    declared ``USAGE OBJECT REFERENCE``; the method name is either a literal
    or an identifier holding the method name string.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.INVOKE, "INVOKE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InvokeStatement:
        start = token_stream.consume()
        stmt = InvokeStatement(token_location(start))
        skip_whitespace(token_stream)

        # Object identifier (SELF, SUPER, or an OBJECT REFERENCE data item).
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            stmt.set_object_name(token.value)
            token_stream.consume()
            skip_whitespace(token_stream)

        # Method name: literal or identifier holding the method name.
        token = token_stream.peek()
        if token and token.type == TokenType.STRING_LITERAL and token.value is not None:
            stmt.set_method_name(token.value.strip("\"'"), is_literal=True)
            token_stream.consume()
            skip_whitespace(token_stream)
        elif token and token.type == TokenType.IDENTIFIER and token.value:
            stmt.set_method_name(token.value, is_literal=False)
            token_stream.consume()
            skip_whitespace(token_stream)

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break

            value = token_value_upper(token)
            if value == "END-INVOKE":
                token_stream.consume()
                skip_whitespace(token_stream)
                consume_period(token_stream)
                break
            if value in SCOPE_TERMINATORS or (
                value in STATEMENT_KEYWORDS and value not in ("USING", "RETURNING")
            ):
                # A following statement with no trailing period must not be
                # swallowed (same boundary discipline as CALL's USING/
                # RETURNING loop).
                break

            if value == "USING" or token.type == TokenType.USING:
                token_stream.consume()
                skip_whitespace(token_stream)
                self._parse_using_clause(token_stream, stmt)
                continue

            if value == "RETURNING":
                token_stream.consume()
                skip_whitespace(token_stream)
                target = token_stream.peek()
                if target and target.type == TokenType.IDENTIFIER and target.value:
                    stmt.set_returning_target(target.value)
                    token_stream.consume()
                    skip_whitespace(token_stream)
                continue

            # Unrecognized token: stop rather than silently consume it.
            break

        return stmt

    def _parse_using_clause(
        self, token_stream: ITokenStream, stmt: InvokeStatement
    ) -> None:
        """Parse USING clause with optional BY REFERENCE|CONTENT|VALUE modifiers.

        A ``BY`` phrase governs every parameter that follows it until the
        next ``BY`` phrase, mirroring CALL's USING clause (see
        ``call_parser.py``).
        """
        passing_mode = "REFERENCE"
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if not token or token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.COMMA:
                token_stream.consume()
                continue

            value = token_value_upper(token)
            if value in ("RETURNING", "END-INVOKE") or value in SCOPE_TERMINATORS:
                break
            if value in STATEMENT_KEYWORDS and value != "USING":
                break

            if value == "BY" or token.type == TokenType.BY:
                token_stream.consume()
                skip_whitespace(token_stream)
                mode_token = token_stream.peek()
                mode_val = token_value_upper(mode_token) if mode_token else ""
                if mode_val in ("REFERENCE", "CONTENT", "VALUE"):
                    passing_mode = mode_val
                    token_stream.consume()
                    skip_whitespace(token_stream)
                continue

            if token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
                TokenType.FIGURATIVE_CONSTANT,
            ):
                stmt.add_using_parameter(token.value or "", passing_mode)
                token_stream.consume()
            else:
                break
