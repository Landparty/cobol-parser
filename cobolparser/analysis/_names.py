"""Shared reference-string normalization for analyzers.

Statement parsers fold ``OF``/``IN`` qualifier chains and ``( subscript )``
groups into a single operand string (``"WS-NUM OF GRP-1"``,
``"WS-TAB OF GRP ( 3 )"``) so no reference tokens are dropped from the AST.
Analyzers that key data items by bare name (a MOVE-target catalog lookup, a
tracked-variable table matched against a bare ``CALL identifier``) must
recover the referenced item's own name from that folded string -- otherwise
a qualified reference silently misses every lookup keyed by the bare name.
"""

from __future__ import annotations

import re

#: A COBOL identifier-shaped token: a letter, then letters/digits/hyphens.
#: The canonical tokenizer for pulling identifier-shaped words out of a raw
#: text blob that has no AST-level operand list of its own to walk (a
#: paragraph's source text for clone-detection renaming, an unstructured
#: EVALUATE selector). Shared so a future fix to what counts as an
#: identifier token does not have to be made in more than one place.
IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

#: Same, but also matches a token that *starts* with a digit. Only where a
#: stray non-identifier match is harmless -- the caller looks every match up
#: against a name map, so a digit-led word (part of a numeric literal, say)
#: simply never matches anything real.
RELAXED_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


def base_data_name(ref: str) -> str:
    """Return the referenced data item's own name from a folded reference.

    ``"WS-NUM OF GRP-1"`` / ``"WS-NUM IN GRP-1"`` / ``"WS-TAB ( 3 )"`` /
    ``"WS-TAB OF GRP ( IDX )"`` all yield the first word. Anything else --
    a bare name, a quoted literal (even one containing spaces), a
    figurative constant like ``ALL 'X'`` -- is returned unchanged: the
    first word is only split off when what follows is a recognized
    qualifier keyword or subscript group, so a literal's content is never
    truncated.
    """
    parts = ref.split()
    if len(parts) >= 2 and (parts[1].upper() in ("OF", "IN") or parts[1] == "("):
        return parts[0]
    return ref
