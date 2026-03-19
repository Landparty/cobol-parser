from typing import Optional, List
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import IfStatement, CobolExpression
from ..lexer import TokenType


class IfStatementParser(StatementParser):
    """Parser for IF statements."""
    token_type = TokenType.IF

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        if token.type == TokenType.IF:
            return True
        if token.type == TokenType.IDENTIFIER and token.value.upper() == "IF":
            return True
        # Recovery: Check if previous token was IF
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.IF or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "IF"
            ):
                return True
        return False

    def parse(self, stream: TokenStream, context: ParseContext) -> IfStatement:
        """Parse IF statement with THEN/ELSE branches and END-IF terminator.

        Supports:
        - IF condition THEN statements END-IF
        - IF condition THEN statements ELSE statements END-IF
        - Nested statements in both branches
        """
        start_token = stream.peek()
        # Consume IF if present
        if start_token and (
            start_token.type == TokenType.IF
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "IF")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)
        
        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = IfStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse condition until THEN or newline
        cond_tokens = []
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break
            if token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                break
            if token.value and token.value.upper() == "THEN":
                break
            if token.value:
                cond_tokens.append(token.value)
            stream.advance()

        condition_text = " ".join(cond_tokens).strip()
        condition_expr = CobolExpression("COMPARISON", start_token_loc)
        condition_expr._metadata["value"] = condition_text
        stmt.set_condition(condition_expr)

        # Skip THEN keyword if present
        token = stream.peek()
        if token and token.value and token.value.upper() == "THEN":
            stream.advance()

        # Skip newlines after condition/THEN
        stream.skip_whitespace_and_comments()

        # Parse THEN branch statements until ELSE or END-IF
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            # Check for ELSE
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "ELSE":
                stream.advance()
                break

            # Check for END-IF
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-IF":
                stream.advance()
                # Skip optional period
                next_token = stream.peek()
                if next_token and next_token.type == TokenType.PERIOD:
                    stream.advance()
                return stmt

            # Skip newlines/comments
            if token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                stream.advance()
                continue

            # Parse nested statement
            nested_stmt = context.parse_nested_statement(stream)
            if nested_stmt:
                stmt.add_then_statement(nested_stmt)
            else:
                # Unable to parse statement, skip token
                stream.advance()

        # Skip newlines after ELSE
        stream.skip_whitespace_and_comments()

        # Parse ELSE branch statements until END-IF
        while not stream.is_at_end:
            token = stream.peek()
            if not token:
                break

            # Check for END-IF
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "END-IF":
                stream.advance()
                # Skip optional period
                next_token = stream.peek()
                if next_token and next_token.type == TokenType.PERIOD:
                    stream.advance()
                break

            # Skip newlines/comments
            if token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                stream.advance()
                continue

            # Parse nested statement
            nested_stmt = context.parse_nested_statement(stream)
            if nested_stmt:
                stmt.add_else_statement(nested_stmt)
            else:
                # Unable to parse statement, skip token
                stream.advance()

        return stmt
