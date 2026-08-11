"""Evaluate statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    STATEMENT_KEYWORDS,
    get_parse_context,
    matches_keyword,
    report_parse_error,
    try_parse_nested_statement,
)

from ...core.ast_factory import create_node
from ...core.exceptions import ParseError, UnexpectedEndOfInput
from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import EvaluateStatement, WhenClause
from ._conditions import condition_token_text


class EvaluateStatementParser(IStatementParser):
    """Parser for EVALUATE statements using IStatementParser interface."""

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.EVALUATE, "EVALUATE")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> EvaluateStatement:
        """Parse an EVALUATE statement with contract-level diagnostics."""
        try:
            start_token = token_stream.consume()
            if not start_token:
                raise UnexpectedEndOfInput("EVALUATE keyword")

            start_location = (
                start_token.location
                if hasattr(start_token, "location")
                else SourceLocation(0, 0)
            )
            stmt: EvaluateStatement = create_node(EvaluateStatement, start_location)  # type: ignore[assignment]
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
                    # A malformed EVALUATE (missing its first WHEN, or with
                    # stray tokens between clauses) must not vacuum forward
                    # past a following statement's verb in search of a WHEN
                    # or END-EVALUATE that may only exist inside a *later*,
                    # unrelated statement (e.g. a second EVALUATE) -- that
                    # silently folded whole intervening statements into this
                    # one with zero errors/warnings. Stop and let the missing
                    # WHEN / missing END-EVALUATE errors below report it.
                    if self._is_statement_keyword(token_val_upper):
                        break
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
                    if found_when_other and stmt.default_when is not None:
                        report_parse_error(
                            context,
                            "Multiple WHEN OTHER clauses not allowed",
                            when_location,
                        )
                        # Malformed input: reuse the existing default clause
                        # instead of attaching a second one. set_default_when
                        # always calls add_child, so a fresh clause each time
                        # would leave orphaned WhenClause children that the
                        # tree-walk APIs surface but default_when / to_dict()
                        # (which reference only the last) do not.
                        default_clause = stmt.default_when
                    else:
                        default_clause = WhenClause([], when_location)
                        # Use set_default_when (not direct assignment) so the
                        # clause is registered as an AST child and its nested
                        # statements are reachable via find_all_by_type /
                        # traverse_depth_first.
                        stmt.set_default_when(default_clause)
                    found_when_other = True
                    statements, period_terminated = self._skip_clause_statements(
                        token_stream
                    )
                    if statements:
                        for nested_statement in statements:
                            default_clause.add_statement(nested_statement)
                    if period_terminated:
                        found_end_evaluate = True
                        break
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
                # Use add_when_clause (not direct list append) so the clause is
                # registered as an AST child and its nested statements are
                # reachable via find_all_by_type / traverse_depth_first.
                stmt.add_when_clause(when_clause)
                statements, period_terminated = self._skip_clause_statements(
                    token_stream
                )
                if statements:
                    for nested_statement in statements:
                        when_clause.add_statement(nested_statement)
                if period_terminated:
                    found_end_evaluate = True
                    break

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
            return create_node(EvaluateStatement, SourceLocation(0, 0))  # type: ignore[return-value]

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

            # A malformed/period-less EVALUATE (missing its first WHEN)
            # must not swallow a following statement's verb into the
            # subject list -- this hit even fully-supported verbs like
            # STOP RUN, not just unsupported ones.
            if self._is_statement_keyword(token_val_upper):
                break

            if token_val_upper == "ALSO":
                if current_subject:
                    stmt.subjects.append(" ".join(current_subject).strip())
                    current_subject = []
                token_stream.consume()
                continue

            if token.type != TokenType.NEWLINE:
                current_subject.append(condition_token_text(token))
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
                current_selector.append(condition_token_text(token))
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

    def _skip_clause_statements(
        self, token_stream: ITokenStream
    ) -> tuple[list | None, bool]:
        """Parse statements within a WHEN clause, building nested AST nodes.

        Returns ``(statements, period_terminated)`` where:
        - ``statements``: list of parsed nested statement nodes, or ``None`` if
          empty.
        - ``period_terminated``: ``True`` when the EVALUATE was closed by a
          period rather than ``END-EVALUATE`` — valid IBM COBOL / NIST-85 style.

        Period-termination is detected by checkpointing ``token_stream._pos``
        before and after each nested parse: if any PERIOD token appears in the
        consumed range, the EVALUATE scope has ended.  This lets us both build
        AST nodes for nested statements *and* detect period-termination, even
        when statement parsers consume the period internally (e.g. via
        parse_size_error_clauses).
        """
        period_terminated = False
        statements = []

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            token_val_upper = token.value.upper() if token.value else ""

            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break

            if token.type == TokenType.PERIOD:
                # Period still visible — EVALUATE closed here.
                token_stream.consume()
                period_terminated = True
                break

            # Snapshot the stream position so we can inspect which tokens were
            # consumed by the nested parser (including any trailing PERIOD).
            pos_before = getattr(token_stream, "_pos", None)
            tokens_list = getattr(token_stream, "_tokens", None)

            nested = try_parse_nested_statement(token_stream)
            if nested is not None:
                statements.append(nested)
                # Check whether the nested parser consumed a PERIOD as its own
                # trailing terminator (IBM-style period-terminated EVALUATE
                # where the scope ends mid-WHEN body, e.g. a statement parser
                # that consumes its own trailing period internally via
                # parse_size_error_clauses). Only the LAST meaningful
                # (non-NEWLINE) token consumed counts -- not "any" PERIOD in
                # the whole range: an EXEC SQL/CICS/DLI statement's embedded
                # text can legally contain periods that are not COBOL
                # statement terminators at all (e.g. a schema-qualified SQL
                # table name like "BANK.GL_ACCOUNT"), and treating one of
                # those as ending the EVALUATE misparses everything after it
                # in the WHEN clause as trailing top-level paragraph
                # statements instead of the clause's own body.
                if pos_before is not None and tokens_list is not None:
                    pos_after = getattr(token_stream, "_pos", 0)
                    last_meaningful = next(
                        (
                            t
                            for t in reversed(tokens_list[pos_before:pos_after])
                            if t.type != TokenType.NEWLINE
                        ),
                        None,
                    )
                    if (
                        last_meaningful is not None
                        and last_meaningful.type == TokenType.PERIOD
                    ):
                        period_terminated = True
                        break
            else:
                # No parser matched (NEWLINE, unrecognised token, or partial-
                # parse failure). Consume one token only if position did not
                # advance — partial failures may have already moved the cursor.
                pos_after = getattr(token_stream, "_pos", None)
                if pos_before is not None and pos_after == pos_before:
                    token_stream.consume()

        return statements if statements else None, period_terminated

    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check if word is a known statement keyword."""
        return word.upper() in STATEMENT_KEYWORDS
