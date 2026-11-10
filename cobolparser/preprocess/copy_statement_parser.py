"""
COPY statement parser for COBOL copybook expansion.

This module handles parsing of COBOL COPY statements from source code,
supporting various syntax variants including library qualifiers,
REPLACING clauses with LEADING/TRAILING modifiers, and SUPPRESS options.

Properly handles:
- Comment lines (asterisk in column 7 of fixed-format COBOL)
- COPY keywords within string literals
- Continuation lines (hyphen in column 7)
- Sequence/identification area (columns 73-80) in fixed-format COBOL
"""

import bisect
import re

from .._lines import split_source_lines
from .._source_directive import free_format_flags
from .._source_text.normalize import ALL_COMMENT_INDICATORS, DEBUG_INDICATORS
from ..lexer import mask_comment_entries
from .models import CopyStatement, ReplacingClause, SuppressClause


def _records(text: str) -> list[str]:
    """``text.split("\\n")`` on every record boundary.

    A source read from a bare-CR (``\\r``) or CRLF file is one record per
    ``\\r`` / ``\\r\\n`` too (:mod:`cobolparser._lines`); splitting on
    ``\\n`` alone made a bare-CR program one 72-column "record" whose COPY
    was silently never expanded. Like ``str.split`` (and unlike
    ``split_source_lines``) a terminating line break yields a trailing empty
    element, so the callers' ``"\\n".join`` round-trips the text they had.
    """
    parts = split_source_lines(text)
    if text.endswith(("\n", "\r")):
        parts.append("")
    return parts


# Fixed-format COBOL column boundaries
# Columns 1-6: Sequence number area
# Column 7: Indicator area
# Columns 8-72: Program text area (Area A + Area B)
# Columns 73-80: Identification/sequence area (ignored for parsing)
FIXED_FORMAT_CODE_END_COLUMN = 72

# Regex to identify comment lines in fixed-format COBOL
# Column 7 (index 6) contains '*' for full-line comments or '/' for page break comments
COMMENT_LINE_PATTERN = re.compile(r"^.{6}[*\/]", re.MULTILINE)

# Matches a single end-of-line terminator: \r\n (Windows), bare \r
# (classic Mac / mainframe-transferred), or \n (Unix). Stored position is the
# last char of the EOL so col_num arithmetic stays correct across conventions.
_EOL_RE = re.compile(r"\r\n|\r|\n")

# A PROCESS/CBL compiler-directing statement must start in column 1 per the
# COBOL standard -- even inside an otherwise strictly fixed-format program
# that carries real sequence numbers on every other line -- so its own
# columns 1-6 are never a sequence area. See strip_sequence_area's use below.
_COMPILER_DIRECTIVE_RE = re.compile(r"^(?:PROCESS|CBL)(?:[ \t].*)?$", re.IGNORECASE)

# NOTE (audit 2026-08-12, S-1): the module previously exported a monolithic
# COPY_PATTERN regex here. It was unused by the live expansion path (the real
# scanner is CopyStatementLexer.tokenize_copy_statements, a linear
# hand-written lexer) and its ambiguous REPLACING sub-pattern exhibited
# exponential backtracking on unterminated input such as
# "COPY X REPLACING BY BY BY ... BY %". It has been removed rather than
# de-ambiguated; use CopyStatementLexer instead.


# Columns 8-72: the width of the program-text area a continued literal runs
# to the end of.
_PROGRAM_TEXT_WIDTH = 65


def normalize_continuation_lines(
    source: str,
    indicator_position: int = 6,
    line_origins: list[int] | None = None,
) -> str:
    """
    Normalize COBOL fixed-format continuation lines for COPY statement detection.

    In fixed-format COBOL:
    - Columns 1-6: Sequence number area
    - Column 7: Indicator area ('-' for continuation)
    - Columns 8-72: Program text area

    This function merges continuation lines to enable proper COPY statement parsing.
    Handles string literal continuation where:
    - The continued line ends mid-literal (no closing quote)
    - The continuation line starts with a quote to continue the literal

    Args:
        source: COBOL source code (may contain continuation lines)
        indicator_position: Position of the indicator column (default 6 for original,
                           0 for source that has had columns 1-6 stripped)
        line_origins: Optional out-parameter. When given, receives one entry per
                     *output* line: the 1-based number of the input line that
                     started it. Merging a continuation record appends nothing,
                     so ``len(line_origins)`` equals the output line count and
                     a caller can map a merged line back to where it began.
                     This is what lets ``expand_copybooks`` build a real
                     expanded-line -> (file, original line) map across a step
                     that changes the line count.

    Returns:
        Source with continuation lines merged

    Example:
        >>> source = "       COPY EMPLOYEE REPLACING\\n      -    ==OLD== BY ==NEW==."
        >>> normalize_continuation_lines(source)
        "       COPY EMPLOYEE REPLACING ==OLD== BY ==NEW==."
    """
    # Tabs are expanded before any column-sensitive slicing, exactly as
    # normalize_fixed_format does, so the indicator column is found where
    # the final parse will look for it.
    lines = _records(source.expandtabs(8))
    result: list[str] = []

    # Text starts after the indicator column
    text_start = indicator_position + 1
    # Where column 72 ends in this coordinate system: a continued literal
    # runs through it, blanks and all.
    text_end = text_start + _PROGRAM_TEXT_WIDTH
    # Physical width (sans "\r") of the last record merged into each output
    # line, so a continued literal is padded for *that* record's missing
    # columns, not the merged line's.
    tail_width: dict[int, int] = {}

    for _i, line in enumerate(lines):
        line_number = _i + 1
        # Check if this is a continuation line (indicator is '-')
        if len(line) > indicator_position and line[indicator_position] == "-":
            # This is a continuation line. It continues the nearest earlier
            # line that is not blank: comment lines reach this function
            # already blanked (remove_comment_lines), and IBM fixed format
            # lets comment and blank lines sit between a continued line and
            # its continuation -- joining onto the blank line instead would
            # sever a continued literal.
            target = len(result) - 1
            while target >= 0 and not result[target].strip():
                target -= 1
            if target >= 0:
                # Get the continuation text (after the indicator)
                continuation_text = line[text_start:] if len(line) > text_start else ""

                # Get the previous line (the one we're continuing). A CRLF
                # source keeps its "\r" here (lines were split on "\n"); it
                # is a line terminator, never part of the continued text.
                prev_line = result[target]
                if prev_line.endswith("\r"):
                    prev_line = prev_line[:-1]

                # Same open-quote state machine as normalize_fixed_format:
                # doubled quotes are escapes, the quote that opened the
                # literal is the only one that closes it, and a `*>` outside
                # a literal comments out the rest of the line. Counting
                # quotes (the previous rule) miscounted an apostrophe
                # literal holding a double quote, and vice versa.
                open_quote = _open_literal_quote(prev_line)

                if open_quote is not None:
                    # We're continuing a string literal. The continuation
                    # line's leading quote only marks the resumption and is
                    # dropped; the continued line keeps its trailing blanks
                    # up to column 72, which are part of the literal's value
                    # (the M5 rule) -- never rstrip an open literal.
                    #
                    # A record shorter than column 72 (its trailing blanks
                    # stripped by an editor or transfer) is padded back out:
                    # the columns it lost are blanks inside the literal all
                    # the same, and normalize_fixed_format pads them too.
                    cont_stripped = continuation_text.lstrip()
                    if cont_stripped.startswith(open_quote):
                        cont_stripped = cont_stripped[1:]
                    pad = " " * max(0, text_end - tail_width.get(target, text_end))
                    result[target] = prev_line + pad + cont_stripped
                else:
                    # Non-literal continuation: strip leading spaces
                    # In COBOL, when continuing a non-literal (like an identifier),
                    # the continuation text is concatenated directly to the previous text.
                    # Example: "O005" continued with "F-001" becomes "O005F-001"
                    result[target] = prev_line.rstrip() + continuation_text.lstrip()
                tail_width[target] = len(line.rstrip("\r"))
            else:
                # Orphan continuation line - just add the text part
                result.append(line[text_start:] if len(line) > text_start else "")
                if line_origins is not None:
                    line_origins.append(line_number)
        else:
            tail_width[len(result)] = len(line.rstrip("\r"))
            result.append(line)
            if line_origins is not None:
                line_origins.append(line_number)

    return "\n".join(result)


def _open_literal_quote(text: str) -> str | None:
    """Return the quote character of a literal still open at the end of *text*.

    Mirrors ``normalize_fixed_format``'s quote tracking: a doubled quote
    inside a literal is an escape, only the opening quote character closes
    the literal, and outside a literal a ``*>`` inline comment runs to end of
    line (a quote after it is comment text). ``None`` when no literal is
    open.
    """
    open_quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if open_quote is not None:
            if ch == open_quote:
                if i + 1 < n and text[i + 1] == open_quote:
                    i += 2
                    continue
                open_quote = None
            i += 1
        elif ch in ('"', "'"):
            open_quote = ch
            i += 1
        elif ch == "*" and i + 1 < n and text[i + 1] == ">":
            break
        else:
            i += 1
    return open_quote


def _count_unmatched_quotes(text: str, quote_char: str) -> int:
    """
    Count the number of unescaped quote characters in text.

    In COBOL, quotes are escaped by doubling them ("" or '').

    Args:
        text: Text to analyze
        quote_char: The quote character (" or ')

    Returns:
        Count of unescaped quote characters
    """
    count = 0
    i = 0
    while i < len(text):
        if text[i] == quote_char:
            # Check if this is an escaped quote (doubled)
            if i + 1 < len(text) and text[i + 1] == quote_char:
                # Skip the escaped pair
                i += 2
                continue
            count += 1
        i += 1
    return count


_RESERVED_WORDS_CACHE: frozenset[str] | None = None


def _cobol_reserved_words() -> frozenset[str]:
    """The lexer's COBOL keyword set, imported lazily and cached.

    Deferred import: ``cobolparser.lexer`` must stay out of this module's
    import-time dependencies (the package ``__init__`` chain would make an
    eager import circular), same rationale as the lexer's own deferred
    preprocess imports.
    """
    global _RESERVED_WORDS_CACHE
    if _RESERVED_WORDS_CACHE is None:
        from ..lexer import CobolLexer

        _RESERVED_WORDS_CACHE = frozenset(CobolLexer.KEYWORDS)
    return _RESERVED_WORDS_CACHE


def strip_sequence_area(source: str) -> str:
    """
    Strip the sequence areas from fixed-format COBOL for regex-based extraction.

    In fixed-format COBOL:
    - Columns 1-6: Sequence number area (stripped for pattern matching)
    - Column 7: Indicator area (kept for comment/continuation detection)
    - Columns 8-72: Program text area (the actual code)
    - Columns 73-80: Identification/sequence area (stripped to prevent false matches)

    Stripping both areas is critical for COPY statement extraction where:
    1. The copybook name may appear at the end of the code area (column 72) and
       could incorrectly concatenate with content from the identification area.
    2. Multi-line statements need to match across line breaks without sequence
       numbers interfering with the regex patterns.

    Args:
        source: COBOL source code (may be fixed-format with sequence areas)

    Returns:
        Source with columns 1-6 and 73+ stripped from each line

    Example:
        >>> line = "033800     COPY                                                    KP001SM2064.2"
        >>> strip_sequence_area(line)
        "     COPY                                                    KP001"
    """
    # Tabs are expanded before slicing, as normalize_fixed_format does, so a
    # tab-indented member is cut at the same columns the final parse uses.
    lines = _records(source.expandtabs(8))
    result = []
    # Lines after ``>>SOURCE FORMAT IS FREE`` have no sequence area,
    # indicator column or column-72 limit: kept whole, behind a blank
    # indicator so the stripped shape (indicator at index 0) still holds.
    free = free_format_flags(lines) if ">>" in source else None

    # Define column boundaries (0-indexed)
    SEQUENCE_NUMBER_END = 6  # Columns 1-6 (indices 0-5)

    for index, line in enumerate(lines):
        if free is not None and free[index]:
            result.append(" " + line if line.strip() else "")
            continue
        if len(line) < 7:
            # Short line: in strict fixed format every character it has
            # lies within columns 1-6, the sequence area this function
            # exists to strip. Shop change-control tags stamped into
            # columns 1-6 of their own line (``P2P``, ``M1005`` -- any
            # prefix, unlike the column-7 V-convention) used to survive the
            # old pass-it-through-verbatim behavior; the expander's 6-space
            # re-pad then shifted the tag's first letter into the indicator
            # column and the rest into columns 8+ as live code, surfacing
            # as "Unparsed tokens" (or silently swallowed garbage) in the
            # final parse. But blanking *every* short line is too eager:
            # real-world flush-left copybooks (no sequence numbers at all)
            # carry short code lines like ``01 A.`` or ``EXIT.`` that the
            # passthrough kept working -- blanking those silently deletes
            # code with no warning. So blank only tag-shaped content: a
            # single blank-free token that neither ends the statement with
            # a period nor is ANY COBOL reserved word. The keyword check
            # matters beyond compiler-directing words: a flush-left
            # ``GOBACK`` (6 chars) with its period on the next line, or a
            # verb like ``MOVE``/``EXIT``/``STOP`` split from its operands,
            # is real code -- shop change tags (``P2P``, ``M1005``,
            # ``E1A``) are never reserved words. Everything else keeps the
            # passthrough.
            content = line.strip()
            is_tag = (
                bool(content)
                and " " not in content
                and not content.endswith(".")
                and content.upper() not in _cobol_reserved_words()
            )
            result.append("" if is_tag else line)
        else:
            # A flush-left PROCESS/CBL directive is real code occupying
            # columns 1+, not a sequence number -- unconditionally eating
            # columns 1-6 turns "PROCESS &CICS-31&..." into a mangled
            # "S &CICS-31&..." before any later PROCESS-stripping pass ever
            # sees the directive intact. Only lines whose columns 1-6 do NOT
            # already look like a real sequence area (blank or all-digit)
            # are considered, so ordinary numbered/tagged source is
            # unaffected -- this line is passed through untouched rather
            # than re-sliced at column 7, since there is no indicator column
            # to preserve when the directive itself starts at column 1.
            first_six = line[:SEQUENCE_NUMBER_END]
            has_sequence_area = (
                first_six.strip() == "" or first_six.replace(" ", "").isdigit()
            )
            if not has_sequence_area and _COMPILER_DIRECTIVE_RE.match(line):
                result.append(line[:FIXED_FORMAT_CODE_END_COLUMN])
                continue

            # Extract columns 7-72 (indicator + program text)
            # Column 7 (index 6) is indicator area - keep it
            # Columns 8-72 (indices 7-71) are program text area
            # Columns 73+ (index 72+) are identification area - strip

            # Keep indicator (index 6) and program text (indices 7 to 71)
            start_idx = SEQUENCE_NUMBER_END  # Start at column 7 (index 6)
            end_idx = min(len(line), FIXED_FORMAT_CODE_END_COLUMN)

            result.append(line[start_idx:end_idx])

    return "\n".join(result)


def is_comment_line(line: str) -> bool:
    """
    Check if a line is a COBOL comment line.

    In fixed-format COBOL:
    - Column 7 (index 6) contains '*' for full-line comments
    - Column 7 contains '/' for page break comments (also treated as comments)
    - Column 7 contains 'D' or 'd' for debugging lines (typically treated as comments)
    - Column 7 contains 'V' or 'v' for shop-specific change-control
      version-tag lines (e.g. a short tag like ``V97``/``TFEC`` stamped into
      Area A) -- not a standard COBOL indicator, but standard fixed-format
      source never puts live code in column 7 either, so treating it as a
      comment is unambiguous with real code.

    Args:
        line: A single line of COBOL source code

    Returns:
        True if the line is a comment, False otherwise

    Example:
        >>> is_comment_line("      * This is a comment")
        True
        >>> is_comment_line("       MOVE A TO B.")
        False
    """
    if len(line) < 7:
        return False
    return line[6] in ALL_COMMENT_INDICATORS


def is_within_string_literal(source: str, match_start: int, match_end: int) -> bool:
    """
    Check if a regex match position falls within a COBOL string literal.

    COBOL strings are delimited by either single quotes (') or double quotes (").
    This function checks if the match position is inside an unclosed string.

    Args:
        source: The full source code string
        match_start: Start position of the match in the source
        match_end: End position of the match in the source

    Returns:
        True if the match is within a string literal, False otherwise

    Example:
        >>> source = '       DISPLAY "COPY EMPLOYEE.".'
        >>> is_within_string_literal(source, 16, 20)  # Position of "COPY"
        True
    """
    # Get the text before the match on the same line
    line_start = source.rfind("\n", 0, match_start) + 1
    text_before_match = source[line_start:match_start]

    # Count unescaped quotes before the match (doubled quotes are escaped)
    double_quote_count = _count_unmatched_quotes(text_before_match, '"')
    single_quote_count = _count_unmatched_quotes(text_before_match, "'")

    # If we have an odd number of quotes, we're inside a string
    # COBOL typically uses one type consistently, so check both
    in_double_quote_string = double_quote_count % 2 == 1
    in_single_quote_string = single_quote_count % 2 == 1

    return in_double_quote_string or in_single_quote_string


def remove_comment_lines(source: str, *, keep_debug_lines: bool = False) -> str:
    """
    Remove comment content from COBOL source code while preserving line count.

    Args:
        source: COBOL source code
        keep_debug_lines: Leave debugging lines (``D`` in column 7) in place
            rather than blanking them -- for a parse that compiles them as
            code (``debug_lines=True``); their indicator stays in column 7
            for the final normalization to read

    Returns:
        Source with comment lines blanked out so line positions remain stable
    """
    # Tabs expanded first so column 7 is judged where normalize_fixed_format
    # will judge it (a tab-indented line is never a comment in either).
    lines = _records(source.expandtabs(8))
    result = []
    # A free-format line (after ``>>SOURCE FORMAT IS FREE``) has no
    # indicator column, so column 7 says nothing about it.
    free = free_format_flags(lines) if ">>" in source else None

    for index, line in enumerate(lines):
        if free is not None and free[index]:
            result.append(line)
        elif is_comment_line(line) and not (
            keep_debug_lines and line[6] in DEBUG_INDICATORS
        ):
            result.append(" " * len(line))
        else:
            result.append(line)

    return "\n".join(result)


#: ``EXEC SQL`` immediately before an ``INCLUDE`` keyword (any layout
#: between the words); the match starts at ``EXEC`` so the whole statement,
#: terminator included, is the span the expander replaces.
_EXEC_SQL_TAIL_RE = re.compile(r"EXEC\s+SQL\s*$", re.IGNORECASE)

#: Runs the statement scan can skip whole once a keyword match fails at their
#: first character: from anywhere inside a separator run ``_match_keyword``
#: skips to the same next character and fails the same way, and a keyword
#: starting inside an identifier is always rejected by the left word-boundary
#: check. Stepping through them one character at a time made the scan
#: quadratic in the length of a whitespace run (a few thousand blank lines
#: took minutes).
_SEPARATOR_RUN_RE = re.compile(r"[\s,;]+")
_WORD_RUN_RE = re.compile(r"[\w-]+")


class CopyStatementLexer:
    """
    A robust state-based lexer for extracting COPY statements from COBOL source.
    """

    def __init__(
        self,
        source: str,
        source_file: str = "<main>",
        *,
        sql_include: bool = False,
        line_origins: list[int] | None = None,
    ):
        # Comment-entry text (``AUTHOR. JOHN O'BRIEN.``) is blanked: it is
        # opaque documentation, never literals or COPY statements (#251).
        self.source = mask_comment_entries(source)
        self.source_file = source_file
        self.pos = 0
        self.length = len(source)
        #: Also recognize ``EXEC SQL INCLUDE member END-EXEC`` as a copy
        #: statement (see :attr:`CopyStatement.sql_include`). Off by
        #: default: the un-expanding parse path strips what this lexer
        #: finds, and an INCLUDE it cannot expand must reach the parser
        #: intact as the EXEC SQL statement it is.
        self.sql_include = sql_include
        #: Diagnostics for COPY statements that were recognized but could not
        #: be tokenized into a complete CopyStatement (and are therefore never
        #: expanded). Callers surface these via ExpansionStatistics.warnings /
        #: ParseResult.warnings so the drop is not silent (audit 2026-07-07
        #: H6a/H6c).
        self.warnings: list[str] = []
        #: Per line of *source*, the 1-based line of the caller's original
        #: text it came from -- set when *source* had continuation records
        #: merged (``normalize_continuation_lines(line_origins=...)``), so
        #: :attr:`warnings` name the line a human edits rather than a line of
        #: the merged text (#256).
        self.line_origins = line_origins

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.source[idx] if idx < self.length else ""

    def _advance(self, count: int = 1) -> None:
        self.pos = min(self.pos + count, self.length)

    def _is_at_end(self) -> bool:
        return self.pos >= self.length

    def _skip_separators(self) -> None:
        """Skip whitespace and COBOL separators (comma, semicolon)."""
        while not self._is_at_end():
            c = self._peek()
            if c.isspace() or c in (",", ";"):
                self._advance()
            else:
                break

    def _match_keyword(self, keyword: str) -> bool:
        """Check for a keyword and advance if matched, skipping leading separators."""
        start_pos = self.pos
        self._skip_separators()
        if self.source[self.pos : self.pos + len(keyword)].upper() == keyword.upper():
            # Check for word boundary
            next_char = self._peek(len(keyword))
            if not next_char or not (next_char.isalnum() or next_char in ("-", "_")):
                self._advance(len(keyword))
                return True

        # Restore position if no match
        self.pos = start_pos
        return False

    def _read_operand(self, *, keep_literal_quotes: bool = False) -> str | None:
        """Read a pseudo-text, literal, or identifier operand.

        Pseudo-text delimiters are stripped from the returned text. This
        applies both to the standard ``==text==`` form and to the alternate
        ``:text:`` form (e.g. ``REPLACING :ABC: BY :XYZ:`` yields the operand
        pair ``ABC`` / ``XYZ``), mirroring :func:`parse_replacing_clause`.

        A literal comes back as its content (``COPY 'REC'`` names member
        ``REC``) unless *keep_literal_quotes*, which REPLACING operands need:
        ``'ABC' BY 'XYZ'`` replaces the *literal* ``'ABC'`` with the literal
        ``'XYZ'``. Stripped, it became the word ``ABC``, which never matched
        the literal and rewrote an identifier ``ABC`` to a bare ``XYZ``.
        """
        self._skip_separators()
        if self._is_at_end():
            return None

        start_pos = self.pos
        char = self._peek()

        # 1. Pseudo-text ==...==
        if char == "=" and self._peek(1) == "=":
            self._advance(2)
            while not self._is_at_end():
                if self._peek() == "=" and self._peek(1) == "=":
                    # Leading/trailing blanks of pseudo-text are not part of
                    # it (``== A ==`` finds the word A), as in
                    # parse_replacing_clause.
                    text = self.source[start_pos + 2 : self.pos].strip()
                    self._advance(2)
                    return text
                self._advance()
            self.warnings.append(
                f"{self.source_file}: unterminated ==pseudo-text== operand "
                "(missing closing '==') — the REPLACING clause was abandoned "
                "and its COPY statement will not be expanded"
            )
            return None

        # 1b. Alternate pseudo-text :text: (COPY REPLACING colon delimiters).
        # The colons are delimiters, not part of the operand text:
        # "REPLACING :ABC: BY :XYZ:" replaces ABC by XYZ. If no closing colon
        # is found on the same line, fall through to the identifier scan so a
        # stray colon is treated as ordinary token text (mirrors the regex in
        # parse_replacing_clause, which also strips the delimiters).
        if char == ":":
            scan = self.pos + 1
            while scan < self.length and self.source[scan] not in (":", "\n", "\r"):
                scan += 1
            if scan > self.pos + 1 and scan < self.length and self.source[scan] == ":":
                text = self.source[self.pos + 1 : scan]
                self.pos = scan + 1
                return text

        # 2. String literal "..." or '...'. A literal ends at the end of its
        # line at the latest: this scan runs after continuation records are
        # merged, so no real literal spans a newline, and an unmatched quote
        # must not swallow the rest of the file (#251).
        if char in ('"', "'"):
            quote = char
            self._advance()
            while not self._is_at_end():
                if self._peek() in ("\n", "\r"):
                    return None
                if self._peek() == quote and self._peek(1) == quote:
                    self._advance(2)
                elif self._peek() == quote:
                    self._advance()
                    if keep_literal_quotes:
                        return self.source[start_pos : self.pos]
                    return self.source[start_pos + 1 : self.pos - 1].replace(
                        quote * 2, quote
                    )
                else:
                    self._advance()
            return None

        # 3. Identifier or qualified identifier
        while not self._is_at_end():
            c = self._peek()
            if c.isspace() or c in (",", ";", "=", "(", ")"):
                if c == "(":  # Handle MEMBER(QUAL)
                    while not self._is_at_end() and self._peek() != ")":
                        self._advance()
                    if not self._is_at_end():
                        self._advance()
                    continue
                break
            # Allow dot inside identifier only when followed by alphanumeric
            # (e.g. "CUSTDATA.CPY" — the .CPY is a file extension)
            # Stop at dot if followed by space or another non-alnum (statement terminator)
            if c == ".":
                next_c = self._peek(1)
                if next_c and (next_c.isalnum() or next_c == "_"):
                    self._advance()
                    continue
                break
            self._advance()

        return self.source[start_pos : self.pos] if self.pos > start_pos else None

    def _read_replacing_operand(self) -> str | None:
        """Read one REPLACING operand (pseudo-text, literal, word or identifier).

        An identifier operand may be qualified and subscripted (IBM:
        ``identifier`` includes ``OF``/``IN`` qualification, subscripts and
        reference modification). Once REPLACING has started, ``OF``/``IN`` can
        only be qualification -- the library name comes before REPLACING -- so
        a word operand is extended greedily with ``(OF|IN) word`` pairs and
        with parenthesised groups, with or without a blank before the ``(``:
        ``WS-FLD OF WS-GRP`` and ``WS-TBL (2)`` used to come back as
        ``WS-FLD`` / ``WS-TBL``, the rest dropped without a warning (#253).
        """
        self._skip_separators()
        start = self.pos
        first = self._peek()
        operand = self._read_operand(keep_literal_quotes=True)
        if operand is None or first in ('"', "'", "=", ":"):
            return operand
        while True:
            save = self.pos
            self._skip_separators()
            if self._peek() == "(":
                depth = 0
                while not self._is_at_end():
                    c = self._peek()
                    self._advance()
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
                if depth != 0:
                    self.pos = save
                    break
                continue
            if self._match_keyword("OF") or self._match_keyword("IN"):
                self._skip_separators()
                if self._peek() not in ('"', "'", "=", ":", "."):
                    qualifier = self._read_operand()
                    if qualifier:
                        continue
            self.pos = save
            break
        return self.source[start : self.pos]

    def tokenize_copy_statements(self) -> list[CopyStatement]:
        newline_positions = [m.end() - 1 for m in _EOL_RE.finditer(self.source)]
        statements: list[CopyStatement] = []
        while not self._is_at_end():
            char = self._peek()

            # 1. Protection against COPY inside strings
            if char in ('"', "'"):
                self._read_operand()
                continue

            # 1b. A `*>` inline comment (outside a literal) runs to end of
            # line: a COPY mentioned there is prose, not a statement.
            if char == "*" and self._peek(1) == ">":
                newline = self.source.find("\n", self.pos)
                self.pos = self.length if newline == -1 else newline
                continue

            # 2. Find next 'COPY' -- or, when enabled, an EXEC SQL INCLUDE
            is_include = False
            if self._match_keyword("COPY"):
                match_start = self.pos - 4
                # Word-boundary check on the LEFT side: "GOODCOPY." must not
                # be treated as an identifier followed by a COPY statement.
                if match_start > 0:
                    prev_char = self.source[match_start - 1]
                    if prev_char.isalnum() or prev_char in ("-", "_"):
                        continue
            elif self.sql_include and self._match_keyword("INCLUDE"):
                keyword_start = self.pos - len("INCLUDE")
                if keyword_start > 0:
                    prev_char = self.source[keyword_start - 1]
                    if prev_char.isalnum() or prev_char in ("-", "_"):
                        continue
                exec_sql = _EXEC_SQL_TAIL_RE.search(self.source[:keyword_start])
                if exec_sql is None:
                    continue  # INCLUDE as an ordinary word, not EXEC SQL INCLUDE
                match_start = exec_sql.start()
                is_include = True
            else:
                run = _SEPARATOR_RUN_RE.match(self.source, self.pos) or (
                    _WORD_RUN_RE.match(self.source, self.pos)
                )
                if run:
                    self.pos = run.end()
                else:
                    self._advance()
                continue
            self._skip_separators()

            # 3. Read Member Name
            member_name = self._read_operand()
            if not member_name:
                self.warnings.append(
                    f"{self.source_file}: {'EXEC SQL INCLUDE' if is_include else 'COPY'} "
                    f"statement at line "
                    f"{self._report_line(match_start, newline_positions)} has no "
                    "member name and was ignored"
                )
                continue
            stmt_count_before = len(statements)

            if is_include:
                # EXEC SQL INCLUDE member END-EXEC [.] -- no clauses; the
                # scope terminator is the only thing that may follow.
                self._skip_separators()
                if not self._match_keyword("END-EXEC"):
                    self.warnings.append(
                        f"{self.source_file}: EXEC SQL INCLUDE {member_name} at "
                        f"line {self._report_line(match_start, newline_positions)} "
                        "has no END-EXEC and was ignored"
                    )
                    continue
                if self._peek() == "." and not self._peek(1).isalnum():
                    self._advance()
                line_num, col_num = self._line_col_of(match_start, newline_positions)
                statements.append(
                    CopyStatement(
                        member_name=member_name.strip(),
                        source_location=(self.source_file, line_num, col_num),
                        original_text=self.source[match_start : self.pos],
                        start_index=match_start,
                        end_index=self.pos,
                        sql_include=True,
                    )
                )
                continue

            library_qualifier = None
            suppress_clause = None
            replacing_clauses: list[ReplacingClause] = []

            # 4. Parse Clauses
            while not self._is_at_end():
                self._skip_separators()

                # End of statement
                if self._peek() == "." and not self._peek(1).isalnum():
                    self._advance()
                    _nl_idx = bisect.bisect_right(newline_positions, match_start)
                    line_num = _nl_idx + 1
                    prev_nl_idx = _nl_idx - 1
                    col_num = match_start - (
                        newline_positions[prev_nl_idx] if prev_nl_idx >= 0 else -1
                    )

                    statements.append(
                        CopyStatement(
                            member_name=member_name.strip(),
                            library_qualifier=(
                                library_qualifier.strip() if library_qualifier else None
                            ),
                            replacing_clauses=(
                                replacing_clauses if replacing_clauses else None
                            ),
                            suppress_clause=suppress_clause,
                            source_location=(self.source_file, line_num, col_num),
                            original_text=self.source[match_start : self.pos],
                            start_index=match_start,
                            end_index=self.pos,
                        )
                    )
                    break

                # IN/OF
                if self._match_keyword("IN") or self._match_keyword("OF"):
                    library_qualifier = self._read_operand()
                    continue

                # SUPPRESS
                if self._match_keyword("SUPPRESS"):
                    self._match_keyword("PRINTING")
                    suppress_clause = SuppressClause(suppress_all=True)
                    continue

                # REPLACING
                if self._match_keyword("REPLACING"):
                    while True:
                        self._skip_separators()
                        if self._is_at_end() or self._peek() == ".":
                            break

                        # Peek for next major clause
                        curr_before_peek = self.pos
                        if (
                            self._match_keyword("IN")
                            or self._match_keyword("OF")
                            or self._match_keyword("SUPPRESS")
                        ):
                            self.pos = curr_before_peek
                            break

                        mode = "ALL"
                        if self._match_keyword("LEADING"):
                            mode = "LEADING"
                        elif self._match_keyword("TRAILING"):
                            mode = "TRAILING"

                        search = self._read_replacing_operand()
                        if not search:
                            # If no operand, break REPLACING loop
                            break

                        if not self._match_keyword("BY"):
                            # This word was not part of a replacement pair,
                            # back up to before this search operand if possible or just break
                            # In most cases, it means the REPLACING clause ended early or is malformed
                            # We break and let the outer loop handle the next token
                            break

                        replace = self._read_replacing_operand()
                        if replace is None:
                            break

                        replacing_clauses.append(
                            ReplacingClause(
                                find_text=search, replace_text=replace, mode=mode
                            )
                        )
                    continue

                # Next COPY or unexpected token
                curr = self.pos
                if self._match_keyword("COPY") or self._peek().isalnum():
                    self.pos = curr
                    break

                self._advance()

            # A COPY whose clause scan ended without reaching a terminating
            # period is never appended — and therefore never expanded. That
            # used to be completely silent (audit 2026-07-07 H6a): the
            # copybook's data items simply did not exist in the AST.
            if len(statements) == stmt_count_before:
                self.warnings.append(
                    f"{self.source_file}: COPY {member_name.strip()} at line "
                    f"{self._report_line(match_start, newline_positions)} has no "
                    "terminating period (or is followed by unexpected tokens) "
                    "and was NOT expanded — its content is missing from the "
                    "parsed program"
                )

        return statements

    @staticmethod
    def _line_col_of(index: int, newline_positions: list[int]) -> tuple[int, int]:
        """1-based (line, column) of *index*, like the COPY branch computes."""
        nl_idx = bisect.bisect_right(newline_positions, index)
        prev_nl_idx = nl_idx - 1
        col = index - (newline_positions[prev_nl_idx] if prev_nl_idx >= 0 else -1)
        return nl_idx + 1, col

    def _report_line(self, index: int, newline_positions: list[int]) -> int:
        """Line of *index* for a diagnostic: in the original text when
        :attr:`line_origins` maps it, else in *source*."""
        line = self._line_of(index, newline_positions)
        if self.line_origins and 0 < line <= len(self.line_origins):
            return self.line_origins[line - 1]
        return line

    @staticmethod
    def _line_of(index: int, newline_positions: list[int]) -> int:
        """Return the 1-based line number of a character *index*."""
        return bisect.bisect_right(newline_positions, index) + 1


def extract_copy_statements(
    source_code: str,
    source_file: str = "<main>",
    warnings: list[str] | None = None,
    sql_include: bool = False,
) -> list[CopyStatement]:
    """
    Extract all COPY statements from COBOL source code using a robust shallow lexer.

    This function properly handles:
    - Comment lines (asterisk/slash in column 7) - ignored
    - COPY keywords within string literals - ignored
    - Continuation lines (hyphen in column 7) - merged before parsing
    - Sequence/identification areas (columns 1-6 and 73-80) - stripped before parsing

    Args:
        source_code: COBOL source code to parse
        source_file: Source file name for location tracking
        warnings: Optional list that receives diagnostics for COPY statements
            that were recognized but dropped (no terminating period,
            unterminated pseudo-text) and will therefore never be expanded
        sql_include: Also return each ``EXEC SQL INCLUDE member END-EXEC`` as
            a :class:`CopyStatement` with ``sql_include=True`` -- the same
            members the copybook expander inlines. Off by default.

    Returns:
        List of CopyStatement objects representing each COPY statement found
    """
    # Step 1: Remove comment lines FIRST
    source_without_comments = remove_comment_lines(source_code)

    # Step 2: Strip sequence areas
    source_stripped = strip_sequence_area(source_without_comments)

    # Step 3: Normalize continuation lines
    normalized_source = normalize_continuation_lines(
        source_stripped, indicator_position=0
    )

    # Step 4: Use CopyStatementLexer for extraction
    lexer = CopyStatementLexer(normalized_source, source_file, sql_include=sql_include)
    statements = lexer.tokenize_copy_statements()
    if warnings is not None and lexer.warnings:
        warnings.extend(lexer.warnings)
    return statements


def parse_suppress_clause(suppress_text: str | None) -> SuppressClause:
    """
    Parse COPY SUPPRESS clause into a SuppressClause object.

    Supports IBM Enterprise COBOL SUPPRESS syntax:
    - SUPPRESS (suppress all)
    - SUPPRESS 1 THRU 5 (suppress lines 1-5)
    - SUPPRESS 1 THRU 5, 10, 15 THRU 20 (multiple ranges and lines)

    Args:
        suppress_text: The SUPPRESS clause text (after SUPPRESS keyword), or None

    Returns:
        SuppressClause object representing the suppression rules

    Example:
        >>> clause = parse_suppress_clause(None)
        >>> clause.suppress_all
        True

        >>> clause = parse_suppress_clause("1 THRU 5, 10")
        >>> clause.line_ranges
        [(1, 5)]
        >>> clause.single_lines
        [10]
    """
    if not suppress_text or not suppress_text.strip():
        # SUPPRESS with no details means suppress all
        return SuppressClause(suppress_all=True)

    suppress_text = suppress_text.strip()
    line_ranges = []
    single_lines = []

    # Pattern for "N THRU M" or "N THROUGH M"
    range_pattern = re.compile(r"(\d+)\s+(?:THRU|THROUGH)\s+(\d+)", re.IGNORECASE)

    # Find all ranges
    for match in range_pattern.finditer(suppress_text):
        start = int(match.group(1))
        end = int(match.group(2))
        line_ranges.append((start, end))

    # Remove ranges from text to find standalone numbers
    remaining = range_pattern.sub("", suppress_text)

    # Find standalone line numbers
    for num_match in re.finditer(r"\b(\d+)\b", remaining):
        single_lines.append(int(num_match.group(1)))

    return SuppressClause(
        suppress_all=False, line_ranges=line_ranges, single_lines=single_lines
    )


def parse_replacing_clause(replacing_text: str) -> list[ReplacingClause]:
    """
    Parse COPY REPLACING clause into ReplacingClause objects.

    Supports IBM Enterprise COBOL REPLACING syntax:
    - ==text== BY ==replacement==
    - :text: BY :replacement:
    - LEADING ==prefix== BY ==new-prefix==
    - TRAILING ==suffix== BY ==new-suffix==

    Args:
        replacing_text: The REPLACING clause text (after REPLACING keyword)

    Returns:
        List of ReplacingClause objects

    Example:
        >>> clauses = parse_replacing_clause("==OLD== BY ==NEW==")
        >>> clauses[0].find_text
        'OLD'
        >>> clauses[0].mode
        'ALL'

        >>> clauses = parse_replacing_clause("LEADING ==:PREFIX:== BY ==EMP-==")
        >>> clauses[0].mode
        'LEADING'
    """
    clauses = []

    # Enhanced pattern with LEADING/TRAILING support
    # Supports both == and : delimiters, and allows empty replacement text
    pattern = re.compile(
        r"(LEADING|TRAILING)?\s*"  # Optional modifier (group 1)
        r"(?:==([^=]+)==|:([^:]+):)"  # Find text (groups 2, 3)
        r"\s+BY\s+"
        r"(?:==([^=]*)==|:([^:]*):)",  # Replace text (groups 4, 5) - allow empty
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(replacing_text):
        modifier = match.group(1)
        find_text = match.group(2) or match.group(3)
        replace_text = match.group(4) if match.group(4) is not None else match.group(5)

        if replace_text is None:
            replace_text = ""

        mode = modifier.upper() if modifier else "ALL"

        clauses.append(
            ReplacingClause(
                find_text=find_text.strip(),
                replace_text=replace_text.strip(),
                mode=mode,
            )
        )

    return clauses


#: The text words of a pseudo-text operand: a literal (doubled quotes kept),
#: a parenthesis (a text word of its own), or a run of anything else.
_PSEUDO_TEXT_WORD_RE = re.compile(
    r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[()]|[^\s()'\"]+"
)


#: One separator between two text words of the source: a blank, a line
#: break, or a separator comma / semicolon (one followed by a blank).  IBM:
#: "a separator comma or separator semicolon ... is considered to be a
#: space" when comparing pseudo-text, so ``==X(3) VALUE==`` finds ``X(3),
#: VALUE``. Pseudo-text is compared on the text-word stream, where the end of
#: a line is just another separator, so ``==ML-B PIC X(5). 05 ML-C==`` finds
#: the two copybook lines it spans (#560).
_SEPARATOR_GAP = r"(?:[ \t\n]|[,;](?=[ \t\n]))"

#: A separator comma / semicolon at the end of a pseudo-text word.
_TRAILING_SEPARATOR_RE = re.compile(r"[,;]+$")


def _pseudo_text_words(text: str) -> list[str]:
    """The text words of pseudo-text *text*, separator commas dropped.

    A comma or semicolon ending a (non-literal) word is a separator, not
    part of the word, so it is dropped rather than compared -- the other
    half of the rule :data:`_SEPARATOR_GAP` applies to the source side.
    Only one at the very end of *text* or followed by a blank counts: a
    comma inside a word (``1,5`` under DECIMAL-POINT IS COMMA) is kept.
    """
    words: list[str] = []
    for match in _PSEUDO_TEXT_WORD_RE.finditer(text):
        word = match.group(0)
        if word[0] not in "'\"":
            after = text[match.end() : match.end() + 1]
            if after in ("", " ", "\t", "\n", "\r"):
                word = _TRAILING_SEPARATOR_RE.sub("", word)
            if not word:
                continue
        words.append(word)
    return words


def _build_clause_pattern(clause: ReplacingClause) -> str | None:
    """
    Build the regex *source* for a single REPLACING clause.

    Pseudo-text is compared as COBOL *text words*, not as raw characters:
    the blanks between two words of the search text match any run of
    blanks in the source (``==PIC X(10)==`` finds ``PIC  X(10)``), and a
    parenthesis is a text word of its own, so the blank beside it is
    optional (``X (10)`` too). A separator comma or semicolon counts as a
    blank on both sides (``==X(3) VALUE==`` finds ``X(3), VALUE``).
    Leading/trailing blanks of the pseudo-text are not part of it.
    A line break in the source is a separator like any blank (#560).

    Uses identifier-safe boundaries to avoid partial word collisions: regex
    ``\\b`` is unsuitable because COBOL identifiers can contain hyphens, so a
    custom boundary (not preceded/followed by ``[A-Za-z0-9-]``) is applied on
    each side of the search text that starts/ends with an identifier
    character. If the text starts/ends with a special character (like ``:``),
    no boundary is enforced on that side.

    Returns None when the clause cannot be applied (empty search text or an
    unknown mode), in which case the clause is skipped.
    """
    find_text = clause.find_text.strip()
    if not find_text:
        return None
    words = _pseudo_text_words(find_text)
    if not words:
        return None

    body = ""
    for index, word in enumerate(words):
        if index:
            beside_paren = word in ("(", ")") or words[index - 1] in ("(", ")")
            body += _SEPARATOR_GAP + ("*" if beside_paren else "+")
        if word[0] in ("'", '"'):
            # Literal content is case-sensitive even though the pattern as a
            # whole is compiled IGNORECASE (``=='abc'==`` must not rewrite
            # ``'ABC'``).
            body += "(?-i:" + re.escape(word) + ")"
        else:
            body += re.escape(word)

    is_start_word = _is_word_char(find_text[0])
    is_end_word = _is_word_char(find_text[-1])

    # A word boundary is "no identifier character beside it"; a numeric
    # literal's decimal point also binds (``1`` is not a word of ``1.5``).
    start_boundary = r"(?<![A-Za-z0-9_-])(?<![0-9]\.)" if is_start_word else r""
    end_boundary = r"(?![A-Za-z0-9_-])(?!\.[0-9])" if is_end_word else r""

    if clause.mode == "ALL":
        return start_boundary + body + end_boundary
    if clause.mode == "LEADING":
        return start_boundary + body + (r"(?=[A-Za-z0-9_-])" if is_end_word else r"")
    if clause.mode == "TRAILING":
        return (r"(?<=[A-Za-z0-9_-])" if is_start_word else r"") + body + end_boundary
    return None


def _is_word_char(char: str) -> bool:
    """True for a character that can be part of a COBOL word."""
    return char.isalnum() or char in ("-", "_")


def _split_literal_segments(line: str) -> list[tuple[str, bool]]:
    """
    Split a single source line into (segment, is_literal) pieces.

    Literal segments include their delimiting quotes. Doubled quotes inside a
    literal (``''`` or ``""``) are treated as escapes and do not terminate it.
    An unterminated literal runs to the end of the line (fixed-format
    continuation of literals is not resolved at this stage).
    """
    segments: list[tuple[str, bool]] = []
    length = len(line)
    pos = 0
    code_start = 0
    while pos < length:
        quote = line[pos]
        if quote not in ('"', "'"):
            pos += 1
            continue
        if pos > code_start:
            segments.append((line[code_start:pos], False))
        end = pos + 1
        while end < length:
            if line[end] == quote:
                if end + 1 < length and line[end + 1] == quote:
                    end += 2  # Escaped (doubled) quote inside the literal
                    continue
                end += 1  # Closing quote
                break
            end += 1
        segments.append((line[pos:end], True))
        pos = end
        code_start = end
    if code_start < length or not segments:
        segments.append((line[code_start:], False))
    return segments


def apply_replacing_clauses(
    content: str,
    clauses: list[ReplacingClause],
    indicator_position: int = 6,
    line_origins: list[int] | None = None,
) -> str:
    """
    Apply REPLACING clauses to copybook content with identifier awareness.

    Substitution is context-aware (open-findings M13):

    - Fixed-format comment lines (``*`` or ``/`` in the indicator column) are
      never modified.
    - Text inside alphanumeric string literals (``'...'`` or ``"..."``,
      including doubled-quote escapes) is never modified — unless the
      clause's own search text contains a quote character (a pseudo-text
      operand such as ``=='OLD'== BY =='NEW'==`` explicitly targets literal
      text and is therefore allowed to match it).
    - Identifier operands match whole COBOL words only (custom boundaries so
      hyphenated identifiers are not split). Operands written with the
      alternate ``:text:`` pseudo-text delimiters arrive here with the
      delimiters already stripped by the tokenizer and use the same
      whole-word semantics; because ``:`` is not an identifier character,
      ``REPLACING :TAG: BY :EMP:`` rewrites the ``TAG`` in ``:TAG:-FIELD``
      as well as standalone ``TAG`` tokens (whole-token-substring
      semantics).

    Args:
        content: Copybook content. Column 7 is fixed-format's indicator
            column; ``indicator_position`` locates it in *content*.
        clauses: REPLACING clauses to apply.
        indicator_position: Index of the indicator character in each line
            (default 6, matching raw fixed-format text with the
            sequence-number area still present). Pass 0 for content that has
            already had ``strip_sequence_area`` applied, where the indicator
            is the first character of each line.
        line_origins: When given, filled with the 1-based line of *content*
            each line of the result came from. A BY text that adds lines
            repeats the line its match started on; one that removes lines
            (a match spanning several) keeps the first. The source map needs
            it: numbering the replaced text from 1 as if it were the
            copybook shifted every later line (#561).

    Matching runs over the whole text, not line by line: pseudo-text is
    compared on the text-word stream, where a line break is a separator, so
    a search text whose words a copybook splits across two lines is found
    (#560). A match is never taken inside a comment line.
    """
    lines = _records(content)

    # Comment status is decided once, from the original content, so a
    # substitution can never shift a line into or out of comment status
    # midway through applying the clause list.
    is_comment = [
        len(line) > indicator_position and line[indicator_position] in ("*", "/")
        for line in lines
    ]

    # Sort clauses by length descending to prioritize longer matches (e.g. 'ABC-1' before 'ABC')
    sorted_clauses = sorted(clauses, key=lambda c: len(c.find_text), reverse=True)

    # Every clause goes into ONE alternation applied in ONE left-to-right
    # pass per segment, so each text word is compared against the clauses
    # (longest search text first) and replaced at most once -- the
    # standard's rule. The previous one-pass-per-clause loop re-scanned the
    # text an earlier clause had just emitted, so
    # ``==A== BY ==B== ==B== BY ==A==`` turned every A *and* B into A
    # instead of swapping them.
    replacements: dict[str, str] = {}
    quoted: set[str] = set()
    code_alternatives: list[str] = []
    literal_alternatives: list[str] = []
    # LEADING / TRAILING clauses, in clause order, each with its own pattern:
    # a word one of them matches is settled by the first that fits (#513).
    # Written order, not the longest-first order above: with
    # LEADING ==X== ... TRAILING ==XX== the standard (and REPLACE) let the
    # LEADING clause settle X-NAME-XX because it is written first.
    partial_clauses: list[tuple[str, str, re.Pattern[str]]] = []
    written_order = {id(clause): i for i, clause in enumerate(clauses)}
    partial_order: list[int] = []
    for index, clause in enumerate(sorted_clauses):
        source = _build_clause_pattern(clause)
        if source is None:
            continue
        name = f"c{index}"
        alternative = f"(?P<{name}>{source})"
        replacements[name] = clause.replace_text
        if clause.mode in ("LEADING", "TRAILING"):
            partial_clauses.append(
                (name, clause.mode, re.compile(source, re.IGNORECASE))
            )
            partial_order.append(written_order[id(clause)])
        code_alternatives.append(alternative)
        # A search text that itself contains a quote deliberately targets
        # literal text; only such clauses may match inside string literals.
        if '"' in clause.find_text or "'" in clause.find_text:
            quoted.add(name)
            literal_alternatives.append(alternative)
    partial_clauses = [
        partial
        for _, partial in sorted(
            zip(partial_order, partial_clauses, strict=True),
            key=lambda pair: pair[0],
        )
    ]
    if not code_alternatives:
        if line_origins is not None:
            line_origins[:] = range(1, len(lines) + 1)
        return content
    code_pattern = re.compile("|".join(code_alternatives), re.IGNORECASE)
    literal_pattern = (
        re.compile("|".join(literal_alternatives), re.IGNORECASE)
        if literal_alternatives
        else None
    )

    text = "\n".join(lines)
    # Offset of each line's first character in *text*.
    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1
    comment_spans = [
        (line_starts[idx], line_starts[idx] + len(line))
        for idx, line in enumerate(lines)
        if is_comment[idx]
    ]
    literal_spans = [
        (line_starts[idx] + start, line_starts[idx] + start + len(segment))
        for idx, line in enumerate(lines)
        if not is_comment[idx] and ('"' in line or "'" in line)
        for start, segment, is_literal in _segment_offsets(line)
        if is_literal
    ]

    def _in_spans(spans: list[tuple[int, int]], start: int, end: int) -> bool:
        # *spans* are sorted and disjoint: only the last one starting before
        # *end* can overlap [start, end).
        index = bisect.bisect_left(spans, (max(end, start + 1), -1)) - 1
        return index >= 0 and spans[index][1] > start

    def _line_of(position: int) -> int:
        return bisect.bisect_right(line_starts, position)  # 1-based

    out: list[str] = []
    origins: list[int] = [1]
    pos = 0
    search_from = 0

    def _copy(end: int) -> None:
        # Unchanged text: each line it starts keeps its own input line.
        chunk = text[pos:end]
        newline = chunk.find("\n")
        while newline != -1:
            origins.append(_line_of(pos + newline + 1))
            newline = chunk.find("\n", newline + 1)
        out.append(chunk)

    while True:
        match = code_pattern.search(text, search_from)
        if match is None:
            break
        name = match.lastgroup or ""
        chosen: re.Match[str] | None = match
        if _in_spans(comment_spans, match.start(), match.end()):
            chosen = None
        elif name not in quoted and _in_spans(
            literal_spans, match.start(), match.start() + 1
        ):
            # A search text with no quote of its own can only lie wholly
            # inside a literal; at that position the quote-bearing clauses
            # still get their turn.
            chosen = (
                literal_pattern.match(text, match.start())
                if literal_pattern is not None
                else None
            )
            if chosen is not None and _in_spans(
                comment_spans, chosen.start(), chosen.end()
            ):
                chosen = None
        if chosen is None:
            search_from = match.start() + 1
            continue
        name = chosen.lastgroup or ""
        start, end = chosen.start(), chosen.end()
        word_end = end
        if any(name == partial_name for partial_name, _, _ in partial_clauses):
            # LEADING tests a word's start and TRAILING its end, so the
            # leftmost hit is not the whole story: the standard compares the
            # word against the clauses in order, the first that fits
            # replaces it, and the word is then done. Without this,
            # LEADING ==XX== ... TRAILING ==XX== rewrote both ends of
            # XX-NAME-XX (#513), unlike REPLACE.
            word_start = start
            # Never reach back into text an earlier replacement emitted.
            while word_start > pos and _is_word_char(text[word_start - 1]):
                word_start -= 1
            while word_end < len(text) and _is_word_char(text[word_end]):
                word_end += 1
            for partial_name, mode, pattern in partial_clauses:
                hit = (
                    pattern.match(text, word_start, word_end)
                    if mode == "LEADING"
                    else pattern.search(text, word_start, word_end)
                )
                if hit is not None:
                    name, start, end = partial_name, hit.start(), hit.end()
                    break
        _copy(start)
        # Literal text, never an re template: a backslash in it
        # (`'C:\TEMP\1'`) must not be read as a group reference.
        replacement = replacements[name]
        out.append(replacement)
        # Lines the BY text adds belong to the line its match started on.
        origins.extend([_line_of(start)] * replacement.count("\n"))
        pos = end
        _copy(word_end)  # the rest of a partially replaced word, unchanged
        pos = search_from = word_end
    _copy(len(text))

    if line_origins is not None:
        line_origins[:] = origins
    return "".join(out)


def _segment_offsets(line: str) -> list[tuple[int, str, bool]]:
    """``_split_literal_segments`` with each segment's start offset."""
    result: list[tuple[int, str, bool]] = []
    offset = 0
    for segment, is_literal in _split_literal_segments(line):
        result.append((offset, segment, is_literal))
        offset += len(segment)
    return result


def track_source_location(
    line_number: int, source_file: str, original_line: int
) -> tuple[int, tuple[str, int]]:
    """
    Create a source location mapping entry.

    Args:
        line_number: Line number in expanded output
        source_file: Original source file path
        original_line: Line number in original source file

    Returns:
        Tuple of (line_number, (source_file, original_line))
    """
    return (line_number, (source_file, original_line))


__all__ = [
    "extract_copy_statements",
    "parse_replacing_clause",
    "parse_suppress_clause",
    "apply_replacing_clauses",
    "normalize_continuation_lines",
    "strip_sequence_area",
    "track_source_location",
    "is_comment_line",
    "is_within_string_literal",
    "remove_comment_lines",
    "FIXED_FORMAT_CODE_END_COLUMN",
]
