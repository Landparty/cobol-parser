"""Shared FILE SECTION lookups for the I/O analyzers.

``WRITE`` and ``REWRITE`` name a *record*, never a file (``WRITE OUT-REC``),
so no parser ever populates ``file_name`` on :class:`IOWriteStatement` /
:class:`IORewriteStatement` -- only ``record_name``. An analyzer keyed by
file name (which file is open, which file a WRITE targets) must resolve the
record back to the FD/SD that owns it. The DATA DIVISION parser records that
ownership as ``fd_file_name`` metadata on every 01-level FILE SECTION item;
this module is the one place that mapping is read from, so the CRUD matrix,
the sequence checker and the I/O logger cannot disagree about it.
"""

from __future__ import annotations

from ..models.program import CobolProgram


def record_to_file_map(ast: CobolProgram) -> dict[str, str]:
    """Map every FILE SECTION record name to the file its FD/SD declares.

    Keys and values are upper-cased. Empty when the program has no FILE
    SECTION (or the records carry no ``fd_file_name`` metadata).
    """
    mapping: dict[str, str] = {}
    data_div = ast.get_division("DATA")
    if data_div is None:
        return mapping
    file_section = data_div._sections.get("FILE")
    if file_section is None:
        return mapping
    for item in file_section.data_items:
        fd_file = item.get_metadata("fd_file_name")
        name = getattr(item, "name", None)
        if fd_file and name:
            mapping[name.upper()] = str(fd_file).upper()
    return mapping


def resolve_file_name(
    file_name: str | None,
    record_name: str | None,
    record_map: dict[str, str],
) -> str | None:
    """The file a statement targets: its own ``file_name`` when the parser
    set one, else the FD that owns ``record_name``, else ``None``."""
    if file_name:
        return file_name
    if record_name:
        return record_map.get(record_name.upper())
    return None
