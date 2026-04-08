"""Entry statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...models.ast_base import SourceLocation
from ...models.statements import EntryStatement


class EntryStatementParser(IStatementParser):
    """Parser for ENTRY statements using IStatementParser interface.

    ENTRY statements define alternate entry points into a program.
    Syntax: ENTRY 'entry-name' [USING parameter1 parameter2 ...]

    Example:
        ENTRY 'DLITCBL' USING LKPCB-IO LKPCB-ALT LKPCB-BPP100MA
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is ENTRY keyword.

        Args:
            token_stream: Token stream to check

        Returns:
            True if next token is ENTRY, False otherwise
        """
        try:
            token = token_stream.peek()
            if not token:
                return False
            token_val_upper = token.value.upper() if token.value else ""
            return token_val_upper == "ENTRY"
        except Exception:
            return False

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> EntryStatement:
        """Parse an ENTRY statement.

        Handles:
        - ENTRY 'entry-name'
        - ENTRY 'entry-name' USING param1 param2 ...

        Args:
            token_stream: Token stream positioned at ENTRY keyword

        Returns:
            EntryStatement with entry name and parameters

        Raises:
            ValueError: If entry name is not present
        """
        start_token = token_stream.consume()  # consume ENTRY keyword

        # Create statement with location
        stmt = EntryStatement(
            start_token.location
            if hasattr(start_token, "location")
            else SourceLocation(0, 0)
        )

        # Parse entry name (must be a string literal)
        if token_stream.is_empty():
            raise ValueError("ENTRY statement requires a name")

        next_token = token_stream.peek()
        if not next_token:
            raise ValueError("ENTRY statement requires a name")

        # Get entry name - should be a STRING_LITERAL or identifier
        entry_name = None
        if next_token.type.name == "STRING_LITERAL":
            # Remove quotes from string literal
            entry_name = next_token.value.strip("\"'")
            token_stream.consume()  # consume the literal
        elif next_token.type.name == "IDENTIFIER":
            entry_name = next_token.value
            token_stream.consume()  # consume the identifier
        else:
            # Try to treat the value as entry name anyway
            entry_name = next_token.value
            token_stream.consume()  # consume it

        if not entry_name:
            raise ValueError("ENTRY statement requires a name")

        stmt.set_entry_name(entry_name)

        # Check for USING clause
        self._parse_using_clause(token_stream, stmt)

        # Consume period if present
        _t = token_stream.peek()
        if not token_stream.is_empty() and _t and _t.value == ".":
            token_stream.consume()

        return stmt

    def _parse_using_clause(
        self, token_stream: ITokenStream, stmt: EntryStatement
    ) -> None:
        """Parse the optional USING clause of an ENTRY statement.

        Args:
            token_stream: Token stream positioned after entry name
            stmt: EntryStatement to populate with parameters
        """
        # Check for USING keyword
        if token_stream.is_empty():
            return

        next_token = token_stream.peek()
        if not next_token or next_token.value.upper() != "USING":
            return

        # Consume USING keyword
        token_stream.consume()

        # Parse parameter list until period or next keyword
        while not token_stream.is_empty():
            # Skip whitespace tokens (including newlines)
            while not token_stream.is_empty():
                next_token = token_stream.peek()
                if not next_token or (
                    hasattr(next_token, "type")
                    and next_token.type.name not in ("WHITESPACE", "COMMENT", "NEWLINE")
                ):
                    break
                token_stream.consume()

            if token_stream.is_empty():
                break

            next_token = token_stream.peek()
            if not next_token:
                break

            token_val_upper = next_token.value.upper() if next_token.value else ""

            # Stop if we hit a period or another keyword
            if next_token.value == "." or token_val_upper in ("BY", "GIVING", "ON"):
                break

            # Parse parameter name (should be identifier)
            if next_token.type.name in ("IDENTIFIER", "PICTURE"):
                param_name = next_token.value
                stmt.add_using_parameter(param_name)
                token_stream.consume()
            else:
                # Try to consume as parameter anyway
                stmt.add_using_parameter(next_token.value)
                token_stream.consume()
