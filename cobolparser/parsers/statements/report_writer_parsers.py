"""Report Writer control statement parsers: INITIATE, TERMINATE, SUPPRESS.

``GENERATE`` is parsed by :class:`~.simple_statement_parsers.
GenerateStatementParser`; these complete the Report Writer verb set.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import (
    InitiateStatement,
    SuppressStatement,
    TerminateStatement,
)
from ._utils import (
    collect_operands,
    consume_period,
    matches_word,
    peek_value_upper,
    skip_whitespace,
    token_column,
    token_location,
)


class InitiateStatementParser(IStatementParser):
    """Parser for ``INITIATE report-name-1 [report-name-2 ...]``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "INITIATE", TokenType.INITIATE)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> InitiateStatement:
        start = token_stream.consume()
        stmt = InitiateStatement(token_location(start))
        for name in collect_operands(token_stream, start_column=token_column(start)):
            stmt.add_report_name(name)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class TerminateStatementParser(IStatementParser):
    """Parser for ``TERMINATE report-name-1 [report-name-2 ...]``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "TERMINATE", TokenType.TERMINATE)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> TerminateStatement:
        start = token_stream.consume()
        stmt = TerminateStatement(token_location(start))
        for name in collect_operands(token_stream, start_column=token_column(start)):
            stmt.add_report_name(name)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class SuppressStatementParser(IStatementParser):
    """Parser for ``SUPPRESS [PRINTING]``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "SUPPRESS", TokenType.SUPPRESS)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SuppressStatement:
        start = token_stream.consume()
        stmt = SuppressStatement(token_location(start))
        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "PRINTING":
            token_stream.consume()
            stmt.printing = True
            skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


__all__ = [
    "InitiateStatementParser",
    "TerminateStatementParser",
    "SuppressStatementParser",
]
