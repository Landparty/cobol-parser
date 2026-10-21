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

That extension is compiled separately from this module and can therefore be
older than it. It is only looked for under ``COBOLPARSER_ACCEL=1``; when it
is, ``_data_fast_usable`` probes the compiled helper once at import
and disables the fast path (with a warning naming the rebuild) when it does not
match, so a stale binary costs speed rather than correctness.
"""

import logging
from typing import Any

from cobolparser._accel import accelerators_enabled
from cobolparser._literals import quote_literal
from cobolparser._storage import FIXED_SIZE_USAGES, is_known_usage
from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem, OccursClause, PictureClause
from cobolparser.parsers.statements._utils import peek_past_noise

logger = logging.getLogger(__name__)

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
        # COBOL 2002 usages, which may also be written without the USAGE
        # keyword (``05 X BINARY-LONG.``), #524. ``_data_fast`` receives
        # this set as an argument, so both clause loops accept them.
        "FLOAT-SHORT",
        "FLOAT-LONG",
        *FIXED_SIZE_USAGES,
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
        "POINTER-32",
        "POINTER-64",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
    }
)

# USAGE values with no token type of their own that may be written without
# the USAGE keyword. ``DISPLAY-1`` is a token type of its own
# (``TokenType.DISPLAY_1``) and is matched on that as well.
_BARE_USAGE_WORDS: frozenset[str] = frozenset({"NATIONAL", "UTF-8", "DISPLAY-1"})

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
        # ``PIC S999 LEADING SEPARATE`` -- the SIGN word itself is optional
        # (NIST NC117A/NC118A), so the direction words must stop the
        # picture scan too, or they are glued into the pattern.
        "LEADING",
        "TRAILING",
        "SEPARATE",
        "SYNCHRONIZED",
        "SYNC",
        "JUSTIFIED",
        "JUST",
        "BLANK",
        "EXTERNAL",
        "GLOBAL",
        # Enterprise COBOL 6.x clauses that may follow a PICTURE: ``PIC X(8)
        # VOLATILE``, ``PIC U BYTE-LENGTH 120``, ``PIC U DYNAMIC LENGTH``,
        # and OO COBOL's ``OBJECT REFERENCE``. None is a picture symbol
        # string, so each is a safe terminator.
        "VOLATILE",
        # ``PIC X(50) BASED`` (Micro Focus / GnuCOBOL; pairs with ALLOCATE
        # and FREE). It used to be glued onto the picture (``X(50)BASED``).
        "BASED",
        "BYTE-LENGTH",
        "DYNAMIC",
        "OBJECT",
        # The USAGE word is optional, so ``PIC N(5) NATIONAL`` / ``PIC U(4)
        # UTF-8`` name their usage straight after the picture. Both lex as
        # IDENTIFIERs, which the picture scan collects: ``NATIONAL`` was
        # glued onto the pattern (``N(5)NATIONAL``, sized 3 bytes).
        # (DISPLAY / DISPLAY-1 have token types of their own and already
        # stopped the scan.)
        *_BARE_USAGE_WORDS,
        # Report-group clause words (REPORT SECTION, 2026-09-02): ``PIC ZZ9
        # SOURCE WS-X`` must stop the picture scan at SOURCE. None of these
        # is a valid picture string, so they are safe terminators everywhere.
        "SOURCE",
        "SUM",
        "COLUMN",
        "COL",
        "LINE",
        "NEXT",
        "GROUP",
        "TYPE",
        "PRESENT",
    }
)
# Clause words that begin a REPORT SECTION report-group clause (only
# honoured when ``parse_data_item`` runs with ``report_group=True``).
_REPORT_CLAUSE_STARTS: frozenset[str] = frozenset(
    {"TYPE", "LINE", "NEXT", "COLUMN", "COL", "SOURCE", "SUM", "GROUP", "PRESENT"}
)
# A report-group entry is anonymous (``01 TYPE IS PAGE HEADING.``, ``05 LINE
# NUMBER IS 1.``, ``10 COLUMN 1 PIC X``) when its level is followed directly
# by any clause word rather than a data-name.
_REPORT_ANONYMOUS_STARTS: frozenset[str] = _REPORT_CLAUSE_STARTS | frozenset(
    {"PIC", "PICTURE", "VALUE", "USAGE", "JUST", "JUSTIFIED", "BLANK", "SIGN"}
)
# Words at which a free-text report clause operand list (TYPE ..., SUM ...,
# PRESENT WHEN ...) ends.
_REPORT_OPERAND_STOPS: frozenset[str] = _PICTURE_TERMINATOR_KEYWORDS | frozenset(
    {"PIC", "PICTURE", "OCCURS", "REDEFINES", "UPON", "RESET"}
)
# After one of these a one-/two-digit integer (which lexes as a
# LEVEL_NUMBER) is an operand -- ``PRESENT WHEN WS-I > 1`` -- not the level
# number of a following data entry.
_REPORT_OPERATOR_WORDS: frozenset[str] = frozenset(
    {
        "=",
        ">",
        "<",
        ">=",
        "<=",
        "+",
        "-",
        "*",
        "/",
        "**",
        "AND",
        "OR",
        "NOT",
        "THAN",
        "TO",
        "EQUAL",
        "EQUALS",
        "GREATER",
        "LESS",
        "IS",
    }
)
# ``,`` / ``;`` between data-item clauses are separators, not clauses.
# Words that open the next OCCURS phrase, never a key or an index name.
_OCCURS_PHRASE_WORDS = frozenset({"ASCENDING", "DESCENDING", "INDEXED", "KEY"})
_CLAUSE_SEPARATOR_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {TokenType.COMMA, TokenType.SEMICOLON}
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

#: ``<word> SECTION`` headers of the DATA DIVISION. Matched by value (and a
#: following ``SECTION``) since REPORT / SCREEN / COMMUNICATION lex as plain
#: identifiers and ``FILE`` lexes as FILE_SECTION even in ``FILE STATUS``.
_DATA_SECTION_HEADER_WORDS: frozenset[str] = frozenset(
    {
        "FILE",
        "WORKING-STORAGE",
        "LOCAL-STORAGE",
        "LINKAGE",
        "REPORT",
        "SCREEN",
        "COMMUNICATION",
    }
)

#: File/sort/report description entries open with these level indicators.
_LEVEL_INDICATOR_WORDS: frozenset[str] = frozenset({"FD", "SD", "RD"})

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


def data_entry_ending_header(token_stream: ITokenStream, offset: int = 0) -> str | None:
    """The header text when the token *offset* ahead opens something no
    data-description entry can contain -- a DIVISION header, a DATA DIVISION
    section header (``FILE`` / ``WORKING-STORAGE`` / ``LOCAL-STORAGE`` /
    ``LINKAGE`` / ``REPORT`` / ``SCREEN`` / ``COMMUNICATION SECTION``) or an
    FD / SD / RD level indicator -- so it ends an entry whose period was
    left off (issue #559). ``None`` otherwise."""
    token = token_stream.peek(offset)
    if token is None:
        return None
    word = (token.value or "").strip().upper()
    if token.type in _DIVISION_TOKEN_TYPES:
        return word if word.endswith(" DIVISION") else f"{word} DIVISION"
    if word in _LEVEL_INDICATOR_WORDS:
        return word
    if word in _DATA_SECTION_HEADER_WORDS:
        i = offset + 1
        while True:
            nxt = token_stream.peek(i)
            if nxt is None or nxt.type not in _WHITESPACE_TOKEN_TYPES:
                break
            i += 1
        if nxt is not None and (nxt.value or "").upper() == "SECTION":
            return f"{word} SECTION"
    return None


# Number of positional arguments ``parse_data_item`` passes to the compiled
# clause helper. Keep in sync with the call site below; ``_data_fast_usable``
# checks the compiled extension against it at import time.
_DATA_FAST_ARG_COUNT = 20


def _data_fast_usable(helper: Any) -> bool:
    """True if the compiled clause helper matches this module's call site.

    ``_data_fast`` is compiled separately from this module, so the two can
    drift out of step: a stale in-place ``.so``, a cached ``build/`` tree, or
    an installed wheel built from an older revision all leave a binary whose
    signature no longer matches the call in :meth:`parse_data_item`. Because
    that call is unconditional and positional, the drift used to surface as a
    ``TypeError`` raised from the middle of every data-description entry,
    which the division loop recorded as a generic error and recovered from by
    abandoning the division — so a *build* problem degraded every program with
    a DATA DIVISION to a near-empty AST instead of naming its own cause.

    Probing costs one call: with an empty token list the helper's clause loop
    never runs, so it returns its ``pos`` argument without reading any other
    parameter (hence the ``None`` placeholders). That validates arity, which
    is the drift that actually happens — parameters get appended as the fast
    path grows. It cannot detect a same-arity extension whose parameters were
    reordered; nothing cheap can, and that has never been the failure mode.
    """
    probe_args = [[], 0] + [None] * (_DATA_FAST_ARG_COUNT - 2)
    try:
        return bool(helper(*probe_args) == 0)
    except Exception:
        return False


# Optional Cython acceleration for the picture-clause inner loop. The
# pure-Python implementation in ``parse_picture_clause`` below remains
# the authoritative behaviour; we only delegate when the extension is
# available and the token stream is the standard ``TokenStream`` (so we
# can safely poke its underlying token list and cursor). Off by default: the
# extension is looked for only under COBOLPARSER_ACCEL=1 (cobolparser._accel).
try:
    if not accelerators_enabled():
        raise ImportError("Cython accelerators not enabled")
    from cobolparser._data_fast import (  # type: ignore[import-not-found]
        parse_data_item_clauses_fast as _fast_data_item_clauses,
    )
except ImportError:
    _fast_data_item_clauses = None
    _HAS_DATA_FAST = False
else:
    _HAS_DATA_FAST = _data_fast_usable(_fast_data_item_clauses)
    if not _HAS_DATA_FAST:
        _fast_data_item_clauses = None
        # Logged, not ``warnings.warn``-ed. This runs at module import, and
        # under ``-W error`` / ``PYTHONWARNINGS=error`` / a pytest
        # ``filterwarnings = error`` a warning here would turn a stale build
        # into an ``import cobolparser`` failure -- the exact inversion of
        # this guard's purpose, and strictly worse than the bug it fixes.
        logger.warning(
            "cobolparser._data_fast does not match this version of "
            "cobolparser and has been disabled; parsing falls back to the "
            "pure-Python path (same results, slower). Rebuild the extension "
            "with `COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace`, "
            "or reinstall cobolparser, to restore it, or unset "
            "COBOLPARSER_ACCEL to silence this."
        )


def literal_source(token: Token) -> str:
    """A STRING_LITERAL token rendered back as COBOL source text.

    A typed literal (``X"4142"``, ``Z"..."``, ``N"..."``) keeps its prefixed
    source text from ``raw_value``, as the MOVE/DISPLAY parsers already do:
    re-quoting only the decoded content silently turned the two-byte hex
    literal ``X"4142"`` into the four-character text literal ``"4142"``.
    """
    return token.raw_value if token.raw_value else quote_literal(token.value)


def _follows_gap(prev: Token, token: Token) -> bool:
    """True when *token* sits on *prev*'s line but not immediately after it.

    Columns come from the lexer, which keeps them contiguous across a merged
    continuation line, so the only way to a gap on one line is whitespace in
    the source.
    """
    if token.location.line != prev.location.line:
        return False
    return token.location.column > prev.location.column + len(
        prev.raw_value or prev.value
    )


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
        # Non-``$`` currency symbols (``CURRENCY SIGN IS '£'``) the most
        # recent parse_picture_clause() collected; read by
        # _picture_clause() right after, on both the pure-Python and the
        # Cython data-item paths.
        self._picture_currency_symbols: frozenset[str] = frozenset()

    def _picture_clause(self, pattern: str, location: SourceLocation) -> PictureClause:
        """Build the PictureClause for the pattern parse_picture_clause()
        just returned, with the declared currency symbols it contains."""
        host = getattr(self._parser, "host", None)
        signs = getattr(host, "currency_signs", None) or {}
        return PictureClause(
            pattern,
            location,
            currency_symbols=self._picture_currency_symbols,
            decimal_point_is_comma=bool(getattr(host, "decimal_point_is_comma", False)),
            currency_signs={
                symbol: signs[symbol]
                for symbol in self._picture_currency_symbols
                if symbol in signs
            },
        )

    def parse_data_item(
        self, token_stream: ITokenStream, report_group: bool = False
    ) -> CobolDataItem | None:
        """Parse a single data item definition.

        Format: level-number data-name [clauses].

        Args:
            token_stream: Token stream positioned at level number
            report_group: True inside a REPORT SECTION -- the entry may be
                anonymous (``01 TYPE IS DETAIL.``) and the report-group
                clauses (TYPE, LINE, NEXT GROUP, COLUMN, SOURCE, SUM, GROUP
                INDICATE, PRESENT WHEN) are parsed into
                ``metadata["report_clauses"]`` instead of being dropped.

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

        # Get data name. It may sit on the line after its level number
        # (NIST NC205A writes ``02\n    SPACING-2.``); without crossing the
        # break the item became anonymous and the name was dropped as an
        # unparsed clause token. A NEWLINE is only crossed when the next
        # meaningful token can actually be a name -- an IDENTIFIER or
        # FILLER -- so a bare level number at end of line followed by the
        # *next* item's level number is left exactly as before.
        name = None
        token = token_stream.peek()
        if token and token.type == TokenType.NEWLINE:
            following = self._peek_next_meaningful(token_stream, 0)
            if following and (
                following.type == TokenType.IDENTIFIER
                or (following.value and following.value.upper() == "FILLER")
            ):
                self._skip_newlines(token_stream)
                token = token_stream.peek()

        implicit_filler = False
        if (
            report_group
            and token
            and token.value
            and token.value.upper() in _REPORT_ANONYMOUS_STARTS
        ):
            # ``01 TYPE IS PAGE HEADING.`` -- the clause word is not a name.
            name = f"ANONYMOUS-{level}-{location.line}"
        elif token and token.type == TokenType.IDENTIFIER:
            name = token.value
            token_stream.consume()
        elif token and token.value and token.value.upper() == "FILLER":
            name = "FILLER"
            token_stream.consume()
        else:
            # Anonymous data item; ``location`` is always a SourceLocation.
            name = f"ANONYMOUS-{level}-{location.line}"
            # Outside a report group, an entry with no data-name is FILLER
            # with the word omitted (``05 PIC X(3).``): set below.
            implicit_filler = not report_group

        # Create data item
        data_item = CobolDataItem(name, level, location)
        if implicit_filler:
            data_item.is_filler = True

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
                    self._picture_clause,
                    OccursClause,
                    TokenType.PERIOD,
                    TokenType.LEVEL_NUMBER,
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.NEWLINE,
                    TokenType.COMMA,
                    TokenType.SEMICOLON,
                )
                token_stream._pos = new_pos  # type: ignore[attr-defined]
                # Fall through (no early return): the Python loop below
                # finishes any clauses the fast helper handed back.
                #
                # The argument list above is positional and must stay
                # _DATA_FAST_ARG_COUNT long; the import-time probe checks the
                # compiled extension against that count.

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

            # ``,`` / ``;`` between clauses are separators (NIST NC245A:
            # ``77 TEMP; PIC S999999.``, ``PIC X, VALUE 'A'``), not clauses.
            if tok_type in _CLAUSE_SEPARATOR_TOKEN_TYPES:
                token_stream.consume()
                continue

            # A DIVISION or DATA DIVISION section header ends this data item
            # (don't consume it): its period was left off, and IBM assumes
            # one. Issue #559: the loop used to stop at DIVISION tokens only,
            # so ``01 A PIC X`` + ``LINKAGE SECTION.`` ate the header and
            # every LINKAGE item landed in the previous section.
            header = data_entry_ending_header(token_stream)
            if header:
                self._warn_item_missing_period(token, header, data_item)
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
                        self._picture_clause(picture_pattern, location)
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
                if self._at_object_reference(token_stream):
                    self._parse_object_reference(token_stream, data_item)
                else:
                    usage = self.parse_usage_clause(token_stream)
                    if usage:
                        data_item.set_usage(usage)

            # OBJECT REFERENCE [class-name] without the USAGE keyword
            elif value_upper == "OBJECT" and self._at_object_reference(token_stream):
                self._parse_object_reference(token_stream, data_item)

            # VOLATILE (Enterprise COBOL 6.2)
            elif value_upper == "VOLATILE":
                data_item.is_volatile = True
                token_stream.consume()

            # BASED (Micro Focus / GnuCOBOL): storage comes from ALLOCATE.
            elif value_upper == "BASED":
                data_item.metadata["based"] = True
                token_stream.consume()

            # PIC U BYTE-LENGTH n (UTF-8, Enterprise COBOL 6.3)
            elif value_upper == "BYTE-LENGTH":
                token_stream.consume()  # BYTE-LENGTH
                self._skip_clause_separators(token_stream)
                if self._consume_if(token_stream, "IS") is not None:
                    self._skip_clause_separators(token_stream)
                length = self._consume_integer(token_stream)
                if length is None:
                    self._warn_dropped_data_token(token, data_item)
                else:
                    data_item.set_byte_length(length)

            # DYNAMIC LENGTH [LIMIT [IS] n] (Enterprise COBOL 6.3)
            elif value_upper == "DYNAMIC":
                token_stream.consume()  # DYNAMIC
                self._skip_clause_separators(token_stream)
                self._consume_if(token_stream, "LENGTH")
                self._skip_clause_separators(token_stream)
                limit: int | None = None
                if self._consume_if(token_stream, "LIMIT") is not None:
                    self._skip_clause_separators(token_stream)
                    if self._consume_if(token_stream, "IS") is not None:
                        self._skip_clause_separators(token_stream)
                    limit = self._consume_integer(token_stream)
                data_item.set_dynamic_length(limit)

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

            # ``BINARY-LONG [SIGNED|UNSIGNED]`` written without the USAGE
            # keyword: the sign does not change the width (#524). The fast
            # clause loop hands this word back here, so one branch serves both.
            elif value_upper in ("SIGNED", "UNSIGNED") and (
                data_item.usage or ""
            ).upper().startswith("BINARY-"):
                token_stream.consume()

            # DISPLAY without the USAGE keyword (``05 X PIC X(3) DISPLAY.``).
            # DISPLAY lexes as the verb token, which no branch accepted, so
            # the clause was dropped with an "Unparsed token" warning (32
            # times across the NIST corpus). A data item can never be
            # *named* DISPLAY, so in clause position it is the usage.
            elif tok_type == TokenType.DISPLAY or value_upper == "DISPLAY":
                data_item.set_usage("DISPLAY")
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

            # GROUP-USAGE [IS] NATIONAL | UTF-8 (a national / UTF-8 group:
            # every subordinate elementary item takes that usage -- applied
            # by ``propagate_group_usage_and_sign`` once the hierarchy is
            # built). It used to be dropped with two "Unparsed token"
            # warnings, leaving ``PIC 9`` children sized as DISPLAY.
            elif value_upper == "GROUP-USAGE":
                token_stream.consume()  # GROUP-USAGE
                self._consume_if(token_stream, "IS")
                group_usage = self._consume_if(token_stream, "NATIONAL", "UTF-8")
                if group_usage is None:
                    self._warn_dropped_data_token(token, data_item)
                else:
                    data_item.group_usage = group_usage

            # NATIONAL / DISPLAY-1 / UTF-8 without the USAGE keyword
            # (``05 X PIC N(5) NATIONAL.``, ``05 X PIC G(4) DISPLAY-1.``).
            # None can name a data item, so in clause position each is the
            # usage; before, NATIONAL was glued onto the PICTURE and
            # DISPLAY-1 dropped with an "Unparsed token" warning.
            elif value_upper in _BARE_USAGE_WORDS or tok_type == TokenType.DISPLAY_1:
                data_item.set_usage(value_upper)
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
                self._parse_sign_direction(token_stream, data_item)

            # The same clause with the SIGN word omitted -- ``[SIGN IS]
            # LEADING|TRAILING [SEPARATE [CHARACTER]]`` is the standard's
            # grammar, and NIST NC117A/NC118A write ``PIC S999 LEADING
            # SEPARATE`` and ``01 MULTIPLY-DATA LEADING SEPARATE.``
            # (a group-level sign clause). Neither word can name a data
            # item, so in clause position they are unambiguous.
            elif value_upper in ("LEADING", "TRAILING"):
                self._parse_sign_direction(token_stream, data_item)

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
                if (
                    nxt_upper in _POINTER_KEYWORDS
                    or nxt_upper in _BARE_USAGE_WORDS
                    or nxt_upper in ("EXTERNAL", "GLOBAL", "INDEX")
                ):
                    token_stream.consume()  # Consume the optional IS
                else:
                    self._warn_dropped_data_token(token, data_item)
                    token_stream.consume()

            # REPORT SECTION report-group clauses (TYPE, LINE, NEXT GROUP,
            # COLUMN, SOURCE, SUM, GROUP INDICATE, PRESENT WHEN)
            elif report_group and value_upper in _REPORT_CLAUSE_STARTS:
                self._parse_report_clause(token_stream, data_item, value_upper)

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

    def _parse_sign_direction(
        self, token_stream: ITokenStream, data_item: CobolDataItem
    ) -> None:
        """Parse ``LEADING|TRAILING [SEPARATE [CHARACTER]]`` into
        ``data_item.sign_clause`` (each word may start a continuation line;
        the read is restricted to LEADING/TRAILING so a raw newline is never
        recorded as the direction). Shared by the ``SIGN [IS] ...`` branch and
        the bare form with the SIGN word omitted."""
        self._skip_newlines(token_stream)
        dir_tok = token_stream.peek()
        if not (
            dir_tok
            and dir_tok.value
            and dir_tok.value.upper() in ("LEADING", "TRAILING")
        ):
            return
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

    # ------------------------------------------------------------------
    # REPORT SECTION report-group clauses
    # ------------------------------------------------------------------

    def _report_clauses(self, data_item: CobolDataItem) -> dict[str, Any]:
        clauses = data_item.get_metadata("report_clauses")
        if clauses is None:
            clauses = {}
            data_item.set_metadata("report_clauses", clauses)
        return clauses  # type: ignore[no-any-return]

    def _consume_integer(self, token_stream: ITokenStream) -> int | None:
        """Consume an unsigned integer operand (``BYTE-LENGTH 120``,
        ``LIMIT 4000``) whatever the lexer called it -- a two-digit count
        lexes as a LEVEL_NUMBER token -- returning None, consuming nothing,
        when the next token is not one."""
        token = token_stream.peek()
        if token is None or not token.value or not str(token.value).isdigit():
            return None
        token_stream.consume()
        return int(token.value)

    @staticmethod
    def _at_object_reference(token_stream: ITokenStream) -> bool:
        """True at ``OBJECT REFERENCE`` (the stream is at ``OBJECT`` or, after
        a consumed USAGE keyword, at ``[IS] OBJECT``)."""
        # Each word may start the next line (``OBJECT <newline> REFERENCE``);
        # a fixed-offset peek saw the NEWLINE and recorded plain OBJECT.
        first, at = peek_past_noise(token_stream, 0)
        if first is not None and first.type == TokenType.IS:
            first, at = peek_past_noise(token_stream, at + 1)
        if first is None or (first.value or "").upper() != "OBJECT":
            return False
        second, _ = peek_past_noise(token_stream, at + 1)
        return bool(second is not None and (second.value or "").upper() == "REFERENCE")

    def _parse_object_reference(
        self, token_stream: ITokenStream, data_item: CobolDataItem
    ) -> None:
        """Consume ``[IS] OBJECT REFERENCE [[FACTORY OF] class-name |
        ACTIVE-CLASS]`` and record it on *data_item* (IBM OO COBOL)."""
        if self._consume_if(token_stream, "IS") is not None:
            pass
        self._skip_newlines(token_stream)
        token_stream.consume()  # OBJECT
        self._skip_newlines(token_stream)
        token_stream.consume()  # REFERENCE
        self._skip_clause_separators(token_stream)
        class_name: str | None = None
        nxt = token_stream.peek()
        nxt_upper = (nxt.value or "").upper() if nxt is not None else ""
        if nxt is not None and nxt_upper == "FACTORY":
            token_stream.consume()
            self._skip_clause_separators(token_stream)
            self._consume_if(token_stream, "OF")
            self._skip_clause_separators(token_stream)
            nxt = token_stream.peek()
            nxt_upper = (nxt.value or "").upper() if nxt is not None else ""
        if (
            nxt is not None
            and nxt.type == TokenType.IDENTIFIER
            and nxt_upper not in _PICTURE_TERMINATOR_KEYWORDS
            and nxt_upper not in ("PIC", "PICTURE")
        ):
            class_name = nxt.value
            token_stream.consume()
        data_item.set_object_reference(class_name)

    def _consume_if(self, token_stream: ITokenStream, *words: str) -> str | None:
        """Consume the next meaningful token when its upper-cased value is
        one of *words*; return that value, else None (nothing consumed)."""
        self._skip_newlines(token_stream)
        token = token_stream.peek()
        if token and token.value and token.value.upper() in words:
            token_stream.consume()
            return token.value.upper()
        return None

    def _report_position(self, token_stream: ITokenStream) -> str | None:
        """``[PLUS] integer`` or ``NEXT PAGE`` -- the operand shape shared by
        LINE, NEXT GROUP and COLUMN. Returned as text ("1", "PLUS 2",
        "NEXT PAGE"); None when nothing operand-shaped follows."""
        self._skip_newlines(token_stream)
        token = token_stream.peek()
        if token and (token.value or "").upper() == "NEXT":
            # ``NEXT PAGE`` is a position; ``NEXT GROUP`` starts its own
            # clause and must be left for the clause loop.
            following = self._peek_next_meaningful(token_stream)
            if not (following and (following.value or "").upper() == "PAGE"):
                return None
            token_stream.consume()  # NEXT
            token_stream.consume()  # PAGE
            return "NEXT PAGE"
        plus = self._consume_if(token_stream, "PLUS")
        self._skip_newlines(token_stream)
        token = token_stream.peek()
        if token and token.type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL):
            token_stream.consume()
            if plus:
                return f"PLUS {token.value}"
            # ``LINE [NUMBER IS] integer ON NEXT PAGE`` (COBOL-85): an
            # absolute line on a fresh page. Before 2026-09-28 the ``ON``
            # was warned about and dropped, and ``NEXT PAGE`` was misread
            # as a ``NEXT GROUP`` clause with no operand.
            if self._at_on_next_page(token_stream):
                for _ in range(3):  # ON NEXT PAGE
                    self._skip_newlines(token_stream)
                    token_stream.consume()
                return f"{token.value} ON NEXT PAGE"
            return str(token.value)
        return "PLUS" if plus else None

    def _at_on_next_page(self, token_stream: ITokenStream) -> bool:
        """True when the next three meaningful tokens are ``ON NEXT PAGE``
        (nothing consumed)."""
        words: list[str] = []
        offset = 0
        while len(words) < 3:
            token = token_stream.peek(offset)
            if token is None:
                return False
            offset += 1
            if token.type == TokenType.NEWLINE:
                continue
            words.append((token.value or "").upper())
        return words == ["ON", "NEXT", "PAGE"]

    def _report_operands(self, token_stream: ITokenStream) -> list[str]:
        """Free-text operands up to the next clause word, period, level
        number or division header (TYPE ..., SUM ..., PRESENT WHEN ...)."""
        words: list[str] = []
        depth = 0
        while not token_stream.is_empty():
            self._skip_newlines(token_stream)
            token = token_stream.peek()
            if token is None or token.type == TokenType.PERIOD:
                break
            # A one-/two-digit integer lexes as LEVEL_NUMBER whatever it
            # means. Inside a subscript (``SUM WS-AMT (1)``) or after an
            # operator (``PRESENT WHEN WS-I > 1``) it is an operand; only
            # elsewhere is it the level number of the next entry (a
            # missing period). Before 2026-09-28 every such integer ended
            # the clause, and the clause loop then opened a phantom data
            # item at it, dropping the rest of the entry.
            if (
                token.type == TokenType.LEVEL_NUMBER
                and depth == 0
                and not (words and words[-1].upper() in _REPORT_OPERATOR_WORDS)
            ):
                break
            if token.type in _DIVISION_TOKEN_TYPES:
                break
            upper = (token.value or "").upper()
            if depth == 0 and (
                upper in _REPORT_CLAUSE_STARTS or upper in _REPORT_OPERAND_STOPS
            ):
                break
            if token.type == TokenType.LEFT_PAREN:
                depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                depth = max(0, depth - 1)
            value = token.value or ""
            if token.type == TokenType.STRING_LITERAL:
                # Keep a literal distinguishable from a data name
                # (``PRESENT WHEN WS-FLAG = 'Y'``, not ``= Y``).
                value = "'" + value.replace("'", "''") + "'"
            words.append(value)
            token_stream.consume()
        return words

    @staticmethod
    def _group_report_operands(words: list[str]) -> list[str]:
        """Fold each operand's subscript and ``OF``/``IN`` qualifiers into
        one string, so ``SUM WS-AMT (1) WS-AMT (2)`` lists two operands
        (``WS-AMT ( 1 )``, ``WS-AMT ( 2 )``), not eight words."""
        grouped: list[str] = []
        depth = 0
        glue_next = False
        for word in words:
            upper = word.upper()
            if grouped and (depth > 0 or glue_next or word == "("):
                grouped[-1] = f"{grouped[-1]} {word}"
            elif grouped and upper in ("OF", "IN"):
                grouped[-1] = f"{grouped[-1]} {word}"
                glue_next = True
                continue
            else:
                grouped.append(word)
            glue_next = False
            if word == "(":
                depth += 1
            elif word == ")":
                depth = max(0, depth - 1)
        return grouped

    def _parse_report_clause(
        self, token_stream: ITokenStream, data_item: CobolDataItem, word: str
    ) -> None:
        """Parse one report-group clause starting at *word* (already peeked,
        not yet consumed) into ``metadata["report_clauses"]``."""
        clauses = self._report_clauses(data_item)
        token_stream.consume()  # the clause word
        if word == "TYPE":
            self._consume_if(token_stream, "IS")
            clauses["type"] = " ".join(self._report_operands(token_stream))
        elif word == "LINE":
            self._consume_if(token_stream, "NUMBER", "NUMBERS")
            self._consume_if(token_stream, "IS", "ARE")
            lines = clauses.setdefault("line", [])
            position = self._report_position(token_stream)
            while position is not None:
                lines.append(position)
                position = self._report_position(token_stream)
        elif word == "NEXT":
            self._consume_if(token_stream, "GROUP")
            self._consume_if(token_stream, "IS")
            clauses["next_group"] = self._report_position(token_stream)
        elif word in ("COLUMN", "COL"):
            self._consume_if(token_stream, "NUMBER", "NUMBERS")
            self._consume_if(token_stream, "IS", "ARE")
            columns = clauses.setdefault("column", [])
            position = self._report_position(token_stream)
            while position is not None:
                columns.append(position)
                position = self._report_position(token_stream)
        elif word == "SOURCE":
            self._consume_if(token_stream, "IS")
            clauses["source"] = " ".join(self._report_operands(token_stream))
        elif word == "SUM":
            operands = self._group_report_operands(self._report_operands(token_stream))
            entry: dict[str, Any] = {"operands": operands}
            if self._consume_if(token_stream, "UPON"):
                entry["upon"] = self._report_operands(token_stream)
            if self._consume_if(token_stream, "RESET"):
                self._consume_if(token_stream, "ON")
                entry["reset_on"] = " ".join(self._report_operands(token_stream))
            clauses.setdefault("sum", []).append(entry)
        elif word == "GROUP":
            self._consume_if(token_stream, "INDICATE")
            clauses["group_indicate"] = True
        elif word == "PRESENT":
            self._consume_if(token_stream, "WHEN")
            clauses["present_when"] = " ".join(self._report_operands(token_stream))

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
        max_count: int | None = 0
        # ``OCCURS UNBOUNDED DEPENDING ON counter`` (Enterprise COBOL 5+, a
        # LINKAGE SECTION table with no declared maximum): there is no
        # count to read, the minimum is 1 and the maximum stays None.
        # Peeked without consuming layout: the count read below keeps its
        # own line-crossing guard, which a consumed newline would defeat.
        first = self._peek_next_meaningful(token_stream, offset=0)
        unbounded = bool(
            first is not None and (first.value or "").upper() == "UNBOUNDED"
        )
        if unbounded:
            self._skip_clause_separators(token_stream)
            token_stream.consume()
            min_count = 1
            max_count = None
        count_token, count_offset = (
            (None, 0) if unbounded else self._peek_count_token(token_stream)
        )
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
        self._skip_clause_separators(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "TO":
            token_stream.consume()  # consume TO
            # ``OCCURS min TO UNBOUNDED`` (Enterprise COBOL 6.x): no declared
            # maximum, the same as the bare ``OCCURS UNBOUNDED`` form above.
            after_to = self._peek_next_meaningful(token_stream, offset=0)
            if after_to is not None and (after_to.value or "").upper() == "UNBOUNDED":
                self._skip_clause_separators(token_stream)
                token_stream.consume()
                unbounded = True
                max_count = None
                max_token, max_offset = None, 0
            else:
                max_token, max_offset = self._peek_count_token(token_stream)
            if max_token is not None:
                try:
                    max_count = int(max_token.value)
                except (TypeError, ValueError):
                    max_count = min_count
                for _ in range(max_offset + 1):
                    token_stream.consume()

        # Skip optional TIMES keyword (may be preceded by newlines)
        self._skip_clause_separators(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "TIMES":
            token_stream.consume()

        # DEPENDING ON clause (ON and the variable may each start a
        # continuation line; the variable read requires an IDENTIFIER, so
        # crossing the break can never swallow a level number)
        depending_var = None
        self._skip_clause_separators(token_stream)
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() == "DEPENDING":
            token_stream.consume()  # consume DEPENDING
            self._skip_clause_separators(token_stream)
            on_token = token_stream.peek()
            if on_token and on_token.value and on_token.value.upper() == "ON":
                token_stream.consume()  # consume ON
            self._skip_clause_separators(token_stream)
            dep_token = token_stream.peek()
            if dep_token and dep_token.type == TokenType.IDENTIFIER:
                depending_var = dep_token.value
                token_stream.consume()
                # ``DEPENDING ON CNT OF CTL``: the qualifiers used to stop
                # the walk, so every KEY / INDEXED BY after them was
                # dropped as an unparsed token.
                occurs.depending_on_qualifiers = self._consume_qualifiers(token_stream)

        # ASCENDING / DESCENDING KEY IS key-1 [key-2 ...] phrases (may
        # repeat) and the INDEXED BY phrase, in either order: IBM accepts
        # ``INDEXED BY IX ASCENDING KEY K`` as well as the standard order
        # (#542). The KEY phrases are what makes a table valid for SEARCH
        # ALL (binary search), so dropping them loses real semantics.
        while True:
            self._skip_clause_separators(token_stream)
            nxt = token_stream.peek()
            word = nxt.value.upper() if nxt and nxt.value else ""
            if word in ("ASCENDING", "DESCENDING"):
                self._parse_occurs_key_phrase(token_stream, occurs, word)
            elif word == "INDEXED":
                self._parse_occurs_indexed_by(token_stream, occurs)
            else:
                break

        if unbounded:
            occurs.is_unbounded = True
            occurs.set_variable_occurs(min_count, None, depending_var)
            data_item.set_occurs_clause(occurs)
            return

        if depending_var:
            occurs.set_variable_occurs(min_count, max_count, depending_var)
        else:
            occurs.set_fixed_occurs(max_count or 0)

        if occurs.max_times is not None:
            data_item.set_occurs_clause(occurs)

    def _parse_occurs_key_phrase(
        self, token_stream: Any, occurs: Any, direction: str
    ) -> None:
        """``ASCENDING|DESCENDING [KEY] [IS] key-1 [key-2 ...]``."""
        token_stream.consume()  # consume ASCENDING/DESCENDING
        self._skip_clause_separators(token_stream)
        key_kw = token_stream.peek()
        if key_kw and key_kw.value and key_kw.value.upper() == "KEY":
            token_stream.consume()  # consume KEY
        self._skip_clause_separators(token_stream)
        is_kw = token_stream.peek()
        if is_kw and is_kw.value and is_kw.value.upper() == "IS":
            token_stream.consume()  # consume optional IS
        keys: list[str] = []
        while True:
            self._skip_clause_separators(token_stream)
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
                and key_token.value.upper() not in _OCCURS_PHRASE_WORDS
            ):
                keys.append(key_token.value)
                token_stream.consume()
                # A key may be qualified (``KEY IS K1 OF ENTRY``); the
                # key is the bare name, the qualifier only locates it.
                self._consume_qualifiers(token_stream)
            else:
                break
        if keys:
            occurs.add_key_clause(direction, keys)

    def _parse_occurs_indexed_by(self, token_stream: Any, occurs: Any) -> None:
        """``INDEXED [BY] index-1 [index-2 ...]`` (optionally comma-separated;
        INDEXED and BY may straddle a line break). Stops at a following
        ASCENDING / DESCENDING / KEY, which open a KEY phrase (#542)."""
        token_stream.consume()  # consume INDEXED
        self._skip_clause_separators(token_stream)
        by_token = token_stream.peek()
        if by_token and by_token.value and by_token.value.upper() == "BY":
            token_stream.consume()  # consume BY
        while True:
            self._skip_clause_separators(token_stream)
            idx_token = token_stream.peek()
            if idx_token and idx_token.type == TokenType.COMMA:
                token_stream.consume()
                continue
            if (
                idx_token
                and idx_token.type == TokenType.IDENTIFIER
                and (idx_token.value or "").upper() not in _OCCURS_PHRASE_WORDS
            ):
                occurs.add_index_name(idx_token.value)
                token_stream.consume()
            else:
                break

    def _warn_item_missing_period(
        self, token: Any, header: str, data_item: Any
    ) -> None:
        """Record that a data item was closed by *header* instead of its
        terminating period (IBM: "a period was assumed before ...")."""
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        item_name = getattr(data_item, "name", None) or "?"
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(
                f"Data item '{item_name}' missing its terminating period: a "
                f"period was assumed before '{header}'{where}"
            )

    def _warn_unknown_usage(self, token: Any, usage: str) -> None:
        """Record that *usage* is not a USAGE this parser can size."""
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        host = getattr(self._parser, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(
                f"Unsupported USAGE '{usage}'{where}: its storage size is "
                "unknown, so record offsets from this item on are unreliable"
            )

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
    def _skip_clause_separators(token_stream: ITokenStream) -> None:
        """Consume NEWLINE, ``,`` and ``;`` tokens at the current position.

        Inside an OCCURS clause the sub-clauses may be comma/semicolon
        separated (NIST NC245A: ``OCCURS 15 TIMES;\n INDEXED BY IN1,
        INDEX1,``); a separator is layout, never an operand.
        """
        while not token_stream.is_empty():
            t = token_stream.peek()
            if t and (
                t.type == TokenType.NEWLINE or t.type in _CLAUSE_SEPARATOR_TOKEN_TYPES
            ):
                token_stream.consume()
            else:
                break

    def _consume_qualifiers(self, token_stream: ITokenStream) -> list[str]:
        """Consume an ``OF|IN data-name`` qualifier chain; return the names.

        ``OCCURS ... DEPENDING ON CNT OF CTL`` is how a counter whose name
        is not unique is written.  ``OF``/``IN`` is only taken when a name
        follows it, so a malformed clause cannot swallow anything else.
        """
        qualifiers: list[str] = []
        while True:
            keyword = self._peek_next_meaningful(token_stream, offset=0)
            if not (
                keyword and keyword.value and keyword.value.upper() in ("OF", "IN")
            ):
                break
            self._skip_newlines(token_stream)
            name = self._peek_next_meaningful(token_stream, offset=1)
            if name is None or name.type != TokenType.IDENTIFIER:
                break
            token_stream.consume()  # OF / IN
            self._skip_newlines(token_stream)
            qualifiers.append(name.value)
            token_stream.consume()
        return qualifiers

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
        currency_symbols: set[str] = set()
        # The last token collected into the pattern on the current line.
        # A PICTURE character-string has no embedded spaces, so a word that
        # sits on the same line as the pattern but *after a gap* is the
        # next clause (or a stray word), never more picture: ``PIC X(3)
        # VALUES ARE 'ABC'`` used to glue ``VALUES`` on (``X(3)VALUES``,
        # sized 0) and ``PIC X(3) FOO`` read as ``X(3)FOO``. The keyword
        # list above still ends the scan early for known clause words; the
        # gap rule is what catches the ones it does not list. Reset at a
        # line break so a pattern continued on the next line (which the
        # NEWLINE branch below tolerates) is unaffected.
        prev_token: Token | None = None

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            # Stop at specific keywords when outside parentheses
            if paren_depth == 0:
                if (
                    token.type in _PICTURE_PATTERN_TOKEN_TYPES
                    and prev_token is not None
                    and _follows_gap(prev_token, token)
                ):
                    break
                if token.type == TokenType.PERIOD:
                    # An interior '.' is an editing decimal point and stays in
                    # the pattern; the terminating period ends the clause.
                    if self._period_is_picture_decimal(token, token_stream.peek(1)):
                        pattern_parts.append(".")
                        token_stream.consume()
                        prev_token = token
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
                # All these token types can be part of a picture pattern.
                # A numeric literal's value is canonical (``9,9`` under
                # DECIMAL-POINT IS COMMA reads ``9.9``); the picture wants
                # the characters as written.
                token_value = (
                    token.raw_value
                    if token.type == TokenType.NUMERIC_LITERAL and token.raw_value
                    else token.value
                )
                if paren_depth == 0 and token_value.endswith("."):
                    pattern_parts.append(token_value[:-1])
                    token_stream.consume()
                    break
                pattern_parts.append(token_value)
                token_stream.consume()
            # Editing symbols emitted as their own token types ($ + - * /)
            elif token.type in _PICTURE_SYMBOL_TOKEN_TYPES:
                pattern_parts.append(token.value)
                if token.type == TokenType.CURRENCY and token.value != "$":
                    # A SPECIAL-NAMES CURRENCY SIGN symbol (the lexer only
                    # emits a non-``$`` CURRENCY token for a declared one).
                    currency_symbols.add(token.value)
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
                # An editing comma (``ZZ,ZZ9``) is always followed by more
                # pattern; a comma followed by a clause word, the period or
                # a line break is the NIST-style clause separator (``PIC X,
                # VALUE 'A'``) and must not be glued onto the pattern.
                if paren_depth == 0 and self._comma_ends_picture(token_stream):
                    token_stream.consume()
                    break
                pattern_parts.append(token.value)
                token_stream.consume()
            elif token.type == TokenType.SEMICOLON and paren_depth == 0:
                # ``PIC S999999; OCCURS 10 TIMES`` (NIST NC245A)
                token_stream.consume()
                break
            elif token.type == TokenType.NEWLINE:
                if paren_depth == 0:
                    next_item_token = self._picture_clause_next_item_token(token_stream)
                    if next_item_token is not None:
                        self._warn_picture_clause_missing_terminator(next_item_token)
                        break
                token_stream.consume()
                prev_token = None
                continue
            else:
                break
            prev_token = token

        self._picture_currency_symbols = frozenset(currency_symbols)
        result = "".join(pattern_parts) if pattern_parts else None
        return result

    @staticmethod
    def _comma_ends_picture(token_stream: ITokenStream) -> bool:
        """True when the ``,`` at the current position is a clause separator
        rather than an editing symbol: nothing pattern-shaped follows it."""
        nxt = token_stream.peek(1)
        if nxt is None:
            return True
        if nxt.type in (TokenType.PERIOD, TokenType.NEWLINE, TokenType.EOF):
            return True
        if nxt.type in _COMP_TOKEN_TYPES:
            return True
        value = (nxt.value or "").upper()
        return value in _PICTURE_TERMINATOR_KEYWORDS or value in ("PIC", "PICTURE")

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
                return f"ALL {literal_source(literal)}"
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
                literal_source(token)
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
            if usage in FIXED_SIZE_USAGES and usage.startswith("BINARY-"):
                # ``BINARY-LONG [SIGNED|UNSIGNED]``: the sign does not
                # change the width.
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt is not None and (nxt.value or "").upper() in (
                    "SIGNED",
                    "UNSIGNED",
                ):
                    token_stream.consume()
            elif not is_known_usage(usage):
                # A word nothing here can size (``USAGE IS COMPX``, a vendor
                # extension): say so instead of storing it silently (#524).
                self._warn_unknown_usage(token, usage)
            return usage

        # Check for COMP variations that are tokenized differently
        if token.value and token.value.upper() in _COMP_KEYWORDS:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        return None
