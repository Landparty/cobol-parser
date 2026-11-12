"""Static CALLs of abend services that never return to the caller."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from ..models.statements.call import CallStatement

#: IBM abend services that end the run unit and never return: Language
#: Environment's CEE3ABD ("CEE3ABD does not return", ``le_signatures``) and
#: the COBOL library's ILBOABN0. Site-specific abend modules (``ABEND``,
#: ``CKRABEND``) are left out: whether they return is not known here. A
#: site names its own with :func:`set_site_abend_programs` (the CLI's
#: ``--abend-program`` / ``project.abend_programs`` in ``cobol.yml``).
NON_RETURNING_ABEND_PROGRAMS = frozenset({"CEE3ABD", "ILBOABN0"})

#: The site's own non-returning abend routines (``CBLTBNC2``, ``CSDABEND``
#: ...), upper-cased. Process-wide: set it in the process that analyzes,
#: as the CLI does for each file it parses.
_site_abend_programs: frozenset[str] = frozenset()

#: :func:`using_site_abend_programs`' list, for the thread that entered the
#: block only. Thread-local, so two threads of one process (the MCP server's
#: tool call and its index warm-up) each see their own list: a process-wide
#: swap restored by one thread would cut the list from under the other.
_scoped = threading.local()


def _normalize(names: Iterable[str]) -> frozenset[str]:
    return frozenset(
        n.strip().strip("'\"").upper() for n in names if n and n.strip().strip("'\"")
    )


def set_site_abend_programs(names: Iterable[str] | None) -> None:
    """Treat a static ``CALL`` of any of *names* as never returning, like
    ``CALL 'CEE3ABD'``; ``None`` or empty clears the list."""
    global _site_abend_programs
    _site_abend_programs = _normalize(names or ())


def site_abend_programs() -> frozenset[str]:
    """The site's abend routines in effect (upper-cased): the innermost
    :func:`using_site_abend_programs` block of this thread, else what
    :func:`set_site_abend_programs` set."""
    scoped: frozenset[str] | None = getattr(_scoped, "names", None)
    return _site_abend_programs if scoped is None else scoped


@contextmanager
def using_site_abend_programs(names: Iterable[str] | None) -> Iterator[None]:
    """:func:`set_site_abend_programs` for the ``with`` block only, and only
    in the thread that entered it."""
    saved = getattr(_scoped, "names", None)
    _scoped.names = _normalize(names or ())
    try:
        yield
    finally:
        _scoped.names = saved


def is_abend_program(name: str | None) -> bool:
    """Whether a CALL of program *name* never returns: an IBM abend service
    or one of the site's own (:func:`set_site_abend_programs`)."""
    target = (name or "").strip().strip("'\"").upper()
    return target in NON_RETURNING_ABEND_PROGRAMS or target in site_abend_programs()


def abend_call_target(stmt: Any) -> str | None:
    """The abend service *stmt* CALLs statically, or None.

    Only a literal ``CALL 'CEE3ABD'`` counts: a dynamic CALL through a data
    name may name any program at run time.
    """
    if not isinstance(stmt, CallStatement) or stmt.is_dynamic:
        return None
    target = (stmt.called_program or "").strip().strip("'\"").upper()
    return target if is_abend_program(target) else None
