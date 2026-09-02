"""XML/JSON GENERATE and PARSE statement parser (IBM Enterprise COBOL).

Before this parser existed, the leading ``XML``/``JSON`` keyword was silently
consumed by the unknown-statement skip and the remaining ``GENERATE dest FROM
src`` mis-parsed as a Report Writer :class:`GenerateStatement` — a wrong node
with ``errors=0``. This parser captures the construct faithfully: verb,
action, primary operands, and the raw text of any trailing clauses.
"""

from typing import Any

from cobolparser.parsers.statements._utils import (
    get_parse_context,
    is_statement_boundary,
    peek_token,
    report_parse_error,
    skip_whitespace,
)

from ...core.interfaces import IStatementParser, ITokenStream
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

    The primary operands are modeled; trailing clauses (including exception
    handlers) are preserved verbatim in ``clause_text`` so no source content
    is silently dropped.
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

        # Preserve everything else up to the sentence period or END-XML/
        # END-JSON scope terminator. Exception-handler bodies frequently
        # contain other verbs, so collection only stops at the terminator or
        # period — the raw text is kept rather than dropped.
        terminator = f"END-{verb}"
        clause_parts: list[str] = []
        in_handler = False
        seen_suppress = False
        while not token_stream.is_empty():
            token = peek_token(token_stream)
            if token is None:
                break
            value = token.value or ""
            upper = value.upper()
            if upper == terminator:
                token_stream.consume()
                break
            if value == ".":
                # Leave the period for the enclosing sentence logic
                break
            if token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                token_stream.consume()
                continue
            # A new statement keyword ends the clause region — unless we are
            # inside an ON/NOT ON EXCEPTION handler, whose imperative
            # statements belong to this construct and are preserved as raw
            # text rather than dropped -- or the keyword is one of this
            # construct's own clause words (SUPPRESS ..., NOT ON EXCEPTION).
            # ``NOT`` leaves the handler so ``NOT ON EXCEPTION`` after an
            # ``ON EXCEPTION`` body is not mistaken for that body's content.
            if upper == "NOT":
                in_handler = False
            is_clause_word = upper in _CLAUSE_CONTINUATION_WORDS or (
                seen_suppress and upper in _SUPPRESS_CONTINUATION_WORDS
            )
            if is_statement_boundary(token) and not in_handler and not is_clause_word:
                break
            if upper == "EXCEPTION":
                in_handler = True
            if upper == "SUPPRESS":
                seen_suppress = True
            clause_parts.append(value)
            token_stream.consume()

        if clause_parts:
            stmt.set_clause_text(" ".join(clause_parts))

        # Consume trailing period if present
        tail = peek_token(token_stream)
        if tail and tail.value == ".":
            token_stream.consume()

        return stmt


__all__ = ["XmlJsonStatementParser"]
