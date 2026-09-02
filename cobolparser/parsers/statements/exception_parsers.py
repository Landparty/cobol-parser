"""COBOL 2002 exception-handling and validation statement parsers.

``RAISE`` / ``RESUME`` (declarative exception handling) and ``VALIDATE``.
None of the three has a dedicated lexer TokenType; they all lex as plain
IDENTIFIERs, so each ``matches()`` checks the word itself.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import RaiseStatement, ResumeStatement, ValidateStatement
from ._utils import (
    collect_operands,
    consume_period,
    matches_word,
    peek_past_noise,
    peek_value_upper,
    skip_whitespace,
    token_column,
    token_location,
)


class RaiseStatementParser(IStatementParser):
    """Parser for ``RAISE EXCEPTION exception-name`` / ``RAISE identifier``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "RAISE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> RaiseStatement:
        start = token_stream.consume()
        stmt = RaiseStatement(token_location(start))
        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "EXCEPTION":
            token_stream.consume()
            skip_whitespace(token_stream)
            name = token_stream.peek()
            if name and name.value and name.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_target(name.value, raise_type="EXCEPTION")
        else:
            operands = collect_operands(
                token_stream, max_items=1, start_column=token_column(start)
            )
            if operands:
                stmt.set_target(operands[0], raise_type="IDENTIFIER")
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ResumeStatementParser(IStatementParser):
    """Parser for ``RESUME [AT] NEXT STATEMENT`` / ``RESUME [AT] procedure``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "RESUME")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ResumeStatement:
        start = token_stream.consume()
        stmt = ResumeStatement(token_location(start))
        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "AT":
            token_stream.consume()
            skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "NEXT":
            token_stream.consume()
            skip_whitespace(token_stream)
            if peek_value_upper(token_stream) == "STATEMENT":
                token_stream.consume()
            stmt.target = "NEXT STATEMENT"
        else:
            operands = collect_operands(token_stream, max_items=1)
            if operands:
                stmt.target = operands[0]
                stmt._add_unique_operand(operands[0])
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ValidateStatementParser(IStatementParser):
    """Parser for ``VALIDATE identifier-1 [identifier-2 ...]``.

    VALIDATE is not reserved by IBM Enterprise COBOL, so a paragraph named
    ``VALIDATE.`` is legal there; this only claims the word when a data-name
    follows it on the same sentence.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        if not matches_word(token_stream, "VALIDATE"):
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(
            lookahead
            and lookahead.type == TokenType.IDENTIFIER
            and lookahead.value
            and lookahead.value.upper() != "SECTION"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ValidateStatement:
        start = token_stream.consume()
        stmt = ValidateStatement(token_location(start))
        for target in collect_operands(token_stream, start_column=token_column(start)):
            stmt.add_target(target)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


__all__ = ["RaiseStatementParser", "ResumeStatementParser", "ValidateStatementParser"]
