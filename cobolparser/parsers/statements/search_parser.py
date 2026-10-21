"""SEARCH statement parser implementing IStatementParser interface."""

from typing import Any

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import CobolExpression, SearchStatement
from ._conditions import (
    ConditionSymbols,
    build_condition_expression,
    condition_symbols,
    condition_token_text,
)
from ._utils import (
    LITERAL_TOKEN_TYPES,
    SEPARATOR_TOKEN_TYPES,
    STATEMENT_KEYWORDS,
    bare_end_starts_at_end_clause,
    consume_optional_qualifiers,
    get_parse_context,
    is_bare_separator,
    keyword_upper,
    matches_keyword,
    paren_depth_after,
    previous_meaningful_token,
    skip_statement_separators,
    skip_whitespace,
    token_location,
    try_parse_nested_statement,
)
from ._utils import (
    token_value_upper as _val,
)


class SearchStatementParser(IStatementParser):
    """Parser for SEARCH statements.

    Syntax:
        SEARCH table-name [VARYING identifier]
            [AT END imperative-statement]
            WHEN condition imperative-statement
            ...
        END-SEARCH

        SEARCH ALL table-name
            [AT END imperative-statement]
            WHEN condition imperative-statement
        END-SEARCH
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.SEARCH, "SEARCH")

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> SearchStatement:
        start = token_stream.consume()
        stmt = SearchStatement(token_location(start))
        skip_whitespace(token_stream)

        # Check for ALL
        token = token_stream.peek()
        if token and _val(token) == "ALL":
            token_stream.consume()
            stmt.set_metadata("is_search_all", True)
            skip_whitespace(token_stream)

        # Table name
        token = token_stream.peek()
        if token and token.type != TokenType.PERIOD:
            token_stream.consume()
            # ``SEARCH T OF G`` -- a qualified table name. Left in the
            # stream, ``OF`` ended the SEARCH: its AT END and WHEN bodies
            # were parsed as free-standing statements of the paragraph.
            stmt.set_table_name(
                consume_optional_qualifiers(token_stream, token.value or "")
            )
        skip_whitespace(token_stream)

        # Optional VARYING
        token = token_stream.peek()
        if token and _val(token) == "VARYING":
            token_stream.consume()
            skip_whitespace(token_stream)
            var_token = token_stream.peek()
            if var_token and var_token.type != TokenType.PERIOD:
                token_stream.consume()
                stmt.set_varying_variable(
                    consume_optional_qualifiers(token_stream, var_token.value or "")
                )
            skip_whitespace(token_stream)

        # Parse AT END and WHEN clauses
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            val = _val(token)
            if val == "END-SEARCH":
                token_stream.consume()
                skip_whitespace(token_stream)
                p = token_stream.peek()
                if p and p.type == TokenType.PERIOD:
                    token_stream.consume()
                break
            if val == "AT":
                token_stream.consume()
                skip_whitespace(token_stream)
                nxt = token_stream.peek()
                if nxt and _val(nxt) == "END":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    # Parse AT END nested statements
                    at_end_stmts = self._parse_nested_statements(token_stream)
                    if at_end_stmts:
                        stmt.set_at_end_clause(at_end_stmts)
                        if _sentence_period_consumed(token_stream):
                            break
            elif bare_end_starts_at_end_clause(token_stream):
                # ``SEARCH T END stmts WHEN ...`` -- AT is optional.
                token_stream.consume()  # END
                skip_whitespace(token_stream)
                at_end_stmts = self._parse_nested_statements(token_stream)
                if at_end_stmts:
                    stmt.set_at_end_clause(at_end_stmts)
                    if _sentence_period_consumed(token_stream):
                        break
            elif val == "WHEN":
                when_location = token_location(token_stream.consume())
                skip_whitespace(token_stream)
                # Collect condition text until statement keyword
                cond_parts: list[str] = []
                paren_depth = 0
                while not token_stream.is_empty():
                    t = token_stream.peek()
                    if not t:
                        break
                    # A separator comma/semicolon is a space (#386).
                    if is_bare_separator(t, paren_depth):
                        token_stream.consume()
                        skip_whitespace(token_stream)
                        continue
                    # Clause words only as words: WHEN K = "WHEN" compares
                    # against a literal (the lexer strips its quotes).
                    tv = keyword_upper(t)
                    if t.type == TokenType.PERIOD or tv in (
                        "WHEN",
                        "END-SEARCH",
                        "AT",
                    ):
                        break
                    if t.type not in LITERAL_TOKEN_TYPES and tv in STATEMENT_KEYWORDS:
                        break
                    token_stream.consume()
                    paren_depth = paren_depth_after(t, paren_depth)
                    # Re-quote string literals so ``= 'X'`` and ``= X`` stay
                    # distinguishable in the recorded condition text.
                    cond_parts.append(condition_token_text(t))
                    skip_whitespace(token_stream)
                # Parse nested statements after condition
                when_stmts = self._parse_nested_statements(token_stream)
                stmt.add_when_clause(
                    " ".join(cond_parts),
                    when_stmts,
                    _condition_tree(
                        cond_parts,
                        when_location,
                        condition_symbols(get_parse_context(token_stream)),
                    ),
                )
                if when_stmts and _sentence_period_consumed(token_stream):
                    break
            elif token.type in SEPARATOR_TOKEN_TYPES:
                token_stream.consume()
            else:
                # Anything else ends the SEARCH: an enclosing ELSE / END-IF /
                # WHEN (SEARCH nested in IF or EVALUATE without END-SEARCH),
                # or a following statement. Consuming it here used to eat
                # every token up to the period, silently.
                break
            skip_whitespace(token_stream)

        return stmt

    @staticmethod
    def _parse_nested_statements(token_stream: ITokenStream) -> list:
        """Parse nested imperative statements until a WHEN/END-SEARCH/period boundary."""
        stmts: list = []
        while not token_stream.is_empty():
            skip_statement_separators(token_stream)
            token = token_stream.peek()
            if not token:
                break
            val = _val(token)
            if token.type == TokenType.PERIOD or val in (
                "WHEN",
                "END-SEARCH",
                "AT",
            ):
                break
            nested = try_parse_nested_statement(token_stream)
            if nested:
                stmts.append(nested)
            else:
                break
            if _sentence_period_consumed(token_stream):
                # ``WHEN c DISPLAY X.`` -- the nested statement took the
                # sentence period, which ends the SEARCH too. Without this
                # check every later statement of the paragraph was parsed
                # into this WHEN (or AT END) body.
                break
        return stmts


def _condition_tree(
    cond_parts: list[str],
    location: SourceLocation,
    symbols: ConditionSymbols | None = None,
) -> CobolExpression | None:
    """The WHEN condition as a structural tree, or None.

    Built with the same machinery IF and PERFORM UNTIL use, so a compound
    ``WHEN A = 1 AND B = 2`` is an AND of two comparisons rather than one
    string a consumer has to re-split. Fail-soft, like PERFORM UNTIL's: a
    condition the builder cannot handle keeps only the raw text.
    """
    if not cond_parts:
        return None
    try:
        return build_condition_expression(list(cond_parts), location, symbols=symbols)
    except Exception:
        return None


def _sentence_period_consumed(token_stream: ITokenStream) -> bool:
    """True when the last meaningful token consumed was the sentence period."""
    prev = previous_meaningful_token(token_stream)
    return prev is not None and prev.type == TokenType.PERIOD
