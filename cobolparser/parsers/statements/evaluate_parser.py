"""Evaluate statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    STATEMENT_KEYWORDS,
    get_parse_context,
    report_parse_error,
    try_parse_nested_statement,
)

from ...core.exceptions import ParseError
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import EvaluateStatement, WhenClause


class EvaluateStatementParser(IStatementParser):
    """Parser for EVALUATE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token is EVALUATE keyword."""
        try:
            token = token_stream.peek()
            if not token:
                return False
            is_evaluate = token.type == TokenType.EVALUATE
            is_evaluate_id = (
                token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "EVALUATE"
            )
            return bool(is_evaluate or is_evaluate_id)
        except Exception:
            return False

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> EvaluateStatement:
        """Parse an EVALUATE statement with contract-level diagnostics."""
        try:
            start_token = token_stream.consume()
            if not start_token:
                raise Exception("Expected EVALUATE keyword")

            start_location = (
                start_token.location
                if hasattr(start_token, "location")
                else SourceLocation(0, 0)
            )
            stmt = EvaluateStatement(start_location)
            context = get_parse_context(token_stream)

            subject_count = self._parse_subjects(token_stream, stmt)

            found_when_clause = False
            found_end_evaluate = False
            found_when_other = False

            while not token_stream.is_empty():
                token = token_stream.peek()
                if not token:
                    break

                token_val_upper = token.value.upper() if token.value else ""

                if token_val_upper == "END-EVALUATE":
                    token_stream.consume()
                    found_end_evaluate = True
                    break

                if token_val_upper != "WHEN":
                    token_stream.consume()
                    continue

                found_when_clause = True
                when_location = (
                    token.location if hasattr(token, "location") else start_location
                )
                token_stream.consume()

                next_token = token_stream.peek()
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "OTHER"
                ):
                    token_stream.consume()
                    if found_when_other:
                        report_parse_error(
                            context,
                            "Multiple WHEN OTHER clauses not allowed",
                            when_location,
                        )
                    found_when_other = True
                    stmt.default_when = WhenClause([], when_location)
                    statements = self._skip_clause_statements(token_stream)
                    if statements:
                        for nested_statement in statements:
                            stmt.default_when.add_statement(nested_statement)
                    lookahead = token_stream.peek()
                    if (
                        lookahead
                        and lookahead.value
                        and lookahead.value.upper() == "WHEN"
                    ):
                        report_parse_error(
                            context,
                            "WHEN OTHER must be the last WHEN clause",
                            when_location,
                        )
                    continue

                selectors, selector_count, issues = self._parse_selectors(token_stream)
                for issue in issues:
                    report_parse_error(context, issue, when_location)

                if selector_count == 0:
                    report_parse_error(
                        context,
                        "WHEN clause must have at least one selector",
                        when_location,
                    )

                if (
                    subject_count > 0
                    and selector_count > 0
                    and selector_count != subject_count
                ):
                    report_parse_error(
                        context,
                        f"Selector count mismatch: expected {subject_count} selectors, got {selector_count}",
                        when_location,
                    )

                when_clause = WhenClause(selectors, when_location)
                stmt.when_clauses.append(when_clause)
                statements = self._skip_clause_statements(token_stream)
                if statements:
                    for nested_statement in statements:
                        when_clause.add_statement(nested_statement)

            if not found_when_clause:
                report_parse_error(
                    context,
                    "EVALUATE statement must have at least one WHEN clause",
                    start_location,
                )

            if not found_end_evaluate:
                report_parse_error(
                    context,
                    "EVALUATE statement missing END-EVALUATE terminator",
                    start_location,
                )

            return stmt
        except ParseError:
            return EvaluateStatement(SourceLocation(0, 0))

    def _parse_subjects(
        self, token_stream: ITokenStream, stmt: EvaluateStatement
    ) -> int:
        """Parse EVALUATE subjects before the first WHEN clause."""
        current_subject: list[str] = []

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break

            if token_val_upper == "ALSO":
                if current_subject:
                    stmt.subjects.append(" ".join(current_subject).strip())
                    current_subject = []
                token_stream.consume()
                continue

            if token.type != TokenType.NEWLINE:
                current_subject.append(token.value if token.value else "")
            token_stream.consume()

        if current_subject:
            stmt.subjects.append(" ".join(current_subject).strip())

        stmt.subjects = [subject for subject in stmt.subjects if subject]
        return len(stmt.subjects)

    def _parse_selectors(
        self, token_stream: ITokenStream
    ) -> tuple[list, int, list[str]]:
        """Parse selector list for a WHEN clause, including validation issues."""
        selectors = []
        current_selector: list[str] = []
        issues = []
        selector_count = 0
        expecting_selector = True
        saw_separator = False

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            # Stop at WHEN, END-EVALUATE, or statement keywords
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break

            if self._is_statement_keyword(token_val_upper):
                break

            # Handle ALSO separator (move to next selector)
            if token_val_upper == "ALSO":
                if expecting_selector:
                    issues.append("Consecutive ALSO keywords without selector")
                elif current_selector:
                    selector = self._build_selector(current_selector)
                    if selector:
                        selectors.append(selector)
                        selector_count += 1
                    current_selector = []
                expecting_selector = True
                saw_separator = True
                token_stream.consume()
                continue

            if token.type != TokenType.NEWLINE:
                current_selector.append(token.value if token.value else "")
                expecting_selector = False
                saw_separator = False
            token_stream.consume()

        # Save final selector if any
        if current_selector:
            selector = self._build_selector(current_selector)
            if selector:
                selectors.append(selector)
                selector_count += 1
        elif saw_separator:
            issues.append("Consecutive ALSO keywords without selector")

        for selector in selectors:
            if selector.get("type") == "Range" and not selector.get("end"):
                issues.append("THRU/THROUGH range is incomplete - missing end value")

        return selectors, selector_count, issues

    def _build_selector(self, selector_tokens: list[str]) -> dict | None:
        """Convert raw selector tokens into a selector dictionary."""
        normalized_tokens = [
            token for token in selector_tokens if token and token.strip()
        ]
        if not normalized_tokens:
            return None

        selector_text = " ".join(normalized_tokens).strip()
        selector_upper = selector_text.upper()

        if selector_upper == "ANY":
            return {"type": "Any"}

        parts = selector_text.split()
        for index, part in enumerate(parts):
            if part.upper() in ("THRU", "THROUGH"):
                start_value = " ".join(parts[:index]).strip()
                end_value = " ".join(parts[index + 1 :]).strip()
                return {
                    "type": "Range",
                    "start": start_value,
                    "end": end_value,
                }

        if any(
            part.upper() in ("AND", "OR", "NOT", "=", "<", ">", "<=", ">=", "<>")
            for part in parts
        ):
            selector = {"type": "Condition", "text": selector_text}
            if " OR " in f" {selector_upper} ":
                selector["operator"] = "OR"
            elif " AND " in f" {selector_upper} ":
                selector["operator"] = "AND"
            return selector

        return {"type": "Literal", "value": selector_text}

    def _skip_clause_statements(self, token_stream: ITokenStream) -> list | None:
        """Parse statements within WHEN clause until next WHEN or END-EVALUATE.

        Returns list of parsed statements, or None if no statements found.
        """
        statements = []

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            # Stop at WHEN or END-EVALUATE
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break

            # Try to parse a nested statement if registry is available
            nested_stmt = try_parse_nested_statement(token_stream)
            if nested_stmt:
                statements.append(nested_stmt)
            else:
                # Skip token if can't parse
                if token.type == TokenType.PERIOD:
                    token_stream.consume()
                    break
                token_stream.consume()

        return statements if statements else None

    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check if word is a known statement keyword."""
        return word.upper() in STATEMENT_KEYWORDS
