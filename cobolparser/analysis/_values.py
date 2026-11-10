"""Which outcomes of an ``IF`` the values a program can hold never take.

The value side of :class:`~cobolparser.analysis.input_dependence.
InputDependenceAnalyzer`: a forward pass over the same context-expanded
control-flow graph, carrying the bytes of WORKING-STORAGE (and
LOCAL-STORAGE) as far as they are known. Each PERFORM is followed with the
values it is called with and returns to its own call site (the pass keeps a
stack of return points), so a shared paragraph such as a validation
program's ``PRINT-DETAIL`` is judged once per call, not on the mix of all
of them. An ``IF`` whose condition follows from the bytes it reads sends a
state down one branch only, so ``BAIL-OUT`` (run only when ``P-OR-F`` is not
``"FAIL*"``) sees the states of the passing tests and nothing else.

Exact by construction, or absent:

* A byte is either known or unknown. Storage starts as its VALUE clauses
  say (a byte without one -- FILLER included, since nothing resets it
  between test cases -- is unknown), and only a MOVE or ADD / SUBTRACT this
  module can follow byte for byte writes a known value; every other write
  makes what it may touch unknown, whole 01 records at a time.
* Records nothing tracks: FILE, LINKAGE, COMMUNICATION and SCREEN records,
  EXTERNAL and GLOBAL items, everything the analyzer seeds as input (FILE
  STATUS fields, registers), anything a caller sets from outside
  (``extra_inputs``), anything an ``ADDRESS OF`` names, anything code that
  DECLARATIVES reach writes, and any record whose layout this module cannot
  lay out exactly (SYNCHRONIZED, OCCURS DEPENDING ON, unknown usages).
* Only DISPLAY data is read: alphanumeric items and groups as text, unsigned
  zoned decimals as numbers. A comparison is decided only when its answer
  cannot depend on the collating sequence: equality between texts, any
  relation between numbers, level-88 tests built from those.
* States meeting at one point with one return stack are kept apart up to a
  small number, then merged byte by byte (a byte two states disagree on
  becomes unknown), which is what makes loops terminate.
* A budget bounds the work; past it, or on anything the graph does not
  explain (a return with no matching call), the pass claims nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from .._literals import unquote_literal
from .._storage import storage_size
from .._vocabulary import ZERO_WORDS
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.arithmetic import AddStatement, SubtractStatement
from ..models.statements.base import ConditionalExpression, LogicalExpression
from ..models.statements.control import IfStatement
from ..models.statements.data import MoveStatement

if TYPE_CHECKING:
    from .input_dependence import _Graph, _Records

#: The byte standing for "unknown". A literal holding it is not followed.
UNKNOWN = "\x00"
#: A byte known to hold a digit ("0" to "9"), but not which one: what a
#: numeric-edited ``9`` position always holds, and what two digits merge
#: to.
DIGIT = "\x01"
_DIGITS = frozenset("0123456789" + DIGIT)
#: States kept apart at one (node, return stack); past it a new state is
#: merged into the one it differs least from.
MAX_STATES_PER_POINT = 16
#: How much more a byte some condition reads weighs when choosing which
#: states to merge.
_TESTED_WEIGHT = 1000
#: State transitions before the pass gives up and claims nothing.
MAX_STEPS = 400_000
#: Return-stack depth past which the pass gives up (recursive PERFORMs).
MAX_DEPTH = 64

_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(\d+)(?:\.(\d+))?$")
_QUOTED_RE = re.compile(r'^(["\'])(.*)\1$', re.DOTALL)
_ALL_RE = re.compile(r"^ALL\s+(.+)$", re.IGNORECASE | re.DOTALL)
_QUALIFIER_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)
_FIGURATIVE_FILL = {
    "SPACE": " ",
    "SPACES": " ",
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
    "QUOTE": '"',
    "QUOTES": '"',
    "HIGH-VALUE": "\xff",
    "HIGH-VALUES": "\xff",
}
_ZERO_WORDS = ZERO_WORDS
_RELATIONS = {
    "EQUAL": lambda a, b: a == b,
    "NOT_EQUAL": lambda a, b: a != b,
    "GREATER": lambda a, b: a > b,
    "LESS": lambda a, b: a < b,
    "GREATER_OR_EQUAL": lambda a, b: a >= b,
    "LESS_OR_EQUAL": lambda a, b: a <= b,
}
_SIGNS = {
    "POSITIVE": lambda v: v > 0,
    "NEGATIVE": lambda v: v < 0,
    "ZERO": lambda v: v == 0,
    "ZEROS": lambda v: v == 0,
    "ZEROES": lambda v: v == 0,
}
_TRACKED_SECTIONS = frozenset({"WORKING-STORAGE", "LOCAL-STORAGE"})

#: kinds of a laid-out item
_TEXT, _NUM, _OPAQUE = "text", "num", "opaque"

Env = dict[str, str]
_Operand = tuple[str, Any]  # ("text", str) | ("num", Decimal) | ("fill", char)


class _Field:
    __slots__ = ("root", "offset", "length", "kind", "scale", "in_table", "item")

    def __init__(
        self,
        root: str,
        offset: int,
        length: int,
        kind: str,
        scale: int,
        in_table: bool,
        item: CobolDataItem,
    ) -> None:
        self.root = root
        self.offset = offset
        self.length = length
        self.kind = kind
        self.scale = scale
        self.in_table = in_table
        self.item = item


class _Layout:
    """Byte layout of every record the pass tracks, and name lookup."""

    def __init__(self, ast: CobolProgram, records: _Records) -> None:
        self.fields: dict[int, _Field] = {}
        self.by_name: dict[str, list[CobolDataItem]] = {}
        self.parent: dict[int, CobolDataItem | None] = {}
        self.conditions: dict[str, list[tuple[ConditionNameItem, CobolDataItem]]] = {}
        self.initial: Env = {}
        self.length: dict[str, int] = {}
        self.untracked: set[str] = set()
        #: FILLER items with a VALUE: (root, offset, bytes). Nothing resets
        #: a FILLER between test cases, so the pass trusts one only while no
        #: write can store anything else there (see `ValuePass.run`).
        self.fillers: list[tuple[str, int, str]] = []
        data = ast.data_division
        if data is None:
            return
        for section in data.sections:
            if not isinstance(section, CobolSection):
                continue
            kind = (section.section_name or "").upper()
            for item in section.data_items:
                root = records.root_of_item.get(id(item))
                self._index_names(item, None)
                if root is None:
                    continue
                if kind not in _TRACKED_SECTIONS or not self._lay_record(item, root):
                    self.untracked.add(root)

    def _index_names(self, item: CobolDataItem, parent: CobolDataItem | None) -> None:
        self.parent[id(item)] = parent
        if item.name and not item.is_filler:
            self.by_name.setdefault(item.name.upper(), []).append(item)
        for child in item.children:
            if isinstance(child, ConditionNameItem) and child.name:
                self.conditions.setdefault(child.name.upper(), []).append((child, item))
            elif isinstance(child, CobolDataItem) and child.level != 77:
                self._index_names(child, item)

    def _lay_record(self, item: CobolDataItem, root: str) -> bool:
        if item.is_external or item.is_global:
            return False
        if item.redefines and item.level in (1, 77):
            # Shares the redefined record's storage, from byte 0.
            pass
        initial = list(self.initial.get(root, ""))
        size = self._lay(item, root, 0, False, initial)
        if size is None:
            return False
        if len(initial) < size:
            initial.extend(UNKNOWN * (size - len(initial)))
        self.initial[root] = "".join(initial)
        self.length[root] = max(self.length.get(root, 0), size)
        return True

    def _lay(
        self,
        item: CobolDataItem,
        root: str,
        offset: int,
        in_table: bool,
        initial: list[str],
    ) -> int | None:
        """Lay *item* out at *offset*; its length, or None when not exact."""
        if item.synchronized:
            return None
        occurs = item.occurs_clause
        times = 1
        if occurs is not None:
            if occurs.depending_on or occurs.is_unbounded or not occurs.max_times:
                return None
            times = occurs.max_times
            in_table = True
        children = [
            c for c in item.children if isinstance(c, CobolDataItem) and c.level != 77
        ]
        if children:
            cursor = offset
            end = offset
            starts: dict[str, int] = {}
            for child in children:
                if child.redefines:
                    start = starts.get(child.redefines.upper())
                    if start is None:
                        return None
                    length = self._lay(child, root, start, in_table, initial)
                    if length is None:
                        return None
                    end = max(end, start + length)
                    continue
                if child.name:
                    starts[child.name.upper()] = cursor
                length = self._lay(child, root, cursor, in_table, initial)
                if length is None:
                    return None
                cursor += length
                end = max(end, cursor)
            one = end - offset
            kind, scale = _TEXT, 0
        else:
            pic = item.picture_clause
            try:
                one = storage_size(
                    item.usage,
                    picture_size=pic.size if pic else None,
                    total_digits=pic.total_digits if pic else None,
                    sign_clause=item.sign_clause,
                    is_signed=bool(pic and pic.is_signed),
                    national_picture=bool(pic and pic.is_national),
                )
            except (ValueError, KeyError, TypeError):
                return None
            if not one or one < 0:
                return None
            kind, scale = _elementary_kind(item)
        self.fields[id(item)] = _Field(root, offset, one, kind, scale, in_table, item)
        if not children and not in_table and not item.redefines:
            value = _initial_bytes(item, one, kind, scale)
            if value is not None and item.is_filler:
                self.fillers.append((root, offset, value))
            elif value is not None:
                if len(initial) < offset + one:
                    initial.extend(UNKNOWN * (offset + one - len(initial)))
                initial[offset : offset + one] = list(value)
        return one * times

    # -- lookup ---------------------------------------------------------------

    def resolve(self, name: str) -> _Field | None:
        """The one tracked item *name* means, without subscript or
        reference modification; None otherwise."""
        if "(" in name or ":" in name:
            return None
        parts = [p.strip().upper() for p in _QUALIFIER_RE.split(name.strip())]
        if not parts or not parts[0]:
            return None
        found = [
            item
            for item in self.by_name.get(parts[0], [])
            if self._qualified_by(item, parts[1:])
        ]
        if len(found) != 1:
            return None
        field = self.fields.get(id(found[0]))
        if field is None or field.root in self.untracked or field.in_table:
            return None
        return field

    def _qualified_by(self, item: CobolDataItem, qualifiers: list[str]) -> bool:
        node = self.parent.get(id(item))
        for qualifier in qualifiers:
            while node is not None and (node.name or "").upper() != qualifier:
                node = self.parent.get(id(node))
            if node is None:
                return False
            node = self.parent.get(id(node))
        return True


def _elementary_kind(item: CobolDataItem) -> tuple[str, int]:
    pic = item.picture_clause
    if pic is None or (item.usage or "DISPLAY").upper() != "DISPLAY":
        return _OPAQUE, 0
    if pic.is_edited or pic.is_national or item.justified:
        return _OPAQUE, 0
    pattern = pic.pattern.upper()
    if pic.total_digits:
        if pic.is_signed or pic.has_scaling_factor or "P" in pattern:
            return _OPAQUE, 0
        if pic.size != pic.total_digits:
            return _OPAQUE, 0
        return _NUM, pic.decimal_digits or 0
    if set(re.sub(r"\(\d+\)", "", pattern)) <= {"X", "A"}:
        return _TEXT, 0
    return _OPAQUE, 0


def _edited_display(item: CobolDataItem) -> bool:
    """A DISPLAY numeric-edited item: compared as the text it holds."""
    pic = item.picture_clause
    return bool(
        pic is not None
        and pic.is_numeric_edited
        and (item.usage or "DISPLAY").upper() == "DISPLAY"
    )


def _initial_bytes(
    item: CobolDataItem, length: int, kind: str, scale: int
) -> str | None:
    if not item.value_clause:
        return None
    raw = item.value_clause.strip()
    if kind == _TEXT:
        return _text_fill(raw, length)
    if kind == _NUM:
        value = _numeric_literal(raw)
        if value is None and raw.upper() in _ZERO_WORDS:
            value = Decimal(0)
        return None if value is None else _render_num(value, length, scale, exact=True)
    return None


def _numeric_literal(text: str) -> Decimal | None:
    if not _NUMERIC_LITERAL_RE.match(text.strip()):
        return None
    try:
        return Decimal(text.strip())
    except InvalidOperation:  # pragma: no cover - the regex admits only numbers
        return None


def _text_literal(text: str) -> str | None:
    match = _QUOTED_RE.match(text.strip())
    if not match:
        return None
    value = unquote_literal(text.strip())
    return None if UNKNOWN in value or DIGIT in value else value


def _text_fill(raw: str, length: int) -> str | None:
    """The bytes a text item of *length* holds after VALUE / MOVE *raw* (a
    literal or figurative constant); None when not followed."""
    upper = raw.strip().upper()
    fill = _FIGURATIVE_FILL.get(upper)
    if fill is not None:
        return fill * length
    match = _ALL_RE.match(raw.strip())
    if match:
        inner = match.group(1).strip()
        pattern = _text_literal(inner)
        if pattern is None:
            pattern = _FIGURATIVE_FILL.get(inner.upper())
        if not pattern:
            return None
        return (pattern * (length // len(pattern) + 1))[:length]
    text = _text_literal(raw)
    if text is None:
        return None
    return text[:length].ljust(length)


def _expand_picture(pattern: str) -> str | None:
    """A PICTURE string with its repeat counts written out and the symbols
    that take no byte (V, P, S) dropped; None when it uses anything else
    this module does not lay out (currency strings, national)."""
    out: list[str] = []
    text = pattern.upper()
    i = 0
    while i < len(text):
        c = text[i]
        count = 1
        if i + 1 < len(text) and text[i + 1] == "(":
            end = text.find(")", i)
            if end < 0 or not text[i + 2 : end].isdigit():
                return None
            count = int(text[i + 2 : end])
            i = end + 1
        else:
            i += 1
        if c in "VPS":
            continue
        if c == "C" and text[i : i + 1] == "R" or c == "D" and text[i : i + 1] == "B":
            out.append(c + text[i])
            i += 1
            continue
        if c not in "9Z*+-.,/0B$X":
            return None
        out.append(c * count)
    return "".join(out)


def _render_num(value: Decimal, length: int, scale: int, *, exact: bool) -> str | None:
    """Zoned digits of an unsigned DISPLAY item holding *value*. A MOVE
    truncates (high-order integer digits, low-order decimals); with *exact*
    a value that does not fit is not followed."""
    if value < 0:
        return None
    scaled = value.scaleb(scale)
    whole = int(scaled)
    if exact and (whole != scaled or whole >= 10**length):
        return None
    whole %= 10**length
    return str(whole).rjust(length, "0")


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


class ValuePass:
    """Runs the pass; :meth:`run` returns ``{id(IF statement): outcomes no
    state took}`` for every IF some state reached, or None when the pass
    gave up."""

    def __init__(
        self,
        ast: CobolProgram,
        graph: _Graph,
        records: _Records,
        call_entries: dict[int, list[tuple[int, int]]],
        untracked_roots: Iterable[str],
    ) -> None:
        self.graph = graph
        self.records = records
        self.layout = _Layout(ast, records)
        self.call_entries = call_entries
        self.untracked = set(self.layout.untracked) | set(untracked_roots)
        self.untracked |= set(records.seeds)
        self.layout.untracked = self.untracked
        self.steps = 0
        self.tested = self._tested_bytes()
        self.abbreviated = {
            id(stmt)
            for stmt in graph.node_stmt.values()
            if isinstance(stmt, IfStatement) and _maybe_abbreviated(stmt.condition)
        }
        # Storage no condition reads, directly or through what is MOVEd or
        # added from it, cannot decide anything: leaving it untracked keeps
        # states that differ only in a line counter from multiplying.
        relevant = set(self.tested)
        modeled = [
            stmt
            for stmt in graph.node_stmt.values()
            if isinstance(stmt, (MoveStatement, AddStatement, SubtractStatement))
        ]
        changed = True
        while changed:
            changed = False
            for stmt in modeled:
                if records.roots_written(stmt) & relevant:
                    more = records.roots_named(stmt) - relevant
                    if more:
                        relevant |= more
                        changed = True
        self.untracked |= set(self.layout.initial) - relevant
        self.untracked |= set(self.layout.length) - relevant

    def _tested_bytes(self) -> dict[str, frozenset[int]]:
        """Root -> byte positions some IF condition reads."""
        out: dict[str, set[int]] = {}
        for stmt in self.graph.node_stmt.values():
            if not isinstance(stmt, IfStatement):
                continue
            stack = [stmt.condition]
            while stack:
                expr = stack.pop()
                if isinstance(expr, LogicalExpression):
                    stack.extend([expr.left_condition, expr.right_condition])
                    continue
                if not isinstance(expr, ConditionalExpression):
                    continue
                for operand in (expr.left_operand, expr.right_operand):
                    if not isinstance(operand, str):
                        continue
                    field = self.layout.resolve(operand)
                    if field is None and (expr.operator or "").upper() == (
                        "CONDITION_NAME"
                    ):
                        conds = self.layout.conditions.get(operand.strip().upper())
                        if conds and len(conds) == 1:
                            field = self.layout.fields.get(id(conds[0][1]))
                    if field is not None:
                        out.setdefault(field.root, set()).update(
                            range(field.offset, field.offset + field.length)
                        )
        return {root: frozenset(v) for root, v in out.items()}

    # -- driver ---------------------------------------------------------------

    def run(self) -> dict[int, set[int]] | None:
        """Run to a fixpoint. FILLER VALUEs are trusted first; any FILLER a
        write could change is then distrusted and the pass runs again."""
        trusted = {
            i
            for i, (root, _, _) in enumerate(self.layout.fillers)
            if root not in self.untracked
        }
        for _attempt in range(8):
            self.violated: set[int] = set()
            self._trusted = trusted
            self._fillers_of: dict[str, list[int]] = {}
            for i in trusted:
                self._fillers_of.setdefault(self.layout.fillers[i][0], []).append(i)
            found = self._run_once()
            if found is None or not self.violated:
                return found
            trusted = trusted - self.violated
        return None

    def _run_once(self) -> dict[int, set[int]] | None:
        graph = self.graph
        if not graph.roots:
            return {}
        initial = dict(self.layout.initial)
        for i in self._trusted:
            root, offset, value = self.layout.fillers[i]
            record = initial.get(root)
            if record is None:
                continue
            initial[root] = record[:offset] + value + record[offset + len(value) :]
        env0 = {
            root: value
            for root, value in initial.items()
            if root not in self.untracked and value.count(UNKNOWN) != len(value)
        }
        self.steps = 0
        taken: dict[int, set[int]] = {}
        reached: set[int] = set()
        points: dict[tuple[int, tuple[int, ...]], list[_Kept]] = {}
        indegree = [0] * len(graph.succ)
        for outs in graph.succ:
            for target, _ in outs:
                indegree[target] += 1
        joins = {n for n, count in enumerate(indegree) if count > 1}
        joins.add(graph.roots[0])
        work: list[tuple[int, tuple[int, ...], Env]] = [(graph.roots[0], (), env0)]
        while work:
            node, stack, env = work.pop()
            self.steps += 1
            if self.steps > MAX_STEPS:
                return None
            if node not in joins:
                # States are only compared where paths meet: every cycle
                # passes such a point, so the pass still terminates.
                nxt = self._step(node, stack, env, taken, reached)
                if nxt is None:
                    return None
                work.extend(nxt)
                continue
            admitted = _admit(points.setdefault((node, stack), []), env, self.tested)
            if admitted is None:
                continue
            env = admitted
            nxt = self._step(node, stack, env, taken, reached)
            if nxt is None:
                return None
            work.extend(nxt)
        out: dict[int, set[int]] = {}
        for stmt_id in reached:
            missing = {0, 1} - taken.get(stmt_id, set())
            out[stmt_id] = missing
        return out

    def _step(
        self,
        node: int,
        stack: tuple[int, ...],
        env: Env,
        taken: dict[int, set[int]],
        reached: set[int],
    ) -> list[tuple[int, tuple[int, ...], Env]] | None:
        graph = self.graph
        if node in graph.ret_of:
            if not stack:
                return []  # a range end no PERFORM of the pass reached
            back = stack[-1]
            if not any(target == back for target, _ in graph.succ[node]):
                return None
            return [(back, stack[:-1], env)]
        stmt = graph.node_stmt.get(node)
        verdict: bool | None = None
        if stmt is not None:
            if isinstance(stmt, IfStatement):
                reached.add(id(stmt))
                verdict = (
                    self._decide(stmt.condition, env)
                    if id(stmt) not in self.abbreviated
                    else None
                )
                outcomes = {0, 1} if verdict is None else {0 if verdict else 1}
                taken.setdefault(id(stmt), set()).update(outcomes)
            else:
                env = self._transfer(stmt, env)
        out: list[tuple[int, tuple[int, ...], Env]] = []
        entries = dict(self.call_entries.get(node, []))
        for target, outcome in graph.succ[node]:
            if verdict is not None and outcome in (0, 1):
                if outcome != (0 if verdict else 1):
                    continue
            after = entries.get(target)
            if after is not None:
                if len(stack) >= MAX_DEPTH:
                    return None
                out.append((target, (*stack, after), env))
            else:
                out.append((target, stack, env))
        return out

    # -- writes ---------------------------------------------------------------

    def _forget_roots(self, env: Env, roots: Iterable[str]) -> Env:
        roots = list(roots)
        for root in roots:
            self.violated.update(self._fillers_of.get(root, ()))
        drop = [r for r in roots if r in env]
        if not drop:
            return env
        env = dict(env)
        for root in drop:
            del env[root]
        return env

    def _forget_names(self, env: Env, names: Iterable[str]) -> Env:
        roots: set[str] = set()
        for name in names:
            roots |= self.records.roots_of_name(name)
        return self._forget_roots(env, roots)

    def _transfer(self, stmt: Any, env: Env) -> Env:
        if isinstance(stmt, MoveStatement) and not stmt.is_corresponding:
            for target in stmt.targets:
                env = self._move(stmt.source, target, env)
            return env
        if (
            isinstance(stmt, (AddStatement, SubtractStatement))
            and not stmt.rounded
            and not stmt.is_corresponding
        ):
            return self._add_subtract(stmt, env, add=isinstance(stmt, AddStatement))
        return self._forget_roots(env, self.records.roots_written(stmt))

    def _store(self, env: Env, field: _Field, data: str | None) -> Env:
        if field.root not in env and data is None:
            if self._fillers_of.get(field.root):
                self._store_check(field, UNKNOWN * field.length)
            return env
        env = dict(env)
        current = env.get(field.root)
        if current is None:
            current = UNKNOWN * self.layout.length[field.root]
        if data is None:
            data = UNKNOWN * field.length
        self._store_check(field, data)
        env[field.root] = (
            current[: field.offset] + data + current[field.offset + field.length :]
        )
        if env[field.root].count(UNKNOWN) == len(env[field.root]):
            del env[field.root]
        return env

    def _store_check(self, field: _Field, data: str) -> None:
        """Distrust every trusted FILLER *data* stored in *field* changes."""
        for i in self._fillers_of.get(field.root, ()):
            _, offset, value = self.layout.fillers[i]
            low = max(offset, field.offset)
            high = min(offset + len(value), field.offset + field.length)
            if low < high and (
                data[low - field.offset : high - field.offset]
                != value[low - offset : high - offset]
            ):
                self.violated.add(i)

    def _move(self, source: str | None, target: str, env: Env) -> Env:
        field = self.layout.resolve(target)
        if field is None:
            return self._forget_names(env, [target])
        data = None if source is None else self._move_bytes(source, field, env)
        return self._store(env, field, data)

    def _move_bytes(self, source: str, field: _Field, env: Env) -> str | None:
        """The bytes MOVE *source* leaves in *field*; None when not followed."""
        text = source.strip()
        if field.kind == _OPAQUE:
            return self._edited_digits(text, field)
        number = _numeric_literal(text)
        if field.kind == _NUM:
            if number is None and text.upper() in _ZERO_WORDS:
                number = Decimal(0)
            if number is None:
                ref = self.layout.resolve(text)
                if ref is not None and ref.kind == _NUM:
                    number = self._number(ref, env)
            if number is None:
                return None
            return _render_num(number, field.length, field.scale, exact=False)
        # Text and group receivers: an alphanumeric move.
        if number is not None:
            match = _NUMERIC_LITERAL_RE.match(text)
            if text[0] in "+-" or (match and match.group(2)):
                return None
            return text[: field.length].ljust(field.length)
        fill = _text_fill(text, field.length)
        if fill is not None:
            return fill
        ref = self.layout.resolve(text)
        if ref is None or ref.root not in env:
            return None
        if ref.kind == _NUM and ref.scale:
            return None
        if ref.kind == _OPAQUE:
            return None
        data = self._bytes(ref, env)
        return data[: field.length].ljust(field.length)

    def _edited_digits(self, source: str, field: _Field) -> str | None:
        """A numeric-edited receiver of a numeric MOVE: every ``9`` position
        gets a digit, whatever the value (editing writes a digit there even
        from a field holding invalid data); the rest is unknown."""
        item = field.item
        pic = item.picture_clause
        if pic is None or not pic.is_numeric_edited or item.blank_when_zero:
            return None
        if (item.usage or "DISPLAY").upper() != "DISPLAY":
            return None
        if _numeric_literal(source) is None and source.upper() not in _ZERO_WORDS:
            ref = self._numeric_item(source)
            if ref is None:
                return None
        symbols = _expand_picture(pic.pattern)
        if symbols is None or len(symbols) != field.length:
            return None
        return "".join(DIGIT if c == "9" else UNKNOWN for c in symbols)

    def _numeric_item(self, name: str) -> CobolDataItem | None:
        """The one elementary numeric item *name* names (any usage, tracked
        or not, subscripts allowed)."""
        base = re.split(r"[\s(]", name.strip(), maxsplit=1)[0].upper()
        items = self.layout.by_name.get(base, [])
        if len(items) != 1:
            return None
        item = items[0]
        pic = item.picture_clause
        if pic is None or not pic.total_digits or pic.is_edited:
            return None
        if any(isinstance(c, CobolDataItem) for c in item.children):
            return None
        return item

    def _add_subtract(self, stmt: Any, env: Env, *, add: bool) -> Env:
        written = [*stmt.targets, *stmt.givings]
        operands = stmt.source_operands
        if not operands:
            return self._forget_names(env, written)
        values = [self._operand_number(op, env) for op in operands]
        if any(v is None for v in values):
            if all(self._operand_digits(op, env) for op in operands):
                return self._digits_result(stmt, env)
            return self._forget_names(env, written)
        total = sum((v for v in values if v is not None), Decimal(0))
        if stmt.givings:
            if len(stmt.targets) > 1:
                return self._forget_names(env, written)
            base: Decimal | None = Decimal(0)
            if stmt.targets:
                base = self._operand_number(stmt.targets[0], env)
            for giving in stmt.givings:
                field = self.layout.resolve(giving)
                if field is None or field.kind != _NUM or base is None:
                    env = self._forget_names(env, [giving])
                    continue
                result = base + total if add else base - total
                env = self._store(
                    env,
                    field,
                    _render_num(result, field.length, field.scale, exact=True),
                )
            return env
        for target in stmt.targets:
            field = self.layout.resolve(target)
            current = self._number(field, env) if field is not None else None
            if field is None or field.kind != _NUM or current is None:
                if field is not None and self._operand_digits(target, env):
                    env = self._store(env, field, DIGIT * field.length)
                else:
                    env = self._forget_names(env, [target])
                continue
            result = current + total if add else current - total
            env = self._store(
                env, field, _render_num(result, field.length, field.scale, exact=True)
            )
        return env

    def _digits_result(self, stmt: Any, env: Env) -> Env:
        """ADD / SUBTRACT on operands that hold digits, values unknown: an
        unsigned DISPLAY receiver ends up holding digits (truncated, or the
        absolute value, but digits)."""
        receivers = list(stmt.givings) if stmt.givings else list(stmt.targets)
        for name in stmt.targets if stmt.givings else ():
            if not self._operand_digits(name, env):
                return self._forget_names(env, [*stmt.targets, *stmt.givings])
        for name in receivers:
            field = self.layout.resolve(name)
            if field is None or field.kind != _NUM:
                env = self._forget_names(env, [name])
                continue
            if not stmt.givings and not self._operand_digits(name, env):
                env = self._forget_names(env, [name])
                continue
            env = self._store(env, field, DIGIT * field.length)
        return env

    def _operand_digits(self, token: str, env: Env) -> bool:
        """Whether *token* is a number: a numeric literal, ZERO, or an
        unsigned DISPLAY item whose every byte is a digit."""
        text = token.strip()
        if _numeric_literal(text) is not None or text.upper() in _ZERO_WORDS:
            return True
        field = self.layout.resolve(text)
        if field is None or field.kind != _NUM:
            return False
        return all(c in _DIGITS for c in self._bytes(field, env))

    # -- reads ----------------------------------------------------------------

    def _bytes(self, field: _Field, env: Env) -> str:
        record = env.get(field.root)
        if record is None:
            return UNKNOWN * field.length
        return record[field.offset : field.offset + field.length]

    def _number(self, field: _Field, env: Env) -> Decimal | None:
        if field.kind != _NUM:
            return None
        data = self._bytes(field, env)
        if not data.isdigit() or not data.isascii():
            return None
        return Decimal(int(data)).scaleb(-field.scale)

    def _operand_number(self, token: str, env: Env) -> Decimal | None:
        text = token.strip()
        number = _numeric_literal(text)
        if number is not None:
            return number
        if text.upper() in _ZERO_WORDS:
            return Decimal(0)
        field = self.layout.resolve(text)
        return None if field is None else self._number(field, env)

    def _operand(self, token: str, env: Env) -> _Operand | None:
        text = token.strip()
        number = _numeric_literal(text)
        if number is not None:
            return ("num", number)
        literal = _text_literal(text)
        if literal is not None:
            return ("text", literal)
        upper = text.upper()
        if upper in _ZERO_WORDS:
            return ("zero", "0")
        fill = _FIGURATIVE_FILL.get(upper)
        if fill is not None:
            return ("fill", fill)
        field = self.layout.resolve(text)
        if field is None:
            return None
        if field.kind == _NUM:
            value = self._number(field, env)
            return None if value is None else ("num", value)
        if field.kind == _TEXT or _edited_display(field.item):
            data = self._bytes(field, env)
            return None if data == UNKNOWN * len(data) else ("text", data)
        return None

    def _decide(self, expr: Any, env: Env) -> bool | None:
        if isinstance(expr, LogicalExpression):
            op = (expr.operator or "").upper()
            left = (
                self._decide(expr.left_condition, env)
                if expr.left_condition is not None
                else None
            )
            if op == "NOT":
                return None if left is None else not left
            right = (
                self._decide(expr.right_condition, env)
                if expr.right_condition is not None
                else None
            )
            if op == "AND":
                if left is False or right is False:
                    return False
                return True if left and right else None
            if op == "OR":
                if left is True or right is True:
                    return True
                return False if left is False and right is False else None
            return None
        if not isinstance(expr, ConditionalExpression):
            return None
        op = (expr.operator or "").upper()
        if not isinstance(expr.left_operand, str):
            return None
        if op == "CONDITION_NAME":
            return self._condition_name(expr.left_operand, env)
        if op in _RELATIONS:
            if not isinstance(expr.right_operand, str):
                return None
            left_value = self._operand(expr.left_operand, env)
            right_value = self._operand(expr.right_operand, env)
            if left_value is None or right_value is None:
                return None
            if _longer_literal(left_value, right_value):
                # Equal only past the item's end: trust the PICTURE's size no
                # further than that (a comma closing an edited PICTURE is
                # easy to lose).
                return None
            return _compare(op, left_value, right_value)
        negated = op.startswith("IS NOT ")
        word = op.removeprefix("IS NOT ").removeprefix("IS ")
        if word in _SIGNS:
            value = self._operand(expr.left_operand, env)
            if value is None or value[0] != "num":
                return None
            verdict = bool(_SIGNS[word](value[1]))
            return not verdict if negated else verdict
        return None

    def _condition_name(self, name: str, env: Env) -> bool | None:
        if "(" in name:
            return None
        parts = [p.strip().upper() for p in _QUALIFIER_RE.split(name.strip())]
        found = [
            (cond, parent)
            for cond, parent in self.layout.conditions.get(parts[0], [])
            if not parts[1:]
            or self.layout._qualified_by(parent, parts[1:])
            or (parent.name or "").upper() == parts[1]
        ]
        if len(found) != 1:
            return None
        cond, parent = found[0]
        field = self.layout.fields.get(id(parent))
        if (
            field is None
            or field.root in self.untracked
            or field.in_table
            or field.kind == _OPAQUE
        ):
            return None
        current = self._operand_of_field(field, env)
        if current is None:
            return None
        verdicts: list[bool | None] = []
        values = list(cond.values)
        kinds = list(getattr(cond, "value_kinds", None) or [])
        kinds += [None] * (len(values) - len(kinds))
        position = 0
        while position < len(values):
            raw = str(values[position])
            kind = kinds[position]
            position += 1
            start: _Operand | None
            if raw.upper().startswith("THROUGH:"):
                start = None
            elif kind == "string":
                start = ("text", raw)
            else:
                start = self._operand(raw, {})
            if start is None:
                return None
            if position < len(values) and str(values[position]).upper().startswith(
                "THROUGH:"
            ):
                end = self._operand(str(values[position])[len("THROUGH:") :], {})
                position += 1
                if current[0] != "num" or end is None:
                    return None
                low = _compare("GREATER_OR_EQUAL", current, start)
                high = _compare("LESS_OR_EQUAL", current, end)
                verdicts.append(None if low is None or high is None else low and high)
            else:
                verdicts.append(_compare("EQUAL", current, start))
        if True in verdicts:
            return True
        return None if None in verdicts or not verdicts else False

    def _operand_of_field(self, field: _Field, env: Env) -> _Operand | None:
        if field.kind == _NUM:
            value = self._number(field, env)
            return None if value is None else ("num", value)
        data = self._bytes(field, env)
        return None if data == UNKNOWN * len(data) else ("text", data)


def _maybe_abbreviated(expr: Any) -> bool:
    """Whether two relations of one condition share their subject: what an
    abbreviated combined relation (``A = B AND C OR NOT < D``) parses to.
    Compilers disagree with a plain reading of those, so the pass never
    decides one -- nor a condition that merely spells the subject twice."""
    subjects: list[str] = []
    stack = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, LogicalExpression):
            stack.extend([node.left_condition, node.right_condition])
        elif isinstance(node, ConditionalExpression) and isinstance(
            node.left_operand, str
        ):
            subjects.append(node.left_operand.strip().upper())
    return len(subjects) != len(set(subjects))


def _compare(op: str, left: _Operand, right: _Operand) -> bool | None:
    """A relation whose answer cannot depend on the collating sequence."""
    lk, rk = left[0], right[0]
    if lk == "zero" and rk == "num":
        left, lk = ("num", Decimal(0)), "num"
    if rk == "zero" and lk == "num":
        right, rk = ("num", Decimal(0)), "num"
    if lk == "num" and rk == "num":
        return bool(_RELATIONS[op](left[1], right[1]))
    if op not in ("EQUAL", "NOT_EQUAL"):
        return None
    if lk == "text" and rk == "text":
        a, b = str(left[1]), str(right[1])
        width = max(len(a), len(b))
        equal = _text_equal(a.ljust(width), b.ljust(width))
    elif lk == "text" and rk in ("fill", "zero"):
        a = str(left[1])
        equal = _text_equal(a, str(right[1]) * len(a)) if a else None
    elif rk == "text" and lk in ("fill", "zero"):
        b = str(right[1])
        equal = _text_equal(b, str(left[1]) * len(b)) if b else None
    else:
        return None
    if equal is None:
        return None
    return equal if op == "EQUAL" else not equal


def _longer_literal(left: _Operand, right: _Operand) -> bool:
    """Two texts of different lengths whose longer one has more than spaces
    past the shorter one's end."""
    if left[0] != "text" or right[0] != "text":
        return False
    a, b = str(left[1]), str(right[1])
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    return bool(longer[len(shorter) :].strip(" "))


def _text_equal(a: str, b: str) -> bool | None:
    """Byte-wise equality of two texts of one length that may hold DIGIT and
    UNKNOWN bytes: False as soon as one position surely differs, None when
    only such positions leave it open."""
    open_ = False
    for x, y in zip(a, b, strict=False):
        if x == y and x not in (DIGIT, UNKNOWN):
            continue
        if x == UNKNOWN or y == UNKNOWN:
            open_ = True
            continue
        if x == DIGIT or y == DIGIT:
            other = y if x == DIGIT else x
            if other in _DIGITS:
                open_ = True
                continue
        return False
    return None if open_ else True


_Kept = tuple[Env, frozenset[tuple[str, str]]]


def _admit(
    known: list[_Kept], env: Env, weights: dict[str, frozenset[int]]
) -> Env | None:
    """Record *env* at a point holding *known*; the state to carry on with,
    or None when *known* already covers it. Past `MAX_STATES_PER_POINT` the
    new state is merged into the nearest one: the one it differs from in the
    fewest bytes, a byte some condition reads counting far more than one
    nothing tests. So states that differ only in a line counter merge
    before a PASS state and a FAIL state do."""
    items = frozenset(env.items())
    for other, other_items in known:
        if _covers(other, other_items, env, items):
            return None
    if len(known) < MAX_STATES_PER_POINT:
        known.append((env, items))
        return env
    best = min(
        range(len(known)),
        key=lambda i: _distance(known[i][0], known[i][1], env, items, weights),
    )
    merged = _meet(known[best][0], env)
    known[best] = (merged, frozenset(merged.items()))
    return merged


def _covers(
    general: Env,
    general_items: frozenset[tuple[str, str]],
    env: Env,
    items: frozenset[tuple[str, str]],
) -> bool:
    """Whether every byte *general* knows, *env* knows the same."""
    for root, value in general_items - items:
        other = env.get(root)
        if other is None:
            return False
        for x, y in zip(value, other, strict=False):
            if x == y or x == UNKNOWN:
                continue
            if x == DIGIT and y in _DIGITS:
                continue
            return False
    return True


def _distance(
    a: Env,
    a_items: frozenset[tuple[str, str]],
    b: Env,
    b_items: frozenset[tuple[str, str]],
    weights: dict[str, frozenset[int]],
) -> int:
    total = 0
    for root in {root for root, _ in a_items ^ b_items}:
        left, right = a.get(root), b.get(root)
        tested = weights.get(root, frozenset())
        if left is None or right is None:
            value = left or right or ""
            total += len(value) + (_TESTED_WEIGHT - 1) * len(tested)
            continue
        differs = list(map(str.__ne__, left, right))
        total += sum(differs)
        if tested:
            total += (_TESTED_WEIGHT - 1) * sum(
                1 for i in tested if i < len(differs) and differs[i]
            )
    return total


def _meet(a: Env, b: Env) -> Env:
    """Byte-wise agreement of two states: a byte they disagree on, or one
    either does not know, is unknown."""
    out: Env = {}
    for root, left in a.items():
        right = b.get(root)
        if right is None:
            continue
        if left == right:
            out[root] = left
            continue
        joined = "".join(
            x if x == y else DIGIT if x in _DIGITS and y in _DIGITS else UNKNOWN
            for x, y in zip(left, right, strict=False)
        )
        if joined.count(UNKNOWN) != len(joined):
            out[root] = joined
    return out
