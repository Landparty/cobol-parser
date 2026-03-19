from typing import Optional, List
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import CallStatement
from ..lexer import TokenType


class CallStatementParser(StatementParser):
    """Parser for CALL statements."""
    token_type = TokenType.CALL

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        if token.type == TokenType.CALL:
            return True
        if token.type == TokenType.IDENTIFIER and token.value.upper() == "CALL":
            return True
        # Recovery: Check if previous token was CALL
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.CALL or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "CALL"
            ):
                return True
        return False

    def parse(self, stream: TokenStream, context: ParseContext) -> CallStatement:
        """Parse CALL statement.

        Supports:
        - CALL "literal" or CALL identifier (dynamic)
        - USING clause with BY REFERENCE/CONTENT/VALUE parameters
        - RETURNING clause
        - ON EXCEPTION/OVERFLOW clauses with END-CALL terminator
        """
        start_token = stream.peek()
        # Consume CALL if present
        if start_token and (
            start_token.type == TokenType.CALL
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "CALL")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)
        
        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = CallStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Get program name (literal or identifier)
        token = stream.peek()
        if not token or not token.value:
            context.error("Expected program name after CALL", start_token)
            return stmt

        program_name = token.value
        is_dynamic = token.type == TokenType.IDENTIFIER

        # For string literals, keep the quotes
        if token.type == TokenType.STRING_LITERAL:
            program_name = f'"{program_name}"'

        stmt.set_called_program(program_name, is_dynamic)
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Parse optional USING clause
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value.upper() == "USING":
            stream.advance()  # Skip USING
            stream.skip_whitespace_and_comments()
            self._parse_using_parameters(stream, stmt)

        stream.skip_whitespace_and_comments()

        # Parse optional RETURNING clause
        returning_location = None
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value.upper() == "RETURNING":
            returning_location = token.location
            stream.advance()
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_returning_parameter(token.value)
                stream.advance()

        stream.skip_whitespace_and_comments()

        # Parse optional GIVING clause (IBM Enterprise COBOL extension)
        giving_location = None
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value.upper() == "GIVING":
            giving_location = token.location
            stream.advance()
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                stmt.set_giving_parameter(token.value)
                stream.advance()

        # Validate mutual exclusivity of RETURNING and GIVING
        if stmt.returning_parameter is not None and stmt.giving_parameter is not None:
            error_location = giving_location if giving_location else returning_location
            context.error(
                "RETURNING and GIVING clauses are mutually exclusive in CALL statements",
                None,
            )

        stream.skip_whitespace_and_comments()

        # Parse optional ON EXCEPTION/OVERFLOW clauses
        token = stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value.upper() == "ON":
            stream.advance()  # Skip ON
            stream.skip_whitespace_and_comments()

            token = stream.peek()
            if token and token.type == TokenType.IDENTIFIER:
                exception_type = token.value.upper()

                if exception_type in ("EXCEPTION", "OVERFLOW"):
                    stream.advance()
                    stream.skip_whitespace_and_comments()

                    # Parse statements until END-CALL or period
                    exception_statements = []
                    while not stream.is_at_end:
                        stream.skip_whitespace_and_comments()
                        token = stream.peek()
                        if not token:
                            break

                        # Check for END-CALL
                        if token.type == TokenType.IDENTIFIER and token.value.upper() == "END-CALL":
                            stream.advance()
                            break

                        # Check for period (alternative terminator)
                        if token.type == TokenType.PERIOD:
                            break

                        # Check for NOT ON EXCEPTION
                        if token.type == TokenType.IDENTIFIER and token.value.upper() == "NOT":
                            # Look ahead for ON EXCEPTION
                            saved_pos = stream.position
                            stream.advance()
                            stream.skip_whitespace_and_comments()
                            next_token = stream.peek()

                            if next_token and next_token.value.upper() == "ON":
                                stream.advance()
                                stream.skip_whitespace_and_comments()
                                next_token = stream.peek()

                                if next_token and next_token.value.upper() == "EXCEPTION":
                                    # Found NOT ON EXCEPTION
                                    if exception_type == "EXCEPTION":
                                        stmt.on_exception = exception_statements
                                    else:
                                        stmt.on_overflow = exception_statements

                                    stream.advance()
                                    not_exception_statements = []

                                    # Parse NOT ON EXCEPTION statements
                                    while not stream.is_at_end:
                                        stream.skip_whitespace_and_comments()
                                        token = stream.peek()
                                        if not token:
                                            break

                                        if (
                                            token.type == TokenType.IDENTIFIER
                                            and token.value.upper() == "END-CALL"
                                        ):
                                            stream.advance()
                                            stmt.not_on_exception = not_exception_statements
                                            break

                                        if token.type == TokenType.PERIOD:
                                            stmt.not_on_exception = not_exception_statements
                                            break

                                        # Parse statement in NOT ON EXCEPTION block
                                        nested_stmt = context.parse_nested_statement(stream)
                                        if nested_stmt:
                                            not_exception_statements.append(nested_stmt)
                                        else:
                                            stream.advance()
                                    break

                            # Not NOT ON EXCEPTION, restore position
                            # We can't easily restore in TokenStream without a transaction
                            # So we just continue from current position

                        # Parse statement in exception handler
                        nested_stmt = context.parse_nested_statement(stream)
                        if nested_stmt:
                            exception_statements.append(nested_stmt)
                        else:
                            # Couldn't parse statement, skip token to avoid infinite loop
                            stream.advance()

                    # Store which type of exception handler we found
                    if exception_type == "EXCEPTION":
                        stmt.on_exception = exception_statements
                    else:
                        stmt.on_overflow = exception_statements

        stream.skip_whitespace_and_comments()

        # Expect period or END-CALL
        token = stream.peek()
        if token and token.type == TokenType.PERIOD:
            stream.advance()

        return stmt

    def _parse_using_parameters(self, stream: TokenStream, stmt: CallStatement) -> None:
        """Parse USING parameters for CALL statement."""
        while not stream.is_at_end:
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if not token:
                break

            # Check for end of parameters
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.IDENTIFIER:
                val = token.value.upper()
                if val in (
                    "RETURNING",
                    "GIVING",
                    "ON",
                    "END-CALL",
                    "EXCEPTION",
                    "OVERFLOW",
                ):
                    break

            # Check for BY REFERENCE/CONTENT/VALUE
            passing_mode = "REFERENCE"  # Default
            if token.type == TokenType.IDENTIFIER and token.value.upper() == "BY":
                stream.advance()  # Skip BY
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    mode_val = token.value.upper()
                    if mode_val in ("REFERENCE", "CONTENT", "VALUE"):
                        passing_mode = mode_val
                        stream.advance()
                        stream.skip_whitespace_and_comments()
                        token = stream.peek()

            # Get parameter name
            if token and token.type == TokenType.IDENTIFIER:
                # Check if it's a keyword that ends the parameter list
                val = token.value.upper()
                if val in (
                    "RETURNING",
                    "GIVING",
                    "ON",
                    "END-CALL",
                    "EXCEPTION",
                    "OVERFLOW",
                ):
                    break
                stmt.add_using_parameter(token.value, passing_mode)
                stream.advance()
            else:
                # Not a parameter, might be end of list
                break
