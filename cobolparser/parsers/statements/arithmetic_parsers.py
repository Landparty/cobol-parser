"""Arithmetic statement parsers implementing IStatementParser interface.

Supports ADD, SUBTRACT, MULTIPLY, DIVIDE, and COMPUTE statements with proper
parsing of operands, targets, expressions, and error handling clauses.
"""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ._utils import (
    matches_keyword,
    parse_size_error_clauses,
    skip_to_period,
    token_location,
)


class AddStatementParser(IStatementParser):
    """Parser for ADD statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.ADD, "ADD")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> AddStatement:
        """Parse an ADD statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        stmt = AddStatement(start_loc)

        # Parse operands until TO or GIVING
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""
            if token_val_upper in ("TO", "GIVING"):
                break

            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)

            token_stream.consume()

        # Check for TO or GIVING
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper == "TO":
                token_stream.consume()  # Skip TO
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    token_stream.consume()
                # After TO, check for GIVING
                token = token_stream.peek()
                if token and token.value and token.value.upper() == "GIVING":
                    token_stream.consume()  # Skip GIVING
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_giving(token.value)
                        token_stream.consume()
            elif token_val_upper == "GIVING":
                token_stream.consume()  # Skip GIVING
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    token_stream.consume()

        # Parse optional ON SIZE ERROR / NOT ON SIZE ERROR clauses
        parse_size_error_clauses(token_stream, stmt)

        return stmt


class SubtractStatementParser(IStatementParser):
    """Parser for SUBTRACT statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SUBTRACT, "SUBTRACT")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SubtractStatement:
        """Parse a SUBTRACT statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        stmt = SubtractStatement(start_loc)

        # Parse operands until FROM or GIVING
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""
            if token_val_upper in ("FROM", "GIVING"):
                break

            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)

            token_stream.consume()

        # Check for FROM or GIVING
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper == "FROM":
                token_stream.consume()  # Skip FROM
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    token_stream.consume()
            elif token_val_upper == "GIVING":
                token_stream.consume()  # Skip GIVING
                token = token_stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    token_stream.consume()

        skip_to_period(token_stream)
        return stmt


class MultiplyStatementParser(IStatementParser):
    """Parser for MULTIPLY statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.MULTIPLY, "MULTIPLY")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> MultiplyStatement:
        """Parse a MULTIPLY statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        stmt = MultiplyStatement(start_loc)

        # Parse first operand
        token = token_stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            token_stream.consume()

        # Check for BY
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "BY":
            token_stream.consume()  # Skip BY
            token = token_stream.peek()
            if token and token.type in (
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
            ):
                stmt.add_operand(token.value)
                token_stream.consume()

        # Check for GIVING
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            token_stream.consume()  # Skip GIVING
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                token_stream.consume()

        skip_to_period(token_stream)
        return stmt


class DivideStatementParser(IStatementParser):
    """Parser for DIVIDE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.DIVIDE, "DIVIDE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> DivideStatement:
        """Parse a DIVIDE statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        stmt = DivideStatement(start_loc)

        # Parse first operand
        token = token_stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            token_stream.consume()

        # Check for BY or INTO
        token = token_stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()
            if token_val_upper in ("BY", "INTO"):
                token_stream.consume()  # Skip BY/INTO
                token = token_stream.peek()
                if token and token.type in (
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                ):
                    stmt.add_operand(token.value)
                    token_stream.consume()

        # Check for GIVING
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            token_stream.consume()  # Skip GIVING
            token = token_stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                token_stream.consume()

        skip_to_period(token_stream)
        return stmt


class ComputeStatementParser(IStatementParser):
    """Parser for COMPUTE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.COMPUTE, "COMPUTE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> ComputeStatement:
        """Parse a COMPUTE statement."""
        start_token = token_stream.consume()
        start_loc = token_location(start_token)
        stmt = ComputeStatement(start_loc)

        # Parse target variable(s)
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.add_target(token.value)
            token_stream.consume()

        # Skip ROUNDED if present
        token = token_stream.peek()
        if token and token.value and token.value.upper() == "ROUNDED":
            token_stream.consume()

        # Check for =
        token = token_stream.peek()
        if token and token.value == "=":
            token_stream.consume()  # Skip =

        # Parse expression (collect all tokens until terminator)
        expr_tokens = []
        paren_depth = 0
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            # Stop at terminators
            if paren_depth == 0 and (
                token.type == TokenType.PERIOD
                or token_val_upper in ("ON", "NOT", "END-COMPUTE")
            ):
                break

            if token.type == TokenType.LEFT_PAREN:
                paren_depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                paren_depth -= 1

            expr_tokens.append(token.value if token.value else "")
            token_stream.consume()

        if expr_tokens:
            expr_str = " ".join(expr_tokens).strip()
            stmt.set_expression(expr_str)

        parse_size_error_clauses(token_stream, stmt)
        return stmt
