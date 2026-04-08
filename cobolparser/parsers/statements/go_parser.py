"""Go statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import get_parse_context, report_parse_error

from ...core.interfaces import IStatementParser, ITokenStream
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
        try:
            token = token_stream.peek()
            if not token:
                return False
            token_val_upper = token.value.upper() if token.value else ""
            return token_val_upper == "GO"
        except Exception:
            return False

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

        # Expect TO keyword
        if token_stream.is_empty():
            report_parse_error(
                context, "GO statement requires TO keyword", stmt.location
            )
            return stmt

        next_token = token_stream.peek()
        if not next_token or not next_token.value or next_token.value.upper() != "TO":
            report_parse_error(
                context, "GO statement requires TO keyword", stmt.location
            )
            return stmt

        token_stream.consume()  # consume TO

        # Parse target paragraph name
        if token_stream.is_empty():
            report_parse_error(
                context, "GO TO statement requires a target paragraph", stmt.location
            )
            return stmt

        next_token = token_stream.peek()
        if not next_token or not next_token.value:
            report_parse_error(
                context, "GO TO statement requires a target paragraph", stmt.location
            )
            return stmt

        target_name = next_token.value

        stmt.set_target_paragraph(target_name)
        token_stream.consume()  # consume target name

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
        # Check for DEPENDING keyword
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token or next_token.value.upper() != "DEPENDING":
            return

        # Consume DEPENDING keyword
        token_stream.consume()

        # Expect ON keyword
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token or next_token.value.upper() != "ON":
            return

        token_stream.consume()  # consume ON

        # Parse variable name
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token:
            return

        var_name = next_token.value
        if var_name and var_name != ".":
            stmt.set_depending_on_variable(var_name)
            token_stream.consume()
