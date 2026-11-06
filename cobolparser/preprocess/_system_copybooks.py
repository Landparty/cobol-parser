"""Stand-ins for the IBM-supplied copybooks a CICS program COPYs.

``COPY DFHAID`` and ``COPY DFHBMSCA`` name members that live in the CICS
libraries (``SDFHCOB``), not in the application's repository, so a program
that COPYs them cannot be expanded from the repository alone. The
``system_copybooks/`` folder next to this module holds a stand-in for each:
the same field names and PICTUREs, with the EBCDIC VALUEs as hex literals.

:func:`with_system_copybooks` appends that folder to a copybook search path,
*last*, so a real copy of the member anywhere on the caller's path wins.
"""

from pathlib import Path

#: The folder holding the stand-in members.
SYSTEM_COPYBOOK_DIR = Path(__file__).with_name("system_copybooks")

#: The members it holds, upper-cased.
SYSTEM_COPYBOOKS: frozenset[str] = frozenset(
    p.stem.upper() for p in SYSTEM_COPYBOOK_DIR.glob("*.cpy")
)


def with_system_copybooks(copybook_paths: list[str]) -> list[str]:
    """*copybook_paths* with the stand-in folder appended (once), or
    unchanged when it is empty: without a search path no COPY is expanded
    at all, so there is nothing for a stand-in to complete."""
    if not copybook_paths:
        return list(copybook_paths)
    folder = str(SYSTEM_COPYBOOK_DIR)
    if folder in copybook_paths:
        return list(copybook_paths)
    return [*copybook_paths, folder]
