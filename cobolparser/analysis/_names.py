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
