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
* ``DIVIDE`` is poisoned unconditionally: the AST does not record whether
  ``BY`` or ``INTO`` was used, and the two invert dividend/divisor order, so
  there is no way to compute the correct value from the node alone. A ``/``
  inside a COMPUTE expression tree has no such ambiguity (both operands are
  explicit) and folds normally.
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
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

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
        for name, raw in (seed_values or {}).items():
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
        state = _WalkState(env=env)
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
    __slots__ = ("env", "observed", "stopped")

    def __init__(self, env: dict[str, Decimal | str]) -> None:
        self.env = env
        self.observed: set[str] = set()
        self.stopped = False


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
            _poison_written_names(body, index, state.env, by_name, ordered_names)
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
        # See module docstring: BY vs INTO is not recoverable from the AST.
        _poison_names([*stmt.targets, *stmt.givings], index, state.env)
    elif isinstance(stmt, ComputeStatement):
        _fold_compute(stmt, index, state.env)
    elif isinstance(stmt, DisplayStatement):
        for item in stmt.display_items:
            _mark_observed(item, index, state)
    elif isinstance(stmt, IOWriteStatement):
        if stmt.record_name:
            _mark_observed(stmt.record_name, index, state)
    elif isinstance(stmt, (IOAcceptStatement, IOReadStatement)):
        # A deliberate no-op, not an omission: ACCEPT/READ are exactly the
        # boundary categories `_tier2_expectations` (program_fixtures.py)
        # seeds `env` from before the walk starts, using the scenario's own
        # mock-supplied value. Falling through to the generic "unmodeled
        # write" fallback below would poison that seed the instant the walk
        # reached the very statement it represents -- self-defeating. A
        # field with no seed simply stays absent from `env`, which is
        # already "unknown"; there is nothing to poison either way.
        # CALL/EXEC SQL/CICS/DLI are NOT given the same treatment: their
        # operand lists mix genuinely-unknowable OUT-direction values with
        # seedable IN ones, and the raw AST does not carry resolved
        # direction to tell them apart (only `BoundaryInventoryAnalyzer`'s
        # own richer analysis does) -- deferred to a future version rather
        # than risk treating an OUT value as still-known.
        pass
    elif isinstance(stmt, PerformStatement):
        return _walk_perform(stmt, index, by_name, ordered_names, state)
    elif isinstance(stmt, IfStatement):
        _poison_written_names(
            stmt.then_statements, index, state.env, by_name, ordered_names
        )
        _poison_written_names(
            stmt.else_statements, index, state.env, by_name, ordered_names
        )
    elif isinstance(stmt, EvaluateStatement):
        for wc in stmt.when_clauses:
            _poison_written_names(
                wc.statements, index, state.env, by_name, ordered_names
            )
        if stmt.default_when:
            _poison_written_names(
                stmt.default_when.statements, index, state.env, by_name, ordered_names
            )
    elif isinstance(stmt, (GoStatement, StopStatement, GobackStatement)):
        state.stopped = True
    elif isinstance(stmt, ExitStatement) and stmt.exit_type == "PROGRAM":
        state.stopped = True
    else:
        # Unmodeled statement type: conservatively poison every name it
        # references rather than risk a stale, now-incorrect env entry
        # surviving an unrecognized write (INITIALIZE, SET, STRING,
        # UNSTRING, INSPECT, ACCEPT, CALL, SQL/CICS/DLI host variables, ...).
        _poison_names(list(getattr(stmt, "operands", [])), index, state.env)
    return None


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
        body = stmt.inline_statements or _perform_body_statements(
            stmt, by_name, ordered_names
        )
        _poison_written_names(body, index, state.env, by_name, ordered_names)
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
    if isinstance(
        stmt, (AddStatement, SubtractStatement, MultiplyStatement, DivideStatement)
    ):
        return [*stmt.targets, *stmt.givings]
    if isinstance(stmt, ComputeStatement):
        return list(stmt.targets)
    if isinstance(stmt, IOReadStatement) and stmt.into_target:
        return [stmt.into_target]
    if isinstance(stmt, CallStatement):
        names = [p.name for p in stmt.using_parameters]
        if stmt.returning_parameter:
            names.append(stmt.returning_parameter)
        if stmt.giving_parameter:
            names.append(stmt.giving_parameter)
        return names
    return list(getattr(stmt, "operands", []))


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
        _poison_names(_write_targets(stmt), index, env)
        for nested in _nested_statement_lists(stmt):
            _poison_written_names(nested, index, env, by_name, ordered_names, visiting)


# -- MOVE ----------------------------------------------------------------------


def _fold_move(
    stmt: MoveStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.is_corresponding:
        _poison_names(stmt.targets, index, env)
        return
    source = _resolve_move_source(stmt.source, index, env) if stmt.source else None
    for target in stmt.targets:
        _apply_move_target(target, source, index, env)


def _resolve_move_source(
    source: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> tuple[str, Decimal | str] | None:
    if _NUMERIC_LITERAL_RE.match(source):
        try:
            return ("numeric", Decimal(source))
        except InvalidOperation:
            return None
    quoted = _QUOTED_LITERAL_RE.match(source)
    if quoted:
        return ("text", quoted.group(2))
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
) -> None:
    resolved = _safe_resolve(index, target_name)
    if resolved is None:
        return
    qname = resolved.spec.qualified_name
    if source is None:
        env.pop(qname, None)
        return
    kind, value = source
    if kind == "numeric" and isinstance(value, Decimal):
        if resolved.spec.category is FieldCategory.NUMERIC and _fits_exactly(
            value, resolved.spec
        ):
            env[qname] = value
        else:
            env.pop(qname, None)
    elif kind == "text" and isinstance(value, str):
        if resolved.spec.category in _TEXT_CATEGORIES:
            size = resolved.spec.size if resolved.spec.size > 0 else len(value)
            env[qname] = value[:size]
        else:
            env.pop(qname, None)
    else:
        env.pop(qname, None)


# -- arithmetic ------------------------------------------------------------


def _resolve_operand(
    token: str, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> Decimal | None:
    if _NUMERIC_LITERAL_RE.match(token):
        try:
            return Decimal(token)
        except InvalidOperation:
            return None
    resolved = _safe_resolve(index, token)
    if resolved is None:
        return None
    value = env.get(resolved.spec.qualified_name)
    return value if isinstance(value, Decimal) else None


def _poison_names(
    names: list[str], index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    for name in names:
        resolved = _safe_resolve(index, name)
        if resolved is not None:
            env.pop(resolved.spec.qualified_name, None)


def _write_numeric(
    name: str, value: Decimal, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    resolved = _safe_resolve(index, name)
    if resolved is None:
        return
    if resolved.spec.category is FieldCategory.NUMERIC and _fits_exactly(
        value, resolved.spec
    ):
        env[resolved.spec.qualified_name] = value
    else:
        env.pop(resolved.spec.qualified_name, None)


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
    operand in place -- `_fold_giving_form` (via `base`, below) separately
    reads the (at most one, in standard grammar) TO/FROM operand's own
    current value, so filtering `.operands` by target/giving names to get
    the addend list is the right general shape. But a well-formed ADD/
    SUBTRACT always has >= 1 real addend (parser-enforced), so if that
    filter empties the list entirely, every addend token coincided with a
    target/giving name -- `.operands` deduplicates on insertion, so
    "``ADD X TO X GIVING Y`` really lists X twice" is indistinguishable
    from "X was never a separate addend" without this check. A *partial*
    overlap (`ADD X, Z TO X GIVING Y`) is not caught and silently
    undercounts -- narrower and rarer, and documented here rather than
    silently."""
    reserved = set(stmt.targets) | set(stmt.givings)
    addend_tokens = [op for op in stmt.operands if op not in reserved]
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
    sum(addends)`. A target's own name is *expected* to appear in
    `.operands` regardless of any real overlap (`set_target` always ends up
    adding it there, see the module's arithmetic-operand notes) -- checking
    for that would fire on every ordinary `ADD 1 TO WS-X`, not just a
    genuine self-reference. The one case worth catching: a well-formed
    ADD/SUBTRACT always has >= 1 real addend, so if removing target names
    from `.operands` leaves nothing at all, every addend token coincided
    with a target -- `ADD X TO X` doubles X, but `.operands` deduplication
    makes that indistinguishable from "no real addend at all" without this
    check. A *partial* overlap (`ADD X, Y TO X`) is not caught and silently
    undercounts -- narrower and rarer, and documented here rather than
    silently."""
    addend_tokens = [op for op in stmt.operands if op not in stmt.targets]
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


def _fold_compute(
    stmt: ComputeStatement, index: ProgramLayoutIndex, env: dict[str, Decimal | str]
) -> None:
    if stmt.rounded or stmt.expression_tree is None:
        _poison_names(stmt.targets, index, env)
        return
    value = _eval_expr(stmt.expression_tree, index, env)
    if value is None:
        _poison_names(stmt.targets, index, env)
        return
    for target in stmt.targets:
        _write_numeric(target, value, index, env)


def _eval_expr(
    node: str | CobolExpression | None,
    index: ProgramLayoutIndex,
    env: dict[str, Decimal | str],
) -> Decimal | None:
    if node is None:
        return None
    if isinstance(node, str):
        return _resolve_operand(node, index, env)
    if isinstance(node, FunctionCall):
        return None  # intrinsic functions are not folded in v1
    if isinstance(node, ArithmeticExpression):
        if node.operator == "NEGATE":
            right = _eval_expr(node.right_operand, index, env)
            return -right if right is not None else None
        left = _eval_expr(node.left_operand, index, env)
        right = _eval_expr(node.right_operand, index, env)
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
                return None if right == 0 else left / right
            if node.operator == "**":
                if right == right.to_integral_value():
                    return left ** int(right)
                return None
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
    if value < 0 and not spec.is_signed:
        return False
    magnitude = abs(value)
    scaled = magnitude * (Decimal(10) ** spec.decimal_digits)
    if scaled != scaled.to_integral_value():
        return False
    ceiling = Decimal(10) ** spec.integer_digits
    return magnitude < ceiling


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
