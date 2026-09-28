"""Recognising the ``>>SOURCE FORMAT`` compiler directive.

Shared by the pure-Python fixed-format normalizer and its Cython mirror
(``_preprocess_fast.pyx``), which cannot import from ``preprocess`` (circular
import), so it lives in a dependency-free module of its own -- the same
reason ``_lines.py`` does.

IBM Enterprise COBOL::

    >>SOURCE [FORMAT] [IS] {FIXED | FREE}

switches the reference format for every line after it until the next
``>>SOURCE``. ``>>`` and the directive name may be separated by blanks, and
the directive may carry a trailing ``*>`` inline comment.
"""

from __future__ import annotations

import re

_SOURCE_DIRECTIVE_RE = re.compile(
    r">>[ \t]*SOURCE(?:[ \t]+FORMAT)?(?:[ \t]+IS)?[ \t]+(FIXED|FREE)"
    r"[ \t]*(?:\*>.*)?$",
    re.IGNORECASE,
)


def source_format_directive(text: str) -> str | None:
    """``"FIXED"`` / ``"FREE"`` when *text* is a ``>>SOURCE`` directive.

    *text* is the directive's program text -- columns 7-72 of a fixed-format
    record, or a whole free-format line; surrounding blanks are ignored.
    ``None`` for anything else, including a ``>>SOURCE`` naming no format.
    """
    stripped = text.strip()
    if not stripped.startswith(">>"):
        return None
    match = _SOURCE_DIRECTIVE_RE.match(stripped)
    return match.group(1).upper() if match else None


def free_format_flags(lines: list[str], indicator_position: int = 6) -> list[bool]:
    """Per line of a fixed-format file, whether it is in free format.

    A line is free when a ``>>SOURCE ... FREE`` directive before it is still
    in force.  The directive records themselves are flagged with the format
    they are *written* in (the one in force before them).  In fixed format a
    directive is looked for from the indicator column (*indicator_position*,
    0-based: 6 for raw records, 0 once columns 1-6 are stripped) to column
    72; on a free-format line, anywhere.
    """
    flags: list[bool] = []
    free = False
    fixed_end = indicator_position + 66
    for line in lines:
        flags.append(free)
        if ">>" not in line:
            continue
        text = line if free else line.expandtabs(8)[indicator_position:fixed_end]
        directive = source_format_directive(text)
        if directive is not None:
            free = directive == "FREE"
    return flags
