"""XML/JSON GENERATE and PARSE statement parser (IBM Enterprise COBOL).

Before this parser existed, the leading ``XML``/``JSON`` keyword was silently
consumed by the unknown-statement skip and the remaining ``GENERATE dest FROM
src`` mis-parsed as a Report Writer :class:`GenerateStatement` — a wrong node
with ``errors=0``. This parser captures the construct faithfully: verb,
action, primary operands, the raw text of any trailing clauses, and --
since 2026-09-02 -- structured ``PROCESSING PROCEDURE`` fields plus real
``[ON] EXCEPTION`` / ``NOT [ON] EXCEPTION`` handler bodies (previously
flattened into the clause text, which hid every statement inside them from
``get_all_statements()`` and from any nested-body walk).
"""

from typing import Any

from cobolparser.parsers.statements._utils import (
    collect_clause_stmts,
    consume_end_keyword_and_period,
    get_parse_context,
    is_statement_boundary,
    peek_past_noise,
    peek_token,
    peek_value_upper,
    report_parse_error,
    skip_whitespace,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.ast_base import SourceLocation
from ...models.statements import XmlJsonStatement

#: Clause words of XML/JSON GENERATE/PARSE that also happen to be statement
#: or control-flow keywords elsewhere (``SUPPRESS`` is the Report Writer verb,
#: ``WHEN`` closes an EVALUATE arm) -- inside this construct they continue
#: the clause region and must not end it. ``WHEN`` is only a continuation
#: after ``SUPPRESS`` (``SUPPRESS WHEN SPACES`` / ``EVERY NUMERIC ... WHEN
#: ZERO``); elsewhere it still closes an enclosing EVALUATE arm.
_CLAUSE_CONTINUATION_WORDS = frozenset({"SUPPRESS", "NOT", "ON"})
_SUPPRESS_CONTINUATION_WORDS = frozenset({"WHEN"})


class XmlJsonStatementParser(IStatementParser):
    """Parser for XML GENERATE / XML PARSE / JSON GENERATE / JSON PARSE.

    Syntax (simplified):
        XML GENERATE receiving FROM source [COUNT IN c] [WITH ENCODING ...]
            [ON EXCEPTION ...] [END-XML]
        XML PARSE source [PROCESSING PROCEDURE proc] [ON EXCEPTION ...]
            [END-XML]
        JSON GENERATE receiving FROM source [COUNT IN c] [NAME OF ...]
            [ON EXCEPTION ...] [END-JSON]
        JSON PARSE source INTO receiving [ON EXCEPTION ...] [END-JSON]

    The primary operands are modeled; trailing clauses are preserved
    verbatim in ``clause_text`` so no source content is silently dropped.
    ``PROCESSING PROCEDURE [IS] name [THRU name]`` is additionally captured
    as ``processing_procedure`` / ``processing_procedure_thru`` (it stays in
    ``clause_text`` too), and the ``[ON] EXCEPTION`` / ``NOT [ON] EXCEPTION``
    handler bodies are parsed into ``on_exception`` / ``not_on_exception``
    statement lists exactly like CALL and ACCEPT do.
    """

    _VERBS = ("XML", "JSON")
    _ACTIONS = ("GENERATE", "PARSE")

    def matches(self, token_stream: ITokenStream) -> bool:
        """True when the stream is at ``XML``/``JSON`` followed by an action."""
        token = peek_token(token_stream)
        if not token or not token.value or token.value.upper() not in self._VERBS:
            return False
        # Look past whitespace/newlines for GENERATE or PARSE
        idx = 1
        while idx < 6:
            nxt = token_stream.peek(idx)
            if nxt is None:
                return False
            if nxt.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                idx += 1
                continue
            return bool(nxt.value) and nxt.value.upper() in self._ACTIONS
        return False

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> XmlJsonStatement:
        """Parse an XML/JSON GENERATE or PARSE statement."""
        start_token = token_stream.consume()  # XML | JSON
        context = get_parse_context(token_stream)
        verb = (start_token.value or "").upper()
        location = (
            start_token.location
            if hasattr(start_token, "location")
            else SourceLocation(0, 0)
        )

        skip_whitespace(token_stream)
        action_token = token_stream.consume()  # GENERATE | PARSE
        action = (action_token.value or "").upper() if action_token else ""

        stmt = XmlJsonStatement(verb, action, location)

        # Primary operand (receiving item for GENERATE, source for PARSE)
        skip_whitespace(token_stream)
        primary = peek_token(token_stream)
        if primary and primary.value and not is_statement_boundary(primary):
            stmt.set_primary_operand(primary.value)
            token_stream.consume()
        else:
            report_parse_error(
                context,
                f"{verb} {action} requires an operand",
                location,
            )
            return stmt

        # GENERATE: FROM source
        skip_whitespace(token_stream)
        nxt = peek_token(token_stream)
        if action == "GENERATE" and nxt and nxt.value and nxt.value.upper() == "FROM":
            token_stream.consume()  # FROM
            skip_whitespace(token_stream)
            src = peek_token(token_stream)
            if src and src.value and not is_statement_boundary(src):
                stmt.set_from_item(src.value)
                token_stream.consume()
            else:
                report_parse_error(
                    context,
                    f"{verb} GENERATE requires a source item after FROM",
                    location,
                )

        # Preserve every non-handler clause up to the sentence period, the
        # END-XML/END-JSON scope terminator, or the first exception handler
        # (which is parsed structurally below, not kept as text).
        terminator = f"END-{verb}"
        clause_parts: list[str] = []
        seen_suppress = False
        while not token_stream.is_empty():
            token = peek_token(token_stream)
            if token is None:
                break
            value = token.value or ""
            upper = value.upper()
            if upper == terminator or value == ".":
                # Both are consumed by consume_end_keyword_and_period below.
                break
            if token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                token_stream.consume()
                continue
            if self._at_exception_handler(token_stream):
                break
            if upper == "PROCESSING" and self._consume_processing_procedure(
                token_stream, stmt, clause_parts
            ):
                continue
            # A new statement keyword ends the clause region -- unless it is
            # one of this construct's own clause words (SUPPRESS ..., NOT ON
            # EXCEPTION is handled above).
            is_clause_word = (
                upper in _CLAUSE_CONTINUATION_WORDS
                or (seen_suppress and upper in _SUPPRESS_CONTINUATION_WORDS)
                # JSON GENERATE ... CONVERTING item TO JSON DECIMAL|BOOLEAN
                # (Enterprise COBOL 6.3): the word JSON after TO is the
                # target type, not the start of a new JSON statement.
                or (
                    upper == "JSON"
                    and bool(clause_parts)
                    and clause_parts[-1].upper() == "TO"
                )
            )
            if is_statement_boundary(token) and not is_clause_word:
                break
            if upper == "SUPPRESS":
                seen_suppress = True
            clause_parts.append(value)
            token_stream.consume()

        if clause_parts:
            stmt.set_clause_text(" ".join(clause_parts))

        self._parse_exception_clauses(token_stream, stmt, terminator)
        consume_end_keyword_and_period(token_stream, terminator)
        return stmt

    @staticmethod
    def _at_exception_handler(token_stream: ITokenStream) -> bool:
        """True at ``[ON] EXCEPTION`` or ``NOT [ON] EXCEPTION`` (nothing
        consumed)."""
        token, idx = peek_past_noise(token_stream, 0)
        if token is None:
            return False
        if token.type == TokenType.NOT:
            token, idx = peek_past_noise(token_stream, idx + 1)
        if token is not None and (token.value or "").upper() == "ON":
            token, idx = peek_past_noise(token_stream, idx + 1)
        return token is not None and (token.value or "").upper() == "EXCEPTION"

    @staticmethod
    def _consume_processing_procedure(
        token_stream: ITokenStream, stmt: XmlJsonStatement, clause_parts: list[str]
    ) -> bool:
        """Consume ``PROCESSING PROCEDURE [IS] name [THRU|THROUGH name]``.

        Records the names on *stmt* and echoes the consumed words into
        *clause_parts* so ``clause_text`` keeps its historical content.
        Returns False (consuming nothing) when the stream is not actually
        at that clause."""
        nxt, _ = peek_past_noise(token_stream, 1)
        if nxt is None or (nxt.value or "").upper() != "PROCEDURE":
            return False

        def take() -> str:
            skip_whitespace(token_stream)
            token = token_stream.consume()
            word = (token.value or "") if token else ""
            clause_parts.append(word)
            return word

        take()  # PROCESSING
        take()  # PROCEDURE
        if peek_value_upper(token_stream) == "IS":
            take()
        skip_whitespace(token_stream)
        name_token = peek_token(token_stream)
        if name_token is None or is_statement_boundary(name_token):
            return True
        name = take()
        thru: str | None = None
        if peek_value_upper(token_stream) in ("THRU", "THROUGH"):
            take()
            skip_whitespace(token_stream)
            thru_token = peek_token(token_stream)
            if thru_token is not None and not is_statement_boundary(thru_token):
                thru = take()
        stmt.set_processing_procedure(name, thru)
        return True

    @staticmethod
    def _parse_exception_clauses(
        token_stream: ITokenStream, stmt: XmlJsonStatement, terminator: str
    ) -> None:
        """Parse ``[ON] EXCEPTION stmts [NOT [ON] EXCEPTION stmts]`` -- the
        same shape ``AcceptStatementParser._parse_exception_clauses``
        handles, stopping at this construct's own END-XML/END-JSON."""
        for negated in (False, True):
            skip_whitespace(token_stream)
            if negated:
                token = token_stream.peek()
                if not (token and token.type == TokenType.NOT):
                    return
                lookahead, idx = peek_past_noise(token_stream, 1)
                if lookahead and peek_value_upper(token_stream, idx) == "ON":
                    lookahead, _ = peek_past_noise(token_stream, idx + 1)
                if not (lookahead and (lookahead.value or "").upper() == "EXCEPTION"):
                    return
                token_stream.consume()  # NOT
                skip_whitespace(token_stream)
            if peek_value_upper(token_stream) == "ON":
                lookahead, _ = peek_past_noise(token_stream, 1)
                if not (lookahead and (lookahead.value or "").upper() == "EXCEPTION"):
                    return
                token_stream.consume()  # ON
                skip_whitespace(token_stream)
            if peek_value_upper(token_stream) != "EXCEPTION":
                return
            token_stream.consume()  # EXCEPTION
            clause = collect_clause_stmts(token_stream, {terminator})
            if negated:
                stmt.set_not_on_exception_clause(clause)
            else:
                stmt.set_on_exception_clause(clause)


__all__ = ["XmlJsonStatementParser"]
