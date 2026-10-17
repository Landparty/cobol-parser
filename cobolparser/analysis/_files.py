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


def report_to_file_map(ast: CobolProgram) -> dict[str, str]:
    """Map every Report Writer report *and* report-group name to its file.

    A report file (``FD f REPORT IS r``) has no record description and is
    written only by ``INITIATE r`` / ``GENERATE r-or-group`` /
    ``TERMINATE r``, so a WRITE-keyed analyzer never sees it written. The
    FILE SECTION carries ``report_files`` metadata (report -> FD); each
    REPORT SECTION 01 group carries ``rd_report_name``. Keys and values are
    upper-cased; empty when the program uses no Report Writer.
    """
    mapping: dict[str, str] = {}
    data_div = ast.get_division("DATA")
    if data_div is None:
        return mapping
    file_section = data_div._sections.get("FILE")
    if file_section is not None:
        for report, file_name in (
            file_section.get_metadata("report_files") or {}
        ).items():
            mapping[str(report).upper()] = str(file_name).upper()
    report_section = data_div._sections.get("REPORT")
    if report_section is not None:
        for item in report_section.data_items:
            report = item.get_metadata("rd_report_name")
            name = getattr(item, "name", None)
            file_name = mapping.get(str(report).upper()) if report else None
            if name and file_name and name.upper() not in mapping:
                mapping[name.upper()] = file_name
    return mapping


def report_writer_files(stmt: object, report_map: dict[str, str]) -> list[str]:
    """The report files an ``INITIATE`` / ``GENERATE`` / ``TERMINATE`` writes.

    Upper-cased, in operand order, without duplicates; empty for any other
    statement or for a report name ``report_map`` cannot place. INITIATE
    and TERMINATE write too (page/report headings and footings).
    """
    names: list[str] = []
    stype = getattr(stmt, "statement_type", "")
    if stype == "GENERATE":
        name = getattr(stmt, "report_name", None)
        names = [name] if name else []
    elif stype in ("INITIATE", "TERMINATE"):
        names = list(getattr(stmt, "report_names", None) or [])
    files: list[str] = []
    for name in names:
        file_name = report_map.get(str(name).upper())
        if file_name and file_name not in files:
            files.append(file_name)
    return files


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
