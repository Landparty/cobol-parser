"""Static CALLs of abend services that never return to the caller."""

from __future__ import annotations

from typing import Any

from ..models.statements.call import CallStatement

#: IBM abend services that end the run unit and never return: Language
#: Environment's CEE3ABD ("CEE3ABD does not return", ``le_signatures``) and
#: the COBOL library's ILBOABN0. Site-specific abend modules (``ABEND``,
#: ``CKRABEND``) are left out: whether they return is not known here.
NON_RETURNING_ABEND_PROGRAMS = frozenset({"CEE3ABD", "ILBOABN0"})


def abend_call_target(stmt: Any) -> str | None:
    """The abend service *stmt* CALLs statically, or None.

    Only a literal ``CALL 'CEE3ABD'`` counts: a dynamic CALL through a data
    name may name any program at run time.
    """
    if not isinstance(stmt, CallStatement) or stmt.is_dynamic:
        return None
    target = (stmt.called_program or "").strip().strip("'\"").upper()
    return target if target in NON_RETURNING_ABEND_PROGRAMS else None
