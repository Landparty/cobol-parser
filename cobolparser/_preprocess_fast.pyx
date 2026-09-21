# cython: language_level=3
"""Cython-accelerated normalize_fixed_format for the COBOL preprocessor.

Provides the same public interface as the pure-Python version in
cobolparser/preprocess/__init__.py but replaces the quote-state inner
loop with C-typed integer variables and inlines the nested closure to
eliminate Python closure overhead.

Imported transparently by preprocess/__init__.py; pure-Python fallback
used when not compiled.
"""

cimport cython

from collections.abc import Iterable

from cobolparser._lines import split_source_lines

# Cannot import from preprocess/__init__.py (circular import); values must mirror it.
_SEQ_END    = 6   # DEFAULT_SEQ_COL_END
_IND_IDX    = 6   # INDICATOR_COL - 1
_TEXT_START = 7   # TEXT_START_COL - 1
_TEXT_END   = 72  # TEXT_END_COL
_ID_END     = 80  # IDENTIFICATION_END_COL
_MIN_ID_STAMP_EVIDENCE = 3  # MIN_ID_STAMP_EVIDENCE_LINES


cdef bint _has_identification_stamp_convention(list lines):
    """True when *lines* demonstrably stamp a per-line numeric
    identification code into columns 73-80 while keeping program text
    within column 72. Mirrors the pure-Python
    `_has_identification_stamp_convention`: only lines whose column 72 is
    blank (nothing could have been split there), whose columns-73+ tail is
    non-empty and all digits, and whose content stays inside the
    traditional 80-column width count as evidence; `_MIN_ID_STAMP_EVIDENCE`
    of them settle it. Returns as soon as the threshold is met."""
    cdef Py_ssize_t j, n = len(lines)
    cdef int evidence = 0
    cdef str candidate, tail
    for j in range(n):
        candidate = lines[j].rstrip("\n").expandtabs(8)
        if len(candidate) <= _TEXT_END:
            continue
        if len(candidate.rstrip()) > _ID_END:
            continue
        if not candidate[_TEXT_END - 1].isspace():
            continue
        tail = candidate[_TEXT_END:].strip()
        if not tail.isdigit():
            continue
        evidence += 1
        if evidence >= _MIN_ID_STAMP_EVIDENCE:
            return True
    return False


cdef tuple _next_code_line(list lines, Py_ssize_t idx,
                           bint debug_lines_as_comments,
                           bint version_tag_lines_as_comments):
    """Index of the next program-text line after physical index *idx*
    (``len(lines)`` when there is none) and whether it is a continuation
    record. Mirrors the pure-Python `_continuation_follows` lookahead."""
    cdef Py_ssize_t j, n = len(lines)
    cdef str candidate, ind
    for j in range(idx + 1, n):
        candidate = lines[j].rstrip("\n").expandtabs(8)
        if len(candidate) < _TEXT_START:
            continue
        ind = candidate[_IND_IDX] if len(candidate) > _IND_IDX else " "
        if (
            ind == "*" or ind == "/"
            or (debug_lines_as_comments and (ind == "D" or ind == "d"))
            or (version_tag_lines_as_comments and (ind == "V" or ind == "v"))
        ):
            continue
        return (j, ind == "-")
    return (n, False)


def normalize_fixed_format(lines, *, merge_continued_literals=True, debug_lines_as_comments=True, version_tag_lines_as_comments=True, warnings=None):
    """Normalize fixed-format COBOL lines into a pseudo free-form block.

    Identical contract to the pure-Python version; see that function for
    full documentation, including the column-73+ overflow warning rule:
    a mid-token split (columns 72 and 73 both non-blank) or a
    word-boundary overflow (line content extends past the traditional
    80-column identification-area width even when it broke on a space).
    """
    cdef int  i, n
    cdef bint quote_open    = False
    cdef bint pending_literal = False
    cdef str  quote_ch      = None
    cdef str  ch
    cdef bint is_debug_comment
    cdef bint is_version_tag_comment
    # True once a non-comment, non-short physical line has started (or
    # continued) the logical line currently buffered in `parts`. Distinguishes
    # "no logical line accumulated yet" (nothing to flush) from "a logical
    # line was accumulated but its merged text happens to be empty" (a blank
    # placeholder must still be emitted). Mirrors the pure-Python fix: the
    # old `if combined:` guard silently dropped a full-width blank line (all-
    # whitespace program text, non-comment indicator) whenever it followed
    # another blank/comment line, shifting every later line number.
    cdef bint has_line = False
    # Placeholder lines owed *after* the logical line in `parts` is flushed
    # (mirrors the pure-Python `deferred`): every physical line contributes
    # exactly one output line, so a continuation record -- merged into the
    # logical line -- still owes one empty placeholder, emitted once the
    # logical line is written. Comment/blank lines interrupting an open
    # continued literal are deferred the same way instead of severing it.
    cdef int deferred = 0
    # True while a literal is left open across an interrupting comment/blank
    # line; such a literal keeps the historical "closed at the interruption"
    # outcome at EOF instead of raising (mirrors `literal_suspended`).
    cdef bint literal_suspended = False
    # Mirrors the pure-Python `closing_quote_at_72`: the quote that closed a
    # literal exactly in column 72 of the last program-text line. IBM's
    # rule: a continuation line then starting with two quotation marks
    # means the literal never closed -- the pair is one doubled quote and
    # the literal carries on.
    cdef str closing_quote_at_72 = None
    cdef str lead, rest
    # Mirrors the pure-Python one-code-line lookahead (`_continuation_follows`):
    # a comment/blank line followed by a continuation record is deferred
    # behind the logical line for ANY continued text, not only an open
    # literal, so a word split across a comment rejoins.
    cdef Py_ssize_t next_code_idx = -1
    cdef bint next_code_is_cont = False
    # Mirrors the pure-Python `stamps_identification_area`: whether this
    # file stamps a numeric identification code into columns 73-80. A
    # whole-file property, so it is computed at most once -- -1 means "not
    # asked yet", 0/1 the cached answer.
    cdef int stamps_identification_area = -1
    cdef bint is_short_id_stamp

    if isinstance(lines, str):
        lines = split_source_lines(lines)
    lines = list(lines)

    result = []
    parts  = []

    for line_no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n").expandtabs(8)

        if len(line) < _TEXT_START:
            # Blank/short line. Inside an open continued literal it may sit
            # between the continued line and its continuation: keep the
            # logical line pending and owe a placeholder for this record.
            if pending_literal and merge_continued_literals and has_line:
                deferred += 1
                literal_suspended = True
                continue
            if has_line:
                if next_code_idx <= line_no - 1:
                    next_code_idx, next_code_is_cont = _next_code_line(
                        lines, line_no - 1,
                        debug_lines_as_comments, version_tag_lines_as_comments,
                    )
                if next_code_is_cont:
                    deferred += 1
                    continue
            # Flush accumulated parts for this logical line, then emit an
            # empty placeholder for this physical line so later lines keep
            # their true line number (mirrors the pure-Python fix — a
            # dropped line here would silently shift every subsequent
            # error/warning location).
            if has_line:
                result.append("".join(parts))
            if deferred:
                result.extend([""] * deferred)
                deferred = 0
            result.append("")
            parts         = []
            has_line      = False
            literal_suspended = False
            quote_open    = False
            quote_ch      = None
            pending_literal = False
            continue

        indicator  = line[_IND_IDX] if len(line) > _IND_IDX else " "
        text_slice = line[_TEXT_START : _TEXT_END]

        # Indicator characters mirror _normalize.py's COMMENT_INDICATORS /
        # DEBUG_INDICATORS / VERSION_TAG_INDICATORS constants (inlined here
        # for C-level char comparisons, like the rest of this mirror) --
        # extend those sets and this line together.
        is_debug_comment = debug_lines_as_comments and (indicator == "D" or indicator == "d")
        is_version_tag_comment = version_tag_lines_as_comments and (indicator == "V" or indicator == "v")
        if indicator == "*" or indicator == "/" or is_debug_comment or is_version_tag_comment:
            # Comment line (incl. page eject, debug lines, version-tag
            # lines): discard comment text, but still emit an empty
            # placeholder to preserve line numbering. A comment interrupting
            # an open continued literal does not sever it -- the placeholder
            # is deferred behind the logical line instead.
            if pending_literal and merge_continued_literals and has_line:
                deferred += 1
                literal_suspended = True
                continue
            if has_line:
                if next_code_idx <= line_no - 1:
                    next_code_idx, next_code_is_cont = _next_code_line(
                        lines, line_no - 1,
                        debug_lines_as_comments, version_tag_lines_as_comments,
                    )
                if next_code_is_cont:
                    deferred += 1
                    continue
            if has_line:
                result.append("".join(parts))
            if deferred:
                result.extend([""] * deferred)
                deferred = 0
            result.append("")
            parts         = []
            has_line      = False
            literal_suspended = False
            quote_open    = False
            quote_ch      = None
            pending_literal = False
            continue

        if warnings is not None and len(line) > _TEXT_END:
            seq_area = line[:_SEQ_END]
            # Mirrors the pure-Python rule: a numeric sequence number in
            # columns 1-6 is strong evidence this line deliberately uses
            # the traditional 80-column convention (identification field
            # may abut column 72 with no separating blank), so the
            # overflow check is skipped entirely for such lines -- avoids
            # flooding sequence-numbered decks with false positives.
            has_sequence_number = (
                seq_area.strip() != "" and seq_area.strip().isdigit()
            )
            if not has_sequence_number:
                before, after = line[_TEXT_END - 1], line[_TEXT_END]
                mid_token = not before.isspace() and not after.isspace()
                content_len = len(line.rstrip())
                # A real 80-column punch-card line can't exceed 80 columns
                # by construction, so content surviving past column 80 is
                # overflow even when the split lands on a space
                # (mid_token False) rather than mid-token.
                exceeds_traditional_width = content_len > _ID_END
                dropped = line[_TEXT_END:].rstrip()
                # Second, independent gate (mirrors the pure-Python rule): a
                # purely-numeric dropped tail that fills the traditional
                # 80-column identification area EXACTLY (digits from column
                # 73 through 80) is a per-line sequence/change-tracking
                # stamp (e.g. IBM Z Open Editor/ISPF-style auto numbering
                # like 03050009, always the full 8-column field) even when
                # columns 1-6 are blank -- not an actual token split. A
                # shorter all-digit tail (a data name's own trailing digits
                # spilling past 72) and a mixed alnum tail (e.g. NIST's
                # IX2094.2 test-case id) both still warn.
                is_numeric_id_stamp = (
                    content_len == _ID_END and dropped.isdigit()
                )
                # Mirrors the pure-Python rule: a *shorter* all-digit tail
                # is the same convention whenever the file itself proves it
                # uses one (a shop change-tracking stamp is commonly 4-6
                # digits at column 73, not the full 8-column field). Per
                # line that is indistinguishable from a data name's own
                # trailing digits getting cut; across the file it is not,
                # so the question is asked of the file.
                is_short_id_stamp = (
                    not is_numeric_id_stamp
                    and content_len <= _ID_END
                    and dropped.isdigit()
                )
                # Mirrors the pure-Python rule: a dropped tail that is only
                # the statement-terminating period (e.g. a banner-style
                # VALUE literal whose closing quote lands on column 72)
                # closed cleanly -- nothing was actually split mid-token.
                is_bare_terminal_period = dropped == "."
                if mid_token and is_short_id_stamp:
                    # Only now is the whole-file scan worth its cost.
                    if stamps_identification_area < 0:
                        stamps_identification_area = (
                            1 if _has_identification_stamp_convention(lines) else 0
                        )
                    if stamps_identification_area == 1:
                        is_numeric_id_stamp = True
                if mid_token and not is_numeric_id_stamp and not is_bare_terminal_period:
                    warnings.append(
                        f"Line {line_no}: content beyond column {_TEXT_END} "
                        f"was dropped mid-token: {dropped!r}"
                    )
                elif exceeds_traditional_width:
                    warnings.append(
                        f"Line {line_no}: content beyond column {_TEXT_END} "
                        f"was dropped -- line is {content_len} columns wide, "
                        f"past the traditional {_ID_END}-column "
                        f"identification-area width: {dropped!r}"
                    )

        is_cont = indicator == "-"

        if is_cont:
            # One physical line merged into the logical line: owe one
            # placeholder behind it (an orphan continuation with nothing to
            # join starts the logical line itself and owes none).
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
                # the literal never closed. Re-open it, keep one of the pair
                # so the joined text reads as the doubled quote it is, and
                # scan on from the second (mirrors the pure-Python branch).
                quote_open = True
                quote_ch   = closing_quote_at_72
                rest = lead[2:]
                n = len(rest)
                i = 0
                while i < n:
                    ch = rest[i]
                    if quote_open:
                        if ch == quote_ch:
                            if i + 1 < n and rest[i + 1] == quote_ch:
                                i += 2
                                continue
                            quote_open = False
                            quote_ch   = None
                        i += 1
                    else:
                        if ch == "'" or ch == '"':
                            quote_open = True
                            quote_ch   = ch
                            i += 1
                        elif ch == "*" and i + 1 < n and rest[i + 1] == ">":
                            break
                        else:
                            i += 1
                pending_literal = quote_open
                parts.append(
                    closing_quote_at_72 + (rest if pending_literal else rest.rstrip())
                )
            elif pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and quote_ch is not None and chunk[0] == quote_ch:
                    chunk = chunk[1:]
                # Inline quote-state update (scan the un-rstripped chunk so
                # trailing blanks aren't discarded before we know whether
                # the literal is still open -- M5).
                n = len(chunk)
                i = 0
                while i < n:
                    ch = chunk[i]
                    if quote_open:
                        if ch == quote_ch:
                            if i + 1 < n and chunk[i + 1] == quote_ch:
                                i += 2
                                continue
                            quote_open = False
                            quote_ch   = None
                        i += 1
                    else:
                        if ch == "'" or ch == '"':
                            quote_open = True
                            quote_ch   = ch
                            i += 1
                        elif ch == "*" and i + 1 < n and chunk[i + 1] == ">":
                            # Inline comment outside a literal: nothing after it
                            # can open one (mirrors _update_quote_state).
                            break
                        else:
                            i += 1
                pending_literal = quote_open
                # Trailing blanks up to column 72 are part of a literal's
                # value when it remains open at end of line (COBOL
                # fixed-format continuation rule) -- only strip them once
                # we know no literal is left dangling (M5).
                parts.append(chunk if pending_literal else chunk.rstrip())
            else:
                # Non-literal continuation: '-' in column 7 with no
                # alphanumeric literal open. Per COBOL fixed-format rules the
                # first non-blank char of the continuation line is the
                # successor of the last non-blank char of the continued line,
                # with NO intervening space (numeric literals / words split
                # mid-token, e.g. '-999.777' one character per line). Strip
                # both ends so the chunk butts directly onto the buffer.
                stripped = text_slice.strip()
                parts.append(stripped)
                if merge_continued_literals:
                    n = len(stripped)
                    i = 0
                    while i < n:
                        ch = stripped[i]
                        if quote_open:
                            if ch == quote_ch:
                                if i + 1 < n and stripped[i + 1] == quote_ch:
                                    i += 2
                                    continue
                                quote_open = False
                                quote_ch   = None
                            i += 1
                        else:
                            if ch == "'" or ch == '"':
                                quote_open = True
                                quote_ch   = ch
                                i += 1
                            elif ch == "*" and i + 1 < n and stripped[i + 1] == ">":
                                # Inline comment outside a literal: nothing after it
                                # can open one (mirrors _update_quote_state).
                                break
                            else:
                                i += 1
                    pending_literal = quote_open
        else:
            # Non-continuation: flush previous logical line
            if has_line:
                result.append("".join(parts))
            if deferred:
                result.extend([""] * deferred)
                deferred = 0
            parts         = []
            has_line      = False
            literal_suspended = False
            quote_open    = False
            quote_ch      = None
            pending_literal = False

            if merge_continued_literals:
                n = len(text_slice)
                i = 0
                while i < n:
                    ch = text_slice[i]
                    if quote_open:
                        if ch == quote_ch:
                            if i + 1 < n and text_slice[i + 1] == quote_ch:
                                i += 2
                                continue
                            quote_open = False
                            quote_ch   = None
                        i += 1
                    else:
                        if ch == "'" or ch == '"':
                            quote_open = True
                            quote_ch   = ch
                            i += 1
                        elif ch == "*" and i + 1 < n and text_slice[i + 1] == ">":
                            # Inline comment outside a literal: nothing after it
                            # can open one (mirrors _update_quote_state).
                            break
                        else:
                            i += 1
                pending_literal = quote_open
                # M5: trailing blanks are part of the literal's value when
                # it remains open at end of line -- only strip once closed.
                parts.append(text_slice if pending_literal else text_slice.rstrip())
            else:
                parts.append(text_slice.rstrip())

        # Mirrors the pure-Python rule: a quote in column 72 with no literal
        # left open can only have closed one -- remember it for the next
        # continuation record.
        if (
            merge_continued_literals
            and not pending_literal
            and len(text_slice) == _TEXT_END - _TEXT_START
            and (text_slice[-1] == "'" or text_slice[-1] == '"')
        ):
            closing_quote_at_72 = text_slice[-1]
        else:
            closing_quote_at_72 = None

        # Either branch above (continuation or new logical line) always
        # appends to `parts` (even an empty string), so this physical line
        # has real content pending flush.
        has_line = True

    if has_line:
        result.append("".join(parts))
    if deferred:
        result.extend([""] * deferred)

    if pending_literal and merge_continued_literals and not literal_suspended:
        raise ValueError(
            f"Unterminated string literal at end of input "
            f"(opened with quote character '{quote_ch or '?'}')"
        )

    return "\n".join(result) + "\n"
