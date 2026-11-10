"""The one traversal API over the AST: paragraphs, statements, nested bodies.

Analyzers kept private copies of the same few walks (every paragraph of a
PROCEDURE DIVISION, a unit's statements without its contained programs'),
and the copies drifted: one listed section paragraphs after top-level ones,
one deduplicated and sorted, one excluded a contained program's statements
by AST child and so kept the ones held in clause attributes. These are the
shared versions.

::

    from cobolparser.models.walk import all_paragraphs, own_statements

    for paragraph in all_paragraphs(ast.procedure_division):
        ...
    calls = [s for s in own_statements(unit) if isinstance(s, CallStatement)]
"""

from __future__ import annotations

from .program import CobolDivision, CobolParagraph, CobolProgram
from .statements.base import CobolStatement, iter_clause_bodies, walk_statements


def _in_source_order(paragraphs: list[CobolParagraph]) -> list[CobolParagraph]:
    unique = list({id(p): p for p in paragraphs}.values())
    if any(p.location is None for p in unique):
        return unique  # a hand-built tree: keep the order it was built in
    return sorted(unique, key=lambda p: (p.location.line, p.location.column))


def all_paragraphs(division: CobolDivision | None) -> list[CobolParagraph]:
    """Every paragraph of a PROCEDURE DIVISION, in source order: those
    written before the first SECTION header and every section's, each once.

    The unnamed paragraph holding statements written before the first
    paragraph name is included (``ProcedureIndex`` leaves it out, as no one
    can name it). ``None`` gives ``[]``.
    """
    if division is None:
        return []
    paragraphs = list(division.paragraphs)
    for section in division._sections.values():
        paragraphs.extend(section.paragraphs)
    return _in_source_order(paragraphs)


def section_paragraphs(
    division: CobolDivision | None,
) -> list[tuple[str | None, CobolParagraph]]:
    """:func:`all_paragraphs`, each paired with the upper-cased name of the
    section that owns it (``None`` outside any section, or for a section
    with no name)."""
    if division is None:
        return []
    owner: dict[int, str | None] = {}
    for section in division._sections.values():
        name = (section.section_name or "").upper() or None
        for para in section.paragraphs:
            owner.setdefault(id(para), name)
    return [(owner.get(id(p)), p) for p in all_paragraphs(division)]


def own_statements(unit: CobolProgram) -> list[CobolStatement]:
    """*unit*'s statements, nested ones included, without those of the
    programs it contains.

    ``get_all_statements()`` walks children, and a contained program is a
    child, so an inner unit's ``CALL`` or ``PERFORM`` would otherwise read
    as the outer unit's (#274). Exclusion is by the contained programs' own
    ``get_all_statements()``, so a statement a contained program holds in a
    clause attribute (not an AST child) is excluded too.
    """
    statements = unit.get_all_statements()
    if not unit.contained_programs:
        return list(statements)
    inner = {
        id(statement)
        for contained in unit.contained_programs
        for statement in contained.get_all_statements()
    }
    return [s for s in statements if id(s) not in inner]


__all__ = [
    "all_paragraphs",
    "iter_clause_bodies",
    "own_statements",
    "section_paragraphs",
    "walk_statements",
]
