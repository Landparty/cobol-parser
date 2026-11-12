"""Group items whose layout has a hole where a ``COPY`` was not expanded.

When a member is not on the copybook path, the parser blanks its ``COPY``
statement and says so in a warning; the unit keeps the blanked line ranges
in :attr:`~cobolparser.models.program.CobolProgram.omitted_copy_lines`. A
group declared around such a ``COPY`` (``01 WS-GMO. COPY CMQGMOV.``) parses
with only the fields that were written out, so any length computed for it --
zero bytes for a group that held nothing but the ``COPY`` -- is short by the
member's fields. An analyzer comparing lengths has to leave such a group
out rather than report the shortfall as a finding.
"""

from __future__ import annotations

from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram

#: Level numbers that never own storage of their own.
_NON_STORAGE_LEVELS = (66, 88)


def items_with_copy_holes(unit: CobolProgram) -> set[int]:
    """``id()`` of every group item of *unit* whose extent holds a ``COPY``
    that was not expanded.

    A group's extent runs from its own line to the line before the next
    item at its level or above (its next sibling, or the next record). A
    blanked ``COPY`` starting inside it belongs to it -- and, the extents
    being nested, to every group around it. Elementary items are never
    reported: a ``COPY`` after one belongs to the group that holds it.
    """
    holes = getattr(unit, "omitted_copy_lines", ()) or ()
    if not holes:
        return set()
    items = [
        item
        for item in unit.get_data_items()
        if isinstance(item, CobolDataItem)
        and item.location is not None
        and item.level not in _NON_STORAGE_LEVELS
    ]
    items.sort(key=lambda item: item.location.line)
    procedure = unit.procedure_division
    # A COPY in the PROCEDURE DIVISION is no record's.
    last: float = (
        procedure.location.line - 1
        if procedure is not None and procedure.location is not None
        else float("inf")
    )
    found: set[int] = set()
    for at, item in enumerate(items):
        if item.picture_clause is not None:
            continue
        start = item.location.line
        end = last
        for later in items[at + 1 :]:
            if _level_rank(later.level) <= _level_rank(item.level):
                end = later.location.line - 1
                break
        if any(start < first <= end for first, _last in holes):
            found.add(id(item))
    return found


def _level_rank(level: int) -> int:
    """01 and 77 both start a new record."""
    return 1 if level == 77 else level
