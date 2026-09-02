"""Legacy, dialect, and compiler-directing statement parsers.

* OS/VS COBOL: ``EXHIBIT``, ``EXAMINE``, ``TRANSFORM`` (superseded by
  DISPLAY / INSPECT, but still found in code migrated to Enterprise COBOL).
* IBM compiler-directing / debugging statements: ``READY TRACE`` /
  ``RESET TRACE``, ``SERVICE LABEL`` / ``SERVICE RELOAD``, ``ENTER``,
  ``TITLE``.
* COBOL-74 ``NOTE`` and Micro Focus ``CHAIN``.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import (
    ChainStatement,
    EnterStatement,
    ExamineStatement,
    ExhibitStatement,
    NoteStatement,
    ServiceStatement,
    TitleStatement,
    TraceStatement,
    TransformStatement,
)
from ._utils import (
    collect_operands,
    consume_period,
    is_statement_boundary,
    matches_word,
    peek_past_noise,
    peek_token,
    peek_value_upper,
    skip_whitespace,
    token_column,
    token_location,
)


def _consume_one_operand(token_stream: ITokenStream) -> str | None:
    operands = collect_operands(token_stream, max_items=1)
    return operands[0] if operands else None


class ExhibitStatementParser(IStatementParser):
    """Parser for ``EXHIBIT [NAMED | CHANGED NAMED | CHANGED] item ...``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "EXHIBIT", TokenType.EXHIBIT)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ExhibitStatement:
        start = token_stream.consume()
        stmt = ExhibitStatement(token_location(start))
        mode_words: list[str] = []
        while True:
            skip_whitespace(token_stream)
            word = peek_value_upper(token_stream)
            if word in ("NAMED", "CHANGED") and word not in mode_words:
                mode_words.append(word)
                token_stream.consume()
                continue
            break
        if mode_words:
            stmt.set_mode(" ".join(mode_words))
        for item in collect_operands(token_stream, start_column=token_column(start)):
            stmt.add_item(item)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ExamineStatementParser(IStatementParser):
    """Parser for the OS/VS COBOL EXAMINE statement.

    Syntax::

        EXAMINE identifier TALLYING {ALL | LEADING | UNTIL FIRST} literal
                                    [REPLACING BY literal]
        EXAMINE identifier REPLACING {ALL | LEADING | FIRST | UNTIL FIRST}
                                     literal BY literal
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "EXAMINE", TokenType.EXAMINE)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ExamineStatement:
        start = token_stream.consume()
        stmt = ExamineStatement(token_location(start))
        target = _consume_one_operand(token_stream)
        if target:
            stmt.set_target(target)

        skip_whitespace(token_stream)
        action = peek_value_upper(token_stream)
        if action in ("TALLYING", "REPLACING"):
            stmt.action = action
            token_stream.consume()
            skip_whitespace(token_stream)
            mode = peek_value_upper(token_stream)
            if mode in ("ALL", "LEADING", "FIRST"):
                stmt.mode = mode
                token_stream.consume()
            elif mode == "UNTIL":
                token_stream.consume()
                skip_whitespace(token_stream)
                if peek_value_upper(token_stream) == "FIRST":
                    token_stream.consume()
                stmt.mode = "UNTIL FIRST"
            stmt.search_value = _consume_one_operand(token_stream)

            skip_whitespace(token_stream)
            if peek_value_upper(token_stream) == "REPLACING":
                token_stream.consume()
                skip_whitespace(token_stream)
            if peek_value_upper(token_stream) == "BY":
                token_stream.consume()
                stmt.replacing_value = _consume_one_operand(token_stream)

        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class TransformStatementParser(IStatementParser):
    """Parser for ``TRANSFORM identifier CHARACTERS FROM x TO y``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "TRANSFORM", TokenType.TRANSFORM)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> TransformStatement:
        start = token_stream.consume()
        stmt = TransformStatement(token_location(start))
        target = _consume_one_operand(token_stream)
        if target:
            stmt.set_target(target)
        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "CHARACTERS":
            token_stream.consume()
            skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "FROM":
            token_stream.consume()
            stmt.from_value = _consume_one_operand(token_stream)
            skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "TO":
            token_stream.consume()
            stmt.to_value = _consume_one_operand(token_stream)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class EnterStatementParser(IStatementParser):
    """Parser for ``ENTER language-name [routine-name]``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "ENTER", TokenType.ENTER)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> EnterStatement:
        start = token_stream.consume()
        stmt = EnterStatement(token_location(start))
        # The language name is any word (``ENTER LINKAGE`` -- LINKAGE lexes
        # as a section keyword, not an IDENTIFIER), so read up to two bare
        # words by value rather than through collect_operands.
        words: list[str] = []
        while len(words) < 2:
            skip_whitespace(token_stream)
            token = peek_token(token_stream)
            if (
                token is None
                or not token.value
                or token.type == TokenType.PERIOD
                or is_statement_boundary(token)
            ):
                break
            token_stream.consume()
            words.append(token.value)
        if words:
            stmt.language = words[0]
        if len(words) > 1:
            stmt.routine = words[1]
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class NoteStatementParser(IStatementParser):
    """Parser for the COBOL-74 ``NOTE`` comment statement.

    Everything up to and including the next sentence period is comment text
    (COBOL-74 4.2.3: "the NOTE statement allows the programmer to write
    commentary which will be produced on the listing but not compiled").
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "NOTE", TokenType.NOTE)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> NoteStatement:
        start = token_stream.consume()
        stmt = NoteStatement(token_location(start))
        parts: list[str] = []
        at_line_start = False
        while not token_stream.is_empty():
            token = peek_token(token_stream)
            if token is None or token.type == TokenType.EOF:
                break
            # A NOTE with no terminating period must not swallow the rest of
            # the program: a verb at the start of a following line ends it.
            if at_line_start and is_statement_boundary(token):
                break
            token_stream.consume()
            if token.type == TokenType.PERIOD:
                break
            if token.type in (
                TokenType.WHITESPACE,
                TokenType.NEWLINE,
                TokenType.CONTINUATION,
                TokenType.COMMENT,
            ):
                at_line_start = token.type == TokenType.NEWLINE or at_line_start
                continue
            at_line_start = False
            parts.append(token.raw_value or token.value or "")
        stmt.text = " ".join(parts)
        return stmt


class ChainStatementParser(IStatementParser):
    """Parser for the Micro Focus ``CHAIN {literal | identifier} [USING ...]``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_word(token_stream, "CHAIN", TokenType.CHAIN)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ChainStatement:
        start = token_stream.consume()
        stmt = ChainStatement(token_location(start))
        skip_whitespace(token_stream)
        token = peek_token(token_stream)
        is_dynamic = bool(token and token.type == TokenType.IDENTIFIER)
        program = _consume_one_operand(token_stream)
        if program:
            stmt.set_program(program, is_dynamic=is_dynamic)
        skip_whitespace(token_stream)
        if peek_value_upper(token_stream) == "USING":
            token_stream.consume()
            for param in collect_operands(
                token_stream, start_column=token_column(start)
            ):
                stmt.add_using_parameter(param)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class TraceStatementParser(IStatementParser):
    """Parser for IBM ``READY TRACE`` / ``RESET TRACE``.

    Only matches when the verb is actually followed by ``TRACE``: ``RESET``
    also appears inside Report Writer ``SUM ... RESET ON`` clauses, and
    neither word alone is a statement.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        if not (
            matches_word(token_stream, "READY", TokenType.READY)
            or matches_word(token_stream, "RESET", TokenType.RESET)
        ):
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(
            lookahead and lookahead.value and lookahead.value.upper() == "TRACE"
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> TraceStatement:
        start = token_stream.consume()
        stmt = TraceStatement(token_location(start), (start.value or "").upper())
        skip_whitespace(token_stream)
        token_stream.consume()  # TRACE
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class ServiceStatementParser(IStatementParser):
    """Parser for IBM ``SERVICE LABEL`` and ``SERVICE RELOAD identifier``."""

    def matches(self, token_stream: ITokenStream) -> bool:
        if not matches_word(token_stream, "SERVICE", TokenType.SERVICE):
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(
            lookahead
            and lookahead.value
            and lookahead.value.upper() in ("LABEL", "RELOAD")
        )

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ServiceStatement:
        start = token_stream.consume()
        stmt = ServiceStatement(token_location(start))
        skip_whitespace(token_stream)
        kind_token = token_stream.consume()  # LABEL | RELOAD
        stmt.kind = (kind_token.value or "").upper() if kind_token else None
        if stmt.kind == "RELOAD":
            stmt.operand = _consume_one_operand(token_stream)
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


class TitleStatementParser(IStatementParser):
    """Parser for the IBM ``TITLE literal`` compiler-directing statement.

    TITLE has no dedicated TokenType and is not reserved by every dialect, so
    this only claims the word when a string literal follows it -- a paragraph
    or data item named TITLE is left alone.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        if not matches_word(token_stream, "TITLE"):
            return False
        lookahead, _ = peek_past_noise(token_stream, 1)
        return bool(lookahead and lookahead.type == TokenType.STRING_LITERAL)

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> TitleStatement:
        start = token_stream.consume()
        stmt = TitleStatement(token_location(start))
        skip_whitespace(token_stream)
        literal = token_stream.consume()
        stmt.title = literal.value if literal else None
        skip_whitespace(token_stream)
        consume_period(token_stream)
        return stmt


__all__ = [
    "ExhibitStatementParser",
    "ExamineStatementParser",
    "TransformStatementParser",
    "EnterStatementParser",
    "NoteStatementParser",
    "ChainStatementParser",
    "TraceStatementParser",
    "ServiceStatementParser",
    "TitleStatementParser",
]
