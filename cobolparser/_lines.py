"""Record-boundary line splitting shared by every stage of the pipeline.

``str.splitlines()`` breaks on every Unicode line boundary: not only ``\\n``,
``\\r\\n`` and ``\\r`` but also form feed (``\\x0c``, a page eject inside a
comment), vertical tab, the C1 NEL (``\\x85``, what a cp1252 ``…`` becomes
when a file is decoded as latin-1), U+2028/2029 and the ``\\x1c``-``\\x1e``
separators. A physical record holding one of those became two lines, and
every ``location.line`` after it was off by one against the editor and the
IBM listing. A record is delimited by ``\\n``, ``\\r\\n`` or ``\\r`` and
nothing else, so every stage splits through here.
"""

from __future__ import annotations

import re

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
_LINE_WITH_END_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


def split_source_lines(text: str, keepends: bool = False) -> list[str]:
    """Split *text* into lines on ``\\n`` / ``\\r\\n`` / ``\\r`` only.

    Mirrors ``str.splitlines(keepends)`` otherwise: no trailing empty line for
    a terminating line break, ``[]`` for ``""``.
    """
    if not text:
        return []
    if keepends:
        return _LINE_WITH_END_RE.findall(text)
    parts = _LINE_BREAK_RE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts
