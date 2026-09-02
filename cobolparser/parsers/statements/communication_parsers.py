"""COBOL-85 Communication Module statement parsers.

SEND, RECEIVE, ENABLE, DISABLE and PURGE -- the message-control verbs of the
(now-obsolete) Communication Module, still present in the NIST COBOL-85
suite's ``CM`` programs and in older ANSI code bases.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import (
    DisableStatement,
    EnableStatement,
    PurgeStatement,
    ReceiveStatement,
    SendStatement,
)
from ._utils import (
    collect_clause_stmts,
    collect_operands,
    consume_end_keyword_and_period,
    consume_period,
    matches_word,
    peek_past_noise,
    peek_value_upper,
    skip_whitespace,
    token_column,
    token_location,
)


def _consume_one_operand(token_stream: ITokenStream) -> str | None:
    """Consume a single operand (data-name/literal) if one is next."""
    operands = collect_operands(token_stream, max_items=1)
    return operands[0] if operands else None


def _consume_cd_name(
    token_stream: ITokenStream, start_column: int | None
) -> str | None:
    operands = collect_operands(token_stream, max_items=1, start_column=start_column)
    return operands[0] if operands else None


class SendStatementParser(IStatementParser):
    """Parser for the SEND statement.

    Syntax::

        SEND cd-name [FROM identifier]
             [WITH {EGI | EMI | ESI | identifier}]
             [{BEFORE | AFTER} [ADVANCING] {identifier | integer [LINE|LINES]
                                            | PAGE | mnemonic-name}]
             [REPLACING LINE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "SEND", TokenType.SEND)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SendStatement:
        start = token_stream.consume()
        stmt = SendStatement(token_location(start))
        cd_name = _consume_cd_name(token_stream, token_column(start))
        if cd_name:
            stmt.set_cd_name(cd_name)

        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            word = peek_value_upper(token_stream)
            if word == "FROM":
                token_stream.consume()
                value = _consume_one_operand(token_stream)
                if value:
                    stmt.set_from_identifier(value)
            elif word == "WITH":
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and token.value and token.type != TokenType.PERIOD:
                    token_stream.consume()
                    stmt.set_indicator(token.value)
            elif word in ("BEFORE", "AFTER", "ADVANCING"):
                # BEFORE/AFTER is required by the standard, but a bare
                # ``ADVANCING PAGE`` is tolerated (mode left unset) rather
                # than dropped.
                if word == "ADVANCING":
                    word = ""
                else:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                if peek_value_upper(token_stream) == "ADVANCING":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                adv_value: str | None = None
                unit: str | None = None
                if peek_value_upper(token_stream) == "PAGE":
                    token_stream.consume()
                    adv_value = "PAGE"
                else:
                    adv_value = _consume_one_operand(token_stream)
                    skip_whitespace(token_stream)
                    if peek_value_upper(token_stream) in ("LINE", "LINES"):
                        unit = peek_value_upper(token_stream)
                        token_stream.consume()
                stmt.set_advancing(word, adv_value, unit)
            elif word == "REPLACING":
                token_stream.consume()
                skip_whitespace(token_stream)
                if peek_value_upper(token_stream) == "LINE":
                    token_stream.consume()
                stmt.replacing_line = True
            else:
                break

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ReceiveStatementParser(IStatementParser):
    """Parser for the RECEIVE statement.

    Syntax::

        RECEIVE cd-name {MESSAGE | SEGMENT} INTO identifier
                [NO DATA imperative-statement]
                [WITH DATA imperative-statement]
                [END-RECEIVE]
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "RECEIVE", TokenType.RECEIVE)

    @staticmethod
    def _at_keyword_pair(token_stream: ITokenStream, first: str, second: str) -> bool:
        if peek_value_upper(token_stream) != first:
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(lookahead and lookahead.value and lookahead.value.upper() == second)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ReceiveStatement:
        start = token_stream.consume()
        stmt = ReceiveStatement(token_location(start))
        cd_name = _consume_cd_name(token_stream, token_column(start))
        if cd_name:
            stmt.set_cd_name(cd_name)

        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) in ("MESSAGE", "SEGMENT"):
            stmt.set_mode(peek_value_upper(token_stream))
            token_stream.consume()

        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "INTO":
            token_stream.consume()
            target = _consume_one_operand(token_stream)
            if target:
                stmt.set_into(target)

        skip_whitespace(token_stream)
        if self._at_keyword_pair(token_stream, "NO", "DATA"):
            token_stream.consume()  # NO
            skip_whitespace(token_stream)
            token_stream.consume()  # DATA
            stmt.set_no_data_clause(
                collect_clause_stmts(token_stream, {"WITH", "END-RECEIVE"})
            )

        skip_whitespace(token_stream)
        if self._at_keyword_pair(token_stream, "WITH", "DATA"):
            token_stream.consume()  # WITH
            skip_whitespace(token_stream)
            token_stream.consume()  # DATA
            stmt.set_with_data_clause(
                collect_clause_stmts(token_stream, {"END-RECEIVE"})
            )

        consume_end_keyword_and_period(token_stream, "END-RECEIVE")
        return stmt


class _EnableDisableParserBase(IStatementParser):
    """Shared ENABLE/DISABLE grammar::

    {ENABLE | DISABLE} {INPUT [TERMINAL] | I-O TERMINAL | OUTPUT} cd-name
                       [WITH KEY {identifier | literal}]
    """

    _WORD = ""
    _TOKEN_TYPE: Any = None

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, self._WORD, self._TOKEN_TYPE)

    def _build(self, location: Any) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> Any:
        start = token_stream.consume()
        stmt = self._build(token_location(start))
        skip_whitespace(token_stream)

        mode_words: list[str] = []
        word = peek_value_upper(token_stream)
        if word in ("INPUT", "OUTPUT", "I-O"):
            mode_words.append(word)
            token_stream.consume()
            skip_whitespace(token_stream)
            if peek_value_upper(token_stream) == "TERMINAL":
                mode_words.append("TERMINAL")
                token_stream.consume()
        if mode_words:
            stmt.set_mode(" ".join(mode_words))

        cd_name = _consume_cd_name(token_stream, token_column(start))
        if cd_name:
            stmt.set_cd_name(cd_name)

        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "WITH":
            token_stream.consume()
            skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "KEY":
            token_stream.consume()
            key = _consume_one_operand(token_stream)
            if key:
                stmt.set_key(key)

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class EnableStatementParser(_EnableDisableParserBase):
    """Parser for the ENABLE statement."""

    _WORD = "ENABLE"
    _TOKEN_TYPE = TokenType.ENABLE

    def _build(self, location: Any) -> EnableStatement:
        return EnableStatement(location)


class DisableStatementParser(_EnableDisableParserBase):
    """Parser for the DISABLE statement."""

    _WORD = "DISABLE"
    _TOKEN_TYPE = TokenType.DISABLE

    def _build(self, location: Any) -> DisableStatement:
        return DisableStatement(location)


class PurgeStatementParser(IStatementParser):
    """Parser for ``PURGE cd-name``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        # PURGE has no dedicated TokenType; it lexes as a plain IDENTIFIER.
        return matches_word(token_stream, "PURGE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> PurgeStatement:
        start = token_stream.consume()
        stmt = PurgeStatement(token_location(start))
        cd_name = _consume_cd_name(token_stream, token_column(start))
        if cd_name:
            stmt.set_cd_name(cd_name)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


__all__ = [
    "SendStatementParser",
    "ReceiveStatementParser",
    "EnableStatementParser",
    "DisableStatementParser",
    "PurgeStatementParser",
]
