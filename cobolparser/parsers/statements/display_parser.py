"""Display statement parser implementing IStatementParser interface.

Refactored to implement the IStatementParser interface for registry-based
statement parsing in the extracted statement parser architecture.

Uses ASTNodeFactory for validated node creation.
"""

from typing import Any

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import DisplayStatement
from ._utils import SCOPE_TERMINATORS, matches_keyword, skip_whitespace


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
                break

            # Scope terminators of an enclosing statement (e.g. END-READ when
            # this DISPLAY is an AT END clause body) end the item list.
            if (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in SCOPE_TERMINATORS
            ):
                break

            # Collect display item
            if token.type in (
                TokenType.STRING_LITERAL,
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
            ):
                item_token = token_stream.consume()

                # Format string literals
                item_value = item_token.value or ""
                if token.type == TokenType.STRING_LITERAL:
                    item_value = f'"{item_value}"'

                # Subscripted operand, e.g. `SQLERRD(3)`: fold the
                # parenthesized subscript into this item instead of
                # leaving it for the next iteration, where a bare
                # LEFT_PAREN would fall into the "unknown token" branch
                # below and abort the whole DISPLAY item list.
                if token.type == TokenType.IDENTIFIER:
                    item_value += self._consume_subscript(token_stream)

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
    def _consume_subscript(token_stream: ITokenStream) -> str:
        """Consume a following `( subscript-expr )` if present, returning its
        text (including the parens) for appending to the preceding
        identifier, or "" if the next token isn't a LEFT_PAREN. Tracks paren
        depth so a nested subscript/function call like `TAB(FUNCTION
        MOD(X 3))` is consumed as one unit and its inner parens are kept
        literally (mirrors move_parser._parse_source, which also tracks
        depth rather than assuming a single paren pair)."""
        token = token_stream.peek()
        if not token or token.type != TokenType.LEFT_PAREN:
            return ""

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
                f'"{value}"' if token.type == TokenType.STRING_LITERAL else value
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
