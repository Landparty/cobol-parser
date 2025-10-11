"""Preprocessing utilities for COBOL source normalization.

Functions here help convert fixed-format COBOL into a simplified free-form
representation for easier lexing, while preserving approximate line mapping.
"""
from __future__ import annotations
from typing import Iterable, List

DEFAULT_SEQ_COL_END = 6  # 1-6 sequence numbers
INDICATOR_COL = 7        # column 7 indicator position (1-based)
TEXT_START_COL = 8       # program text begins (1-based)
TEXT_END_COL = 72        # program text end (inclusive, 1-based)


def normalize_fixed_format(lines: Iterable[str], *, merge_continued_literals: bool = True) -> str:
    """Normalize fixed-format COBOL lines into a pseudo free-form block.

    Steps:
    - Strip sequence area (cols 1-6).
    - Capture indicator column; treat '*' and '/' lines as comments (preserve as-is).
    - Extract program text cols 8-72.
    - If a continuation line (indicator '-') occurs and previous line ended inside a literal,
      merge without inserting a newline.
    - Otherwise join with newlines.

    This does NOT attempt full column-sensitive semantics (debugging helper).
    """
    result: List[str] = []
    pending_literal = False
    quote_char: str | None = None
    buffer = ''

    def flush_buffer():
        nonlocal buffer
        if buffer:
            result.append(buffer)
            buffer = ''

    for raw in lines:
        line = raw.rstrip('\n')
        if len(line) < TEXT_START_COL - 1:
            flush_buffer()
            continue
        indicator = line[INDICATOR_COL - 1] if len(line) >= INDICATOR_COL else ' '
        text_slice = line[TEXT_START_COL - 1:TEXT_END_COL]
        if indicator == '*':  # comment
            flush_buffer()
            result.append(text_slice.rstrip())
            continue
        is_cont = indicator == '-'

        # Append to buffer if we are inside a literal continuation
        if pending_literal and is_cont and merge_continued_literals:
            # continuation: remove leading spaces in slice
            chunk = text_slice.lstrip()
            buffer += chunk
        else:
            # Start new logical line
            flush_buffer()
            buffer = text_slice.rstrip()

        # Update literal tracking (simple heuristic)
        if merge_continued_literals:
            # Count quotes ignoring doubled ones
            i = 0
            while i < len(buffer):
                ch = buffer[i]
                if quote_char:
                    if ch == quote_char:
                        if i + 1 < len(buffer) and buffer[i+1] == quote_char:  # escaped
                            i += 2
                            continue
                        # closing quote
                        quote_char = None
                        pending_literal = False
                    i += 1
                else:
                    if ch in ("'", '"'):
                        quote_char = ch
                        pending_literal = True
                        i += 1
                    else:
                        i += 1

    flush_buffer()
    return '\n'.join(result) + '\n'

__all__ = ["normalize_fixed_format"]
