"""
Cross-reference (XREF) listing for a COBOL program.

Produces the classic mainframe compiler cross-reference: for every symbol a
program declares -- data items, level-88 condition names, files, paragraphs
and sections -- where it is *defined* and every place it is *referenced*,
each reference carrying its source location, the statement it sits in, the
enclosing paragraph, and the **role** the symbol plays there (written,
read, tested in a condition, used as a subscript, PERFORMed, ...).

This is the natural completion of ``unused_variables.py``: that analyzer
answers "is this name referenced at all?" with a flat ``set[str]``; this one
keeps the locations and the roles that set throws away, so "unused" becomes
"fully cross-referenced". All of its reference-collection machinery is
reused rather than re-derived -- ``_extract_identifiers``,
``_walk_expression_operands``, ``_names_from_value``,
``collect_declared_items`` and the ``_STR_ATTR_EXTRAS`` /
``_STR_LIST_EXTRAS`` / ``_DICT_LIST_EXTRAS`` tables all come from there.

Single-program scope: like ``DeadCodeAnalyzer`` and ``UnusedVariableAnalyzer``
this analyzer only looks at *ast* itself, not ``ast.contained_programs``.
Call ``analyze()`` separately on each contained program if needed.

Nothing is guessed. Where a role, a location or an identifier could only be
recovered approximately, the reference is still reported (with role
``"reference"`` when the role itself is unknown) and a line explaining the
approximation is appended to ``report.caveats`` -- a quiet report must never
be mistaken for a complete one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..dialects.ibm_enterprise import IBMEnterpriseCobol
from ..lexer import CobolLexer
from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem, RenamesItem
from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..models.statements.arithmetic import (
    ArithmeticStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
)
from ..models.statements.base import CobolExpression, CobolStatement
from ..models.statements.call import CallStatement, EntryStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import (
    DisplayStatement,
    InitializeStatement,
    InspectStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.io import (
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)
from ..models.statements.misc import (
    AllocateStatement,
    AlterStatement,
    FreeStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
    XmlJsonStatement,
)
from ._names import QUALIFIER_SEPARATOR
from .unused_variables import (
    _DATA_SECTION_NAMES,
    _DICT_LIST_EXTRAS,
    _STR_ATTR_EXTRAS,
    _STR_LIST_EXTRAS,
    UnusedVariableAnalyzer,
    _ancestor_names,
    _extract_identifiers,
    _names_from_value,
    _qualifiers_match,
    _walk_expression_operands,
    collect_declared_items,
    inherited_data_records,
)

# --------------------------------------------------------------------------
# Role vocabulary
# --------------------------------------------------------------------------

ROLE_WRITE = "write"
ROLE_READ = "read"
ROLE_CONDITION = "condition"
ROLE_SUBSCRIPT = "subscript"
ROLE_PERFORM = "perform"
ROLE_GOTO = "goto"
ROLE_CALL_ARGUMENT = "call-argument"
ROLE_HOST_VARIABLE = "host-variable"
ROLE_FILE_OPERATION = "file-operation"
ROLE_REFERENCE = "reference"

#: Every role this analyzer can emit. ``"reference"`` is the deliberate
#: "role not determined" rung -- a role is never fabricated.
XREF_ROLES: frozenset[str] = frozenset(
    {
        ROLE_WRITE,
        ROLE_READ,
        ROLE_CONDITION,
        ROLE_SUBSCRIPT,
        ROLE_PERFORM,
        ROLE_GOTO,
        ROLE_CALL_ARGUMENT,
        ROLE_HOST_VARIABLE,
        ROLE_FILE_OPERATION,
        ROLE_REFERENCE,
    }
)

# Symbol kinds.
KIND_DATA_ITEM = "data-item"
KIND_CONDITION_NAME = "condition-name"
KIND_PARAGRAPH = "paragraph"
KIND_SECTION = "section"
KIND_FILE = "file"

#: Kind ordering used when sorting ``XrefReport.entries``; unknown kinds sort
#: last, then alphabetically, so the ordering is total and deterministic.
_KIND_ORDER: dict[str, int] = {
    KIND_DATA_ITEM: 0,
    KIND_CONDITION_NAME: 1,
    KIND_FILE: 2,
    KIND_PARAGRAPH: 3,
    KIND_SECTION: 4,
}

# Roles that name a procedure rather than a data item, and roles that name a
# file. The role decides which namespace a reference is resolved against, so
# a paragraph and a data item that share a name are never confused.
_PROCEDURE_ROLES = frozenset({ROLE_PERFORM, ROLE_GOTO})

#: Words that can never be a user-declared symbol: every reserved word the
#: lexer knows plus the IBM intrinsic function names. Identifier extraction
#: is deliberately over-inclusive (see ``_extract_identifiers``), so a raw
#: operand can yield ``BY``, ``DISPLAY`` or ``ASIN``; those attach to nothing
#: and must not be reported as *undeclared* symbols either. Checked only
#: after a lookup has already failed, so a real declaration always wins.
_RESERVED_WORDS: frozenset[str] = frozenset(CobolLexer.KEYWORDS) | frozenset(
    IBMEnterpriseCobol.IBM_INTRINSIC_FUNCTIONS
)

#: A COBOL word: letters/digits/hyphens, never starting or ending with a
#: hyphen. Identifier extraction runs over raw operand text a statement
#: parser sometimes truncates (an UNSTRING ``DELIMITER IN`` operand can
#: arrive as ``"WS-"``), and a fragment like that is not a symbol -- it is
#: dropped and counted rather than reported as an undeclared name.
_COBOL_WORD_RE = re.compile(
    r"^(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$"
)

#: IBM special registers and precompiler/translator-supplied items: never
#: declared in the DATA DIVISION the analyzer sees, yet not undeclared
#: either. A reference to one is counted and reported in a caveat rather
#: than listed in ``undefined``, which would otherwise name RETURN-CODE or
#: SQLCODE on nearly every enterprise program and make the list useless as
#: a lint signal.
_SPECIAL_REGISTERS: frozenset[str] = frozenset(
    {
        "RETURN-CODE",
        "SORT-RETURN",
        "SORT-MESSAGE",
        "SORT-CORE-SIZE",
        "SORT-FILE-SIZE",
        "SORT-MODE-SIZE",
        "SORT-CONTROL",
        "TALLY",
        "WHEN-COMPILED",
        "DEBUG-ITEM",
        "SHIFT-IN",
        "SHIFT-OUT",
        "LINAGE-COUNTER",
        "ADDRESS",
        "LENGTH",
        "XML-CODE",
        "XML-EVENT",
        "XML-TEXT",
        "XML-NTEXT",
        "XML-NAMESPACE",
        "XML-NNAMESPACE",
        "XML-NAMESPACE-PREFIX",
        "XML-NNAMESPACE-PREFIX",
        "XML-INFORMATION",
        "JSON-CODE",
        "JSON-STATUS",
        "SQLCODE",
        "SQLSTATE",
        "SQLCA",
        "SQLERRD",
        "SQLERRM",
        "SQLERRMC",
        "SQLWARN0",
        "SQLDA",
        "EIBCALEN",
        "EIBRESP",
        "EIBRESP2",
        "EIBTRNID",
        "EIBTRMID",
        "EIBAID",
        "EIBFN",
        "EIBRCODE",
        "EIBDATE",
        "EIBTIME",
        "EIBTASKN",
        "EIBCPOSN",
        "DFHRESP",
        "DFHVALUE",
        "DFHCOMMAREA",
        "DFHEIBLK",
    }
)


def is_special_register(name: str) -> bool:
    """Whether *name* is a special register or a precompiler/translator item.

    These are never declared in the DATA DIVISION the analyzer sees, so a
    lookup finds no entry for them; this tells "special register" from
    "unknown name".
    """
    return name.strip().upper() in _SPECIAL_REGISTERS


_PAREN_RE = re.compile(r"\(([^()]*)\)")
_FUNCTION_RE = re.compile(r"\bFUNCTION\b", re.IGNORECASE)


@dataclass(frozen=True)
class _RawText:
    """Raw statement text whose identifiers must not be split into subscripts.

    EXEC CICS options and EXEC IMS/DLI arguments keep their operands as one
    joined string with the *option keyword* wrapped around the data name
    (``"INTO(WS-BUFFER)"``), so the parenthesised part is an argument, not a
    subscript. Wrapping such a value in ``_RawText`` runs plain identifier
    extraction over it instead of ``_partition_operand``.
    """

    text: str


@dataclass
class XrefReference:
    """One place a symbol is referenced, and what it is doing there."""

    location: SourceLocation
    role: str
    statement: str
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location.to_dict(),
            "role": self.role,
            "statement": self.statement,
            "context": self.context,
        }


@dataclass
class XrefEntry:
    """One symbol: where it is declared and everywhere it is referenced."""

    name: str
    kind: str
    definition: SourceLocation | None
    references: list[XrefReference] = field(default_factory=list)
    level: int | None = None
    section: str | None = None
    #: ``"AMT OF OUT-REC"`` when another declared data item or condition
    #: name shares this one's name in a different record (issue #258); each
    #: such item then has an entry of its own, and ``name`` alone no longer
    #: identifies it.
    qualified_name: str | None = None

    @property
    def reference_count(self) -> int:
        return len(self.references)

    @property
    def is_referenced(self) -> bool:
        return bool(self.references)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "definition": self.definition.to_dict() if self.definition else None,
            "level": self.level,
            "section": self.section,
            **({"qualified_name": self.qualified_name} if self.qualified_name else {}),
            "reference_count": self.reference_count,
            "references": [ref.to_dict() for ref in self.references],
        }


@dataclass
class XrefReport:
    """Result of a cross-reference analysis."""

    entries: list[XrefEntry] = field(default_factory=list)
    undefined: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    #: Names declared more than once in one namespace (a copybook COPYed
    #: into both WORKING-STORAGE and LINKAGE is the common shape). Every
    #: reference to such a name is attributed to the first declaration, so
    #: a consumer grading *which* declaration was touched must not trust it.
    duplicate_declarations: list[str] = field(default_factory=list)

    @property
    def total_references(self) -> int:
        return sum(entry.reference_count for entry in self.entries)

    def entry_for(self, name: str) -> XrefEntry | None:
        """The entry for *name* (case-insensitive), or None.

        When a name is both declared and, say, PERFORMed as a paragraph, the
        first matching entry in ``entries`` order (data items first -- see
        ``_KIND_ORDER``) is returned. A qualified name (``"AMT OF OUT-REC"``)
        picks out one of several same-named data items.
        """
        upper = " ".join(name.upper().split())
        for entry in self.entries:
            if entry.name == upper or entry.qualified_name == upper:
                return entry
        return None

    def entries_of_kind(self, kind: str) -> list[XrefEntry]:
        """Every entry of one kind, in ``entries`` order."""
        return [entry for entry in self.entries if entry.kind == kind]

    def to_dict(self) -> dict[str, Any]:
        defined = [e for e in self.entries if e.definition is not None]
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "undefined": list(self.undefined),
            "caveats": list(self.caveats),
            "duplicate_declarations": list(self.duplicate_declarations),
            "summary": {
                "total_symbols": len(self.entries),
                "defined_symbols": len(defined),
                "referenced_symbols": sum(1 for e in defined if e.is_referenced),
                "unreferenced_symbols": sum(1 for e in defined if not e.is_referenced),
                "undefined_symbols": len(self.undefined),
                "total_references": self.total_references,
            },
        }


def _partition_operand(text: str) -> tuple[set[str], set[str], bool]:
    """Split one operand's raw text into (base names, subscript names, exact).

    Statement parsers hand a whole reference through as one joined string
    (``"WS-TBL (WS-IDX)"``, ``"WS-A OF WS-GRP"``, ``"FUNCTION UPPER-CASE(WS-X)"``
    -- see ``_extract_identifiers``' docstring), so the subscript has to be
    recovered from the text. Parenthesised groups are peeled off innermost
    first: their identifiers are subscripts, everything left is the operand
    itself.

    Two exceptions, both reported rather than guessed:

    - A reference-modification group (``WS-X (1:5)``) is not a subscript; its
      identifiers are folded back into the base names.
    - An intrinsic-function reference (``FUNCTION UPPER-CASE(WS-X)``) is not a
      subscript either, and this analyzer cannot tell the function's own name
      from its arguments, so every identifier is returned as a base name and
      the result is flagged *inexact* (third element False) -- inexact names
      never contribute to ``report.undefined``.
    """
    base, refmod, subscripts, exact = _split_operand(text)
    return base | refmod, subscripts, exact


def _split_operand(text: str) -> tuple[set[str], set[str], set[str], bool]:
    """Like ``_partition_operand``, keeping reference-modifier names apart.

    Returns (base names, reference-modification names, subscript names,
    exact). The offset and length of ``WS-X (WS-OFF:WS-LEN)`` are *read* to
    locate the substring whatever the operand's own role is, so a caller
    recording a receiving operand must not stamp them ``write``.
    """
    if not text:
        return set(), set(), set(), True

    if _FUNCTION_RE.search(text):
        return _extract_identifiers(text), set(), set(), False

    subscripts: set[str] = set()
    refmod: set[str] = set()
    remaining = text
    while True:
        match = _PAREN_RE.search(remaining)
        if match is None:
            break
        inner = match.group(1)
        if ":" in inner:
            # Reference modification: offsets/lengths, not subscripts.
            refmod |= _extract_identifiers(inner)
        else:
            subscripts |= _extract_identifiers(inner)
        remaining = f"{remaining[: match.start()]} {remaining[match.end():]}"

    base = _extract_identifiers(remaining)
    refmod -= subscripts
    return base - subscripts, refmod, subscripts, True


#: ``OF`` / ``IN`` as a qualifier connective, not part of a hyphenated name.
_QUALIFIER_CONNECTIVE_RE = re.compile(r"(?<![\w-])(?:OF|IN)(?![\w-])", re.IGNORECASE)


def _qualifier_names(text: str) -> set[str]:
    """Names that only qualify the operand: ``WS-GRP`` in ``WS-A OF WS-GRP``.

    Subscript and reference-modifier groups are removed first, so a
    qualified subscript does not count.
    """
    remaining = text
    while True:
        match = _PAREN_RE.search(remaining)
        if match is None:
            break
        remaining = f"{remaining[: match.start()]} {remaining[match.end():]}"
    connective = _QUALIFIER_CONNECTIVE_RE.search(remaining)
    if connective is None:
        return set()
    return _extract_identifiers(remaining[connective.end() :]) - _extract_identifiers(
        remaining[: connective.start()]
    )


def _contained_node_ids(ast: CobolProgram) -> set[int]:
    """``id()`` of every node under a program contained in *ast*.

    ``traverse_depth_first`` descends into contained programs (they are AST
    children); the outer unit's cross-reference must not see them.
    """
    return {
        id(node)
        for contained in ast.contained_programs
        for node in contained.traverse_depth_first()
    }


class XrefAnalyzer:
    """Analyzer producing a full cross-reference listing for one program.

    Every symbol the program declares gets an ``XrefEntry``:

    - ``data-item`` -- every non-FILLER item of the FILE, WORKING-STORAGE,
      LOCAL-STORAGE and LINKAGE sections (the same set
      ``collect_declared_items`` feeds ``UnusedVariableAnalyzer``), with its
      level number and owning section; plus every level-66 ``RENAMES`` item
      (level 66).
    - ``condition-name`` -- every level-88 item, carrying its parent's section
      -- including the level-88s under a FILLER (issue #485).
    - ``file`` -- every file named by a ``SELECT`` or by an ``FD``/``SD``.
    - ``paragraph`` / ``section`` -- every PROCEDURE DIVISION procedure.

    Each reference records the role the symbol plays (see ``XREF_ROLES``).
    The role also decides which namespace a name resolves against: a
    ``perform``/``goto`` reference only ever matches a procedure, a
    ``file-operation`` reference only ever matches a file, everything else
    only ever matches a data item or condition name. A name that resolves
    against nothing gets an entry with ``definition=None`` and is listed in
    ``report.undefined``.

    Known limitations, each also surfaced through ``report.caveats`` on the
    runs where they actually bite:

    - SEARCH WHEN conditions and EVALUATE ``TRUE``-style WHEN selectors carry
      only raw joined text, never a structural tree (confirmed against
      ``search_parser.py`` / ``evaluate_parser.py``), so identifier
      extraction there is a best-effort regex.
    - EXEC CICS options and EXEC IMS/DLI arguments are raw text with no fixed
      argument-role shape, so their identifiers get role ``"reference"``.
    - Statement types with no dedicated role mapping fall back to a generic
      sweep of ``.operands`` (plus ``unused_variables``' extras tables) with
      role ``"reference"``.
    - Names extracted from any of the above never land in
      ``report.undefined`` -- an approximate extraction must not invent an
      undeclared symbol.
    - The declared-symbol set is the one ``collect_declared_items`` defines
      (FILE / WORKING-STORAGE / LOCAL-STORAGE / LINKAGE), plus files,
      procedures, level-88 condition names (FILLER parents included),
      level-66 ``RENAMES`` items and ``INDEXED BY`` index names.
      SCREEN / COMMUNICATION / REPORT SECTION items and special registers are
      outside it, so a reference to one reads as undefined -- reported, with
      a caveat saying so, rather than silently swallowed.
    - Symbols are resolved by uppercased name, not by structural identity, so
      two same-named items at different qualification scopes (legal but rare
      in COBOL) share one entry; a duplicate declaration is reported as a
      caveat.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.xref import XrefAnalyzer

        report = XrefAnalyzer().analyze(parse_cobol(source).ast)
        for entry in report.entries:
            print(entry.name, entry.kind, entry.reference_count)
            for ref in entry.references:
                print("   ", ref.role, ref.location.line, ref.context)
        ```
    """

    def __init__(self) -> None:
        self._entries: list[XrefEntry] = []
        self._data: dict[str, XrefEntry] = {}
        # Every declared data item of a name, with its entry: two records
        # holding a same-named field get one entry each (issue #258).
        self._data_items: dict[str, list[tuple[XrefEntry, Any]]] = {}
        self._procedures: dict[str, XrefEntry] = {}
        self._files: dict[str, XrefEntry] = {}
        self._undefined: dict[tuple[str, str], XrefEntry] = {}
        self._caveats: list[str] = []
        self._generic_statements: set[str] = set()
        self._location_fallbacks: int = 0
        self._dropped_tokens: int = 0
        self._special_registers: set[str] = set()
        self._duplicates: set[str] = set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def analyze(self, ast: CobolProgram) -> XrefReport:
        """Cross-reference every symbol of *ast* (one program unit).

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            An XrefReport whose ``entries`` are sorted by kind then name.
        """
        self._entries = []
        self._data = {}
        self._data_items = {}
        self._procedures = {}
        self._files = {}
        self._undefined = {}
        self._caveats = []
        self._generic_statements = set()
        self._location_fallbacks = 0
        self._dropped_tokens = 0
        self._special_registers = set()
        self._duplicates = set()

        self._collect_data_definitions(ast)
        self._collect_file_definitions(ast)
        self._collect_procedure_definitions(ast)
        self._collect_references(ast)
        self._collect_contained_references(ast)

        if self._location_fallbacks:
            self._caveat(
                f"{self._location_fallbacks} reference(s) had no usable statement "
                "location; the enclosing paragraph's location was used instead"
            )
        if self._dropped_tokens:
            self._caveat(
                f"{self._dropped_tokens} extracted token(s) matched no declared "
                "symbol and could not be one -- a reserved word, an intrinsic "
                "function name, or a truncated operand -- so they were dropped "
                "rather than reported as undeclared symbols"
            )
        if self._generic_statements:
            names = ", ".join(sorted(self._generic_statements))
            self._caveat(
                "role 'reference' was used for operands of statement types with "
                f"no dedicated role mapping: {names}"
            )
        if self._undefined:
            self._caveat(
                "the kind of an undefined symbol is inferred from the role it is "
                "used in (procedure for perform/goto, file for file-operation, "
                "data-item otherwise), not from a declaration"
            )
            self._caveat(
                "'undefined' means 'not declared in anything this analyzer sees': "
                "SCREEN / COMMUNICATION / REPORT SECTION items, special registers "
                "and non-IBM dialect words are outside its declared-symbol set and "
                "read as undefined"
            )

        entries = [*self._entries, *self._undefined.values()]
        for entry in entries:
            entry.references.sort(
                key=lambda ref: (
                    ref.location.line,
                    ref.location.column,
                    ref.role,
                    ref.statement,
                )
            )
        entries.sort(key=lambda e: (_KIND_ORDER.get(e.kind, len(_KIND_ORDER)), e.name))

        if self._special_registers:
            names = ", ".join(sorted(self._special_registers))
            self._caveat(
                "special registers / precompiler-supplied items referenced but "
                f"not declared here, excluded from 'undefined': {names}"
            )
        return XrefReport(
            entries=entries,
            undefined=sorted({e.name for e in self._undefined.values()}),
            caveats=list(self._caveats),
            duplicate_declarations=sorted(self._duplicates),
        )

    # ------------------------------------------------------------------
    # Definition collection
    # ------------------------------------------------------------------

    def _caveat(self, text: str) -> None:
        """Append a caveat once (order preserved, duplicates dropped)."""
        if text not in self._caveats:
            self._caveats.append(text)

    def _define(
        self,
        name: str,
        kind: str,
        location: SourceLocation | None,
        *,
        level: int | None = None,
        section: str | None = None,
        item: Any = None,
    ) -> XrefEntry:
        """Register a declared symbol, or return the existing entry.

        A data item (*item* given) whose name is already declared gets an
        entry of its own when it sits in a different record (a different
        chain of enclosing items): both are then qualified. The same chain
        declared twice (a copybook COPYed into two sections) is a duplicate.
        """
        upper = name.upper()
        table = self._table_for_kind(kind)
        existing = table.get(upper)
        if item is not None:
            path = _ancestor_names(item)
            namesakes = self._data_items.setdefault(upper, [])
            if existing is not None and all(
                _ancestor_names(other) != path for _, other in namesakes
            ):
                entry = XrefEntry(
                    name=upper,
                    kind=kind,
                    definition=location,
                    references=[],
                    level=level,
                    section=section,
                )
                namesakes.append((entry, item))
                self._entries.append(entry)
                for named, named_item in namesakes:
                    named.qualified_name = QUALIFIER_SEPARATOR.join(
                        [upper, *_ancestor_names(named_item)]
                    )
                return entry
        if existing is not None:
            self._duplicates.add(upper)
            self._caveat(
                f"{existing.kind} '{upper}' is declared more than once; every "
                "reference is attributed to the first declaration"
            )
            return existing
        entry = XrefEntry(
            name=upper,
            kind=kind,
            definition=location,
            references=[],
            level=level,
            section=section,
        )
        table[upper] = entry
        self._entries.append(entry)
        if item is not None:
            self._data_items.setdefault(upper, []).append((entry, item))
        return entry

    def _table_for_kind(self, kind: str) -> dict[str, XrefEntry]:
        if kind in (KIND_PARAGRAPH, KIND_SECTION):
            return self._procedures
        if kind == KIND_FILE:
            return self._files
        return self._data

    def _collect_data_definitions(self, ast: CobolProgram) -> None:
        """Every DATA DIVISION item, level-88 condition name and level-66
        RENAMES item, in source order (the first declaration of a name wins).

        The data items are exactly ``collect_declared_items``'. Two kinds of
        name sit beside, rather than among, those items (issue #485):

        - A FILLER is never a name, but the level-88s under it are: the
          ``05 FILLER PIC X VALUE 'N'. 88 SW-ON VALUE 'Y'.`` switch is a
          common batch idiom, and dropping the FILLER together with its
          children listed every such switch in ``undefined``.
        - A level-66 ``RENAMES`` item is a section child of its own
          (``RenamesItem``, not a ``CobolDataItem``), so the data-item walk
          never sees it.

        A contained program also sees its containers' GLOBAL records
        (``inherited_data_records``, #504): they are defined after its own
        items, at their own declaration, so a reference to one resolves
        instead of reading as undefined.
        """
        declared = {id(item) for item in collect_declared_items(ast)}
        data_div = ast.data_division
        sections = data_div.sections if data_div is not None else []
        for data_section in sections:
            if not isinstance(data_section, CobolSection):
                continue
            section = data_section.section_name or "UNKNOWN"
            if section.upper() not in _DATA_SECTION_NAMES:
                continue
            for top_item in data_section.data_items:
                self._define_record(top_item, section, declared)
            for child in data_section.children:
                if isinstance(child, RenamesItem) and child.name:
                    self._define(
                        child.name,
                        KIND_DATA_ITEM,
                        child.location,
                        level=66,
                        section=section,
                        item=child,
                    )

        for _owner, section, record in inherited_data_records(ast):
            self._define_record(
                record,
                section,
                {
                    id(item)
                    for item in [record, *record.get_all_children()]
                    if not item.is_filler
                    and not item.name.upper().startswith("ANONYMOUS-")
                },
            )

    def _define_record(
        self, top_item: CobolDataItem, section: str, declared: set[int]
    ) -> None:
        """Define *top_item*, its subordinates, their level-88s and index
        names (the items in *declared* only, and the level-88s under any
        FILLER)."""
        for item in [top_item, *top_item.get_all_children()]:
            if id(item) in declared:
                self._define(
                    item.name,
                    KIND_DATA_ITEM,
                    item.location,
                    level=item.level,
                    section=section,
                    item=item,
                )
            elif not item.is_filler:
                continue
            self._define_condition_names(item, section)
            # `OCCURS ... INDEXED BY ix` declares `ix` as a name in its own
            # right -- it is not a data item of its own (no level number, no
            # PICTURE), but SET/SEARCH/subscript references to it are real
            # references a cross-reference listing must resolve.
            self._define_index_names(item, section)

    def _define_condition_names(self, item: CobolDataItem, section: str) -> None:
        """The level-88 condition names written directly under *item*."""
        for child in item.children:
            if isinstance(child, ConditionNameItem):
                self._define(
                    child.name,
                    KIND_CONDITION_NAME,
                    child.location,
                    level=88,
                    section=section,
                    item=child,
                )

    def _define_index_names(self, item: CobolDataItem, section: str) -> None:
        """The ``INDEXED BY`` names of *item*'s OCCURS clause."""
        occurs = item.occurs_clause
        if occurs is None:
            return
        # ``indexed_by`` is the first of ``index_names`` (kept for
        # backward compatibility), not another index: declaring it again
        # listed every INDEXED BY name in ``duplicate_declarations``.
        index_names = list(occurs.index_names)
        if occurs.indexed_by and occurs.indexed_by.upper() not in {
            name.upper() for name in index_names
        }:
            index_names.append(occurs.indexed_by)
        for index_name in index_names:
            if index_name:
                self._define(
                    index_name,
                    KIND_DATA_ITEM,
                    item.location,
                    level=None,
                    section=section,
                )

    def _collect_file_definitions(self, ast: CobolProgram) -> None:
        """Every file named by a SELECT (ENVIRONMENT) or an FD/SD record.

        A file declared by only one of the two still gets an entry: the
        ``SELECT`` carries the location when there is one, otherwise the FD
        record's own location does.
        """
        inner = _contained_node_ids(ast)
        for node in ast.traverse_depth_first():
            if id(node) in inner:
                continue
            if isinstance(node, SelectStatement) and node.file_name:
                self._define_file(node.file_name, node.location)

        data_div = ast.data_division
        if data_div is None:
            return
        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            for record in section.data_items:
                fd_file = record.get_metadata("fd_file_name")
                if fd_file:
                    self._define_file(str(fd_file), record.location)

    def _define_file(self, name: str, location: SourceLocation) -> None:
        """Declare a file once, from whichever half is seen first.

        A file is normally declared *twice* -- a ``SELECT`` in the
        ENVIRONMENT DIVISION and an ``FD``/``SD`` in the FILE SECTION -- and
        those two halves are one declaration of one file, not a duplicate.
        The SELECT is collected first, so its location is the one kept.
        """
        if name.upper() in self._files:
            return
        self._define(name, KIND_FILE, location)

    def _collect_procedure_definitions(self, ast: CobolProgram) -> None:
        """Every PROCEDURE DIVISION section and paragraph, in source order.

        Mirrors ``DeadCodeAnalyzer._collect_procedures``: sections and
        top-level paragraphs are interleaved by source line, since COBOL
        allows paragraphs before the first SECTION header.
        """
        proc_division = ast.procedure_division
        if proc_division is None:
            return
        for item in self._ordered_procedures(proc_division):
            if isinstance(item, CobolSection):
                if item.section_name:
                    self._define(item.section_name, KIND_SECTION, item.location)
                for para in item.paragraphs:
                    if self._is_valid_procedure_name(para.paragraph_name):
                        self._define(para.paragraph_name, KIND_PARAGRAPH, para.location)
            elif self._is_valid_procedure_name(item.paragraph_name):
                self._define(item.paragraph_name, KIND_PARAGRAPH, item.location)

    @staticmethod
    def _ordered_procedures(
        proc_division: CobolDivision,
    ) -> list[CobolSection | CobolParagraph]:
        items: list[CobolSection | CobolParagraph] = [
            *proc_division._sections.values(),
            *proc_division.paragraphs,
        ]
        return sorted(items, key=lambda node: node.location.line)

    @staticmethod
    def _is_valid_procedure_name(name: str | None) -> bool:
        """Reject the synthetic paragraph names the parser can emit (a lone
        period), same filter ``DeadCodeAnalyzer`` applies.
        """
        return bool(name) and name not in (".",)

    # ------------------------------------------------------------------
    # Reference collection
    # ------------------------------------------------------------------

    def _collect_references(self, ast: CobolProgram) -> None:
        """Walk every statement, in its paragraph context, and record roles.

        The PROCEDURE DIVISION is walked structurally (section -> paragraph ->
        statement -> nested statement) so each reference knows the paragraph
        it sits in. A second sweep picks up statements that live outside a
        paragraph -- notably a DATA DIVISION ``EXEC SQL`` -- which would
        otherwise be invisible; those get ``context=None``.
        """
        visited: set[int] = set()

        proc_division = ast.procedure_division
        if proc_division is not None:
            for item in self._ordered_procedures(proc_division):
                if isinstance(item, CobolSection):
                    for para in item.paragraphs:
                        self._visit_paragraph(para, visited)
                else:
                    self._visit_paragraph(item, visited)

        inner = _contained_node_ids(ast)
        for node in ast.traverse_depth_first():
            if id(node) in inner:
                # A contained program is an AST child; its statements
                # belong to its own symbol table, not this unit's.
                continue
            if isinstance(node, CobolStatement) and id(node) not in visited:
                visited.add(id(node))
                if isinstance(node, SelectStatement):
                    # The SELECT *is* the file's declaration, not a use of
                    # it -- but the data items its clauses name are used.
                    self._visit_select_clauses(node)
                    continue
                self._visit_statement(node, context=None, fallback=None)

        self._visit_data_division_references(ast)

    def _collect_contained_references(self, ast: CobolProgram) -> None:
        """Add the references *ast*'s contained programs make to *ast*'s
        own GLOBAL items (#504).

        Each contained program is cross-referenced on its own; its entries
        for items it inherited from *ast* (the same item object, so a name
        it redeclares is not one of them) carry those references. Its own
        contained programs are folded into it first, so direct children
        cover every depth.
        """
        if not ast.contained_programs:
            return
        mine = {
            id(item): entry
            for namesakes in self._data_items.values()
            for entry, item in namesakes
        }
        for contained in ast.contained_programs:
            inner = XrefAnalyzer()
            inner.analyze(contained)
            for namesakes in inner._data_items.values():
                for entry, item in namesakes:
                    target = mine.get(id(item))
                    if target is not None:
                        target.references.extend(entry.references)

    def _visit_select_clauses(self, select: SelectStatement) -> None:
        """Data items a ``SELECT`` names: FILE STATUS, RECORD / ALTERNATE /
        RELATIVE KEY, PASSWORD, ASSIGN USING, PADDING CHARACTER.

        The runtime stores into the FILE STATUS item after every I/O, reads
        the key items on every keyed READ / START / WRITE / DELETE (and
        writes the RELATIVE KEY on a sequential READ), and reads the padding
        item on every WRITE, whether or not the PROCEDURE DIVISION ever names
        them -- ``UnusedVariableAnalyzer._file_control_references`` counts
        them as used, and listing them unreferenced here contradicted that
        (#549, #556). Recorded with role ``"reference"`` at the SELECT; the
        roles a READ / START gives the keys are unchanged.
        """
        values: list[str | None] = [
            select.file_status,
            select.file_status_vsam,
            select.record_key,
            select.record_key_source,
            select.relative_key,
            select.password,
            select.assign_using,
            select.padding_character,
        ]
        for alternate in select.alternate_keys:
            values.append(alternate.get("key"))
            values.append(alternate.get("password"))
        self._record_structural(
            [value for value in values if value], select.location, "SelectStatement"
        )

    def _visit_data_division_references(self, ast: CobolProgram) -> None:
        """References that live in the DATA DIVISION itself.

        ``OCCURS ... DEPENDING ON`` counters and the data items an FD's own
        clauses name (``RECORD VARYING ... DEPENDING ON``, ``LINAGE``):
        ``UnusedVariableAnalyzer`` counts them as used, so a cross-reference
        that listed them unreferenced contradicted it. Recorded with role
        ``"reference"`` at the declaring entry's location.
        """
        for item in collect_declared_items(ast):
            fd_names = UnusedVariableAnalyzer._fd_clause_references(item)
            if fd_names:
                self._record_structural(sorted(fd_names), item.location, "FD")
            occurs = item.occurs_clause
            if occurs is not None and occurs.depending_on:
                self._record_structural(
                    [occurs.depending_on], item.location, "OCCURS DEPENDING ON"
                )

    def _record_structural(
        self, values: list[str], location: SourceLocation, statement: str
    ) -> None:
        """Record DATA/ENVIRONMENT DIVISION clause operands as references."""
        emitted: set[str] = set()
        for value in values:
            for name in sorted(_extract_identifiers(value)):
                if name in emitted:
                    continue
                emitted.add(name)
                self._record(
                    name, ROLE_REFERENCE, location, statement, None, exact=True
                )

    def _visit_paragraph(self, para: CobolParagraph, visited: set[int]) -> None:
        context = para.paragraph_name
        for stmt in para.statements:
            self._visit_statement_tree(stmt, context, para.location, visited)

    def _visit_statement_tree(
        self,
        node: ASTNode,
        context: str | None,
        fallback: SourceLocation | None,
        visited: set[int],
    ) -> None:
        """Visit *node* and every statement nested beneath it.

        Nested statements (an IF's THEN arm, a READ's AT END clause, a PERFORM
        inline body) are registered as AST children by the statement models,
        so one child walk reaches all of them regardless of which clause
        attribute holds them.
        """
        if id(node) in visited:
            return
        visited.add(id(node))
        if isinstance(node, CobolStatement):
            self._visit_statement(node, context, fallback)
        for child in node.children:
            self._visit_statement_tree(child, context, fallback, visited)

    def _visit_statement(
        self,
        stmt: CobolStatement,
        context: str | None,
        fallback: SourceLocation | None,
    ) -> None:
        location = self._location_of(stmt, fallback)
        statement_name = type(stmt).__name__
        recorded: set[str] = set()
        # One statement can name the same symbol in the same role twice (an
        # ADD's ``target`` and ``targets`` are the same operand under two
        # attributes); that is one reference, not two.
        emitted: set[tuple[str, str]] = set()

        for value, role, exact in self._role_assignments(stmt):
            for name, resolved_role, name_exact in self._names_for(value, role):
                recorded.add(name)
                if (name, resolved_role) in emitted:
                    continue
                emitted.add((name, resolved_role))
                self._record(
                    name,
                    resolved_role,
                    location,
                    statement_name,
                    context,
                    exact and name_exact,
                )

        residual = self._residual_names(stmt) - recorded
        if residual and not isinstance(stmt, _ROLE_MAPPED_STATEMENTS):
            self._generic_statements.add(statement_name)
        for name in sorted(residual):
            self._record(
                name, ROLE_REFERENCE, location, statement_name, context, exact=False
            )

    def _location_of(
        self, stmt: CobolStatement, fallback: SourceLocation | None
    ) -> SourceLocation:
        location = getattr(stmt, "location", None)
        if isinstance(location, SourceLocation) and location.line > 0:
            return location
        if fallback is not None:
            self._location_fallbacks += 1
            return fallback
        return (
            location if isinstance(location, SourceLocation) else SourceLocation(0, 0)
        )

    def _names_for(self, value: Any, role: str) -> list[tuple[str, str, bool]]:
        """Resolve one operand-position value into (name, role, exact) triples.

        A ``CobolExpression`` is walked structurally by
        ``_walk_expression_operands``; anything else is operand text split by
        ``_partition_operand`` into the operand itself (keeping *role*) and
        its subscripts (role ``"subscript"``).
        """
        if value is None:
            return []
        if role in _PROCEDURE_ROLES and isinstance(value, str):
            # A procedure name is one word, and the dominant mainframe
            # convention makes it digit-led (``1000-INIT``); the generic
            # identifier extraction would split that into ``INIT``.
            target = value.strip().upper()
            if _COBOL_WORD_RE.match(target):
                return [(target, role, True)]
        if isinstance(value, _RawText):
            return [
                (name, role, False) for name in sorted(_extract_identifiers(value.text))
            ]
        if isinstance(value, CobolExpression):
            return [
                (name, role, True) for name in sorted(_walk_expression_operands(value))
            ]
        if not isinstance(value, str):
            # Clause values read out of a dict (a PERFORM AFTER's
            # ``until_condition``, ...) may be an expression *or* raw operand
            # text; ``_names_from_value`` is exactly that dispatch.
            return [(name, role, True) for name in sorted(_names_from_value(value))]
        if _FUNCTION_RE.search(value):
            self._caveat(
                "an intrinsic FUNCTION reference joins the function name and its "
                "arguments into one operand string; its identifiers are extracted "
                "best-effort, are not classified as subscripts, and are not exact"
            )
        base, refmod, subscripts, exact = _split_operand(value)
        # A reference modifier's offset/length is only ever read, even on a
        # receiving operand: `MOVE X TO WS-B (WS-P:2)` writes WS-B, not WS-P.
        refmod_role = ROLE_READ if role == ROLE_WRITE else role
        # A qualifier is not written: `MOVE X TO WS-A OF WS-GRP` writes WS-A
        # and only names WS-GRP to locate it.
        qualifiers = _qualifier_names(value) if role == ROLE_WRITE else set()
        triples = [
            (name, ROLE_REFERENCE if name in qualifiers else role, exact)
            for name in sorted(base)
        ]
        triples += [(name, refmod_role, exact) for name in sorted(refmod)]
        triples += [(name, ROLE_SUBSCRIPT, exact) for name in sorted(subscripts)]
        return triples

    def _record(
        self,
        name: str,
        role: str,
        location: SourceLocation,
        statement: str,
        context: str | None,
        exact: bool,
    ) -> None:
        """Attach one reference to the entry *name* resolves to.

        A name that resolves against nothing becomes an ``definition=None``
        entry *only* when the extraction was exact; an approximate extraction
        (raw condition text, EXEC CICS/DLI arguments, a generic operand sweep)
        never invents an undeclared symbol -- it would report intrinsic
        function names and stray keywords as undefined data items.
        """
        upper, *qualifiers = name.upper().split(QUALIFIER_SEPARATOR)
        entries = self._lookup_all(upper, role, qualifiers)
        if len(entries) > 1:
            # Every same-named item the reference can mean, as
            # UnusedVariableAnalyzer counts it.
            for candidate in entries:
                candidate.references.append(
                    XrefReference(
                        location=location,
                        role=role,
                        statement=statement,
                        context=context,
                    )
                )
            return
        entry = entries[0] if entries else None
        if entry is None and upper in _SPECIAL_REGISTERS:
            self._special_registers.add(upper)
            return
        if entry is None and (
            upper in _RESERVED_WORDS or not _COBOL_WORD_RE.match(upper)
        ):
            self._dropped_tokens += 1
            return
        if entry is None:
            if not exact:
                return
            kind = self._kind_for_role(role)
            key = (kind, upper)
            entry = self._undefined.get(key)
            if entry is None:
                entry = XrefEntry(name=upper, kind=kind, definition=None, references=[])
                self._undefined[key] = entry
        entry.references.append(
            XrefReference(
                location=location, role=role, statement=statement, context=context
            )
        )

    def _lookup_all(
        self, upper: str, role: str, qualifiers: list[str]
    ) -> list[XrefEntry]:
        """The entries a reference resolves to: one, unless an unqualified
        (or unresolvable) reference names a data item several records
        declare, which counts for each of them."""
        if role not in _PROCEDURE_ROLES and role != ROLE_FILE_OPERATION:
            namesakes = self._data_items.get(upper, [])
            if len(namesakes) > 1:
                if qualifiers:
                    matched = [
                        entry
                        for entry, item in namesakes
                        if _qualifiers_match(item, qualifiers)
                    ]
                    if matched:
                        return matched
                return [entry for entry, _ in namesakes]
        entry = self._lookup(upper, role)
        return [entry] if entry is not None else []

    def _lookup(self, upper: str, role: str) -> XrefEntry | None:
        if role in _PROCEDURE_ROLES:
            return self._procedures.get(upper)
        if role == ROLE_FILE_OPERATION:
            return self._files.get(upper)
        return self._data.get(upper)

    @staticmethod
    def _kind_for_role(role: str) -> str:
        if role in _PROCEDURE_ROLES:
            return KIND_PARAGRAPH
        if role == ROLE_FILE_OPERATION:
            return KIND_FILE
        return KIND_DATA_ITEM

    # ------------------------------------------------------------------
    # Residual (generic) operand sweep
    # ------------------------------------------------------------------

    def _residual_names(self, stmt: CobolStatement) -> set[str]:
        """Every identifier reachable from a statement's generic operand bag.

        Reuses ``unused_variables``' extras tables verbatim -- the statement
        attributes that never reach ``.operands`` -- so a statement type this
        module has no dedicated mapping for still contributes references
        (with role ``"reference"``) instead of silently dropping them.
        """
        names: set[str] = set()
        for operand in stmt.operands:
            base, subscripts, _ = _partition_operand(str(operand))
            names |= base | subscripts

        for klass in type(stmt).__mro__:
            for attr in _STR_ATTR_EXTRAS.get(klass, ()):
                names |= _extract_identifiers(getattr(stmt, attr, None))
            for attr in _STR_LIST_EXTRAS.get(klass, ()):
                for value in getattr(stmt, attr, None) or []:
                    names |= _extract_identifiers(value)
            for attr, keys in _DICT_LIST_EXTRAS.get(klass, ()):
                for entry in getattr(stmt, attr, None) or []:
                    for key in keys:
                        names |= _extract_identifiers(entry.get(key))
        return names

    # ------------------------------------------------------------------
    # Role assignment, statement type by statement type
    # ------------------------------------------------------------------

    def _role_assignments(self, stmt: CobolStatement) -> list[tuple[Any, str, bool]]:
        """The (value, role, exact) triples this statement states explicitly.

        Whatever is *not* covered here is still swept up by
        ``_residual_names`` with role ``"reference"``, so adding a mapping
        only ever sharpens a role -- it never adds or removes a reference.
        """
        pairs: list[tuple[Any, str, bool]] = []
        pairs.extend(self._data_statement_roles(stmt))
        pairs.extend(self._control_statement_roles(stmt))
        pairs.extend(self._io_statement_roles(stmt))
        pairs.extend(self._exec_statement_roles(stmt))
        return pairs

    def _data_statement_roles(
        self, stmt: CobolStatement
    ) -> list[tuple[Any, str, bool]]:
        pairs: list[tuple[Any, str, bool]] = []
        if isinstance(stmt, MoveStatement):
            if stmt.source:
                pairs.append((stmt.source, ROLE_READ, True))
            pairs += [(t, ROLE_WRITE, True) for t in stmt.targets]
        elif isinstance(stmt, DisplayStatement):
            pairs += [(item, ROLE_READ, True) for item in stmt.display_items]
        elif isinstance(stmt, ComputeStatement):
            pairs += [(t, ROLE_WRITE, True) for t in stmt.targets]
            if stmt.expression is not None:
                pairs.append((stmt.expression, ROLE_READ, True))
            if stmt.expression_tree is not None:
                pairs.append((stmt.expression_tree, ROLE_READ, True))
        elif isinstance(stmt, ArithmeticStatement):
            # With GIVING, only the GIVING (and REMAINDER) items change: the
            # TO/FROM operand of `SUBTRACT A FROM B GIVING C` is read, never
            # written. Without GIVING, the TO/FROM/BY/INTO target is both
            # read and written (`ADD A TO B` is B = B + A).
            givings = [*stmt.givings, *([stmt.giving] if stmt.giving else [])]
            targets = [*stmt.targets, *([stmt.target] if stmt.target else [])]
            written: list[str] = list(givings) if givings else list(targets)
            if isinstance(stmt, DivideStatement) and stmt.remainder:
                written.append(stmt.remainder)
            # The sending operands. `.operands` also holds target/GIVING
            # names, appended only when absent, so it cannot tell `ADD A B
            # GIVING B` from `ADD A GIVING B`: ADD/SUBTRACT record what was
            # written before TO/FROM/GIVING, and MULTIPLY/DIVIDE always put
            # their two operands first.
            if stmt.source_operands is not None:
                read: list[str] = [*stmt.source_operands, *targets]
            elif isinstance(stmt, (MultiplyStatement, DivideStatement)):
                if givings or not targets:
                    read = list(stmt.operands[:2])
                else:
                    # `MULTIPLY n BY a b` is a = a * n; b = b * n: every
                    # BY/INTO receiver is read, not just the first (#534).
                    read = [*stmt.operands[:1], *targets]
            else:
                consumed = {name.upper() for name in written}
                read = [op for op in stmt.operands if op.upper() not in consumed]
            pairs += [(name, ROLE_WRITE, True) for name in written]
            pairs += [(name, ROLE_READ, True) for name in read]
        elif isinstance(stmt, SetStatement):
            pairs += [(t, ROLE_WRITE, True) for t in stmt.targets]
            if stmt.value:
                pairs.append((stmt.value, ROLE_READ, False))
            for group in stmt.groups:
                pairs += [(t, ROLE_WRITE, True) for t in group.get("targets") or []]
                if group.get("value"):
                    pairs.append((group["value"], ROLE_READ, False))
        elif isinstance(stmt, AllocateStatement):
            # ALLOCATE gives a based item storage (its address is set, its
            # bytes are not read or written -- INITIALIZED aside) and writes
            # the RETURNING pointer; the CHARACTERS size is read (#570).
            if stmt.data_item:
                pairs.append((stmt.data_item, ROLE_REFERENCE, True))
            if stmt.size_expr:
                pairs.append((stmt.size_expr, ROLE_READ, True))
            if stmt.returning_target:
                pairs.append((stmt.returning_target, ROLE_WRITE, True))
        elif isinstance(stmt, FreeStatement):
            # FREE releases the storage and sets each pointer to NULL.
            pairs += [(name, ROLE_WRITE, True) for name in stmt.pointer_names]
        elif isinstance(stmt, InitializeStatement):
            pairs += [(t, ROLE_WRITE, True) for t in stmt.targets]
            # A REPLACING ``BY`` value arrives with its string-literal quotes
            # already stripped, so a literal's contents cannot be told apart
            # from an identifier -- inexact, and never an undefined symbol.
            pairs += [
                (clause.get("by_value"), ROLE_READ, False)
                for clause in stmt.replacing_clauses
            ]
        elif isinstance(stmt, StringStatement):
            if stmt.into_target:
                pairs.append((stmt.into_target, ROLE_WRITE, True))
            if stmt.pointer_variable:
                # WITH POINTER starts at the pointer's current value and
                # advances it: read and written (#269).
                pairs.append((stmt.pointer_variable, ROLE_READ, True))
                pairs.append((stmt.pointer_variable, ROLE_WRITE, True))
            # ``DELIMITED BY`` holds either a data name, a (quoted) literal,
            # or the keyword SIZE -- inexact either way.
            pairs += [(d, ROLE_READ, False) for d in stmt.delimiters]
            consumed = {
                value.upper()
                for value in (stmt.into_target, stmt.pointer_variable)
                if value
            }
            # A literal operand arrives quoted (``'VERY LONG TEXT'`` as
            # ``"VERY LONG TEXT"``); operands stay inexact so a figurative
            # constant or special register is never reported undefined.
            pairs += [
                (operand, ROLE_READ, False)
                for operand in stmt.operands
                if operand.upper() not in consumed
            ]
        elif isinstance(stmt, UnstringStatement):
            if stmt.source_operand:
                pairs.append((stmt.source_operand, ROLE_READ, True))
            pairs += [(d, ROLE_READ, False) for d in stmt.delimiters]
            for target in stmt.into_targets:
                if target.get("target"):
                    pairs.append((target["target"], ROLE_WRITE, True))
                if target.get("count_var"):
                    pairs.append((target["count_var"], ROLE_WRITE, True))
                if target.get("delimiter_var"):
                    pairs.append((target["delimiter_var"], ROLE_WRITE, True))
            # POINTER starts at its current value and is advanced; TALLYING
            # IN is incremented, never reset: both read and written (#269).
            for value in (stmt.pointer_variable, stmt.tallying_variable):
                if value:
                    pairs.append((value, ROLE_READ, True))
                    pairs.append((value, ROLE_WRITE, True))
        elif isinstance(stmt, InspectStatement):
            if stmt.target:
                # The inspected item is always read; REPLACING / CONVERTING
                # rewrite it in place, so it is written too (#269).
                pairs.append((stmt.target, ROLE_READ, True))
                inspected = (stmt.inspect_type or "").upper()
                # ``TALLYING ... REPLACING`` is recorded as TALLYING_REPLACING.
                if inspected in ("REPLACING", "CONVERTING", "TALLYING_REPLACING"):
                    pairs.append((stmt.target, ROLE_WRITE, True))
            for clause in stmt.tallying_clauses:
                if clause.get("counter"):
                    # TALLYING adds to the counter's current value: it is
                    # read as well as written (#269).
                    pairs.append((clause["counter"], ROLE_READ, True))
                    pairs.append((clause["counter"], ROLE_WRITE, True))
                # Everything else in an INSPECT clause is a value that may
                # equally be a (quoted) literal or a figurative -- inexact.
                for key in ("value", "before", "after"):
                    if clause.get(key):
                        pairs.append((clause[key], ROLE_READ, False))
            for clause in stmt.replacing_clauses:
                for key in ("from_value", "to_value", "before", "after"):
                    if clause.get(key):
                        pairs.append((clause[key], ROLE_READ, False))
            if stmt.converting_from:
                pairs.append((stmt.converting_from, ROLE_READ, False))
            for value in (
                stmt.converting_to,
                stmt.converting_before,
                stmt.converting_after,
            ):
                if value:
                    pairs.append((value, ROLE_READ, False))
        elif isinstance(stmt, XmlJsonStatement):
            if stmt.primary_operand:
                role = ROLE_WRITE if stmt.action == "GENERATE" else ROLE_READ
                pairs.append((stmt.primary_operand, role, True))
            if stmt.from_item:
                pairs.append((stmt.from_item, ROLE_READ, True))
            # COUNT IN and JSON PARSE's INTO receive a value; every other
            # clause subject (NAME OF / TYPE OF / SUPPRESS / CONVERTING /
            # NAMESPACE ...) is read.
            for receiver in (stmt.count_in, stmt.into_item):
                if receiver:
                    pairs.append((receiver, ROLE_WRITE, True))
            pairs += [(name, ROLE_READ, True) for name in stmt.clause_items]
            if stmt.processing_procedure:
                pairs.append((stmt.processing_procedure, ROLE_PERFORM, True))
            if stmt.processing_procedure_thru:
                pairs.append((stmt.processing_procedure_thru, ROLE_PERFORM, True))
        return pairs

    def _control_statement_roles(
        self, stmt: CobolStatement
    ) -> list[tuple[Any, str, bool]]:
        pairs: list[tuple[Any, str, bool]] = []
        if isinstance(stmt, IfStatement):
            if stmt.condition is not None:
                pairs.append((stmt.condition, ROLE_CONDITION, True))
        elif isinstance(stmt, EvaluateStatement):
            # An expression-shaped subject only ever reaches `add_child()`,
            # never `.operands` (see EvaluateStatement.add_subject), so this
            # walk is its only coverage.
            pairs += [(subject, ROLE_CONDITION, True) for subject in stmt.subjects]
            clauses = list(stmt.when_clauses)
            if stmt.default_when is not None:
                clauses.append(stmt.default_when)
            for clause in clauses:
                for selector in clause.selectors:
                    pairs.extend(self._selector_roles(selector))
        elif isinstance(stmt, PerformStatement):
            if stmt.target_paragraph:
                pairs.append((stmt.target_paragraph, ROLE_PERFORM, True))
            if stmt.thru_paragraph:
                pairs.append((stmt.thru_paragraph, ROLE_PERFORM, True))
            if stmt.until_condition is not None:
                pairs.append((stmt.until_condition, ROLE_CONDITION, True))
            if isinstance(stmt.times_count, str):
                pairs.append((stmt.times_count, ROLE_READ, True))
            varying = [c for c in (stmt.varying_clause,) if c] + list(
                stmt.after_clauses
            )
            for varying_clause in varying:
                if varying_clause.get("variable"):
                    pairs.append((varying_clause["variable"], ROLE_WRITE, True))
                for key in ("from_value", "by_value"):
                    if varying_clause.get(key):
                        pairs.append((varying_clause[key], ROLE_READ, True))
                if varying_clause.get("until_condition") is not None:
                    pairs.append(
                        (varying_clause["until_condition"], ROLE_CONDITION, True)
                    )
        elif isinstance(stmt, GoStatement):
            pairs += [(target, ROLE_GOTO, True) for target in stmt.target_paragraphs]
            if stmt.depending_on_variable:
                pairs.append((stmt.depending_on_variable, ROLE_READ, True))
        elif isinstance(stmt, AlterStatement):
            # Both halves of `ALTER x TO PROCEED TO y` name a procedure: `y`
            # is the new jump target, `x` the paragraph whose GO TO is
            # rewritten. Both are recorded in the procedure namespace.
            for alteration in stmt.alterations:
                for key in ("from_paragraph", "to_paragraph"):
                    if alteration.get(key):
                        pairs.append((alteration[key], ROLE_GOTO, True))
        elif isinstance(stmt, SearchStatement):
            if stmt.table_name:
                pairs.append((stmt.table_name, ROLE_READ, True))
            if stmt.varying_variable:
                pairs.append((stmt.varying_variable, ROLE_WRITE, True))
            for when_clause in stmt.when_clauses:
                condition = when_clause.get("condition")
                if condition:
                    self._caveat(
                        "SEARCH WHEN conditions carry only raw joined text, never a "
                        "structural tree; their identifiers are extracted "
                        "best-effort and are not exact"
                    )
                    pairs.append((str(condition), ROLE_CONDITION, False))
        elif isinstance(stmt, (SortStatement, MergeStatement)):
            file_name = getattr(stmt, "file_name", None)
            if file_name:
                pairs.append((file_name, ROLE_FILE_OPERATION, True))
            for attr in ("using_files", "giving_files"):
                for name in getattr(stmt, attr, None) or []:
                    pairs.append((name, ROLE_FILE_OPERATION, True))
            for sort_key in getattr(stmt, "keys", None) or []:
                if sort_key.get("field"):
                    pairs.append((sort_key["field"], ROLE_READ, True))
            for attr in (
                "input_procedure",
                "input_procedure_thru",
                "output_procedure",
                "output_procedure_thru",
            ):
                procedure = getattr(stmt, attr, None)
                if procedure:
                    pairs.append((procedure, ROLE_PERFORM, True))
        elif isinstance(stmt, CallStatement):
            for parameter in stmt.using_parameters:
                if parameter.name:
                    # BY CONTENT / BY VALUE hand the callee a copy: the
                    # caller's item is read and can never be written back.
                    # Only BY REFERENCE (the default) may go either way.
                    mode = (parameter.passing_mode or "REFERENCE").upper()
                    by_copy = mode in ("CONTENT", "VALUE")
                    role = ROLE_READ if by_copy else ROLE_CALL_ARGUMENT
                    pairs.append((parameter.name, role, True))
            for attr in ("returning_parameter", "giving_parameter"):
                value = getattr(stmt, attr, None)
                if value:
                    pairs.append((value, ROLE_WRITE, True))
            if stmt.is_dynamic and stmt.called_program:
                pairs.append((stmt.called_program, ROLE_READ, True))
        elif isinstance(stmt, EntryStatement):
            pairs += [
                (parameter, ROLE_CALL_ARGUMENT, True)
                for parameter in stmt.using_parameters
            ]
        return pairs

    def _selector_roles(self, selector: dict[str, Any]) -> list[tuple[Any, str, bool]]:
        """Roles for one EVALUATE WHEN selector dict.

        ``_build_selector`` in ``evaluate_parser.py`` classifies a bare
        data-name (or level-88 condition-name) selector as ``Literal``, never
        ``Identifier`` -- and selector values arrive with string-literal
        quotes already stripped, so a literal's *contents* cannot be told
        apart from an identifier. Those are therefore inexact: they attach to
        a declared name when one matches, but never invent an undefined one.
        """
        selector_type = selector.get("type")
        if selector_type == "Identifier":
            return [(selector.get("value"), ROLE_CONDITION, True)]
        if selector_type == "Literal":
            return [(selector.get("value"), ROLE_CONDITION, False)]
        if selector_type == "Range":
            return [
                (selector.get(key), ROLE_CONDITION, False) for key in ("start", "end")
            ]
        if selector_type == "Condition":
            text = selector.get("text")
            if text:
                self._caveat(
                    "EVALUATE TRUE condition selectors carry only raw joined text, "
                    "never a structural tree; their identifiers are extracted "
                    "best-effort and are not exact"
                )
                return [(str(text), ROLE_CONDITION, False)]
        return []

    def _io_statement_roles(self, stmt: CobolStatement) -> list[tuple[Any, str, bool]]:
        pairs: list[tuple[Any, str, bool]] = []
        if isinstance(stmt, (IOOpenStatement, IOCloseStatement)):
            pairs += [(name, ROLE_FILE_OPERATION, True) for name in stmt.file_names]
            return pairs

        file_name = getattr(stmt, "file_name", None)
        if file_name and isinstance(
            stmt,
            (
                IOReadStatement,
                IOWriteStatement,
                IORewriteStatement,
                IODeleteStatement,
                IOStartStatement,
                IOUnlockStatement,
            ),
        ):
            pairs.append((file_name, ROLE_FILE_OPERATION, True))

        if isinstance(stmt, IOReadStatement):
            if stmt.record_name:
                pairs.append((stmt.record_name, ROLE_WRITE, True))
            if stmt.into_target:
                pairs.append((stmt.into_target, ROLE_WRITE, True))
            if stmt.key_name:
                pairs.append((stmt.key_name, ROLE_READ, True))
        elif isinstance(stmt, (IOWriteStatement, IORewriteStatement)):
            if stmt.record_name:
                pairs.append((stmt.record_name, ROLE_READ, True))
            if stmt.from_clause:
                pairs.append((stmt.from_clause, ROLE_READ, True))
            # ``WRITE ... AFTER ADVANCING WS-N LINES``: the line count is
            # read on every WRITE. It lives in ``advancing_clause`` only
            # (never ``.operands``), as an int for a literal count and a
            # string for an identifier or a mnemonic-name / PAGE.
            advancing = getattr(stmt, "advancing_clause", None)
            if isinstance(advancing, dict) and isinstance(advancing.get("value"), str):
                pairs.append((advancing["value"], ROLE_READ, False))
        elif isinstance(stmt, IOStartStatement):
            if stmt.key_name:
                pairs.append((stmt.key_name, ROLE_READ, True))
        elif isinstance(stmt, IOAcceptStatement):
            if stmt.target:
                pairs.append((stmt.target, ROLE_WRITE, True))
        elif isinstance(stmt, ReleaseStatement):
            # The sort-side twin of WRITE: `RELEASE rec FROM x` reads x (and
            # hands rec's contents to the sort).
            if stmt.record_name:
                pairs.append((stmt.record_name, ROLE_READ, True))
            if stmt.from_source:
                pairs.append((stmt.from_source, ROLE_READ, True))
        elif isinstance(stmt, ReturnStatement):
            # The sort-side twin of READ: `RETURN sd-file INTO x` names the
            # SD file and writes x.
            if stmt.file_name:
                pairs.append((stmt.file_name, ROLE_FILE_OPERATION, True))
            if stmt.into_target:
                pairs.append((stmt.into_target, ROLE_WRITE, True))
        return pairs

    def _exec_statement_roles(
        self, stmt: CobolStatement
    ) -> list[tuple[Any, str, bool]]:
        """EXEC SQL host variables, and the raw-text EXEC CICS/DLI operands.

        Duck-typed rather than imported: ``host_variables`` /
        ``null_indicators`` / ``options`` / ``arguments`` are untyped raw text
        on every one of these classes, and importing them would add an
        analysis -> parsers layering dependency for no type-safety gain (the
        same call ``unused_variables`` makes).
        """
        pairs: list[tuple[Any, str, bool]] = []
        for attr in ("host_variables", "null_indicators"):
            for value in getattr(stmt, attr, None) or []:
                pairs.append((value, ROLE_HOST_VARIABLE, True))

        type_name = type(stmt).__name__
        if type_name == "ExecCicsStatement":
            options = getattr(stmt, "options", None) or {}
            if options:
                self._caveat(
                    "EXEC CICS options carry raw argument text with no fixed "
                    "argument-role shape; their identifiers get role 'reference'"
                )
            for value in options.values():
                if value:
                    pairs.append((_RawText(value), ROLE_REFERENCE, False))
        elif type_name == "ExecImsStatement":
            arguments = getattr(stmt, "arguments", None) or []
            if arguments:
                self._caveat(
                    "EXEC IMS/DLI arguments carry raw argument text with no fixed "
                    "argument-role shape; their identifiers get role 'reference'"
                )
            for value in arguments:
                if value:
                    pairs.append((_RawText(value), ROLE_REFERENCE, False))
        return pairs


#: Statement classes with a dedicated role mapping above. A residual operand
#: falling through to role "reference" on any *other* type is what the
#: generic-sweep caveat reports.
_ROLE_MAPPED_STATEMENTS: tuple[type, ...] = (
    AllocateStatement,
    AlterStatement,
    ArithmeticStatement,
    CallStatement,
    ComputeStatement,
    DisplayStatement,
    EntryStatement,
    EvaluateStatement,
    FreeStatement,
    GoStatement,
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
    IfStatement,
    InitializeStatement,
    InspectStatement,
    MergeStatement,
    MoveStatement,
    PerformStatement,
    ReleaseStatement,
    ReturnStatement,
    SearchStatement,
    SetStatement,
    SortStatement,
    StringStatement,
    UnstringStatement,
    XmlJsonStatement,
)
