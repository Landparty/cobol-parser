"""Special DATA DIVISION entries: level-88, level-66, and EXEC SQL blocks.

Collaborator of :class:`~cobolparser.parsers.divisions.data.DataDivisionParser`
for the entries that are not ordinary data-description items:

- level-88 condition names (``88 name VALUE literal ...``)
- level-66 RENAMES aliases (``66 name RENAMES a [THROUGH b].``)
- ``EXEC SQL ... END-EXEC`` blocks embedded in the data division
  (DCLGEN ``DECLARE TABLE``, ``INCLUDE SQLCA``/``SQLDA``)
"""

from typing import Any

from cobolparser._literals import quote_literal
from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import ConditionNameItem, RenamesItem
from cobolparser.models.sql_statements import ExecSQLStatement, parse_exec_sql
from cobolparser.parsers.divisions.data_clauses import data_entry_ending_header
from cobolparser.parsers.statements._utils import collect_exec_sql_text


def _condition_literal(token: Any) -> str:
    """A level-88 VALUE operand as recorded in ``ConditionNameItem.values``.

    Plain literals keep their decoded content (``'B1'`` is ``B1``). A typed
    literal keeps its prefixed source text (``X'C1'``), which
    ``generators.data.layout`` decodes: recording the content alone turned
    the one-byte hex literal ``X'C1'`` into the two-character value ``C1``.
    Same rule as the VALUE clause of an ordinary entry
    (``data_clauses.literal_source``).
    """
    if token.type == TokenType.STRING_LITERAL and token.raw_value:
        return str(token.raw_value)
    return str(token.value)


def _literal_kind(token: Any) -> str:
    """``ConditionNameItem.value_kinds`` entry for a VALUE operand token."""
    if token.type == TokenType.STRING_LITERAL:
        return "string"
    if token.type == TokenType.FIGURATIVE_CONSTANT:
        return "figurative"
    return "numeric"


def _skip_newlines(token_stream: ITokenStream) -> None:
    """Consume any NEWLINE tokens at the current position."""
    while not token_stream.is_empty():
        t = token_stream.peek()
        if t and t.type == TokenType.NEWLINE:
            token_stream.consume()
        else:
            break


class SpecialEntryParser:
    """Parses level-88/level-66 entries and data-division EXEC SQL blocks."""

    def __init__(self, parser: Any = None) -> None:
        """*parser*: the owning division parser, whose host receives
        warnings for dropped entry content."""
        self._parser = parser

    def _warn_dropped_condition_tokens(
        self, token_stream: ITokenStream, item: ConditionNameItem
    ) -> None:
        """Warn when a level-88 entry has content after its VALUE list that
        nothing parsed (``88 V VALUE 'A' FOO.``): the caller's scan skips it,
        and it used to vanish without a trace."""
        offset = 0
        token = token_stream.peek(offset)
        while token is not None and token.type == TokenType.NEWLINE:
            offset += 1
            token = token_stream.peek(offset)
        if token is None or token.type in (
            TokenType.PERIOD,
            TokenType.EOF,
            TokenType.LEVEL_NUMBER,
        ):
            return
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        header = data_entry_ending_header(token_stream, offset)
        if header:
            # The header is left for the section loop, which parses it;
            # only the period is missing (issue #559).
            if callable(add_warning):
                add_warning(
                    f"Data item '{item.name}' missing its terminating period: "
                    f"a period was assumed before '{header}'{where}"
                )
            return
        if offset and token.type == TokenType.IDENTIFIER:
            # A missing period followed by a new line: the next entry, not
            # content of this one.
            return
        if callable(add_warning):
            add_warning(
                f"Unparsed token '{token.value}'{where} in condition-name "
                f"'{item.name}' skipped: clause not fully supported; content "
                "dropped from the AST"
            )

    def parse_condition_name_item(
        self, token_stream: ITokenStream
    ) -> ConditionNameItem | None:
        """Parse a level-88 condition name item.

        Format: 88 condition-name VALUE [IS] literal {literal | THROUGH literal}...
        """
        level_token = token_stream.consume()  # consume '88'
        location = getattr(level_token, "location", None)
        if location is None:
            location = SourceLocation(0, 0)

        # The name may start the next line; a bare peek recorded the
        # NEWLINE token's "\n" as the name.
        _skip_newlines(token_stream)
        name_token = token_stream.peek()
        if not name_token or not name_token.value:
            return None
        name = name_token.value
        token_stream.consume()

        item = ConditionNameItem(name, location)

        # Skip tokens until VALUE keyword
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD or t.type == TokenType.LEVEL_NUMBER:
                break
            # ``VALUE [IS]`` and ``VALUES [ARE]`` are the same clause; only
            # the singular was recognised, so ``88 V VALUES 'A' 'B'.``
            # skipped every value as noise and recorded none.
            if t.value and t.value.upper() in ("VALUE", "VALUES"):
                token_stream.consume()
                # optional IS / ARE, possibly on the next line
                _skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() in ("IS", "ARE"):
                    token_stream.consume()
                break
            token_stream.consume()

        # Collect value literals. LEVEL_NUMBER is accepted as a numeric
        # literal (the lexer types 1-2 digit integers as LEVEL_NUMBER even
        # in value position); the item terminator is the PERIOD, so this
        # cannot swallow a following item's level number in well-formed
        # source. A MINUS/PLUS token followed by a numeric is a signed
        # literal.
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD:
                break
            if t.type == TokenType.FIGURATIVE_CONSTANT and t.value.upper() == "ALL":
                # ``VALUE ALL 'X'``: one value, the literal repeated to the
                # field's width. Stored the way a non-88 ``VALUE ALL`` is
                # (``ALL "X"`` / ``ALL SPACES``, see
                # ``data_clauses.parse_value_clause``); it was two values,
                # ``ALL`` and ``X``, and ``X`` read as a one-character value.
                token_stream.consume()
                operand = token_stream.peek()
                if operand is not None and operand.type == TokenType.STRING_LITERAL:
                    item.add_value(
                        kind="all",
                        value="ALL "
                        + (
                            operand.raw_value
                            if operand.raw_value
                            else quote_literal(operand.value)
                        ),
                    )
                    token_stream.consume()
                elif (
                    operand is not None
                    and operand.type == TokenType.FIGURATIVE_CONSTANT
                    and operand.value.upper() != "ALL"
                ):
                    item.add_value(f"ALL {operand.value}", "all")
                    token_stream.consume()
                else:
                    item.add_value(t.value)
            elif t.type in (
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.FIGURATIVE_CONSTANT,
                TokenType.LEVEL_NUMBER,
            ):
                item.add_value(_condition_literal(t), _literal_kind(t))
                token_stream.consume()
            elif t.type in (TokenType.MINUS, TokenType.PLUS):
                sign_value = t.value
                next_token = token_stream.peek(1)
                if next_token and next_token.type in (
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    item.add_value(f"{sign_value}{next_token.value}", "numeric")
                    token_stream.consume()
                    token_stream.consume()
                else:
                    break
            elif t.value == "," or t.type == TokenType.SEMICOLON:
                # A semicolon separates values exactly as a comma does
                # (``VALUES 'A', 'B'; 'C'``); it used to end the list and
                # silently drop every value after it.
                token_stream.consume()
            elif t.type == TokenType.NEWLINE:
                token_stream.consume()
            elif t.value and t.value.upper() in ("THROUGH", "THRU"):
                token_stream.consume()
                # The range end may start the next line (``VALUE 1 THRU`` /
                # ``5.``); peeking straight at the NEWLINE dropped the
                # THROUGH marker and degraded the range to its endpoints.
                _skip_newlines(token_stream)
                end_token = token_stream.peek()
                # A figurative end (``LOW-VALUE THRU HIGH-VALUE``) is a range
                # end like any literal; it used to fall through as a second
                # discrete value, dropping the THROUGH marker (#468).
                if end_token and (
                    end_token.type
                    in (
                        TokenType.STRING_LITERAL,
                        TokenType.NUMERIC_LITERAL,
                        TokenType.LEVEL_NUMBER,
                    )
                    or (
                        end_token.type == TokenType.FIGURATIVE_CONSTANT
                        and (end_token.value or "").upper() != "ALL"
                    )
                ):
                    item.add_value(
                        f"THROUGH:{_condition_literal(end_token)}",
                        _literal_kind(end_token),
                    )
                    token_stream.consume()
                elif end_token and end_token.type in (TokenType.MINUS, TokenType.PLUS):
                    # A signed range end (``VALUE -9 THRU -1``): the sign is
                    # its own token, exactly as in the value branch above.
                    # Without this lookahead the THROUGH marker was dropped
                    # and the range degraded to its two endpoints.
                    after_sign = token_stream.peek(1)
                    if after_sign and after_sign.type in (
                        TokenType.NUMERIC_LITERAL,
                        TokenType.LEVEL_NUMBER,
                    ):
                        item.add_value(
                            f"THROUGH:{end_token.value}{after_sign.value}", "numeric"
                        )
                        token_stream.consume()
                        token_stream.consume()
            else:
                break

        self._parse_when_set_to_false(token_stream, item)
        self._warn_dropped_condition_tokens(token_stream, item)

        # Consume trailing period
        if not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.PERIOD:
                token_stream.consume()

        return item

    @staticmethod
    def _parse_when_set_to_false(
        token_stream: ITokenStream, item: ConditionNameItem
    ) -> None:
        """``WHEN SET TO FALSE [IS] literal`` after a level-88 value list.

        IBM Enterprise COBOL: the literal is what ``SET condition-name TO
        FALSE`` stores in the conditional variable. It used to be skipped to
        the period with no trace. Recorded as ``item.false_value``; a sign
        token before a numeric literal is folded in as in the value list.
        """

        # Every word of the phrase may start a continuation line, so each
        # peek steps over NEWLINE tokens; a fixed-offset peek missed the
        # phrase (and the false value) whenever it was split across lines.
        def meaningful(offset: int) -> tuple[Any, int]:
            tok = token_stream.peek(offset)
            while tok is not None and tok.type == TokenType.NEWLINE:
                offset += 1
                tok = token_stream.peek(offset)
            return tok, offset

        t, offset = meaningful(0)
        if not t or not t.value or t.value.upper() not in ("WHEN", "FALSE"):
            return
        # ``WHEN SET TO`` are optional words (ISO 2002 / GnuCOBOL: ``88 V
        # VALUE 'Y' FALSE 'N'``); a bare FALSE phrase was dropped silently.
        if t.value.upper() == "WHEN":
            offset += 1
        for keyword in ("SET", "TO"):
            nxt, at = meaningful(offset)
            if nxt and nxt.value and nxt.value.upper() == keyword:
                offset = at + 1
        nxt, offset = meaningful(offset)
        if not nxt or not nxt.value or nxt.value.upper() != "FALSE":
            return
        offset += 1
        nxt, at = meaningful(offset)
        if nxt and nxt.value and nxt.value.upper() == "IS":
            offset = at + 1
        literal, offset = meaningful(offset)
        sign = ""
        if literal and literal.type in (TokenType.MINUS, TokenType.PLUS):
            after = token_stream.peek(offset + 1)
            if not after or after.type not in (
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
            ):
                return
            sign = literal.value
            offset += 1
            literal = after
        if not literal or literal.type not in (
            TokenType.STRING_LITERAL,
            TokenType.NUMERIC_LITERAL,
            TokenType.FIGURATIVE_CONSTANT,
            TokenType.LEVEL_NUMBER,
        ):
            return
        item.false_value = f"{sign}{_condition_literal(literal)}"
        for _ in range(offset + 1):
            token_stream.consume()

    def parse_renames_item(self, token_stream: ITokenStream) -> RenamesItem | None:
        """Parse a level-66 RENAMES item.

        Format: 66 data-name RENAMES data-name-1 [THROUGH|THRU data-name-2].
        """
        level_token = token_stream.consume()  # consume '66'
        location = getattr(level_token, "location", None)
        if location is None:
            location = SourceLocation(0, 0)

        # The name may start the next line; a bare peek recorded the
        # NEWLINE token's "\n" as the name.
        _skip_newlines(token_stream)
        name_token = token_stream.peek()
        if not name_token or not name_token.value:
            return None
        name = name_token.value
        token_stream.consume()

        # Expect RENAMES keyword (possibly on the next line)
        _skip_newlines(token_stream)
        renames_kw = token_stream.peek()
        if (
            not renames_kw
            or not renames_kw.value
            or renames_kw.value.upper() != "RENAMES"
        ):
            # Not a valid RENAMES — skip to period
            while not token_stream.is_empty():
                t = token_stream.peek()
                if not t or t.type in (TokenType.PERIOD, TokenType.LEVEL_NUMBER):
                    break
                token_stream.consume()
            return None
        token_stream.consume()  # consume RENAMES

        # Each operand may start a continuation line and may be qualified
        # (``RENAMES A OF REC THRU C OF REC``). Neither was allowed for: a
        # line break after RENAMES recorded the NEWLINE token's "\n" as the
        # renamed item, and a break or an ``OF`` qualifier before THRU lost
        # the THRU operand -- silently, the rest of the entry was discarded
        # by the section scan -- turning a range into a single item.
        _skip_newlines(token_stream)
        from_token = token_stream.peek()
        if (
            not from_token
            or not from_token.value
            or from_token.type == TokenType.PERIOD
        ):
            return None
        renames_from = from_token.value
        token_stream.consume()
        from_qualifiers = self._consume_qualifiers(token_stream)

        renames_through = None
        through_qualifiers: list[str] = []
        _skip_newlines(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() in ("THROUGH", "THRU"):
            token_stream.consume()
            _skip_newlines(token_stream)
            thru_token = token_stream.peek()
            if thru_token and thru_token.value and thru_token.type != TokenType.PERIOD:
                renames_through = thru_token.value
                token_stream.consume()
                through_qualifiers = self._consume_qualifiers(token_stream)

        _skip_newlines(token_stream)
        # Consume trailing period
        if not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.PERIOD:
                token_stream.consume()

        item = RenamesItem(name, renames_from, location, renames_through)
        item.renames_from_qualifiers = from_qualifiers
        item.renames_through_qualifiers = through_qualifiers
        return item

    def _consume_qualifiers(self, token_stream: ITokenStream) -> list[str]:
        """Consume an ``OF|IN data-name`` chain (line breaks allowed) and
        return the qualifier names, innermost first. ``OF``/``IN`` is only
        taken when a data-name follows it."""
        qualifiers: list[str] = []
        while True:
            offset = 0
            keyword = token_stream.peek(offset)
            while keyword is not None and keyword.type == TokenType.NEWLINE:
                offset += 1
                keyword = token_stream.peek(offset)
            if not (
                keyword and keyword.value and keyword.value.upper() in ("OF", "IN")
            ):
                return qualifiers
            offset += 1
            qualifier = token_stream.peek(offset)
            while qualifier is not None and qualifier.type == TokenType.NEWLINE:
                offset += 1
                qualifier = token_stream.peek(offset)
            if qualifier is None or qualifier.type != TokenType.IDENTIFIER:
                return qualifiers
            for _ in range(offset + 1):
                token_stream.consume()
            qualifiers.append(qualifier.value)

    def parse_exec_sql_in_data(
        self, token_stream: ITokenStream
    ) -> ExecSQLStatement | None:
        """Parse an EXEC SQL...END-EXEC block appearing in the Data Division.

        This handles DCLGEN-generated ``DECLARE TABLE`` blocks and
        ``INCLUDE SQLCA`` / ``INCLUDE SQLDA`` directives that are placed in
        the Working-Storage or Linkage sections.

        The token-to-SQL-text reconstruction is shared with the procedure-
        division EXEC SQL parser via :func:`collect_exec_sql_text`.

        Args:
            token_stream: Token stream positioned at the EXEC token.

        Returns:
            An :class:`ExecSQLStatement` (or subclass) node, or *None* if the
            block cannot be parsed.
        """
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Consume SQL keyword (possibly on the next line)
        _skip_newlines(token_stream)
        if not token_stream.is_empty():
            token_stream.consume()

        sql_text = collect_exec_sql_text(token_stream, sql=True)
        if not sql_text.strip():
            return None
        return parse_exec_sql(sql_text, start_location)
