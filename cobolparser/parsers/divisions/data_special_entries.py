"""Special DATA DIVISION entries: level-88, level-66, and EXEC SQL blocks.

Collaborator of :class:`~cobolparser.parsers.divisions.data.DataDivisionParser`
for the entries that are not ordinary data-description items:

- level-88 condition names (``88 name VALUE literal ...``)
- level-66 RENAMES aliases (``66 name RENAMES a [THROUGH b].``)
- ``EXEC SQL ... END-EXEC`` blocks embedded in the data division
  (DCLGEN ``DECLARE TABLE``, ``INCLUDE SQLCA``/``SQLDA``)
"""

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import ConditionNameItem, RenamesItem
from cobolparser.models.sql_statements import ExecSQLStatement, parse_exec_sql
from cobolparser.parsers.statements._utils import collect_exec_sql_text


class SpecialEntryParser:
    """Parses level-88/level-66 entries and data-division EXEC SQL blocks."""

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
                # optional IS / ARE
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
            if t.type in (
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.FIGURATIVE_CONSTANT,
                TokenType.LEVEL_NUMBER,
            ):
                item.add_value(t.value)
                token_stream.consume()
            elif t.type in (TokenType.MINUS, TokenType.PLUS):
                sign_value = t.value
                next_token = token_stream.peek(1)
                if next_token and next_token.type in (
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    item.add_value(f"{sign_value}{next_token.value}")
                    token_stream.consume()
                    token_stream.consume()
                else:
                    break
            elif t.value == ",":
                token_stream.consume()
            elif t.type == TokenType.NEWLINE:
                token_stream.consume()
            elif t.value and t.value.upper() in ("THROUGH", "THRU"):
                token_stream.consume()
                end_token = token_stream.peek()
                if end_token and end_token.type in (
                    TokenType.STRING_LITERAL,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    item.add_value(f"THROUGH:{end_token.value}")
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
                        item.add_value(f"THROUGH:{end_token.value}{after_sign.value}")
                        token_stream.consume()
                        token_stream.consume()
            else:
                break

        self._parse_when_set_to_false(token_stream, item)

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
        t = token_stream.peek()
        if not t or not t.value or t.value.upper() != "WHEN":
            return
        offset = 1
        for keyword in ("SET", "TO"):
            nxt = token_stream.peek(offset)
            if nxt and nxt.value and nxt.value.upper() == keyword:
                offset += 1
        nxt = token_stream.peek(offset)
        if not nxt or not nxt.value or nxt.value.upper() != "FALSE":
            return
        offset += 1
        nxt = token_stream.peek(offset)
        if nxt and nxt.value and nxt.value.upper() == "IS":
            offset += 1
        literal = token_stream.peek(offset)
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
        item.false_value = f"{sign}{literal.value}"
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

        name_token = token_stream.peek()
        if not name_token or not name_token.value:
            return None
        name = name_token.value
        token_stream.consume()

        # Expect RENAMES keyword
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

        from_token = token_stream.peek()
        if not from_token or not from_token.value:
            return None
        renames_from = from_token.value
        token_stream.consume()

        renames_through = None
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() in ("THROUGH", "THRU"):
            token_stream.consume()
            thru_token = token_stream.peek()
            if thru_token and thru_token.value:
                renames_through = thru_token.value
                token_stream.consume()

        # Consume trailing period
        if not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.PERIOD:
                token_stream.consume()

        return RenamesItem(name, renames_from, location, renames_through)

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

        # Consume SQL keyword
        if not token_stream.is_empty():
            token_stream.consume()

        sql_text = collect_exec_sql_text(token_stream)
        if not sql_text.strip():
            return None
        return parse_exec_sql(sql_text, start_location)
