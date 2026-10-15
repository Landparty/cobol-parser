"""If statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._conditions import (
    COMPARISON_OPS,
    build_condition_expression,
    condition_token_text,
    find_top_level_operator,
    strip_enclosing_parens,
)
from cobolparser.parsers.statements._utils import (
    LITERAL_TOKEN_TYPES,
    STATEMENT_KEYWORDS,
    get_parse_context,
    is_bare_separator,
    keyword_upper,
    matches_keyword,
    paren_depth_after,
    report_parse_error,
    skip_statement_separators,
    skip_whitespace,
    try_parse_nested_statement,
)

from ...core.ast_factory import get_factory
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CobolExpression, IfStatement


class IfStatementParser(IStatementParser):
    """Parser for IF statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.IF, "IF")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IfStatement:
        """Parse an IF statement with nested statement support.

        Supports:
        - IF condition statement [ELSE statement] [END-IF]
        - IF condition THEN statement [ELSE statement] [END-IF]
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(
            IfStatement, start_token.location if start_token else SourceLocation(0, 0)
        )
        context = get_parse_context(token_stream)

        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(
                start_token.location if start_token else SourceLocation(0, 0)
            )

        skip_whitespace(token_stream)

        # Parse condition tokens - stop at THEN or statement keyword
        condition_tokens: list[str] = []
        paren_depth = 0
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or not token.value:
                break

            # Skip layout tokens (whitespace, end-of-line, continuation,
            # comments) so they never enter the condition token list. A
            # trailing "\n" would otherwise defeat the enclosing-paren strip in
            # _build_condition_expression (making tokens[-1] != ")"), and stray
            # tokens muddy operand strings for multi-line conditions.
            if token.type in (
                TokenType.WHITESPACE,
                TokenType.NEWLINE,
                TokenType.CONTINUATION,
                TokenType.COMMENT,
            ):
                token_stream.consume()
                continue
            # A separator comma/semicolon is a space (#386): ``IF X = 1,``
            # must not leave ``1 ,`` as the right operand.
            if is_bare_separator(token, paren_depth):
                token_stream.consume()
                continue

            token_upper = token.value.upper()
            # THEN / ELSE / END-IF only as words: IF X = "ELSE" compares
            # against a literal (the lexer strips its quotes).
            word = keyword_upper(token)

            # Stop at explicit THEN
            if word == "THEN":
                break

            # Stop at statement keywords (implicit THEN) -- but a literal
            # spelled like a verb (``IF X = "IF"``) is condition content.
            if token.type not in LITERAL_TOKEN_TYPES and self._is_statement_keyword(
                token_upper
            ):
                break

            # Stop at ELSE or END-IF
            if word in ("ELSE", "END-IF"):
                break

            # Stop at period
            if token.type == TokenType.PERIOD:
                break

            # Add token to condition
            paren_depth = paren_depth_after(token, paren_depth)
            condition_tokens.append(condition_token_text(token))
            token_stream.consume()

        # Create condition expression tree
        loc = start_token.location if start_token else SourceLocation(0, 0)
        if condition_tokens:
            condition_expr = self._build_condition_expression(condition_tokens, loc)
            if condition_expr:
                stmt.set_condition(condition_expr)
            else:
                report_parse_error(
                    context,
                    "IF statement: could not parse condition expression",
                    loc,
                )
        else:
            report_parse_error(
                context,
                "IF statement requires a condition before the THEN branch",
                loc,
            )

        skip_whitespace(token_stream)

        # Skip explicit THEN keyword if present
        if not token_stream.is_empty():
            token = token_stream.peek()
            if token and token.value and token.value.upper() == "THEN":
                token_stream.consume()
                skip_whitespace(token_stream)

        # Parse THEN branch statements until ELSE, END-IF, or period
        period_found = False
        while not token_stream.is_empty():
            skip_statement_separators(token_stream)

            if token_stream.is_empty():
                break

            token = token_stream.peek()
            if not token:
                break

            token_upper = token.value.upper() if token.value else ""

            # End of THEN branch at ELSE
            if token_upper == "ELSE":
                token_stream.consume()
                skip_whitespace(token_stream)
                period_found = False  # Reset for ELSE branch
                break

            # End of IF statement at END-IF
            if token_upper == "END-IF":
                token_stream.consume()
                self._try_consume_period(token_stream)
                return stmt

            # End of IF statement at period (when not in a multi-line block)
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt

            # If we already found a period terminating the previous statement,
            # don't parse more (this means inline IF)
            if period_found:
                break

            # Try to parse nested statement
            nested_stmt = try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_then_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                skip_whitespace(token_stream)
                if previous_token and previous_token.type == TokenType.PERIOD:
                    return stmt
                if not token_stream.is_empty():
                    next_token = token_stream.peek()
                    if next_token and next_token.type == TokenType.PERIOD:
                        period_found = True
            else:
                # Couldn't parse - stop trying to parse statements in this branch
                break

        # Parse ELSE branch statements until END-IF or period
        period_found = False
        while not token_stream.is_empty():
            skip_statement_separators(token_stream)

            if token_stream.is_empty():
                break

            token = token_stream.peek()
            if not token:
                break

            token_upper = token.value.upper() if token.value else ""

            # End of IF statement at END-IF
            if token_upper == "END-IF":
                token_stream.consume()
                self._try_consume_period(token_stream)
                return stmt

            # End of IF statement at period
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                return stmt

            # If we already found a period terminating the previous statement,
            # don't parse more (this means inline IF-ELSE)
            if period_found:
                break

            # Try to parse nested statement
            nested_stmt = try_parse_nested_statement(token_stream)
            if nested_stmt:
                stmt.add_else_statement(nested_stmt)
                previous_token = self._previous_meaningful_token(token_stream)
                skip_whitespace(token_stream)
                if previous_token and previous_token.type == TokenType.PERIOD:
                    return stmt
                if not token_stream.is_empty():
                    next_token = token_stream.peek()
                    if next_token and next_token.type == TokenType.PERIOD:
                        period_found = True
            else:
                # Couldn't parse - stop trying to parse statements in this branch
                break

        return stmt

    # Kept as a class attribute for backward compatibility; the canonical
    # table now lives in cobolparser.parsers.statements._conditions (M12).
    _COMPARISON_OPS = COMPARISON_OPS

    def _build_condition_expression(
        self, tokens: list[str], location: SourceLocation
    ) -> CobolExpression | None:
        """Convert a flat list of condition token strings into an expression tree.

        Delegates to the shared condition machinery in
        :mod:`cobolparser.parsers.statements._conditions`, which is also
        used by the PERFORM parser to decompose UNTIL conditions (M12).
        """
        return build_condition_expression(tokens, location)

    @staticmethod
    def _strip_enclosing_parens(tokens: list[str]) -> list[str]:
        """Delegate to the shared :func:`strip_enclosing_parens` (M12)."""
        return strip_enclosing_parens(tokens)

    @staticmethod
    def _find_top_level_operator(tokens: list[str], op: str) -> int | None:
        """Delegate to the shared :func:`find_top_level_operator` (M12)."""
        return find_top_level_operator(tokens, op)

    def _is_statement_keyword(self, token_upper: str) -> bool:
        """Check if token is a COBOL statement keyword."""
        return token_upper in STATEMENT_KEYWORDS

    def _try_consume_period(self, stream: ITokenStream) -> None:
        """Try to consume a period if present."""
        if not stream.is_empty():
            token = stream.peek()
            if token and token.type == TokenType.PERIOD:
                stream.consume()

    @staticmethod
    def _previous_meaningful_token(stream: ITokenStream) -> Any | None:
        """Return the last non-whitespace token consumed by the stream."""
        offset = -1
        while True:
            token = stream.peek(offset)
            if token is None:
                return None
            if token.type.name not in (
                "WHITESPACE",
                "COMMENT",
                "NEWLINE",
                "CONTINUATION",
            ):
                return token
            offset -= 1
