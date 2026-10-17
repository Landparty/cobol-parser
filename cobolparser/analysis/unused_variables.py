"""
Unused variable detection for COBOL programs.

Analyzes the DATA DIVISION (WORKING-STORAGE, LINKAGE, FILE, and
LOCAL-STORAGE sections) to find declared data items that are never
referenced anywhere in the PROCEDURE DIVISION, and never structurally
depended on by another DATA DIVISION item (REDEFINES, OCCURS DEPENDING ON,
RENAMES). FILLER items are always excluded -- they are never nameable, so
"unused" is meaningless for them.

Single-program scope: like DeadCodeAnalyzer and ProgramFlowAnalyzer, this
analyzer only looks at *ast* itself, not ``ast.contained_programs``. Call
``analyze()`` separately on each contained program if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .._literals import QUOTED_LITERAL_RE
from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
    CobolStatement,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import (
    InitializeStatement,
    InspectStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.misc import (
    ContinueStatement,
    MergeStatement,
    SelectStatement,
    SortStatement,
    XmlJsonStatement,
)
from ._cics import cics_identifier_options
from ._names import QUALIFIER_SEPARATOR, qualified_references

# DATA DIVISION section names whose data items are in scope for this
# analysis. Matches the exact names the DATA DIVISION parser assigns (see
# parsers/divisions/data.py) -- the same convention LinkageChecker and
# CRUDMatrixGenerator rely on.
# REPORT SECTION is deliberately absent: its report groups are not
# candidates for "unused" (nothing outside the report names them), but the
# data items they READ are -- see `_report_section_references`, which mines
# SOURCE/SUM/CONTROL out of the report-group metadata so a Report Writer
# program's fields are not all reported unused.
# TODO(known limitation): SCREEN SECTION / COMMUNICATION SECTION items
# (screen fields, CD entries) are still entirely invisible to this analyzer.
# Adding those names to this frozenset alone would be a no-op: the DATA
# DIVISION parser's _skip_section (parsers/divisions/data.py) discards those
# sections' content into always-empty section nodes, so the parser must
# first retain their data items before this set could expose them.
_DATA_SECTION_NAMES = frozenset({"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"})

# OO units whose DATA DIVISION every contained METHOD sees, GLOBAL or not.
_OO_DATA_OWNERS = frozenset({"FACTORY", "OBJECT"})

# Words that can appear as, or inside, an operand's text but are never
# themselves a data-name reference: figurative constants, connective/
# qualification keywords the parser leaves joined into an operand string
# instead of splitting out (``WS-A OF WS-GRP``, ``FUNCTION UPPER-CASE(X)``,
# ``LENGTH OF X`` -- confirmed empirically, none of these reach
# ``.operands`` pre-split), and common raw condition-text keywords (SEARCH
# WHEN / EVALUATE TRUE Condition selectors, which carry only joined text --
# see ``_extract_identifiers``).
_NON_IDENTIFIER_WORDS = frozenset(
    {
        # Figurative constants / reserved literals
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
        "ALL",
        # Qualification / special-register / intrinsic-function keywords
        # that stay joined into an operand's raw text
        "OF",
        "IN",
        "FUNCTION",
        "LENGTH",
        "ADDRESS",
        # Condition-text keywords (raw, un-decomposed SEARCH/EVALUATE text)
        "AND",
        "OR",
        "NOT",
        "IS",
        "ARE",
        "NUMERIC",
        "ALPHABETIC",
        "ALPHABETIC-LOWER",
        "ALPHABETIC-UPPER",
        "POSITIVE",
        "NEGATIVE",
        "THRU",
        "THROUGH",
        "TRUE",
        "FALSE",
        "EQUAL",
        "GREATER",
        "LESS",
        "THAN",
        "TO",
    }
)

_QUOTED_TEXT_RE = QUOTED_LITERAL_RE

# Statement attributes holding a single identifier string that isn't
# already folded into `.operands` by the statement's own setters -- found
# by auditing each statement model's setters for missing
# `_add_unique_operand`/`add_operand` calls.
_STR_ATTR_EXTRAS: dict[type, tuple[str, ...]] = {
    UnstringStatement: ("source_operand", "pointer_variable", "tallying_variable"),
    StringStatement: ("into_target", "pointer_variable"),
    InspectStatement: (
        "converting_from",
        "converting_to",
        "converting_before",
        "converting_after",
    ),
    SearchStatement: ("table_name", "varying_variable"),
    # ``CONTINUE AFTER expr SECONDS`` reads every operand of its delay (#578).
    ContinueStatement: ("delay_expression",),
}

# Statement attributes holding a plain list of operand strings that never
# reach `.operands`. `DELIMITED BY <identifier>` is a real reference -- it
# is the *value* the runtime splits or joins on -- and both STRING and
# UNSTRING keep it here rather than in the operand bag, so a delimiter held
# in a variable used to be reported unused. (UNSTRING's per-target
# `delimiter_var` is a different clause, already covered by
# `_DICT_LIST_EXTRAS` below.) A literal delimiter is quoted text and
# `_extract_identifiers` drops it.
_STR_LIST_EXTRAS: dict[type, tuple[str, ...]] = {
    UnstringStatement: ("delimiters",),
    StringStatement: ("delimiters",),
}

# Statement attributes holding a list of dicts with identifier-bearing
# keys, none of which reach `.operands`.
_DICT_LIST_EXTRAS: dict[type, tuple[tuple[str, tuple[str, ...]], ...]] = {
    UnstringStatement: (("into_targets", ("target", "delimiter_var", "count_var")),),
    # ``INITIALIZE X REPLACING NUMERIC DATA BY WS-ZERO``: the BY value is
    # read. A literal arrives quoted, and its quoted text is never taken
    # for a name.
    InitializeStatement: (("replacing_clauses", ("by_value",)),),
    InspectStatement: (
        ("tallying_clauses", ("counter", "value", "before", "after")),
        ("replacing_clauses", ("from_value", "to_value", "before", "after")),
    ),
    SortStatement: (("keys", ("field",)),),
    MergeStatement: (("keys", ("field",)),),
}


@dataclass
class UnusedVariableItem:
    """A DATA DIVISION item identified as unused (never referenced)."""

    name: str
    level: int
    section: str
    location: SourceLocation
    from_copybook: bool = False
    #: ``"AMT OF OUT-REC"`` (every enclosing item, innermost first) when
    #: another declared item shares this one's name, else ``None``.
    qualified_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "level": self.level,
            "section": self.section,
            "location": self.location.to_dict(),
            "from_copybook": self.from_copybook,
        }
        if self.qualified_name:
            result["qualified_name"] = self.qualified_name
        return result


@dataclass
class UnusedVariableReport:
    """Result of an unused-variable analysis."""

    unused_items: list[UnusedVariableItem] = field(default_factory=list)
    total_variables: int = 0
    referenced_variables: int = 0
    skipped_copybook_count: int = 0

    @property
    def unused_count(self) -> int:
        return len(self.unused_items)

    @property
    def has_unused_variables(self) -> bool:
        return len(self.unused_items) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "unused_variables": [item.to_dict() for item in self.unused_items],
            "summary": {
                "total_variables": self.total_variables,
                "referenced_variables": self.referenced_variables,
                "unused_variables": self.unused_count,
                "skipped_copybook_variables": self.skipped_copybook_count,
            },
        }


def collect_declared_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Collect every non-FILLER, non-synthetic data item across the
    in-scope DATA DIVISION sections (FILE, WORKING-STORAGE, LOCAL-STORAGE,
    LINKAGE), including nested group children.

    Exposed as a standalone helper so callers (e.g. the CLI) can reuse the
    same declared-name walk to diff an unexpanded parse against an
    expanded one for copybook-provenance detection -- see
    ``UnusedVariableAnalyzer``'s docstring.

    Items named ``ANONYMOUS-<level>-<line>`` are excluded alongside FILLER:
    the DATA DIVISION parser (``data_clauses.py``) generates that name for
    any level-number entry with no real IDENTIFIER token, so it is never a
    name a program could reference -- same rationale as FILLER, and it
    also filters out the clause fragments SCREEN SECTION/REPORT SECTION
    entries get mis-parsed as (see module docstring's "known limitations").
    """
    data_div = ast.data_division
    if data_div is None:
        return []

    items: list[CobolDataItem] = []
    for section in data_div.sections:
        if not isinstance(section, CobolSection):
            continue
        if (section.section_name or "").upper() not in _DATA_SECTION_NAMES:
            continue
        for top_item in section.data_items:
            items.append(top_item)
            items.extend(top_item.get_all_children())

    return [
        item
        for item in items
        if not item.is_filler and not item.name.upper().startswith("ANONYMOUS-")
    ]


#: Statement attributes that hold a procedure (paragraph / section) name:
#: PERFORM's target and THRU, SORT / MERGE input / output procedures.
_PROCEDURE_NAME_ATTRS: tuple[str, ...] = (
    "target_paragraph",
    "thru_paragraph",
    "processing_procedure",
    "processing_procedure_thru",
    "input_procedure",
    "input_procedure_thru",
    "output_procedure",
    "output_procedure_thru",
)


def _procedure_operands(stmt: Any) -> set[str]:
    """Upper-cased procedure names *stmt* names (PERFORM / GO TO / ALTER /
    SORT-MERGE procedures): operands that are never data references."""
    names: set[str] = set()
    for attr in _PROCEDURE_NAME_ATTRS:
        value = getattr(stmt, attr, None)
        if isinstance(value, str) and value:
            names.add(value.strip().upper())
    for value in getattr(stmt, "target_paragraphs", None) or []:
        if isinstance(value, str) and value:
            names.add(value.strip().upper())
    for alteration in getattr(stmt, "alterations", None) or []:
        if isinstance(alteration, dict):
            for key in ("from_paragraph", "to_paragraph"):
                value = alteration.get(key)
                if isinstance(value, str) and value:
                    names.add(value.strip().upper())
    return names


def inherited_data_records(
    ast: CobolProgram,
) -> list[tuple[CobolProgram, str, CobolDataItem]]:
    """``(owner, section name, record)`` for every 01/77 record of a program
    enclosing *ast* that *ast*'s own statements can name (#504).

    A contained program sees each enclosing program's ``GLOBAL`` records
    (and everything under them); a METHOD sees *all* of its FACTORY /
    OBJECT paragraph's data, GLOBAL or not. Innermost container first. A
    name *ast* declares itself, or a nearer container already supplied,
    hides the farther one, as COBOL name resolution does. ``EXTERNAL``
    needs no case of its own: an EXTERNAL record is declared in each
    program that uses it. The records are *not* part of
    ``collect_declared_items`` -- *ast* does not declare them, so they are
    never *ast*'s unused items -- but every analyzer that resolves *ast*'s
    references to declarations (xref, lineage, move-type-check) must see
    them.
    """
    hidden = {item.name.upper() for item in collect_declared_items(ast)}
    result: list[tuple[CobolProgram, str, CobolDataItem]] = []
    owner = ast.parent
    while owner is not None:
        if isinstance(owner, CobolProgram) and owner.data_division is not None:
            shares_all = getattr(owner, "unit_kind", "PROGRAM") in _OO_DATA_OWNERS
            for section in owner.data_division.sections:
                if not isinstance(section, CobolSection):
                    continue
                section_name = section.section_name or ""
                if section_name.upper() not in _DATA_SECTION_NAMES:
                    continue
                for record in section.data_items:
                    if not isinstance(record, CobolDataItem) or record.is_filler:
                        continue
                    name = (record.name or "").upper()
                    if name in hidden:
                        continue
                    if shares_all or getattr(record, "is_global", False):
                        result.append((owner, section_name, record))
                        hidden.add(name)
        owner = owner.parent
    return result


def _extract_identifiers(operand: Any) -> set[str]:
    """Extract every candidate data-name reference out of an operand's raw
    text.

    Statement parsers frequently join a whole qualified reference,
    subscript, reference-modification, special register, or intrinsic
    function call into a *single* operand string instead of splitting out
    the underlying data-name(s) -- confirmed empirically:
    ``MoveStatement.source`` for ``MOVE WS-A OF WS-GRP TO ...`` is the
    literal string ``"WS-A OF WS-GRP"``; ``"FUNCTION UPPER-CASE(WS-X)"``
    and ``"LENGTH OF WS-X"`` shapes are the same. Treating an operand as
    one opaque token (the previous approach) meant ``WS-A``/``WS-GRP``/
    ``WS-X`` never matched a declared item's bare name and were falsely
    reported unused -- caught by Copilot review on the PR that introduced
    this analyzer.

    Quoted substrings are stripped first so literal text is never mistaken
    for an identifier (also handles the plain-literal-operand case, e.g.
    ``"'HELLO'"`` reduces to nothing); every remaining letter-led token is
    a candidate, filtered against ``_NON_IDENTIFIER_WORDS`` (figurative
    constants, qualification/special-register/intrinsic-function keywords,
    raw condition-text keywords). A bare numeric literal (``"12345"``)
    never matches at all, since a token must start with a letter.

    A qualified reference keeps its qualifiers (see
    ``_names.qualified_references``): ``"WS-A OF WS-GRP"`` yields
    ``"WS-A OF WS-GRP"`` and ``"WS-GRP"``, so two same-named fields in
    different records can be told apart (issue #258). ``_names.bare_names``
    recovers the plain token set.

    Deliberately over-inclusive: a token that isn't really a data-name
    (e.g. an intrinsic function name like ``UPPER-CASE``) only risks
    coincidentally matching an unrelated declared item and marking it
    used -- the analyzer's stated bias throughout is that a missed
    truly-unused variable is safe, a falsely-flagged used one is not.
    """
    if not isinstance(operand, str) or not operand:
        return set()

    stripped = _QUOTED_TEXT_RE.sub(" ", operand)
    return qualified_references(stripped, _NON_IDENTIFIER_WORDS)


def _mark_subtree_used(item: CobolDataItem, group_used: dict[int, bool]) -> None:
    """Mark *item* and everything beneath it used, structurally."""
    group_used[id(item)] = True
    for child in item.children:
        if isinstance(child, CobolDataItem):
            _mark_subtree_used(child, group_used)


def _descendant_names(item: CobolDataItem) -> set[str]:
    out: set[str] = set()
    for child in item.children:
        if isinstance(child, CobolDataItem):
            out.add(child.name.upper())
            out |= _descendant_names(child)
    return out


def _mark_matching_used(
    item: CobolDataItem, shared: set[str], group_used: dict[int, bool]
) -> None:
    for child in item.children:
        if not isinstance(child, CobolDataItem):
            continue
        if child.name.upper() in shared and not child.is_filler:
            _mark_subtree_used(child, group_used)
        else:
            _mark_matching_used(child, shared, group_used)


def _mark_corresponding_used(
    source: CobolDataItem, target: CobolDataItem, group_used: dict[int, bool]
) -> None:
    """Mark the same-named subordinates of a CORRESPONDING pair (and the two
    groups themselves) used; every other subordinate keeps its own standing."""
    group_used[id(source)] = True
    group_used[id(target)] = True
    shared = _descendant_names(source) & _descendant_names(target)
    shared.discard("FILLER")
    if not shared:
        return
    _mark_matching_used(source, shared, group_used)
    _mark_matching_used(target, shared, group_used)


def _names_from_value(value: object) -> set[str]:
    """Identifiers referenced by one operand-position value, dispatching on
    shape: a ``CobolExpression`` is walked structurally, anything else is
    treated as operand text. The one shared form of a dispatch previously
    hand-rolled at three sites (``FunctionCall`` arguments,
    ``ConditionalExpression``/``ArithmeticExpression`` operands, and the
    ``EvaluateStatement`` subjects walk).
    """
    if isinstance(value, CobolExpression):
        return _walk_expression_operands(value)
    return _extract_identifiers(value)


def _walk_expression_operands(expr: CobolExpression | None) -> set[str]:
    """Collect every leaf identifier referenced by a condition/arithmetic
    expression tree (IF conditions, PERFORM UNTIL guards, COMPUTE
    expressions). Falls back to best-effort raw-text extraction for a node
    shape that couldn't be structurally decomposed, mirroring
    ``program_flow/condition_text.py``'s ``render_condition_text`` fallback
    chain.
    """
    names: set[str] = set()
    if expr is None:
        return names

    if isinstance(expr, LogicalExpression):
        names |= _walk_expression_operands(expr.left_condition)
        names |= _walk_expression_operands(expr.right_condition)
        return names

    if isinstance(expr, FunctionCall):
        for arg in expr.arguments:
            names |= _names_from_value(arg)
        return names

    if isinstance(expr, (ConditionalExpression, ArithmeticExpression)):
        if expr.left_operand is None and expr.right_operand is None:
            # A condition the builder could not decompose (``X EXCEEDS Y``,
            # a class test without IS) keeps only its raw text. Now that a
            # PERFORM UNTIL guard is walked through its tree (#539), this
            # is the only place its names can come from.
            raw = expr.get_metadata("raw_condition")
            if raw:
                return _extract_identifiers(str(raw))
        for operand in (expr.left_operand, expr.right_operand):
            names |= _names_from_value(operand)
        return names

    tree = getattr(expr, "condition_tree", None)
    if isinstance(tree, CobolExpression):
        # A PERFORM UNTIL guard: the raw joined text sits in `operands`, the
        # structural tree next to it. Walk the tree -- the text would also
        # yield a SPECIAL-NAMES class-name (``UNTIL X IS NOT VALID-CODE``)
        # as if it were a data item (#539).
        return _walk_expression_operands(tree)

    # Unrecognized/opaque expression shape: fall back to the raw text this
    # codebase always keeps around for exactly this situation. Scan every
    # operand, not just the first -- a programmatically built expression may
    # carry several, and dropping operands[1:] falsely reported those names
    # unused.
    if expr.operands:
        for operand in expr.operands:
            names |= _extract_identifiers(str(operand))
        return names
    raw = expr.get_metadata("raw_condition")
    if raw:
        names |= _extract_identifiers(str(raw))
    return names


def _ancestor_names(item: Any) -> list[str]:
    """Upper-cased names of *item*'s enclosing data items, innermost first."""
    names: list[str] = []
    node = getattr(item, "parent", None)
    while isinstance(node, CobolDataItem):
        names.append(node.name.upper())
        node = getattr(node, "parent", None)
    return names


def qualified_data_name(item: Any, by_name: dict[str, list[Any]]) -> str | None:
    """``"AMT OF OUT-REC"`` for an item whose name another declared item
    shares, else ``None``."""
    name = item.name.upper()
    if len(by_name.get(name, [])) <= 1:
        return None
    return QUALIFIER_SEPARATOR.join([name, *_ancestor_names(item)])


def _qualifiers_match(item: Any, qualifiers: list[str]) -> bool:
    """Whether *qualifiers* (as written, innermost first) name enclosing
    items of *item* in ascending order -- the COBOL rule: each qualifier
    must be a containing item, but intermediate levels may be skipped."""
    ancestors = iter(_ancestor_names(item))
    return all(q in ancestors for q in qualifiers)


def _redefines_targets(item: CobolDataItem, by_name: dict[str, list[Any]]) -> list[Any]:
    """The item(s) *item* REDEFINES: its same-named sibling when it has one,
    else every item of that name."""
    name = (item.redefines or "").upper()
    candidates = [c for c in by_name.get(name, []) if isinstance(c, CobolDataItem)]
    parent = getattr(item, "parent", None)
    siblings = [c for c in candidates if getattr(c, "parent", None) is parent]
    return siblings or candidates


class _NameMatcher:
    """Resolves references (as ``_extract_identifiers`` spells them, with
    ``" OF "`` qualifiers) to the declared items they can mean.

    The standard COBOL rule (issue #258): a qualified reference means the
    item of that name whose enclosing items match the qualifiers; an
    unqualified one means the item of that name, which the compiler requires
    to be unique. Where that cannot pick one item -- an unqualified
    reference to a shared name, or qualifiers that match no candidate (a
    file-name qualifier, say) -- every candidate counts, so a reference can
    only ever keep an item alive, never hide one.
    """

    def __init__(self, refs: set[str], by_name: dict[str, list[Any]]) -> None:
        self._by_name = by_name
        self._bare: set[str] = set()
        self._qualified: dict[str, list[list[str]]] = {}
        for ref in refs:
            name, *qualifiers = ref.split(QUALIFIER_SEPARATOR)
            if qualifiers:
                self._qualified.setdefault(name, []).append(qualifiers)
            else:
                self._bare.add(name)

    def names(self, item: Any) -> bool:
        """Whether any reference resolves to *item*."""
        name = item.name.upper()
        if name in self._bare:
            return True
        chains = self._qualified.get(name)
        if not chains:
            return False
        candidates = self._by_name.get(name, [])
        if len(candidates) <= 1:
            return True
        return any(
            _qualifiers_match(item, qualifiers)
            or not any(_qualifiers_match(c, qualifiers) for c in candidates)
            for qualifiers in chains
        )

    def resolve(self, ref: str) -> list[Any]:
        """The declared items one reference means."""
        name, *qualifiers = ref.split(QUALIFIER_SEPARATOR)
        candidates = self._by_name.get(name, [])
        if not qualifiers or len(candidates) <= 1:
            return list(candidates)
        matched = [c for c in candidates if _qualifiers_match(c, qualifiers)]
        return matched or list(candidates)


def _all_contained_units(ast: CobolProgram) -> list[CobolProgram]:
    """Every program unit contained in *ast*, at any depth."""
    units: list[CobolProgram] = []
    for contained in ast.contained_programs:
        units.append(contained)
        units += _all_contained_units(contained)
    return units


class UnusedVariableAnalyzer:
    """Analyzer for detecting unused (never-referenced) DATA DIVISION items.

    A data item is considered "used" if any of the following holds:

    - Its own name is referenced anywhere in the PROCEDURE DIVISION (as a
      MOVE/DISPLAY/arithmetic/CALL/SET/... operand, an IF/EVALUATE/SEARCH/
      PERFORM UNTIL condition operand, or similar).
    - It is a group item and any of its descendant fields is used.
    - It has a level-88 condition-name child that is itself referenced
      (e.g. ``IF ORDER-VALID`` where ``ORDER-VALID`` is a condition name
      on this item).
    - It is named by another item's REDEFINES, OCCURS ... DEPENDING ON, or
      a level-66 RENAMES, *and* that referencing item is itself used (for
      REDEFINES) or the reference is unconditional (OCCURS DEPENDING ON,
      RENAMES) -- these are real structural dependencies even when the
      name never appears in a procedural statement.

    FILLER items and level-88/level-66 items themselves are never reported
    (see module docstring and ``collect_declared_items``).

    Known limitations (documented rather than silently guessed, matching
    this package's convention -- see ``.okf/analysis.md``):

    - EXEC CICS and EXEC DLI statement arguments are not scanned for
      identifiers (no fixed argument-role shape to key off, same gap
      ``BoundaryInventoryAnalyzer`` documents for these two statement
      types). A field referenced *only* inside one of these may be
      falsely reported unused.
    - SEARCH WHEN and EVALUATE TRUE Condition-type selectors carry only
      raw joined text (never a structural tree -- confirmed against
      ``search_parser.py``/``evaluate_parser.py``); identifier extraction
      there is a best-effort regex, not exact.
    - Same-named items in different records (the input/output record
      pair ``MOVE CORRESPONDING`` relies on) are told apart by the
      qualifiers of each reference (``AMT OF OUT-REC``) and by REDEFINES
      siblinghood. An unqualified reference to a shared name, and the
      OCCURS DEPENDING ON / RENAMES name lookups, still count for every
      item of that name.
    - SCREEN SECTION, REPORT SECTION, and COMMUNICATION SECTION headers
      are now recognized by the DATA DIVISION parser and their content
      discarded into distinctly-named, always-empty ``SCREEN``/``REPORT``/
      ``COMMUNICATION`` sections (a separate parser fix, landed after this
      analyzer was first written -- see ``parsers/divisions/data.py``'s
      ``_skip_section``). ``collect_declared_items`` only recognizes
      FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE, so these three sections
      contribute nothing to the declared-item set either way -- no
      analyzer-side change was needed once the parser stopped corrupting
      WORKING-STORAGE with their clause keywords. Their content (screen
      fields, report groups, CD entries) is simply invisible to this
      analyzer, same as any other construct outside its documented scope.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer

        result = parse_cobol(source)
        report = UnusedVariableAnalyzer().analyze(result.ast)
        for item in report.unused_items:
            print(f"Unused: {item.name} at line {item.location.line}")
        ```
    """

    def analyze(
        self,
        ast: CobolProgram,
        *,
        include_copybook_variables: bool = True,
        copybook_item_names: set[str] | None = None,
    ) -> UnusedVariableReport:
        """Analyze *ast* for unused DATA DIVISION items.

        Args:
            ast: The parsed COBOL program AST.
            include_copybook_variables: When False, unused items whose
                name is in *copybook_item_names* are excluded from
                ``report.unused_items`` (counted instead in
                ``report.skipped_copybook_count``). Has no effect when
                *copybook_item_names* is None -- this analyzer has no way
                to know a data item's originating file on its own.
            copybook_item_names: Uppercased names of data items that came
                from an expanded COPY, as determined by the caller (e.g.
                by diffing ``collect_declared_items()`` on an unexpanded
                parse against the expanded one -- see the ``unused-variables``
                CLI subcommand for a worked example). None (default) means
                "no copybook-provenance information available".

        Returns:
            An UnusedVariableReport.
        """
        declared_items = collect_declared_items(ast)
        if not declared_items:
            return UnusedVariableReport()

        referenced = self._collect_referenced_names(ast)
        referenced |= self._collect_data_division_references(ast)
        # A contained program sees only the container's GLOBAL items, so its
        # references count for those alone (``get_all_statements()`` walks
        # into contained programs, and crediting every one of their
        # references here hid the container's genuinely unused items).
        # The exception is IBM OO COBOL: data declared in a FACTORY or OBJECT
        # paragraph is visible to every METHOD of that paragraph without a
        # GLOBAL clause, so there the methods' references count for all of it.
        nested_referenced = self._nested_referenced_names(ast)
        shares_all_data = getattr(ast, "unit_kind", "PROGRAM") in _OO_DATA_OWNERS
        global_ids: set[int] = set()
        for item in declared_items:
            if shares_all_data or getattr(item, "is_global", False):
                global_ids.add(id(item))
                global_ids.update(id(child) for child in item.get_all_children())

        by_name: dict[str, list[Any]] = {}
        for item in declared_items:
            by_name.setdefault(item.name.upper(), []).append(item)
            for child in item.children:
                if isinstance(child, ConditionNameItem):
                    by_name.setdefault(child.name.upper(), []).append(child)

        own_refs = _NameMatcher(referenced, by_name)
        global_refs = _NameMatcher(referenced | nested_referenced, by_name)

        group_used: dict[int, bool] = {}

        def is_used(item: CobolDataItem) -> bool:
            key = id(item)
            if key in group_used:
                return group_used[key]
            group_used[key] = False  # cycle guard
            refs = global_refs if key in global_ids else own_refs
            result = refs.names(item)
            if not result:
                for child in item.children:
                    if isinstance(child, ConditionNameItem) and refs.names(child):
                        result = True
                        break
            if not result:
                for child in item.children:
                    if isinstance(child, CobolDataItem) and is_used(child):
                        result = True
                        break
            group_used[key] = result
            return result

        for item in declared_items:
            is_used(item)

        # A group passed whole to another program is consumed field by field
        # by code this analyzer cannot see, so every item beneath it is used.
        # Propagation elsewhere runs child -> parent only, which is right for
        # `MOVE 'X' TO WS-CHILD` (the group is touched because a field was)
        # but leaves `CALL 'SUB' USING WS-GRP` reporting every field of
        # WS-GRP unused. Deliberately limited to CALL arguments rather than
        # any group reference: `MOVE SPACES TO WS-GRP` really does leave its
        # fields never individually referenced, which is a finding worth
        # keeping.
        # An OO FACTORY/OBJECT unit has no statements of its own: its METHODs
        # do the CALL USING / CORRESPONDING work on its data, so read theirs.
        statement_units = [ast]
        if shares_all_data:
            statement_units += _all_contained_units(ast)
        for ref in {
            ref
            for unit in statement_units
            for ref in self._whole_group_references(unit)
        }:
            for item in own_refs.resolve(ref):
                if isinstance(item, CobolDataItem):
                    _mark_subtree_used(item, group_used)

        # ``MOVE CORRESPONDING A TO B``: the operands are the subordinates
        # of A and B that share a name (IBM: "items in identifier-1 and
        # identifier-2 with the same data-name"), so those -- and only
        # those -- are referenced by the statement. A field with no
        # same-named twin stays assessed.
        for source_ref, target_ref in (
            pair for unit in statement_units for pair in self._corresponding_pairs(unit)
        ):
            sources = [
                i for i in own_refs.resolve(source_ref) if isinstance(i, CobolDataItem)
            ]
            targets = [
                i for i in own_refs.resolve(target_ref) if isinstance(i, CobolDataItem)
            ]
            for source in sources:
                for target in targets:
                    _mark_corresponding_used(source, target, group_used)

        # The CICS translator's own LINKAGE items. DFHEIBLK is the EXEC
        # interface block: the translator declares every EIB field and the
        # runtime fills them, so an untouched EIBRESP2 is not an unused
        # variable in any sense a reviewer cares about -- and the 30-odd
        # fields would bury the real findings of every CICS program.
        # DFHCOMMAREA itself is passed by the translator-generated USING;
        # its *fields* are the program's own and stay assessed.
        for item in by_name.get("DFHEIBLK", []):
            _mark_subtree_used(item, group_used)
        for item in by_name.get("DFHCOMMAREA", []):
            group_used[id(item)] = True

        # REDEFINES: when the redefining item is used, its target shares
        # the same physical storage and counts as used too. Iterated to a
        # fixpoint for REDEFINES chains (A REDEFINES B REDEFINES C). The
        # target is a sibling of the redefining item (COBOL requires it to
        # be the preceding entry at the same level), which tells two
        # same-named targets in different records apart; a name with no
        # such sibling falls back to every item of that name.
        redefines_edges = [
            (item, _redefines_targets(item, by_name))
            for item in declared_items
            if item.redefines
        ]
        changed = True
        while changed:
            changed = False
            for redefining_item, targets in redefines_edges:
                if not group_used.get(id(redefining_item)):
                    continue
                for target in targets:
                    if not group_used.get(id(target)):
                        group_used[id(target)] = True
                        changed = True

        report = UnusedVariableReport()
        report.total_variables = len(declared_items)
        report.referenced_variables = sum(
            1 for item in declared_items if group_used.get(id(item))
        )

        for item in declared_items:
            if group_used.get(id(item)):
                continue
            from_copybook = bool(
                copybook_item_names and item.name.upper() in copybook_item_names
            )
            if from_copybook and not include_copybook_variables:
                report.skipped_copybook_count += 1
                continue
            report.unused_items.append(
                UnusedVariableItem(
                    name=item.name,
                    level=item.level,
                    section=self._section_of(item),
                    location=item.location,
                    from_copybook=from_copybook,
                    qualified_name=qualified_data_name(item, by_name),
                )
            )

        return report

    # ------------------------------------------------------------------
    # PROCEDURE DIVISION reference collection
    # ------------------------------------------------------------------

    @staticmethod
    def _own_statements(ast: CobolProgram) -> list[CobolStatement]:
        """*ast*'s statements, without those of the programs it contains.

        ``get_all_statements()`` walks children, and a contained program is
        a child, so its statements would otherwise read as *ast*'s own.
        """
        statements = ast.get_all_statements()
        if not ast.contained_programs:
            return statements
        inner = {
            id(node)
            for contained in ast.contained_programs
            for node in contained.traverse_depth_first()
        }
        return [stmt for stmt in statements if id(stmt) not in inner]

    def _nested_referenced_names(self, ast: CobolProgram) -> set[str]:
        """Every name referenced by a program contained in *ast*, at any
        depth -- the references that may reach *ast*'s GLOBAL items."""
        names: set[str] = set()
        for contained in ast.contained_programs:
            names |= self._collect_referenced_names(contained)
            names |= self._call_argument_names(contained)
            names |= self._nested_referenced_names(contained)
        return names

    @staticmethod
    def _call_argument_names(ast: CobolProgram) -> set[str]:
        """Every data name handed to a ``CALL ... USING``, upper-cased.

        Every passing mode counts: BY REFERENCE hands over the storage, and
        BY CONTENT / BY VALUE both read it to make the copy.
        """
        names: set[str] = set()
        for stmt in UnusedVariableAnalyzer._own_statements(ast):
            if not isinstance(stmt, CallStatement):
                continue
            for parameter in stmt.using_parameters:
                if not parameter.name:
                    continue
                # The argument itself, qualifiers kept, not its subscripts.
                head = parameter.name.split()[0].split("(")[0].upper()
                names |= {
                    ref
                    for ref in _extract_identifiers(parameter.name)
                    if ref.split(QUALIFIER_SEPARATOR, 1)[0] == head
                }
        return names

    @staticmethod
    def _whole_group_references(ast: CobolProgram) -> set[str]:
        """Group references whose subordinates are consumed *by name* by the
        statement itself, so every item beneath counts as used (2026-10-08):

        * ``CALL ... USING`` arguments (:meth:`_call_argument_names`);
        * ``MOVE / ADD / SUBTRACT CORRESPONDING A TO B``: the same-named
          subordinates of both groups are the operands (IBM: "items in
          identifier-1 and identifier-2 with the same data-name");
        * ``XML GENERATE doc FROM group`` / ``JSON GENERATE doc FROM group``
          emit one element per subordinate, by name; ``XML PARSE`` /
          ``JSON PARSE doc INTO group`` store into each subordinate by name;
        * EXEC SQL host variables and null indicators (#531): DB2 reads or
          writes a host structure one column per elementary field, and a
          VARCHAR group through both 49-level parts -- removing one breaks
          the precompile or shifts the column mapping. Includes the EXEC
          SQL of the program's own DATA DIVISION (a DECLARE CURSOR in
          WORKING-STORAGE), which no PROCEDURE DIVISION walk reaches.

        ``MOVE SPACES TO group`` deliberately stays a plain group reference:
        its fields really are never individually referenced.
        """
        names = UnusedVariableAnalyzer._call_argument_names(ast)
        for stmt in UnusedVariableAnalyzer._own_statements(ast):
            if isinstance(stmt, XmlJsonStatement):
                for operand in (stmt.from_item, stmt.into_item):
                    names |= _extract_identifiers(operand)
        names |= UnusedVariableAnalyzer._sql_host_variable_names(ast)
        return names

    @staticmethod
    def _sql_host_variable_names(ast: CobolProgram) -> set[str]:
        """Every EXEC SQL host variable and null indicator of *ast*'s own
        PROCEDURE and DATA DIVISION statements."""
        statements: list[Any] = list(UnusedVariableAnalyzer._own_statements(ast))
        data_div = ast.get_division("DATA")
        if data_div is not None:
            statements += [
                node
                for node in data_div.traverse_depth_first()
                if hasattr(node, "host_variables")
            ]
        names: set[str] = set()
        for stmt in statements:
            for attr in ("host_variables", "null_indicators"):
                for value in getattr(stmt, attr, None) or []:
                    names |= _extract_identifiers(value)
        return names

    @staticmethod
    def _corresponding_pairs(ast: CobolProgram) -> list[tuple[str, str]]:
        """The ``(source, target)`` group references of every ``MOVE / ADD /
        SUBTRACT CORRESPONDING`` statement, as raw operand text."""
        pairs: list[tuple[str, str]] = []
        for stmt in UnusedVariableAnalyzer._own_statements(ast):
            if not getattr(stmt, "is_corresponding", False):
                continue
            operands = [op for op in stmt.operands if isinstance(op, str) and op]
            if len(operands) >= 2:
                pairs.append((operands[0], operands[-1]))
        return pairs

    def _collect_referenced_names(self, ast: CobolProgram) -> set[str]:
        """Collect every identifier referenced anywhere in the PROCEDURE
        DIVISION: each statement's own ``.operands`` bag plus the
        statement-type-specific fields that don't reach ``.operands`` (see
        module-level ``_STR_ATTR_EXTRAS``/``_DICT_LIST_EXTRAS`` and the
        condition/expression-tree handling below).
        """
        names: set[str] = set()

        for stmt in self._own_statements(ast):
            procedures = _procedure_operands(stmt)
            for operand in stmt.operands:
                if isinstance(operand, str) and operand.strip().upper() in procedures:
                    # ``PERFORM INIT`` names paragraph INIT, never a data
                    # item of that name (#487).
                    continue
                names |= _extract_identifiers(operand)

            # Walked by MRO, not exact type, so a (currently hypothetical)
            # subclass of a keyed statement type still gets its extras
            # collected instead of silently losing coverage.
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

            # ``WRITE REC AFTER ADVANCING WS-N LINES``: the line count is
            # read on every WRITE and lives in ``advancing_clause`` only
            # (a str for an identifier, an int for a literal count).
            advancing = getattr(stmt, "advancing_clause", None)
            if isinstance(advancing, dict):
                value = advancing.get("value")
                if isinstance(value, str):
                    names |= _extract_identifiers(value)

            if isinstance(stmt, IfStatement):
                names |= _walk_expression_operands(stmt.condition)
            elif isinstance(stmt, PerformStatement):
                names |= _walk_expression_operands(stmt.until_condition)
                # ``PERFORM P WS-N TIMES``: the count is an identifier held
                # in ``times_count`` only (an int for a literal count).
                if isinstance(stmt.times_count, str):
                    names |= _extract_identifiers(stmt.times_count)
                if stmt.varying_clause:
                    for key in ("variable", "from_value", "by_value"):
                        names |= _extract_identifiers(stmt.varying_clause.get(key))
                for after in stmt.after_clauses:
                    names |= _walk_expression_operands(after.get("until_condition"))
                    for key in ("variable", "from_value", "by_value"):
                        names |= _extract_identifiers(after.get(key))
            elif isinstance(stmt, EvaluateStatement):
                # EVALUATE subject-1 [ALSO subject-2]...: string subjects
                # now reach `.operands` too (evaluate_parser routes them
                # through `add_subject()`), so the base-case operand scan
                # already covers them -- the double-count here is a
                # harmless set union. This walk must stay regardless: a
                # `CobolExpression` subject goes to `add_child()`, never
                # `add_operand()` (see EvaluateStatement.add_subject), so
                # this is the ONLY coverage for expression-shaped subjects.
                for subject in stmt.subjects:
                    names |= _names_from_value(subject)
                clauses = list(stmt.when_clauses)
                if stmt.default_when is not None:
                    clauses.append(stmt.default_when)
                for clause in clauses:
                    for selector in clause.selectors:
                        names |= self._selector_identifiers(selector)
            elif isinstance(stmt, SearchStatement):
                # TODO(known limitation): SEARCH WHEN condition text is raw
                # joined text, not a structural tree -- best-effort regex
                # extraction only, not exact (same gap as EVALUATE TRUE
                # Condition-type selectors in `_selector_identifiers` below).
                for search_clause in stmt.when_clauses:
                    condition_text = search_clause.get("condition")
                    if condition_text:
                        names |= _extract_identifiers(str(condition_text))

            expression_tree = getattr(stmt, "expression_tree", None)
            if expression_tree is not None:
                names |= _walk_expression_operands(expression_tree)

            host_variables = getattr(stmt, "host_variables", None)
            if host_variables:
                for v in host_variables:
                    names |= _extract_identifiers(v)
            null_indicators = getattr(stmt, "null_indicators", None)
            if null_indicators:
                for v in null_indicators:
                    names |= _extract_identifiers(v)

        # EXEC CICS (`ExecCicsStatement.options`: option keyword ->
        # parenthesized argument text, e.g. INTO(WS-BUFFER)) and EXEC
        # IMS/DLI (`ExecImsStatement.arguments`: a positional list, e.g.
        # ["PCB(1)", "SEGMENT(EMPLOYEE)"]) carry their operands as raw
        # joined text rather than a structural tree, the same shape as EXEC
        # SQL's host_variables above, so the operand loop cannot decompose
        # them and they are swept here by duck typing (importing the classes
        # would add an analysis -> parsers layering dependency for no real
        # type-safety benefit, since these fields are untyped raw text
        # either way). Previously a field referenced only inside one of
        # these was falsely reported unused.
        #
        # This sweep once existed because neither class extended
        # CobolStatement, so neither reached ``get_all_statements()`` at all.
        # Both do now (see ibm_exec_statements.py, whose docstring records
        # why that changed), so the loop above already visits them and this
        # pass is a harmless set union rather than the only coverage. Do not
        # read it as evidence that these nodes are still invisible to
        # ``get_all_statements()`` -- a new analyzer does not need to
        # reproduce this workaround.
        # One shared traversal for both node types (find_all_by_type would
        # walk the whole AST once per type -- two extra full walks on every
        # analysis run, for nodes most programs don't contain at all).
        inner = {
            id(node)
            for contained in ast.contained_programs
            for node in contained.traverse_depth_first()
        }
        for node in ast.traverse_depth_first():
            if id(node) in inner:
                continue
            type_name = type(node).__name__
            if type_name == "ExecCicsStatement":
                for v in cics_identifier_options(node).values():
                    names |= _extract_identifiers(v)
            elif type_name == "ExecImsStatement":
                for v in getattr(node, "arguments", None) or []:
                    names |= _extract_identifiers(v)

        return names

    @staticmethod
    def _selector_identifiers(selector: dict[str, Any]) -> set[str]:
        """Extract identifiers from a single EVALUATE WHEN selector dict
        (see ``WhenClause`` docstring for the selector shape vocabulary).

        ``Literal`` selectors are scanned too: ``_build_selector`` in
        evaluate_parser.py classifies a bare data-name (or level-88
        condition-name) selector as ``{"type": "Literal"}`` -- it never
        emits ``"Identifier"``, a fact constraints.py's EVALUATE handling
        also relies on -- so skipping ``Literal`` values falsely reported
        a variable referenced only as a WHEN selector unused. The
        ``Identifier`` arm is kept defensively for programmatically built
        selector dicts.

        TODO(known limitation): unlike subject/IF text (re-quoted via
        ``condition_token_text``), selector values arrive with string-
        literal quotes already stripped by the lexer (the unquoted shape
        is pinned by tests/regression/test_evaluate_space_literal_when.py
        and consumed by constraints.py), so ``_extract_identifiers``'
        quote-stripping cannot distinguish literal contents from
        identifiers here. Literal contents that coincidentally match a
        declared name mark it used -- the module's accepted over-inclusive
        direction -- and a truly-unused variable sharing its name with a
        WHEN literal's contents goes unreported.
        """
        names: set[str] = set()
        selector_type = selector.get("type")
        if selector_type in ("Identifier", "Literal"):
            names |= _extract_identifiers(selector.get("value"))
        elif selector_type == "Range":
            for key in ("start", "end"):
                names |= _extract_identifiers(selector.get(key))
        elif selector_type == "Condition":
            # TODO(known limitation): EVALUATE TRUE Condition-type
            # selectors carry only raw joined text, never a structural
            # tree (confirmed against evaluate_parser.py) -- best-effort
            # regex extraction only, not exact (same gap as SEARCH WHEN
            # condition text above), and quote-stripped like every other
            # selector value (see the docstring's TODO).
            text = selector.get("text")
            if text:
                names |= _extract_identifiers(str(text))
        return names

    # ------------------------------------------------------------------
    # DATA DIVISION-internal reference collection
    # ------------------------------------------------------------------

    def _collect_data_division_references(self, ast: CobolProgram) -> set[str]:
        """Collect references that live outside the PROCEDURE DIVISION:
        OCCURS ... DEPENDING ON variables, level-66 RENAMES targets, the
        REPORT SECTION clauses that name a data item, the data items an FD
        names (``RECORD VARYING ... DEPENDING ON``, ``LINAGE``), and the ones
        a ``SELECT`` names (``FILE STATUS``, ``RECORD KEY``, ``ALTERNATE
        RECORD KEY``, ``RELATIVE KEY``, ``PASSWORD``).  REDEFINES is handled
        separately in ``analyze()`` since it needs item-level (not just
        name-level) propagation.
        """
        names: set[str] = set()
        names |= self._file_control_references(ast)

        data_div = ast.data_division
        if data_div is None:
            return names

        names |= self._report_section_references(data_div)

        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            if (section.section_name or "").upper() not in _DATA_SECTION_NAMES:
                continue

            for item in section.data_items:
                names |= self._fd_clause_references(item)
                for descendant in [item, *item.get_all_children()]:
                    occurs = descendant.occurs_clause
                    if occurs and occurs.depending_on:
                        names |= _extract_identifiers(occurs.depending_on)

            for child in section.children:
                if getattr(child, "node_type", None) == "RenamesItem":
                    names |= _extract_identifiers(getattr(child, "renames_from", None))
                    names |= _extract_identifiers(
                        getattr(child, "renames_through", None)
                    )

        return names

    @staticmethod
    def _file_control_references(ast: CobolProgram) -> set[str]:
        """Data names the FILE-CONTROL paragraph's SELECT clauses read or
        write at run time.

        The runtime stores into a ``FILE STATUS`` item after every I/O
        operation and reads the ``RECORD KEY`` / ``ALTERNATE RECORD KEY`` /
        ``RELATIVE KEY`` / ``PASSWORD`` items to position the file (and the
        ``ASSIGN USING`` item to name it), whether
        or not the PROCEDURE DIVISION ever names them -- a program that
        only tests its status through a level-88 on the same item, or never
        tests it at all, still uses it. Scanning only the PROCEDURE
        DIVISION reported every one of them unused.
        """
        names: set[str] = set()
        env_div = ast.get_division("ENVIRONMENT")
        if env_div is None:
            return names
        for node in env_div.find_all_by_type("Statement"):
            if not isinstance(node, SelectStatement):
                continue
            for value in (
                node.file_status,
                node.file_status_vsam,
                node.record_key,
                node.record_key_source,
                node.relative_key,
                node.password,
                node.assign_using,
            ):
                names |= _extract_identifiers(value)
            for alt in node.alternate_keys:
                names |= _extract_identifiers(alt.get("key"))
                names |= _extract_identifiers(alt.get("password"))
        return names

    @staticmethod
    def _fd_clause_references(item: Any) -> set[str]:
        """Data names an FD/SD's own clauses depend on, from the
        ``fd_clauses`` metadata the DATA DIVISION parser leaves on the
        01-level record: ``RECORD VARYING ... DEPENDING ON`` (the runtime
        reads/sets the length item on every WRITE/READ) and ``LINAGE``
        (its LINES / FOOTING / TOP / BOTTOM operands may be data names)."""
        names: set[str] = set()
        get_metadata = getattr(item, "get_metadata", None)
        clauses = get_metadata("fd_clauses") if get_metadata else None
        if not isinstance(clauses, dict):
            return names
        record = clauses.get("record")
        if isinstance(record, dict):
            names |= _extract_identifiers(record.get("depending_on"))
        linage = clauses.get("linage")
        if linage:
            names |= _extract_identifiers(str(linage))
        return names

    @staticmethod
    def _report_section_references(data_div: Any) -> set[str]:
        """Data names a REPORT SECTION reads, from its report-group clauses.

        A Report Writer program never mentions these fields in its PROCEDURE
        DIVISION at all -- ``INITIATE``/``GENERATE``/``TERMINATE`` drive the
        report, and the report groups themselves say which data items to
        print, total and break on.  Scanning only the PROCEDURE DIVISION
        therefore reported every one of them unused, which is every field of
        every Report Writer program.

        The clauses that name a data item, per ``data_report_description.py``
        and ``data_clauses.py``, which park them on the item's metadata:
        ``SOURCE`` (print this field), ``SUM`` (total these fields), and the
        RD's own ``CONTROL``/``CONTROLS`` (break on this field).
        """
        names: set[str] = set()
        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            if (section.section_name or "").upper() != "REPORT":
                continue
            for item in section.data_items:
                for node in [item, *item.get_all_children()]:
                    metadata = getattr(node, "metadata", None) or {}
                    clauses = metadata.get("report_clauses") or {}
                    names |= _extract_identifiers(clauses.get("source"))
                    for entry in clauses.get("sum") or []:
                        for operand in (entry or {}).get("operands") or []:
                            names |= _extract_identifiers(operand)
                    rd_clauses = metadata.get("rd_clauses") or {}
                    for control in rd_clauses.get("controls") or []:
                        names |= _extract_identifiers(control)
        return names

    @staticmethod
    def _section_of(item: CobolDataItem) -> str:
        """Walk up an item's parents to find its owning DATA DIVISION
        section name.
        """
        node = item.parent
        while node is not None:
            if isinstance(node, CobolSection):
                return node.section_name or "UNKNOWN"
            node = node.parent
        return "UNKNOWN"
