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

from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.misc import SelectStatement
from ..parser import parse_cobol, parse_cobol_with_expansion
from ..preprocess import CircularReferenceError, CopybookNotFoundError
from .errors import ProgramLayoutError
from .fields import (
    FieldCategory,
    FieldSpec,
    _link_odo_counters,
    expand_condition_values,
    flatten_record,
    layout_segment,
    occurs_expansion_caveats,
)
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


def split_qualified_name(text: str | None) -> tuple[str, list[str]] | None:
    """Split a data-name -- bare, ``A OF B [OF C ...]``, or dotted ``B.A``
    -- into ``(base, qualifiers)``, upper-cased. ``None`` when *text* has
    nothing resolvable in it (e.g. just ``"OF"`` alone, or an empty/blank
    string).

    The one place this grammar is parsed: :meth:`ProgramLayoutIndex.resolve`
    and ``analysis.const_fold``'s own qualifier splitting (``_group_paths``)
    both call this rather than each re-deriving it, so a name like
    ``"A OF B"`` cannot resolve differently depending on which one asked.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None

    if _OF_IN_RE.search(stripped):
        # "A OF B [OF C ...]" -- the field comes first, qualifiers follow.
        parts = [p.strip() for p in _OF_IN_RE.split(stripped) if p.strip()]
        if not parts:
            # e.g. text is just "OF"/"IN" with nothing either side --
            # every segment stripped to empty. Not a resolvable name.
            return None
        return parts[0].upper(), [p.upper() for p in parts[1:]]

    if "." in stripped:
        # "B.A" mirrors FieldSpec.qualified_name (root-first, field-last),
        # so the field is the *last* segment and qualifiers precede it.
        parts = [p.strip() for p in stripped.split(".") if p.strip()]
        if not parts:
            # e.g. text is "."/".." -- every segment stripped to empty.
            return None
        return parts[-1].upper(), [p.upper() for p in parts[:-1]]

    return stripped.upper(), []


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
        #: The same condition names' VALUE entries exactly as parsed (range
        #: ends still ``THROUGH:``-marked, figuratives still words) -- what
        #: :meth:`condition_raw_values` hands a caller that must know whether
        #: the expanded list above is the whole set or only a sample of it.
        self._condition_raw_values: dict[str, list[list[str]]] = {}
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
        #: Expanded line number -> (original file, original line), from the
        #: copybook expander's own per-line record (``ParseResult.
        #: expansion_source_map``), when ``from_file()`` expanded COPY
        #: statements. ``None`` when nothing was expanded (``build()``, or
        #: ``from_file()`` with no ``copybook_paths``) -- every location this
        #: index's AST carries is already on-disk truth in that case. A
        #: caller that reports a line number derived from this AST (a
        #: branch's location, a boundary's line) to the developer should
        #: translate it through this map first, the same way ``lint``/
        #: ``parse`` already do via :func:`stamp_report_origins` --
        #: otherwise a line number from the expanded source gets handed to
        #: someone looking at the file on disk, where it points at nothing.
        self.source_map: dict[int, tuple[str, int]] | None = None
        #: Data name (uppercased, bare and qualified) -> the VALUE literal of
        #: a WORKING-STORAGE item the program never changes, so a comparison
        #: against it is a comparison against that literal. Filled by
        #: :class:`~cobolparser.analysis.constraints.ConstraintExtractor`.
        self.named_constants: dict[str, str] = {}
        #: True once :meth:`add_cics_interface` indexed a DFHEIBLK the
        #: program itself does not declare.
        self.synthetic_eib = False
        #: CALL line -> the RETURN-CODE field a branch after it tests
        #: (:meth:`call_return_code`).
        self._call_return_codes: dict[int, ResolvedField] = {}
        #: EXEC SQL line -> the SQLCODE field a branch after it tests
        #: (:meth:`sql_code`).
        self._sql_codes: dict[int, ResolvedField] = {}

    def call_return_code(self, line: int) -> ResolvedField:
        """The RETURN-CODE the CALL on *line* leaves, as a field (#831).

        RETURN-CODE is a special register (binary, ``S9(4)``), not a declared
        item; after a CALL it holds what the callee set, which a CALL mock
        supplies. Each call site gets its own field (qualified name
        ``CALL@<line>.RETURN-CODE``) so a scenario's witness sets it for the
        one CALL whose result the program tests.
        """
        found = self._call_return_codes.get(line)
        if found is None:
            spec = FieldSpec(
                name="RETURN-CODE",
                path=(f"CALL@{line}", "RETURN-CODE"),
                column="RETURN-CODE",
                level=1,
                picture="S9(4)",
                usage="BINARY",
                category=FieldCategory.NUMERIC,
                size=4,
                integer_digits=4,
                decimal_digits=0,
                is_signed=True,
                total_digits=4,
            )
            record = CobolDataItem("RETURN-CODE", 1, SourceLocation(line, 1))
            found = ResolvedField(spec=spec, section="special", record=record)
            self._call_return_codes[line] = found
        return found

    def call_return_code_at(self, line: int | None) -> ResolvedField | None:
        """The RETURN-CODE field of the CALL on *line*, if a branch tests it."""
        return self._call_return_codes.get(line) if line is not None else None

    def sql_code(self, line: int, *, fetch: bool = False) -> ResolvedField:
        """The SQLCODE the EXEC SQL on *line* leaves, as a field (#840).

        SQLCODE belongs to the SQLCA the precompiler includes; after an SQL
        statement it holds that statement's outcome, which its mock reports
        (the SQL fixture's ``status``). Each statement gets its own field
        (qualified name ``SQL@<line>.SQLCODE``, ``FETCH@<line>.SQLCODE`` for
        a FETCH) so a scenario's witness, a negative SQLCODE for ``IF
        SQLCODE < 0``, fails only the statement whose result the program
        tests. The solver prefers real SQLCODEs for it
        (:data:`~cobolparser.analysis.domains.SQLCODE_PREFERENCES`).
        """
        found = self._sql_codes.get(line)
        if found is None:
            spec = FieldSpec(
                name="SQLCODE",
                path=(f"{'FETCH' if fetch else 'SQL'}@{line}", "SQLCODE"),
                column="SQLCODE",
                level=1,
                picture="S9(9)",
                usage="BINARY",
                category=FieldCategory.NUMERIC,
                size=4,
                integer_digits=9,
                decimal_digits=0,
                is_signed=True,
                total_digits=9,
            )
            record = CobolDataItem("SQLCODE", 1, SourceLocation(line, 1))
            found = ResolvedField(spec=spec, section="special", record=record)
            self._sql_codes[line] = found
        return found

    def sql_code_at(self, line: int | None) -> ResolvedField | None:
        """The SQLCODE field of the EXEC SQL on *line*, if a branch tests it."""
        return self._sql_codes.get(line) if line is not None else None

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
        debug_lines: bool = False,
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

        ``debug_lines`` is ``parse_cobol``'s: compile fixed-format debugging
        lines (``D`` in column 7) as code, through copybook expansion too.
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
                    source,
                    filename=str(path),
                    copybook_paths=list(copybook_paths),
                    debug_lines=debug_lines,
                )
            except (CopybookNotFoundError, CircularReferenceError) as exc:
                if strict_copybooks:
                    raise ProgramLayoutError(
                        f"{path}: unresolved copybook dependency: {exc}"
                    ) from exc
                result = parse_cobol(path, debug_lines=debug_lines)
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
            result = parse_cobol(path, debug_lines=debug_lines)

        if isinstance(result, tuple):  # enable_profiling=True form
            result = result[0]
        if result.ast is None:
            raise ProgramLayoutError(
                f"{path} did not produce a program AST: {result.errors}"
            )
        index = cls.build(result.ast)
        index.source_map = getattr(result, "expansion_source_map", None)
        return index

    # -- public lookups ------------------------------------------------------

    def records_for_file(self, file_name: str) -> list[CobolDataItem]:
        """All 01/77 records owned by *file_name*'s FD/SD, in source order."""
        return list(self._records_by_file.get(file_name.upper(), []))

    def file_names(self) -> list[str]:
        """Every (UPPERCASED) file name that owns at least one FD/SD record,
        in the order its first record was seen."""
        return list(self._records_by_file)

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
        found = self._condition_entry(name)
        if found is None:
            return None
        base, position = found
        values = self._condition_values.get(base) or []
        if position >= len(values):
            return None
        return tuple(values[position])

    @staticmethod
    def _qualifiers_match(entry: ResolvedField, qualifiers: list[str]) -> bool:
        """Whether every OF/IN qualifier names *entry*'s record or one of the
        groups on its path -- the one rule :meth:`resolve` applies to a
        field and to a level-88 condition name alike."""
        path = {p.upper() for p in entry.spec.path}
        return all(q == entry.record.name.upper() or q in path for q in qualifiers)

    def _condition_matches(
        self, base: str, qualifiers: list[str]
    ) -> list[tuple[int, ResolvedField]]:
        """``(position, parent field)`` of every level-88 *base* declaration
        the *qualifiers* admit; position indexes the lockstep value lists."""
        return [
            (position, entry)
            for position, entry in enumerate(self._condition_index.get(base) or [])
            if self._qualifiers_match(entry, qualifiers)
        ]

    def _condition_entry(self, name: str) -> tuple[str, int] | None:
        """``(base, position)`` of the ONE level-88 declaration *name*
        (bare or qualified) names, or ``None`` when it names none or is
        ambiguous across more than one parent field."""
        split = split_qualified_name(name)
        if split is None:
            return None
        base, qualifiers = split
        matches = self._condition_matches(base, qualifiers)
        if not matches:
            return None
        if len({entry.spec.qualified_name for _, entry in matches}) != 1:
            return None
        return base, matches[0][0]

    def condition_raw_values(self, name: str) -> tuple[str, ...] | None:
        """The level-88 condition name *name*'s VALUE entries as parsed.

        Same lookup and ambiguity policy as :meth:`condition_values`, but
        unexpanded: a ``THRU`` range end is still ``"THROUGH:<end>"`` and a
        figurative constant is still its word. :meth:`condition_values` is a
        *sample* of the condition's values whenever a range could not be
        enumerated in full, and only this form can tell a caller so (see
        :func:`~.layout.condition_values_exhaustive`).
        """
        if self.condition_values(name) is None:
            return None
        found = self._condition_entry(name)
        assert found is not None  # condition_values() just found it
        base, position = found
        values = self._condition_raw_values.get(base) or []
        return tuple(values[position]) if position < len(values) else None

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

        split = split_qualified_name(text)
        if split is None:
            return None
        base, qualifiers = split

        candidates = self._name_index.get(base)
        if not candidates:
            conditions = [
                entry for _, entry in self._condition_matches(base, qualifiers)
            ]
            if conditions:
                parents = sorted({c.spec.qualified_name for c in conditions})
                if len(parents) == 1:
                    if conditions[0].spec.subscripts:
                        # Under an OCCURS table: the bare name tests every
                        # occurrence, not the first one; only a subscripted
                        # reference names a single field.
                        return None
                    return conditions[0]
                # The same 88 name is declared under more than one distinct
                # parent field (e.g. in two different records): refuse to
                # guess, record the ambiguity -- same policy as bare-name
                # and record_named() lookups.
                self.ambiguities[text if qualifiers else base] = parents
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
            if len(filtered) > 1 and not self._one_table_element(filtered):
                self.ambiguities[text] = sorted(
                    {c.spec.qualified_name for c in filtered}
                )
            return None

        if len(candidates) == 1:
            return candidates[0]

        if not self._one_table_element(candidates):
            self.ambiguities[base] = sorted({c.spec.qualified_name for c in candidates})
        return None

    @staticmethod
    def _one_table_element(candidates: list[ResolvedField]) -> bool:
        """Whether *candidates* are the occurrences of ONE declared item
        inside an OCCURS table: an unsubscripted name there resolves to no
        single field (only ``NAME(n)`` does), but it is not ambiguous
        either -- there is exactly one path."""
        return len({c.spec.qualified_name for c in candidates}) == 1 and all(
            c.spec.subscripts for c in candidates
        )

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

    def records(self) -> list[CobolDataItem]:
        """Every top-level (01/77) record this index knows, section by
        section (FILE, WORKING-STORAGE, LOCAL-STORAGE, LINKAGE), each in
        source order -- for a caller that needs to walk the raw
        :class:`CobolDataItem` trees themselves (group membership, REDEFINES
        siblings, JUSTIFIED flags: facts ``flatten_record`` does not carry)."""
        return [
            record
            for attr in _SECTION_NAMES.values()
            for record in self._section_records[attr]
        ]

    def linkage_records(self) -> list[CobolDataItem]:
        """Top-level (01/77) LINKAGE SECTION records, in source order."""
        return list(self._section_records["linkage"])

    def working_storage_records(self) -> list[CobolDataItem]:
        """Top-level (01/77) WORKING-STORAGE SECTION records, in source order."""
        return list(self._section_records["working_storage"])

    # -- build mechanics ------------------------------------------------------

    def add_cics_interface(self) -> bool:
        """Index the CICS Execute Interface Block (``DFHEIBLK``) as a
        LINKAGE record when the program does not declare it, the way the
        CICS translator inserts it, so ``IF EIBCALEN = 0`` and ``IF EIBAID =
        ...`` resolve to fields a scenario can set. Returns whether it was
        added (False when the program already declares one)."""
        if self.record_named("DFHEIBLK") is not None:
            return False
        record = _synthetic_eib_record()
        if record is None:  # pragma: no cover - the text is fixed
            return False
        self._section_records.setdefault("linkage", []).append(record)
        self._index_record(record, "linkage")
        self.synthetic_eib = True
        return True

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
            self._link_odo_counters_across_records()

        self._collect_file_facts(ast)

    def _link_odo_counters_across_records(self) -> None:
        """Bound an ODO counter declared outside its table's record.

        ``flatten_record`` stamps ``odo_counter_bounds`` within one record;
        the usual WORKING-STORAGE layout gives the counter its own 01
        (``01 WS-CNT PIC 99.`` / ``01 WS-TAB. 05 E OCCURS 1 TO 5 DEPENDING
        ON WS-CNT``), so it never got the table's bounds and scenarios fed
        it 0 or 99 (#832). Re-run the linking over every indexed field, so
        the counter is stamped wherever it is declared (``OF`` qualifiers
        still honoured).
        """
        specs = [
            entry.spec for entries in self._name_index.values() for entry in entries
        ]
        if any(spec.odo_controls for spec in specs):
            _link_odo_counters(list({id(spec): spec for spec in specs}.values()))

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
        index_options = DataGeneratorOptions(
            include_filler=True, include_redefines=True
        )
        fields = flatten_record(record, index_options)
        # A table the expansion caps cut short is indexed (and so generated)
        # only partly: say so rather than let a fixture look complete (#376).
        self.unresolved.extend(occurs_expansion_caveats(record, index_options))
        qualified_index: dict[str, list[ResolvedField]] = {}
        for spec in fields:
            resolved = ResolvedField(spec=spec, section=section, record=record)
            self._name_index.setdefault(spec.name.upper(), []).append(resolved)
            qualified_index.setdefault(spec.qualified_name, []).append(resolved)

        self._index_condition_names(record, (), qualified_index, None)

    def _index_condition_names(
        self,
        item: CobolDataItem,
        path: tuple[str, ...],
        qualified_index: dict[str, list[ResolvedField]],
        parent: CobolDataItem | None,
    ) -> None:
        """Map each level-88 condition name to its parent field's ResolvedField."""
        # The same segment flatten_record() gave the field, so a FILLER that
        # owns the 88 is found as itself, not as the group's first FILLER.
        item_path = (*path, layout_segment(item, parent))
        qualified = ".".join(item_path)
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                owners = qualified_index.get(qualified)
                if owners:
                    key = child.name.upper()
                    self._condition_index.setdefault(key, []).append(owners[0])
                    self._condition_values.setdefault(key, []).append(
                        expand_condition_values(child.values, owners[0].spec.size)
                    )
                    self._condition_raw_values.setdefault(key, []).append(
                        list(child.values)
                    )
            elif isinstance(child, CobolDataItem):
                self._index_condition_names(child, item_path, qualified_index, item)

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


#: The CICS EIB layout the translator inserts (unchanged across CICS TS
#: releases), as one LINKAGE record.
_EIB_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EIBLAYOUT.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHEIBLK.
           05  EIBTIME      PIC S9(7) COMP-3.
           05  EIBDATE      PIC S9(7) COMP-3.
           05  EIBTRNID     PIC X(4).
           05  EIBTASKN     PIC S9(7) COMP-3.
           05  EIBTRMID     PIC X(4).
           05  FILLER       PIC S9(4) COMP.
           05  EIBCPOSN     PIC S9(4) COMP.
           05  EIBCALEN     PIC S9(4) COMP.
           05  EIBAID       PIC X(1).
           05  EIBFN        PIC X(2).
           05  EIBRCODE     PIC X(6).
           05  EIBDS        PIC X(8).
           05  EIBREQID     PIC X(8).
           05  EIBRSRCE     PIC X(8).
           05  EIBSYNC      PIC X(1).
           05  EIBFREE      PIC X(1).
           05  EIBRECV      PIC X(1).
           05  FILLER       PIC X(1).
           05  EIBATT       PIC X(1).
           05  EIBEOC       PIC X(1).
           05  EIBFMH       PIC X(1).
           05  EIBCOMPL     PIC X(1).
           05  EIBSIG       PIC X(1).
           05  EIBCONF      PIC X(1).
           05  EIBERR       PIC X(1).
           05  EIBERRCD     PIC X(4).
           05  EIBSYNRB     PIC X(1).
           05  EIBNODAT     PIC X(1).
           05  EIBRESP      PIC S9(8) COMP.
           05  EIBRESP2     PIC S9(8) COMP.
           05  EIBRLDBK     PIC X(1).
       PROCEDURE DIVISION.
           GOBACK.
"""


def _synthetic_eib_record() -> CobolDataItem | None:
    """A fresh ``01 DFHEIBLK`` data item parsed from :data:`_EIB_SOURCE`."""
    result = parse_cobol(_EIB_SOURCE)
    if isinstance(result, tuple):
        result = result[0]
    ast = result.ast
    data_div = ast.get_division("DATA") if ast is not None else None
    section = data_div.get_section_by_name("LINKAGE") if data_div is not None else None
    if not isinstance(section, CobolSection):
        return None
    for item in section.data_items:
        if isinstance(item, CobolDataItem):
            return item
    return None
