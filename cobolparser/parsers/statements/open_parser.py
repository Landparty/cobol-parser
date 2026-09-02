"""Open statement parser implementing IStatementParser interface."""

from typing import Any

from cobolparser.parsers.statements._utils import (
    SEPARATOR_TOKEN_TYPES,
    create_statement,
    is_statement_boundary,
    looks_dedented_relative_to,
    looks_like_paragraph_boundary,
    matches_keyword,
    skip_whitespace,
    token_column,
    token_value_upper,
    try_consume_keyword,
    warn_paragraph_boundary_swallowed,
)

from ...core.interfaces import IStatementParser, ITokenStream
from ...lexer import TokenType
from ...models.statements import IOOpenStatement

# Open modes recognized as IDENTIFIER tokens with these values
_OPEN_MODES = {"INPUT", "OUTPUT", "EXTEND"}
# I-O is also a mode but contains a hyphen


class OpenStatementParser(IStatementParser):
    """Parser for OPEN statements.

    Supports:
    - OPEN INPUT|OUTPUT|I-O|EXTEND file-name...
    - OPEN I-O file-name WITH REPOSITION (VSAM)
    """

    def matches(self, token_stream: ITokenStream) -> bool:
        return matches_keyword(token_stream, TokenType.OPEN, "OPEN")

    @staticmethod
    def _consume_open_option(token_stream: ITokenStream, stmt: IOOpenStatement) -> bool:
        """Consume one ``[WITH] NO REWIND`` / ``[WITH] LOCK`` / ``REVERSED`` /
        ``[WITH] REPOSITION`` option if present; True if anything was consumed."""
        consumed = False
        word = token_value_upper(token_stream.peek())
        if word == "WITH":
            token_stream.consume()
            skip_whitespace(token_stream)
            consumed = True
            word = token_value_upper(token_stream.peek())
        if word == "NO":
            token_stream.consume()
            skip_whitespace(token_stream)
            if token_value_upper(token_stream.peek()) == "REWIND":
                token_stream.consume()
            stmt.set_no_rewind(True)
            consumed = True
        elif word == "LOCK":
            token_stream.consume()
            stmt.set_with_lock(True)
            consumed = True
        elif word == "REVERSED":
            token_stream.consume()
            stmt.set_reversed(True)
            consumed = True
        elif word == "REPOSITION":
            token_stream.consume()
            stmt.set_reposition(True)
            consumed = True
        if consumed:
            skip_whitespace(token_stream)
        return consumed

    def parse(
        self, token_stream: ITokenStream, context: Any | None = None
    ) -> IOOpenStatement:
        """Parse an OPEN statement."""
        stmt, start_token = create_statement(token_stream, IOOpenStatement)
        start_column = token_column(start_token)

        skip_whitespace(token_stream)

        # Parse open mode: INPUT, OUTPUT, I-O, EXTEND
        current_mode: str | None = None
        token = token_stream.peek()
        if token and token.type == TokenType.IDENTIFIER and token.value:
            val = token.value.upper()
            if val in _OPEN_MODES or val == "I-O":
                current_mode = val
                stmt.set_open_mode(val)
                token_stream.consume()
                skip_whitespace(token_stream)

        # Parse one or more file names, possibly across several mode groups
        # (OPEN INPUT FILE-A OUTPUT FILE-B ...). `open_mode` keeps the first
        # group's mode for backward compatibility; `current_mode` tracks
        # whichever mode group is active as the loop advances so each file
        # is recorded (via `file_modes`) with its own mode rather than all
        # files being indistinguishably attributed to the first group's mode.
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type in SEPARATOR_TOKEN_TYPES:
                # ``OPEN INPUT SQ-FS1, SQ-FS3 OUTPUT SQ-FS4`` (NIST SQ206A)
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            # Per-file options -- ``[WITH] NO REWIND``, ``[WITH] LOCK``,
            # ``REVERSED``, ``[WITH] REPOSITION`` -- consumed here so they
            # are neither misread as file names (REVERSED was) nor left as
            # unparsed tokens (NO REWIND was).
            if self._consume_open_option(token_stream, stmt):
                continue
            if token.type == TokenType.IDENTIFIER and token.value:
                val = token.value.upper()
                # A subsequent open mode starts a new mode group: consume it,
                # update current_mode, and keep collecting its file names.
                if val in _OPEN_MODES or val == "I-O":
                    current_mode = val
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    continue
                # WITH REPOSITION for VSAM (when REPOSITION seen directly)
                if val == "REPOSITION":
                    token_stream.consume()
                    stmt.set_reposition(True)
                    skip_whitespace(token_stream)
                    continue
                # A following statement's verb that lexes as a plain
                # IDENTIFIER (e.g. PURGE/RAISE/RESUME have no dedicated
                # TokenType) must not be folded into the file-name list when
                # OPEN has no trailing period.
                if is_statement_boundary(token):
                    break
                # A missing period on this OPEN followed by what looks like
                # the next paragraph/section header (H9): stop instead of
                # folding it into the file-name list. Disambiguated by
                # indentation (Area A vs Area B) so a file name that merely
                # wraps onto its own continuation line -- legitimate for any
                # file in the list, not just the first -- isn't misread as a
                # boundary and dropped.
                if looks_like_paragraph_boundary(
                    token_stream
                ) and looks_dedented_relative_to(token_stream, start_column):
                    warn_paragraph_boundary_swallowed(token_stream)
                    break
                # Otherwise it's a file name
                stmt.add_file(token.value, current_mode)
                token_stream.consume()
                skip_whitespace(token_stream)
            else:
                break

        # Optional WITH REPOSITION
        # Lexer emits TokenType.WITH for "WITH" (not IDENTIFIER).
        if try_consume_keyword(token_stream, TokenType.WITH, "WITH"):
            token = token_stream.peek()
            if (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "REPOSITION"
            ):
                token_stream.consume()
                stmt.set_reposition(True)
                skip_whitespace(token_stream)

        # Consume period if present
        token = token_stream.peek()
        if token and token.type == TokenType.PERIOD:
            token_stream.consume()

        return stmt
