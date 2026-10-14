"""Evaluate statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    LITERAL_TOKEN_TYPES,
    STATEMENT_KEYWORDS,
    get_parse_context,
    keyword_upper,
    matches_keyword,
    report_parse_error,
    skip_statement_separators,
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
                    if (
                        token.type not in LITERAL_TOKEN_TYPES
                        and self._is_statement_keyword(token_val_upper)
                    ):
                        break
                    token_stream.consume()
                    continue

                found_when_clause = True
                when_location = (
                    token.location if hasattr(token, "location") else start_location
                )
                token_stream.consume()
                # A selector always follows WHEN, so a line break here is
                # layout: ``WHEN <newline> OTHER`` must still be the default.
                skip_statement_separators(token_stream)

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
                when_clause.stacked = self._at_stacked_when(
                    token_stream, when_location.line
                )
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
        """Parse EVALUATE subjects before the first WHEN clause.

        Subjects are added via ``stmt.add_subject()`` -- not appended to
        ``stmt.subjects`` directly -- so each string subject also lands in
        the generic ``.operands`` bag that ``.operands``-based consumers
        (``find_statements_using_variable``, intrinsic-function detection,
        ``LanguageEnvironmentAnalyzer``, ``BoundaryInventoryAnalyzer``'s
        caller-dataflow rung) scan.
        """

        def add_current() -> None:
            # Guarded add: an all-noise buffer joins to "" and is dropped
            # rather than recorded as an empty subject.
            subject = " ".join(current_subject).strip()
            if subject:
                stmt.add_subject(subject)

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
            if token.type not in LITERAL_TOKEN_TYPES and self._is_statement_keyword(
                token_val_upper
            ):
                break

            if token_val_upper == "ALSO":
                add_current()
                current_subject = []
                token_stream.consume()
                continue

            if token.type != TokenType.NEWLINE:
                current_subject.append(condition_token_text(token))
            token_stream.consume()

        add_current()
        return len(stmt.subjects)

    def _parse_selectors(
        self, token_stream: ITokenStream
    ) -> tuple[list, int, list[str]]:
        """Parse selector list for a WHEN clause, including validation issues."""
        selectors = []
        current_selector: list[str] = []
        current_types: list[TokenType] = []
        # The same tokens as written (string literals re-quoted), for a
        # Condition selector's ``text``.
        current_texts: list[str] = []
        issues = []
        selector_count = 0
        expecting_selector = True
        saw_separator = False

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            # WHEN / END-EVALUATE / ALSO only as words: ``WHEN "WHEN"`` is a
            # selector value (the lexer strips the literal's quotes).
            token_val_upper = keyword_upper(token)

            # Stop at WHEN, END-EVALUATE, or statement keywords (a literal
            # spelled like a verb -- ``WHEN "IF"`` -- is a selector value)
            if token_val_upper in ("WHEN", "END-EVALUATE"):
                break

            if token.type not in LITERAL_TOKEN_TYPES and self._is_statement_keyword(
                token_val_upper
            ):
                break

            # Handle ALSO separator (move to next selector)
            if token_val_upper == "ALSO":
                if expecting_selector:
                    issues.append("Consecutive ALSO keywords without selector")
                elif current_selector:
                    selector = self._build_selector(
                        current_selector, current_types, current_texts
                    )
                    if selector:
                        selectors.append(selector)
                        selector_count += 1
                    current_selector = []
                    current_types = []
                    current_texts = []
                expecting_selector = True
                saw_separator = True
                token_stream.consume()
                continue

            if token.type != TokenType.NEWLINE:
                value = token.value if token.value else ""
                # The lexer strips quotes off string literals, so a blank
                # literal (WHEN '  ' — the IMS DL/I "call succeeded" status
                # idiom) arrives as whitespace-only text that _build_selector
                # would filter out as an empty artifact, collapsing the WHEN
                # to zero selectors. Re-quote it so the value survives.
                # Non-blank literals keep their unquoted representation —
                # the selector-dict shape is pinned by
                # tests/regression/test_evaluate_space_literal_when.py.
                if token.type == TokenType.STRING_LITERAL and not value.strip():
                    value = f"'{value}'"
                current_selector.append(value)
                current_types.append(token.type)
                current_texts.append(
                    condition_token_text(token)
                    if token.type == TokenType.STRING_LITERAL
                    else value
                )
                expecting_selector = False
                saw_separator = False
            token_stream.consume()

        # Save final selector if any
        if current_selector:
            selector = self._build_selector(
                current_selector, current_types, current_texts
            )
            if selector:
                selectors.append(selector)
                selector_count += 1
        elif saw_separator:
            issues.append("Consecutive ALSO keywords without selector")

        for selector in selectors:
            is_range = selector.get("type") == "Range" or "end" in selector
            if is_range and not selector.get("end"):
                issues.append("THRU/THROUGH range is incomplete - missing end value")

        return selectors, selector_count, issues

    def _build_selector(
        self,
        selector_tokens: list[str],
        token_types: list[TokenType] | None = None,
        token_texts: list[str] | None = None,
    ) -> dict | None:
        """Convert raw selector tokens into a selector dictionary.

        A plain value selector is always ``{"type": "Literal", "value": ...}``
        -- the lexer strips string quotes, so ``WHEN "AB"`` and ``WHEN WS-AB``
        were indistinguishable in the dict. When the selector is a single
        IDENTIFIER token the dict additionally carries ``"identifier": True``;
        a single FIGURATIVE_CONSTANT token (``WHEN SPACES``) carries
        ``"figurative": True`` and a single STRING_LITERAL (``WHEN 'SPACES'``)
        ``"quoted": True`` -- without them the two read as the same value.
        The ``type`` key deliberately stays ``"Literal"``: the constraint
        extractor (``analysis/constraints.py``) keys EVALUATE TRUE
        condition-name selectors on it, so an additive marker is the
        backward-compatible way to make the distinction visible.
        """
        types: list[TokenType | None] = (
            list(token_types)
            if token_types and len(token_types) == len(selector_tokens)
            else [None] * len(selector_tokens)
        )
        texts: list[str] = (
            list(token_texts)
            if token_texts and len(token_texts) == len(selector_tokens)
            else list(selector_tokens)
        )
        kept = [
            (token, token_type, text)
            for token, token_type, text in zip(
                selector_tokens, types, texts, strict=True
            )
            if token and token.strip()
        ]
        if not kept:
            return None
        pairs = [(token, token_type) for token, token_type, _ in kept]
        # A Condition's text keeps string literals quoted: ``WHEN A = "B"``
        # stored as ``A = B`` read the literal as the data name ``B``.
        condition_text = " ".join(text for _, _, text in kept).strip()
        normalized_tokens = [token for token, _ in pairs]
        single_type = (
            token_types[0]
            if token_types and len(token_types) == len(selector_tokens) == 1
            else None
        )

        selector_text = " ".join(normalized_tokens).strip()

        # Keywords and operators are recognized only as *words*: the lexer
        # strips a string literal's quotes, so WHEN "ANY" / "THRU" / "AND"
        # / "<" -- a COBOL tokenizer's operator table -- would otherwise
        # read as a wildcard, a broken range (a spurious error) or a
        # condition. A STRING_LITERAL token is always a value.
        words = [
            [] if token_type == TokenType.STRING_LITERAL else token.upper().split()
            for token, token_type in pairs
        ]
        flat_words = [word for token_words in words for word in token_words]

        if len(pairs) == 1 and words[0] == ["ANY"]:
            return {"type": "Any"}

        for index, token_words in enumerate(words):
            if token_words[:1] in (["THRU"], ["THROUGH"]):
                negated = words[0] == ["NOT"] and index > 1
                first = 1 if negated else 0
                start_value = " ".join(normalized_tokens[first:index]).strip()
                end_value = " ".join(normalized_tokens[index + 1 :]).strip()
                if negated:
                    # ``WHEN NOT 1 THRU 5`` selects everything *outside* the
                    # range. As a plain Range it read as ``start="NOT 1"``,
                    # which a consumer takes for the range itself -- the
                    # opposite arm. A negated selector is a Condition, as
                    # ``WHEN NOT 'Y'`` already is; the bounds stay readable.
                    return {
                        "type": "Condition",
                        "text": condition_text,
                        "negated": True,
                        "start": start_value,
                        "end": end_value,
                    }
                return {
                    "type": "Range",
                    "start": start_value,
                    "end": end_value,
                }

        if any(
            word in ("AND", "OR", "NOT", "=", "<", ">", "<=", ">=", "<>")
            for word in flat_words
        ):
            selector: dict[str, Any] = {"type": "Condition", "text": condition_text}
            if "OR" in flat_words:
                selector["operator"] = "OR"
            elif "AND" in flat_words:
                selector["operator"] = "AND"
            return selector

        literal: dict[str, Any] = {"type": "Literal", "value": selector_text}
        if single_type == TokenType.IDENTIFIER:
            literal["identifier"] = True
        elif single_type == TokenType.FIGURATIVE_CONSTANT:
            literal["figurative"] = True
        elif single_type == TokenType.STRING_LITERAL:
            literal["quoted"] = True
        return literal

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
            skip_statement_separators(token_stream)
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
    def _at_stacked_when(token_stream: ITokenStream, when_line: int) -> bool:
        """True when the next phrase is another (non-OTHER) WHEN.

        Called right after a WHEN's selectors: nothing but layout between
        them and the next WHEN means the two phrases share one body (a
        stacked WHEN). WHEN OTHER cannot be stacked onto. Text removed before
        lexing (an unexpanded COPY) on the lines from this WHEN to the next
        is a body that never reached the AST, not a stack.
        """
        skip_statement_separators(token_stream)
        token = token_stream.peek()
        if token is None or not token.value or token.value.upper() != "WHEN":
            return False
        next_line = token.location.line if token.location else when_line
        omitted = getattr(token_stream, "omitted_source_lines", ())
        if any(first <= next_line and last >= when_line for first, last in omitted):
            return False
        offset = 1
        while True:
            following = token_stream.peek(offset)
            if following is None or following.type != TokenType.NEWLINE:
                break
            offset += 1
        return not (
            following is not None
            and following.value
            and following.value.upper() == "OTHER"
        )

    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check if word is a known statement keyword."""
        return word.upper() in STATEMENT_KEYWORDS
