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


def same_record_area_groups(ast: CobolProgram | None) -> list[list[str]]:
    """The files whose records share one storage area, one list per group.

    Read from the ``I-O-CONTROL`` paragraph's ``SAME RECORD AREA FOR f1 f2
    ...`` entries (the INPUT-OUTPUT section's ``io_control`` metadata).
    Under it every record of every named file is an implicit REDEFINES of
    one area -- across FDs, the way the 01 records under one FD always
    are -- so an analyzer that treats storage as per-FD must widen its
    alias classes to these groups. Plain ``SAME AREA`` (and ``SAME SORT``
    / ``SORT-MERGE AREA``) shares no records and is not returned. Groups
    that name a common file are merged; names are upper-cased, groups of
    fewer than two files are dropped.
    """
    if ast is None:
        return []
    env = ast.get_division("ENVIRONMENT")
    if env is None:
        return []
    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for section in getattr(env, "sections", None) or []:
        get_metadata = getattr(section, "get_metadata", None)
        entries = get_metadata("io_control") if callable(get_metadata) else None
        for entry in entries or []:
            if not isinstance(entry, dict) or entry.get("clause") != "SAME":
                continue
            if entry.get("area") != "RECORD":
                continue
            files = [str(f).upper() for f in entry.get("files") or [] if f]
            for other in files[1:]:
                root_a, root_b = find(files[0]), find(other)
                if root_a != root_b:
                    parent[root_b] = root_a
    groups: dict[str, list[str]] = {}
    for name in parent:
        groups.setdefault(find(name), []).append(name)
    return [members for members in groups.values() if len(members) > 1]
