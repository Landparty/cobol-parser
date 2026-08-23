"""Data-item clause parsing for the DATA DIVISION.

Collaborator of :class:`~cobolparser.parsers.divisions.data.DataDivisionParser`:
parses one data-description entry (``level-number data-name [clauses].``) and
each of its clauses (PICTURE, VALUE, USAGE, SIGN, SYNCHRONIZED, JUSTIFIED,
BLANK WHEN ZERO, EXTERNAL, GLOBAL, REDEFINES, OCCURS).

The optional Cython fast path (``cobolparser._data_fast``) accelerates the
clause dispatch loop; it calls back into the parser's
``_parse_picture_clause`` / ``_parse_value_clause`` / ``_parse_usage_clause``
methods, which the ``DataDivisionParser`` keeps as stable delegating wrappers
around this class — so the compiled extension's callback surface is unchanged.
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem, OccursClause, PictureClause

# Constants for COMP/COMPUTATIONAL usage keywords and token types.
# These appear in multiple parsing methods; keeping them in one place avoids
# duplication and makes adding new variants trivial.
_COMP_KEYWORDS: frozenset[str] = frozenset(
    {
        "COMP",
        "COMP-1",
        "COMP-2",
        "COMP-3",
        "COMP-4",
        "COMP-5",
        "COMPUTATIONAL",
        "COMPUTATIONAL-1",
        "COMPUTATIONAL-2",
        "COMPUTATIONAL-3",
        "COMPUTATIONAL-4",
        "COMPUTATIONAL-5",
        "BINARY",
        "PACKED-DECIMAL",
    }
)

_COMP_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.COMP_1,
        TokenType.COMP_2,
        TokenType.COMP_3,
        TokenType.COMP_4,
        TokenType.COMP_5,
    }
)

_POINTER_KEYWORDS: frozenset[str] = frozenset(
    {
        "POINTER",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
    }
)

# Hoisted out of _parse_picture_clause -- the union was being rebuilt on
# every iteration of that method's inner loop.
_PICTURE_TERMINATOR_KEYWORDS: frozenset[str] = frozenset(
    _COMP_KEYWORDS
    | _POINTER_KEYWORDS
    | {
        "VALUE",
        "USAGE",
        "OCCURS",
        "REDEFINES",
        "SIGN",
        "SYNCHRONIZED",
        "SYNC",
        "JUSTIFIED",
        "JUST",
        "BLANK",
        "EXTERNAL",
        "GLOBAL",
    }
)
_PICTURE_PATTERN_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.IDENTIFIER,
        TokenType.NUMERIC_LITERAL,
        TokenType.STRING_LITERAL,
        TokenType.LEVEL_NUMBER,
    }
)
# Editing symbols that the lexer emits as their own token types (rather than
# folding into an IDENTIFIER): currency ($), fixed/floating sign (+/-), and the
# check-protect (*) and stroke (/) insertion characters. Collected verbatim so
# edited pictures such as ``$$$,$$9.99`` or ``ZZ9.99-`` survive extraction.
_PICTURE_SYMBOL_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.CURRENCY,
        TokenType.MINUS,
        TokenType.PLUS,
        TokenType.MULTIPLY_OP,  # '*' check-protect symbol -- NOT the MULTIPLY
        TokenType.DIVIDE_OP,  # '/' stroke/slash editing symbol -- NOT the DIVIDE
        # *statement* keyword tokens (see reports/open-findings.md M16: using
        # the statement tokens here silently truncated slash/asterisk-edited
        # PICTURE patterns at the first edit symbol).
    }
)
# Token types that may legitimately follow an *interior* decimal point in a
# picture (i.e. the fractional digits / edit symbols).
_PICTURE_DECIMAL_FOLLOW_TYPES: frozenset[TokenType] = (
    _PICTURE_PATTERN_TOKEN_TYPES | _PICTURE_SYMBOL_TOKEN_TYPES
)

_DIVISION_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.IDENTIFICATION_DIVISION,
        TokenType.ENVIRONMENT_DIVISION,
        TokenType.DATA_DIVISION,
        TokenType.PROCEDURE_DIVISION,
    }
)

# Non-meaningful tokens (layout only) that the clause loop skips silently —
# warning on these would be noise.
_WHITESPACE_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.NEWLINE,
        TokenType.WHITESPACE,
        TokenType.COMMENT,
        TokenType.CONTINUATION,
    }
)

# Optional Cython acceleration for the picture-clause inner loop. The
# pure-Python implementation in ``parse_picture_clause`` below remains
# the authoritative behaviour; we only delegate when the extension is
# available and the token stream is the standard ``TokenStream`` (so we
# can safely poke its underlying token list and cursor).
try:
    from cobolparser._data_fast import (  # type: ignore[import-not-found]
        parse_data_item_clauses_fast as _fast_data_item_clauses,
    )

    _HAS_DATA_FAST = True
except ImportError:
    _fast_data_item_clauses = None
    _HAS_DATA_FAST = False


class DataItemClauseParser:
    """Parses a single data-description entry and its clauses.

    Holds a back-reference to the owning :class:`DataDivisionParser` so
    warnings reach the host parser's warning channel and so the Cython fast
    path can call back through the parser's stable wrapper methods.
    """

    def __init__(self, parser: Any) -> None:
        """Initialize with the owning division parser.

        Args:
            parser: The ``DataDivisionParser`` this collaborator belongs to.
        """
        self._parser = parser

    def parse_data_item(self, token_stream: ITokenStream) -> CobolDataItem | None:
        """Parse a single data item definition.

        Format: level-number data-name [clauses].

        Args:
            token_stream: Token stream positioned at level number

        Returns:
            CobolDataItem or None if parsing fails
        """
        token = token_stream.peek()
        if not token or token.type != TokenType.LEVEL_NUMBER:
            return None

        try:
            level = int(token.value)
        except (ValueError, AttributeError):
            return None

        location = token.location
        token_stream.consume()  # Consume level number

        # Get data name
        name = None
        token = token_stream.peek()

        if token and token.type == TokenType.IDENTIFIER:
            name = token.value
            token_stream.consume()
        elif token and token.value and token.value.upper() == "FILLER":
            name = "FILLER"
            token_stream.consume()
        else:
            # Anonymous data item; ``location`` is always a SourceLocation.
            name = f"ANONYMOUS-{level}-{location.line}"

        # Create data item
        data_item = CobolDataItem(name, level, location)

        # Fast path: drive the common-clause loop in Cython. VALUE and
        # USAGE clauses call back into the Python helpers below via
        # ``parser_self``. The fast helper handles only the hot clauses
        # (PICTURE, VALUE, USAGE, COMP, REDEFINES, OCCURS) and bails back
        # on any clause it does not recognize (SIGN, SYNCHRONIZED,
        # JUSTIFIED, BLANK, POINTER, EXTERNAL, GLOBAL, ...). We then fall
        # through to the pure-Python loop below, which is the single
        # source of truth for those clauses -- so the two implementations
        # can never drift on the rarer clauses.
        if _HAS_DATA_FAST:
            tokens_list = getattr(token_stream, "_tokens", None)
            if tokens_list is not None:
                new_pos = _fast_data_item_clauses(
                    tokens_list,
                    token_stream._pos,  # type: ignore[attr-defined]
                    data_item,
                    location,
                    self._parser,
                    token_stream,
                    _PICTURE_TERMINATOR_KEYWORDS,
                    _PICTURE_PATTERN_TOKEN_TYPES,
                    _COMP_KEYWORDS,
                    _COMP_TOKEN_TYPES,
                    _DIVISION_TOKEN_TYPES,
                    PictureClause,
                    OccursClause,
                    TokenType.PERIOD,
                    TokenType.LEVEL_NUMBER,
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.NEWLINE,
                    TokenType.COMMA,
                )
                token_stream._pos = new_pos  # type: ignore[attr-defined]
                # Fall through (no early return): the Python loop below
                # finishes any clauses the fast helper handed back.

        # Parse clauses until period or next item
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            tok_type = token.type

            # Period ends this data item
            if tok_type == TokenType.PERIOD:
                token_stream.consume()
                break

            # Level number starts next item
            if tok_type == TokenType.LEVEL_NUMBER:
                break

            # Division tokens end this data item (don't consume them)
            if tok_type in _DIVISION_TOKEN_TYPES:
                break

            # An EXEC SQL block ends this data item without consuming it.
            # A data-division EXEC SQL statement (e.g. DCLGEN's
            # ``EXEC SQL INCLUDE SQLCA END-EXEC``) is recognized by the
            # section-level scan loop (``DataDivisionParser._parse_section``)
            # -- but only when that loop sees the leading EXEC token fresh.
            # If the previous data item's terminating period was omitted
            # (a common real-world slip, especially right before a COPY- or
            # DCLGEN-inserted block), this per-item clause loop would
            # otherwise treat EXEC/SQL/INCLUDE/SQLCA/END-EXEC one token at a
            # time as unrecognized clauses and drop the whole SQL statement
            # from the AST. Breaking here (implicitly closing the item, same
            # as the LEVEL_NUMBER/division-token cases above) hands the EXEC
            # token back to the section loop so it parses normally.
            if tok_type == TokenType.EXEC or (
                tok_type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "EXEC"
            ):
                nxt = self._peek_next_meaningful(token_stream)
                if nxt and (
                    nxt.type == TokenType.SQL
                    or (
                        nxt.type == TokenType.IDENTIFIER
                        and nxt.value
                        and nxt.value.upper() == "SQL"
                    )
                ):
                    break

            # Compute upper-cased token value once -- the chain of clause
            # checks below would otherwise call ``.upper()`` up to six times
            # per loop iteration on the same string.
            value_upper = token.value.upper() if token.value else ""

            #  PICTURE/PIC clause
            if value_upper == "PICTURE" or value_upper == "PIC":
                token_stream.consume()  # Consume PIC keyword
                picture_pattern = self.parse_picture_clause(token_stream)
                if picture_pattern:
                    data_item.set_picture_clause(
                        PictureClause(picture_pattern, location)
                    )

            # VALUE clause
            elif value_upper == "VALUE":
                token_stream.consume()  # Consume VALUE keyword
                value = self.parse_value_clause(token_stream)
                if value:
                    data_item.set_value_clause(value)

            # USAGE clause
            elif value_upper == "USAGE":
                token_stream.consume()  # Consume USAGE keyword
                usage = self.parse_usage_clause(token_stream)
                if usage:
                    data_item.set_usage(usage)

            # COMP, COMP-3, etc. without USAGE keyword
            elif value_upper in _COMP_KEYWORDS:
                data_item.set_usage(value_upper)
                token_stream.consume()

            # Also check for COMP token types (COMP_1, COMP_2, COMP_3, etc.)
            elif token.type in _COMP_TOKEN_TYPES:
                data_item.set_usage(token.value.upper())
                token_stream.consume()

            # POINTER, PROCEDURE-POINTER, FUNCTION-POINTER without USAGE keyword
            elif value_upper in _POINTER_KEYWORDS:
                data_item.set_usage(value_upper)
                token_stream.consume()

            # INDEX without the USAGE keyword: ``05 X [USAGE [IS]] INDEX.``
            # -- both USAGE and IS are optional in the grammar, and INDEX
            # is a reserved word, so a bare INDEX in clause position is
            # unambiguously the usage (a data item can never be *named*
            # INDEX). USAGE IS INDEX already worked via parse_usage_clause;
            # only this bare form fell through to the unknown-clause branch
            # and was dropped with an "Unparsed token 'INDEX'" warning.
            elif value_upper == "INDEX":
                data_item.set_usage("INDEX")
                token_stream.consume()

            # SIGN clause: SIGN [IS] LEADING|TRAILING [SEPARATE [CHARACTER]]
            # (each keyword may start a continuation line -- and the
            # direction read is restricted to LEADING/TRAILING: the old
            # any-truthy-value read recorded a raw "\n" as the sign clause
            # whenever SIGN IS landed at the end of a 72-column line)
            elif value_upper == "SIGN":
                token_stream.consume()
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "IS":
                    token_stream.consume()
                self._skip_newlines(token_stream)
                dir_tok = token_stream.peek()
                if (
                    dir_tok
                    and dir_tok.value
                    and dir_tok.value.upper()
                    in (
                        "LEADING",
                        "TRAILING",
                    )
                ):
                    direction = dir_tok.value.upper()
                    token_stream.consume()
                    self._skip_newlines(token_stream)
                    sep = token_stream.peek()
                    if sep and sep.value and sep.value.upper() == "SEPARATE":
                        token_stream.consume()
                        self._skip_newlines(token_stream)
                        ch = token_stream.peek()
                        if ch and ch.value and ch.value.upper() == "CHARACTER":
                            token_stream.consume()
                        direction = direction + " SEPARATE"
                    data_item.sign_clause = direction

            # SYNCHRONIZED / SYNC [IS] [LEFT|RIGHT] clause
            elif value_upper in {"SYNCHRONIZED", "SYNC"}:
                data_item.synchronized = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.type == TokenType.IS:
                    token_stream.consume()
                    nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() in {"LEFT", "RIGHT"}:
                    token_stream.consume()

            # JUSTIFIED / JUST [IS] [RIGHT] clause
            elif value_upper in {"JUSTIFIED", "JUST"}:
                data_item.justified = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.type == TokenType.IS:
                    token_stream.consume()
                    nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "RIGHT":
                    token_stream.consume()

            # BLANK WHEN ZERO clause
            elif value_upper == "BLANK":
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "WHEN":
                    token_stream.consume()
                nxt = token_stream.peek()
                if (
                    nxt
                    and nxt.value
                    and nxt.value.upper() in {"ZERO", "ZEROS", "ZEROES"}
                ):
                    token_stream.consume()
                data_item.blank_when_zero = True

            # EXTERNAL clause: [IS] EXTERNAL [AS literal]
            elif value_upper == "EXTERNAL":
                data_item.is_external = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "AS":
                    token_stream.consume()
                    lit = token_stream.peek()
                    if lit and lit.type in (
                        TokenType.STRING_LITERAL,
                        TokenType.IDENTIFIER,
                    ):
                        token_stream.consume()

            # GLOBAL clause: [IS] GLOBAL
            elif value_upper == "GLOBAL":
                data_item.is_global = True
                token_stream.consume()

            # Leading "IS" ahead of EXTERNAL / GLOBAL / a bare
            # USAGE-family keyword (POINTER, PROCEDURE-POINTER,
            # FUNCTION-POINTER, INDEX). EXTERNAL and GLOBAL are standard
            # "[IS] <keyword>" clauses; the USAGE-omitted POINTER/INDEX
            # forms accept the same optional "IS" as a real-world IBM
            # Enterprise convention. The keyword itself is handled by its
            # own branch above/below on the very next loop iteration, so
            # this branch only needs to swallow the "IS" -- silently,
            # since nothing is actually lost. Falling through to the
            # generic "unknown token" branch instead would misreport a
            # dropped-content warning for a clause that in fact parsed
            # completely.
            elif value_upper == "IS":
                nxt = self._peek_next_meaningful(token_stream)
                nxt_upper = nxt.value.upper() if nxt and nxt.value else ""
                if nxt_upper in _POINTER_KEYWORDS or nxt_upper in (
                    "EXTERNAL",
                    "GLOBAL",
                    "INDEX",
                ):
                    token_stream.consume()  # Consume the optional IS
                else:
                    self._warn_dropped_data_token(token, data_item)
                    token_stream.consume()

            # REDEFINES clause
            elif value_upper == "REDEFINES":
                token_stream.consume()  # Consume REDEFINES keyword
                # The target may sit on the next line (continuation).
                self._skip_newlines(token_stream)
                redef_token = token_stream.peek()
                if redef_token and redef_token.type == TokenType.IDENTIFIER:
                    data_item.set_redefines(redef_token.value)
                    token_stream.consume()

            # OCCURS clause
            elif value_upper == "OCCURS":
                token_stream.consume()  # Consume OCCURS keyword
                self._parse_occurs_clause(token_stream, data_item, location)

            else:
                # Skip unknown tokens/clauses. PERIOD, LEVEL_NUMBER, and
                # division tokens are already handled at the top of the
                # loop (they ``break`` before we get here), so the only
                # remaining case is "consume and continue". Record a warning
                # for meaningful (non-whitespace) tokens so a data-item clause
                # this parser does not yet support (GROUP-USAGE, VOLATILE,
                # DYNAMIC LENGTH, ...) is not dropped completely silently —
                # symmetric with the ENVIRONMENT division's SELECT handling.
                self._warn_dropped_data_token(token, data_item)
                token_stream.consume()

        return data_item

    def _parse_occurs_clause(
        self,
        token_stream: ITokenStream,
        data_item: CobolDataItem,
        location: SourceLocation,
    ) -> None:
        """Parse an OCCURS clause (the OCCURS keyword is already consumed).

        Handles fixed and variable (``min TO max DEPENDING ON var``) table
        sizes, repeatable ``ASCENDING/DESCENDING KEY`` clauses, and
        ``INDEXED BY`` index names. Attaches the resulting
        :class:`OccursClause` to *data_item* when a table size was captured.
        """
        occurs = OccursClause(location)

        # Read first (minimum or fixed) count. The count may sit on the
        # line after OCCURS (a long data name pushing OCCURS to the end of
        # its 72-column line is routine in real decks) -- without crossing
        # the line break, a two-digit count on the next line (which lexes
        # as LEVEL_NUMBER) was misread by the caller's clause loop as a
        # *new data item's level number*, fabricating a phantom item while
        # this OCCURS silently recorded a table size of 0. The crossing is
        # guarded, though: when the count would come from a *following*
        # line and is a LEVEL_NUMBER token, it is only accepted if the
        # token after it reads like the OCCURS clause continuing -- else a
        # malformed ``OCCURS`` with no count at all would swallow the
        # *next data item's own level number* as the count, deleting that
        # item from the AST (a worse failure than the missing count).
        # Same-line counts keep the historical unconditional read.
        min_count = 0
        max_count = 0
        count_token, count_offset = self._peek_count_token(token_stream)
        if count_token is not None:
            try:
                min_count = int(count_token.value)
                max_count = min_count
            except (TypeError, ValueError):
                pass
            for _ in range(count_offset + 1):
                token_stream.consume()

        # Variable OCCURS: OCCURS min TO max [TIMES] DEPENDING ON var
        # (TO and the max count may each start a continuation line too;
        # the max-count read carries the same crossing guard as the first)
        self._skip_newlines(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "TO":
            token_stream.consume()  # consume TO
            max_token, max_offset = self._peek_count_token(token_stream)
            if max_token is not None:
                try:
                    max_count = int(max_token.value)
                except (TypeError, ValueError):
                    max_count = min_count
                for _ in range(max_offset + 1):
                    token_stream.consume()

        # Skip optional TIMES keyword (may be preceded by newlines)
        self._skip_newlines(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "TIMES":
            token_stream.consume()

        # DEPENDING ON clause (ON and the variable may each start a
        # continuation line; the variable read requires an IDENTIFIER, so
        # crossing the break can never swallow a level number)
        depending_var = None
        self._skip_newlines(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "DEPENDING":
            token_stream.consume()  # consume DEPENDING
            self._skip_newlines(token_stream)
            on_token = token_stream.peek()
            if on_token and on_token.value and on_token.value.upper() == "ON":
                token_stream.consume()  # consume ON
            self._skip_newlines(token_stream)
            dep_token = token_stream.peek()
            if dep_token and dep_token.type == TokenType.IDENTIFIER:
                depending_var = dep_token.value
                token_stream.consume()

        # ASCENDING / DESCENDING KEY IS key-1 [key-2 ...] clauses
        # (may repeat). These sit between DEPENDING ON and INDEXED BY
        # in standard COBOL and are what makes a table valid for
        # SEARCH ALL (binary search), so dropping them loses real
        # semantics — and previously it also cascaded into dropping a
        # following INDEXED BY clause.
        self._skip_newlines(token_stream)
        nxt = token_stream.peek()
        while (
            nxt
            and nxt.value
            and nxt.value.upper()
            in (
                "ASCENDING",
                "DESCENDING",
            )
        ):
            direction = nxt.value.upper()
            token_stream.consume()  # consume ASCENDING/DESCENDING
            self._skip_newlines(token_stream)
            key_kw = token_stream.peek()
            if key_kw and key_kw.value and key_kw.value.upper() == "KEY":
                token_stream.consume()  # consume KEY
            self._skip_newlines(token_stream)
            is_kw = token_stream.peek()
            if is_kw and is_kw.value and is_kw.value.upper() == "IS":
                token_stream.consume()  # consume optional IS
            keys: list[str] = []
            while True:
                self._skip_newlines(token_stream)
                key_token = token_stream.peek()
                if key_token and key_token.type == TokenType.COMMA:
                    # Comma-separated key list: the comma is only a
                    # separator, never a key name -- consume and continue.
                    token_stream.consume()
                    continue
                if (
                    key_token
                    and key_token.type == TokenType.IDENTIFIER
                    and key_token.value
                    and key_token.value.upper()
                    not in ("ASCENDING", "DESCENDING", "INDEXED", "KEY")
                ):
                    keys.append(key_token.value)
                    token_stream.consume()
                else:
                    break
            if keys:
                occurs.add_key_clause(direction, keys)
            self._skip_newlines(token_stream)
            nxt = token_stream.peek()

        # INDEXED BY clause (one or more index names, optionally
        # comma-separated; INDEXED and BY may straddle a line break)
        self._skip_newlines(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "INDEXED":
            token_stream.consume()  # consume INDEXED
            self._skip_newlines(token_stream)
            by_token = token_stream.peek()
            if by_token and by_token.value and by_token.value.upper() == "BY":
                token_stream.consume()  # consume BY
            while True:
                self._skip_newlines(token_stream)
                idx_token = token_stream.peek()
                if idx_token and idx_token.type == TokenType.COMMA:
                    token_stream.consume()
                    continue
                if idx_token and idx_token.type == TokenType.IDENTIFIER:
                    occurs.add_index_name(idx_token.value)
                    token_stream.consume()
                else:
                    break

        if depending_var:
            occurs.set_variable_occurs(min_count, max_count, depending_var)
        else:
            occurs.set_fixed_occurs(max_count)

        if occurs.max_times is not None:
            data_item.set_occurs_clause(occurs)

    def _warn_dropped_data_token(self, token: Any, data_item: Any) -> None:
        """Record a warning for an unrecognized data-item clause token."""
        if token is None or token.type in _WHITESPACE_TOKEN_TYPES:
            return
        value = (token.value or "").strip() if token.value else ""
        if not value:
            return
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        item_name = getattr(data_item, "name", None) or "?"
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(
                f"Unparsed token '{value}'{where} in data item '{item_name}' "
                "skipped: clause not fully supported; content dropped from the AST"
            )

    @staticmethod
    def _peek_next_meaningful(
        token_stream: ITokenStream, offset: int = 1, max_lookahead: int = 32
    ) -> Any:
        """Look ahead past layout-only tokens (NEWLINE/WHITESPACE/COMMENT/
        CONTINUATION), starting at ``offset`` token(s) past the current
        position. Unlike a plain ``peek(offset)``, this tolerates a clause
        keyword landing on a later source line than the token that precedes
        it (e.g. ``IS`` at end of line, the keyword on the next), which a
        fixed-offset peek would otherwise misclassify as "not this pattern".
        """
        i = offset
        limit = offset + max_lookahead
        while i < limit:
            tok = token_stream.peek(i)
            if tok is None:
                return None
            if tok.type not in _WHITESPACE_TOKEN_TYPES:
                return tok
            i += 1
        return None

    @staticmethod
    def _skip_newlines(token_stream: ITokenStream) -> None:
        """Consume any NEWLINE tokens at the current position."""
        while not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.NEWLINE:
                token_stream.consume()
            else:
                break

    @staticmethod
    def _peek_count_token(token_stream: ITokenStream) -> tuple[Any, int]:
        """Locate an OCCURS count/max token without consuming anything.

        Returns ``(token, newline_offset)`` where *newline_offset* is how
        many NEWLINE tokens precede the count at the current position, or
        ``(None, 0)`` when no acceptable count is present. Non-destructive
        so the caller can decline to cross a line break.

        Acceptance rules encode the error-recovery guard the plain
        skip-newlines-then-read version lacked: a NUMERIC_LITERAL (3+
        digits -- can never start a data item) is always the count; a
        LEVEL_NUMBER on the *same* line keeps the historical unconditional
        read; a LEVEL_NUMBER on a *following* line is the count only when
        the token after it (past further newlines) reads like the OCCURS
        clause continuing (TIMES/TO/DEPENDING/INDEXED/ASCENDING/
        DESCENDING/PIC...). Otherwise -- e.g. a malformed ``OCCURS`` with
        no count, followed by the next item's ``05  WS-NEXT`` -- the
        two-digit token is that next item's own level number, and
        consuming it would delete the item from the AST.
        """
        offset = 0
        tok = token_stream.peek(offset)
        while tok is not None and tok.type == TokenType.NEWLINE:
            offset += 1
            tok = token_stream.peek(offset)
        if tok is None:
            return None, 0
        if tok.type == TokenType.NUMERIC_LITERAL:
            return tok, offset
        if tok.type != TokenType.LEVEL_NUMBER:
            return None, 0
        if offset == 0:
            return tok, 0
        follow_offset = offset + 1
        follow = token_stream.peek(follow_offset)
        while follow is not None and follow.type == TokenType.NEWLINE:
            follow_offset += 1
            follow = token_stream.peek(follow_offset)
        follow_upper = follow.value.upper() if follow and follow.value else ""
        if follow_upper in (
            "TIMES",
            "TO",
            "DEPENDING",
            "INDEXED",
            "ASCENDING",
            "DESCENDING",
            "PIC",
            "PICTURE",
        ):
            return tok, offset
        return None, 0

    @staticmethod
    def _period_is_picture_decimal(period: Any, nxt: Any) -> bool:
        """Decide whether a PERIOD token is an editing decimal point.

        An interior decimal point is written with no surrounding space, so the
        next token sits on the same line in the immediately adjacent column and
        is itself a picture symbol (e.g. the ``.`` in ``ZZ9.99``). The entry's
        terminating period, by contrast, is followed by whitespace, a newline,
        or a different construct.
        """
        if nxt is None or nxt.type in (TokenType.NEWLINE, TokenType.EOF):
            return False
        if nxt.type not in _PICTURE_DECIMAL_FOLLOW_TYPES:
            return False
        ploc = period.location
        nloc = nxt.location
        if ploc is None or nloc is None:
            return False
        return bool(nloc.line == ploc.line and nloc.column == ploc.column + 1)

    def parse_picture_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse PICTURE clause pattern.

        Returns the picture pattern string (e.g., 'X(10)', '9(5)', '9(7)V99',
        'ZZ,ZZ9.99-', '$$$,$$9.99'). This is the single implementation used by
        both the pure-Python and Cython-accelerated data-item paths; the fast
        clause loop delegates here so the two can never drift.
        """
        # Optional IS: PICTURE IS <pattern> / PIC IS <pattern>. Consumed
        # here (rather than by callers) so both the pure-Python and
        # Cython-accelerated dispatch loops get it via this shared method.
        # Previously unhandled: the pattern-token dispatch below has no
        # branch for TokenType.IS, so an unconsumed IS fell straight
        # through to the caller's clause loop, which (seeing no picture
        # pattern was returned) moved on and then silently dropped IS, the
        # whole pattern, and any numeric literal in it (misread as a new
        # data item's level number) as unrecognized clause tokens.
        self._skip_newlines(token_stream)
        is_token = token_stream.peek()
        if is_token and is_token.type == TokenType.IS:
            token_stream.consume()
            self._skip_newlines(token_stream)

        pattern_parts = []
        paren_depth = 0  # Track parenthesis nesting

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            # Stop at specific keywords when outside parentheses
            if paren_depth == 0:
                if token.type == TokenType.PERIOD:
                    # An interior '.' is an editing decimal point and stays in
                    # the pattern; the terminating period ends the clause.
                    if self._period_is_picture_decimal(token, token_stream.peek(1)):
                        pattern_parts.append(".")
                        token_stream.consume()
                        continue
                    break
                # Stop at keywords that follow picture clause
                if token.value and token.value.upper() in _PICTURE_TERMINATOR_KEYWORDS:
                    break
                # Also stop at COMP token types
                if token.type in _COMP_TOKEN_TYPES:
                    break

            # Collect picture pattern tokens
            if token.type in _PICTURE_PATTERN_TOKEN_TYPES:
                # All these token types can be part of a picture pattern
                token_value = token.value
                if paren_depth == 0 and token_value.endswith("."):
                    pattern_parts.append(token_value[:-1])
                    token_stream.consume()
                    break
                pattern_parts.append(token_value)
                token_stream.consume()
            # Editing symbols emitted as their own token types ($ + - * /)
            elif token.type in _PICTURE_SYMBOL_TOKEN_TYPES:
                pattern_parts.append(token.value)
                token_stream.consume()
            elif token.value == "(":
                pattern_parts.append(token.value)
                paren_depth += 1
                token_stream.consume()
            elif token.value == ")":
                pattern_parts.append(token.value)
                paren_depth -= 1
                token_stream.consume()
            elif token.value == ",":
                pattern_parts.append(token.value)
                token_stream.consume()
            elif token.type == TokenType.NEWLINE:
                if paren_depth == 0:
                    next_item_token = self._picture_clause_next_item_token(token_stream)
                    if next_item_token is not None:
                        self._warn_picture_clause_missing_terminator(next_item_token)
                        break
                token_stream.consume()
            else:
                break

        result = "".join(pattern_parts) if pattern_parts else None
        return result

    @staticmethod
    def _picture_clause_next_item_token(token_stream: ITokenStream) -> Any:
        """Look past the NEWLINE at the current stream position for a fresh
        ``level-number [data-name]`` header (the start of the *next* data
        item entry, possibly anonymous/FILLER) rather than more picture
        pattern.

        A bare, unparenthesized LEVEL_NUMBER never legally appears inside a
        PICTURE pattern -- occurrence/repetition counts are always written
        in parentheses (e.g. ``9(05)``) -- but the lexer types every 1-2
        digit integer as LEVEL_NUMBER regardless of context, including the
        legitimate case of a multi-line picture pattern built only from the
        two digit-shaped picture symbols, ``9`` (digit position) and ``0``
        (zero-insertion) -- e.g. a pattern split as ``PIC 9\\n99.``. Two
        independent signals distinguish a genuine next-item header from
        that case:

        - The LEVEL_NUMBER's value contains a digit other than ``0``/``9``
          (e.g. the ``5`` in ``05``) -- no legal PICTURE symbol produces
          such a digit, so the token can only be a real level number,
          regardless of what follows it (covers unnamed/anonymous items
          and items introduced directly by a clause keyword, e.g.
          ``05  REDEFINES ...`` with no data-name).
        - The LEVEL_NUMBER is immediately followed by an IDENTIFIER (a
          named or ``FILLER`` data item -- both lex as IDENTIFIER) --
          covers the remaining case of an all-0/9 level number (``99``,
          ``90``, ...) that happens to carry a name.

        Returns the LEVEL_NUMBER token when either signal fires, else None
        -- preserving the legitimate multi-line PICTURE continuation case
        (e.g. ``PIC 9(5)\\n   V99.``), where the token after the newline is
        not a LEVEL_NUMBER at all.
        """
        offset = 0
        token = token_stream.peek(offset)
        while token is not None and token.type == TokenType.NEWLINE:
            offset += 1
            token = token_stream.peek(offset)
        if token is None or token.type != TokenType.LEVEL_NUMBER:
            return None
        value = token.value or ""
        if value and any(ch not in "09" for ch in value):
            return token
        next_token = token_stream.peek(offset + 1)
        if next_token is None or next_token.type != TokenType.IDENTIFIER:
            return None
        return token

    def _warn_picture_clause_missing_terminator(self, next_item_token: Any) -> None:
        """Record a warning when a PICTURE clause is stopped early because
        what follows its newline looks like the next data item's own
        level-number/name pair. Consistent with the ``ParseResult.warnings``
        "dropped-content signal" contract other silent-drop fixes in this
        codebase use -- this is the difference between a clean-looking
        `success=True, warnings=[]` parse and one that actually lost data.
        """
        line = getattr(getattr(next_item_token, "location", None), "line", None)
        where = f" before line {line}" if line else ""
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(
                f"PICTURE clause has no terminating period{where}: stopped "
                "at what looks like the next data item's level number and "
                "name; the terminating period may have been lost to "
                "fixed-format column-72 truncation"
            )

    def parse_value_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse VALUE clause value.

        Returns the value string.

        The lexer types 1-2 digit integers as LEVEL_NUMBER everywhere (even
        after VALUE), so LEVEL_NUMBER is accepted as a numeric literal here —
        after a consumed VALUE keyword a level number can only be a literal.
        A MINUS/PLUS token followed by a numeric is a signed literal.

        The clause's operand may start on the physical line after the
        `VALUE`/`IS` keyword with no fixed-format `-` continuation
        indicator required (ordinary multi-line clause continuation, legal
        COBOL, same as any other clause in this division) -- so NEWLINE
        tokens are skipped both before and after an optional `IS`, mirroring
        `_skip_newlines`'s use elsewhere in this file (e.g. the OCCURS
        ASCENDING/DESCENDING KEY and INDEXED BY clauses).
        """
        self._skip_newlines(token_stream)
        token = token_stream.peek()
        if not token:
            return None

        # Optional IS: VALUE IS <literal>
        if token.type == TokenType.IS:
            token_stream.consume()
            self._skip_newlines(token_stream)
            token = token_stream.peek()
            if not token:
                return None

        # ALL <literal>: the literal (or figurative constant) fills the
        # item by repetition, e.g. VALUE ALL '='. Returned as
        # `ALL "<literal>"` so the clause round-trips as legal COBOL
        # (MOVE ALL "=" TO X). A bare ALL with nothing repeatable after
        # it keeps the previous plain-figurative-constant behavior.
        if token.type == TokenType.FIGURATIVE_CONSTANT and token.value.upper() == "ALL":
            token_stream.consume()
            self._skip_newlines(token_stream)
            literal = token_stream.peek()
            if literal and literal.type == TokenType.STRING_LITERAL:
                token_stream.consume()
                return f'ALL "{literal.value}"'
            if literal and literal.type == TokenType.FIGURATIVE_CONSTANT:
                token_stream.consume()
                return f"ALL {literal.value}"
            return "ALL"

        sign = ""
        if token.type in (TokenType.MINUS, TokenType.PLUS):
            next_token = token_stream.peek(1)
            if next_token and next_token.type in (
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
            ):
                sign = token.value
                token_stream.consume()
                token = next_token
            else:
                return None

        if token.type in [
            TokenType.STRING_LITERAL,
            TokenType.NUMERIC_LITERAL,
            TokenType.FIGURATIVE_CONSTANT,
            TokenType.LEVEL_NUMBER,
        ]:
            value = (
                f'"{token.value}"'
                if token.type == TokenType.STRING_LITERAL
                else f"{sign}{token.value}"
            )
            token_stream.consume()
            return value
        elif token.type == TokenType.IDENTIFIER:
            value = token.value
            token_stream.consume()
            return value

        return None

    def parse_usage_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse USAGE clause value.

        Returns the usage type (e.g., COMP-3, COMP-5, DISPLAY, DISPLAY-1).

        Optional IS: USAGE IS <keyword> / USAGE <keyword>. Consumed here,
        mirroring the ``parse_picture_clause`` / ``parse_value_clause`` IS
        handling above, so a leading IS token doesn't fall through
        unmatched (none of the branches below accept ``TokenType.IS``) and
        get silently dropped -- with a spurious "Unparsed token" warning --
        by the caller's generic clause-recovery branch.
        """
        self._skip_newlines(token_stream)
        is_token = token_stream.peek()
        if is_token and is_token.type == TokenType.IS:
            token_stream.consume()
            self._skip_newlines(token_stream)

        token = token_stream.peek()
        if not token:
            return None

        # Check for COMP token types first (COMP_1, COMP_2, etc.)
        if token.type in _COMP_TOKEN_TYPES:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        # DISPLAY-1 lexes as its own token type (see lexer.py's DISPLAY-1
        # keyword mapping), not IDENTIFIER and not a value in
        # _COMP_KEYWORDS, so it needs an explicit check here.
        if token.type == TokenType.DISPLAY_1:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        # Check for regular IDENTIFIER
        if token.type == TokenType.IDENTIFIER:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        # Check for COMP variations that are tokenized differently
        if token.value and token.value.upper() in _COMP_KEYWORDS:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        return None
