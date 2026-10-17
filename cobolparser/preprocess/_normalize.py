"""Source normalization and conditional-compilation preprocessing.

Implementation module for the parts of :mod:`cobolparser.preprocess` that are
not copybook expansion: fixed-format normalization, compiler-directive
stripping, the ``>>IF``/``>>EVALUATE`` conditional-compilation evaluator, the
copybook content/level validators, and the preprocessing exception hierarchy.

This lives in a private module so that ``preprocess/__init__.py`` stays a
thin re-export stub. Import these names from :mod:`cobolparser.preprocess`
-- the package re-exports all of them.
"""

import re
from collections.abc import Callable, Iterable, Mapping

from .._lines import split_source_lines
from .._source_directive import source_format_directive

# Pre-compiled regex patterns for preprocessing (avoids re-compilation per call)
#: ``>>DEFINE name [AS] {literal | PARAMETER | OFF} [OVERRIDE]`` (IBM). The
#: value is captured lazily so a trailing ``OVERRIDE`` is never taken as
#: part of it (``AS 2 OVERRIDE`` used to define the value ``"2 OVERRIDE"``).
#: The symbol may carry hyphens like any COBOL word (``>>DEFINE MAX-ROWS``);
#: ``\w+`` alone rejected every such name as malformed.
_DEFINE_RE = re.compile(
    r">>DEFINE\s+([\w-]+)(?:\s+(?:AS\s+)?(?!OVERRIDE\s*$)(.+?))?(?:\s+OVERRIDE)?\s*$"
)
#: The head of a data-description entry: a level number and the name it
#: introduces. Shared by the two patterns below so they cannot disagree about
#: what an entry looks like -- when they did, a single-digit level closed the
#: entry above it (via the first) but could never be reported for its own
#: missing period (via the second). ``\d{1,2}`` because a single-digit level
#: (``5 FIELD-A``) is legal COBOL.
_ENTRY_HEAD = r"[ \t]*\d{1,2}[ \t]+[A-Za-z][A-Za-z0-9-]*"
#: Starts a data-description entry. Used to find where one entry ENDS -- at the
#: line that starts the next one -- since a single entry may legally span
#: several lines.
_DATA_ENTRY_START_RE = re.compile(rf"^{_ENTRY_HEAD}\b")
#: An entry that declares a PICTURE, and so is one whose missing terminating
#: period is worth reporting. Matched against a whole entry, not one line.
_DATA_DEF_RE = re.compile(
    rf"^{_ENTRY_HEAD}[ \t]+.*\bPIC(?:TURE)?\b",
    re.IGNORECASE | re.DOTALL,
)
#: A line that is not part of the entry above it even though it does not start
#: one either -- an in-line ``EXEC SQL`` block being the copybook case.
# A line that belongs to no data-description entry: an EXEC block, or a
# ``>>`` compiler directive (``>>IF`` / ``>>ELSE`` / ``>>END-IF`` wrapping
# alternative entries of a copybook -- the validator runs before the
# directives are evaluated, and an entry that "ran on" into ``>>ELSE`` read
# as one missing its period).
_NON_ENTRY_LINE_RE = re.compile(r"^[ \t]*(?:EXEC\b|>>)", re.IGNORECASE)

#: An IDENTIFICATION (or ID) DIVISION header line, raw or normalized. A
#: fixed-format record's columns 1-6 may hold *anything* -- sequence digits,
#: blanks, or a change tag such as ``CHG001`` -- so whether the line has a
#: sequence area is decided by column 7 (blank) rather than by what columns
#: 1-6 contain (#252). A comment record (``*`` / ``/`` in column 7) never
#: matches.
ID_DIVISION_HEADER_RE = re.compile(
    r"^(?:[^\r\n]{6}(?=[ \t]))?\s*(IDENTIFICATION|ID)\s+(DIVISION|DIV)",
    re.IGNORECASE,
)
_LEVEL_NUMBER_RE = re.compile(r"^\s*(\d{2})\s+[A-Za-z]", re.MULTILINE)


def _unterminated_data_entries(content: str) -> list[int]:
    """Line numbers (1-based) of PICTURE entries with no terminating period.

    A data-description entry is one COBOL sentence, and it is routinely
    written across several lines -- ``05 WS-B PIC X(30)`` on one and
    ``VALUE 'TEXT'.`` on the next is correct, terminated source. Judging
    each physical line on its own reports every such entry as unterminated,
    which is how this check used to read a whole copybook of legal
    ``PIC``/``VALUE`` pairs as a whole copybook of errors. So the unit
    examined here is the ENTRY: the line that starts it, plus every line up
    to (not including) the one that starts the next.

    Blank lines never close an entry. ``remove_comment_lines`` blanks comment
    lines to whitespace before this runs, and a comment sitting between an
    entry's ``PIC`` line and its ``VALUE`` line is ordinary source -- treating
    the blank it leaves behind as a terminator would resurrect the same false
    positive by another route.
    """
    lines = split_source_lines(content)
    starts = [i for i, line in enumerate(lines) if _DATA_ENTRY_START_RE.match(line)]
    unterminated: list[int] = []

    for position, first in enumerate(starts):
        # The entry runs to the next entry, or to the next line that belongs
        # to neither (an EXEC block), or to the end of the content.
        limit = starts[position + 1] if position + 1 < len(starts) else len(lines)
        last = first + 1
        while last < limit and not _NON_ENTRY_LINE_RE.match(lines[last]):
            last += 1

        entry = "\n".join(lines[first:last]).rstrip()
        if entry.endswith("."):
            continue
        if _DATA_DEF_RE.match(entry):
            unterminated.append(first + 1)

    return unterminated


class PreprocessingError(Exception):
    """Base class for all preprocessing exceptions.

    Catch this to handle any failure that occurs during copybook expansion
    or source normalization, without needing to enumerate every subtype.
    """

    pass


class CircularReferenceError(PreprocessingError):
    """
    Raised when a circular dependency is detected in copybook includes.

    Attributes:
        dependency_chain: List of copybook names showing the circular path
        message: Human-readable error message with dependency chain
    """

    def __init__(self, dependency_chain: list[str], message: str | None = None):
        self.dependency_chain = dependency_chain
        if message is None:
            chain_str = " → ".join(dependency_chain)
            message = f"Circular copybook dependency detected: {chain_str}"
        super().__init__(message)


class CopybookNotFoundError(PreprocessingError):
    """
    Raised when a referenced copybook file cannot be found.

    Attributes:
        copybook_name: Name of the copybook that was not found
        search_paths: List of directories that were searched
        suggestions: List of similar copybook names (for typo detection)
        message: Human-readable error message
    """

    def __init__(
        self,
        copybook_name: str,
        search_paths: list[str],
        suggestions: list[str] | None = None,
        message: str | None = None,
    ):
        self.copybook_name = copybook_name
        self.search_paths = search_paths
        self.suggestions = suggestions or []
        if message is None:
            paths_str = (
                ", ".join(search_paths) if search_paths else "(no paths configured)"
            )
            message = (
                f"Copybook '{copybook_name}' not found in search paths: {paths_str}"
            )
            if self.suggestions:
                message += f". Did you mean: {', '.join(self.suggestions)}?"
        super().__init__(message)


class PathTraversalError(PreprocessingError):
    """
    Raised when a path traversal attempt is detected (security violation).

    Attributes:
        attempted_path: The path that triggered the security violation
        message: Human-readable error message
    """

    def __init__(self, attempted_path: str, message: str | None = None):
        self.attempted_path = attempted_path
        if message is None:
            message = f"Path traversal attempt detected: '{attempted_path}' attempts to escape search directories"
        super().__init__(message)


class EncodingError(PreprocessingError):
    """
    Raised when file encoding cannot be detected or conversion fails.

    Attributes:
        file_path: Path to the file with encoding issues
        details: Additional details about the encoding problem
        message: Human-readable error message
    """

    def __init__(
        self, file_path: str, details: str | None = None, message: str | None = None
    ):
        self.file_path = file_path
        self.details = details
        if message is None:
            message = f"Encoding error for file '{file_path}'"
            if details:
                message += f": {details}"
        super().__init__(message)


class NestingDepthError(PreprocessingError):
    """
    Raised when copybook nesting exceeds the configured maximum depth.

    Attributes:
        current_depth: The nesting depth that was reached
        max_depth: The configured maximum depth limit
        message: Human-readable error message
    """

    def __init__(self, current_depth: int, max_depth: int, message: str | None = None):
        self.current_depth = current_depth
        self.max_depth = max_depth
        if message is None:
            message = f"Nesting depth exceeded: reached {current_depth} levels (max: {max_depth})"
        super().__init__(message)


class CopybookSizeExceededError(PreprocessingError):
    """
    Raised when a copybook file exceeds the configured size limit.

    Attributes:
        copybook_path: Path to the oversized copybook
        size: Actual size in bytes
        limit: Configured size limit in bytes
        message: Human-readable error message
    """

    def __init__(
        self, copybook_path: str, size: int, limit: int, message: str | None = None
    ):
        self.copybook_path = copybook_path
        self.size = size
        self.limit = limit
        if message is None:
            message = (
                f"Copybook '{copybook_path}' size ({size:,} bytes) "
                f"exceeds limit ({limit:,} bytes)"
            )
        super().__init__(message)


class CopybookSyntaxError(PreprocessingError):
    """
    Raised when copybook contains invalid or malformed content.

    Attributes:
        copybook_path: Path to the copybook with syntax issues
        line: Line number where issue was detected (if applicable)
        details: Description of the syntax problem
        message: Human-readable error message
    """

    def __init__(
        self,
        copybook_path: str,
        details: str,
        line: int | None = None,
        message: str | None = None,
    ):
        self.copybook_path = copybook_path
        self.line = line
        self.details = details
        if message is None:
            if line:
                message = f"Syntax error in '{copybook_path}' at line {line}: {details}"
            else:
                message = f"Syntax error in '{copybook_path}': {details}"
        super().__init__(message)


class LevelNumberMismatchWarning(UserWarning):
    """
    Warning issued when level numbers may not align correctly after expansion.

    This is a warning rather than an error because some level mismatches
    may be intentional (e.g., copybook designed for specific contexts).
    """

    pass


class TotalExpansionSizeExceededError(PreprocessingError):
    """
    Raised when total expanded content exceeds the configured limit.

    Attributes:
        total_size: Total size reached in bytes
        limit: Configured limit in bytes
        message: Human-readable error message
    """

    def __init__(self, total_size: int, limit: int, message: str | None = None):
        self.total_size = total_size
        self.limit = limit
        if message is None:
            message = (
                f"Total expansion size ({total_size:,} bytes) "
                f"exceeds limit ({limit:,} bytes)"
            )
        super().__init__(message)


# Fixed-format COBOL normalization constants
DEFAULT_SEQ_COL_END = 6  # 1-6 sequence numbers
INDICATOR_COL = 7  # column 7 indicator position (1-based)
TEXT_START_COL = 8  # program text begins (1-based)
TEXT_END_COL = 72  # program text end (inclusive, 1-based)
IDENTIFICATION_END_COL = 80  # 73-80 identification area end (inclusive, 1-based)

# Column-7 indicator characters that mark a line as a comment. These are the
# single source of truth for every site that classifies indicator characters
# -- normalize_fixed_format below, copy_statement_parser.is_comment_line,
# source_format.detect_fixed_format, and lexer._fixed_format_comment_tokens all
# derive from these sets (the Cython mirror _preprocess_fast.pyx repeats the
# literals by design, like the rest of its body -- keep it in sync when
# extending these). The next shop convention from the corpus goes here, not
# into another hand-maintained per-site tuple.
COMMENT_INDICATORS = frozenset({"*", "/"})  # unconditional: comment / page eject
DEBUG_INDICATORS = frozenset({"D", "d"})  # debug lines (flag-gated in normalize)
VERSION_TAG_INDICATORS = frozenset({"V", "v"})  # version tags (flag-gated too)
ALL_COMMENT_INDICATORS = COMMENT_INDICATORS | DEBUG_INDICATORS | VERSION_TAG_INDICATORS

# How many *unambiguous* stamped lines a file must show before its
# columns-73+ numeric tails are read as an identification-area stamping
# convention rather than as split code. See
# _has_identification_stamp_convention below.
MIN_ID_STAMP_EVIDENCE_LINES = 3


def _literal_pad(text_slice: str) -> str:
    """Blanks standing in for the columns a *short* record never had.

    A literal left open at the end of a fixed-format line runs through
    column 72: the blanks between its last written character and column 72
    are part of its value (the M5 rule). Source whose trailing blanks were
    stripped -- by an editor, a file transfer, a commit filter; i.e. most
    copies of a deck kept off the mainframe -- ends such a line early, but
    the columns it lost are blanks to the compiler all the same. Without
    this pad ``VALUE 'ERROR: NOT `` + ``-    'FOUND'.`` read
    ``'ERROR: NOTFOUND'`` once its trailing blank was stripped, and
    ``'ERROR: NOT FOUND'`` while it was still there: one program, two values.
    """
    return " " * (TEXT_END_COL - TEXT_START_COL + 1 - len(text_slice))


def _is_numeric_id_stamp_text(tail: str) -> bool:
    """True when *tail* has the shape of a numeric identification-area stamp:
    at least one digit, and nothing but digits and blanks.

    Blanks are part of the shape, not noise around it. A change-control tool
    lays the identification field out in fixed sub-fields -- a real observed
    one writes ``01636  0`` (a 5-digit change id, two blanks, a 1-digit
    level), filling columns 73-80 exactly -- so a plain ``str.isdigit()``
    reads the shop's own stamp as split code. What the shape still excludes
    is any letter or punctuation, so a mixed identification code (NIST's
    ``IX2094.2``) and real truncated program text (``AYS``, ``ON
    WS-COUNT.``) are unaffected.
    """
    return any(ch.isdigit() for ch in tail) and all(
        ch.isdigit() or ch.isspace() for ch in tail
    )


def _has_identification_stamp_convention(lines: list[str]) -> bool:
    """True when *lines* demonstrably stamp a per-line numeric identification
    code into columns 73-80 while keeping all program text within column 72.

    This is the file-level counterpart to the columns-1-6 sequence-number
    gate in ``normalize_fixed_format``: both answer "does this deck use the
    traditional 80-column convention, where columns 73-80 are an
    identification field the compiler ignores unconditionally?" -- the
    question the per-line column-72/73 shape cannot answer on its own.

    Only *unambiguous* lines count as evidence: column 72 blank (so no token
    could have been split there), a stamp-shaped tail in columns 73 onward
    (``_is_numeric_id_stamp_text``), and total content within the
    traditional 80-column width. On
    such a line the tail cannot be anything but identification-area content,
    whatever columns 1-6 hold. ``MIN_ID_STAMP_EVIDENCE_LINES`` of them is
    the threshold: one or two numbers dangling past column 72 is an
    authoring accident, a whole deck of them is a convention.

    Returns as soon as the threshold is met, so a stamped file pays for a
    handful of lines rather than a full scan.
    """
    evidence = 0
    for raw in lines:
        candidate = raw.rstrip("\n").expandtabs(8)
        if len(candidate) <= TEXT_END_COL:
            continue
        if len(candidate.rstrip()) > IDENTIFICATION_END_COL:
            continue
        if not candidate[TEXT_END_COL - 1].isspace():
            # Column 72 non-blank: this line is itself ambiguous (it is the
            # very shape under investigation), so it can never be evidence.
            continue
        tail = candidate[TEXT_END_COL:].strip()
        if not _is_numeric_id_stamp_text(tail):
            continue
        evidence += 1
        if evidence >= MIN_ID_STAMP_EVIDENCE_LINES:
            return True
    return False


def strip_compiler_directives(
    source: str, *, preserve_line_numbers: bool = True
) -> str:
    """Remove PROCESS and CBL compiler directives from fixed-format COBOL source.

    This function processes raw fixed-format COBOL lines and removes any
    PROCESS or CBL compiler directives that appear before the IDENTIFICATION
    DIVISION. It handles continuation lines and preserves line numbers for
    accurate error reporting.

    Compiler directives are identified by:
    - Lines starting with "PROCESS" or "CBL" in columns 8-72 (or at start if no sequence area)
    - Continuation lines (indicator '-' in column 7)
    - Must appear before IDENTIFICATION DIVISION

    Args:
        source: Fixed-format COBOL source code (may or may not have sequence area)
        preserve_line_numbers: Replace removed lines with blank lines (default: True)

    Returns:
        Cleaned source code with PROCESS/CBL directives removed

    Note:
        This should be called BEFORE normalize_fixed_format().

    Example:
        >>> source = '''PROCESS APOST
        ...        IDENTIFICATION DIVISION.'''
        >>> result = strip_compiler_directives(source)
        >>> 'PROCESS' in result
        False
        >>> 'IDENTIFICATION' in result
        True
    """
    lines = split_source_lines(source, keepends=True)
    result_lines = []
    in_directive_section = True  # We start in the directive section
    in_continuation = False

    for line in lines:
        # Preserve the original line ending
        line_content = line.rstrip("\r\n")
        line_ending = line[len(line_content) :]

        # Determine where program text starts
        # Check if line has sequence area (columns 1-7 are typically spaces or sequence numbers)
        # If line starts with non-space in first 7 positions, it's likely without sequence area
        has_sequence_area = False
        if len(line_content) >= TEXT_START_COL:
            # Check if first 7 chars look like sequence area (spaces or digits)
            first_seven = line_content[: TEXT_START_COL - 1]
            # If first 7 chars are all spaces or digits, it's likely a sequence area
            if first_seven.strip() == "" or first_seven.replace(" ", "").isdigit():
                has_sequence_area = True

        if has_sequence_area:
            text_start = TEXT_START_COL - 1
            indicator_pos = INDICATOR_COL - 1
        else:
            # No sequence area - text starts at beginning
            text_start = 0
            indicator_pos = 6 if len(line_content) > 6 else 0

        # Extract program text area
        text_area = (
            line_content[text_start:].strip() if len(line_content) > text_start else ""
        )

        # Check if we've reached IDENTIFICATION DIVISION
        # This marks the end of the directive section
        # The header test does not rely on has_sequence_area: a change tag
        # in columns 1-6 of the header record (``CHG001``) used to keep the
        # directive section open for the whole file, blanking every later
        # ``PROCESS SECTION.`` as an option card (#252).
        if in_directive_section and text_area:
            text_upper = text_area.upper()
            if (
                text_upper.startswith("IDENTIFICATION")
                or text_upper.startswith("ID ")
                or ID_DIVISION_HEADER_RE.match(line_content)
            ):
                in_directive_section = False
                in_continuation = False
                result_lines.append(line)
                continue

        # If we're past the directive section, keep all lines
        if not in_directive_section:
            result_lines.append(line)
            continue

        # We're in the directive section - check for PROCESS/CBL
        # Get the indicator column (column 7, or position 6 for short lines)
        indicator = (
            line_content[indicator_pos] if len(line_content) > indicator_pos else " "
        )

        # Check for continuation line
        if indicator == "-":
            if in_continuation:
                # This is a continuation of a PROCESS/CBL directive
                if preserve_line_numbers:
                    result_lines.append(line_ending)  # Blank line
                # else: skip entirely
                continue
            else:
                # Continuation of something else (shouldn't happen before IDENTIFICATION)
                result_lines.append(line)
                continue

        # Not a continuation line - check if it's a PROCESS/CBL directive
        if text_area:
            text_upper = text_area.upper()

            # Check if line starts with PROCESS or CBL
            # Handle various formats: "PROCESS ", "PROCESS\t", "PROCESS", "CBL ", etc.
            is_directive = False
            if text_upper == "PROCESS" or text_upper == "CBL":
                is_directive = True
            elif text_upper.startswith("PROCESS ") or text_upper.startswith(
                "PROCESS\t"
            ):
                is_directive = True
            elif text_upper.startswith("CBL ") or text_upper.startswith("CBL\t"):
                is_directive = True

            if is_directive:
                # This is a PROCESS/CBL directive
                in_continuation = True
                if preserve_line_numbers:
                    result_lines.append(line_ending)  # Blank line
                # else: skip entirely
                continue

        # Not a directive - keep the line
        in_continuation = False
        result_lines.append(line)

    return "".join(result_lines)


def normalize_fixed_format(
    lines: Iterable[str] | str,
    *,
    merge_continued_literals: bool = True,
    debug_lines_as_comments: bool = True,
    version_tag_lines_as_comments: bool = True,
    warnings: list[str] | None = None,
) -> str:
    """Normalize fixed-format COBOL lines into a pseudo free-form block.

    Steps:
    - Strip sequence area (cols 1-6).
    - Expand tabs (8-column stops) before any column-sensitive slicing.
    - Capture indicator column; treat '*' and '/' lines as comments (preserve as-is).
      Optionally treat 'D'/'d' in the indicator column as a comment too
      (debug_lines_as_comments, default True) -- matches
      copy_statement_parser.is_comment_line(). Optionally treat 'V'/'v' in
      the indicator column as a comment too (version_tag_lines_as_comments,
      default True) -- some shops stamp a short change-control version tag
      (e.g. ``V97``, ``TFEC``) into Area A with 'V' in column 7; standard
      fixed-format COBOL never puts live code there, so this is unambiguous
      with real source and also matches copy_statement_parser.is_comment_line().
    - Extract program text cols 8-72.
    - If a continuation line (indicator '-') occurs and previous line ended inside a literal,
      merge without inserting a newline.
    - Otherwise join with newlines.

    This does NOT attempt full column-sensitive semantics (debugging helper).

    **``>>SOURCE FORMAT``.** A ``>>SOURCE [FORMAT] [IS] FREE`` directive
    (columns 7-72) switches the lines after it to free format: each is
    passed through whole as its own logical line, with no column slicing.
    ``>>SOURCE [FORMAT] [IS] FIXED`` (anywhere on a free-format line)
    switches back. The directive record itself becomes a blank line.

    **Column 73+ overflow.** Columns 73-80 are the identification area:
    real fixed-format compilers ignore them regardless of content, and so
    does this slice (``line[TEXT_START_COL - 1 : TEXT_END_COL]`` never
    bounds-checks the line length). Traditional 80-column source
    legitimately puts non-blank sequence/identification text there (e.g.
    NIST CCVS85's ``IC1014.2`` on every line) -- flagging that would be
    noise, not signal. Two independent shapes are worth flagging, checked
    in this order:

    1. **Mid-token split** -- columns 72 and 73 are both non-blank, i.e. a
       word was split with no separating blank (``WS-PARM-DORM-DAYS`` ->
       ``WS-PARM-DORM-D`` + dropped ``AYS``).
    2. **Word-boundary overflow** -- the split lands on a space at column
       72/73 (so case 1 misses it), but the line's real content -- after
       trailing whitespace is stripped -- extends past column
       ``IDENTIFICATION_END_COL`` (80), the traditional maximum width of an
       80-column punch-card line (72 code + 8 identification). Content that
       survives past column 80 can never be legitimate identification-area
       text regardless of where exactly it broke (e.g. ``OCCURS 1 TO 10
       TIMES DEPENDING ON WS-COUNT.`` on one line keeps ``DEPENDING`` but
       silently drops its `` ON WS-COUNT.`` operand -- columns 72/73
       straddle a space, so case 1 alone never catches it).

    Both rules are skipped entirely when the line's own columns 1-6 hold a
    real sequence number (all digits, ignoring surrounding blanks) --
    strong evidence the file deliberately uses the traditional 80-column
    convention, where the identification field may abut column 72 with no
    separating blank at all. Without this gate, rule 1 alone false-positives
    on the vast majority of genuinely traditional 80-column source (measured
    at 4434 of 4438 raw hits across the vendored NIST CCVS85 corpus): a
    line's own statement-terminating period frequently lands exactly on
    column 72, immediately followed by an unrelated per-line identification
    code at column 73 -- e.g. ``029100          "...".IX2094.2`` -- which
    is not a split at all. Hand-typed modern source never bothers with
    sequence numbers, so this gate leaves real truncation (this function's
    own reviewer-repro case, `WS-PARM-DORM-DAYS`, the OCCURS/DEPENDING ON
    case above) unaffected.

    Rule 1 has a second, independent gate: a *purely numeric* dropped tail
    that fits within the traditional 80-column width never warns either,
    regardless of columns 1-6. This covers editors/shops that stamp a
    per-line sequence or change-tracking number into columns 73-80 without
    also filling columns 1-6 (e.g. IBM Z Open Editor/ISPF-style auto
    numbering such as ``03050009``, incrementing on every line) -- a real,
    observed convention distinct from the columns-1-6 case above, where the
    *whole file* doesn't carry sequence numbers at the start of the line but
    still does at the end. This is narrower than "any dropped tail": a
    mixed alphanumeric tail like NIST's own ``IX2094.2`` test-case id does
    not qualify (it isn't all-digit), so that shape still warns -- see
    ``test_blank_sequence_area_with_same_shape_still_warns``.

    When `warnings` is given, each such line appends one
    ``f"Line {n}: ..."`` message to it (comment lines are never checked:
    their text is discarded whether truncated or not, so truncation there
    changes nothing). A line whose content stays within the traditional
    80-column width and doesn't split mid-token (the classic
    sequence-number/identification-area case) is never flagged.
    """
    if isinstance(lines, str):
        # A whole source string is a common caller mistake (iterating it
        # would feed one *character* per "line" and normalize to nothing).
        lines = split_source_lines(lines)
    # The comment/blank-line branches below look one code line ahead (a
    # continuation record may follow them), which needs random access.
    lines = list(lines)
    result: list[str] = []
    pending_literal = False
    quote_char: str | None = None
    parts: list[str] = []  # accumulates chunks for the current logical line
    # True once a non-comment, non-short physical line has started (or
    # continued) the logical line currently buffered in `parts`. Distinguishes
    # "no logical line accumulated yet" (nothing to flush) from "a logical
    # line was accumulated but its merged text happens to be empty" (a blank
    # placeholder must still be emitted -- see flush_parts below).
    has_line = False
    # Placeholder lines owed *after* the logical line in `parts` is flushed.
    # Every physical line must contribute exactly one output line so line
    # numbers survive normalization (``output.count("\n") == len(lines)``);
    # a continuation record merges its text into the logical line but is
    # still one physical line, so it owes one empty placeholder -- emitted
    # once the logical line it belongs to is written, so the logical line
    # keeps the number of its *first* record and the placeholders keep the
    # numbers of the records that followed it. Comment/blank lines that
    # interrupt a continued literal (legal in IBM fixed format: a
    # continuation line is "the next line that is neither a comment line nor
    # a blank line") are deferred the same way instead of severing it.
    deferred = 0
    # True while a literal is left open across an interrupting comment/blank
    # line. Decides the EOF verdict: a literal still open on the last *code*
    # line raises as before; one whose only successors were comment/blank
    # lines keeps the historical outcome (closed at the interruption, left
    # for the lexer to warn about) rather than escalating to a hard error.
    literal_suspended = False
    # Track quote state incrementally to avoid O(n²) rescanning
    _quote_open = False
    _quote_ch: str | None = None
    # The quote character that closed a literal exactly in column 72 of the
    # last program-text line, else None. IBM's continuation rule for that
    # case: if the next continuation line starts with two consecutive
    # quotation marks, the literal was NOT closed -- the column-72 quote and
    # the first of the pair are one doubled (escaped) quote, the value gets
    # a single quotation mark, and the literal carries on.
    closing_quote_at_72: str | None = None
    # Blanks owed to a literal left open on a line shorter than column 72
    # (see _literal_pad); paid only if a continuation record resumes it.
    literal_pad = ""
    # One-code-line lookahead for the comment/blank branches: the index of
    # the next program-text line after the one being examined, and whether
    # it is a continuation record. IBM: a continuation line is "the next
    # line that is neither a comment line nor a blank line", for ANY
    # continued text -- not only an open literal -- so a word split across
    # a comment (``MOVE WS-CO`` / ``* note`` / ``-    UNT TO X``) must rejoin.
    next_code_idx = -1
    next_code_is_cont = False
    # Whether this file stamps a numeric identification code into columns
    # 73-80 (see _has_identification_stamp_convention). None until the first
    # line that would warn about a short all-digit tail asks for it -- the
    # answer is a whole-file property, so it is computed once and reused.
    stamps_identification_area: bool | None = None
    # ``>>SOURCE FORMAT IS FREE`` switches every later line to free format
    # (no sequence area, no indicator column, no column-72 limit) until a
    # ``>>SOURCE FORMAT IS FIXED`` switches back. A free-format line is its
    # own logical line and is passed through whole; the directive record
    # itself becomes a blank placeholder, so line numbers are unchanged.
    free_mode = False

    def _is_comment_indicator(ch: str) -> bool:
        return (
            ch in COMMENT_INDICATORS
            or (debug_lines_as_comments and ch in DEBUG_INDICATORS)
            or (version_tag_lines_as_comments and ch in VERSION_TAG_INDICATORS)
        )

    def _continuation_follows(idx: int) -> bool:
        """True when the next program-text line after physical index
        *idx* has ``-`` in its indicator column. Cached, so a run of
        comment lines ahead of one continuation costs one scan, not one
        per comment line."""
        nonlocal next_code_idx, next_code_is_cont
        if next_code_idx <= idx:
            next_code_idx = len(lines)
            next_code_is_cont = False
            for j in range(idx + 1, len(lines)):
                candidate = lines[j].rstrip("\n").expandtabs(8)
                if len(candidate) < TEXT_START_COL - 1:
                    continue
                ind = (
                    candidate[INDICATOR_COL - 1]
                    if len(candidate) >= INDICATOR_COL
                    else " "
                )
                if _is_comment_indicator(ind):
                    continue
                next_code_idx = j
                next_code_is_cont = ind == "-"
                break
        return next_code_is_cont

    def _update_quote_state(text: str) -> None:
        """Incrementally update quote state for new text chunk.

        Outside a literal, a ``*>`` inline comment runs to end of line, so a
        quote after it is comment text, not a literal opening -- scanning
        stops there. Inside a literal ``*>`` is just literal text.
        """
        nonlocal _quote_open, _quote_ch, pending_literal, quote_char
        if not text:
            pending_literal = _quote_open
            quote_char = _quote_ch
            return

        if not _quote_open:
            first_single = text.find("'")
            first_double = text.find('"')

            if first_single == -1 and first_double == -1:
                pending_literal = False
                quote_char = None
                return

            if first_single == -1:
                i = first_double
            elif first_double == -1:
                i = first_single
            else:
                i = min(first_single, first_double)

            comment_at = text.find("*>")
            if comment_at != -1 and comment_at < i:
                pending_literal = False
                quote_char = None
                return
        else:
            i = 0

        n = len(text)
        while i < n:
            ch = text[i]
            if _quote_open:
                if ch == _quote_ch:
                    if i + 1 < n and text[i + 1] == _quote_ch:
                        i += 2  # escaped quote
                        continue
                    _quote_open = False
                    _quote_ch = None
                i += 1
            else:
                if ch in ("'", '"'):
                    _quote_open = True
                    _quote_ch = ch
                    i += 1
                elif ch == "*" and i + 1 < n and text[i + 1] == ">":
                    break  # inline comment: nothing after it can open a literal
                else:
                    i += 1
        pending_literal = _quote_open
        quote_char = _quote_ch

    def flush_parts() -> None:
        nonlocal parts, has_line, deferred, literal_suspended
        nonlocal _quote_open, _quote_ch, pending_literal, quote_char
        # A logical line that was actually started (has_line) must always get
        # a result entry, even when its merged text is empty -- e.g. a
        # full-width blank line (all-whitespace program text, non-comment
        # indicator). Silently skipping it here (the pre-fix `if combined:`
        # guard) shifted every later line's number, exactly like the
        # already-fixed short-line/comment-line cases below, but only when
        # nothing else on the line ever produced non-blank text.
        if has_line:
            result.append("".join(parts))
        if deferred:
            # One placeholder per physical line merged into (or deferred
            # behind) the logical line just written.
            result.extend([""] * deferred)
            deferred = 0
        parts = []
        has_line = False
        literal_suspended = False
        # Reset quote state for new logical line
        _quote_open = False
        _quote_ch = None
        pending_literal = False
        quote_char = None

    for line_no, raw in enumerate(lines, start=1):
        if free_mode:
            text = raw.rstrip("\r\n")
            flush_parts()
            closing_quote_at_72 = None
            directive = source_format_directive(text) if ">>" in text else None
            if directive is not None:
                free_mode = directive == "FREE"
                result.append("")
            else:
                result.append(text.rstrip())
            continue
        line = raw.rstrip("\n").expandtabs(8)
        if ">>" in line:
            # Columns 7-72: a directive may start in the indicator column.
            directive = source_format_directive(line[INDICATOR_COL - 1 : TEXT_END_COL])
            if directive is not None:
                flush_parts()
                closing_quote_at_72 = None
                free_mode = directive == "FREE"
                result.append("")
                continue
        if len(line) < TEXT_START_COL - 1:
            # Blank/short line. When a literal is open it may legitimately
            # sit between a continued line and its continuation: keep the
            # logical line pending and owe a placeholder for this record.
            # Otherwise flush whatever logical line was in progress, then
            # emit an empty placeholder for this physical line so later
            # lines keep their true line number (a dropped line here would
            # silently shift every subsequent error/warning location).
            if pending_literal and merge_continued_literals and has_line:
                deferred += 1
                literal_suspended = True
                continue
            if has_line and _continuation_follows(line_no - 1):
                deferred += 1
                continue
            flush_parts()
            result.append("")
            continue
        indicator = line[INDICATOR_COL - 1] if len(line) >= INDICATOR_COL else " "
        text_slice = line[TEXT_START_COL - 1 : TEXT_END_COL]
        is_debug_comment = debug_lines_as_comments and indicator in DEBUG_INDICATORS
        is_version_tag_comment = (
            version_tag_lines_as_comments and indicator in VERSION_TAG_INDICATORS
        )
        if (
            indicator in COMMENT_INDICATORS
            or is_debug_comment
            or is_version_tag_comment
        ):  # comment (incl. page eject, debug lines, version-tag lines)
            # Comment lines: do not emit comment text (emitting it would let
            # the free-form lexer tokenize it as code), but still account
            # for the physical line with an empty placeholder. A comment
            # interrupting an open continued literal does not sever it --
            # the placeholder is deferred behind the logical line instead.
            if pending_literal and merge_continued_literals and has_line:
                deferred += 1
                literal_suspended = True
                continue
            if has_line and _continuation_follows(line_no - 1):
                deferred += 1
                continue
            flush_parts()
            result.append("")
            continue

        if warnings is not None and len(line) > TEXT_END_COL:
            seq_area = line[:DEFAULT_SEQ_COL_END]
            has_sequence_number = seq_area.strip() != "" and seq_area.strip().isdigit()
            if not has_sequence_number:
                before, after = line[TEXT_END_COL - 1], line[TEXT_END_COL]
                mid_token = not before.isspace() and not after.isspace()
                content_len = len(line.rstrip())
                exceeds_traditional_width = content_len > IDENTIFICATION_END_COL
                dropped = line[TEXT_END_COL:].rstrip()
                # A purely-numeric tail that fills the traditional 80-column
                # identification area (columns 73-80) EXACTLY is a per-line
                # sequence/change-tracking stamp -- e.g. IBM Z Open Editor/
                # ISPF-style auto numbering (03050009, incrementing on every
                # line, always writing the full 8-column field) -- not a
                # token that was actually split. Unlike the columns-1-6 gate
                # above, this doesn't require the *whole file* to carry
                # sequence numbers there; it trusts the shape of the dropped
                # content itself, so the shape requirement is strict: the
                # line must span the full 80 columns with digits from 73
                # through 80. A shorter all-digit tail (a data name's own
                # trailing digits spilling a few columns past 72 on a
                # 75-column line) does NOT qualify and warns as the
                # mid-token truncation it really is, and a mixed
                # alnum+punctuation tail (e.g. the NIST-style `IX2094.2`
                # test-case id already covered by
                # test_blank_sequence_area_with_same_shape_still_warns)
                # fails the stamp shape -- both keep warning exactly as
                # before. The shape itself allows blanks *between* digits
                # (`01636  0`), because a change-control tool lays the
                # identification field out in fixed sub-fields -- see
                # _is_numeric_id_stamp_text.
                is_numeric_id_stamp = (
                    content_len == IDENTIFICATION_END_COL
                    and _is_numeric_id_stamp_text(dropped)
                )
                # A *shorter* stamp-shaped tail is the same convention whenever
                # the file itself proves it uses one -- a shop's
                # change-tracking stamp (Panvalet/Librarian/Endevor and
                # friends) is commonly 4-6 digits at column 73, not the full
                # 8-column field, and jumps around non-sequentially rather
                # than counting lines. Per line that is indistinguishable
                # from a data name's own trailing digits getting cut, which
                # is why the rule above demands the full width; across the
                # file it is not, so the question is asked of the file. See
                # _has_identification_stamp_convention.
                is_short_id_stamp = (
                    not is_numeric_id_stamp
                    and content_len <= IDENTIFICATION_END_COL
                    and _is_numeric_id_stamp_text(dropped)
                )
                # A dropped tail that is *only* the statement-terminating
                # period (nothing else survives the rstrip) never corrupts a
                # token: whatever ended at column 72 -- most commonly a
                # string literal's closing quote in a banner-style VALUE
                # clause -- closed cleanly, and the period is a separate,
                # single-character token the parser already tolerates
                # missing entirely (PROGRAM-ID, MOVE, and every other
                # statement recover from a missing terminator). Flagging
                # this as a "mid-token" split is misleading -- nothing was
                # split -- and floods well-formed source whose closing quote
                # merely lands on column 72 with a spurious warning.
                is_bare_terminal_period = dropped == "."
                if mid_token and is_short_id_stamp:
                    # Only now is the whole-file scan worth its cost: a file
                    # with no such line never pays for it, and one that has
                    # them pays once.
                    if stamps_identification_area is None:
                        stamps_identification_area = (
                            _has_identification_stamp_convention(lines)
                        )
                    if stamps_identification_area:
                        is_numeric_id_stamp = True
                if (
                    mid_token
                    and not is_numeric_id_stamp
                    and not is_bare_terminal_period
                ):
                    warnings.append(
                        f"Line {line_no}: content beyond column {TEXT_END_COL} "
                        f"was dropped mid-token: {dropped!r}"
                    )
                elif exceeds_traditional_width:
                    warnings.append(
                        f"Line {line_no}: content beyond column {TEXT_END_COL} "
                        f"was dropped -- line is {content_len} columns wide, "
                        f"past the traditional {IDENTIFICATION_END_COL}-column "
                        f"identification-area width: {dropped!r}"
                    )

        is_cont = indicator == "-"

        # Handle continuation lines
        if is_cont:
            # This is a continuation line - merge with previous buffer. It
            # is still one physical line, so it owes one placeholder behind
            # the logical line it joins (an orphan continuation with nothing
            # to join starts the logical line itself and owes none).
            if has_line:
                deferred += 1
            literal_suspended = False
            lead = text_slice.lstrip()
            if (
                merge_continued_literals
                and not pending_literal
                and closing_quote_at_72 is not None
                and lead.startswith(closing_quote_at_72 * 2)
            ):
                # Column-72 quote + a continuation opening with two quotes:
                # the literal never closed (see closing_quote_at_72). Re-open
                # it, keep one of the pair so the joined text reads as the
                # doubled quote it is, and scan on from the second.
                _quote_open = True
                _quote_ch = closing_quote_at_72
                rest = lead[2:]
                _update_quote_state(rest)
                parts.append(closing_quote_at_72 + rest)
                if not pending_literal:
                    parts[-1] = parts[-1].rstrip()
            elif pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and chunk[0] == quote_char:
                    chunk = chunk[1:]
                _update_quote_state(chunk)
                # Trailing blanks up to column 72 are part of a literal's
                # value when it remains open at end of line (COBOL
                # fixed-format continuation rule) -- only strip them once
                # we know no literal is left dangling (M5).
                out_chunk = chunk if pending_literal else chunk.rstrip()
                # The continued record's missing columns first: they sit
                # inside the literal, ahead of the resumed text.
                parts.append(literal_pad + out_chunk)
            else:
                # Non-literal continuation: '-' in column 7 with no
                # alphanumeric literal currently open. Per COBOL fixed-format
                # rules the first non-blank character of the continuation line
                # is the successor of the last non-blank character of the
                # continued line, with NO intervening space. This is how a
                # numeric literal (or a word) split mid-token across lines
                # rejoins — e.g. '-999.777' written one character per line.
                # Strip both ends so the chunk butts directly onto the buffer
                # instead of injecting a space that would break the token.
                stripped = text_slice.strip()
                parts.append(stripped)
                if merge_continued_literals:
                    _update_quote_state(stripped)
        else:
            # Non-continuation line - start new logical line
            flush_parts()
            if merge_continued_literals:
                _update_quote_state(text_slice)
                # Same M5 fix as the continuation branch above: only strip
                # trailing blanks once we know no literal is left open.
                chunk = text_slice if pending_literal else text_slice.rstrip()
            else:
                chunk = text_slice.rstrip()
            parts.append(chunk)

        # Remember a literal closed exactly in column 72 for the next
        # continuation record (see closing_quote_at_72). A quote there with
        # no literal left open can only be a closing one: an opening quote
        # would leave pending_literal set, and a doubled pair straddling
        # columns 71-72 inside a literal likewise.
        closing_quote_at_72 = (
            text_slice[-1]
            if (
                merge_continued_literals
                and not pending_literal
                and len(text_slice) == TEXT_END_COL - TEXT_START_COL + 1
                and text_slice[-1] in ("'", '"')
            )
            else None
        )

        # A literal still open here runs through column 72; if this record
        # stops short of it (trailing blanks stripped), the next
        # continuation owes the literal those blanks.
        literal_pad = (
            _literal_pad(text_slice)
            if merge_continued_literals and pending_literal
            else ""
        )

        # Either branch above always appends to `parts` (even an empty
        # string), so this physical line has real content pending flush.
        has_line = True

    # Save state before final flush
    final_pending_literal = pending_literal and not literal_suspended
    final_quote_char = quote_char
    flush_parts()

    # If pending_literal is True at EOF there is no subsequent continuation line,
    # so the string is genuinely unterminated.
    if final_pending_literal and merge_continued_literals:
        raise ValueError(
            f"Unterminated string literal at end of input "
            f"(opened with quote character '{final_quote_char or '?'}')"
        )

    return "\n".join(result) + "\n"


# ---------------------------------------------------------------------------
# Conditional-compilation condition evaluator (>>IF / >>WHEN / >>EVALUATE)
# ---------------------------------------------------------------------------


class _ConditionSyntaxError(Exception):
    """Raised when a >>IF/>>WHEN condition cannot be tokenized or parsed."""


class _UndefinedSymbolError(Exception):
    """Raised when a condition references a symbol that is not defined."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


_COND_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<op>>=|<=|<>|=|>|<)
    | (?P<boollit>B'[01]'|B"[01]")
    | (?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")
    | (?P<number>[-+]?\d+(?:\.\d+)?)
    | (?P<word>[A-Z_][A-Z0-9_-]*)
    | (?P<arith>[-+*/])
    """,
    re.VERBOSE,
)

# >>DIRECTIVE-NAME [rest-of-line]
_DIRECTIVE_LINE_RE = re.compile(r"^>>\s*([A-Z][A-Z0-9-]*)(?:\s+(.*?))?\s*$")

_OPERAND_KINDS = frozenset({"word", "string", "number", "boollit"})

#: Words a condition gives meaning to; never a compile-time arithmetic
#: operand after the first (so ``X = 1 AND Y`` is not read as an expression).
_CONDITION_KEYWORDS = frozenset(
    {
        "AND",
        "OR",
        "NOT",
        "IS",
        "DEFINED",
        "GREATER",
        "LESS",
        "EQUAL",
        "THAN",
        "TO",
        "TRUE",
        "FALSE",
        "THRU",
        "THROUGH",
        "OTHER",
    }
)


def _strip_directive_comment(text: str) -> str:
    """Drop a ``*>`` floating comment from a ``>>`` directive line.

    Outside a literal, ``*>`` starts a comment that runs to end of line, on
    a directive line as on any other. Left in place it became part of the
    directive: ``>>DEFINE DEBUG AS 1 *> on`` defined DEBUG as ``1 *> ON``
    (so a later ``>>IF DEBUG = 1`` was silently false), and ``>>IF ...
    *> why`` / ``>>WHEN OTHER *> x`` failed to parse. Inside a quoted
    literal ``*>`` is literal text and is kept.
    """
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote is not None:
            if ch == quote:
                quote = None  # a doubled quote reopens on the next char
        elif ch in ("'", '"'):
            quote = ch
        elif text.startswith("*>", i):
            return text[:i].rstrip()
    return text


def _strip_quotes(text: str) -> str:
    """Strip one pair of matching surrounding quotes, if present.

    A doubled delimiter inside the literal stands for one occurrence of it
    (``'O''BRIEN'`` is ``O'BRIEN``), as in any COBOL literal.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        quote = text[0]
        return text[1:-1].replace(quote * 2, quote)
    return text


def _upper_outside_literals(text: str) -> str:
    """Upper-case *text* except the contents of quoted literals.

    Directive keywords and compilation-variable names are case-insensitive,
    but a literal's contents are not: ``>>DEFINE X AS 'abc'`` then ``>>IF X
    = 'ABC'`` is FALSE. Upper-casing the whole directive line made it TRUE.
    A doubled delimiter inside a literal is kept as literal text.
    """
    out: list[str] = []
    quote: str | None = None
    start = 0
    for i, ch in enumerate(text):
        if quote is None:
            if ch in ("'", '"'):
                out.append(text[start:i].upper())
                quote = ch
                start = i
        elif ch == quote:
            # A doubled delimiter closes and immediately reopens: the
            # contents between are still literal text either way.
            out.append(text[start : i + 1])
            quote = None
            start = i + 1
    tail = text[start:]
    out.append(tail if quote is not None else tail.upper())
    return "".join(out)


_DEFINE_ARITH_TOKEN_RE = re.compile(r"\s*(?:([A-Za-z0-9][\w-]*)|([-+*/()]))")


def _eval_define_arithmetic(text: str, defined: Mapping[str, str]) -> int | None:
    """Value of a ``>>DEFINE name AS arithmetic-expression`` operand.

    IBM allows ``>>DEFINE V AS 2 + 1`` / ``AS MAX-ROWS * 2``: integer
    literals and already-defined compilation variables combined with
    ``+ - * /`` and parentheses. Returns ``None`` when *text* is not such an
    expression or cannot be evaluated exactly (an undefined or non-integer
    operand, an inexact division) -- the caller then keeps the raw text.
    Before this the raw text was stored verbatim, so ``>>IF V = 3`` compared
    against ``"2 + 1"`` and was silently FALSE.
    """
    tokens: list[str] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        match = _DEFINE_ARITH_TOKEN_RE.match(text, pos)
        if match is None:
            return None
        tokens.append((match.group(1) or match.group(2)).upper())
        pos = match.end()
    if not any(tok in "+-*/" for tok in tokens):
        return None  # a plain literal or word, not an expression

    index = 0

    def _peek() -> str | None:
        return tokens[index] if index < len(tokens) else None

    def _next() -> str | None:
        nonlocal index
        tok = _peek()
        index += 1
        return tok

    def _primary() -> int | None:
        tok = _next()
        if tok is None:
            return None
        if tok in ("+", "-"):
            value = _primary()
            return None if value is None else (value if tok == "+" else -value)
        if tok == "(":
            value = _sum()
            return value if _next() == ")" else None
        if tok.isdigit():
            return int(tok)
        symbol_value = defined.get(tok)
        if symbol_value is None:
            return None
        symbol_value = symbol_value.strip()
        if symbol_value.lstrip("+-").isdigit():
            return int(symbol_value)
        return None

    def _product() -> int | None:
        value = _primary()
        while value is not None and _peek() in ("*", "/"):
            op = _next()
            rhs = _primary()
            if rhs is None:
                return None
            if op == "*":
                value *= rhs
            elif rhs == 0 or value % rhs:
                return None  # division by zero / inexact: do not guess
            else:
                value //= rhs
        return value

    def _sum() -> int | None:
        value = _product()
        while value is not None and _peek() in ("+", "-"):
            op = _next()
            rhs = _product()
            if rhs is None:
                return None
            value = value + rhs if op == "+" else value - rhs
        return value

    result = _sum()
    return result if index == len(tokens) else None


#: A COBOL numeric literal (what a directive compares numerically). Plain
#: ``float()`` also accepts ``nan`` / ``inf`` / ``Infinity`` / ``1_000`` / ``1e3``,
#: so ``>>DEFINE X AS 'nan'`` made ``>>IF X = 'nan'`` FALSE (NaN never equals
#: itself) and ``'INF' = 'Infinity'`` TRUE.
_DIRECTIVE_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def _try_number(text: str) -> float | None:
    """Return the numeric value of *text*, or None if it is not numeric."""
    stripped = text.strip()
    if _DIRECTIVE_NUMBER_RE.fullmatch(stripped) is None:
        return None
    return float(stripped)


def _values_equal(left: str, right: str) -> bool:
    """Compare two resolved values: numerically when both are numeric,
    otherwise as strings. Case matters -- a literal's contents are never
    folded (keywords and symbol names already are, before this is reached).
    """
    ln, rn = _try_number(left), _try_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    return left == right


def _tokenize_condition(text: str) -> list[tuple[str, str]]:
    """Tokenize a constant conditional expression (already uppercased)."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _COND_TOKEN_RE.match(text, pos)
        if match is None:
            raise _ConditionSyntaxError(f"unexpected character {text[pos]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind is None or kind == "ws":
            continue
        tokens.append((kind, match.group()))
    return tokens


class _ConditionParser:
    """Recursive-descent evaluator for constant conditional expressions.

    Grammar (a practical subset of IBM Enterprise COBOL conditional
    compilation conditions)::

        expression := and-expr ( OR and-expr )*
        and-expr   := not-expr ( AND not-expr )*
        not-expr   := NOT not-expr | primary
        primary    := '(' expression ')'
                    | DEFINED '(' symbol ')'
                    | operand IS [NOT] DEFINED
                    | operand [IS [NOT]] relop operand
                    | operand                    -- interpreted as a boolean
        relop      := = | <> | > | < | >= | <=
                    | GREATER [THAN] [OR EQUAL [TO]]
                    | LESS [THAN] [OR EQUAL [TO]]
                    | EQUAL [TO]
        operand    := 'string' | "string" | B'0' | B'1' | TRUE | FALSE
                    | arith      -- integers / symbols with + - * / ( )

    A compile-time arithmetic operand (``X + 1``) is evaluated exactly as
    ``>>DEFINE ... AS`` evaluates one (``_eval_define_arithmetic``), so the
    two directives agree. Word-form operators and arithmetic used to be
    "unsupported ... treated as FALSE", compiling the wrong branch (#512).
    """

    def __init__(self, tokens: list[tuple[str, str]], defined: dict[str, str]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._defined = defined

    def parse(self) -> bool:
        value = self._parse_or()
        if self._pos != len(self._tokens):
            raise _ConditionSyntaxError(
                f"unexpected trailing token {self._tokens[self._pos][1]!r}"
            )
        return value

    # -- token helpers ----------------------------------------------------

    def _peek(self, offset: int = 0) -> tuple[str, str] | None:
        index = self._pos + offset
        return self._tokens[index] if index < len(self._tokens) else None

    def _advance(self) -> tuple[str, str]:
        token = self._peek()
        if token is None:
            raise _ConditionSyntaxError("unexpected end of condition")
        self._pos += 1
        return token

    def _match_word(self, *words: str) -> str | None:
        token = self._peek()
        if token is not None and token[0] == "word" and token[1] in words:
            self._pos += 1
            return token[1]
        return None

    def _match_op(self) -> str | None:
        """A relational operator, symbolic or in its word form."""
        token = self._peek()
        if token is not None and token[0] == "op":
            self._pos += 1
            return token[1]
        if self._match_word("EQUAL"):
            self._match_word("TO")
            return "="
        word = self._match_word("GREATER", "LESS")
        if word is None:
            return None
        self._match_word("THAN")
        op = ">" if word == "GREATER" else "<"
        # ``OR EQUAL [TO]`` belongs to the operator; any other OR is boolean.
        if self._peek() == ("word", "OR") and self._peek(1) == ("word", "EQUAL"):
            self._pos += 2
            self._match_word("TO")
            op += "="
        return op

    def _follows_operand(self) -> bool:
        """Whether the next token continues a comparison whose left operand
        just ended: a relational operator (or IS / NOT before one), or an
        arithmetic operator extending the operand."""
        token = self._peek()
        return token is not None and (
            token[0] in ("op", "arith")
            or (token[0] == "number" and token[1][0] in "+-")
            or token in (("word", "IS"), ("word", "NOT"))
            or token in (("word", "GREATER"), ("word", "LESS"), ("word", "EQUAL"))
        )

    # -- grammar ----------------------------------------------------------

    def _parse_or(self) -> bool:
        value = self._parse_and()
        while self._match_word("OR"):
            rhs = self._parse_and()
            value = value or rhs
        return value

    def _parse_and(self) -> bool:
        value = self._parse_not()
        while self._match_word("AND"):
            rhs = self._parse_not()
            value = value and rhs
        return value

    def _parse_not(self) -> bool:
        if self._match_word("NOT"):
            return not self._parse_not()
        return self._parse_primary()

    def _parse_primary(self) -> bool:
        token = self._peek()
        if token is None:
            raise _ConditionSyntaxError("unexpected end of condition")
        kind, text = token

        if kind == "lparen":
            start = self._pos
            try:
                self._advance()
                value = self._parse_or()
                closing = self._peek()
                if closing is None or closing[0] != "rparen":
                    raise _ConditionSyntaxError("missing closing parenthesis")
                self._advance()
                if not self._follows_operand():
                    return value
            except (_ConditionSyntaxError, _UndefinedSymbolError):
                pass
            # Not a parenthesized condition: an arithmetic operand such as
            # ``(X + 1) * 2 = 16``. Re-read it as one.
            self._pos = start

        # DEFINED(symbol) function form
        if kind == "word" and text == "DEFINED":
            after = self._peek(1)
            if after is not None and after[0] == "lparen":
                self._advance()  # DEFINED
                self._advance()  # (
                name_token = self._advance()
                if name_token[0] != "word":
                    raise _ConditionSyntaxError(
                        f"expected symbol name in DEFINED(...), got "
                        f"{name_token[1]!r}"
                    )
                closing = self._advance()
                if closing[0] != "rparen":
                    raise _ConditionSyntaxError("missing ')' after DEFINED(symbol")
                return name_token[1] in self._defined

        operand = self._parse_operand()

        # operand [IS] [NOT] DEFINED | operand [IS] [NOT] <op> operand.
        # IBM's diagram makes IS optional in both forms (``>>IF DEBUG
        # DEFINED`` is legal), so it is matched and then ignored; NOT is
        # what carries meaning.
        has_is = self._match_word("IS") is not None
        negate = self._match_word("NOT") is not None
        if self._match_word("DEFINED"):
            if operand[0] != "word":
                raise _ConditionSyntaxError(
                    "only a symbol name can be tested with [IS] [NOT] DEFINED"
                )
            exists = operand[1] in self._defined
            return not exists if negate else exists

        op = self._match_op()
        if op is None:
            if has_is or negate:
                keyword = "NOT" if negate else "IS"
                raise _ConditionSyntaxError(
                    f"expected DEFINED or a comparison operator after {keyword}"
                )
            return self._truthy(operand)
        result = self._compare(operand, op, self._parse_operand())
        return not result if negate else result

    def _parse_operand(self) -> tuple[str, str]:
        token = self._peek()
        if token is not None and token[0] in ("string", "boollit"):
            self._pos += 1
            return token
        parts = self._arith_parts()
        atoms = [part for part in parts if part[0] not in ("lparen", "rparen")]
        if len(atoms) == 1 and atoms[0][0] != "arith":
            return atoms[0]  # ``X`` or ``(X)``
        # A compile-time arithmetic expression: evaluated the way >>DEFINE
        # ... AS evaluates one, to an integer operand.
        for kind, text in parts:
            if kind == "word" and text not in self._defined:
                raise _UndefinedSymbolError(text)
        value = _eval_define_arithmetic(
            " ".join(text for _kind, text in parts), self._defined
        )
        if value is None:
            raise _ConditionSyntaxError(
                "arithmetic operand is not an exact integer expression"
            )
        return ("number", str(value))

    def _arith_parts(self) -> list[tuple[str, str]]:
        """The tokens of one operand: a single symbol / number / TRUE /
        FALSE, or an arithmetic expression over integers and symbols."""
        parts: list[tuple[str, str]] = []
        depth = 0
        expect_atom = True
        token = self._peek()
        while token is not None:
            kind, text = token
            if expect_atom:
                if kind == "arith" and text in "+-":
                    parts.append(token)  # unary sign
                elif kind == "lparen":
                    depth += 1
                    parts.append(token)
                elif kind == "number" or (
                    kind == "word" and (text not in _CONDITION_KEYWORDS or not parts)
                ):
                    parts.append(token)
                    expect_atom = False
                else:
                    break
            elif kind == "arith":
                parts.append(token)
                expect_atom = True
            elif kind == "number" and text[0] in "+-":
                # ``X -1`` / ``X+1``: the tokenizer read the sign into the
                # number; between two operands it is the binary operator.
                parts.extend([("arith", text[0]), ("number", text[1:])])
            elif kind == "rparen" and depth:
                depth -= 1
                parts.append(token)
            else:
                break
            self._pos += 1
            token = self._peek()
        if not parts or expect_atom or depth:
            found = "end of condition" if token is None else repr(token[1])
            raise _ConditionSyntaxError(f"expected an operand, got {found}")
        return parts

    # -- evaluation -------------------------------------------------------

    def _resolve(self, operand: tuple[str, str]) -> str:
        kind, text = operand
        if kind == "word":
            if text in ("TRUE", "FALSE"):
                return text
            if text in self._defined:
                return self._defined[text]
            raise _UndefinedSymbolError(text)
        if kind == "string":
            return _strip_quotes(text)
        if kind == "boollit":
            return "TRUE" if text[2] == "1" else "FALSE"
        return text  # number

    def _compare(self, left: tuple[str, str], op: str, right: tuple[str, str]) -> bool:
        lv, rv = self._resolve(left), self._resolve(right)
        ln, rn = _try_number(lv), _try_number(rv)
        lc: float | str
        rc: float | str
        if ln is not None and rn is not None:
            lc, rc = ln, rn
        else:
            lc, rc = lv, rv
        if op == "=":
            return lc == rc
        if op == "<>":
            return lc != rc
        if op == ">":
            return lc > rc  # type: ignore[operator]
        if op == "<":
            return lc < rc  # type: ignore[operator]
        if op == ">=":
            return lc >= rc  # type: ignore[operator]
        return lc <= rc  # type: ignore[operator]

    def _truthy(self, operand: tuple[str, str]) -> bool:
        kind, text = operand
        if kind == "string":
            raise _ConditionSyntaxError(
                f"string literal {text} is not a boolean condition"
            )
        value = self._resolve(operand)
        number = _try_number(value)
        if number is not None:
            return number != 0
        return value.upper() not in ("FALSE", "B'0'", 'B"0"', "")


def _evaluate_condition(
    condition_text: str,
    defined: dict[str, str],
    warn: Callable[[str], None],
    line_no: int,
    directive: str,
) -> bool:
    """Evaluate a >>IF / >>WHEN condition, degrading to False with a warning.

    Degradation rules (documented behavior):

    - A condition that references an **undefined symbol** (outside of an
      ``IS [NOT] DEFINED`` / ``DEFINED(...)`` test) is treated as FALSE and
      a warning is recorded.
    - A condition that cannot be **parsed** is treated as FALSE (the guarded
      block is blanked out) and a warning is recorded.
    """
    try:
        tokens = _tokenize_condition(condition_text)
        return _ConditionParser(tokens, defined).parse()
    except _UndefinedSymbolError as exc:
        warn(
            f"Line {line_no}: {directive} condition '{condition_text}' "
            f"references undefined symbol '{exc.name}' — condition treated "
            "as FALSE"
        )
        return False
    except _ConditionSyntaxError as exc:
        warn(
            f"Line {line_no}: unsupported {directive} condition "
            f"'{condition_text}' ({exc}) — condition treated as FALSE "
            "(guarded lines blanked out)"
        )
        return False


def _coerce_symbol_value(value: str | int | float | bool) -> str:
    """Normalize a caller-supplied symbol value to its string form.

    A quoted value is an alphanumeric literal and keeps its case
    (``"'prod'"`` is ``prod``); an unquoted one is taken as a word, which --
    like a word on a directive line -- is case-insensitive and so folded
    (``"prod"`` is ``PROD``).
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        return _strip_quotes(stripped)
    return stripped.upper()


def _normalize_defined_symbols(
    defined_symbols: Mapping[str, str | int | float | bool] | Iterable[str] | None,
) -> dict[str, str]:
    """Normalize the *defined_symbols* argument into ``{NAME: value}``.

    Accepts a mapping of name -> value (str/int/float/bool), a bare string
    (a single symbol name), or an iterable of symbol names (each defined
    with the default value ``"TRUE"``). Symbol names are uppercased to match
    the case-insensitive handling of directive lines.
    """
    result: dict[str, str] = {}
    if defined_symbols is None:
        return result
    if isinstance(defined_symbols, Mapping):
        for name, value in defined_symbols.items():
            result[str(name).strip().upper()] = _coerce_symbol_value(value)
    elif isinstance(defined_symbols, str):
        result[defined_symbols.strip().upper()] = "TRUE"
    else:
        for name in defined_symbols:
            result[str(name).strip().upper()] = "TRUE"
    return result


def _when_value_matches(
    subject: str, tokens: list[tuple[str, str]], defined: dict[str, str]
) -> bool:
    """Whether a ``>>WHEN`` selection object selects *subject*.

    The object is one literal or symbol, or a range ``low THRU high``
    (``THROUGH``), inclusive -- compared numerically when every value is
    numeric, else as text. A range used to be rejected as "not a single
    literal", so ``>>WHEN 1 THRU 5`` never matched and ``>>WHEN OTHER`` was
    compiled instead.
    """
    resolver = _ConditionParser([], defined)
    if len(tokens) == 1 and tokens[0][0] in _OPERAND_KINDS:
        return _values_equal(subject, resolver._resolve(tokens[0]))
    if (
        len(tokens) == 3
        and tokens[0][0] in _OPERAND_KINDS
        and tokens[1] in (("word", "THRU"), ("word", "THROUGH"))
        and tokens[2][0] in _OPERAND_KINDS
    ):
        low, high = resolver._resolve(tokens[0]), resolver._resolve(tokens[2])
        numbers = [_try_number(v) for v in (subject, low, high)]
        if all(n is not None for n in numbers):
            value, lo, hi = numbers
            return lo <= value <= hi  # type: ignore[operator]
        return low <= subject <= high
    raise _ConditionSyntaxError("expected a literal, a symbol, or a THRU range")


class _CondFrame:
    """One nesting level of >>IF or >>EVALUATE processing."""

    __slots__ = (
        "kind",
        "parent_active",
        "active",
        "branch_taken",
        "eval_cond_mode",
        "eval_cond_negate",
        "eval_subject",
        "eval_subject_valid",
    )

    def __init__(
        self, kind: str, parent_active: bool, active: bool, branch_taken: bool
    ) -> None:
        self.kind = kind  # "if" or "eval"
        self.parent_active = parent_active
        self.active = active
        self.branch_taken = branch_taken
        self.eval_cond_mode = False  # True for >>EVALUATE TRUE / FALSE
        self.eval_cond_negate = False  # True for >>EVALUATE FALSE
        self.eval_subject: str | None = None  # resolved subject value
        self.eval_subject_valid = True  # False -> only >>WHEN OTHER matches


def _fixed_format_directive_text(line: str) -> str | None:
    """The ``>>`` directive a sequence-numbered fixed-format line carries.

    ``line.strip()`` finds a directive only when columns 1-6 are blank; a
    numbered deck (``000400     >>IF DEBUG IS DEFINED``) puts the sequence
    number first. Returns the upper-cased directive text from columns 8-72
    when columns 1-6 look like a sequence area (blank or digits, the
    parser's own strict rule) and column 7 is blank; otherwise ``None``.
    """
    if ">>" not in line or len(line) < TEXT_START_COL:
        return None
    expanded = line.expandtabs(8)
    if len(expanded) < TEXT_START_COL or expanded[INDICATOR_COL - 1] != " ":
        return None
    # Deferred: source_format imports this module at module scope.
    from .source_format import _sequence_area_is_fixed_like

    if not _sequence_area_is_fixed_like(expanded[:DEFAULT_SEQ_COL_END])[0]:
        return None
    text = _upper_outside_literals(expanded[TEXT_START_COL - 1 : TEXT_END_COL].strip())
    return text if text.startswith(">>") else None


def preprocess_conditional_compilation(
    source: str,
    defined_symbols: (
        Mapping[str, str | int | float | bool] | Iterable[str] | None
    ) = None,
    warnings: list[str] | None = None,
    *,
    keep_source_format_directives: bool = False,
    define_log: list[tuple[int, dict[str, str]]] | None = None,
) -> str:
    """
    Process IBM Enterprise COBOL conditional compilation directives.

    Supported directives:

    - ``>>DEFINE symbol [AS value]`` — values may be numeric literals,
      quoted strings, or ``B'0'``/``B'1'``; a bare ``>>DEFINE symbol``
      defines the symbol with the value ``TRUE``
    - ``>>IF condition`` / ``>>ELSE`` / ``>>END-IF`` (nestable)
    - ``>>EVALUATE TRUE`` with condition ``>>WHEN`` branches,
      ``>>EVALUATE symbol-or-literal`` with literal ``>>WHEN`` branches,
      ``>>WHEN OTHER``, ``>>END-EVALUATE`` (nestable, may contain >>IF
      blocks and vice versa)

    ``>>IF`` / ``>>WHEN`` conditions support (see ``_ConditionParser``):

    - ``symbol IS [NOT] DEFINED`` and ``DEFINED(symbol)``
    - comparisons ``=``, ``<>``, ``>``, ``<``, ``>=``, ``<=`` between
      symbols and numeric/string literals (numeric when both sides are
      numeric, otherwise a case-sensitive comparison of literal contents;
      keywords and symbol names are case-insensitive)
    - boolean literals ``B'0'``/``B'1'``, ``TRUE``, ``FALSE``
    - ``AND`` / ``OR`` / ``NOT`` with parentheses

    Degradation rules (all recorded via *warnings*):

    - A condition referencing an **undefined symbol** (outside of an
      ``IS [NOT] DEFINED`` / ``DEFINED(...)`` test) evaluates to FALSE.
    - An **unparseable** condition evaluates to FALSE (the guarded block is
      blanked out).
    - An undefined or unparseable ``>>EVALUATE`` subject means only a
      ``>>WHEN OTHER`` branch can be selected.
    - Stray ``>>ELSE``/``>>END-IF``/``>>WHEN``/``>>END-EVALUATE`` are
      ignored; unclosed ``>>IF``/``>>EVALUATE`` at end of input warn.
    - Any other ``>>`` directive is blanked out with a warning (it is a
      compiler directive, never program text).

    Args:
        source: COBOL source code containing directives
        defined_symbols: Pre-defined symbols. Either a mapping of symbol
            name to value (str, int, float, or bool — bools become
            ``TRUE``/``FALSE``), or an iterable of symbol names (each
            defined as ``TRUE``). Names are matched case-insensitively.
        warnings: Optional list that receives diagnostics (see the
            degradation rules above); the function never raises for
            malformed directives.
        define_log: When a list is given, it receives ``(0, symbols)`` for
            the symbols in effect before line 1 and then ``(line, symbols)``
            after every active ``>>DEFINE`` -- the symbol table as it stands
            from that line on. The copybook expander reads it to hand each
            ``COPY`` the symbols defined *above* it, so a ``>>DEFINE`` in a
            program is in effect inside the copybooks it copies afterwards.
        keep_source_format_directives: Leave an active ``>>SOURCE FORMAT``
            directive line in place (unwarned) instead of blanking it, for a
            caller that runs this *before* ``normalize_fixed_format`` -- the
            copybook expander -- so the normalizer still sees where the
            reference format switches.

    Returns:
        Source code with conditional sections processed. Directive lines and
        lines inside a skipped block are blanked out rather than removed, so
        every surviving line keeps its original line number for
        error/warning reporting.

    Example:
        >>> source = '>>DEFINE DEBUG\\n>>IF DEBUG IS DEFINED\\n       DISPLAY "Debug mode".\\n>>END-IF\\n'
        >>> preprocess_conditional_compilation(source)
        '\\n\\n       DISPLAY "Debug mode".\\n'
    """
    defined = _normalize_defined_symbols(defined_symbols)
    if define_log is not None:
        define_log.append((0, dict(defined)))
    result_lines: list[str] = []
    frames: list[_CondFrame] = []

    def _warn(message: str) -> None:
        if warnings is not None:
            warnings.append(message)

    def _active() -> bool:
        return all(frame.active for frame in frames)

    for line_no, line in enumerate(split_source_lines(source), start=1):
        stripped = _upper_outside_literals(line.strip())
        if not stripped.startswith(">>"):
            # A directive in a sequence-numbered fixed-format line
            # (``000400     >>IF ...``) starts at column 8, not column 1.
            fixed_text = _fixed_format_directive_text(line)
            if fixed_text is not None:
                stripped = fixed_text

        if stripped.startswith(">>"):
            stripped = _strip_directive_comment(stripped)
        directive_match = (
            _DIRECTIVE_LINE_RE.match(stripped) if stripped.startswith(">>") else None
        )
        name = directive_match.group(1) if directive_match else None
        rest = (
            (directive_match.group(2) or "").strip()
            if directive_match is not None
            else ""
        )

        # >>DEFINE symbol [AS value] — honored only in an active region.
        if name == "DEFINE":
            match = _DEFINE_RE.match(stripped)
            if match:
                if _active():
                    symbol = match.group(1)
                    raw_value = match.group(2)
                    if raw_value is None:
                        defined[symbol] = "TRUE"
                    elif raw_value.upper() == "OFF":
                        # IBM: ``>>DEFINE name [AS] OFF`` undefines it.
                        defined.pop(symbol, None)
                    elif raw_value.upper() == "PARAMETER":
                        # IBM: the value comes from the DEFINE compiler
                        # option -- here, the caller's defined_symbols.
                        if symbol not in defined:
                            _warn(
                                f"Line {line_no}: >>DEFINE {symbol} AS "
                                "PARAMETER takes its value from the caller's "
                                "defined symbols, which do not define it — "
                                "left undefined"
                            )
                    else:
                        arith_value = _eval_define_arithmetic(raw_value, defined)
                        defined[symbol] = (
                            str(arith_value)
                            if arith_value is not None
                            else _strip_quotes(raw_value)
                        )
                    if define_log is not None:
                        define_log.append((line_no, dict(defined)))
            else:
                _warn(
                    f"Line {line_no}: malformed >>DEFINE directive "
                    f"'{line.strip()}' ignored — no symbol was defined"
                )
            # A directive line consumes no output, but still occupies a
            # source line: emit a blank placeholder so later lines keep
            # their true line number instead of silently shifting.
            result_lines.append("")
            continue

        # >>IF condition
        elif name == "IF":
            parent_active = _active()
            if parent_active:
                condition = _evaluate_condition(rest, defined, _warn, line_no, ">>IF")
            else:
                condition = False
            frames.append(
                _CondFrame(
                    "if",
                    parent_active,
                    active=parent_active and condition,
                    # In an inactive region no branch (including >>ELSE)
                    # may ever activate.
                    branch_taken=condition if parent_active else True,
                )
            )
            result_lines.append("")
            continue

        # >>ELSE
        elif name == "ELSE":
            if frames and frames[-1].kind == "if":
                frame = frames[-1]
                frame.active = frame.parent_active and not frame.branch_taken
                frame.branch_taken = True
            else:
                _warn(f"Line {line_no}: >>ELSE without a matching >>IF ignored")
            result_lines.append("")
            continue

        # >>END-IF
        elif name == "END-IF":
            if frames and frames[-1].kind == "if":
                frames.pop()
            else:
                _warn(f"Line {line_no}: >>END-IF without a matching >>IF ignored")
            result_lines.append("")
            continue

        # >>EVALUATE TRUE | >>EVALUATE symbol-or-literal
        elif name == "EVALUATE":
            parent_active = _active()
            frame = _CondFrame(
                "eval",
                parent_active,
                active=False,  # lines before the first >>WHEN are blanked
                branch_taken=not parent_active,
            )
            if rest in ("TRUE", "FALSE"):
                # ``>>EVALUATE FALSE`` selects the first ``>>WHEN`` whose
                # condition is false. It used to be taken as the subject
                # value FALSE, so every conditional ``>>WHEN`` was rejected
                # as "not a single literal" and only OTHER could match.
                frame.eval_cond_mode = True
                frame.eval_cond_negate = rest == "FALSE"
            elif parent_active:
                try:
                    tokens = _tokenize_condition(rest)
                    if len(tokens) != 1 or tokens[0][0] not in _OPERAND_KINDS:
                        raise _ConditionSyntaxError(
                            "expected TRUE, a symbol, or a single literal"
                        )
                    frame.eval_subject = _ConditionParser([], defined)._resolve(
                        tokens[0]
                    )
                except _UndefinedSymbolError as exc:
                    _warn(
                        f"Line {line_no}: >>EVALUATE subject references "
                        f"undefined symbol '{exc.name}' — only >>WHEN OTHER "
                        "can match"
                    )
                    frame.eval_subject_valid = False
                except _ConditionSyntaxError as exc:
                    _warn(
                        f"Line {line_no}: unsupported >>EVALUATE subject "
                        f"'{rest}' ({exc}) — only >>WHEN OTHER can match"
                    )
                    frame.eval_subject_valid = False
            frames.append(frame)
            result_lines.append("")
            continue

        # >>WHEN OTHER | >>WHEN condition-or-literal
        elif name == "WHEN":
            if frames and frames[-1].kind == "eval":
                frame = frames[-1]
                if rest == "OTHER":
                    frame.active = frame.parent_active and not frame.branch_taken
                    frame.branch_taken = True
                else:
                    matched = False
                    if frame.parent_active and not frame.branch_taken:
                        if frame.eval_cond_mode and not frame.eval_cond_negate:
                            matched = _evaluate_condition(
                                rest, defined, _warn, line_no, ">>WHEN"
                            )
                        elif frame.eval_cond_mode:
                            # Not _evaluate_condition: its "treated as
                            # FALSE" fallback would *select* the branch here.
                            try:
                                tokens = _tokenize_condition(rest)
                                matched = (
                                    _ConditionParser(tokens, defined).parse()
                                    != frame.eval_cond_negate
                                )
                            except _UndefinedSymbolError as exc:
                                _warn(
                                    f"Line {line_no}: >>WHEN condition '{rest}' "
                                    f"references undefined symbol '{exc.name}' "
                                    "— branch not selected"
                                )
                            except _ConditionSyntaxError as exc:
                                _warn(
                                    f"Line {line_no}: unsupported >>WHEN "
                                    f"condition '{rest}' ({exc}) — branch not "
                                    "selected"
                                )
                        elif frame.eval_subject_valid:
                            try:
                                tokens = _tokenize_condition(rest)
                                matched = _when_value_matches(
                                    frame.eval_subject or "", tokens, defined
                                )
                            except _UndefinedSymbolError as exc:
                                _warn(
                                    f"Line {line_no}: >>WHEN value references "
                                    f"undefined symbol '{exc.name}' — branch "
                                    "not selected"
                                )
                            except _ConditionSyntaxError as exc:
                                _warn(
                                    f"Line {line_no}: unsupported >>WHEN value "
                                    f"'{rest}' ({exc}) — branch not selected"
                                )
                    frame.active = matched
                    if matched:
                        frame.branch_taken = True
            else:
                _warn(f"Line {line_no}: >>WHEN without a matching >>EVALUATE ignored")
            result_lines.append("")
            continue

        # >>END-EVALUATE
        elif name == "END-EVALUATE":
            if frames and frames[-1].kind == "eval":
                frames.pop()
            else:
                _warn(
                    f"Line {line_no}: >>END-EVALUATE without a matching "
                    ">>EVALUATE ignored"
                )
            result_lines.append("")
            continue

        elif (
            keep_source_format_directives
            and source_format_directive(stripped) is not None
        ):
            result_lines.append(line if _active() else "")
            continue

        # Any other >> compiler directive (>>CALLINTERFACE, >>INLINE,
        # >>SOURCE FORMAT, ...) is not evaluated here, but it is a directive
        # to the compiler and never program text, so it is blanked out like
        # the ones above rather than handed to the lexer as a stray ``>>``
        # token pair that the parser would then report as unparsed content.
        elif stripped.startswith(">>"):
            _warn(
                f"Line {line_no}: unknown compiler directive "
                f"'{line.strip()}' ignored"
            )
            result_lines.append("")
            continue

        # Regular line - include if not skipping. A skipped line still
        # occupies a source line, so emit a blank placeholder rather than
        # dropping it outright, to keep every later line's number accurate.
        if _active():
            result_lines.append(line)
        else:
            result_lines.append("")

    unclosed_ifs = sum(1 for frame in frames if frame.kind == "if")
    unclosed_evals = len(frames) - unclosed_ifs
    if unclosed_ifs:
        _warn(
            f"{unclosed_ifs} unclosed >>IF directive(s) at end of "
            "input — every line after the unclosed >>IF may have been "
            "included or skipped incorrectly"
        )
    if unclosed_evals:
        _warn(
            f"{unclosed_evals} unclosed >>EVALUATE directive(s) at end of "
            "input — every line after the unclosed >>EVALUATE may have been "
            "included or skipped incorrectly"
        )

    return "\n".join(result_lines)


def validate_copybook_content(
    content: str,
    copybook_path: str,
    raw_content: str | None = None,
    *,
    indicator_position: int | None = 6,
) -> list[str]:
    """
    Validate copybook content before expansion.

    Checks for:
    - Empty content
    - Binary/corrupted content
    - Unbalanced quotes
    - Missing terminating periods
    - Other potential issues

    Args:
        content: Copybook content to validate. Callers that already ran this
            through remove_comment_lines() (comment lines blanked to
            whitespace) should pass the pre-strip source via raw_content so
            a comment-only copybook is reported correctly instead of as
            empty.
        copybook_path: Path to copybook (for error messages)
        raw_content: Optional original content, before comment lines were
            blanked out, used only to distinguish a comment-only copybook
            from a genuinely empty one.
        indicator_position: Index of the fixed-format indicator column in
            each line -- 6 for raw source with its sequence area, 0 for
            content that already went through ``strip_sequence_area``
            (which is what the expander validates), ``None`` for free-form
            content, which has no continuation lines at all. Only the
            continued-literal quote discount below depends on it.

    Returns:
        List of warning messages (empty if no issues)

    Raises:
        CopybookSyntaxError: For fatal syntax issues like binary content
    """
    warnings = []

    # Check for empty content
    stripped = content.strip()
    if not stripped:
        if raw_content is not None and raw_content.strip():
            warnings.append(f"Copybook '{copybook_path}' contains only comments")
        else:
            warnings.append(f"Copybook '{copybook_path}' is empty")
        return warnings

    # Check for comment-only content
    lines = [
        line
        for line in split_source_lines(stripped)
        if line.strip() and not line.strip().startswith("*")
    ]
    if not lines:
        warnings.append(f"Copybook '{copybook_path}' contains only comments")

    # Check for binary content indicators
    if "\x00" in content:
        raise CopybookSyntaxError(
            copybook_path, "Binary content detected (null bytes found)"
        )

    # Check for unbalanced quotes (simple check). Quotes are counted per
    # line (escaped/doubled quotes discounted) while tracking a running
    # parity so fixed-format string continuation can be recognised: a line
    # with '-' in column 7 whose first significant character is a quote
    # re-opens a literal left open on the previous line ('"AK' continued by
    # '-    "BC".') and that re-opening quote must not count. The discount
    # only applies while a literal of that quote kind is actually open —
    # a continuation line may also legitimately start a brand-new literal
    # (e.g. the previous line ends with VALUE), whose quotes all count.
    effective_singles = 0
    effective_doubles = 0
    for line in split_source_lines(content):
        line_doubles = line.count('"') - (line.count('""') * 2)
        line_singles = line.count("'") - (line.count("''") * 2)
        if (
            indicator_position is not None
            and len(line) > indicator_position + 1
            and line[indicator_position] == "-"
        ):
            resumed = line[indicator_position + 1 : indicator_position + 66].lstrip()
            if resumed.startswith('"') and effective_doubles % 2 == 1:
                line_doubles -= 1
            elif resumed.startswith("'") and effective_singles % 2 == 1:
                line_singles -= 1
        effective_doubles += line_doubles
        effective_singles += line_singles

    if effective_singles % 2 != 0:
        warnings.append(f"Possible unbalanced single quotes in '{copybook_path}'")
    if effective_doubles % 2 != 0:
        warnings.append(f"Possible unbalanced double quotes in '{copybook_path}'")

    # Check for potential missing terminating period on data definitions
    for line_num in _unterminated_data_entries(content):
        warnings.append(
            f"Line {line_num} in '{copybook_path}' may be missing terminating period"
        )

    return warnings


def validate_level_numbers(
    pre_context: str, copybook_content: str, copybook_path: str
) -> list[str]:
    """
    Validate level number continuity between main program and copybook.

    Args:
        pre_context: Source code before the COPY statement
        copybook_content: Content of the copybook being included
        copybook_path: Path to copybook (for messages)

    Returns:
        List of warning messages about potential level mismatches
    """
    import warnings as warn_module

    warnings: list[str] = []

    # Extract last level number before COPY statement
    pre_levels = list(_LEVEL_NUMBER_RE.finditer(pre_context))
    if not pre_levels:
        return warnings  # No prior data definitions

    last_level = int(pre_levels[-1].group(1))

    # Extract first level number in copybook
    copy_levels = list(_LEVEL_NUMBER_RE.finditer(copybook_content))
    if not copy_levels:
        return warnings  # No data definitions in copybook

    first_copy_level = int(copy_levels[0].group(1))

    # Check for potential issues
    if first_copy_level not in (1, 77, 88):  # 01, 77, 88 can start anywhere
        if first_copy_level <= last_level:
            msg = (
                f"Level number mismatch: copybook '{copybook_path}' starts with "
                f"level {first_copy_level:02d} after level {last_level:02d} in main program. "
                f"This may cause data hierarchy issues."
            )
            warnings.append(msg)
            warn_module.warn(msg, LevelNumberMismatchWarning, stacklevel=2)

    return warnings
