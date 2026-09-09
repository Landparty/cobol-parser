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

from ._normalize import ALL_COMMENT_INDICATORS
from .models import CopyStatement, ReplacingClause, SuppressClause

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
    lines = source.expandtabs(8).split("\n")
    result: list[str] = []

    # Text starts after the indicator column
    text_start = indicator_position + 1

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
                    cont_stripped = continuation_text.lstrip()
                    if cont_stripped.startswith(open_quote):
                        cont_stripped = cont_stripped[1:]
                    result[target] = prev_line + cont_stripped
                else:
                    # Non-literal continuation: strip leading spaces
                    # In COBOL, when continuing a non-literal (like an identifier),
                    # the continuation text is concatenated directly to the previous text.
                    # Example: "O005" continued with "F-001" becomes "O005F-001"
                    result[target] = prev_line.rstrip() + continuation_text.lstrip()
            else:
                # Orphan continuation line - just add the text part
                result.append(line[text_start:] if len(line) > text_start else "")
                if line_origins is not None:
                    line_origins.append(line_number)
        else:
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
    lines = source.expandtabs(8).split("\n")
    result = []

    # Define column boundaries (0-indexed)
    SEQUENCE_NUMBER_END = 6  # Columns 1-6 (indices 0-5)

    for line in lines:
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


def remove_comment_lines(source: str) -> str:
    """
    Remove comment content from COBOL source code while preserving line count.

    Args:
        source: COBOL source code

    Returns:
        Source with comment lines blanked out so line positions remain stable
    """
    # Tabs expanded first so column 7 is judged where normalize_fixed_format
    # will judge it (a tab-indented line is never a comment in either).
    lines = source.expandtabs(8).split("\n")
    result = []

    for line in lines:
        if is_comment_line(line):
            result.append(" " * len(line))
        else:
            result.append(line)

    return "\n".join(result)


class CopyStatementLexer:
    """
    A robust state-based lexer for extracting COPY statements from COBOL source.
    """

    def __init__(self, source: str, source_file: str = "<main>"):
        self.source = source
        self.source_file = source_file
        self.pos = 0
        self.length = len(source)
        #: Diagnostics for COPY statements that were recognized but could not
        #: be tokenized into a complete CopyStatement (and are therefore never
        #: expanded). Callers surface these via ExpansionStatistics.warnings /
        #: ParseResult.warnings so the drop is not silent (audit 2026-07-07
        #: H6a/H6c).
        self.warnings: list[str] = []

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

    def _read_operand(self) -> str | None:
        """Read a pseudo-text, literal, or identifier operand.

        Pseudo-text delimiters are stripped from the returned text. This
        applies both to the standard ``==text==`` form and to the alternate
        ``:text:`` form (e.g. ``REPLACING :ABC: BY :XYZ:`` yields the operand
        pair ``ABC`` / ``XYZ``), mirroring :func:`parse_replacing_clause`.
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
                    text = self.source[start_pos + 2 : self.pos]
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

        # 2. String literal "..." or '...'
        if char in ('"', "'"):
            quote = char
            self._advance()
            while not self._is_at_end():
                if self._peek() == quote and self._peek(1) == quote:
                    self._advance(2)
                elif self._peek() == quote:
                    self._advance()
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

            # 2. Find next 'COPY'
            if not self._match_keyword("COPY"):
                self._advance()
                continue

            match_start = self.pos - 4
            # Word-boundary check on the LEFT side: "GOODCOPY." must not be
            # treated as an identifier followed by a COPY statement.
            if match_start > 0:
                prev_char = self.source[match_start - 1]
                if prev_char.isalnum() or prev_char in ("-", "_"):
                    continue
            self._skip_separators()

            # 3. Read Member Name
            member_name = self._read_operand()
            if not member_name:
                self.warnings.append(
                    f"{self.source_file}: COPY statement at line "
                    f"{self._line_of(match_start, newline_positions)} has no "
                    "member name and was ignored"
                )
                continue
            stmt_count_before = len(statements)

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

                        search = self._read_operand()
                        if not search:
                            # If no operand, break REPLACING loop
                            break

                        if not self._match_keyword("BY"):
                            # This word was not part of a replacement pair,
                            # back up to before this search operand if possible or just break
                            # In most cases, it means the REPLACING clause ended early or is malformed
                            # We break and let the outer loop handle the next token
                            break

                        replace = self._read_operand()
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
                    f"{self._line_of(match_start, newline_positions)} has no "
                    "terminating period (or is followed by unexpected tokens) "
                    "and was NOT expanded — its content is missing from the "
                    "parsed program"
                )

        return statements

    @staticmethod
    def _line_of(index: int, newline_positions: list[int]) -> int:
        """Return the 1-based line number of a character *index*."""
        return bisect.bisect_right(newline_positions, index) + 1


def extract_copy_statements(
    source_code: str,
    source_file: str = "<main>",
    warnings: list[str] | None = None,
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
    lexer = CopyStatementLexer(normalized_source, source_file)
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


def _build_clause_pattern(clause: ReplacingClause) -> "re.Pattern[str] | None":
    """
    Compile the regex pattern for a single REPLACING clause.

    Uses identifier-safe boundaries to avoid partial word collisions: regex
    ``\\b`` is unsuitable because COBOL identifiers can contain hyphens, so a
    custom boundary (not preceded/followed by ``[A-Za-z0-9-]``) is applied on
    each side of the search text that starts/ends with an identifier
    character. If the text starts/ends with a special character (like ``:``),
    no boundary is enforced on that side.

    Returns None when the clause cannot be applied (empty search text or an
    unknown mode), in which case the clause is skipped.
    """
    find_text = clause.find_text
    if not find_text:
        return None

    is_start_word = find_text[0].isalnum() or find_text[0] == "-"
    is_end_word = find_text[-1].isalnum() or find_text[-1] == "-"

    start_boundary = r"(?<![A-Za-z0-9-])" if is_start_word else r""
    end_boundary = r"(?![A-Za-z0-9-])" if is_end_word else r""
    escaped = re.escape(find_text)

    if clause.mode == "ALL":
        return re.compile(start_boundary + escaped + end_boundary, re.IGNORECASE)
    if clause.mode == "LEADING":
        return re.compile(
            start_boundary + escaped + (r"(?=[A-Za-z0-9-])" if is_end_word else r""),
            re.IGNORECASE,
        )
    if clause.mode == "TRAILING":
        return re.compile(
            (r"(?<=[A-Za-z0-9-])" if is_start_word else r"") + escaped + end_boundary,
            re.IGNORECASE,
        )
    return None


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
    """
    lines = content.split("\n")

    # Comment status is decided once, from the original content, so a
    # substitution can never shift a line into or out of comment status
    # midway through applying the clause list.
    is_comment = [
        len(line) > indicator_position and line[indicator_position] in ("*", "/")
        for line in lines
    ]

    # Sort clauses by length descending to prioritize longer matches (e.g. 'ABC-1' before 'ABC')
    sorted_clauses = sorted(clauses, key=lambda c: len(c.find_text), reverse=True)

    for clause in sorted_clauses:
        pattern = _build_clause_pattern(clause)
        if pattern is None:
            continue

        # A search text that itself contains a quote deliberately targets
        # literal text; only then may string literals be rewritten.
        protect_literals = '"' not in clause.find_text and "'" not in clause.find_text

        # The replacement is literal text, never an re template: a
        # backslash in it (`'C:\TEMP\1'`) would otherwise raise re.error or
        # be silently reinterpreted as a group reference.
        def _literal_replacement(_m: re.Match[str], r: str = clause.replace_text) -> str:
            return r

        for idx, line in enumerate(lines):
            if is_comment[idx]:
                continue
            if protect_literals and ('"' in line or "'" in line):
                lines[idx] = "".join(
                    segment if is_literal else pattern.sub(_literal_replacement, segment)
                    for segment, is_literal in _split_literal_segments(line)
                )
            else:
                lines[idx] = pattern.sub(_literal_replacement, line)

    return "\n".join(lines)


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
