"""SET statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import SetStatement
from ._utils import (
    SEPARATOR_TOKEN_TYPES,
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

    #: Set by ``_parse_action`` when the value was introduced by ENTRY.
    _entry_form: bool = False

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SET, "SET")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SetStatement:
        start = token_stream.consume()
        stmt = SetStatement(token_location(start))
        start_column = token_column(start)
        skip_whitespace(token_stream)

        targets, ended, address_of = self._collect_targets(token_stream, start_column)
        stmt.targets_are_address_of = address_of
        for target in targets:
            stmt.add_target(target)
        if ended:
            return stmt

        self._entry_form = False
        action = self._parse_action(token_stream)
        if action is not None:
            set_type, value, is_address_of = action
            stmt.set_set_type(set_type)
            if value is not None:
                stmt.set_value(value, is_address_of=is_address_of)
            if self._entry_form:
                stmt.set_metadata("value_is_entry", True)

        # COBOL lets one SET carry several target/value groups: ``SET SW-1
        # TO ON SW-2 TO OFF`` (NIST NC174A) or ``SET IX-1 TO 1 IX-2 TO 2``.
        # Previously only the first group was parsed and the rest was
        # reported as dropped "unparsed tokens".
        while self._starts_another_group(token_stream):
            group_targets, ended, _ = self._collect_targets(token_stream, start_column)
            if ended:
                stmt.add_group(group_targets, None, None, False)
                return stmt
            # Reset before each group's own _parse_action call, same as
            # before the first group above -- otherwise an earlier group's
            # `TO ENTRY 'X'` would leave this flag set for every later group
            # in the same SET statement, even one that never mentions ENTRY.
            self._entry_form = False
            group_action = self._parse_action(token_stream)
            if not group_targets and group_action is None:
                break
            if group_action is None:
                stmt.add_group(group_targets, None, None, False)
            else:
                set_type, value, is_address_of = group_action
                stmt.add_group(
                    group_targets,
                    set_type,
                    value,
                    is_address_of,
                    is_entry=self._entry_form,
                )

        skip_whitespace(token_stream)
        # Consume period
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt

    @staticmethod
    def _collect_targets(
        token_stream: ITokenStream, start_column: int | None
    ) -> tuple[list[str], bool, bool]:
        """Collect targets up to TO/UP/DOWN.

        Returns ``(targets, period_seen, address_of)`` -- the last True for
        the ``SET ADDRESS OF target ...`` form, where the targets are
        LINKAGE items being based rather than items being assigned.
        """
        targets: list[str] = []
        address_of = False
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return targets, True, address_of
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
            if token.type in SEPARATOR_TOKEN_TYPES:
                # A comma or semicolon between targets (`SET IX1, IX2 UP BY
                # 1.` / NIST NC245A's `SET INAME1; INAME2 TO 3.`) is a
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
                # above or this branch never reaches it). ADDRESS is
                # remembered: ``SET ADDRESS OF x TO p`` bases x on p.
                if val == "ADDRESS":
                    address_of = True
                elif val == "OF":
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
                    targets.append(
                        consume_optional_qualifiers(token_stream, token.value or "")
                    )
            else:
                break
            skip_whitespace(token_stream)
        return targets, False, address_of

    def _parse_action(
        self,
        token_stream: ITokenStream,
    ) -> tuple[str, str | None, bool] | None:
        """Parse ``TO value`` / ``TO TRUE|FALSE`` / ``TO ADDRESS OF x`` /
        ``UP BY value`` / ``DOWN BY value``.

        Returns ``(set_type, value, is_address_of)`` or ``None`` when no
        action keyword is next.
        """
        token = token_stream.peek()
        if not token:
            return None

        val = _val(token)
        if val == "TO":
            token_stream.consume()
            skip_whitespace(token_stream)
            v = token_stream.peek()
            if not v:
                return ("TO", None, False)
            vv = _val(v)
            if vv == "TRUE":
                token_stream.consume()
                return ("TRUE", None, False)
            if vv == "FALSE":
                token_stream.consume()
                return ("FALSE", None, False)
            if vv == "ADDRESS":
                # SET pointer-var TO ADDRESS OF identifier -- ADDRESS OF
                # is a prefix on the *value* here (mirrors the target-side
                # ADDRESS OF handling in the target-collection loop above).
                token_stream.consume()
                skip_whitespace(token_stream)
                of_token = token_stream.peek()
                if of_token and _val(of_token) == "OF":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                v2 = token_stream.peek()
                if v2 and v2.type != TokenType.PERIOD:
                    return ("TO", _consume_set_value(token_stream), True)
                return ("TO", None, True)
            if vv == "ENTRY":
                # SET procedure-pointer TO ENTRY literal|identifier. The
                # value recorded is the entry name; ``value_is_entry``
                # metadata marks the form (previously the literal was
                # dropped as an unparsed trailing token).
                token_stream.consume()
                skip_whitespace(token_stream)
                self._entry_form = True
                v2 = token_stream.peek()
                if v2 and v2.type != TokenType.PERIOD:
                    return ("TO", _consume_set_value(token_stream), False)
                return ("TO", None, False)
            if v.type != TokenType.PERIOD:
                return ("TO", _consume_set_value(token_stream), False)
            return ("TO", None, False)
        if val in ("UP", "DOWN"):
            token_stream.consume()
            skip_whitespace(token_stream)
            nxt = token_stream.peek()
            if nxt and _val(nxt) == "BY":
                token_stream.consume()
                skip_whitespace(token_stream)
            set_type = "UP_BY" if val == "UP" else "DOWN_BY"
            v = token_stream.peek()
            if v and v.type != TokenType.PERIOD:
                return (set_type, _consume_set_value(token_stream), False)
            return (set_type, None, False)
        return None

    @staticmethod
    def _starts_another_group(token_stream: ITokenStream) -> bool:
        """True if the tokens ahead form another ``targets TO/UP/DOWN ...``
        group: an identifier now, and TO/UP/DOWN before the next period or
        statement boundary."""
        skip_whitespace(token_stream)
        first = token_stream.peek()
        if (
            not first
            or first.type != TokenType.IDENTIFIER
            or is_statement_boundary(first)
            or looks_like_paragraph_boundary(token_stream)
        ):
            return False
        idx = 0
        while idx < 24:
            look = token_stream.peek(idx)
            if look is None:
                return False
            if look.type in (
                TokenType.WHITESPACE,
                TokenType.NEWLINE,
                TokenType.COMMENT,
                TokenType.CONTINUATION,
                TokenType.COMMA,
                TokenType.SEMICOLON,
                TokenType.OF,
                TokenType.IN,
                TokenType.LEFT_PAREN,
                TokenType.RIGHT_PAREN,
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
            ):
                idx += 1
                continue
            word = _val(look)
            if word in ("TO", "UP", "DOWN"):
                return True
            if look.type == TokenType.PERIOD or (
                look.type == TokenType.IDENTIFIER and is_statement_boundary(look)
            ):
                return False
            if look.type != TokenType.IDENTIFIER:
                return False
            idx += 1
        return False
