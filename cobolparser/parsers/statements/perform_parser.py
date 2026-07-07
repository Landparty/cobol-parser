"""Perform statement parser implementing IStatementParser interface."""

from typing import Any, cast

from cobolparser.parsers.statements._utils import (
    STATEMENT_KEYWORDS,
    STATEMENT_TOKEN_TYPES,
    get_parse_context,
    matches_keyword,
    report_parse_error,
    skip_whitespace,
    try_parse_nested_statement,
)

from ...core.ast_factory import get_factory
from ...core.exceptions import ParseError, TokenMismatch, UnexpectedEndOfInput
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CobolExpression, PerformStatement


class PerformStatementParser(IStatementParser):
    """Parser for PERFORM statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.PERFORM, "PERFORM")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> PerformStatement:
        """Parse a PERFORM statement.

        Supports:
        - PERFORM paragraph-name
        - PERFORM paragraph-name THRU paragraph-name
        - PERFORM UNTIL condition
        - PERFORM TIMES
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        - Inline PERFORM blocks with nested statements
        """
        # Consume PERFORM keyword
        start_token = token_stream.consume()
        factory = get_factory()

        # Create statement with source location
        location = start_token.location if start_token else SourceLocation(0, 0)
        stmt = cast(PerformStatement, factory.create(PerformStatement, location))
        context = get_parse_context(token_stream)

        # Skip whitespace/comments if possible
        skip_whitespace(token_stream)

        # Try to get the next meaningful token (peek without consuming)
        try:
            token = token_stream.peek()
        except UnexpectedEndOfInput:
            # End of stream
            return stmt

        if not token:
            report_parse_error(
                context,
                "PERFORM statement requires a target paragraph or inline clause",
                location,
            )
            return stmt

        if token.type == TokenType.PERIOD:
            report_parse_error(
                context,
                "PERFORM statement requires a target paragraph or inline clause",
                location,
            )
            token_stream.consume()
            return stmt

        # Check for VARYING clause (inline PERFORM VARYING)
        if token.type == TokenType.VARYING:
            self._parse_varying_clause(token_stream, stmt)
            return stmt

        # Check for TEST clause (WITH TEST BEFORE/AFTER)
        if token.type == TokenType.WITH:
            try:
                token_stream.consume()  # Skip WITH
                token = token_stream.peek()
                if token and token.type == TokenType.TEST:
                    token_stream.consume()  # Skip TEST
                    token = token_stream.peek()
                    if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                        val = token.type.name  # "BEFORE" or "AFTER"
                        stmt.set_test_timing(val)
                        token_stream.consume()
                        token = token_stream.peek()
            except (TokenMismatch, UnexpectedEndOfInput):
                pass
            skip_whitespace(token_stream)
            token = token_stream.peek()

        # Check for UNTIL clause (inline PERFORM UNTIL)
        if token and token.type == TokenType.UNTIL:
            self._parse_until_clause(token_stream, stmt)
            return stmt

        # Check for TIMES clause (inline PERFORM n TIMES)
        # Check for numeric literals: TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER, or numeric IDENTIFIER
        if token and (
            token.type == TokenType.NUMERIC_LITERAL
            or token.type == TokenType.LEVEL_NUMBER
            or (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.isdigit()
            )
        ):
            try:
                times_count = int(token.value)
                token_stream.consume()
                token = token_stream.peek()
                # Check for TIMES keyword: TokenType.TIMES or IDENTIFIER "TIMES"
                if token and (
                    token.type == TokenType.TIMES
                    or (
                        token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() in ("TIMES", "TIME")
                    )
                ):
                    token_stream.consume()
                    stmt.set_times_clause(times_count)
                    # Parse inline statements until END-PERFORM
                    self._parse_inline_statements(token_stream, stmt)
                    return stmt
            except (ValueError, TokenMismatch, UnexpectedEndOfInput):
                pass

            skip_whitespace(token_stream)
            token = token_stream.peek()

        # Simple PERFORM paragraph-name
        if token and token.type == TokenType.IDENTIFIER:
            paragraph = token.value
            stmt.set_target_paragraph(paragraph)
            try:
                token_stream.consume()
                token = token_stream.peek()
            except (TokenMismatch, UnexpectedEndOfInput):
                token = None

            skip_whitespace(token_stream)
            token = token_stream.peek()

            # Check for THRU clause (THROUGH is a standard COBOL synonym)
            if (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in ("THRU", "THROUGH")
            ):
                try:
                    token_stream.consume()  # Skip THRU/THROUGH
                    token = token_stream.peek()
                    if token and token.type == TokenType.IDENTIFIER:
                        stmt.set_thru_paragraph(token.value)
                        token_stream.consume()
                        token = token_stream.peek()
                    else:
                        report_parse_error(
                            context,
                            "PERFORM THRU requires an ending paragraph name",
                            location,
                        )
                except (TokenMismatch, UnexpectedEndOfInput):
                    pass

                skip_whitespace(token_stream)
                token = token_stream.peek()

            # Check for TIMES clause after paragraph name (can be numeric or variable)
            if token and token.type == TokenType.IDENTIFIER:
                times_value = token.value
                token_stream.consume()
                token = token_stream.peek()

                # Check if  followed by TIMES keyword
                if token and (
                    token.type == TokenType.TIMES
                    or (
                        token.type == TokenType.IDENTIFIER
                        and token.value
                        and token.value.upper() in ("TIMES", "TIME")
                    )
                ):
                    # Can be numeric (int) or variable (string)
                    para_times_count: Any
                    try:
                        para_times_count = int(times_value)
                    except ValueError:
                        para_times_count = times_value  # Keep as variable name string

                    token_stream.consume()  # Skip TIMES keyword
                    stmt.set_times_clause(para_times_count)
                    token = token_stream.peek()
            elif token and (
                token.type == TokenType.NUMERIC_LITERAL
                or token.type == TokenType.LEVEL_NUMBER
            ):
                try:
                    num_times_count = int(token.value)
                    token_stream.consume()
                    token = token_stream.peek()
                    if token and (
                        token.type == TokenType.TIMES
                        or (
                            token.type == TokenType.IDENTIFIER
                            and token.value
                            and token.value.upper() in ("TIMES", "TIME")
                        )
                    ):
                        token_stream.consume()
                        stmt.set_times_clause(num_times_count)
                        token = token_stream.peek()
                except (ValueError, TokenMismatch, UnexpectedEndOfInput):
                    pass

            skip_whitespace(token_stream)
            token = token_stream.peek()

            # Check for WITH TEST clause after paragraph name (WITH TEST BEFORE/AFTER)
            if token and token.type == TokenType.WITH:
                try:
                    token_stream.consume()  # Skip WITH
                    token = token_stream.peek()
                    if token and token.type == TokenType.TEST:
                        token_stream.consume()  # Skip TEST
                        token = token_stream.peek()
                        if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                            val = token.type.name  # "BEFORE" or "AFTER"
                            stmt.set_test_timing(val)
                            token_stream.consume()
                            token = token_stream.peek()
                except (TokenMismatch, UnexpectedEndOfInput):
                    pass

                skip_whitespace(token_stream)
                token = token_stream.peek()

            # Check for UNTIL clause after paragraph name
            if token and token.type == TokenType.UNTIL:
                try:
                    self._parse_until_condition_only(token_stream, stmt)
                except ParseError:
                    pass

        # Expect period or END-PERFORM
        try:
            token = token_stream.peek()
            if token and token.type == TokenType.PERIOD:
                token_stream.consume()
            elif (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "END-PERFORM"
            ):
                token_stream.consume()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

        return stmt

    def _parse_varying_clause(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse VARYING clause for PERFORM statement."""
        try:
            stream.consume()  # Skip VARYING
            skip_whitespace(stream)

            # Get variable name
            token = stream.peek()
            if not token or token.type != TokenType.IDENTIFIER:
                return

            variable_name = token.value
            stream.consume()
            skip_whitespace(stream)

            # Expect FROM
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "FROM":
                return
            stream.consume()
            skip_whitespace(stream)

            # Get FROM value
            token = stream.peek()
            if not token or not token.value:
                return
            from_value = token.value
            stream.consume()
            skip_whitespace(stream)

            # Expect BY
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "BY":
                return
            stream.consume()
            skip_whitespace(stream)

            # Get BY value
            token = stream.peek()
            if not token or not token.value:
                return
            by_value = token.value
            stream.consume()
            skip_whitespace(stream)

            # Check for WITH TEST clause (before UNTIL)
            token = stream.peek()
            if token and token.type == TokenType.WITH:
                try:
                    stream.consume()  # Skip WITH
                    token = stream.peek()
                    if token and token.type == TokenType.TEST:
                        stream.consume()  # Skip TEST
                        token = stream.peek()
                        if token and token.type in (TokenType.BEFORE, TokenType.AFTER):
                            val = token.type.name  # "BEFORE" or "AFTER"
                            stmt.set_test_timing(val)
                            stream.consume()
                            token = stream.peek()
                except (TokenMismatch, UnexpectedEndOfInput):
                    pass

                skip_whitespace(stream)
                token = stream.peek()

            # Parse UNTIL condition
            token = stream.peek()
            if token and token.type == TokenType.UNTIL:
                until_condition = self._collect_until_expression(stream)
                if until_condition:
                    stmt.set_varying_clause(
                        variable_name, from_value, by_value, until_condition
                    )

            # Parse AFTER dimensions (PERFORM VARYING ... AFTER ... — 2-D/3-D
            # table loops). Each AFTER phrase repeats var FROM x BY y [UNTIL c].
            self._parse_after_clauses(stream, stmt)

            # Parse the inline body (up to END-PERFORM or period)
            self._parse_inline_statements(stream, stmt)
        except ParseError:
            pass

    def _parse_after_clauses(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse zero or more AFTER dimensions of a PERFORM VARYING clause."""
        while True:
            skip_whitespace(stream)
            token = stream.peek()
            if not token or not (
                token.type == TokenType.AFTER
                or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "AFTER"
                )
            ):
                return
            stream.consume()  # Skip AFTER
            skip_whitespace(stream)

            # Variable name
            token = stream.peek()
            if not token or token.type != TokenType.IDENTIFIER:
                return
            variable_name = token.value
            stream.consume()
            skip_whitespace(stream)

            # Expect FROM
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "FROM":
                stmt.add_after_clause(variable_name, "", "")
                return
            stream.consume()
            skip_whitespace(stream)
            token = stream.peek()
            if not token or not token.value:
                stmt.add_after_clause(variable_name, "", "")
                return
            from_value = token.value
            stream.consume()
            skip_whitespace(stream)

            # Expect BY
            token = stream.peek()
            if not token or not token.value or token.value.upper() != "BY":
                stmt.add_after_clause(variable_name, from_value, "")
                return
            stream.consume()
            skip_whitespace(stream)
            token = stream.peek()
            if not token or not token.value:
                stmt.add_after_clause(variable_name, from_value, "")
                return
            by_value = token.value
            stream.consume()
            skip_whitespace(stream)

            # Optional UNTIL condition for this dimension
            until_condition = None
            token = stream.peek()
            if token and token.type == TokenType.UNTIL:
                until_condition = self._collect_until_expression(stream)
            stmt.add_after_clause(variable_name, from_value, by_value, until_condition)

    def _collect_until_condition_tokens(
        self, stream: ITokenStream, for_varying: bool = False
    ) -> list:
        """Consume tokens forming a UNTIL condition and return them as strings.

        When *for_varying* is True, also stops on IDENTIFIER tokens whose value
        matches known statement keywords (extra guard needed for VARYING context).
        """
        tokens: list = []
        while True:
            token = stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.END_PERFORM:
                break
            # AFTER starts the next dimension of a PERFORM VARYING ... AFTER
            # loop — stop without consuming so the whole AFTER phrase isn't
            # absorbed into the condition string. Only applies in the
            # VARYING context (for_varying=True): a plain PERFORM UNTIL has
            # no AFTER clause of its own, so gating this on for_varying
            # avoids truncating a condition that happens to reference an
            # AFTER-named identifier or reserved word elsewhere.
            if for_varying and (
                token.type == TokenType.AFTER
                or (token.value and token.value.upper() == "AFTER")
            ):
                break
            if token.type in STATEMENT_TOKEN_TYPES:
                break
            if for_varying and (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() in STATEMENT_KEYWORDS
            ):
                break
            tokens.append(token.value or str(token.type))
            stream.consume()
        return tokens

    def _parse_until_clause(self, stream: ITokenStream, stmt: PerformStatement) -> None:
        """Parse UNTIL clause for an inline PERFORM."""
        try:
            stream.consume()  # Skip UNTIL
            skip_whitespace(stream)
            condition_tokens = self._collect_until_condition_tokens(stream)
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                condition_expr = CobolExpression("CONDITION", SourceLocation(0, 0))
                condition_expr.operands = [condition_str]
                stmt.set_until_clause(condition_expr)
            self._parse_inline_statements(stream, stmt)
        except ParseError:
            pass

    def _collect_until_expression(self, stream: ITokenStream) -> CobolExpression | None:
        """Consume an UNTIL keyword + condition and return it as an expression.

        Unlike :meth:`_parse_until_clause`, this does NOT parse the inline
        body — the caller decides what follows (an AFTER dimension may
        intervene in PERFORM VARYING ... AFTER ... loops).
        """
        try:
            stream.consume()  # Skip UNTIL
            skip_whitespace(stream)
            condition_tokens = self._collect_until_condition_tokens(
                stream, for_varying=True
            )
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                condition_expr = CobolExpression("CONDITION", SourceLocation(0, 0))
                condition_expr.operands = [condition_str]
                return condition_expr
        except ParseError:
            pass
        return None

    def _parse_until_condition_only(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse just the UNTIL condition after paragraph name."""
        try:
            _ut = stream.peek()
            if _ut and _ut.value and _ut.value.upper() == "UNTIL":
                stream.consume()

            skip_whitespace(stream)

            # Parse condition (simplified)
            condition_tokens = []
            while True:
                token = stream.peek()
                if not token:
                    break
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break
                if (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-PERFORM"
                ):
                    stream.consume()
                    break

                condition_tokens.append(token.value or str(token.type))
                stream.consume()

            # Create CobolExpression for the condition and set it on statement
            if condition_tokens:
                condition_str = " ".join(condition_tokens).strip()
                location = SourceLocation(0, 0)  # Default location
                condition_expr = CobolExpression("CONDITION", location)
                condition_expr.operands = [condition_str]
                stmt.set_until_clause(condition_expr)
        except (TokenMismatch, UnexpectedEndOfInput):
            pass

    def _parse_inline_statements(
        self, stream: ITokenStream, stmt: PerformStatement
    ) -> None:
        """Parse inline statements within PERFORM ... END-PERFORM block."""
        try:
            skip_whitespace(stream)

            # Parse statements until END-PERFORM or PERIOD
            while not stream.is_empty():
                skip_whitespace(stream)
                token = stream.peek()

                if not token:
                    break

                # Check for END-PERFORM
                if token.type == TokenType.END_PERFORM or (
                    token.type == TokenType.IDENTIFIER
                    and token.value
                    and token.value.upper() == "END-PERFORM"
                ):
                    stream.consume()
                    # Skip optional period
                    self._try_consume_period(stream)
                    break

                # Check for PERIOD (inline PERFORM without END-PERFORM)
                if token.type == TokenType.PERIOD:
                    stream.consume()
                    break

                # Try to parse nested statement
                nested_stmt = try_parse_nested_statement(stream)
                if nested_stmt:
                    stmt.add_inline_statement(nested_stmt)
                else:
                    # Can't parse, skip token
                    stream.consume()
        except ParseError:
            pass

    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        try:
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()
        except (TokenMismatch, UnexpectedEndOfInput):
            pass
