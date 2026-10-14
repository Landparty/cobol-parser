"""The procedure an ``EXEC SQL WHENEVER ... GO TO`` directive branches to.

``WHENEVER SQLERROR|SQLWARNING|NOT FOUND GO TO p`` makes the precompiler
put a ``GO TO p`` after every SQL statement it covers, so ``p`` is a branch
target as real as any written GO TO. Shared by the dead-code analyzer (a
reference) and program flow (an edge) so the two cannot disagree on what a
directive names.
"""

from __future__ import annotations

import re
from typing import Any

#: ``GO TO`` / ``GOTO``, then the target -- optionally written as
#: ``:host-label`` (DB2 accepts both). The EXEC text collector glues a colon
#: onto the word before it (``GOTO:NF-PARA``), so no space is required
#: around it.
_WHENEVER_GOTO_RE = re.compile(
    r"^\s*WHENEVER\s+(?:NOT\s+FOUND|SQLERROR|SQLWARNING)\s+GO\s*TO\s*:?\s*"
    r"([A-Za-z0-9][A-Za-z0-9-]*)\s*$",
    re.IGNORECASE,
)


def whenever_goto_target(stmt: Any) -> str | None:
    """The procedure name a ``WHENEVER ... GO TO`` names, else ``None``.

    ``None`` for every other SQL statement and for the ``CONTINUE`` action.
    """
    if (getattr(stmt, "sql_type", None) or "").upper() != "WHENEVER":
        return None
    match = _WHENEVER_GOTO_RE.match(getattr(stmt, "sql_text", None) or "")
    return match.group(1).upper() if match else None
