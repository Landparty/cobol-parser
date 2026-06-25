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

# COPY statement regex patterns supporting IBM Enterprise COBOL syntax
# Matches: COPY member, COPY "member", COPY member IN/OF library, COPY member SUPPRESS, COPY member REPLACING
#
# The REPLACING clause pattern handles:
# - Pseudo-text blocks (==...==) which may contain periods
# - Plain identifiers and literals after BY
# A period inside ==...== should NOT terminate the COPY statement.
# The statement ends with a period that follows the complete REPLACING clause.
#
# Pattern structure:
#   COPY <member> [IN/OF <library>] [SUPPRESS [PRINTING]] [REPLACING <clauses>] .
#
# REPLACING operands can be:
# - Pseudo-text: ==...== or :...:
# - Identifiers: WORD-NAME, FIELD-01, etc.
# - Literals: "string" or 'string'
# - Numeric literals with optional sign: +2, -3, 00001
# - Figurative constants: SPACE, ZERO, etc.

# Helper pattern for REPLACING operands (pseudo-text, identifier, literal, or numeric)
_REPLACING_OPERAND = (
    r"(?:"
    r"==(?:[^=]|=[^=])*=="  # Pseudo-text ==...==
    r"|"
    r":(?:[^:])*:"  # Alternate pseudo-text :...:
    r"|"
    r'"[^"]*"'  # Double-quoted literal
    r"|"
    r"'[^']*'"  # Single-quoted literal
    r"|"
    r"[+-]?[0-9]+(?:\.[0-9]+)?"  # Numeric literal with optional sign and decimal
    r"|"
    r"[A-Za-z0-9][-A-Za-z0-9]*(?:\s+(?:IN|OF)\s+[A-Za-z0-9][-A-Za-z0-9]*)*(?:\s*\([^)]+\))?"  # Qualified identifier with optional subscript
    r")"
)

COPY_PATTERN = re.compile(
    r"\bCOPY\s+"  # COPY keyword
    r"(?:"  # Member name (quoted or unquoted)
    r'"([^"]+)"'  # Quoted member name (group 1)
    r"|"
    r"'([^']+)'"  # Single-quoted member name (group 2)
    r"|"
    r"([A-Za-z0-9_.-]+)"  # Unquoted member name (group 3) - allow dots for extensions like .CPY
    r")"
    r"(?:\s+(?:IN|OF)\s+([A-Za-z0-9_-]+))?"  # Optional library qualifier (group 4)
    r"(?:\s+(SUPPRESS)(?:\s+(PRINTING))?)?"  # Optional SUPPRESS [PRINTING] clause (groups 5, 6)
    r"(?:\s+REPLACING\s+"  # Optional REPLACING clause start
    r"("  # Capture the entire REPLACING content (group 7)
    r"(?:"
    r"(?:LEADING\s+|TRAILING\s+)?"  # Optional LEADING/TRAILING modifier
    + _REPLACING_OPERAND  # Find operand
    + r"\s+BY\s+"
    + _REPLACING_OPERAND  # Replace operand
    + r"\s*"
    r")+"
    r")"
    r")?"
    r"\s*\.",  # Terminating period (NOT inside pseudo-text)
    re.IGNORECASE | re.DOTALL,
)


def normalize_continuation_lines(source: str, indicator_position: int = 6) -> str:
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

    Returns:
        Source with continuation lines merged

    Example:
        >>> source = "       COPY EMPLOYEE REPLACING\\n      -    ==OLD== BY ==NEW==."
        >>> normalize_continuation_lines(source)
        "       COPY EMPLOYEE REPLACING ==OLD== BY ==NEW==."
    """
    lines = source.split("\n")
    result: list[str] = []

    # Text starts after the indicator column
    text_start = indicator_position + 1

    for _i, line in enumerate(lines):
        # Check if this is a continuation line (indicator is '-')
        if len(line) > indicator_position and line[indicator_position] == "-":
            # This is a continuation line
            if result:
                # Get the continuation text (after the indicator)
                continuation_text = line[text_start:] if len(line) > text_start else ""

                # Get the previous line (the one we're continuing)
                prev_line = result[-1].rstrip()

                # Check if we're continuing a string literal
                # Count unmatched quotes in previous line to determine if we're in a string
                in_double_string = _count_unmatched_quotes(prev_line, '"') % 2 == 1
                in_single_string = _count_unmatched_quotes(prev_line, "'") % 2 == 1

                if in_double_string or in_single_string:
                    # We're continuing a string literal
                    # COBOL continuation: the continuation line starts with the quote char
                    # which should be skipped as it's just indicating literal continuation
                    cont_stripped = continuation_text.lstrip()
                    if cont_stripped:
                        if in_double_string and cont_stripped.startswith('"'):
                            # Skip the continuation quote
                            continuation_text = cont_stripped[1:]
                        elif in_single_string and cont_stripped.startswith("'"):
                            # Skip the continuation quote
                            continuation_text = cont_stripped[1:]
                else:
                    # Non-literal continuation: strip leading spaces
                    # In COBOL, when continuing a non-literal (like an identifier),
                    # the continuation text is concatenated directly to the previous text.
                    # Example: "O005" continued with "F-001" becomes "O005F-001"
                    continuation_text = continuation_text.lstrip()

                # Append to previous line
                result[-1] = prev_line + continuation_text
            else:
                # Orphan continuation line - just add the text part
                result.append(line[text_start:] if len(line) > text_start else "")
        else:
            result.append(line)

    return "\n".join(result)


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
    lines = source.split("\n")
    result = []

    # Define column boundaries (0-indexed)
    SEQUENCE_NUMBER_END = 6  # Columns 1-6 (indices 0-5)

    for line in lines:
        if len(line) < 7:
            # Short line - might be free-format or empty, keep as-is
            result.append(line)
        else:
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
    indicator = line[6]
    return indicator in ("*", "/", "D", "d")


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
    lines = source.split("\n")
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
        """Read a pseudo-text, literal, or identifier operand."""
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
            return None

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
        statements = []
        while not self._is_at_end():
            char = self._peek()

            # 1. Protection against COPY inside strings
            if char in ('"', "'"):
                self._read_operand()
                continue

            # 2. Find next 'COPY'
            if not self._match_keyword("COPY"):
                self._advance()
                continue

            match_start = self.pos - 4
            self._skip_separators()

            # 3. Read Member Name
            member_name = self._read_operand()
            if not member_name:
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

        return statements


def extract_copy_statements(
    source_code: str, source_file: str = "<main>"
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
    return lexer.tokenize_copy_statements()


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


def apply_replacing_clauses(content: str, clauses: list[ReplacingClause]) -> str:
    """
    Apply REPLACING clauses to copybook content with identifier awareness.
    """
    result = content

    # Sort clauses by length descending to prioritize longer matches (e.g. 'ABC-1' before 'ABC')
    sorted_clauses = sorted(clauses, key=lambda c: len(c.find_text), reverse=True)

    for clause in sorted_clauses:
        # We use identifier-safe boundaries for modes to avoid partial word collisions
        # word boundaries \b in regex are good but COBOL identifiers can contain hyphens
        # So we define a custom boundary: not followed/preceded by [A-Za-z0-9-]
        # Determine boundaries based on whether the search text starts/ends with word chars
        # If text starts/ends with special char (like :), don't enforce word boundary on that side
        is_start_word = clause.find_text and (
            clause.find_text[0].isalnum() or clause.find_text[0] == "-"
        )
        is_end_word = clause.find_text and (
            clause.find_text[-1].isalnum() or clause.find_text[-1] == "-"
        )

        start_boundary = r"(?<![A-Za-z0-9-])" if is_start_word else r""
        end_boundary = r"(?![A-Za-z0-9-])" if is_end_word else r""

        if clause.mode == "ALL":
            pattern = re.compile(
                start_boundary + re.escape(clause.find_text) + end_boundary,
                re.IGNORECASE,
            )
            result = pattern.sub(clause.replace_text, result)

        elif clause.mode == "LEADING":
            pattern = re.compile(
                start_boundary
                + re.escape(clause.find_text)
                + (r"(?=[A-Za-z0-9-])" if is_end_word else r""),
                re.IGNORECASE,
            )
            result = pattern.sub(clause.replace_text, result)

        elif clause.mode == "TRAILING":
            pattern = re.compile(
                (r"(?<=[A-Za-z0-9-])" if is_start_word else r"")
                + re.escape(clause.find_text)
                + end_boundary,
                re.IGNORECASE,
            )
            result = pattern.sub(clause.replace_text, result)

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
    "COPY_PATTERN",
    "FIXED_FORMAT_CODE_END_COLUMN",
]
