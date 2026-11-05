"""Which procedures ``EXEC SQL WHENEVER ... GO TO`` sends each SQL statement to.

``WHENEVER SQLERROR|SQLWARNING|NOT FOUND GO TO p`` is a precompiler
directive, not an executed statement: it makes the precompiler put a
``GO TO p`` after every executable SQL statement that follows it *in source
order*, until another WHENEVER for the same condition replaces it
(``CONTINUE`` switches it off). So the branch to ``p`` comes from the SQL
statements the directive covers, wherever they sit, and not from the
paragraph that holds the directive -- that one may never run at all (a
"SQL setup" paragraph written ahead of the code it covers).

Shared by the dead-code analyzer (a reference) and program flow (an edge)
so the two cannot disagree on what a directive covers.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.sql_statements import ExecSQLStatement

#: ``WHENEVER <condition> <action>``. The action is ``GO TO`` / ``GOTO`` and
#: a target -- optionally written as ``:host-label`` (DB2 accepts both) -- or
#: ``CONTINUE``. The EXEC text collector glues a colon onto the word before
#: it (``GOTO:NF-PARA``), so no space is required around it.
_WHENEVER_RE = re.compile(
    r"^\s*WHENEVER\s+(NOT\s+FOUND|SQLERROR|SQLWARNING)\s+"
    r"(?:(CONTINUE)|GO\s*TO\s*:?\s*([A-Za-z0-9][A-Za-z0-9-]*))\s*$",
    re.IGNORECASE,
)

#: Precompiler declarations: no SQLCODE is set, so no branch is generated.
_NON_EXECUTABLE_SQL_TYPES = frozenset(
    {"DECLARE CURSOR", "DECLARE TABLE", "INCLUDE", "WHENEVER"}
)
_NON_EXECUTABLE_PREFIXES = ("BEGIN DECLARE SECTION", "END DECLARE SECTION")
#: ``DECLARE GLOBAL TEMPORARY TABLE`` is an executable statement (it sets
#: SQLCODE, so WHENEVER covers it) even though the parser files it under
#: ``DECLARE TABLE`` with the DCLGEN declarations.
_EXECUTABLE_DECLARE_PREFIXES = ("DECLARE GLOBAL TEMPORARY TABLE",)
#: Db2's other two declarations, which the parser files as ``UNKNOWN``:
#: ``DECLARE s1, s2 STATEMENT`` and ``DECLARE :hv1, :hv2 VARIABLE ...``
#: (the collector glues the colon on: ``DECLARE:WS-STMT``) (#830).
_DECLARE_STATEMENT_OR_VARIABLE_RE = re.compile(
    r"^DECLARE\s*:?\s*[A-Z0-9@#$_-]+(?:\s*,\s*:?\s*[A-Z0-9@#$_-]+)*\s+"
    r"(?:STATEMENT|VARIABLE)\b"
)


def _directive(stmt: Any) -> tuple[str, str | None] | None:
    """``(condition, target)`` for a WHENEVER (target ``None`` for
    ``CONTINUE``), else ``None``."""
    if (getattr(stmt, "sql_type", None) or "").upper() != "WHENEVER":
        return None
    match = _WHENEVER_RE.match(getattr(stmt, "sql_text", None) or "")
    if match is None:
        return None
    condition = " ".join(match.group(1).split()).upper()
    return condition, (match.group(3).upper() if match.group(3) else None)


def whenever_goto_target(stmt: Any) -> str | None:
    """The procedure a ``WHENEVER ... GO TO`` names, else ``None``.

    ``None`` for every other SQL statement and for the ``CONTINUE`` action.
    """
    directive = _directive(stmt)
    return directive[1] if directive else None


def _is_executable(stmt: ExecSQLStatement) -> bool:
    text = " ".join((stmt.sql_text or "").upper().split())
    if text.startswith(_EXECUTABLE_DECLARE_PREFIXES):
        return True
    if (stmt.sql_type or "").upper() in _NON_EXECUTABLE_SQL_TYPES:
        return False
    if _DECLARE_STATEMENT_OR_VARIABLE_RE.match(text):
        return False
    return not text.startswith(_NON_EXECUTABLE_PREFIXES)


def whenever_coverage(statements: list[Any]) -> dict[int, list[str]]:
    """For each executable SQL statement in *statements* (by ``id``), the
    procedure names the WHENEVER directives in effect at it branch to.

    Directives apply in source order (line, then column), so *statements*
    may come in any order. A statement no ``GO TO`` directive covers is left
    out.
    """
    sql = [s for s in statements if isinstance(s, ExecSQLStatement)]
    sql.sort(
        key=lambda s: ((s.location.line, s.location.column) if s.location else (0, 0))
    )
    in_effect: dict[str, str | None] = {}
    coverage: dict[int, list[str]] = {}
    for stmt in sql:
        directive = _directive(stmt)
        if directive is not None:
            in_effect[directive[0]] = directive[1]
            continue
        if not _is_executable(stmt):
            continue
        targets = sorted({t for t in in_effect.values() if t})
        if targets:
            coverage[id(stmt)] = targets
    return coverage
