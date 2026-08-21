"""Go statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    STATEMENT_KEYWORDS,
    get_parse_context,
    matches_keyword,
    report_parse_error,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import GoStatement


class GoStatementParser(IStatementParser):
    """Parser for GO (GO TO) statements using IStatementParser interface.

    GO statements transfer control to labeled paragraphs or sections.
    Syntax:
        GO TO paragraph-name
        GO TO paragraph-name DEPENDING ON variable

    Example:
        GO TO PARA-1.
        GO TO PARA-1 DEPENDING ON idx.
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is GO keyword.

        Args:
            token_stream: Token stream to check

        Returns:
            True if next token is GO, False otherwise
        """
        return matches_keyword(token_stream, TokenType.GO, "GO")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> GoStatement:
        """Parse a GO statement.

        Handles:
        - GO TO paragraph-name
        - GO TO paragraph-name DEPENDING ON variable

        Args:
            token_stream: Token stream positioned at GO keyword

        Returns:
            GoStatement with target paragraph and optional DEPENDING ON variable

        Raises:
            ValueError: If TO or target paragraph is missing
        """
        start_token = token_stream.consume()  # consume GO keyword
        context = get_parse_context(token_stream)

        stmt = GoStatement(
            start_token.location
            if hasattr(start_token, "location")
            else SourceLocation(0, 0)
        )

        # Consume optional TO keyword — `GO label.` is valid IBM COBOL
        if token_stream.is_empty():
            report_parse_error(
                context, "GO statement requires a target paragraph", stmt.location
            )
            return stmt

        next_token = token_stream.peek()
        if not next_token or not next_token.value:
            report_parse_error(
                context, "GO statement requires a target paragraph", stmt.location
            )
            return stmt

        if next_token.value.upper() == "TO":
            token_stream.consume()  # consume optional TO

        # Parse target paragraph name
        if token_stream.is_empty():
            report_parse_error(
                context, "GO statement requires a target paragraph", stmt.location
            )
            return stmt

        next_token = token_stream.peek()
        if not next_token or not next_token.value:
            report_parse_error(
                context, "GO statement requires a target paragraph", stmt.location
            )
            return stmt

        target_name = next_token.value

        stmt.set_target_paragraph(target_name)
        token_stream.consume()  # consume target name

        # Computed GO TO: several targets before DEPENDING ON. Historically
        # only the first target was kept and the rest — including the
        # DEPENDING ON variable — were silently skipped, turning a jump
        # table into an unconditional branch to the first label.
        #
        # Scan ahead WITHOUT consuming: additional identifiers are only
        # targets if a DEPENDING follows; otherwise they belong to the next
        # sentence (e.g. a paragraph name after a missing period) and must
        # be left in the stream.
        extra_targets: list[str] = []
        found_depending = False
        idx = 0
        while True:
            look = token_stream.peek(idx)
            if look is None:
                break
            if look.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                idx += 1
                continue
            if look.type is TokenType.COMMA:
                # A comma between targets (`GO TO A, B DEPENDING ON X`) is a
                # separator, not a terminator -- keep scanning for DEPENDING,
                # mirroring the MOVE/SET parsers' comma handling.
                idx += 1
                continue
            look_upper = (look.value or "").upper()
            if look_upper == "DEPENDING":
                found_depending = True
                break
            # COBOL permits all-digit paragraph/section names (idiomatic in
            # THRU-style numbering); the lexer emits those as NUMERIC_LITERAL
            # or LEVEL_NUMBER (1-2 digit values), never IDENTIFIER.
            is_name_token = look.type is TokenType.IDENTIFIER or (
                look.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)
                and look.value.isdigit()
            )
            if (
                not look.value
                or look_upper == "."
                or look_upper in STATEMENT_KEYWORDS
                or not is_name_token
            ):
                break
            extra_targets.append(look.value)
            idx += 1

        if found_depending:
            consumed_targets = 0
            while consumed_targets < len(extra_targets):
                next_token = token_stream.peek()
                if next_token is None:
                    break
                if next_token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                    token_stream.consume()
                    continue
                if next_token.type is TokenType.COMMA:
                    # Separator between targets -- consume without counting
                    # it as (or recording it as) a target.
                    token_stream.consume()
                    continue
                stmt.add_target_paragraph(next_token.value)
                token_stream.consume()
                consumed_targets += 1
            # Position at the DEPENDING keyword (skip layout tokens and any
            # trailing separator comma)
            while not token_stream.is_empty():
                next_token = token_stream.peek()
                if next_token and (
                    next_token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT")
                    or next_token.type is TokenType.COMMA
                ):
                    token_stream.consume()
                    continue
                break

        # Check for DEPENDING ON clause
        self._parse_depending_on_clause(token_stream, stmt)

        # Consume period if present
        _t = token_stream.peek()
        if not token_stream.is_empty() and _t and _t.value == ".":
            token_stream.consume()

        return stmt

    def _parse_depending_on_clause(
        self, token_stream: ITokenStream, stmt: GoStatement
    ) -> None:
        """Parse the optional DEPENDING ON clause of a GO statement.

        Args:
            token_stream: Token stream positioned after target paragraph
            stmt: GoStatement to populate with DEPENDING ON variable
        """

        def _skip_layout() -> None:
            while not token_stream.is_empty():
                tok = token_stream.peek()
                if tok and tok.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                    token_stream.consume()
                    continue
                break

        # Check for DEPENDING keyword
        _skip_layout()
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token or not next_token.value:
            return
        if next_token.value.upper() != "DEPENDING":
            return

        # Consume DEPENDING keyword
        token_stream.consume()

        # Expect ON keyword
        _skip_layout()
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token or not next_token.value or next_token.value.upper() != "ON":
            return

        token_stream.consume()  # consume ON

        # Parse variable name
        _skip_layout()
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token:
            return

        var_name = next_token.value
        if var_name and var_name != ".":
            stmt.set_depending_on_variable(var_name)
            token_stream.consume()
