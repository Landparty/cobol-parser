"""EXEC CICS commands that end the paragraph's flow of control.

Three CICS commands never hand control back to the statement after them:
``RETURN`` gives control back to CICS (or to the LINKing program), ``XCTL``
transfers it to another program for good, and ``ABEND`` ends the task. For
the PROCEDURE DIVISION analyzers they are terminators, like GOBACK.

The one exception is a RETURN or XCTL that *fails* (``INVREQ``, ``PGMIDERR``,
...) while the command carries ``RESP``, ``RESP2`` or ``NOHANDLE``: CICS then
records the condition and execution continues at the next statement, so such
a command is not a terminator (issue #392, option (a)). ABEND has no failure
path and is always a terminator.
"""

from typing import Any

#: Command verb -> whether a ``RESP``/``RESP2``/``NOHANDLE`` option lets
#: execution continue after it.
_TERMINATING_COMMANDS: dict[str, bool] = {
    "RETURN": True,
    "XCTL": True,
    "ABEND": False,
}

_CONTINUE_ON_ERROR_OPTIONS = frozenset({"RESP", "RESP2", "NOHANDLE"})


def cics_exit_kind(stmt: Any) -> str | None:
    """``"EXEC CICS RETURN"`` / ``"... XCTL"`` / ``"... ABEND"`` when *stmt*
    is one of those commands, else ``None``.

    Such a command leaves the program whenever it succeeds, RESP or not, so
    it is a way out of a loop and an exit point even when it is not a
    terminator (:func:`cics_terminator_kind`)."""
    if getattr(stmt, "node_type", None) != "EXEC_CICS":
        return None
    command = (getattr(stmt, "cics_command", "") or "").upper()
    if command not in _TERMINATING_COMMANDS:
        return None
    return f"EXEC CICS {command}"


def cics_terminator_kind(stmt: Any) -> str | None:
    """:func:`cics_exit_kind` when *stmt* never returns control to the next
    statement, else ``None``: a RETURN / XCTL carrying RESP, RESP2 or
    NOHANDLE continues there when it fails."""
    kind = cics_exit_kind(stmt)
    if kind is None:
        return None
    command = kind.removeprefix("EXEC CICS ")
    if _TERMINATING_COMMANDS[command]:
        options = getattr(stmt, "options", None) or {}
        if any(key.upper() in _CONTINUE_ON_ERROR_OPTIONS for key in options):
            return None
    return kind
