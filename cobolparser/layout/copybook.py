"""Copybook parsing: a COPY member (or a whole program) to its 01 records.

Wraps a bare DATA DIVISION fragment in a minimal program skeleton, parses
it, and picks the record a caller asked for.  The CSV / record-image
generator built on this lives in :mod:`cobolparser.generators.data.copybook`.
"""

from __future__ import annotations

import os
import re

from .._lines import split_source_lines
from .._source_text.source_format import detect_member_fixed_format
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..parser import parse_cobol, parse_cobol_with_expansion
from ..plugins.core import ErrorRecoveryMode
from ..preprocess import PreprocessingError
from .errors import CopybookLayoutError

# ---------------------------------------------------------------------------
# Copybook parsing
# ---------------------------------------------------------------------------

# A copybook is a DATA DIVISION fragment, not a compilable program, so it is
# wrapped in a minimal program skeleton before being handed to the parser.
_WRAPPER_HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. COPYBOOK-LAYOUT.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
_WRAPPER_TAIL = "       PROCEDURE DIVISION.\n           CONTINUE.\n"

_PROGRAM_RE = re.compile(r"^\s*IDENTIFICATION\s+DIVISION\s*\.", re.IGNORECASE | re.M)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\s*\.", re.IGNORECASE | re.M)


def _looks_like_program(source: str) -> bool:
    """True when *source* is a whole program rather than a bare fragment."""
    return bool(_PROGRAM_RE.search(source) or _PROGRAM_ID_RE.search(source))


def _wrap_fragment(source: str) -> str:
    """Embed a copybook fragment in a minimal, parseable program skeleton.

    The fragment's format comes from the one member detector copybook
    expansion uses (:func:`detect_member_fixed_format`), so a copybook reads
    the same through gen-data, decode, data-items and the MCP server as it
    does when a program copies it. A fixed-format fragment keeps its columns
    but has its sequence area (columns 1-6) blanked: IBM never reads it, and
    a change tag left there (``CGOGP1``, ``CR 12``) would otherwise make the
    wrapped program look free-form to the parse's own detector.
    """
    if detect_member_fixed_format(source.expandtabs(8)):
        body = "\n".join(
            " " * 6 + line[6:] if len(line) > 6 else ""
            for line in split_source_lines(source.expandtabs(8))
        )
    else:
        # Free-form fragment: shift into Area B so the fixed-format wrapper and
        # the fragment agree on a single column convention.
        body = "\n".join(
            "       " + line if line.strip() else ""
            for line in split_source_lines(source)
        )
    if not body.endswith("\n"):
        body += "\n"
    return _WRAPPER_HEAD + body + _WRAPPER_TAIL


#: Lines :func:`_wrap_fragment` puts in front of a fragment's first line.
WRAPPER_HEAD_LINES = _WRAPPER_HEAD.count("\n")
_DIVISION_HEADER_RE = re.compile(
    r"\b(?:IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.IGNORECASE
)


def wrap_copybook_fragment(source: str) -> str | None:
    """*source* wrapped in the program skeleton :func:`parse_copybook_records`
    parses a copybook through, or ``None`` when *source* is not a bare
    fragment (it names a division or a ``PROGRAM-ID``, or holds no code).

    The fragment's line *n* is line ``n + WRAPPER_HEAD_LINES`` of the result.
    For the tools that take any source file -- ``data-items``, the MCP
    server -- so a copybook answers the way it does for gen-data and decode
    rather than as a program with no divisions (#536).
    """
    if not source.strip() or _looks_like_program(source):
        return None
    if _DIVISION_HEADER_RE.search(source):
        return None
    return _wrap_fragment(source)


def parse_copybook_records(
    source: str,
    *,
    filename: str = "<copybook>",
    copybook_paths: list[str] | None = None,
    warnings: list[str] | None = None,
) -> list[CobolDataItem]:
    """Parse *source* and return its record roots (the level-01/77 items).

    Accepts either a bare copybook fragment or a complete COBOL program; a
    fragment is wrapped in a program skeleton first.  Parsing runs in
    ``COLLECT_ALL`` recovery so an unrelated defect elsewhere in a program
    still yields the data items that did parse.

    With ``copybook_paths``, every ``COPY`` -- one nested in the copybook,
    or one under a whole program's FD -- is expanded from those directories
    first, the way ``parse`` and ``gen-fixtures`` do.  A ``COPY`` that is not
    expanded (no paths given, or its member not found in them) leaves a hole
    in the record: its fields are missing and the record is too short.  Each
    such ``COPY`` appends one sentence saying so to *warnings*, so a caller
    can report the short layout rather than silently generate or decode
    through it.

    Raises:
        CopybookLayoutError: if the source yields no usable record layout,
            or copybook expansion fails outright (a circular ``COPY``).
    """
    if not source.strip():
        raise CopybookLayoutError(f"{filename}: copybook is empty")

    text = source if _looks_like_program(source) else _wrap_fragment(source)
    if copybook_paths:
        try:
            result = parse_cobol_with_expansion(
                text,
                filename=filename,
                copybook_paths=list(copybook_paths),
                # A missing member is reported below like an unexpanded one,
                # not raised: the rest of the layout is still worth having.
                skip_missing_copybooks=True,
                error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            )
        except PreprocessingError as exc:
            raise CopybookLayoutError(
                f"{filename}: could not expand copybooks ({exc})"
            ) from exc
    else:
        result = parse_cobol(
            text,
            filename=filename,
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
    if warnings is not None:
        for warning in result.warnings:
            if _is_unexpanded_copy(warning) and warning not in warnings:
                warnings.append(warning)
    ast = result.ast
    if ast is None:
        detail = result.errors[0] if result.errors else "no AST produced"
        raise CopybookLayoutError(f"{filename}: could not parse copybook ({detail})")

    roots = _top_level_items(ast)
    records = [item for item in roots if item.level in (1, 77) and not item.is_filler]
    if records:
        return records

    # A copybook holding only subordinate items (level 02-49, no 01) is a
    # legitimate idiom: it is meant to be COPY'd *inside* an existing record.
    # Synthesise the record root its author assumed, so such a fragment is
    # still generatable rather than rejected.
    subordinate = [item for item in roots if 2 <= item.level <= 49]
    if subordinate:
        return [_synthesise_record(subordinate, filename)]

    raise CopybookLayoutError(
        f"{filename}: no level-01 record layout found in copybook"
    )


def _is_unexpanded_copy(warning: str) -> bool:
    """True for the parser's "COPY X was not expanded" warning.

    The parser blanks a ``COPY`` it was not given the text of and says so in
    exactly this form (see ``strip_unexpanded_copy_statements``); every other
    parse warning on a copybook fragment is noise to a record-layout caller.
    """
    return warning.startswith("COPY ") and " was not expanded" in warning


def _all_data_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return every data item in *ast*, outermost first, in source order."""
    items = ast.find_all_by_type("DataItem")
    return [item for item in items if isinstance(item, CobolDataItem)]


def _top_level_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return the data items that are not nested inside another data item."""
    items = _all_data_items(ast)
    nested = {id(child) for item in items for child in item.get_all_children()}
    return [item for item in items if id(item) not in nested]


def _synthesise_record(items: list[CobolDataItem], filename: str) -> CobolDataItem:
    """Wrap orphan subordinate items in a virtual level-01 record."""
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    # Reduce the stem to a legal COBOL data name: illegal characters become
    # hyphens, runs collapse, and leading/trailing hyphens are dropped, so the
    # placeholder filename "<copybook>" yields COPYBOOK-RECORD rather than
    # the malformed "-COPYBOOK--RECORD".
    name = re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]", "-", stem)).strip("-")
    root = CobolDataItem(f"{name or 'COPYBOOK'}-RECORD", 1, items[0].location)
    for item in items:
        root.add_child(item)
    return root


def select_record(
    records: list[CobolDataItem],
    record: str | None,
    filename: str = "<copybook>",
) -> CobolDataItem:
    """Pick the record called *record*, or the first one when it is ``None``.

    Module-level because both halves of the package need it and they need it
    to agree: generating data from ``--record CUST-REC`` and *decoding* a
    file through ``--record CUST-REC`` must land on the same 01, or a
    round-trip through the record image silently changes layout.

    Raises:
        CopybookLayoutError: if the named record is not one of *records*,
            listing the ones that are.
    """
    if record is None:
        return records[0]
    wanted = record.upper()
    for item in records:
        if item.name.upper() == wanted:
            return item
    available = ", ".join(item.name for item in records)
    raise CopybookLayoutError(
        f"{filename}: record '{record}' not found (available: {available})"
    )
