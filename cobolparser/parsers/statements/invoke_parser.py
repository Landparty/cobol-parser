"""INVOKE statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import InvokeStatement
from ._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    consume_optional_qualifiers,
    consume_period,
    get_parse_context,
    matches_keyword,
    peek_past_noise,
    report_parse_error,
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
        parse_ctx = get_parse_context(token_stream)
        skip_whitespace(token_stream)

        # Object identifier (SELF, SUPER, or an OBJECT REFERENCE data item).
        # Its absence is a syntax error -- COBOL requires an object
        # reference between INVOKE and the method name -- mirroring how
        # MoveStatementParser reports a missing TO rather than returning a
        # plausible-but-empty node (see move_parser.py / parser.md's
        # "MOVE silently accepted malformed/incomplete input" audit).
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            token_stream.consume()
            # ``INVOKE WS-OBJ-TAB (I) "m"`` / ``INVOKE OBJ OF GRP "m"``
            stmt.set_object_name(consume_optional_qualifiers(token_stream, token.value))
            skip_whitespace(token_stream)
        else:
            report_parse_error(
                parse_ctx,
                "INVOKE statement requires an object identifier",
                stmt.location,
            )
            return stmt

        # Method name: literal or identifier holding the method name. Its
        # absence is likewise a syntax error, not a silently-empty INVOKE.
        token = token_stream.peek()
        if token and token.type == TokenType.STRING_LITERAL and token.value is not None:
            stmt.set_method_name(token.value.strip("\"'"), is_literal=True)
            token_stream.consume()
            skip_whitespace(token_stream)
        elif token and token.type == TokenType.IDENTIFIER and token.value:
            stmt.set_method_name(token.value, is_literal=False)
            token_stream.consume()
            skip_whitespace(token_stream)
        else:
            report_parse_error(
                parse_ctx,
                "INVOKE statement requires a method name (literal or identifier)",
                stmt.location,
            )
            return stmt

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
                    token_stream.consume()
                    # ``RETURNING WS-R (2)`` / ``RETURNING X OF GRP`` -- the
                    # subscript/qualifier is part of the target, not a
                    # stray token to be warned about and dropped.
                    stmt.set_returning_target(
                        consume_optional_qualifiers(token_stream, target.value)
                    )
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

            if token.type == TokenType.OMITTED:
                token_stream.consume()
                stmt.add_using_parameter("OMITTED", passing_mode)
                continue
            if token.type == TokenType.FIGURATIVE_CONSTANT:
                token_stream.consume()
                stmt.add_using_parameter((token.value or "").upper(), passing_mode)
                continue
            if token.type in (
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
            ):
                stmt.add_using_parameter(token.value or "", passing_mode)
                token_stream.consume()
                continue
            if token.type == TokenType.IDENTIFIER and token.value:
                token_stream.consume()
                name = token.value
                # ``LENGTH OF x`` / ``ADDRESS OF x`` are one argument, and a
                # subscript / OF-IN qualifier chain belongs to the argument
                # before it (the same forms CALL's USING folds). Before
                # 2026-09-28 the loop stopped at the ``(`` / ``OF``, the
                # rest of the statement -- RETURNING included -- was
                # warned about and dropped.
                if name.upper() in ("ADDRESS", "LENGTH"):
                    of_tok, of_idx = peek_past_noise(token_stream, 0)
                    if of_tok and token_value_upper(of_tok) == "OF":
                        name_tok, _ = peek_past_noise(token_stream, of_idx + 1)
                        if name_tok and name_tok.type == TokenType.IDENTIFIER:
                            skip_whitespace(token_stream)
                            token_stream.consume()  # OF
                            skip_whitespace(token_stream)
                            token_stream.consume()  # identifier
                            name = f"{name.upper()} OF {name_tok.value}"
                stmt.add_using_parameter(
                    consume_optional_qualifiers(token_stream, name), passing_mode
                )
                continue
            break
