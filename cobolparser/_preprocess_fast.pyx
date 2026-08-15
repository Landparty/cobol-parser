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

# Cannot import from preprocess/__init__.py (circular import); values must mirror it.
_SEQ_END    = 6   # DEFAULT_SEQ_COL_END
_IND_IDX    = 6   # INDICATOR_COL - 1
_TEXT_START = 7   # TEXT_START_COL - 1
_TEXT_END   = 72  # TEXT_END_COL
_ID_END     = 80  # IDENTIFICATION_END_COL


def normalize_fixed_format(lines, *, merge_continued_literals=True, debug_lines_as_comments=True, warnings=None):
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
    # True once a non-comment, non-short physical line has started (or
    # continued) the logical line currently buffered in `parts`. Distinguishes
    # "no logical line accumulated yet" (nothing to flush) from "a logical
    # line was accumulated but its merged text happens to be empty" (a blank
    # placeholder must still be emitted). Mirrors the pure-Python fix: the
    # old `if combined:` guard silently dropped a full-width blank line (all-
    # whitespace program text, non-comment indicator) whenever it followed
    # another blank/comment line, shifting every later line number.
    cdef bint has_line = False

    result = []
    parts  = []

    for line_no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n").expandtabs(8)

        if len(line) < _TEXT_START:
            # Flush accumulated parts for this logical line, then emit an
            # empty placeholder for this physical line so later lines keep
            # their true line number (mirrors the pure-Python fix — a
            # dropped line here would silently shift every subsequent
            # error/warning location).
            if has_line:
                result.append("".join(parts))
            result.append("")
            parts         = []
            has_line      = False
            quote_open    = False
            quote_ch      = None
            pending_literal = False
            continue

        indicator  = line[_IND_IDX] if len(line) > _IND_IDX else " "
        text_slice = line[_TEXT_START : _TEXT_END]

        is_debug_comment = debug_lines_as_comments and (indicator == "D" or indicator == "d")
        if indicator == "*" or indicator == "/" or is_debug_comment:
            # Comment line (incl. page eject, debug lines): flush buffer,
            # discard comment text, but still emit an empty placeholder to
            # preserve line numbering.
            if has_line:
                result.append("".join(parts))
            result.append("")
            parts         = []
            has_line      = False
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
                if mid_token:
                    dropped = line[_TEXT_END:].rstrip()
                    warnings.append(
                        f"Line {line_no}: content beyond column {_TEXT_END} "
                        f"was dropped mid-token: {dropped!r}"
                    )
                elif exceeds_traditional_width:
                    dropped = line[_TEXT_END:].rstrip()
                    warnings.append(
                        f"Line {line_no}: content beyond column {_TEXT_END} "
                        f"was dropped -- line is {content_len} columns wide, "
                        f"past the traditional {_ID_END}-column "
                        f"identification-area width: {dropped!r}"
                    )

        is_cont = indicator == "-"

        if is_cont:
            if pending_literal and merge_continued_literals:
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
                    pending_literal = quote_open
        else:
            # Non-continuation: flush previous logical line
            if has_line:
                result.append("".join(parts))
            parts         = []
            has_line      = False
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
                pending_literal = quote_open
                # M5: trailing blanks are part of the literal's value when
                # it remains open at end of line -- only strip once closed.
                parts.append(text_slice if pending_literal else text_slice.rstrip())
            else:
                parts.append(text_slice.rstrip())

        # Either branch above (continuation or new logical line) always
        # appends to `parts` (even an empty string), so this physical line
        # has real content pending flush.
        has_line = True

    if has_line:
        result.append("".join(parts))

    if pending_literal and merge_continued_literals:
        raise ValueError(
            f"Unterminated string literal at end of input "
            f"(opened with quote character '{quote_ch or '?'}')"
        )

    return "\n".join(result) + "\n"
