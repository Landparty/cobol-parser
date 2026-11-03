"""Display statement parser implementing IStatementParser interface.

Refactored to implement the IStatementParser interface for registry-based
statement parsing in the extracted statement parser architecture.

Uses ASTNodeFactory for validated node creation.
"""

from typing import Any

from ..._literals import quote_literal
from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import DisplayStatement
from ._utils import (
    consume_optional_qualifiers,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    peek_past_noise,
    skip_whitespace,
    token_column,
    warn_paragraph_boundary_swallowed,
)

# Screen-handling phrases of a DISPLAY (IBM, X/Open and GnuCOBOL screen
# I/O). The first set takes an operand (`LINE 3`, `FOREGROUND-COLOR IS 2`),
# the second takes none, the third takes one keyword (`BLANK SCREEN`).
_SCREEN_WORDS_WITH_OPERAND = frozenset(
    {
        "LINE",
        "COL",
        "COLUMN",
        "POSITION",
        "POS",
        "FOREGROUND-COLOR",
        "FOREGROUND-COLOUR",
        "BACKGROUND-COLOR",
        "BACKGROUND-COLOUR",
        "COLOR",
        "COLOUR",
        "SIZE",
        "CONTROL",
        "CURSOR",
    }
)
_SCREEN_WORDS = frozenset(
    {
        "HIGHLIGHT",
        "LOWLIGHT",
        "REVERSE-VIDEO",
        "REVERSED",
        "BLINK",
        "UNDERLINE",
        "OVERLINE",
        "LEFTLINE",
        "BELL",
        "BEEP",
        "NO-ECHO",
        "SECURE",
        "CONVERSION",
        "UPDATE",
        "AUTO",
        "AUTO-SKIP",
        "FULL",
        "REQUIRED",
        "PROMPT",
        "TAB",
    }
)
_SCREEN_WORDS_WITH_KEYWORD = {
    "BLANK": frozenset({"SCREEN", "LINE"}),
    "ERASE": frozenset({"EOL", "EOS", "SCREEN", "LINE"}),
}
_OPERAND_TYPES = (
    TokenType.NUMERIC_LITERAL,
    TokenType.LEVEL_NUMBER,
    TokenType.IDENTIFIER,
)


class DisplayStatementParser(IStatementParser):
    """Parser for DISPLAY statements.

    Implements IStatementParser for registry-based dispatch. Parses DISPLAY
    statements in PROCEDURE DIVISION, collecting output items and optional
    output device specifications.

    Example COBOL:
        DISPLAY "Hello World".
        DISPLAY item-1 UPON CONSOLE.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.DISPLAY, "DISPLAY")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> DisplayStatement:
        """Parse a DISPLAY statement from the token stream.

        Consumes tokens starting from DISPLAY keyword through statement terminator
        (period or END-DISPLAY), building a DisplayStatement AST node.

        Args:
            token_stream: The token stream to parse from

        Returns:
            DisplayStatement AST node

        Raises:
            UnexpectedEndOfInput: If stream ends unexpectedly
            ParseError: If invalid DISPLAY syntax encountered
        """
        # Consume DISPLAY keyword
        start_token = token_stream.consume()
        start_location = start_token.location if start_token else SourceLocation(0, 0)
        start_column = token_column(start_token)

        # Use factory for validated node creation
        factory = get_factory()
        stmt = factory.create(DisplayStatement, start_location)

        # Type guard: ensure stmt is a DisplayStatement
        if not isinstance(stmt, DisplayStatement):
            stmt = DisplayStatement(start_location)

        # Skip whitespace
        skip_whitespace(token_stream)

        # Parse display items and optional output device
        while not token_stream.is_empty():
            token = token_stream.peek()

            if not token:
                break

            # Check for period (statement terminator)
            if token.type == TokenType.PERIOD:
                token_stream.consume()  # Consume period
                break

            # Check for END-DISPLAY (explicit terminator)
            if self._is_keyword(token, "END-DISPLAY"):
                token_stream.consume()
                break

            # Check for UPON (output device specification)
            if self._is_keyword(token, "UPON"):
                token_stream.consume()  # Consume UPON
                skip_whitespace(token_stream)

                device_token = token_stream.peek()
                if device_token:
                    token_stream.consume()
                    stmt.set_output_device(device_token.value or "")
                # Keep looping instead of breaking: clauses may legally
                # follow the device name (`UPON CONSOLE WITH NO ADVANCING`),
                # and the sentence period must be consumed like the non-UPON
                # path does -- breaking here dropped the trailing clause and
                # left the period in the stream, which the procedure parser
                # then misread as an empty paragraph named ".".
                skip_whitespace(token_stream)
                continue

            # Check for AT LINE/COLUMN positioning (M3a)
            if token.type == TokenType.AT:
                start = len(stmt.screen_phrases)
                self._parse_at_clause(token_stream, stmt)
                if len(stmt.screen_phrases) == start:
                    stmt.screen_phrases.append("AT")
                skip_whitespace(token_stream)
                continue

            # Screen phrases outside AT: `LINE 3 COL 5`, `HIGHLIGHT`, ...
            # Without WITH, a bare attribute word is one only once the
            # statement is already a screen DISPLAY: `DISPLAY BELL` shows
            # the SYMBOLIC CHARACTER BELL (issue #519's sample).
            if self._parse_screen_phrase(
                token_stream,
                stmt,
                bare_attributes=bool(stmt.screen_phrases),
                operands=bool(stmt.display_items),
            ):
                skip_whitespace(token_stream)
                continue

            # Check for WITH NO ADVANCING (M2) -- WITH is an optional
            # filler word; NO ADVANCING is the fixed phrase. Neither
            # currently introduces any other DISPLAY clause, so once we
            # commit to consuming WITH we must find NO ADVANCING or stop
            # (matching this loop's "unknown token -> stop" convention).
            if token.type in (TokenType.WITH, TokenType.NO):
                if token.type == TokenType.WITH:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    # `WITH HIGHLIGHT BLANK SCREEN ...`: screen phrases.
                    if self._parse_screen_phrase(token_stream, stmt):
                        skip_whitespace(token_stream)
                        continue
                if token and token.type == TokenType.NO:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    adv_token = token_stream.peek()
                    if adv_token and adv_token.type == TokenType.ADVANCING:
                        token_stream.consume()
                        stmt.set_no_advancing(True)
                        skip_whitespace(token_stream)
                        continue
                break

            # Scope terminators of an enclosing statement (e.g. END-READ when
            # this DISPLAY is an AT END clause body) end the item list. Also
            # stop at a following statement's verb when it lexes as a plain
            # IDENTIFIER (e.g. PURGE/RAISE/RESUME have no dedicated TokenType,
            # so they are otherwise indistinguishable from a data-name item) —
            # without this, `DISPLAY X` immediately followed by an un-punctuated
            # `PURGE Y` silently folded PURGE/Y into the display item list.
            if token.type == TokenType.IDENTIFIER and is_statement_boundary(token):
                break

            # A missing period on this DISPLAY followed by what looks like
            # the next paragraph/section header (H9): stop instead of
            # folding it into the item list. Disambiguated by indentation
            # (Area A vs Area B) so an item that merely wraps onto its own
            # continuation line -- legitimate for any item in the list, not
            # just the first -- isn't misread as a boundary and dropped.
            if (
                token.type == TokenType.IDENTIFIER
                and looks_like_paragraph_boundary(token_stream)
                and looks_dedented_relative_to(token_stream, start_column)
            ):
                warn_paragraph_boundary_swallowed(token_stream)
                break

            if token.type == TokenType.COMMA:
                # A comma between display items (e.g. `DISPLAY WS-A, WS-B.`)
                # is a separator, not a terminator -- skip it and keep
                # collecting items, mirroring the MOVE/SET parsers'
                # target-list handling.
                token_stream.consume()
                skip_whitespace(token_stream)
                continue

            # `DISPLAY OMITTED AT 0101 WITH BLANK SCREEN`: clears the screen,
            # displays nothing.
            if (token.value or "").upper() == "OMITTED":
                token_stream.consume()
                stmt.add_display_item("OMITTED")
                skip_whitespace(token_stream)
                continue

            # Collect display item
            if token.type in (
                TokenType.STRING_LITERAL,
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
                # The lexer classifies a bare 1-2 digit integer (``DISPLAY
                # 21``) as a LEVEL_NUMBER regardless of context.
                TokenType.LEVEL_NUMBER,
                TokenType.FIGURATIVE_CONSTANT,  # SPACE(S), ZERO(S), HIGH-VALUE(S), ... (M1)
            ):
                item_token = token_stream.consume()

                # Format string literals. A typed literal (X"41", Z"...")
                # keeps its original prefixed text in raw_value -- re-quoting
                # only the content would turn the one-byte hex literal X"41"
                # into the two-character text literal "41".
                item_value = item_token.value or ""
                if token.type == TokenType.STRING_LITERAL:
                    item_value = (
                        item_token.raw_value
                        if item_token.raw_value
                        else quote_literal(item_value)
                    )

                # Subscripted operand, e.g. `SQLERRD(3)`: fold the
                # parenthesized subscript into this item instead of
                # leaving it for the next iteration, where a bare
                # LEFT_PAREN would fall into the "unknown token" branch
                # below and abort the whole DISPLAY item list.
                function_name = (
                    self._consume_function_name(token_stream)
                    if token.type == TokenType.IDENTIFIER
                    and item_value.upper() == "FUNCTION"
                    else None
                )
                if function_name is not None:
                    # ``DISPLAY FUNCTION TRIM(A)`` is one item, rendered the
                    # way MOVE/CALL render it (``FUNCTION TRIM(A)``), with
                    # the argument list and any reference modification
                    # (``FUNCTION CURRENT-DATE(1:8)``) folded in.
                    item_value = f"{item_value} {function_name}"
                    while True:
                        group = self._consume_subscript(token_stream)
                        if not group:
                            break
                        item_value += group
                elif token.type == TokenType.IDENTIFIER:
                    item_value += self._consume_subscript(token_stream)
                    # ``DISPLAY ELEM-1 OF GRP-1`` -- fold a qualifier chain
                    # (and any subscript that follows it) into the item
                    # rather than stranding ``OF GRP-1`` as unparsed tokens.
                    qualifier, _ = peek_past_noise(token_stream, 0)
                    if qualifier and qualifier.type in (TokenType.OF, TokenType.IN):
                        item_value = consume_optional_qualifiers(
                            token_stream, item_value
                        )

                stmt.add_display_item(item_value)
            else:
                # Unknown token - probably next statement, stop parsing
                break

            skip_whitespace(token_stream)

        return (
            stmt
            if isinstance(stmt, DisplayStatement)
            else DisplayStatement(start_location)
        )

    @staticmethod
    def _parse_at_clause(token_stream: ITokenStream, stmt: DisplayStatement) -> None:
        """Parse an ``AT`` positioning clause and call ``stmt.set_position``.

        Supports both forms confirmed in real-world usage (see
        reports/open-findings.md M3): the combined 4-digit numeric form
        (``AT 0330`` -> line 3, column 30, where the low-order two digits
        are the column and the remainder is the line) and the explicit
        ``AT LINE n [COLUMN m]`` / ``AT COLUMN m [LINE n]`` keyword form.
        Assumes the ``AT`` token itself has already been peeked but not
        consumed.
        """
        token_stream.consume()  # AT
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if not token:
            return

        line: int | None = None
        column: int | None = None

        if (
            token.type == TokenType.NUMERIC_LITERAL
            and token.value
            and token.value.isdigit()
        ):
            token_stream.consume()
            value = int(token.value)
            line, column = divmod(value, 100)
            stmt.set_position(line, column)
            stmt.screen_phrases.append(f"AT {token.value}")
            return
        if token.type == TokenType.IDENTIFIER and token.value and (
            token.value.upper() not in ("COLUMN", "COL")
        ):
            # `AT WS-POS`: a 4- or 6-digit position held in a data item.
            token_stream.consume()
            stmt.screen_phrases.append(f"AT {token.value}")
            return

        # Keyword form: LINE and/or COLUMN, in either order.
        for _ in range(2):
            token = token_stream.peek()
            if token and token.type == TokenType.LINE:
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.lstrip("-").isdigit():
                    token_stream.consume()
                    line = int(num.value)
                    stmt.screen_phrases.append(f"AT LINE {num.value}")
                elif num and num.type == TokenType.IDENTIFIER and num.value:
                    token_stream.consume()
                    stmt.screen_phrases.append(f"AT LINE {num.value}")
                skip_whitespace(token_stream)
            elif (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in ("COLUMN", "COL")
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.lstrip("-").isdigit():
                    token_stream.consume()
                    column = int(num.value)
                    stmt.screen_phrases.append(f"COLUMN {num.value}")
                elif num and num.type == TokenType.IDENTIFIER and num.value:
                    token_stream.consume()
                    stmt.screen_phrases.append(f"COLUMN {num.value}")
                skip_whitespace(token_stream)
            else:
                break

        if line is not None or column is not None:
            stmt.set_position(line, column)

    @staticmethod
    def _parse_screen_phrase(
        token_stream: ITokenStream,
        stmt: DisplayStatement,
        bare_attributes: bool = True,
        operands: bool = True,
    ) -> bool:
        """Consume one screen phrase (`LINE 3`, `COL WS-C`, `HIGHLIGHT`,
        `BLANK SCREEN`, `FOREGROUND-COLOR IS 2`) into `stmt.screen_phrases`;
        False, consuming nothing, when the next token starts none.
        `bare_attributes` / `operands` False leave a lone attribute word
        (`BELL`) / an operand phrase (`SIZE 3`) to be read as an item."""
        token = token_stream.peek()
        if not token or not token.value:
            return False
        word = token.value.upper()
        if token.type not in (TokenType.IDENTIFIER, TokenType.LINE):
            return False
        if word in _SCREEN_WORDS:
            if not bare_attributes:
                return False
            token_stream.consume()
            stmt.screen_phrases.append(word)
            return True
        if word in _SCREEN_WORDS_WITH_KEYWORD:
            following, _ = peek_past_noise(token_stream, 1)
            if (
                following
                and following.value
                and following.value.upper() in _SCREEN_WORDS_WITH_KEYWORD[word]
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                token_stream.consume()
                stmt.screen_phrases.append(f"{word} {following.value.upper()}")
                return True
            return False
        if word not in _SCREEN_WORDS_WITH_OPERAND or not operands:
            return False
        token_stream.consume()
        skip_whitespace(token_stream)
        phrase = [word]
        for noise in ("NUMBER", "IS", "PLUS", "+"):
            nxt = token_stream.peek()
            if nxt and nxt.value and nxt.value.upper() == noise:
                token_stream.consume()
                skip_whitespace(token_stream)
                phrase.append(noise)
        operand = token_stream.peek()
        if operand and operand.type in _OPERAND_TYPES and operand.value:
            token_stream.consume()
            phrase.append(operand.value)
        stmt.screen_phrases.append(" ".join(phrase))
        return True

    @staticmethod
    def _consume_function_name(token_stream: ITokenStream) -> str | None:
        """After a consumed ``FUNCTION`` word, consume the intrinsic name.

        Returns the name, or ``None`` (consuming nothing) when no identifier
        follows -- then ``FUNCTION`` stays an ordinary item, as before.
        """
        token, _ = peek_past_noise(token_stream, 0)
        if not token or token.type != TokenType.IDENTIFIER or not token.value:
            return None
        skip_whitespace(token_stream)
        token_stream.consume()
        return token.value

    @staticmethod
    def _consume_subscript(token_stream: ITokenStream) -> str:
        """Consume a following `( subscript-expr )` if present, returning its
        text (including the parens) for appending to the preceding
        identifier, or "" if the next token isn't a LEFT_PAREN. Tracks paren
        depth so a nested subscript/function call like `TAB(FUNCTION
        MOD(X 3))` is consumed as one unit and its inner parens are kept
        literally (mirrors move_parser._parse_source, which also tracks
        depth rather than assuming a single paren pair).

        The subscript may sit on its own continuation line (``DISPLAY
        WS-ITEM\\n    (WS-IDX).``) -- a non-destructive lookahead past
        whitespace/newline/continuation tokens confirms a LEFT_PAREN is
        actually there before any whitespace is consumed, so a following
        display item with no subscript at all isn't affected.
        """
        token, _ = peek_past_noise(token_stream, 0)
        if not token or token.type != TokenType.LEFT_PAREN:
            return ""
        skip_whitespace(token_stream)

        parts: list[str] = []
        paren_depth = 0
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.LEFT_PAREN:
                paren_depth += 1
                parts.append("(")
                token_stream.consume()
                continue
            if token.type == TokenType.RIGHT_PAREN:
                paren_depth -= 1
                parts.append(")")
                token_stream.consume()
                if paren_depth == 0:
                    break
                continue
            value = token.value or ""
            parts.append(
                quote_literal(value)
                if token.type == TokenType.STRING_LITERAL
                else value
            )
            token_stream.consume()

        # Join without a space around parens (`SQLERRD(3)`, `MOD(X 3)`) but
        # with one between adjacent non-paren tokens (`TAB(I J)`'s
        # multi-dimension subscript), so nested parens round-trip literally
        # instead of being flattened into a single space-joined pair.
        out: list[str] = []
        for i, part in enumerate(parts):
            if i > 0 and part not in ("(", ")") and parts[i - 1] != "(":
                out.append(" ")
            out.append(part)
        return "".join(out)

    @staticmethod
    def _is_keyword(token: Any, keyword: str) -> bool:
        """Check if token is a specific keyword (case-insensitive).

        Args:
            token: Token to check
            keyword: Keyword name to match

        Returns:
            True if token matches keyword
        """
        if not token or not hasattr(token, "value"):
            return False

        return bool(
            token.type == TokenType.IDENTIFIER
            and token.value
            and token.value.upper() == keyword.upper()
        )
