"""Call statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    SCOPE_TERMINATORS,
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    matches_keyword,
    previous_meaningful_token,
    skip_whitespace,
)

from ...core.ast_factory import get_factory
from ...core.exceptions import ParseError
from ...core.interfaces import IStatementParser, ITokenStream, ParseContext
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CallStatement


class CallStatementParser(IStatementParser):
    """Parser for CALL statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.CALL, "CALL")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> CallStatement:
        """Parse a CALL statement.

        Supports:
        - CALL "program-name"  (static)
        - CALL variable-name   (dynamic)
        - CALL ... USING [BY REFERENCE|CONTENT|VALUE] parameters
        - CALL ... RETURNING variable
        - CALL ... GIVING variable
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = cast(
            CallStatement,
            factory.create(
                CallStatement,
                start_token.location if start_token else SourceLocation(0, 0),
            ),
        )

        # Get context for error reporting if available
        parse_ctx: ParseContext | None = token_stream.context
        if parse_ctx is None:
            parse_ctx = getattr(token_stream, "_context", None)
        if parse_ctx is None and hasattr(token_stream, "context"):
            parse_ctx = token_stream.context

        try:
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token:
                # Missing program name
                if parse_ctx:
                    parse_ctx.error(
                        "CALL statement requires a program name (literal or variable)",
                        start_token.location if start_token else SourceLocation(0, 0),
                    )
                return stmt

            # Parse the program name (can be literal or identifier)
            if token.type == TokenType.STRING_LITERAL:
                # Static CALL with literal program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=False)
                token_stream.consume()
            elif token.type == TokenType.IDENTIFIER:
                # Dynamic CALL with variable program name
                program_name = token.value
                stmt.set_called_program(program_name, is_dynamic=True)
                token_stream.consume()
            else:
                # Unknown token type, report error
                if parse_ctx:
                    parse_ctx.error(
                        f"Expected program name (literal or identifier), found {token.type.name if hasattr(token.type, 'name') else str(token.type)}",
                        (
                            token.location
                            if hasattr(token, "location")
                            else SourceLocation(0, 0)
                        ),
                    )
                token_stream.consume()
                return stmt

            # Parse optional USING and RETURNING clauses

            while not token_stream.is_empty():
                skip_whitespace(token_stream)
                token = token_stream.peek()

                if not token:
                    break

                if token.type == TokenType.PERIOD:
                    token_stream.consume()
                    break

                # Check for statement keywords that end the CALL statement
                if token.type in STATEMENT_TOKEN_TYPES:
                    # This is a new statement, not part of CALL
                    break

                if token.type == TokenType.IDENTIFIER and token.value:
                    if (
                        token.value.upper() in STATEMENT_KEYWORDS
                        and token.value.upper() not in ("RETURNING", "GIVING")
                    ):
                        # This is a new statement, not part of CALL
                        break

                # Parse USING clause
                if token.type == TokenType.USING or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "USING"
                ):
                    token_stream.consume()
                    # Parse parameter list until RETURNING or GIVING or PERIOD
                    self._parse_using_clause(token_stream, stmt)
                    continue
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "RETURNING"
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_returning_parameter(token.value)
                        token_stream.consume()
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "GIVING"
                ):
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_giving_parameter(token.value)
                        token_stream.consume()
                elif token.type == TokenType.ON or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "ON"
                ):
                    next_tok = token_stream.peek(1)
                    next_val = (
                        next_tok.value.upper() if next_tok and next_tok.value else ""
                    )
                    if next_val == "EXCEPTION":
                        token_stream.consume()  # ON
                        token_stream.consume()  # EXCEPTION
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"NOT", "END-CALL"}
                        )
                        stmt.on_exception = nested if nested else None
                    elif next_val == "OVERFLOW":
                        token_stream.consume()  # ON
                        token_stream.consume()  # OVERFLOW
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"END-CALL"}
                        )
                        stmt.on_overflow = nested if nested else []
                    else:
                        break
                elif token.type == TokenType.NOT or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "NOT"
                ):
                    # NOT ON EXCEPTION clause
                    t1 = token_stream.peek(1)
                    t2 = token_stream.peek(2)
                    if (
                        t1
                        and t1.value
                        and t1.value.upper() == "ON"
                        and t2
                        and t2.value
                        and t2.value.upper() == "EXCEPTION"
                    ):
                        token_stream.consume()  # NOT
                        token_stream.consume()  # ON
                        token_stream.consume()  # EXCEPTION
                        nested = self._parse_nested_stmts(
                            token_stream, stop_at={"END-CALL"}
                        )
                        stmt.not_on_exception = nested if nested else None
                    else:
                        break
                elif (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-CALL"
                ):
                    token_stream.consume()  # consume END-CALL
                    break
                else:
                    # Skip unknown tokens or end of CALL statement
                    break
        except ParseError:
            pass

        return stmt

    def _parse_nested_stmts(self, token_stream: ITokenStream, stop_at: set) -> list:
        """Parse statements until a stop keyword is found.

        Used for ON EXCEPTION / NOT ON EXCEPTION clause bodies.
        Returns list of CobolStatement objects.
        """
        stmts = []
        registry = getattr(token_stream, "_registry", None)
        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()
            if not token:
                break
            val = token.value.upper() if token.value else ""
            if val in stop_at or val == ".":
                break
            if registry:
                parser = registry.find_parser(token_stream)
                if parser:
                    try:
                        nested_stmt = parser.parse(token_stream)
                        stmts.append(nested_stmt)
                        # A nested statement that consumed the sentence-
                        # terminating period ends the handler body.
                        prev = previous_meaningful_token(token_stream)
                        if prev is not None and prev.type == TokenType.PERIOD:
                            break
                    except ParseError:
                        token_stream.consume()
                else:
                    token_stream.consume()
            else:
                token_stream.consume()
        return stmts

    def _parse_using_clause(
        self, token_stream: ITokenStream, stmt: CallStatement
    ) -> None:
        """Parse USING clause with optional BY REFERENCE|CONTENT|VALUE modifiers."""

        while not token_stream.is_empty():
            skip_whitespace(token_stream)
            token = token_stream.peek()

            if not token or token.type == TokenType.PERIOD:
                break

            # Check for end of USING clause
            if token.type == TokenType.IDENTIFIER and token.value:
                val_upper = token.value.upper()
                if val_upper in ("RETURNING", "GIVING", "ON"):
                    break
                # Check for statement keywords
                if val_upper in STATEMENT_KEYWORDS:
                    break
                # Scope terminators of an enclosing statement (e.g. END-READ
                # when this CALL is an AT END clause body) end the parameters.
                if val_upper in SCOPE_TERMINATORS:
                    break
            # Check for statement token types
            elif token.type in STATEMENT_TOKEN_TYPES:
                break
            # Check for non-parameter tokens (like NUMERIC_LITERAL), end of USING clause
            elif token.type not in (
                TokenType.BY,
                TokenType.USING,
            ) and token.type not in (
                TokenType.IDENTIFIER,
                TokenType.STRING_LITERAL,
                TokenType.VALUE,
            ):
                break

            # Check for BY [REFERENCE|CONTENT|VALUE]
            passing_mode = "REFERENCE"  # Default
            if token.type == TokenType.BY or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "BY"
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                token = token_stream.peek()
                if token and (
                    token.type == TokenType.IDENTIFIER or token.type == TokenType.VALUE
                ):
                    mode_val = token.value.upper() if token.value else ""
                    if mode_val in ("REFERENCE", "CONTENT", "VALUE"):
                        passing_mode = mode_val
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        token = token_stream.peek()

            # Parse parameter name
            if token and token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                param_name = token.value
                stmt.add_using_parameter(param_name, passing_mode)
                token_stream.consume()
            else:
                # No parameter found, end of USING clause
                break
