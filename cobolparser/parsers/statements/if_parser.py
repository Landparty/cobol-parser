"""If statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    get_parse_context,
    report_parse_error,
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
        """Check if next token is IF keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            return bool(token.type == TokenType.IF or
                    (token.type == TokenType.IDENTIFIER and token.value and
                     token.value.upper() == "IF"))
        except Exception:
            return False

    def parse(self, token_stream: ITokenStream, context: Any | None = None) -> IfStatement:
        """Parse an IF statement with nested statement support.

        Supports:
        - IF condition statement [ELSE statement] [END-IF]
        - IF condition THEN statement [ELSE statement] [END-IF]
        """
        start_token = token_stream.consume()
        factory = get_factory()
        stmt = factory.create(IfStatement, start_token.location if start_token else SourceLocation(0, 0))
        context = get_parse_context(token_stream)

        # Type guard: ensure stmt is an IfStatement
        if not isinstance(stmt, IfStatement):
            stmt = IfStatement(start_token.location if start_token else SourceLocation(0, 0))

        skip_whitespace(token_stream)

        # Parse condition tokens - stop at THEN or statement keyword
        condition_tokens: list[str] = []
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token or not token.value:
                break

            token_upper = token.value.upper()

            # Stop at explicit THEN
            if token_upper == "THEN":
                break

            # Stop at statement keywords (implicit THEN)
            if self._is_statement_keyword(token_upper):
                break

            # Stop at ELSE or END-IF
            if token_upper in ("ELSE", "END-IF"):
                break

            # Stop at period
            if token.type == TokenType.PERIOD:
                break

            # Add token to condition
            condition_tokens.append(token.value)
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
            skip_whitespace(token_stream)

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
            skip_whitespace(token_stream)

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

    _COMPARISON_OPS = {
        "=": "EQUAL",
        "EQUAL": "EQUAL",
        ">": "GREATER",
        "GREATER": "GREATER",
        "<": "LESS",
        "LESS": "LESS",
        ">=": "GREATER_OR_EQUAL",
        "<=": "LESS_OR_EQUAL",
        "<>": "NOT_EQUAL",
    }

    def _build_condition_expression(
        self, tokens: list[str], location: SourceLocation
    ) -> CobolExpression | None:
        """Convert a flat list of condition token strings into an expression tree.

        Handles simple comparisons (LHS op RHS), NOT-prefixed operators, and
        compound conditions joined by AND / OR.
        """
        from cobolparser.models.statements.base import (
            ConditionalExpression,
            LogicalExpression,
        )

        # Normalise multi-word operators ("NOT LESS", "NOT EQUAL", etc.)
        cleaned: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "NOT" and i + 1 < len(tokens):
                nxt = tokens[i + 1].upper()
                combined = {
                    "NOT EQUAL": "NOT_EQUAL",
                    "NOT =": "NOT_EQUAL",
                    "NOT LESS": "GREATER_OR_EQUAL",
                    "NOT <": "GREATER_OR_EQUAL",
                    "NOT GREATER": "LESS_OR_EQUAL",
                    "NOT >": "LESS_OR_EQUAL",
                }.get(f"NOT {nxt}")
                if combined:
                    cleaned.append(combined)
                    i += 2
                    continue
            cleaned.append(tokens[i])
            i += 1

        # Split on AND / OR (left-to-right, lowest precedence)
        for logical_op in ("AND", "OR"):
            upper_cleaned = [t.upper() for t in cleaned]
            if logical_op in upper_cleaned:
                idx = upper_cleaned.index(logical_op)
                left_expr = self._build_condition_expression(cleaned[:idx], location)
                right_expr = self._build_condition_expression(cleaned[idx + 1:], location)
                if left_expr and right_expr:
                    logical = LogicalExpression(logical_op, location)
                    logical.set_left_condition(left_expr)
                    logical.set_right_condition(right_expr)
                    return logical

        # Simple comparison: find the first comparison operator token
        upper_cleaned = [t.upper() for t in cleaned]
        op_idx = None
        resolved_op = None
        for idx, tok in enumerate(upper_cleaned):
            if tok in self._COMPARISON_OPS:
                op_idx = idx
                resolved_op = self._COMPARISON_OPS[tok]
                break
            if tok in ("NOT_EQUAL", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"):
                op_idx = idx
                resolved_op = tok
                break

        if op_idx is not None and resolved_op:
            left_parts = [t for t in cleaned[:op_idx] if t.upper() != "IS"]
            right_parts = cleaned[op_idx + 1:]
            lhs = " ".join(left_parts).strip() if left_parts else None
            rhs = " ".join(right_parts).strip() if right_parts else None
            if lhs:
                expr = ConditionalExpression(resolved_op, location)
                expr.set_left_operand(lhs)
                if rhs:
                    expr.set_right_operand(rhs)
                return expr

        # Fallback: wrap entire token list as a raw comparison node
        if cleaned:
            expr = ConditionalExpression("COMPARISON", location)
            expr._metadata["raw_condition"] = " ".join(cleaned)
            return expr

        return None

    def _is_statement_keyword(self, token_upper: str) -> bool:
        """Check if token is a COBOL statement keyword."""
        statement_keywords = {
            "MOVE", "DISPLAY", "CALL", "PERFORM", "IF", "EVALUATE",
            "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
            "ACCEPT", "READ", "WRITE", "OPEN", "CLOSE",
            "STOP", "GO", "ENTRY", "EXEC", "EXIT",
            "SEARCH", "STRING", "UNSTRING", "INSPECT",
            "ALTER", "CONTINUE", "INITIATE", "TERMINATE",
            "MERGE", "SORT", "RELEASE", "RETURN"
        }
        return token_upper in statement_keywords

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
            if token.type.name not in ('WHITESPACE', 'COMMENT', 'NEWLINE', 'CONTINUATION'):
                return token
            offset -= 1

