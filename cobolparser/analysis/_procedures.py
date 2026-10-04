"""Procedure identity for the PROCEDURE DIVISION analyzers.

COBOL lets two sections each hold a paragraph of the same name (``X1`` in
``S1`` and ``X1`` in ``S2``), told apart by qualification: ``PERFORM X1 OF
S2``. Keying procedures by bare name merged those two into one, so the
second paragraph vanished from the flow graph and a reference to either kept
both alive (issue #258).

:class:`ProcedureIndex` gives every procedure a unique *key*: its bare name
when that name is unique in the program, and ``"<para> OF <section>"`` when
the name is shared. A program with no shared names therefore keys exactly as
before. :meth:`ProcedureIndex.resolve` maps a reference to the key(s) it can
mean, applying the COBOL rule: the qualifier when there is one, otherwise the
paragraph of that name in the referencing statement's own section, otherwise
the name when it is unique. A reference the compiler would reject as
ambiguous resolves to every candidate, so it can never make live code look
dead.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..models.program import CobolDivision, CobolParagraph, CobolSection


def qualify(name: str, section: str) -> str:
    """The qualified key of paragraph *name* in *section*."""
    return f"{name} OF {section}"


def is_valid_procedure_name(name: str | None) -> bool:
    """Whether *name* looks like a real COBOL procedure name (the parser can
    leave a synthetic ``"."`` paragraph behind)."""
    return bool(name) and name not in (".",)


@dataclass
class ProcedureEntry:
    """One paragraph or section of the PROCEDURE DIVISION."""

    key: str
    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    #: Upper-cased owning section of a paragraph, ``None`` for a section or
    #: a paragraph written outside any section.
    section: str | None
    node: CobolParagraph | CobolSection

    @property
    def location(self) -> Any:
        return self.node.location

    @property
    def qualified_name(self) -> str | None:
        """The key, when it differs from the bare name (a shared name)."""
        return self.key if self.key != self.name else None


class ProcedureIndex:
    """Every named procedure of one PROCEDURE DIVISION, in source order."""

    def __init__(self, entries: list[ProcedureEntry]) -> None:
        self.entries = entries
        self.by_key: dict[str, ProcedureEntry] = {e.key: e for e in entries}
        self._by_name: dict[str, list[str]] = {}
        for e in entries:
            self._by_name.setdefault(e.name, []).append(e.key)

    @classmethod
    def build(cls, proc_division: CobolDivision) -> "ProcedureIndex":
        """Index *proc_division*'s sections and named paragraphs.

        Sections and top-level paragraphs are interleaved by source line
        (COBOL allows paragraphs before the first SECTION header). A second
        procedure claiming a key already taken -- two same-named paragraphs
        in one section, or outside any section, which the compiler rejects --
        is dropped, as the name-keyed analyzers always did.
        """
        top_level: list[Any] = sorted(
            [*proc_division._sections.values(), *proc_division.paragraphs],
            key=lambda item: item.location.line,
        )
        raw: list[tuple[str, str, str | None, Any]] = []
        for item in top_level:
            if isinstance(item, CobolSection):
                sec = item.section_name.upper() if item.section_name else None
                if sec:
                    raw.append((sec, "SECTION", None, item))
                for para in item.paragraphs:
                    if is_valid_procedure_name(para.paragraph_name):
                        raw.append(
                            (para.paragraph_name.upper(), "PARAGRAPH", sec, para)
                        )
            elif is_valid_procedure_name(item.paragraph_name):
                raw.append((item.paragraph_name.upper(), "PARAGRAPH", None, item))

        sections_per_name: dict[str, set[str | None]] = {}
        for name, ptype, sec, _ in raw:
            sections_per_name.setdefault(name, set()).add(
                sec if ptype == "PARAGRAPH" else None
            )

        entries: list[ProcedureEntry] = []
        taken: set[str] = set()
        for name, ptype, sec, node in raw:
            shared = len(sections_per_name[name]) > 1
            key = qualify(name, sec) if shared and sec else name
            if key in taken:
                continue
            taken.add(key)
            entries.append(ProcedureEntry(key, name, ptype, sec, node))
        return cls(entries)

    @property
    def keys(self) -> list[str]:
        return [e.key for e in self.entries]

    def section_of(self, key: str | None) -> str | None:
        """The section a procedure belongs to (a section is its own)."""
        entry = self.by_key.get(key or "")
        if entry is None:
            return None
        return entry.key if entry.procedure_type == "SECTION" else entry.section

    def candidates(self, name: str) -> list[str]:
        """Every key a bare *name* can mean."""
        return list(self._by_name.get(name.upper(), []))

    def resolve(
        self,
        name: str | None,
        qualifier: str | None = None,
        from_section: str | None = None,
    ) -> list[str]:
        """The procedure key(s) a reference to *name* means.

        Args:
            name: The referenced paragraph or section name.
            qualifier: The section named by ``OF``/``IN``, if any.
            from_section: The section the referencing statement sits in.

        Returns:
            One key for a reference that resolves, every candidate for one
            that is ambiguous, and ``[NAME]`` for a name that is not a
            procedure of this program (callers keep such targets as-is).
        """
        if not name:
            return []
        upper = name.strip().upper()
        cands = self._by_name.get(upper)
        if not cands:
            return [upper]
        if len(cands) == 1:
            return list(cands)
        if qualifier:
            q = qualifier.strip().upper()
            match = [k for k in cands if self.by_key[k].section == q]
            if match:
                return match
        if from_section:
            match = [k for k in cands if self.by_key[k].section == from_section]
            if match:
                return match
        # The compiler would reject this reference as ambiguous: keep every
        # candidate, so it can only ever keep code alive, never hide it.
        return list(cands)

    def resolve_one(
        self,
        name: str | None,
        qualifier: str | None = None,
        from_section: str | None = None,
    ) -> str | None:
        """Like :meth:`resolve` but the first key only (for THRU range ends,
        where a range needs one endpoint)."""
        keys = self.resolve(name, qualifier, from_section)
        return keys[0] if keys else None


def enclosing_section(stmt: Any) -> str | None:
    """The upper-cased name of the section *stmt* is written in, if any."""
    node = getattr(stmt, "parent", None)
    while node is not None:
        if isinstance(node, CobolSection):
            return node.section_name.upper() if node.section_name else None
        node = getattr(node, "parent", None)
    return None


def statement_qualifier(stmt: Any, key: str) -> str | None:
    """A qualifier the parser recorded in *stmt*'s metadata (``target_
    qualifier`` / ``thru_qualifier``)."""
    meta = getattr(stmt, "metadata", None) or {}
    value = meta.get(key)
    return str(value) if value else None


def unique(keys: Iterable[str]) -> list[str]:
    """*keys* with duplicates removed, order kept."""
    return list(dict.fromkeys(keys))
