from typing import Optional, Union
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import PerformStatement, CobolExpression
from ..lexer import TokenType


class PerformStatementParser(StatementParser):
    """Parser for PERFORM statements."""
    token_type = TokenType.PERFORM

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        if token.type == TokenType.PERFORM:
            return True
        if token.type == TokenType.IDENTIFIER and token.value.upper() == "PERFORM":
            return True
        # Recovery: Check if previous token was PERFORM
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.PERFORM or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "PERFORM"
            ):
                return True
        return False
    
    def matches(self, stream: TokenStream) -> bool:
        """IStatementParser interface: Check if this parser can handle the current state."""
        return self.can_parse(stream)
    
    def _report_error(self, context: Optional[ParseContext], message: str, token: Optional[object] = None) -> None:
        """Helper to report errors safely when context may be None."""
        if context:
            context.error(message, token)

    def parse(self, stream: TokenStream, context: Optional[ParseContext] = None) -> PerformStatement:
        """Parse PERFORM statement.

        Supports:
        - PERFORM paragraph-name
        - PERFORM paragraph-name THRU paragraph-name
        - PERFORM UNTIL condition
        - PERFORM TIMES
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        - Inline PERFORM blocks with nested statements
        """
        start_token = stream.peek()
        # Consume PERFORM if present
        if start_token and (
            start_token.type == TokenType.PERFORM
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "PERFORM")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)
        
        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = PerformStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Check for VARYING clause (inline PERFORM)
        token = stream.peek()
        if token and token.value and token.value.upper() == "VARYING":
            self._parse_varying_clause(stream, context, stmt, start_token_loc)
            return stmt

        # Check for TEST clause (WITH TEST BEFORE/AFTER)
        token = stream.peek()
        if token and token.value and token.value.upper() == "WITH":
            stream.advance()  # Skip WITH
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if token and token.value and token.value.upper() == "TEST":
                stream.advance()  # Skip TEST
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if token and token.value:
                    val = token.value.upper()
                    if val in ("BEFORE", "AFTER"):
                        stmt.set_test_timing(val)
                        stream.advance()
                        stream.skip_whitespace_and_comments()

        # Check for UNTIL clause (inline PERFORM UNTIL)
        token = stream.peek()
        if token and token.value and token.value.upper() == "UNTIL":
            self._parse_until_clause(stream, context, stmt, start_token_loc)
            return stmt

        # Check for TIMES clause (inline PERFORM n TIMES)
        token = stream.peek()
        if token and token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
            self._parse_times_clause(stream, context, stmt, start_token_loc)
            return stmt

        # Simple PERFORM paragraph-name
        if token and token.type == TokenType.IDENTIFIER:
            paragraph = token.value
            stmt.set_target_paragraph(paragraph)
            stream.advance()
            stream.skip_whitespace_and_comments()

            # Check for THRU clause
            token = stream.peek()
            if token and token.value and token.value.upper() == "THRU":
                stream.advance()  # Skip THRU
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if token and token.type == TokenType.IDENTIFIER:
                    stmt.set_thru_paragraph(token.value)
                    stream.advance()
                    stream.skip_whitespace_and_comments()
                else:
                    self._report_error(context, "Expected paragraph name after THRU", token)

            # Check for TIMES clause after paragraph name
            token = stream.peek()
            if token and token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                try:
                    times_count = int(token.value)
                    stream.advance()
                    stream.skip_whitespace_and_comments()
                    token = stream.peek()
                    if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                        stream.advance()
                        stmt.set_times_clause(times_count)
                except ValueError:
                    pass

            # Check for UNTIL clause after paragraph name
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if token and token.type == TokenType.UNTIL:
                self._parse_until_condition_only(stream, stmt, start_token_loc)

        # Expect period
        token = stream.peek()
        if token and token.type == TokenType.PERIOD:
            stream.advance()

        return stmt

    def _parse_varying_clause(
        self, stream: TokenStream, context: ParseContext, stmt: PerformStatement, location
    ) -> None:
        """Parse VARYING clause for PERFORM statement."""
        stream.advance()  # Skip VARYING
        stream.skip_whitespace_and_comments()

        # Get variable name
        token = stream.peek()
        if not token or token.type != TokenType.IDENTIFIER:
            self._report_error(context, "Expected variable name after VARYING", token)
            return

        variable_name = token.value
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Expect FROM
        token = stream.peek()
        if not token or not token.value or token.value.upper() != "FROM":
            self._report_error(context, "Expected FROM after variable in VARYING clause", token)
            return
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Get FROM value
        token = stream.peek()
        if not token or not token.value:
            self._report_error(context, "Expected value after FROM", token)
            return
        from_value = token.value
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Expect BY
        token = stream.peek()
        if not token or not token.value or token.value.upper() != "BY":
            self._report_error(context, "Expected BY in VARYING clause", token)
            return
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Get BY value
        token = stream.peek()
        if not token or not token.value:
            self._report_error(context, "Expected value after BY", token)
            return
        by_value = token.value
        stream.advance()
        stream.skip_whitespace_and_comments()

        # Expect UNTIL
        token = stream.peek()
        if not token or not token.value or token.value.upper() != "UNTIL":
            self._report_error(context, "Expected UNTIL in VARYING clause", token)
            return
        stream.advance()

        # Parse condition until newline or statement
        cond_tokens = []
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            if token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                break
            if token.value:
                cond_tokens.append(token.value)
            stream.advance()

        condition_text = " ".join(cond_tokens).strip()
        condition_expr = CobolExpression("IDENTIFIER", location)
        condition_expr._metadata["value"] = condition_text

        # Set VARYING clause
        stmt.set_varying_clause(variable_name, from_value, by_value, condition_expr)

        # Skip newlines after condition
        stream.skip_whitespace_and_comments()

        # Parse inline statements until END-PERFORM
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            # Check for END-PERFORM
            if token.type == TokenType.IDENTIFIER and token.value.upper() == "END-PERFORM":
                stream.advance()
                # Skip optional period
                next_token = stream.peek()
                if next_token and next_token.type == TokenType.PERIOD:
                    stream.advance()
                break

            # Parse nested statement
            nested_stmt = context.parse_nested_statement(stream)
            if nested_stmt:
                stmt.add_inline_statement(nested_stmt)
            else:
                # Skip unknown token
                stream.advance()

    def _parse_until_clause(
        self, stream: TokenStream, context: ParseContext, stmt: PerformStatement, location
    ) -> None:
        """Parse UNTIL clause for inline PERFORM statement."""
        stream.advance()  # Skip UNTIL

        # Parse condition
        cond_tokens = []
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.NEWLINE:
                break
            # Stop at statement keywords
            if token.type in (
                TokenType.PERFORM,
                TokenType.MOVE,
                TokenType.DISPLAY,
                TokenType.CALL,
                TokenType.STOP,
            ):
                break
            cond_tokens.append(token.value)
            stream.advance()

        condition_text = " ".join(cond_tokens).strip() if cond_tokens else None
        if condition_text:
            condition_expr = CobolExpression("IDENTIFIER", location)
            condition_expr._metadata["value"] = condition_text
            stmt.set_until_clause(condition_expr)

        # Skip newlines
        stream.skip_whitespace_and_comments()

        # Parse inline statements until END-PERFORM
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            # Check for END-PERFORM
            if token.type == TokenType.IDENTIFIER and token.value.upper() == "END-PERFORM":
                stream.advance()
                # Skip optional period
                next_token = stream.peek()
                if next_token and next_token.type == TokenType.PERIOD:
                    stream.advance()
                break

            # Parse nested statement
            nested_stmt = context.parse_nested_statement(stream)
            if nested_stmt:
                stmt.add_inline_statement(nested_stmt)
            else:
                stream.advance()

    def _parse_until_condition_only(
        self, stream: TokenStream, stmt: PerformStatement, location
    ) -> None:
        """Parse just the UNTIL condition for paragraph PERFORM."""
        stream.advance()  # Skip UNTIL

        # Parse condition
        cond_tokens = []
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            if token.type in (TokenType.PERIOD, TokenType.NEWLINE):
                break
            # Stop at statement keywords
            if token.type in (
                TokenType.PERFORM,
                TokenType.MOVE,
                TokenType.DISPLAY,
                TokenType.CALL,
                TokenType.STOP,
            ):
                break
            cond_tokens.append(token.value)
            stream.advance()

        condition_text = " ".join(cond_tokens).strip() if cond_tokens else None
        if condition_text:
            condition_expr = CobolExpression("IDENTIFIER", location)
            condition_expr._metadata["value"] = condition_text
            stmt.perform_type = "UNTIL"
            stmt.until_condition = condition_expr

    def _parse_times_clause(
        self,
        stream: TokenStream,
        context: ParseContext,
        stmt: PerformStatement,
        location,
    ) -> None:
        """Parse TIMES clause for inline PERFORM statement."""
        try:
            token = stream.peek()
            if token and token.value:
                times_count = int(token.value)
                stream.advance()
                stream.skip_whitespace_and_comments()

                # Expect TIMES keyword
                token = stream.peek()
                if token and token.value and token.value.upper() in ("TIMES", "TIME"):
                    stream.advance()
                    stmt.set_times_clause(times_count)
                    stream.skip_whitespace_and_comments()
        except ValueError:
            pass

        # Parse inline statements until END-PERFORM
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            # Check for END-PERFORM
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-PERFORM":
                stream.advance()
                # Skip optional period
                next_token = stream.peek()
                if next_token and next_token.type == TokenType.PERIOD:
                    stream.advance()
                break

            # Parse nested statement
            nested_stmt = context.parse_nested_statement(stream)
            if nested_stmt:
                stmt.add_inline_statement(nested_stmt)
            else:
                stream.advance()
