"""SET statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import SetStatement
from ._utils import (
    consume_optional_qualifiers,
    consume_value_operand,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    skip_whitespace,
    token_column,
    token_location,
    warn_paragraph_boundary_swallowed,
)
from ._utils import token_value_upper as _val


def _strip_period(value: str) -> str:
    """Strip trailing period from numeric literal values like '1.'."""
    if value.endswith(".") and len(value) > 1:
        return value[:-1]
    return value


def _consume_set_value(token_stream: ITokenStream) -> str:
    """Consume one SET value operand, returning the period-stripped string.

    Shared by all four of SET's value-reading forms (``TO``, ``TO ADDRESS
    OF``, ``UP BY``, ``DOWN BY``). The heavy lifting -- a sign-prefixed
    numeric (``SET IDX DOWN BY -1``), a trailing subscript group
    (``SET IDX TO TABLE-ITEM(5)``), and an ``OF``/``IN`` qualifier chain
    (``SET IDX TO WS-VAL OF WS-CTL``, previously stranded in the stream
    and dropped as unparsed tokens) -- is the shared
    :func:`~._utils.consume_value_operand`, the same helper PERFORM
    VARYING/AFTER's FROM/BY values use.
    """
    return _strip_period(consume_value_operand(token_stream) or "")


class SetStatementParser(IStatementParser):
    """Parser for SET statements.

    Syntax:
        SET identifier-1 [identifier-2 ...] TO value
        SET identifier UP BY value
        SET identifier DOWN BY value
        SET condition-name TO TRUE
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SET, "SET")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SetStatement:
        start = token_stream.consume()
        stmt = SetStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        # Collect targets until TO/UP/DOWN/period
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt
            if val in ("TO", "UP", "DOWN"):
                break
            # A following statement's verb that lexes as a plain IDENTIFIER
            # (e.g. PURGE/RAISE/RESUME have no dedicated TokenType) must not
            # be folded into the target list when SET has no trailing period.
            if token.type == TokenType.IDENTIFIER and is_statement_boundary(token):
                break
            # A missing period on this SET followed by what looks like the
            # next paragraph/section header (H9): stop instead of folding it
            # into the target list. Disambiguated by indentation (Area A vs
            # Area B) so a target that merely wraps onto its own
            # continuation line -- legitimate for any target in the list, not
            # just the first -- isn't misread as a boundary and dropped.
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(token_stream)
                break
            if token.type == TokenType.COMMA:
                # A comma between targets (e.g. `SET IX1, IX2 UP BY 1.`) is a
                # separator, not a terminator -- skip it and keep collecting
                # targets, mirroring the MOVE parser's target-list handling.
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.OF,
            ):
                token_stream.consume()
                # Skip ADDRESS and OF keywords (OF lexes as its own dedicated
                # TokenType, not IDENTIFIER, so it must be listed explicitly
                # above or this branch never reaches it).
                if val in ("ADDRESS", "OF"):
                    pass
                else:
                    # A trailing `(subscript[, subscript]...)` group (e.g.
                    # a table reference like `TBL-ITEM(1)`) and an OF/IN
                    # qualifier chain (`SET FLAG-ON OF WS-REC TO TRUE`)
                    # must be folded into the target string, matching MOVE/
                    # ADD/SUBTRACT/COMPUTE targets -- without this, a
                    # subscript broke the rest of the statement as
                    # "Unparsed tokens", and a qualifier's name looped back
                    # around as a spurious separate target with the OF
                    # silently discarded.
                    # Unconditional add (matching the pre-existing
                    # `stmt.add_target(token.value or "")`) -- an empty
                    # target_name is still recorded rather than silently
                    # dropped.
                    stmt.add_target(
                        consume_optional_qualifiers(token_stream, token.value or "")
                    )
            else:
                break
            skip_whitespace(token_stream)

        # Parse the action: TO, UP BY, DOWN BY
        token = token_stream.peek()
        if not token:
            return stmt

        val = _val(token)
        if val == "TO":
            token_stream.consume()
            skip_whitespace(token_stream)
            v = token_stream.peek()
            if v:
                vv = _val(v)
                if vv == "TRUE":
                    stmt.set_set_type("TRUE")
                    token_stream.consume()
                elif vv == "FALSE":
                    stmt.set_set_type("FALSE")
                    token_stream.consume()
                elif vv == "ADDRESS":
                    # SET pointer-var TO ADDRESS OF identifier -- ADDRESS OF
                    # is a prefix on the *value* here (mirrors the target-side
                    # ADDRESS OF handling in the target-collection loop above).
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    of_token = token_stream.peek()
                    if of_token and _val(of_token) == "OF":
                        token_stream.consume()
                        skip_whitespace(token_stream)
                    stmt.set_set_type("TO")
                    v2 = token_stream.peek()
                    if v2 and v2.type != TokenType.PERIOD:
                        stmt.set_value(
                            _consume_set_value(token_stream),
                            is_address_of=True,
                        )
                elif v.type != TokenType.PERIOD:
                    stmt.set_set_type("TO")
                    stmt.set_value(_consume_set_value(token_stream))
        elif val == "UP":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "BY":
                token_stream.consume()
                skip_whitespace(token_stream)
            stmt.set_set_type("UP_BY")
            v = token_stream.peek()
            if v and v.type != TokenType.PERIOD:
                stmt.set_value(_consume_set_value(token_stream))
        elif val == "DOWN":
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "BY":
                token_stream.consume()
                skip_whitespace(token_stream)
            stmt.set_set_type("DOWN_BY")
            v = token_stream.peek()
            if v and v.type != TokenType.PERIOD:
                stmt.set_value(_consume_set_value(token_stream))

        skip_whitespace(token_stream)
        # Consume period
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
