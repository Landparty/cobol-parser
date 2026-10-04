"""ConstantFolder: forward constant folding over a straight-line statement
chain, seeded by a scenario's own mock-supplied IN values.

Phase 7 tier 2 of the `gen-fixtures` program-scoped test-data initiative (see
`docs/plans/2026-08-02-program-data-generation-design.md`). A single forward
walk of the entry paragraph's statement chain -- following non-looping
PERFORMs inline, exactly like a subroutine call executed once -- tracking
which data items hold a knowable literal value after a MOVE or a simple
arithmetic/COMPUTE statement. Any field the walked chain DISPLAYs or WRITEs
that is *still* knowable at the end of the walk becomes a
``kind="field_equals"`` :class:`~cobolparser.generators.data.bundle.Expectation`
(built by ``program_fixtures.py``, not this module -- this module only
answers "what is knowable").

**No generated value may be wrong: exact by construction, or absent.** Every
choice below resolves ambiguity by leaving a field unknown (poisoned) rather
than guessing:

* A ``PERFORM ... UNTIL``/``VARYING``/``TIMES`` loop may run zero or many
  times, so nothing inside it is knowable at fold time -- every field its
  body could write is poisoned, and the walk continues *after* the loop (it
  still executes; the walk just cannot see inside it).
* An ``IF``/``EVALUATE`` branches on data this walk does not evaluate, so
  every field either arm could write is poisoned the same way -- this is a
  conjunctive walk, not per-scenario branch evaluation (Phase 5's
  `ScenarioPlanner` already owns targeting a specific arm).
* A conditional handler body (``AT END``/``INVALID KEY``/``ON SIZE ERROR``/
  ``ON OVERFLOW``/``ON EXCEPTION``/``AT EOP`` and their ``NOT`` variants) may
  or may not fire, so every field it could write is poisoned the same way an
  ``IF`` arm is.
* ``DIVIDE`` folds only the forms whose semantics are unambiguous now that
  ``DivideStatement.division_mode`` records BY vs INTO (the two invert
  dividend/divisor order): mode-less nodes, ROUNDED, the nonstandard
  ``DIVIDE a BY b`` without GIVING, non-exact quotients, and every
  REMAINDER target are all still poisoned -- see ``_fold_divide``. A ``/``
  inside a COMPUTE expression tree goes through the same ``_exact_divide``
  gate, so both spellings of a division hold the same contract.
* ROUNDED, CORRESPONDING, and any target this module cannot resolve to an
  elementary numeric/text field are all poisoned rather than approximated.
* A numeric MOVE/arithmetic result is only ever recorded when it fits its
  target field's PICTURE *exactly* -- no rounding, no truncation, no sign
  coercion. Real COBOL truncation rules for an overflowing MOVE are
  well-defined, but replicating them exactly is out of scope for v1; an
  overflowing result is poisoned instead of guessed.
* Only a bare ``DISPLAY``/``WRITE`` operand that resolves directly to an
  elementary field is an observation point -- a whole-record WRITE's
  individual member fields are not (yet) walked, so some real
  ``field_equals`` opportunities are silently not offered. Never wrong,
  sometimes just quieter than it could be.
"""

from __future__ import annotations

import re
import weakref
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from .._literals import unquote_literal
from ..models.data_items import CobolDataItem, RenamesItem
from ..models.program import CobolParagraph, CobolProgram
from ..models.statements.arithmetic import (
    AddStatement,
    ArithmeticStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ..models.statements.base import ArithmeticExpression, CobolExpression, FunctionCall
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    StopStatement,
)
from ..models.statements.data import DisplayStatement, MoveStatement
from ..models.statements.io import IOAcceptStatement, IOReadStatement, IOWriteStatement
from ..models.statements.misc import ExitStatement, GobackStatement

if TYPE_CHECKING:
    # Same shape as constraints.py's own guard: cobolparser.generators
    # (reached via generators/__init__.py's import chain) constructs
    # ConstantFolder, so a top-level import of the program-layout index here
    # would be circular. Every use below is a type annotation only.
    from ..generators.data.layout import FieldSpec
    from ..generators.data.program_layout import ProgramLayoutIndex

# FieldCategory has no such cycle (generators/data/layout.py has zero
# dependency back into cobolparser.analysis) -- domains.py already imports it
# the same way, unguarded.
from ..generators.data.layout import FieldCategory

_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_QUOTED_LITERAL_RE = re.compile(r'^(["\'])(.*)\1$', re.DOTALL)
#: The figurative constant ZERO in all three spellings: numeric zero moved
#: into a numeric field, a run of "0" characters into an alphanumeric one.
_ZERO_FIGURATIVES = frozenset({"ZERO", "ZEROS", "ZEROES"})
#: A subscript or reference-modification suffix: ``WS-T ( 1 )``, ``WS-B(1:1)``.
_SUFFIX_RE = re.compile(r"\s*\(.*$", re.DOTALL)

_TEXT_CATEGORIES = frozenset(
    {FieldCategory.ALPHANUMERIC, FieldCategory.ALPHABETIC, FieldCategory.NATIONAL}
)

#: Nested statement-list attributes a write-target scan (for IF/EVALUATE arm
#: bodies and loop bodies) must recurse into. Mirrors the same discipline
#: `program_flow/scanner.py` and `boundary_inventory.py` each converged on
#: independently.
_NESTED_STATEMENT_ATTRS = (
    "then_statements",
    "else_statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_size_error",
    "not_on_size_error",
    "on_overflow",
    "not_on_overflow",
    "on_exception",
    "not_on_exception",
)

#: The conditional-handler subset of the above: statement-level clause bodies
#: that may or may not fire at runtime (AT END, INVALID KEY, ON SIZE ERROR,
#: ON OVERFLOW, ON EXCEPTION, AT EOP -- and their NOT variants). The main
#: fold walk cannot evaluate whether such a handler fires, so every field a
#: handler body could write must be poisoned, exactly like an IF arm --
#: "exact by construction, or absent". Excludes the structural attributes
#: (`then_statements`/`else_statements`/`inline_statements`), which the walk
#: already dispatches on per statement type.
_HANDLER_BODY_ATTRS = (
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_size_error",
    "not_on_size_error",
    "on_overflow",
    "not_on_overflow",
    "on_exception",
    "not_on_exception",
)


def _safe_resolve(index: ProgramLayoutIndex, name: str) -> Any:
    """`ProgramLayoutIndex.resolve()`, guarded against garbage tokens.

    This module's fallback for an unmodeled statement type poisons every
    name in its raw `.operands` list (see `_walk_one`), which is not always
    a clean data-name -- a stray `"."` token has been observed leaking into
    an operand list for at least one real-world program (a parser artifact,
    not something this module can prevent at the source). A punctuation-only
    token can never be a real COBOL data-name, so it is filtered out before
    ever reaching `resolve()`, rather than relying solely on that method's
    own defenses against malformed input."""
    if not name or not name.strip(" ."):
        return None
    return index.resolve(name)


def _base_name(name: str) -> tuple[str, bool]:
    """*name* without any subscript / reference-modification suffix, and
    whether one was there. ``WS-T ( 1 )`` and ``WS-B(1:1)`` both name storage
    inside ``WS-T``/``WS-B`` that this walk does not model position by
    position, so a write through either poisons the base item as a whole."""
    text = (name or "").strip()
    if "(" in text:
        return _SUFFIX_RE.sub("", text).strip(), True
    return text, False


class _LayoutFacts:
    """What the walk needs to know about a program's storage *beyond* what
    `ProgramLayoutIndex.resolve()` answers (which only ever finds elementary
    fields): which qualified leaves sit under each group item, which leaves
    share bytes through a REDEFINES chain, and which are JUSTIFIED. Built
    once per index from the raw `CobolDataItem` trees and cached weakly."""

    __slots__ = ("groups", "leaves", "aliases", "justified", "renames")

    def __init__(self) -> None:
        #: UPPERCASED bare group/record name -> qualified paths of every
        #: group item carrying that name (a name may repeat across records).
        self.groups: dict[str, list[str]] = {}
        #: Every elementary leaf, as its qualified name (the env key shape).
        self.leaves: list[str] = []
        #: Leaf -> the other leaves whose bytes it shares via REDEFINES.
        self.aliases: dict[str, set[str]] = {}
        #: Leaves declared JUSTIFIED (RIGHT).
        self.justified: set[str] = set()
        #: UPPERCASED level-66 RENAMES name -> every leaf whose bytes it
        #: covers. A 66 is not a `CobolDataItem` (the index never resolves
        #: it), so without this a write through the alias poisoned nothing.
        self.renames: dict[str, list[str]] = {}

    def leaves_under(self, qpath: str) -> list[str]:
        prefix = qpath + "."
        return [
            leaf for leaf in self.leaves if leaf == qpath or leaf.startswith(prefix)
        ]


_FACTS_CACHE: weakref.WeakKeyDictionary[Any, _LayoutFacts] = weakref.WeakKeyDictionary()


def _facts(index: ProgramLayoutIndex) -> _LayoutFacts:
    try:
        cached = _FACTS_CACHE.get(index)
    except TypeError:  # an index that cannot be weakly referenced
        cached = None
    if cached is not None:
        return cached
    facts = _LayoutFacts()
    records_method = getattr(index, "records", None)
    top_level: list[CobolDataItem] = (
        list(records_method()) if callable(records_method) else []
    )
    for record in top_level:
        _collect_facts(record, (), facts)
    # A top-level ``01 B REDEFINES A`` has the section's records as its
    # sibling list; every section is pooled here, which can only widen the
    # alias set (an over-approximation that poisons more, never less).
    _link_redefines(top_level, (), facts)
    _link_file_records(index, facts)
    _collect_renames(index, facts)
    try:
        _FACTS_CACHE[index] = facts
    except TypeError:
        pass
    return facts


def _collect_renames(index: ProgramLayoutIndex, facts: _LayoutFacts) -> None:
    """Map every level-66 ``RENAMES a [THRU b]`` to the leaves it covers:
    the declaration-order run from *a*'s first leaf to *b*'s last. When the
    run cannot be pinned down exactly (an ambiguous or cross-record span),
    every leaf of the record(s) involved is taken instead -- poisoning more,
    never less."""
    ast = getattr(index, "ast", None)
    get_division = getattr(ast, "get_division", None)
    data_div = get_division("DATA") if callable(get_division) else None
    if data_div is None:
        return
    for section in getattr(data_div, "children", None) or []:
        for node in getattr(section, "children", None) or []:
            if isinstance(node, RenamesItem) and node.name:
                covered = _renames_leaves(node, index, facts)
                if covered:
                    facts.renames.setdefault(node.name.upper(), []).extend(covered)


def _renames_leaves(
    item: RenamesItem, index: ProgramLayoutIndex, facts: _LayoutFacts
) -> list[str]:
    first, first_exact = _span_leaves(item.renames_from, index, facts)
    last, last_exact = _span_leaves(
        item.renames_through or item.renames_from, index, facts
    )
    if first and last and first_exact and last_exact:
        start, end = first[0], last[-1]
        if (
            start in facts.leaves
            and end in facts.leaves
            and start.split(".")[0] == end.split(".")[0]
        ):
            i, j = facts.leaves.index(start), facts.leaves.index(end)
            if i <= j:
                return facts.leaves[i : j + 1]
    records = {leaf.split(".")[0] for leaf in [*first, *last]}
    return [leaf for record in sorted(records) for leaf in facts.leaves_under(record)]


def _span_leaves(
    name: str | None, index: ProgramLayoutIndex, facts: _LayoutFacts
) -> tuple[list[str], bool]:
    """Leaves a RENAMES operand names, in declaration order -- the
    elementary field itself, or every leaf under the group item -- and
    whether that answer is unambiguous (a group name declared more than
    once returns every candidate's leaves, flagged inexact, so the caller
    widens to the whole record)."""
    if not name or not name.strip(" ."):
        return [], False
    resolved = _safe_resolve(index, name)
    if resolved is not None:
        return [resolved.spec.qualified_name], True
    wanted = name.strip().upper()
    paths = facts.groups.get(wanted, [])
    if not paths:
        # An ambiguous elementary name (`resolve()` refuses to pick one):
        # every leaf of that name, flagged inexact.
        return [
            leaf for leaf in facts.leaves if leaf.rsplit(".", 1)[-1].upper() == wanted
        ], False
    leaves = [leaf for qpath in paths for leaf in facts.leaves_under(qpath)]
    return leaves, len(paths) == 1


def _renames_paths(index: ProgramLayoutIndex, name: str) -> list[str]:
    """Leaves covered by *name* when it is a level-66 RENAMES alias."""
    return list(_facts(index).renames.get(name.strip().upper(), []))


def _data_children(item: CobolDataItem) -> list[CobolDataItem]:
    # Same filter as CobolDataItem._direct_data_children: level-88/66 nodes
    # are not CobolDataItems, and a level-77 misfiled under a preceding item
    # by level-number nesting is a standalone record, not a child.
    return [
        child
        for child in item.children
        if isinstance(child, CobolDataItem) and child.level != 77
    ]


def _collect_facts(
    item: CobolDataItem, path: tuple[str, ...], facts: _LayoutFacts
) -> None:
    qpath = (*path, item.name)
    qname = ".".join(qpath)
    children = _data_children(item)
    if children:
        facts.groups.setdefault(item.name.upper(), []).append(qname)
        for child in children:
            _collect_facts(child, qpath, facts)
        _link_redefines(children, qpath, facts)
        return
    facts.leaves.append(qname)
    if getattr(item, "justified", False):
        facts.justified.add(qname)


def _link_redefines(
    siblings: list[CobolDataItem], path: tuple[str, ...], facts: _LayoutFacts
) -> None:
    """Union every leaf under a REDEFINES slot (``[base, redefiner, ...]``,
    chains included) into one alias class: a write to any of them may
    change the bytes every other one reads.

    Deliberately not built on ``layout_offsets._walk_redefines_chain``,
    despite both starting from the same ``item.redefines`` pointers: that
    function walks *one* item's own chain outward (for reporting its
    ``redefines_chain``, ordered, one-directional) and has no way to answer
    "which other siblings also redefine the same base" -- exactly what a
    write-invalidation alias class needs when more than one sibling
    redefines the same base item (``C REDEFINES B``, ``D REDEFINES B``: C
    and D share B's bytes with each other, not just with B, which a
    per-item chain walk never surfaces). The union-find below groups
    transitively-linked siblings into one set regardless of how many
    redefine the same base; a chain walk answers a different question and
    was checked before writing this rather than assumed different."""
    if len(siblings) < 2:
        return
    first_by_name: dict[str, int] = {}
    for position, sibling in enumerate(siblings):
        first_by_name.setdefault(sibling.name.upper(), position)
    parent = list(range(len(siblings)))

    def find(position: int) -> int:
        while parent[position] != position:
            parent[position] = parent[parent[position]]
            position = parent[position]
        return position

    linked = False
    for position, sibling in enumerate(siblings):
        target = (sibling.redefines or "").strip().upper()
        if not target or target not in first_by_name:
            continue
        other = first_by_name[target]
        if other == position:
            continue
        root_a, root_b = find(position), find(other)
        if root_a != root_b:
            parent[root_a] = root_b
            linked = True
    if not linked:
        return

    classes: dict[int, set[str]] = {}
    for position, sibling in enumerate(siblings):
        qname = ".".join((*path, sibling.name))
        classes.setdefault(find(position), set()).update(facts.leaves_under(qname))
    for members in classes.values():
        if len(members) < 2:
            continue
        for leaf in members:
            facts.aliases.setdefault(leaf, set()).update(members - {leaf})


def _link_file_records(index: ProgramLayoutIndex, facts: _LayoutFacts) -> None:
    """Union every leaf of every 01 record under one FD/SD into one alias
    class: the records of a file all implicitly redefine the same record
    area, so writing a field of one changes the bytes the others read --
    with no ``REDEFINES`` clause for `_link_redefines` to see."""
    file_names = getattr(index, "file_names", None)
    if not callable(file_names):
        return
    for file_name in file_names():
        records = index.records_for_file(file_name)
        if len(records) < 2:
            continue
        members: set[str] = set()
        for record in records:
            members.update(facts.leaves_under(record.name))
        for leaf in list(members):
            members |= facts.aliases.get(leaf, set())
        if len(members) < 2:
            continue
        for leaf in members:
            facts.aliases.setdefault(leaf, set()).update(members - {leaf})


def _group_paths(index: ProgramLayoutIndex, name: str) -> list[str]:
    """Qualified paths of the group item(s) *name* denotes -- bare, ``A OF
    B``, or dotted ``B.A``. Every match is returned: when a bare name is
    declared in more than one record the walk poisons all of them rather
    than guess which one the program meant."""
    # Local import: same circular-import guard as the TYPE_CHECKING-only
    # `ProgramLayoutIndex` import above -- a top-level import of
    # program_layout here would be circular (cobolparser.generators
    # constructs ConstantFolder).
    from ..generators.data.program_layout import split_qualified_name

    split = split_qualified_name(name)
    if split is None:
        return []
    base, qualifiers = split
    candidates = _facts(index).groups.get(base, [])
    if not qualifiers:
        return list(candidates)
    wanted = set(qualifiers)
    return [
        qpath
        for qpath in candidates
        if wanted <= {segment.upper() for segment in qpath.split(".")}
    ]


def _file_record_paths(index: ProgramLayoutIndex, file_name: str | None) -> list[str]:
    if not file_name:
        return []
    return [record.name for record in index.records_for_file(file_name)]


def _drop(qname: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]) -> None:
    """Forget *qname* -- and every leaf sharing its bytes through REDEFINES."""
    env.pop(qname, None)
    for alias in _facts(index).aliases.get(qname, ()):
        env.pop(alias, None)


def _drop_under(
    qpath: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    """Forget every leaf under the group/record *qpath* (aliases included)."""
    for leaf in _facts(index).leaves_under(qpath):
        _drop(leaf, index, env)
    prefix = qpath + "."
    for key in [k for k in env if k == qpath or k.startswith(prefix)]:
        env.pop(key, None)


@dataclass
class ConstantFoldResult:
    """Fields still knowable at a DISPLAY/WRITE site by the end of the walk."""

    known: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"known": dict(self.known)}


class ConstantFolder:
    """Forward-walks a program's entry paragraph chain, folding what it can."""

    def fold(
        self,
        ast: CobolProgram,
        index: ProgramLayoutIndex,
        *,
        seed_values: dict[str, str] | None = None,
    ) -> ConstantFoldResult:
        env: dict[str, Decimal | str] = {}
        seeds: dict[str, str] = seed_values if seed_values is not None else {}
        for name, raw in seeds.items():
            resolved = _safe_resolve(index, name)
            if resolved is None:
                continue
            seeded = _seed_value(raw, resolved.spec)
            if seeded is not None:
                env[resolved.spec.qualified_name] = seeded

        entry = _entry_paragraph(ast)
        if entry is None:
            return ConstantFoldResult(known={})

        ordered_names, by_name = _ordered_paragraphs(ast)
        state = _WalkState(env=env, seed_env=dict(env))
        _walk_statements(
            entry.statements,
            index,
            by_name,
            ordered_names,
            state,
            {entry.paragraph_name.upper()} if entry.paragraph_name else set(),
        )

        known: dict[str, str] = {}
        for qname in state.observed:
            value = state.env.get(qname)
            if value is None:
                continue
            resolved = _safe_resolve(index, qname)
            if resolved is None:
                continue
            known[qname] = _render(value, resolved.spec)
        return ConstantFoldResult(known=known)


# -- walk state ---------------------------------------------------------------


class _WalkState:
    __slots__ = ("env", "seed_env", "observed", "stopped", "read_files", "accepted")

    def __init__(
        self,
        env: dict[str, Decimal | str],
        seed_env: dict[str, Decimal | str] | None = None,
    ) -> None:
        self.env = env
        #: The scenario's own mock-supplied values, as typed at fold start:
        #: what the FIRST READ of a file / ACCEPT of a target puts back into
        #: `env`, whatever the chain MOVEd there beforehand.
        self.seed_env: dict[str, Decimal | str] = seed_env if seed_env else {}
        self.observed: set[str] = set()
        self.stopped = False
        #: UPPERCASED file names already READ on the walked path (loop and
        #: branch bodies included), so a later READ is known to be past the
        #: single mocked record and poisons rather than re-seeds.
        self.read_files: set[str] = set()
        #: UPPERCASED ACCEPT targets already ACCEPTed, same idea.
        self.accepted: set[str] = set()


# -- entry point / paragraph ordering -----------------------------------------


def _entry_paragraph(ast: CobolProgram) -> CobolParagraph | None:
    """Mirrors `ProgramFixtureGenerator._entry_paragraph`'s own convention
    (top-level paragraphs take precedence over section-nested ones) --
    duplicated rather than imported, since importing from `generators` here
    would recreate the exact circular-import shape Phase 6 fixed at the
    package-init level."""
    procedure = ast.get_division("PROCEDURE")
    if procedure is None:
        return None
    if procedure.paragraphs:
        return procedure.paragraphs[0]
    for section in procedure.sections:
        if getattr(section, "is_declarative", False):
            # A USE procedure the runtime invokes on an I/O error; control
            # enters at the first section after END DECLARATIVES.
            continue
        section_paragraphs: list[CobolParagraph] | None = getattr(
            section, "paragraphs", None
        )
        if section_paragraphs:
            return section_paragraphs[0]
    return None


def _ordered_paragraphs(
    ast: CobolProgram,
) -> tuple[list[str], dict[str, CobolParagraph]]:
    """Flat, source-ordered paragraph name list + name -> node map, for
    resolving `PERFORM ... THRU ...` ranges. Mirrors
    `program_flow/scanner.py`'s / `dead_code.py`'s traversal: sections and
    top-level paragraphs are interleaved by source line, because COBOL allows
    paragraphs before the first SECTION header -- appending all section-owned
    paragraphs first would invert source order for such mixed programs,
    making every `PERFORM ... THRU ...` range resolve against a scrambled
    list (empty bodies, stale folded values)."""
    procedure = ast.get_division("PROCEDURE")
    if procedure is None:
        return [], {}
    ordered: list[str] = []
    by_name: dict[str, CobolParagraph] = {}

    def register(para: CobolParagraph) -> None:
        if para.paragraph_name:
            name = para.paragraph_name.upper()
            if name not in by_name:
                ordered.append(name)
                by_name[name] = para

    top_level_items: list[Any] = sorted(
        [*procedure._sections.values(), *procedure.paragraphs],
        key=lambda item: item.location.line,
    )
    for item in top_level_items:
        if isinstance(item, CobolParagraph):
            register(item)
        else:
            for para in item.paragraphs:
                register(para)
    return ordered, by_name


# -- the walk itself -----------------------------------------------------------


def _walk_statements(
    statements: list[Any],
    index: ProgramLayoutIndex,
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
    state: _WalkState,
    visiting: set[str],
) -> None:
    """Iterative driver over a statement list, including every SIMPLE
    PERFORM it transitively reaches (inline or out-of-line).

    A non-looping PERFORM to another paragraph is a subroutine jump that
    must eventually return to the calling list -- naively recursing through
    Python's own call stack for that (one frame per paragraph in the chain)
    blows the interpreter's recursion limit on an ordinary large program (a
    few hundred chained paragraphs is enough). An explicit frame stack is
    walked instead, the same fix `program_flow/cycles.py` already applies to
    its own paragraph-graph traversal for the identical reason. Each frame
    is (iterator over a statement list, the paragraph name entered to reach
    it or None) so `visiting` can be added/discarded with the same lifetime
    the recursive version gave it.
    """
    frames: list[tuple[Iterator[Any], str | None]] = [(iter(statements), None)]
    while frames:
        if state.stopped:
            return
        iterator, entered = frames[-1]
        stmt = next(iterator, None)
        if stmt is None:
            frames.pop()
            if entered is not None:
                visiting.discard(entered)
            continue
        jump = _walk_one(stmt, index, by_name, ordered_names, state)
        if jump is not None:
            target, body = jump
            if target is not None:
                if target in visiting:
                    continue  # non-looping PERFORM cycle: stop rather than recurse forever
                visiting.add(target)
            frames.append((iter(body), target))


def _walk_one(
    stmt: Any,
    index: ProgramLayoutIndex,
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
    state: _WalkState,
) -> tuple[str | None, list[Any]] | None:
    """Fold one statement in place; return a (paragraph-name-or-None, body)
    pair when `_walk_statements` must push a new frame to keep walking (a
    SIMPLE PERFORM, inline or to another paragraph), else None."""
    result = _dispatch_one(stmt, index, by_name, ordered_names, state)
    # Conditional handler bodies (AT END / INVALID KEY / ON SIZE ERROR /
    # ON OVERFLOW / ON EXCEPTION / AT EOP, and their NOT variants) may or may
    # not fire -- this walk cannot tell -- so every field they could write is
    # poisoned, the same treatment an IF arm gets. Runs *after* the dispatch
    # above so a handler write always trumps the statement's own folded
    # result (`ADD 1 TO X ON SIZE ERROR MOVE 0 TO X` must leave X unknown).
    for attr in _HANDLER_BODY_ATTRS:
        body = getattr(stmt, attr, None)
        if isinstance(body, list) and body:
            _poison_written_names(
                body, index, state.env, by_name, ordered_names, state=state
            )
    return result


def _dispatch_one(
    stmt: Any,
    index: ProgramLayoutIndex,
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
    state: _WalkState,
) -> tuple[str | None, list[Any]] | None:
    """Per-statement-type fold dispatch for `_walk_one` (which additionally
    poisons conditional handler bodies around whatever happens here)."""
    if isinstance(stmt, MoveStatement):
        _fold_move(stmt, index, state.env)
    elif isinstance(stmt, AddStatement):
        _fold_add(stmt, index, state.env)
    elif isinstance(stmt, SubtractStatement):
        _fold_subtract(stmt, index, state.env)
    elif isinstance(stmt, MultiplyStatement):
        _fold_multiply(stmt, index, state.env)
    elif isinstance(stmt, DivideStatement):
        _fold_divide(stmt, index, state.env)
    elif isinstance(stmt, ComputeStatement):
        _fold_compute(stmt, index, state.env)
    elif isinstance(stmt, DisplayStatement):
        for item in stmt.display_items:
            _mark_observed(item, index, state)
    elif isinstance(stmt, IOWriteStatement):
        if stmt.record_name and stmt.from_clause:
            # `WRITE rec FROM id` is `MOVE id TO rec` and then the WRITE. A
            # group record target is poisoned whole by `_apply_move_target`.
            source = _resolve_move_source(stmt.from_clause, index, state.env)
            _apply_move_target(
                stmt.record_name,
                source,
                index,
                state.env,
                source_width=_text_width(stmt.from_clause, index),
            )
        if stmt.record_name:
            _mark_observed(stmt.record_name, index, state)
    elif isinstance(stmt, IOReadStatement):
        _fold_read(stmt, index, state)
    elif isinstance(stmt, IOAcceptStatement):
        _fold_accept(stmt, index, state)
    elif isinstance(stmt, PerformStatement):
        return _walk_perform(stmt, index, by_name, ordered_names, state)
    elif isinstance(stmt, IfStatement):
        _poison_written_names(
            stmt.then_statements, index, state.env, by_name, ordered_names, state=state
        )
        _poison_written_names(
            stmt.else_statements, index, state.env, by_name, ordered_names, state=state
        )
    elif isinstance(stmt, EvaluateStatement):
        for wc in stmt.when_clauses:
            _poison_written_names(
                wc.statements, index, state.env, by_name, ordered_names, state=state
            )
        if stmt.default_when:
            _poison_written_names(
                stmt.default_when.statements,
                index,
                state.env,
                by_name,
                ordered_names,
                state=state,
            )
    elif isinstance(stmt, (GoStatement, StopStatement, GobackStatement)):
        state.stopped = True
    elif isinstance(stmt, ExitStatement) and stmt.exit_type == "PROGRAM":
        state.stopped = True
    else:
        # Unmodeled statement type: conservatively poison every name it
        # could write -- its operands plus every write-shaped attribute
        # (`_write_targets`) -- rather than risk a stale, now-incorrect env
        # entry surviving an unrecognized write (INITIALIZE, SET, STRING,
        # UNSTRING, INSPECT, CALL, SQL/CICS/DLI host variables, ...).
        # CALL/EXEC SQL/CICS/DLI are not seed-aware the way READ/ACCEPT
        # are: their operand lists mix genuinely-unknowable OUT-direction
        # values with seedable IN ones, and the raw AST does not carry
        # resolved direction to tell them apart (only
        # `BoundaryInventoryAnalyzer`'s own richer analysis does).
        _poison_statement_writes(stmt, index, state.env, state=state)
    return None


def _fold_read(
    stmt: IOReadStatement, index: ProgramLayoutIndex, state: _WalkState
) -> None:
    """A READ overwrites the file's record area and its INTO target.

    The FIRST READ of a file on the walked path is the one the scenario's
    mocked record answers, so every seeded field under the record (and the
    INTO target) is reset to its seed -- whatever the chain MOVEd there
    beforehand -- and every unseeded one is forgotten. A later READ of the
    same file is past the single mocked record (or hit AT END), and
    poisons. Before this, READ was a no-op that left `MOVE 'ABC' TO
    IN-CODE. READ IN-FILE. DISPLAY IN-CODE.` claiming ``'ABC'``.
    """
    file_name = (stmt.file_name or "").strip().upper()
    first = bool(file_name) and file_name not in state.read_files
    if file_name:
        state.read_files.add(file_name)
    for qpath in _file_record_paths(index, stmt.file_name):
        _reset_under(qpath, index, state, restore=first)
    if stmt.into_target:
        for qpath, exact in _target_paths(stmt.into_target, index):
            _reset_under(qpath, index, state, restore=first and exact)


def _fold_accept(
    stmt: IOAcceptStatement, index: ProgramLayoutIndex, state: _WalkState
) -> None:
    """An ACCEPT overwrites its target -- same first-time-reseeds,
    otherwise-poisons rule as `_fold_read`."""
    if not stmt.target:
        return
    base, _ = _base_name(stmt.target)
    key = base.upper()
    first = bool(key) and key not in state.accepted
    if key:
        state.accepted.add(key)
    for qpath, exact in _target_paths(stmt.target, index):
        _reset_under(qpath, index, state, restore=first and exact)


def _target_paths(name: str, index: ProgramLayoutIndex) -> list[tuple[str, bool]]:
    """Qualified path(s) a write target denotes, paired with whether *name*
    names each one exactly (``True``) or only through a subscript /
    reference-modification suffix (``False``).

    A plain name resolves to the leaf (or the group/record item(s) of that
    name) exactly. A subscripted or reference-modified name (``WS-T(1)``,
    ``WS-B(1:1)``) denotes only *part* of its base item -- this walk does
    not model position by position (see ``_base_name``) -- so a caller must
    never restore it to a known value on the strength of this call alone,
    only poison it; that is exactly how ``_apply_move_target``/
    ``_write_numeric`` already treat ``has_suffix`` elsewhere in this
    module. Before this, a first READ/ACCEPT into a subscripted target
    restored the *entire* base item to its seed value even though only the
    subscripted slice was actually written.
    """
    base, has_suffix = _base_name(name)
    if not base or not base.strip(" ."):
        return []
    resolved = _safe_resolve(index, base)
    if resolved is not None:
        return [(resolved.spec.qualified_name, not has_suffix)]
    paths = [(qpath, not has_suffix) for qpath in _group_paths(index, base)]
    # A level-66 RENAMES alias: its leaves are written, never restored to a
    # seed (the scenario's mocked value is for the alias, not the leaves).
    paths.extend((leaf, False) for leaf in _renames_paths(index, base))
    return paths


def _reset_under(
    qpath: str, index: ProgramLayoutIndex, state: _WalkState, *, restore: bool
) -> None:
    _drop_under(qpath, index, state.env)
    if not restore:
        return
    for leaf in _facts(index).leaves_under(qpath):
        if leaf in state.seed_env:
            state.env[leaf] = state.seed_env[leaf]


def _poison_statement_writes(
    stmt: Any,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
    *,
    state: _WalkState | None = None,
) -> None:
    """Poison everything *stmt* could write, with no attempt to fold it.

    A READ inside a branch/loop body poisons the file's whole record area
    (plus its INTO target) and is remembered on *state* so a READ of the
    same file further down the walk knows it is not the first. Every other
    statement poisons `_write_targets`.
    """
    if isinstance(stmt, IOReadStatement):
        file_name = (stmt.file_name or "").strip().upper()
        if state is not None and file_name:
            state.read_files.add(file_name)
        for qpath in _file_record_paths(index, stmt.file_name):
            _drop_under(qpath, index, env)
        if stmt.into_target:
            _poison_names([stmt.into_target], index, env)
        return
    if isinstance(stmt, IOAcceptStatement) and stmt.target and state is not None:
        base, _ = _base_name(stmt.target)
        state.accepted.add(base.upper())
    _poison_names(_write_targets(stmt), index, env)


def _mark_observed(operand: str, index: ProgramLayoutIndex, state: _WalkState) -> None:
    resolved = _safe_resolve(index, operand)
    if resolved is not None:
        state.observed.add(resolved.spec.qualified_name)


def _walk_perform(
    stmt: PerformStatement,
    index: ProgramLayoutIndex,
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
    state: _WalkState,
) -> tuple[str | None, list[Any]] | None:
    """Return the (paragraph-name-or-None, body) frame `_walk_statements`
    should push to keep walking a SIMPLE PERFORM's body, or None when there
    is nothing further for the caller to walk. The cycle guard on an
    out-of-line target lives in `_walk_statements` (it owns `visiting`'s
    add/discard lifetime); this function only resolves *what* to walk."""
    if stmt.perform_type != "SIMPLE":
        # UNTIL / VARYING / TIMES: zero-or-many iterations, nothing inside is
        # knowable -- poison what the body could write, then keep walking
        # *after* the loop (it still runs; the walk just can't see inside).
        # The body is either inline (`PERFORM ... UNTIL ... <stmts> END-
        # PERFORM`) or an out-of-line paragraph/THRU-range target -- never
        # both.
        # The VARYING / AFTER variables are left at whatever value ended the
        # loop (one BY step past the UNTIL), never at their pre-loop value.
        _poison_names(_write_targets(stmt), index, state.env)
        body = stmt.inline_statements or _perform_body_statements(
            stmt, by_name, ordered_names
        )
        _poison_written_names(
            body, index, state.env, by_name, ordered_names, state=state
        )
        return None

    if stmt.inline_statements:
        return (None, stmt.inline_statements)

    if not stmt.target_paragraph:
        return None
    target = stmt.target_paragraph.upper()
    body = _perform_body_statements(stmt, by_name, ordered_names)
    return (target, body)


def _perform_body_statements(
    stmt: PerformStatement,
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
) -> list[Any]:
    if not stmt.target_paragraph:
        return []
    start = stmt.target_paragraph.upper()
    end = (stmt.thru_paragraph or stmt.target_paragraph).upper()
    if start not in ordered_names or end not in ordered_names:
        para = by_name.get(start)
        return list(para.statements) if para else []
    start_idx = ordered_names.index(start)
    end_idx = ordered_names.index(end)
    if end_idx < start_idx:
        return []  # malformed/unexpected THRU order: nothing to walk, not a guess
    statements: list[Any] = []
    for name in ordered_names[start_idx : end_idx + 1]:
        para = by_name.get(name)
        if para:
            statements.extend(para.statements)
    return statements


# -- "what does this block write" (IF/EVALUATE arms, loop bodies) -------------


def _write_targets(stmt: Any) -> list[str]:
    if isinstance(stmt, MoveStatement):
        return list(stmt.targets)
    if isinstance(stmt, DivideStatement):
        # REMAINDER is a written target too -- leaving it out would let a
        # stale env entry survive a DIVIDE inside an IF arm / handler body.
        remainder = [stmt.remainder] if stmt.remainder else []
        return [*stmt.targets, *stmt.givings, *remainder]
    if isinstance(stmt, (AddStatement, SubtractStatement, MultiplyStatement)):
        return [*stmt.targets, *stmt.givings]
    if isinstance(stmt, ComputeStatement):
        return list(stmt.targets)
    if isinstance(stmt, IOReadStatement) and stmt.into_target:
        return [stmt.into_target]
    if isinstance(stmt, PerformStatement):
        # Only the PERFORM's own writes -- its VARYING / AFTER loop
        # variables -- not its body's (callers walk the body separately).
        clauses = [stmt.varying_clause, *stmt.after_clauses]
        return [
            clause["variable"]
            for clause in clauses
            if isinstance(clause, dict) and isinstance(clause.get("variable"), str)
        ]
    if isinstance(stmt, CallStatement):
        names = [p.name for p in stmt.using_parameters]
        if stmt.returning_parameter:
            names.append(stmt.returning_parameter)
        if stmt.giving_parameter:
            names.append(stmt.giving_parameter)
        return names
    # Everything else: its operand bag plus every write-shaped attribute a
    # statement model can carry. `.operands` alone missed real writes --
    # EXEC SQL's host variables live in `.host_variables`, UNSTRING's
    # receivers in `.into_targets[*]["target"]`, STRING's in `.into_target`
    # (absent from its operands entirely), INSPECT/ACCEPT's in `.target`,
    # and the WITH POINTER / TALLYING counters in their own attributes.
    names = list(getattr(stmt, "operands", None) or [])
    for attr in ("targets", "givings", "host_variables"):
        names.extend(getattr(stmt, attr, None) or [])
    for attr in (
        "target",
        "into_target",
        "pointer_variable",
        "tallying_variable",
        "varying_variable",  # SEARCH ... VARYING: stepped with the index
    ):
        value = getattr(stmt, attr, None)
        if isinstance(value, str) and value:
            names.append(value)
    for entry in getattr(stmt, "into_targets", None) or []:
        if not isinstance(entry, dict):
            continue
        for key in ("target", "name", "delimiter_var", "count_var"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                names.append(value)
    return names


def _nested_statement_lists(stmt: Any) -> list[list[Any]]:
    lists: list[list[Any]] = []
    for attr in _NESTED_STATEMENT_ATTRS:
        value = getattr(stmt, attr, None)
        if isinstance(value, list):
            lists.append(value)
    if isinstance(stmt, EvaluateStatement):
        for wc in stmt.when_clauses:
            lists.append(wc.statements)
        if stmt.default_when:
            lists.append(stmt.default_when.statements)
    return lists


def _poison_written_names(
    statements: list[Any],
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
    by_name: dict[str, CobolParagraph],
    ordered_names: list[str],
    visiting: set[str] | None = None,
    *,
    state: _WalkState | None = None,
) -> None:
    """Poison every field a nested block (an IF/EVALUATE arm, a loop body)
    could possibly write -- including through a PERFORM to another
    paragraph, which must be followed back to that paragraph's own
    statements (a PERFORM's own `.operands` is just the target paragraph
    name, not a field).

    A PERFORM-to-paragraph chain is followed via an explicit frame stack
    rather than recursing into this function -- same reasoning as
    `_walk_statements`: one Python stack frame per paragraph in the chain
    blows the recursion limit on an ordinary large program. Recursion is
    still used for genuinely nested statement lists (an IF/EVALUATE arm or
    loop body found *within* a block already being poisoned); that depth is
    bounded by real source nesting, not by paragraph-chain length."""
    if visiting is None:
        visiting = set()
    frames: list[tuple[Iterator[Any], str | None]] = [(iter(statements), None)]
    while frames:
        iterator, entered = frames[-1]
        stmt = next(iterator, None)
        if stmt is None:
            frames.pop()
            if entered is not None:
                visiting.discard(entered)
            continue
        if isinstance(stmt, PerformStatement):
            _poison_names(_write_targets(stmt), index, env)
            if stmt.inline_statements:
                frames.append((iter(stmt.inline_statements), None))
                continue
            target = (stmt.target_paragraph or "").upper()
            if not target or target in visiting:
                continue  # non-looping PERFORM cycle: stop rather than recurse forever
            body = _perform_body_statements(stmt, by_name, ordered_names)
            visiting.add(target)
            frames.append((iter(body), target))
            continue
        _poison_statement_writes(stmt, index, env, state=state)
        for nested in _nested_statement_lists(stmt):
            _poison_written_names(
                nested, index, env, by_name, ordered_names, visiting, state=state
            )


# -- MOVE ----------------------------------------------------------------------


def _fold_move(
    stmt: MoveStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.is_corresponding:
        _poison_names(stmt.targets, index, env)
        return
    source = _resolve_move_source(stmt.source, index, env) if stmt.source else None
    width = _text_width(stmt.source, index) if stmt.source else None
    for target in stmt.targets:
        _apply_move_target(target, source, index, env, source_width=width)


def _text_width(source: str, index: ProgramLayoutIndex) -> int | None:
    """Character width of *source* when it is an alphanumeric-class field,
    else ``None``. `env` stores a text value unpadded, but a MOVE sends the
    source's whole field -- trailing spaces included -- which is what a
    JUSTIFIED RIGHT receiver truncates on the left."""
    if _NUMERIC_LITERAL_RE.match(source) or _QUOTED_LITERAL_RE.match(source):
        return None
    resolved = _safe_resolve(index, source)
    if resolved is None or resolved.spec.category not in _TEXT_CATEGORIES:
        return None
    size = resolved.spec.size
    if resolved.spec.category is FieldCategory.NATIONAL:
        size //= 2
    return size if size > 0 else None


def _resolve_move_source(
    source: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> tuple[str, Decimal | str] | None:
    if _NUMERIC_LITERAL_RE.match(source):
        try:
            return ("numeric", Decimal(source))
        except InvalidOperation:
            return None
    if _QUOTED_LITERAL_RE.match(source):
        # Doubled delimiters collapsed: MOVE '"' arrives as `""""`.
        return ("text", unquote_literal(source))
    if source.strip().upper() in _ZERO_FIGURATIVES:
        return ("zero", Decimal(0))
    resolved = _safe_resolve(index, source)
    if resolved is None:
        return None
    value = env.get(resolved.spec.qualified_name)
    if value is None:
        return None
    return ("numeric", value) if isinstance(value, Decimal) else ("text", value)


def _apply_move_target(
    target_name: str,
    source: tuple[str, Decimal | str] | None,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
    *,
    source_width: int | None = None,
) -> None:
    base, has_suffix = _base_name(target_name)
    resolved = _safe_resolve(index, base) if not has_suffix else None
    if resolved is None:
        # A group/record target (`MOVE SPACES TO WS-GRP`), or a subscripted
        # / reference-modified one (`WS-B(1:1)`): every leaf under the base
        # item is forgotten. `resolve()` never finds a group, which used to
        # leave stale child values standing after a whole-group write.
        _poison_names([base], index, env)
        return
    qname = resolved.spec.qualified_name
    # Any write drops the old value AND every REDEFINES alias sharing its
    # bytes, before the new value (if any) is recorded.
    _drop(qname, index, env)
    if source is None:
        return
    kind, value = source
    if kind == "zero":
        # MOVE ZERO fills the whole field: 0 in a numeric one, "0" in every
        # character position of an alphanumeric one.
        if resolved.spec.category is FieldCategory.NUMERIC:
            env[qname] = Decimal(0)
        elif (
            resolved.spec.category is FieldCategory.ALPHANUMERIC
            and resolved.spec.size > 0
        ):
            env[qname] = "0" * resolved.spec.size
        return
    if kind == "numeric" and isinstance(value, Decimal):
        if resolved.spec.category is FieldCategory.NUMERIC and _fits_exactly(
            value, resolved.spec
        ):
            env[qname] = value
    elif kind == "text" and isinstance(value, str):
        if resolved.spec.category in _TEXT_CATEGORIES:
            size = resolved.spec.size if resolved.spec.size > 0 else len(value)
            if resolved.spec.category is FieldCategory.NATIONAL:
                # `size` is bytes; a national character is two of them, so
                # PIC N(3) (six bytes) holds three characters, not six.
                size //= 2
            if qname in _facts(index).justified:
                # JUSTIFIED RIGHT keeps the RIGHTMOST characters of an
                # oversized value; a shorter one is padded on the left,
                # a rendering this module's unpadded env does not model,
                # so only the exact/oversized case is knowable. A field
                # source sends its whole width, trailing spaces included.
                if source_width is not None:
                    value = value.ljust(source_width)
                if len(value) >= size:
                    env[qname] = value[-size:]
            else:
                env[qname] = value[:size]


# -- arithmetic ------------------------------------------------------------


def _resolve_operand(
    token: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> Decimal | None:
    if _NUMERIC_LITERAL_RE.match(token):
        try:
            return Decimal(token)
        except InvalidOperation:
            return None
    if token.strip().upper() in _ZERO_FIGURATIVES:
        return Decimal(0)
    resolved = _safe_resolve(index, token)
    if resolved is None:
        return None
    value = env.get(resolved.spec.qualified_name)
    return value if isinstance(value, Decimal) else None


def _poison_names(
    names: list[str], index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    """Forget every name: an elementary field (and its REDEFINES aliases),
    or -- when the name is a group/record, or carries a subscript /
    reference-modification -- every leaf under the item as a whole."""
    for name in names:
        base, _ = _base_name(name)
        if not base or not base.strip(" ."):
            continue
        resolved = _safe_resolve(index, base)
        if resolved is not None:
            _drop(resolved.spec.qualified_name, index, env)
            continue
        for qpath in _group_paths(index, base):
            _drop_under(qpath, index, env)
        for leaf in _renames_paths(index, base):
            _drop(leaf, index, env)


def _write_numeric(
    name: str, value: Decimal, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    base, has_suffix = _base_name(name)
    resolved = _safe_resolve(index, base) if not has_suffix else None
    if resolved is None:
        _poison_names([base], index, env)
        return
    qname = resolved.spec.qualified_name
    _drop(qname, index, env)
    if resolved.spec.category is FieldCategory.NUMERIC and _fits_exactly(
        value, resolved.spec
    ):
        env[qname] = value


def _fold_add(
    stmt: AddStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.rounded or stmt.is_corresponding:
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return
    if stmt.givings:
        _fold_add_subtract_giving(stmt, add=True, index=index, env=env)
        return
    _fold_add_subtract_accumulate(stmt, add=True, index=index, env=env)


def _fold_subtract(
    stmt: SubtractStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.rounded or stmt.is_corresponding:
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return
    if stmt.givings:
        _fold_add_subtract_giving(stmt, add=False, index=index, env=env)
        return
    _fold_add_subtract_accumulate(stmt, add=False, index=index, env=env)


def _fold_add_subtract_giving(
    stmt: ArithmeticStatement,
    *,
    add: bool,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
) -> None:
    """The GIVING form always reads OLD values and never modifies an
    operand in place: ``result = base (+/-) sum(addends)``, where ``base`` is
    the (at most one, in standard grammar) TO/FROM operand, or zero.

    The addends are ``stmt.source_operands`` -- what was written before
    TO/FROM/GIVING, duplicates kept. ``.operands`` cannot stand in for it:
    a target or GIVING name is appended there only when not already
    present, so ``ADD A B GIVING B`` and ``ADD A GIVING B`` look identical,
    and filtering target/GIVING names out of it silently dropped a real
    addend (``ADD -6.05 N8 GIVING N8`` folded to -6.05). A node without
    ``source_operands`` is poisoned rather than guessed at."""
    addend_tokens = stmt.source_operands
    if not addend_tokens:
        _poison_names(stmt.givings, index, env)
        return
    addend_values = [_resolve_operand(op, index, env) for op in addend_tokens]
    if any(v is None for v in addend_values):
        _poison_names(stmt.givings, index, env)
        return
    known_addends: list[Decimal] = [v for v in addend_values if v is not None]
    total = sum(known_addends, Decimal(0))
    if len(stmt.targets) > 1:
        # `ADD/SUBTRACT ... TO/FROM b, c GIVING d` is a nonstandard
        # combination this module does not attempt to interpret.
        _poison_names(stmt.givings, index, env)
        return
    base = Decimal(0)
    if stmt.targets:
        resolved_base = _resolve_operand(stmt.targets[0], index, env)
        if resolved_base is None:
            _poison_names(stmt.givings, index, env)
            return
        base = resolved_base
    result = base + total if add else base - total
    for giving in stmt.givings:
        _write_numeric(giving, result, index, env)


def _fold_add_subtract_accumulate(
    stmt: ArithmeticStatement,
    *,
    add: bool,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
) -> None:
    """Format 1 (no GIVING): each target accumulates `target := target (+/-)
    sum(addends)`, the addends being ``stmt.source_operands`` (see
    `_fold_add_subtract_giving` for why ``.operands`` cannot answer that:
    ``ADD X TO X`` doubles X, but its ``.operands`` is just ``[X]``). A node
    without ``source_operands`` is poisoned rather than guessed at."""
    addend_tokens = stmt.source_operands
    if not addend_tokens:
        _poison_names(stmt.targets, index, env)
        return
    operand_values = [_resolve_operand(op, index, env) for op in addend_tokens]
    if any(v is None for v in operand_values):
        _poison_names(stmt.targets, index, env)
        return
    known_operands: list[Decimal] = [v for v in operand_values if v is not None]
    total = sum(known_operands, Decimal(0))
    for target in stmt.targets:
        current = _resolve_operand(target, index, env)
        if current is None:
            _poison_names([target], index, env)
            continue
        _write_numeric(target, current + total if add else current - total, index, env)


def _fold_multiply(
    stmt: MultiplyStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.rounded:
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return
    # Format 1 (no GIVING) legitimately reuses the target's own name as the
    # second operand (`MULTIPLY A BY B` reads B's old value directly, no
    # hidden extra term -- unlike ADD/SUBTRACT's accumulate form) so only
    # GIVING names are filtered out here, never targets.
    true_operands = [op for op in stmt.operands if op not in stmt.givings]
    if len(true_operands) != 2:
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return
    operand_values = [_resolve_operand(op, index, env) for op in true_operands]
    if any(v is None for v in operand_values):
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return
    # Multiplication is commutative, so unlike DIVIDE there is no BY/INTO
    # order ambiguity to worry about here.
    product = operand_values[0] * operand_values[1]  # type: ignore[operator]
    for target in stmt.givings or stmt.targets:
        _write_numeric(target, product, index, env)


def _exact_divide(dividend: Decimal, divisor: Decimal) -> Decimal | None:
    """``dividend / divisor`` only when the quotient is exactly
    representable. None means "poison", same contract as every other helper
    here.

    The multiply-back that proves exactness is done over :class:`Fraction`,
    not over :class:`Decimal`. Verifying in decimal at the *same* precision
    the division used cannot work: the rounding error is by construction
    smaller than that precision can represent, so ``quotient * divisor``
    rounds straight back to ``dividend`` and the check passes for every
    inexact quotient it was written to catch. ``3 / 0.3333333333333333333333333333334``
    at 80 digits multiplies back to exactly ``3`` while the quotient is
    really ``8.999...9982``. A rational multiply-back has no precision to
    hide in.
    """
    if divisor == 0 or not dividend.is_finite() or not divisor.is_finite():
        return None
    with localcontext() as ctx:
        ctx.prec = 80
        quotient = dividend / divisor
    if Fraction(quotient) * Fraction(divisor) != Fraction(dividend):
        return None
    return quotient


def _fold_divide(
    stmt: DivideStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    """Fold the DIVIDE forms whose semantics are now recoverable from the
    AST via ``division_mode`` (BY vs INTO invert dividend/divisor order).

    Kept "exact by construction, or absent" like everything else:

    * ``division_mode is None`` (older AST, unparsable separator) poisons --
      the pre-``division_mode`` behavior for every DIVIDE.
    * ROUNDED poisons (same gate as ADD/SUBTRACT/MULTIPLY).
    * A REMAINDER target is always poisoned: the remainder is defined via
      the quotient *as truncated to the GIVING target's PICTURE*, which
      this module deliberately does not model. The GIVING value itself is
      still safe to fold -- it is only recorded when the true quotient fits
      the target exactly, in which case truncation was a no-op.
    * ``DIVIDE a BY b`` without GIVING is a nonstandard shape the parser
      tolerates; its semantics are not defined by the standard, so it
      poisons rather than guesses.
    * `.operands` deduplication makes ``DIVIDE X INTO X`` indistinguishable
      from a missing operand -- poison when filtering leaves the wrong
      count, the same documented caveat as ADD/MULTIPLY.
    """
    if stmt.remainder:
        _poison_names([stmt.remainder], index, env)
    if stmt.rounded or stmt.division_mode not in ("BY", "INTO"):
        _poison_names([*stmt.targets, *stmt.givings], index, env)
        return

    if stmt.givings:
        reserved = set(stmt.givings)
        if stmt.remainder:
            reserved.add(stmt.remainder)
        true_operands = [op for op in stmt.operands if op not in reserved]
        if len(true_operands) != 2:
            _poison_names(stmt.givings, index, env)
            return
        values = [_resolve_operand(op, index, env) for op in true_operands]
        first, second = values[0], values[1]
        if first is None or second is None:
            _poison_names(stmt.givings, index, env)
            return
        # DIVIDE a BY b GIVING c -> c = a/b; DIVIDE a INTO b GIVING c -> c = b/a.
        quotient = (
            _exact_divide(first, second)
            if stmt.division_mode == "BY"
            else _exact_divide(second, first)
        )
        if quotient is None:
            _poison_names(stmt.givings, index, env)
            return
        for giving in stmt.givings:
            _write_numeric(giving, quotient, index, env)
        return

    # Format 1: DIVIDE a INTO b [c ...] -- each target := target / a.
    if stmt.division_mode != "INTO":
        _poison_names(stmt.targets, index, env)
        return
    divisor_tokens = [op for op in stmt.operands if op not in stmt.targets]
    if len(divisor_tokens) != 1:
        _poison_names(stmt.targets, index, env)
        return
    divisor = _resolve_operand(divisor_tokens[0], index, env)
    if divisor is None:
        _poison_names(stmt.targets, index, env)
        return
    for target in stmt.targets:
        current = _resolve_operand(target, index, env)
        quotient = _exact_divide(current, divisor) if current is not None else None
        if quotient is None:
            _poison_names([target], index, env)
            continue
        _write_numeric(target, quotient, index, env)


def _fold_compute(
    stmt: ComputeStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.rounded or stmt.expression_tree is None:
        _poison_names(stmt.targets, index, env)
        return
    dmax = _dmax_floor(stmt.expression_tree, stmt.targets, index)
    value = _eval_expr(stmt.expression_tree, index, env, dmax)
    if value is None:
        _poison_names(stmt.targets, index, env)
        return
    for target in stmt.targets:
        _write_numeric(target, value, index, env)


def _operand_decimals(token: str, index: ProgramLayoutIndex) -> int:
    """Decimal places an operand is *defined* with: a literal's written
    digits after the point, a numeric field's PICTURE ``V`` digits, else 0."""
    if _NUMERIC_LITERAL_RE.match(token):
        _, _, fraction = token.partition(".")
        return len(fraction)
    base, _ = _base_name(token)
    resolved = _safe_resolve(index, base)
    if resolved is not None and resolved.spec.category is FieldCategory.NUMERIC:
        return max(int(resolved.spec.decimal_digits), 0)
    return 0


def _dmax_floor(
    tree: CobolExpression, targets: list[str], index: ProgramLayoutIndex
) -> int:
    """A lower bound on IBM's ``dmax`` for one COMPUTE: the most decimal
    places of any result field or of any operand other than a divisor or an
    exponent.

    IBM Enterprise COBOL carries a fixed-point division's intermediate
    quotient to only ``max(d1 - d2, dmax)`` decimal places, *truncating*
    the rest ("Intermediate results and arithmetic precision"), so
    ``COMPUTE N = 7 / 2 * 2`` into ``PIC 99`` stores 6, not 7, and the
    classic ``COMPUTE PCT = A / B * 100`` stores 0 whenever A < B. Every
    leaf under the right-hand side of a ``/`` or ``**`` is left out, which
    can only make the bound smaller than the real ``dmax`` -- a smaller
    bound poisons more, never less, so a quotient with no more decimal
    places than it is one whose truncation was a no-op."""
    floor = 0
    for target in targets:
        base, _ = _base_name(target)
        resolved = _safe_resolve(index, base)
        if resolved is not None:
            floor = max(floor, resolved.spec.decimal_digits)

    stack: list[str | CobolExpression | None] = [tree]
    while stack:
        node = stack.pop()
        if node is None or isinstance(node, FunctionCall):
            continue
        if isinstance(node, str):
            floor = max(floor, _operand_decimals(node, index))
            continue
        if isinstance(node, ArithmeticExpression):
            stack.append(node.left_operand)
            if node.operator not in ("/", "**"):
                stack.append(node.right_operand)
            continue
        if node.expression_type == "OPERAND" and node.operands:
            stack.append(node.operands[0])
    return floor


def _decimal_places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _truncation_free_divide(
    dividend: Decimal, divisor: Decimal, dmax: int
) -> Decimal | None:
    """``_exact_divide``, further gated on IBM's intermediate-quotient
    precision: a quotient needing more than *dmax* decimal places would be
    truncated mid-expression, so it poisons (see ``_dmax_floor``)."""
    quotient = _exact_divide(dividend, divisor)
    if quotient is None or _decimal_places(quotient) > dmax:
        return None
    return quotient


_INTEGER_LITERAL_RE = re.compile(r"^[+-]?\d+$")


def _exponent_kind(
    node: str | CobolExpression | None, index: ProgramLayoutIndex
) -> str:
    """How IBM evaluates ``x ** node`` in fixed point: ``"literal"`` for an
    integer literal (optionally signed), ``"field"`` for a bare integral
    numeric data item, ``"other"`` for anything else (a literal or field with
    decimal places -- evaluated in *floating point* -- or a subexpression)."""
    if isinstance(node, ArithmeticExpression) and node.operator == "NEGATE":
        node = node.right_operand
    if isinstance(node, CobolExpression) and node.expression_type == "OPERAND":
        node = node.operands[0] if node.operands else None
    if isinstance(node, str) and _INTEGER_LITERAL_RE.match(node):
        return "literal"
    return "field" if _is_integral_expression(node, index) else "other"


def _is_integral_expression(
    node: str | CobolExpression | None, index: ProgramLayoutIndex
) -> bool:
    """True when *node* is an integer literal, an integral numeric data item,
    or a ``+ - *`` / non-negative-literal ``**`` combination of those -- an
    exponent IBM evaluates with zero decimal places, so in fixed point."""
    if isinstance(node, str):
        if _INTEGER_LITERAL_RE.match(node):
            return True
        base, _ = _base_name(node)
        resolved = _safe_resolve(index, base)
        return bool(
            resolved is not None
            and resolved.spec.category is FieldCategory.NUMERIC
            and resolved.spec.decimal_digits == 0
            and not resolved.spec.scaling_positions
        )
    if isinstance(node, ArithmeticExpression):
        if node.operator == "NEGATE":
            return _is_integral_expression(node.right_operand, index)
        if node.operator in ("+", "-", "*"):
            return _is_integral_expression(
                node.left_operand, index
            ) and _is_integral_expression(node.right_operand, index)
        if node.operator == "**":
            exponent = node.right_operand
            return (
                isinstance(exponent, str)
                and exponent.isdigit()
                and _is_integral_expression(node.left_operand, index)
            )
        return False
    if isinstance(node, CobolExpression) and node.expression_type == "OPERAND":
        return bool(node.operands) and _is_integral_expression(node.operands[0], index)
    return False


def _fold_power(
    base: Decimal,
    exponent_value: Decimal,
    exponent_node: str | CobolExpression | None,
    index: ProgramLayoutIndex,
    dmax: int,
) -> Decimal | None:
    """``base ** exponent`` under IBM's fixed-point exponentiation rules
    ("Fixed-point data and intermediate results"):

    * an integer-literal exponent n >= 0 carries ``d1 * n`` decimal places
      -- the exact power;
    * a negative one is ``1 / (base ** |n|)`` evaluated under the *division*
      rules, so the quotient is truncated to ``dmax`` places;
    * an integral data-name exponent carries only ``dmax`` decimal places;
    * an exponent with decimal places switches the whole evaluation to
      floating point, which this module does not model -- poisoned.

    Every truncating case poisons unless the exact value already fits in
    ``dmax`` places (the truncation was a no-op)."""
    if exponent_value != exponent_value.to_integral_value():
        return None
    kind = _exponent_kind(exponent_node, index)
    if kind == "other":
        return None
    exponent = int(exponent_value)
    if exponent < 0:
        return _truncation_free_divide(Decimal(1), base**-exponent, dmax)
    power = base**exponent
    if kind == "field" and _decimal_places(power) > dmax:
        return None
    return power


def _eval_expr(
    node: str | CobolExpression | None,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
    dmax: int = 0,
) -> Decimal | None:
    if node is None:
        return None
    if isinstance(node, str):
        return _resolve_operand(node, index, env)
    if isinstance(node, FunctionCall):
        return None  # intrinsic functions are not folded in v1
    if isinstance(node, ArithmeticExpression):
        if node.operator == "NEGATE":
            right = _eval_expr(node.right_operand, index, env, dmax)
            return -right if right is not None else None
        left = _eval_expr(node.left_operand, index, env, dmax)
        right = _eval_expr(node.right_operand, index, env, dmax)
        if left is None or right is None:
            return None
        try:
            if node.operator == "+":
                return left + right
            if node.operator == "-":
                return left - right
            if node.operator == "*":
                return left * right
            if node.operator == "/":
                # `_exact_divide`, not a bare `/`: the ambient decimal
                # context silently rounds an inexact quotient to its own
                # precision, and a quotient rounded that way can come back
                # looking clean enough to pass `_fits_exactly` -- which is
                # the one gate standing between this module and a fabricated
                # answer.  `COMPUTE X = 3 / 0.3333333333333333333333333333334`
                # is just under 9, rounds to exactly 9 at 28 digits, and was
                # recorded as 9 where COBOL stores 8.999999999.  The
                # multiply-back check inside `_exact_divide` (already used by
                # `_fold_divide`) rejects exactly that case, so every DIVIDE
                # shape and every `/` in a COMPUTE now hold the same contract.
                # ...and a quotient IBM truncates to `dmax` decimal places
                # before the rest of the expression sees it poisons too.
                return _truncation_free_divide(left, right, dmax)
            if node.operator == "**":
                return _fold_power(left, right, node.right_operand, index, dmax)
        except (ArithmeticError, ValueError):
            # ArithmeticError covers decimal's own exception hierarchy
            # (InvalidOperation, DivisionByZero, Overflow, ...) as well as
            # the builtin OverflowError -- an extreme exponent (`2 ** 9999`)
            # or similar is poisoned rather than left to crash the walk.
            return None
        return None
    # `CobolExpression("OPERAND", ...)` wrapper around a single bare operand
    # (e.g. `COMPUTE X = A`) -- see `_ExpressionTreeParser.parse`.
    if node.expression_type == "OPERAND" and node.operands:
        return _resolve_operand(node.operands[0], index, env)
    return None


# -- fit-checking and rendering ------------------------------------------------


def _fits_exactly(value: Decimal, spec: FieldSpec) -> bool:
    """True only when *value* needs no rounding, truncation, or sign
    coercion to be stored in *spec* -- the "exact by construction" gate
    every numeric write goes through."""
    if spec.category is not FieldCategory.NUMERIC:
        return False
    if spec.scaling_positions:
        # A P-scaled field stores only some of the digits its value shows
        # (``9(3)PPP`` keeps 123 of 123456); truncation rules not modeled.
        return False
    if not value.is_finite():
        return False
    if value < 0 and not spec.is_signed:
        return False
    # Decided over `Fraction`, not `Decimal`. This is the one gate between
    # this module and a fabricated answer, and decimal arithmetic runs in
    # the ambient context: a value carrying more precision than that context
    # (anything out of `_exact_divide`'s 80-digit block) was silently
    # rounded by the very `abs()` and `*` used to test it, so a quotient of
    # 8.999...9982 arrived here already rounded to 9 and passed as exact.
    # A rational has no precision to round to.
    magnitude = abs(Fraction(value))
    if (magnitude * 10**spec.decimal_digits).denominator != 1:
        return False
    # bool(): Fraction's rich comparisons are untyped, so mypy reads the
    # comparison as Any under `disallow_any_return`.
    return bool(magnitude < 10**spec.integer_digits)


def _render_numeric(value: Decimal, spec: FieldSpec) -> str:
    magnitude = abs(value)
    text = (
        f"{magnitude:.{spec.decimal_digits}f}"
        if spec.decimal_digits
        else str(int(magnitude))
    )
    return f"-{text}" if value < 0 and magnitude != 0 else text


def _render(value: Decimal | str, spec: FieldSpec) -> str:
    if isinstance(value, Decimal):
        return _render_numeric(value, spec)
    return value


def _seed_value(raw: str, spec: FieldSpec) -> Decimal | str | None:
    """Type a mock-generated fixture cell for use as an initial env value.
    Fixture cells are already PICTURE-valid (via `ValueFactory`), so this is
    a straight parse, not a fit-check."""
    if spec.category is FieldCategory.NUMERIC:
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    if spec.category in _TEXT_CATEGORIES:
        return raw
    return None  # NUMERIC_EDITED / ALPHANUMERIC_EDITED / FLOAT: not modeled


__all__ = ["ConstantFoldResult", "ConstantFolder"]
