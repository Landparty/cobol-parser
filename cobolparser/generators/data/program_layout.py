"""Program-wide layout resolution: FD/record/field facts for a parsed program.

:class:`ProgramLayoutIndex` is the Phase 1 building block for program-scoped
test-data generation (``gen-fixtures``): it turns a parsed :class:`CobolProgram`
into name -> layout facts a boundary walker can join against, reusing the
:class:`~.layout.FieldSpec` / :func:`~.layout.flatten_record` value engine
Phase 0 lifted out of the copybook-specific generator.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from ...models.data_items import CobolDataItem, ConditionNameItem
from ...models.program import CobolProgram, CobolSection
from ...models.statements.misc import SelectStatement
from ...parser import parse_cobol
from ...preprocess import CircularReferenceError, CopybookNotFoundError
from ...preprocess.copybook_expander import parse_cobol_with_expansion
from .errors import ProgramLayoutError
from .layout import FieldSpec, expand_condition_values, flatten_record
from .options import DataGeneratorOptions

# Canonical section name (as CobolSection.section_name reports it) -> the
# normalized attribute name used throughout this module and the DATA DIVISION
# parser's own ``parse_division()`` result dict.
_SECTION_NAMES: dict[str, str] = {
    "FILE": "file",
    "WORKING-STORAGE": "working_storage",
    "LOCAL-STORAGE": "local_storage",
    "LINKAGE": "linkage",
}

# Splits a qualified reference on OF/IN ("A OF B", "A IN B OF C") -- COBOL's
# own disambiguation syntax for a name that exists at more than one path.
_OF_IN_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class FileFacts:
    """Physical/organizational facts about one FILE-CONTROL / FD-SD file.

    Merges the ENVIRONMENT DIVISION's ``SelectStatement`` (organization,
    access, keys) with the FILE SECTION's FD/SD clauses (record size,
    recording mode) -- two independent parses joined by uppercased file name.
    Either side may be absent (a SELECT with no matching FD, or vice versa);
    absence on one side leaves those fields ``None`` rather than guessing.
    """

    file_name: str
    organization: str | None = None
    access_mode: str | None = None
    record_key: str | None = None
    alternate_keys: tuple[dict[str, Any], ...] = ()
    relative_key: str | None = None
    file_status_field: str | None = None
    is_optional: bool = False
    record_contains: int | None = None
    record_contains_min: int | None = None
    record_contains_max: int | None = None
    recording_mode: str | None = None
    record_names: tuple[str, ...] = ()
    #: "FD" or "SD" -- an SD is a SORT/MERGE work file, not a file a program
    #: OPENs; mockymock refuses SORT/MERGE outright, and later phases key off
    #: this to mark such files ``unconstrained`` rather than mock-eligible.
    record_type: str = "FD"


@dataclass(frozen=True)
class ResolvedField:
    """A name resolved to one elementary field within one record."""

    spec: FieldSpec
    section: str  # "file" | "working_storage" | "local_storage" | "linkage"
    record: CobolDataItem  # the 01/77 root that owns it


class ProgramLayoutIndex:
    """Resolves file/record/field names to layout facts for one program.

    Build once per program via :meth:`build` (from an already-parsed
    ``CobolProgram``) or :meth:`from_file` (parses for you, optionally
    expanding copybooks). Every lookup method returns ``None`` rather than
    raising when a name is not found; genuine problems -- an ambiguous bare
    name, a FILE SECTION record with no owning FD -- are recorded on
    :attr:`ambiguities` / :attr:`unresolved` instead of being silently
    dropped or guessed.
    """

    def __init__(self) -> None:
        #: The program this index was built from (set by build()/from_file()).
        #: Lets a caller that only kept the index (e.g. across a from_file()
        #: call) still reach the AST without re-parsing.
        self.ast: CobolProgram | None = None
        self._records_by_file: dict[str, list[CobolDataItem]] = {}
        self._file_facts: dict[str, FileFacts] = {}
        self._name_index: dict[str, list[ResolvedField]] = {}
        # Level-88 condition name -> every parent field it resolves to. More
        # than one distinct parent (the same 88 name declared under fields in
        # different records) is an ambiguity: lookups refuse to guess, same
        # policy as resolve()/record_named().
        self._condition_index: dict[str, list[ResolvedField]] = {}
        #: Level-88 condition name -> that ONE condition name's own expanded
        #: VALUEs, kept in lockstep with ``_condition_index``. Distinct from
        #: ``FieldSpec.condition_values``, which is deliberately the *union*
        #: across every 88 under a field ("any value that could apply to this
        #: field" -- what the value factory wants). A caller asking what a
        #: *specific* condition name requires needs this one instead; see
        #: :meth:`condition_values`.
        self._condition_values: dict[str, list[list[str]]] = {}
        self._records_by_name: dict[str, list[tuple[str, CobolDataItem]]] = {}
        self._section_records: dict[str, list[CobolDataItem]] = {
            attr: [] for attr in _SECTION_NAMES.values()
        }
        #: name -> the qualified paths it maps to, for a bare name that
        #: exists at more than one path and so cannot resolve automatically.
        self.ambiguities: dict[str, list[str]] = {}
        #: Human-readable reasons for anything this index could not resolve
        #: -- an unowned FILE SECTION record, a SELECT with no matching FD.
        #: Never silently dropped; a caller building on this index should
        #: surface these rather than assume full coverage.
        self.unresolved: list[str] = []

    # -- construction ------------------------------------------------------

    @classmethod
    def build(cls, ast: CobolProgram) -> ProgramLayoutIndex:
        """Index an already-parsed program."""
        index = cls()
        index._build(ast)
        return index

    @classmethod
    def from_file(
        cls,
        path: str,
        *,
        copybook_paths: list[str] | None = None,
        strict_copybooks: bool = True,
    ) -> ProgramLayoutIndex:
        """Parse *path* and index it.

        With ``copybook_paths``, COPY statements are expanded first. A COPY
        member that cannot be resolved raises :class:`ProgramLayoutError`
        when ``strict_copybooks`` is True (the default) -- a record layout
        with a hole in it is wrong, not partial. With
        ``strict_copybooks=False`` the failure is recorded on
        :attr:`unresolved` instead, and indexing falls back to parsing
        without expansion (so unexpanded COPY statements contribute nothing
        to the layout, rather than aborting it).
        """
        if not os.path.isfile(path):
            # parse_cobol() falls back to treating a non-existent "path" as
            # literal source text (it only reads from disk when the string
            # names a real file) -- which would otherwise turn a typo'd
            # filename into a confusing "no recognizable COBOL division"
            # parse error instead of a clear "file not found".
            raise ProgramLayoutError(f"{path}: no such file")

        if copybook_paths:
            with open(path, encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            try:
                result = parse_cobol_with_expansion(
                    source, filename=str(path), copybook_paths=list(copybook_paths)
                )
            except (CopybookNotFoundError, CircularReferenceError) as exc:
                if strict_copybooks:
                    raise ProgramLayoutError(
                        f"{path}: unresolved copybook dependency: {exc}"
                    ) from exc
                result = parse_cobol(path)
                if isinstance(result, tuple):
                    result = result[0]
                if result.ast is None:
                    raise ProgramLayoutError(
                        f"{path} did not produce a program AST: {result.errors}"
                    ) from exc
                index = cls.build(result.ast)
                index.unresolved.append(f"copybooks not expanded: {exc}")
                return index
        else:
            result = parse_cobol(path)

        if isinstance(result, tuple):  # enable_profiling=True form
            result = result[0]
        if result.ast is None:
            raise ProgramLayoutError(
                f"{path} did not produce a program AST: {result.errors}"
            )
        return cls.build(result.ast)

    # -- public lookups ------------------------------------------------------

    def records_for_file(self, file_name: str) -> list[CobolDataItem]:
        """All 01/77 records owned by *file_name*'s FD/SD, in source order."""
        return list(self._records_by_file.get(file_name.upper(), []))

    def record_for_file(self, file_name: str) -> CobolDataItem | None:
        """The first record owned by *file_name*'s FD/SD, if any."""
        records = self._records_by_file.get(file_name.upper())
        return records[0] if records else None

    def file_facts(self, file_name: str) -> FileFacts | None:
        """Organizational/physical facts for *file_name*, if it was seen at all."""
        return self._file_facts.get(file_name.upper())

    def condition_values(self, name: str) -> tuple[str, ...] | None:
        """The VALUEs of the level-88 condition name *name* itself.

        ``None`` when *name* is not a level-88 condition name, or when it is
        declared under more than one distinct parent field (the same
        ambiguity policy :meth:`resolve` applies -- refuse to guess).

        Deliberately NOT the same thing as
        ``resolve(name).spec.condition_values``: that is the *union* of every
        88 declared under the parent field, which is what a value generator
        wants ("any value that could apply to this field") but is wrong for
        any caller asking what *this particular* condition requires. For::

            05  TYPE-P-BAL      PIC X(02).
                88  TYPE-P-BAL-M    VALUE "05".
                88  TYPE-P-BAL-F    VALUE "09".

        ``spec.condition_values`` is ``["05", "09"]`` for both names, while
        this returns ``("05",)`` and ``("09",)`` respectively. Constraint
        extraction reading the union made every arm of an ``EVALUATE TRUE /
        WHEN <88>`` chain produce an identical constraint, so every such
        scenario was seeded with the *first* 88's value and never reached the
        branch it was named for.
        """
        if not name or not name.strip():
            return None
        entries = self._condition_index.get(name.strip().upper())
        if not entries:
            return None
        parents = sorted({entry.spec.qualified_name for entry in entries})
        if len(parents) != 1:
            return None
        values = self._condition_values.get(name.strip().upper()) or []
        if not values:
            return None
        return tuple(values[0])

    def resolve(self, name: str) -> ResolvedField | None:
        """Resolve a data-name (bare, ``A OF B``, or dotted ``B.A``) to a field.

        A unique bare name resolves directly. A name that exists at more than
        one path returns ``None`` and is recorded on :attr:`ambiguities`
        rather than guessed -- callers needing a specific one must qualify
        it. A level-88 condition name resolves to its *parent* field.
        """
        if not name or not name.strip():
            return None
        text = name.strip()

        if _OF_IN_RE.search(text):
            # "A OF B [OF C ...]" -- the field comes first, qualifiers follow.
            parts = [p.strip() for p in _OF_IN_RE.split(text) if p.strip()]
            if not parts:
                # e.g. text is just "OF"/"IN" with nothing either side --
                # every segment stripped to empty. Not a resolvable name.
                return None
            base = parts[0].upper()
            qualifiers = [p.upper() for p in parts[1:]]
        elif "." in text:
            # "B.A" mirrors FieldSpec.qualified_name (root-first, field-last),
            # so the field is the *last* segment and qualifiers precede it.
            parts = [p.strip() for p in text.split(".") if p.strip()]
            if not parts:
                # e.g. text is "."/".." -- every segment stripped to empty.
                return None
            base = parts[-1].upper()
            qualifiers = [p.upper() for p in parts[:-1]]
        else:
            base = text.upper()
            qualifiers = []

        candidates = self._name_index.get(base)
        if not candidates:
            conditions = self._condition_index.get(base)
            if conditions:
                parents = sorted({c.spec.qualified_name for c in conditions})
                if len(parents) == 1:
                    return conditions[0]
                # The same 88 name is declared under more than one distinct
                # parent field (e.g. in two different records): refuse to
                # guess, record the ambiguity -- same policy as bare-name
                # and record_named() lookups.
                self.ambiguities[base] = parents
            return None

        if qualifiers:
            filtered = [
                c
                for c in candidates
                if all(
                    q == c.record.name.upper() or q in {p.upper() for p in c.spec.path}
                    for q in qualifiers
                )
            ]
            if len(filtered) == 1:
                return filtered[0]
            if len(filtered) > 1:
                self.ambiguities[text] = sorted(
                    {c.spec.qualified_name for c in filtered}
                )
            return None

        if len(candidates) == 1:
            return candidates[0]

        self.ambiguities[base] = sorted({c.spec.qualified_name for c in candidates})
        return None

    def section_of(self, name: str) -> str | None:
        """Which DATA DIVISION section *name* lives in, or ``None`` if unresolved."""
        resolved = self.resolve(name)
        return resolved.section if resolved else None

    def record_named(self, name: str) -> CobolDataItem | None:
        """The top-level (01/77) record named *name*, in any section.

        Unlike :meth:`resolve` (which only finds *elementary* fields --
        ``flatten_record`` never emits a ``FieldSpec`` for a group item),
        this finds a whole record by its own name: the shape a WRITE/REWRITE
        target, a READ ``INTO`` target, or a CALL argument naming an entire
        01-level group takes. A name shared by records in more than one
        section (legal but unusual) returns ``None`` and is recorded on
        :attr:`ambiguities`, mirroring :meth:`resolve`'s own policy.
        """
        if not name or not name.strip():
            return None
        candidates = self._records_by_name.get(name.strip().upper())
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][1]
        self.ambiguities[name] = sorted(
            f"{section}:{record.name}" for section, record in candidates
        )
        return None

    def linkage_records(self) -> list[CobolDataItem]:
        """Top-level (01/77) LINKAGE SECTION records, in source order."""
        return list(self._section_records["linkage"])

    def working_storage_records(self) -> list[CobolDataItem]:
        """Top-level (01/77) WORKING-STORAGE SECTION records, in source order."""
        return list(self._section_records["working_storage"])

    # -- build mechanics ------------------------------------------------------

    def _build(self, ast: CobolProgram) -> None:
        self.ast = ast
        data_div = ast.get_division("DATA")
        if data_div is not None:
            for canonical, attr in _SECTION_NAMES.items():
                section = data_div.get_section_by_name(canonical)
                records: list[CobolDataItem] = []
                if isinstance(section, CobolSection):
                    records = [
                        item
                        for item in section.data_items
                        if isinstance(item, CobolDataItem)
                    ]
                self._section_records[attr] = records
                for record in records:
                    self._index_record(record, attr)

        self._collect_file_facts(ast)

    def _index_record(self, record: CobolDataItem, section: str) -> None:
        self._records_by_name.setdefault(record.name.upper(), []).append(
            (section, record)
        )
        if section == "file":
            fd_file = record.get_metadata("fd_file_name")
            if fd_file:
                self._records_by_file.setdefault(fd_file.upper(), []).append(record)
            else:
                self.unresolved.append(
                    f"FILE SECTION record '{record.name}' has no associated FD/SD"
                )

        # Every storage-carrying field flattens into the name multimap --
        # indexing must see all of it (FILLER, REDEFINES included); which
        # fields are *generation*-eligible is a later phase's concern.
        fields = flatten_record(
            record,
            DataGeneratorOptions(include_filler=True, include_redefines=True),
        )
        qualified_index: dict[str, list[ResolvedField]] = {}
        for spec in fields:
            resolved = ResolvedField(spec=spec, section=section, record=record)
            self._name_index.setdefault(spec.name.upper(), []).append(resolved)
            qualified_index.setdefault(spec.qualified_name, []).append(resolved)

        self._index_condition_names(record, (), qualified_index)

    def _index_condition_names(
        self,
        item: CobolDataItem,
        path: tuple[str, ...],
        qualified_index: dict[str, list[ResolvedField]],
    ) -> None:
        """Map each level-88 condition name to its parent field's ResolvedField."""
        item_path = (*path, item.name)
        qualified = ".".join(item_path)
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                owners = qualified_index.get(qualified)
                if owners:
                    key = child.name.upper()
                    self._condition_index.setdefault(key, []).append(owners[0])
                    self._condition_values.setdefault(key, []).append(
                        expand_condition_values(child.values)
                    )
            elif isinstance(child, CobolDataItem):
                self._index_condition_names(child, item_path, qualified_index)

    def _collect_file_facts(self, ast: CobolProgram) -> None:
        select_by_name: dict[str, SelectStatement] = {}
        env_div = ast.get_division("ENVIRONMENT")
        if env_div is not None:
            for node in env_div.find_all_by_type("Statement"):
                if isinstance(node, SelectStatement) and node.file_name:
                    select_by_name[node.file_name.upper()] = node

        all_names = set(select_by_name) | set(self._records_by_file)
        for name in sorted(all_names):
            select = select_by_name.get(name)
            records = self._records_by_file.get(name, [])
            fd_clauses: dict[str, Any] = {}
            record_type = "FD"
            if records:
                fd_clauses = records[0].get_metadata("fd_clauses") or {}
                record_type = records[0].get_metadata("fd_record_type") or "FD"
            elif select is not None:
                self.unresolved.append(
                    f"file '{name}' has a SELECT but no matching FD/SD record"
                )

            record_block = fd_clauses.get("record") or {}
            record_contains: int | None = None
            record_contains_min: int | None = None
            record_contains_max: int | None = None
            if record_block:
                if record_block.get("varying") or record_block.get("min") is not None:
                    record_contains_min = record_block.get("min")
                    record_contains_max = record_block.get("max")
                else:
                    record_contains = record_block.get("max")

            self._file_facts[name] = FileFacts(
                file_name=name,
                organization=select.organization if select else None,
                access_mode=select.access_mode if select else None,
                record_key=select.record_key if select else None,
                alternate_keys=(
                    tuple(select.alternate_keys)
                    if select and select.alternate_keys
                    else ()
                ),
                relative_key=select.relative_key if select else None,
                file_status_field=select.file_status if select else None,
                is_optional=select.is_optional if select else False,
                record_contains=record_contains,
                record_contains_min=record_contains_min,
                record_contains_max=record_contains_max,
                recording_mode=fd_clauses.get("recording_mode"),
                record_names=tuple(r.name for r in records),
                record_type=record_type,
            )


__all__ = [
    "FileFacts",
    "ResolvedField",
    "ProgramLayoutIndex",
]
