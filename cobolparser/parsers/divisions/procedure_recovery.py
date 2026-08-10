"""Statement-level error handling and recovery for the PROCEDURE DIVISION.

Collaborator of
:class:`~cobolparser.parsers.divisions.procedure.ProcedureDivisionParser`:
records caller-visible warnings for content skipped without a parser,
converts unexpected exceptions into :class:`ParseError`, applies the
``FAIL_FAST`` / ``COLLECT_ALL`` recovery policy, and resynchronizes the token
stream at the next statement boundary.
"""

import logging
from typing import Any

from cobolparser._errors import ParseError
from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.plugins.core import ErrorRecoveryMode

from .procedure_boundaries import is_paragraph_or_section_start, is_statement_keyword

logger = logging.getLogger(__name__)

# Stray scope/control markers left behind by error recovery; skipping
# these is routine resynchronization, not a dropped statement, so they
# do not deserve an "unsupported statement" warning.
STRAY_MARKERS: frozenset = frozenset(
    {
        "ELSE",
        "WHEN",
        "THEN",
        "END-IF",
        "END-PERFORM",
        "END-EVALUATE",
        "END-READ",
        "END-WRITE",
        "END-SEARCH",
        "END-CALL",
        "END-ADD",
        "END-SUBTRACT",
        "END-MULTIPLY",
        "END-DIVIDE",
        "END-COMPUTE",
        "END-STRING",
        "END-UNSTRING",
        "END-START",
        "END-DELETE",
        "END-REWRITE",
        "END-RETURN",
        "END-ACCEPT",
        "END-DISPLAY",
        "END-XML",
        "END-JSON",
    }
)

# Real verbs (IBM Enterprise and dialect extensions) that have no
# registered statement parser yet. These get a specific "unsupported
# statement" warning; anything else that reaches the skip path is
# leftover clause content from a partially-parsed statement.
UNSUPPORTED_VERBS: frozenset = frozenset(
    {
        # ALLOCATE, FREE, and INVOKE have registered parsers
        # (allocate_free_parsers.py, invoke_parser.py) and are deliberately
        # NOT listed here -- they now dispatch through the registry instead
        # of reaching this warn-and-discard path.
        "CHAIN",
        "DISABLE",
        "ENABLE",
        "ENTER",
        "EXAMINE",
        "EXECUTE",
        "EXHIBIT",
        "GOTO",
        "INITIATE",
        "NOTE",
        "PURGE",
        "RAISE",
        "READY",
        "RECEIVE",
        "RECOVER",
        "RESET",
        "RESUME",
        "SEND",
        "SERVICE",
        "SUPPRESS",
        "TERMINATE",
        "TRANSFORM",
    }
)


class StatementRecoveryHandler:
    """Warns about, records, and recovers from statement-level parse issues.

    Holds a back-reference to the owning division parser so warnings and
    errors reach the host parser's channels and so stream resynchronization
    can consult the shared statement registry.
    """

    def __init__(self, parser: Any) -> None:
        """Initialize with the owning division parser.

        Args:
            parser: The ``ProcedureDivisionParser`` this collaborator
                belongs to.
        """
        self._parser = parser

    def warn_unsupported_statement(self, token: Any) -> None:
        """Record a caller-visible warning for content skipped without a parser.

        Historically unrecognized statements were consumed with only a
        ``logger.debug`` — real IBM verbs like INVOKE or EXHIBIT vanished
        from the AST with ``errors=0, warnings=0``, and clause tokens a
        statement parser did not understand were dropped just as silently.
        Route both through the host's warning channel so a "clean" parse
        actually means a complete AST.
        """
        value = (token.value or "").upper() if token is not None else ""
        if not value or value in STRAY_MARKERS:
            return
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        if value in UNSUPPORTED_VERBS:
            message = (
                f"Unsupported statement '{value}'{where} skipped: "
                "no parser is registered for this verb; its tokens were "
                "discarded up to the next statement boundary"
            )
        else:
            message = (
                f"Unparsed tokens starting at '{value}'{where} skipped: "
                "clause or statement not fully supported; content dropped "
                "from the AST up to the next statement boundary"
            )
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(message)
        else:
            logger.warning(message)

    def wrap_unexpected(self, exc: BaseException, token: Any) -> ParseError:
        """Convert an unexpected exception into a ParseError with location."""
        loc = getattr(token, "location", None) if token is not None else None
        line = getattr(loc, "line", None) if loc is not None else None
        column = getattr(loc, "column", None) if loc is not None else None
        return ParseError(
            f"Unexpected error parsing statement: {exc}",
            line_number=line,
            column=column,
            location=loc,
        )

    def handle_statement_error(
        self,
        error: ParseError,
        token: Any,
        token_stream: ITokenStream,
    ) -> None:
        """Record a statement-level parse error and continue or re-raise.

        Behavior is determined by ``host.error_recovery``:

        * ``COLLECT_ALL`` (default for batch runs): the error is appended to
          the host's error list via ``add_error`` and the stream is advanced
          past the offending statement so parsing continues.
        * ``FAIL_FAST``: the error is recorded and re-raised so the division
          parser's outer handler can short-circuit the parse.

        Statement parsers that called :func:`report_or_raise` tag the
        ParseError with ``_already_recorded`` so we don't double-count when
        we receive it here.
        """
        loc = getattr(token, "location", None)
        logger.debug(
            "Statement error at line %s (token %r): %s",
            getattr(loc, "line", None),
            getattr(token, "value", None),
            error,
        )

        host = self._parser.host
        if host is not None and hasattr(host, "add_error"):
            if not getattr(error, "_already_recorded", False):
                host.add_error(error)

        mode = getattr(host, "error_recovery", None)
        if mode == ErrorRecoveryMode.FAIL_FAST:
            logger.debug("FAIL_FAST: re-raising statement error")
            raise error

        logger.debug("COLLECT_ALL: recovering past failed statement")
        self.skip_to_next_statement(token_stream)

    # Filler token types that carry no statement content -- consuming one
    # of these must not count as "we've started discarding the statement's
    # tokens" (see the at_call_start comment below).
    _FILLER_TOKEN_TYPES = (
        TokenType.WHITESPACE,
        TokenType.NEWLINE,
        TokenType.COMMENT,
        TokenType.CONTINUATION,
    )

    def skip_to_next_statement(self, token_stream: ITokenStream) -> None:
        """Skip to start of next statement or paragraph.

        Skips tokens until finding a period (statement end) or
        a likely statement keyword.

        Args:
            token_stream: Token stream to advance
        """
        at_call_start = True
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            if token.value == ".":
                token_stream.consume()
                break

            # Only trust the paragraph/section-boundary heuristic before any
            # meaningful (non-filler) token has been consumed by this call.
            # It exists to avoid overrunning into a real next paragraph when
            # the cursor is already sitting at one (e.g. handle_statement_error
            # recovering after a partially-parsed statement whose own
            # terminating period was already consumed -- a caller that gives
            # no guarantee the cursor isn't sitting on leading whitespace/
            # comment tokens first). Once this call has consumed a real
            # token of the statement being discarded, everything up to that
            # statement's own terminating period belongs to it -- COBOL
            # never nests a paragraph header inside an unterminated
            # statement -- so re-checking the heuristic on a later token
            # (e.g. an unsupported verb's own trailing bare-identifier
            # operand, which is followed by that same period and so looks
            # exactly like a paragraph header) misreads the operand as a
            # new paragraph and truncates the statement being discarded.
            if at_call_start and is_paragraph_or_section_start(token_stream):
                break

            # Stop if we hit a statement keyword that has a registered parser.
            # Do NOT break for keywords (READ, OPEN, CLOSE, etc.) that have no
            # registered parser — consuming them is required to avoid an infinite
            # loop where skip_to_next_statement keeps breaking on the same token.
            if token.value and is_statement_keyword(token.value):
                registry = self._parser._statement_registry
                if registry.find_parser(token_stream) is not None:
                    break

            token_stream.consume()
            if token.type not in self._FILLER_TOKEN_TYPES:
                at_call_start = False
