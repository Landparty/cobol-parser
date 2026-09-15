"""Source normalization and conditional-compilation preprocessing.

Implementation module for the parts of :mod:`cobolparser.preprocess` that are
not copybook expansion: fixed-format normalization, compiler-directive
stripping, the ``>>IF``/``>>EVALUATE`` conditional-compilation evaluator, the
copybook content/level validators, and the preprocessing exception hierarchy.

This lives in a private module rather than in ``preprocess/__init__.py`` so
that the closed-source release build can compile it (see ``setup.py``, which
deliberately ships every ``__init__.py`` as plain source on the premise that
they are thin re-export stubs). Import these names from
:mod:`cobolparser.preprocess` -- the package re-exports all of them.
"""

import re
from collections.abc import Callable, Iterable, Mapping

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
_NON_ENTRY_LINE_RE = re.compile(r"^[ \t]*EXEC\b", re.IGNORECASE)
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
    lines = content.splitlines()
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
# parser._detect_fixed_format, and lexer._fixed_format_comment_tokens all
# derive from these sets (the Cython mirror _preprocess_fast.pyx repeats the
# literals by design, like the rest of its body -- keep it in sync when
# extending these). The next shop convention from the corpus goes here, not
# into another hand-maintained per-site tuple.
COMMENT_INDICATORS = frozenset({"*", "/"})  # unconditional: comment / page eject
DEBUG_INDICATORS = frozenset({"D", "d"})  # debug lines (flag-gated in normalize)
VERSION_TAG_INDICATORS = frozenset({"V", "v"})  # version tags (flag-gated too)
ALL_COMMENT_INDICATORS = COMMENT_INDICATORS | DEBUG_INDICATORS | VERSION_TAG_INDICATORS


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
    lines = source.splitlines(keepends=True)
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
        if in_directive_section and text_area:
            text_upper = text_area.upper()
            if text_upper.startswith("IDENTIFICATION") or text_upper.startswith("ID "):
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
        lines = lines.splitlines()
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
        line = raw.rstrip("\n").expandtabs(8)
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
                # fails `.isdigit()` -- both keep warning exactly as before.
                is_numeric_id_stamp = (
                    content_len == IDENTIFICATION_END_COL and dropped.isdigit()
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
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and chunk[0] == quote_char:
                    chunk = chunk[1:]
                _update_quote_state(chunk)
                # Trailing blanks up to column 72 are part of a literal's
                # value when it remains open at end of line (COBOL
                # fixed-format continuation rule) -- only strip them once
                # we know no literal is left dangling (M5).
                out_chunk = chunk if pending_literal else chunk.rstrip()
                parts.append(out_chunk)
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
    | (?P<string>'[^']*'|"[^"]*")
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<word>[A-Z_][A-Z0-9_-]*)
    """,
    re.VERBOSE,
)

# >>DIRECTIVE-NAME [rest-of-line]
_DIRECTIVE_LINE_RE = re.compile(r"^>>\s*([A-Z][A-Z0-9-]*)(?:\s+(.*?))?\s*$")

_OPERAND_KINDS = frozenset({"word", "string", "number", "boollit"})


def _strip_quotes(text: str) -> str:
    """Strip one pair of matching surrounding quotes, if present."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _try_number(text: str) -> float | None:
    """Return the numeric value of *text*, or None if it is not numeric."""
    try:
        return float(text)
    except ValueError:
        return None


def _values_equal(left: str, right: str) -> bool:
    """Compare two resolved values: numerically when both are numeric,
    otherwise as case-insensitive strings."""
    ln, rn = _try_number(left), _try_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    return left.upper() == right.upper()


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
                    | operand [IS [NOT]] (= | <> | > | < | >= | <=) operand
                    | operand                    -- interpreted as a boolean
        operand    := symbol | number | 'string' | "string" | B'0' | B'1'
                    | TRUE | FALSE
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
        token = self._peek()
        if token is not None and token[0] == "op":
            self._pos += 1
            return token[1]
        return None

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
            self._advance()
            value = self._parse_or()
            closing = self._peek()
            if closing is None or closing[0] != "rparen":
                raise _ConditionSyntaxError("missing closing parenthesis")
            self._advance()
            return value

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

        # operand IS [NOT] DEFINED | operand IS [NOT] <op> operand
        if self._match_word("IS"):
            negate = self._match_word("NOT") is not None
            if self._match_word("DEFINED"):
                if operand[0] != "word":
                    raise _ConditionSyntaxError(
                        "only a symbol name can be tested with IS [NOT] DEFINED"
                    )
                exists = operand[1] in self._defined
                return not exists if negate else exists
            op = self._match_op()
            if op is None:
                raise _ConditionSyntaxError(
                    "expected DEFINED or a comparison operator after IS"
                )
            result = self._compare(operand, op, self._parse_operand())
            return not result if negate else result

        op = self._match_op()
        if op is not None:
            return self._compare(operand, op, self._parse_operand())

        return self._truthy(operand)

    def _parse_operand(self) -> tuple[str, str]:
        token = self._peek()
        if token is None or token[0] not in _OPERAND_KINDS:
            found = "end of condition" if token is None else repr(token[1])
            raise _ConditionSyntaxError(f"expected an operand, got {found}")
        self._pos += 1
        return token

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
            lc, rc = lv.upper(), rv.upper()
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
    """Normalize a caller-supplied symbol value to its string form."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return _strip_quotes(value)


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


class _CondFrame:
    """One nesting level of >>IF or >>EVALUATE processing."""

    __slots__ = (
        "kind",
        "parent_active",
        "active",
        "branch_taken",
        "eval_cond_mode",
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
        self.eval_cond_mode = False  # True for >>EVALUATE TRUE
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
    # Deferred: parser imports this package at module scope.
    from ..parser import _sequence_area_is_fixed_like

    if not _sequence_area_is_fixed_like(expanded[:DEFAULT_SEQ_COL_END])[0]:
        return None
    text = expanded[TEXT_START_COL - 1 : TEXT_END_COL].strip().upper()
    return text if text.startswith(">>") else None


def preprocess_conditional_compilation(
    source: str,
    defined_symbols: (
        Mapping[str, str | int | float | bool] | Iterable[str] | None
    ) = None,
    warnings: list[str] | None = None,
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
      numeric, otherwise case-insensitive string comparison)
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
    result_lines: list[str] = []
    frames: list[_CondFrame] = []

    def _warn(message: str) -> None:
        if warnings is not None:
            warnings.append(message)

    def _active() -> bool:
        return all(frame.active for frame in frames)

    for line_no, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip().upper()
        if not stripped.startswith(">>"):
            # A directive in a sequence-numbered fixed-format line
            # (``000400     >>IF ...``) starts at column 8, not column 1.
            fixed_text = _fixed_format_directive_text(line)
            if fixed_text is not None:
                stripped = fixed_text

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
                        defined[symbol] = _strip_quotes(raw_value)
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
            if rest == "TRUE":
                frame.eval_cond_mode = True
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
                        if frame.eval_cond_mode:
                            matched = _evaluate_condition(
                                rest, defined, _warn, line_no, ">>WHEN"
                            )
                        elif frame.eval_subject_valid:
                            try:
                                tokens = _tokenize_condition(rest)
                                if (
                                    len(tokens) != 1
                                    or tokens[0][0] not in _OPERAND_KINDS
                                ):
                                    raise _ConditionSyntaxError(
                                        "expected a single literal or symbol"
                                    )
                                value = _ConditionParser([], defined)._resolve(
                                    tokens[0]
                                )
                                matched = _values_equal(frame.eval_subject or "", value)
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
    content: str, copybook_path: str, raw_content: str | None = None
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
        for line in stripped.splitlines()
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
    for line in content.splitlines():
        line_doubles = line.count('"') - (line.count('""') * 2)
        line_singles = line.count("'") - (line.count("''") * 2)
        if len(line) > 7 and line[6] == "-":
            resumed = line[7:72].lstrip()
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
