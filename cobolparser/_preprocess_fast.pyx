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
_IND_IDX    = 6   # INDICATOR_COL - 1
_TEXT_START = 7   # TEXT_START_COL - 1
_TEXT_END   = 72  # TEXT_END_COL


def normalize_fixed_format(lines, *, merge_continued_literals=True):
    """Normalize fixed-format COBOL lines into a pseudo free-form block.

    Identical contract to the pure-Python version; see that function for
    full documentation.
    """
    cdef int  i, n
    cdef bint quote_open    = False
    cdef bint pending_literal = False
    cdef str  quote_ch      = None
    cdef str  ch

    result = []
    parts  = []

    for raw in lines:
        line = raw.rstrip("\n")

        if len(line) < _TEXT_START:
            # Flush accumulated parts for this logical line
            combined = "".join(parts)
            if combined:
                result.append(combined)
            parts         = []
            quote_open    = False
            quote_ch      = None
            pending_literal = False
            continue

        indicator  = line[_IND_IDX] if len(line) > _IND_IDX else " "
        text_slice = line[_TEXT_START : _TEXT_END]

        if indicator == "*" or indicator == "/":
            # Comment line: flush buffer, discard comment text
            combined = "".join(parts)
            if combined:
                result.append(combined)
            parts         = []
            quote_open    = False
            quote_ch      = None
            pending_literal = False
            continue

        is_cont = indicator == "-"

        if is_cont:
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and quote_ch is not None and chunk[0] == quote_ch:
                    chunk = chunk[1:]
                stripped = chunk.rstrip()
                parts.append(stripped)
                # Inline quote-state update
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
                stripped = " " + text_slice.lstrip()
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
            combined = "".join(parts)
            if combined:
                result.append(combined)
            parts         = []
            quote_open    = False
            quote_ch      = None
            pending_literal = False

            stripped = text_slice.rstrip()
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

    combined = "".join(parts)
    if combined:
        result.append(combined)

    if pending_literal and merge_continued_literals:
        raise ValueError(
            f"Unterminated string literal at end of input "
            f"(opened with quote character '{quote_ch or '?'}')"
        )

    return "\n".join(result) + "\n"
