"""Parsers for arithmetic statements (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE)."""

from typing import Optional, List
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import (
    AddStatement,
    SubtractStatement,
    MultiplyStatement,
    DivideStatement,
    ComputeStatement,
    CobolStatement,
)
from ..lexer import TokenType


class ArithmeticParserBase:
    """Base class with shared logic for arithmetic statement parsers."""

    def parse_size_error_clauses(
        self, stream: TokenStream, context: ParseContext = None
    ) -> tuple[List[CobolStatement], List[CobolStatement]]:
        """Parse ON SIZE ERROR and NOT ON SIZE ERROR clauses.

        Returns:
            Tuple of (on_size_error_stmts, not_on_size_error_stmts)
        """
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)            

        on_size_error_stmts = []
        not_on_size_error_stmts = []

        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            # Check for ON SIZE ERROR
            if token_val_upper == "ON":
                next_token = stream.peek(1)
                if next_token and next_token.value:
                    next_val_upper = next_token.value.upper()
                    if next_val_upper == "SIZE":
                        third_token = stream.peek(2)
                        if third_token and third_token.value and third_token.value.upper() == "ERROR":
                            # Found ON SIZE ERROR
                            stream.advance()  # Skip ON
                            stream.advance()  # Skip SIZE
                            stream.advance()  # Skip ERROR
                            stream.skip_whitespace_and_comments()

                            # Parse statements until NOT ON SIZE ERROR or terminator
                            on_size_error_stmts = self._parse_nested_statements(
                                stream, context, ("NOT", "END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE")
                            )
                            continue

            # Check for NOT ON SIZE ERROR
            if token_val_upper == "NOT":
                next_token = stream.peek(1)
                if next_token and next_token.value and next_token.value.upper() == "ON":
                    third_token = stream.peek(2)
                    if third_token and third_token.value and third_token.value.upper() == "SIZE":
                        fourth_token = stream.peek(3)
                        if fourth_token and fourth_token.value and fourth_token.value.upper() == "ERROR":
                            # Found NOT ON SIZE ERROR
                            stream.advance()  # Skip NOT
                            stream.advance()  # Skip ON
                            stream.advance()  # Skip SIZE
                            stream.advance()  # Skip ERROR
                            stream.skip_whitespace_and_comments()

                            # Parse statements until terminator
                            not_on_size_error_stmts = self._parse_nested_statements(
                                stream, context, ("END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE")
                            )
                            continue

            # Check for terminators
            if token_val_upper in ("END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE"):
                stream.advance()  # Consume terminator
                break

            # Stop at period or other statement keywords
            if token.type == TokenType.PERIOD or token_val_upper in (
                "MOVE", "DISPLAY", "PERFORM", "IF", "CALL", "EVALUATE"
            ):
                break

            stream.advance()

        return on_size_error_stmts, not_on_size_error_stmts

    def _parse_nested_statements(
        self, stream: TokenStream, context: ParseContext, stop_keywords: tuple
    ) -> List[CobolStatement]:
        """Parse nested statements until stop keywords encountered.
        
        Supports parsing common statements like DISPLAY, MOVE, etc. until
        reaching one of the stop keywords.
        """
        statements = []

        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            # Check for stop keywords
            if token_val_upper in stop_keywords:
                break
            
            # Check for scope terminators (Period)
            if token.type == TokenType.PERIOD:
                break

            # Check for multi-word stop keywords (like END-ADD)
            if "-" in token_val_upper:
                if token_val_upper in stop_keywords:
                    break
            else:
                # Check if this might be part of a multi-word keyword
                for stop in stop_keywords:
                    if "-" in stop:
                        first_part = stop.split("-")[0]
                        if token_val_upper == first_part:
                            # Check if next token completes the keyword
                            next_token = stream.peek(1)
                            if next_token and next_token.value:
                                combined = f"{token_val_upper}-{next_token.value.upper()}"
                                if combined in stop_keywords:
                                    break

            # Try to parse statement using registry
            if context and context.registry and context.host:
                parser = context.registry.get_parser(stream)
                if parser:
                    try:
                        stmt = parser.parse(stream, context)
                        if stmt:
                            statements.append(stmt)
                            continue
                    except:
                        # If parser fails, skip token and continue
                        pass

            # No parser found or parse failed, skip token
            stream.advance()

        return statements


class AddStatementParser(StatementParser, ArithmeticParserBase):
    """Parser for ADD statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.ADD or (
            token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "ADD"
        )

    def matches(self, stream: TokenStream) -> bool:
        """Adapter method for registry interface."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream, context: ParseContext = None) -> AddStatement:
        """Parse ADD statement.

        Supports:
        - ADD operand TO target
        - ADD operand operand... GIVING result
        - ON SIZE ERROR clause with nested statements
        - NOT ON SIZE ERROR clause with nested statements
        """
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)

        start_token = stream.peek()
        if start_token and (
            start_token.type == TokenType.ADD
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "ADD")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)

        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = AddStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse operands until TO or GIVING
        operands = []
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            if token_val_upper in ("TO", "GIVING"):
                break

            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                operands.append(token.value)
                stmt.add_operand(token.value)

            stream.advance()
            stream.skip_whitespace_and_comments()

        # Check for TO or GIVING
        token = stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()

            if token_val_upper == "TO":
                stream.advance()  # Skip TO
                stream.skip_whitespace_and_comments()

                # Parse target
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    stream.advance()

            elif token_val_upper == "GIVING":
                stream.advance()  # Skip GIVING
                stream.skip_whitespace_and_comments()

                # Parse result
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    stream.advance()

        stream.skip_whitespace_and_comments()

        # Parse error clauses
        on_error, not_on_error = self.parse_size_error_clauses(stream, context)
        if on_error:
            stmt.set_on_size_error_clause(on_error)
        if not_on_error:
            stmt.set_not_on_size_error_clause(not_on_error)

        return stmt


class SubtractStatementParser(StatementParser, ArithmeticParserBase):
    """Parser for SUBTRACT statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.SUBTRACT or (
            token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "SUBTRACT"
        )

    def matches(self, stream: TokenStream) -> bool:
        """Adapter method for registry interface."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream, context: ParseContext = None) -> SubtractStatement:
        """Parse SUBTRACT statement."""
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)

        start_token = stream.peek()
        if start_token and (
            start_token.type == TokenType.SUBTRACT
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "SUBTRACT")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)

        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = SubtractStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse operands until FROM or GIVING
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            if token_val_upper in ("FROM", "GIVING"):
                break

            if token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)

            stream.advance()
            stream.skip_whitespace_and_comments()

        # Check for FROM or GIVING
        token = stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()

            if token_val_upper == "FROM":
                stream.advance()  # Skip FROM
                stream.skip_whitespace_and_comments()

                # Parse target
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_target(token.value)
                    stream.advance()

            elif token_val_upper == "GIVING":
                stream.advance()  # Skip GIVING
                stream.skip_whitespace_and_comments()

                # Parse result
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_giving(token.value)
                    stream.advance()

        stream.skip_whitespace_and_comments()

        # Parse error clauses
        on_error, not_on_error = self.parse_size_error_clauses(stream, context)
        if on_error:
            stmt.set_on_size_error_clause(on_error)
        if not_on_error:
            stmt.set_not_on_size_error_clause(not_on_error)

        return stmt


class MultiplyStatementParser(StatementParser, ArithmeticParserBase):
    """Parser for MULTIPLY statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.MULTIPLY or (
            token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "MULTIPLY"
        )

    def matches(self, stream: TokenStream) -> bool:
        """Adapter method for registry interface."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream, context: ParseContext = None) -> MultiplyStatement:
        """Parse MULTIPLY statement."""
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)

        start_token = stream.peek()
        if start_token and (
            start_token.type == TokenType.MULTIPLY
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "MULTIPLY")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)

        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = MultiplyStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse first operand
        token = stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            stream.advance()
            stream.skip_whitespace_and_comments()

        # Check for BY
        token = stream.peek()
        if token and token.value and token.value.upper() == "BY":
            stream.advance()  # Skip BY
            stream.skip_whitespace_and_comments()

            # Parse second operand
            token = stream.peek()
            if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_operand(token.value)
                stream.advance()
                stream.skip_whitespace_and_comments()

        # Check for GIVING
        token = stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            stream.advance()  # Skip GIVING
            stream.skip_whitespace_and_comments()

            # Parse result
            token = stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                stream.advance()

        stream.skip_whitespace_and_comments()

        # Parse error clauses
        on_error, not_on_error = self.parse_size_error_clauses(stream, context)
        if on_error:
            stmt.set_on_size_error_clause(on_error)
        if not_on_error:
            stmt.set_not_on_size_error_clause(not_on_error)

        return stmt


class DivideStatementParser(StatementParser, ArithmeticParserBase):
    """Parser for DIVIDE statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.DIVIDE or (
            token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "DIVIDE"
        )

    def matches(self, stream: TokenStream) -> bool:
        """Adapter method for registry interface."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream, context: ParseContext = None) -> DivideStatement:
        """Parse DIVIDE statement."""
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)

        start_token = stream.peek()
        if start_token and (
            start_token.type == TokenType.DIVIDE
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "DIVIDE")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)

        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = DivideStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse first operand
        token = stream.peek()
        if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
            stmt.add_operand(token.value)
            stream.advance()
            stream.skip_whitespace_and_comments()

        # Check for BY or INTO
        token = stream.peek()
        if token and token.value:
            token_val_upper = token.value.upper()

            if token_val_upper in ("BY", "INTO"):
                stream.advance()  # Skip BY/INTO
                stream.skip_whitespace_and_comments()

                # Parse second operand
                token = stream.peek()
                if token and token.type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                    stmt.add_operand(token.value)
                    stream.advance()
                    stream.skip_whitespace_and_comments()

        # Check for GIVING
        token = stream.peek()
        if token and token.value and token.value.upper() == "GIVING":
            stream.advance()  # Skip GIVING
            stream.skip_whitespace_and_comments()

            # Parse result
            token = stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving(token.value)
                stream.advance()

        stream.skip_whitespace_and_comments()

        # Parse error clauses
        on_error, not_on_error = self.parse_size_error_clauses(stream, context)
        if on_error:
            stmt.set_on_size_error_clause(on_error)
        if not_on_error:
            stmt.set_not_on_size_error_clause(not_on_error)

        return stmt


class ComputeStatementParser(StatementParser, ArithmeticParserBase):
    """Parser for COMPUTE statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.COMPUTE or (
            token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "COMPUTE"
        )

    def matches(self, stream: TokenStream) -> bool:
        """Adapter method for registry interface."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream, context: ParseContext = None) -> ComputeStatement:
        """Parse COMPUTE statement."""
        # Get context from stream if not provided
        if context is None:
            context = getattr(stream, '_parse_context', None)

        start_token = stream.peek()
        if start_token and (
            start_token.type == TokenType.COMPUTE
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "COMPUTE")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)

        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = ComputeStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse target variable
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER:
            stmt.add_target(token.value)
            stream.advance()
            stream.skip_whitespace_and_comments()

        # Check for =
        token = stream.peek()
        if token and token.value == "=":
            stream.advance()  # Skip =
            stream.skip_whitespace_and_comments()

        # Parse expression (collect all tokens until terminator)
        expr_tokens = []
        paren_depth = 0
        while not stream.is_at_end:
            token = stream.peek()
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
            stream.advance()
            stream.skip_whitespace_and_comments()

        if expr_tokens:
            expr_str = " ".join(expr_tokens).strip()
            stmt.set_expression(expr_str)

        # Parse error clauses
        on_error, not_on_error = self.parse_size_error_clauses(stream, context)
        if on_error:
            stmt.set_on_size_error_clause(on_error)
        if not_on_error:
            stmt.set_not_on_size_error_clause(not_on_error)

        return stmt
