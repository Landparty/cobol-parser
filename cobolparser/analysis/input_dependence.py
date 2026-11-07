"""Which decisions of a program its inputs can change.

:class:`InputDependenceAnalyzer` answers, for every ``IF`` and ``EVALUATE``
of the PROCEDURE DIVISION, one question: can anything from outside the
program -- a record a READ returns, a FILE STATUS, an ACCEPT, what a CALLed
program writes back, the LINKAGE SECTION, SQL / CICS / DL/I replies, the
clock -- change which way it goes? A decision whose answer is *no* is
**input-independent**: every run that starts at the program's entry point
evaluates it the same number of times with the same values, so a run that
never took one of its outcomes proves that no input ever will. That is what
a coverage report needs to tell "not tested yet" from "cannot be tested":
the self-checking ``IF COMPUTED = 6 ... ELSE PERFORM FAIL`` of a validation
program, or a branch on a constant flag nobody sets.

How it decides (conservative throughout: when in doubt, input-dependent):

* **Taint.** Storage is tracked per 01/77 record (a REDEFINES or RENAMES of
  a record shares it). Seeds: every FILE SECTION and LINKAGE SECTION record,
  EXTERNAL items, the FILE STATUS / RELATIVE KEY items SELECTs name, the
  special registers the runtime sets, and everything a CALL, ACCEPT, READ
  INTO, RETURN, EXEC SQL / CICS / DLI, INVOKE or XML / JSON statement can
  write. A statement that reads tainted storage taints what it writes.
* **Implicit flow.** A write that runs only because of an input-dependent
  decision is tainted too (a counter bumped once per record read depends on
  how many records there are). Control dependence comes from a
  statement-level control-flow graph: a decision's *region* is everything
  reachable from it before its immediate post-dominator, and every write in
  the region of an input-dependent decision is tainted. Clause handlers
  (``AT END``, ``INVALID KEY``, ``ON EXCEPTION``, ...) are decisions on an
  input event; DECLARATIVES, CICS HANDLE and SQL WHENEVER targets run on
  one. The graph models PERFORM's return (a paragraph entered by PERFORM
  returns at its range end instead of falling into the next one), so the
  FAIL paragraph after PASS is not reached through it.
* Taint and control dependence are iterated to a fixpoint. A decision is
  input-independent when its own operands are untainted and it is not in
  the region of an input-dependent decision.

:meth:`InputDependenceReport.unreachable` then combines the analysis with
what a measured run took: outcomes an input-independent decision never took
are pruned, and everything reachable only through them -- or through
nothing at all -- is unreachable. A paragraph a test PERFORMs directly is
outside that claim: it is a statement about the program's own control flow
from its entry point, so callers should only apply it to runs that start
there.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..models.data_items import CobolDataItem, ConditionNameItem, RenamesItem
from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ..models.statements.call import CallStatement, EntryStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.data import DisplayStatement, MoveStatement
from ..models.statements.io import (
    IOAcceptStatement,
    IOCloseStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)
from ..models.statements.misc import (
    AlterStatement,
    ContinueStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    NextSentenceStatement,
    ReturnStatement,
    SortStatement,
)
from ._procedures import ProcedureIndex, enclosing_section, statement_qualifier

#: Clause bodies a statement runs or skips on an outcome of its own.
_CLAUSE_ATTRS = (
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
#: Clauses whose firing depends on the statement's operands only (not on
#: anything outside the program): ON SIZE ERROR, and STRING / UNSTRING's ON
#: OVERFLOW. A CALL's ON OVERFLOW / ON EXCEPTION is an input event.
_VALUE_CLAUSES = frozenset({"on_size_error", "not_on_size_error"})
#: Attributes never walked when collecting the data names a statement names.
_SKIP_ATTRS = frozenset(
    {
        "parent",
        "children",
        "location",
        "_metadata",
        "metadata",
        "then_statements",
        "else_statements",
        "inline_statements",
        "statements",
        *_CLAUSE_ATTRS,
        "_cached_all_statements",
    }
)
#: Special registers the runtime sets: input from the program's view.
_RUNTIME_REGISTERS = frozenset(
    {
        "SORT-RETURN",
        "LINAGE-COUNTER",
        "DEBUG-ITEM",
        "DEBUG-LINE",
        "DEBUG-NAME",
        "DEBUG-CONTENTS",
        "DEBUG-SUB-1",
        "DEBUG-SUB-2",
        "DEBUG-SUB-3",
        "XML-CODE",
        "XML-EVENT",
        "XML-TEXT",
        "XML-NTEXT",
        "XML-NAMESPACE",
        "XML-NAMESPACE-PREFIX",
        "XML-NNAMESPACE",
        "XML-NNAMESPACE-PREFIX",
        "JSON-CODE",
        "JSON-STATUS",
        "WHEN-COMPILED",
        "SQLCODE",
        "SQLSTATE",
        "SQLCA",
        "EIBRESP",
        "EIBRESP2",
        "EIBAID",
        "EIBCALEN",
        "EIBTRNID",
        "EIBDATE",
        "EIBTIME",
        "DIBSTAT",
    }
)
#: Registers a program may also set itself, listed so they are tracked.
_OTHER_REGISTERS = frozenset({"RETURN-CODE", "TALLY", "SORT-CONTROL"})
#: Intrinsic functions whose value comes from the environment.
_ENVIRONMENT_FUNCTIONS = frozenset(
    {
        "CURRENT-DATE",
        "RANDOM",
        "WHEN-COMPILED",
        "SECONDS-PAST-MIDNIGHT",
        "LOCALE-DATE",
        "LOCALE-TIME",
        "LOCALE-TIME-FROM-SECONDS",
        "EXCEPTION-FILE",
        "EXCEPTION-LOCATION",
        "EXCEPTION-STATEMENT",
        "EXCEPTION-STATUS",
        "CONTENT-OF",
    }
)
_IDENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_QUOTED_RE = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'")
#: Statement types that write no data item (their operands are only read).
_READ_ONLY_TYPES: tuple[type, ...] = (
    IfStatement,
    EvaluateStatement,
    DisplayStatement,
    GoStatement,
    IOCloseStatement,
    IOOpenStatement,
    StopStatement,
    ExitStatement,
    ContinueStatement,
    NextSentenceStatement,
    GobackStatement,
    AlterStatement,
    EntryStatement,
)
#: Statement class names that are boundaries: everything they name may be
#: written from outside.
_SOURCE_TYPE_NAMES = frozenset(
    {
        "CallStatement",
        "IOAcceptStatement",
        "ReturnStatement",
        "InvokeStatement",
        "XmlJsonStatement",
        "ReceiveStatement",
        "ExecSQLStatement",
        "ExecCICSStatement",
        "ExecDLIStatement",
        "ExecStatement",
        "ChainStatement",
        "EnterStatement",
        "ServiceStatement",
        "AllocateStatement",
    }
)

#: Reasons (also the strings the report carries).
REASON_FIXED = "decided by the program's own data: no input can change it"
REASON_DEAD = "no PERFORM, GO TO or fall-through reaches it"
#: Edge outcomes of the non-IF/EVALUATE decisions (ON SIZE ERROR, SEARCH,
#: PERFORM UNTIL, ...) start here, clear of IF / EVALUATE outcome indexes.
CLAUSE_OUTCOME_BASE = 1000


@dataclass
class Decision:
    """One IF / EVALUATE of the PROCEDURE DIVISION."""

    kind: str  # "IF" | "EVALUATE"
    line: int
    column: int
    #: Outcome labels in measurement order: IF ``["true", "false"]``;
    #: EVALUATE one per WHEN group, then ``"WHEN OTHER"`` / ``"no WHEN
    #: matched"``.
    outcomes: list[str]
    input_dependent: bool = False
    #: Why it is input-dependent (None when it is not).
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "line": self.line,
            "column": self.column,
            "outcomes": list(self.outcomes),
            "input_dependent": self.input_dependent,
            "reason": self.reason,
        }


@dataclass
class UnreachableResult:
    """What a program can never reach, given what a measured run took."""

    #: Upper-cased paragraph (and section) names -> reason.
    paragraphs: dict[str, str] = field(default_factory=dict)
    #: (kind, line) -> {outcome index: reason}.
    outcomes: dict[tuple[str, int], dict[int, str]] = field(default_factory=dict)
    #: Statement lines -> reason.
    statements: dict[int, str] = field(default_factory=dict)


@dataclass
class InputDependenceReport:
    """Result of :class:`InputDependenceAnalyzer`."""

    decisions: list[Decision]
    #: Upper-cased names of the records (01/77 items, registers) inputs reach.
    input_records: list[str]
    #: Set when the analysis could not be completed; nothing is claimed then.
    incomplete: str | None = None
    #: Upper-cased names a run from the program's entry point may PERFORM to
    #: start there: the first procedure after any DECLARATIVES (and, when it
    #: is a section, its first paragraph).
    entry_names: list[str] = field(default_factory=list)
    _graph: _Graph | None = field(default=None, repr=False)
    #: Clause decisions (not IF / EVALUATE) no input can change: first
    #: context copy of each.
    _independent_clauses: list[int] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [d.to_dict() for d in self.decisions],
            "input_records": list(self.input_records),
            "incomplete": self.incomplete,
        }

    def _prune_clauses(
        self, graph: _Graph, executed: set[int], pruned: dict[int, set[int]]
    ) -> None:
        for node in self._independent_clauses:
            line = graph.statement_lines.get(node)
            if line is None or line not in executed:
                continue
            targets = [
                (graph.statement_lines.get(t), o)
                for t, o in graph.succ[node]
                if o is not None and o >= CLAUSE_OUTCOME_BASE
            ]
            lines = [t for t, _ in targets]
            cut = {
                o
                for t, o in targets
                if t is not None
                and t not in executed
                and t != line
                and lines.count(t) == 1
            }
            if cut:
                pruned[node] = cut

    def decision(self, kind: str, line: int) -> Decision | None:
        for d in self.decisions:
            if d.kind == kind and d.line == line:
                return d
        return None

    def unreachable(
        self,
        taken: Mapping[tuple[str, int], Iterable[int]],
        executed_lines: Iterable[int] | None = None,
    ) -> UnreachableResult:
        """What the program never reaches from its entry point.

        Args:
            taken: For each decision the measured runs executed and could
                attribute fully, ``(kind, line) -> outcome indexes taken``.
                A decision left out is treated as not measured: none of its
                outcomes is pruned.
            executed_lines: The statement lines the measured runs executed.
                With it, an input-independent clause decision (``ON SIZE
                ERROR``, ``SEARCH``, a looping ``PERFORM``) that ran prunes
                the clause bodies whose first line never ran, when that
                line belongs to nothing else the decision leads to.
        """
        result = UnreachableResult()
        graph = self._graph
        if graph is None or self.incomplete:
            return result
        by_key: dict[tuple[str, int], list[Decision]] = {}
        for d in self.decisions:
            by_key.setdefault((d.kind, d.line), []).append(d)
        pruned: dict[int, set[int]] = {}  # decision node -> outcome indexes
        for key, outcomes in taken.items():
            matches = by_key.get(key, [])
            if len(matches) != 1:
                continue  # two decisions on one line: cannot tell them apart
            d = matches[0]
            seen = set(outcomes)
            if d.input_dependent or not seen:
                continue
            missing = {i for i in range(len(d.outcomes)) if i not in seen}
            if missing:
                node = graph.decision_nodes.get((d.kind, d.line, d.column))
                if node is not None:
                    pruned[node] = missing
                    result.outcomes.setdefault(key, {}).update(
                        dict.fromkeys(missing, REASON_FIXED)
                    )
        if executed_lines is not None:
            self._prune_clauses(graph, set(executed_lines), pruned)
        static = graph.reachable({})
        live = graph.reachable(pruned) if pruned else static
        for i, unit in enumerate(graph.units):
            if not unit.name:
                continue
            copies = graph.unit_entry_nodes.get(i, [])
            if any(n in live for n in copies):
                continue
            reason = (
                REASON_DEAD
                if not any(n in static for n in copies)
                else "reached only through decision outcomes no input can take"
            )
            result.paragraphs.setdefault(unit.name, reason)
        live_lines = {ln for n, ln in graph.statement_lines.items() if n in live}
        static_lines = {ln for n, ln in graph.statement_lines.items() if n in static}
        all_lines = set(graph.statement_lines.values())
        for stmt_line in sorted(all_lines - live_lines):
            result.statements[stmt_line] = (
                REASON_DEAD if stmt_line not in static_lines else REASON_FIXED
            )
        for d in self.decisions:
            node = graph.decision_nodes.get((d.kind, d.line, d.column))
            if node is None or node in live:
                continue
            reason = REASON_DEAD if node not in static else REASON_FIXED
            entry = result.outcomes.setdefault((d.kind, d.line), {})
            for i in range(len(d.outcomes)):
                entry.setdefault(i, reason)
        return result


# ---------------------------------------------------------------------------
# Control-flow graph
# ---------------------------------------------------------------------------


@dataclass
class _Unit:
    """One paragraph (or a section header) in source order."""

    name: str | None  # upper-cased; None for an unnamed leading body
    section: str | None
    node: Any
    statements: list[Any]
    entry: int = -1
    end: int = -1


class _Graph:
    """Statement-level CFG with PERFORM return contexts.

    Nodes are ints. Each statement gets one *template* node per context it
    is reached in; a context is the unit index of the innermost active
    PERFORM range end (or -1, the main line). Expansion is lazy (only
    reachable (template, context) pairs exist).
    """

    def __init__(self) -> None:
        self.succ: list[list[tuple[int, int | None]]] = []  # (target, outcome)
        self.units: list[_Unit] = []
        self.decision_nodes: dict[tuple[str, int, int], int] = {}
        self.statement_lines: dict[int, int] = {}
        self.node_stmt: dict[int, Any] = {}
        self.roots: list[int] = []
        #: Unit index -> its entry node in every context it was reached in.
        self.unit_entry_nodes: dict[int, list[int]] = {}
        #: PERFORM site node -> [(range context, node control returns to)].
        self.calls: dict[int, list[tuple[int, int]]] = {}
        #: Return node -> the range context it ends.
        self.ret_of: dict[int, int] = {}
        self.exit = self.new()

    def new(self) -> int:
        self.succ.append([])
        return len(self.succ) - 1

    def edge(self, a: int, b: int, outcome: int | None = None) -> None:
        self.succ[a].append((b, outcome))

    def reachable(self, pruned: Mapping[int, set[int]]) -> set[int]:
        """Nodes reachable along valid paths: a PERFORM returns to its own
        site, never to another site of the same range (the return node's
        edges, which go to every site, are only for post-dominance)."""
        seen: set[int] = set()
        stack = list(self.roots)
        returned: set[int] = set()
        waiting: dict[int, list[int]] = {}
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            ctx = self.ret_of.get(n)
            if ctx is not None:
                returned.add(ctx)
                stack.extend(waiting.get(ctx, ()))
                continue
            for call_ctx, after in self.calls.get(n, ()):
                waiting.setdefault(call_ctx, []).append(after)
                if call_ctx in returned:
                    stack.append(after)
            cut = pruned.get(n)
            for target, outcome in self.succ[n]:
                if cut and outcome is not None and outcome in cut:
                    continue
                if target not in seen:
                    stack.append(target)
        return seen


class _Builder:
    """Builds the context-expanded graph of one PROCEDURE DIVISION."""

    def __init__(
        self, division: CobolDivision, alters: dict[str, list[str]] | None = None
    ) -> None:
        self.g = _Graph()
        self.alters = alters or {}
        #: ids of GO TO statements an ALTER can redirect (input-like: which
        #: target they take depends on which ALTERs ran).
        self.altered_gotos: set[int] = set()
        self.index = ProcedureIndex.build(division)
        self.units: list[_Unit] = []
        self._unit_of_key: dict[str, tuple[int, int]] = {}  # key -> (first, last)
        self._collect_units(division)
        # Per context: (template id) -> node.
        self._nodes: dict[tuple[int, int], int] = {}
        # Template graph: each statement / unit marker is a template id.
        self.t_succ: list[list[tuple[str, Any]]] = []
        self.t_stmt: list[Any] = []
        self.t_kind: list[str] = []
        self._build_templates()
        #: context (range end unit) -> return targets (template, context)
        self.returns: dict[int, set[tuple[int, int]]] = {}
        self.alter_targets: dict[str, list[str]] = {}
        #: Decision template -> True when it is an input event.
        self.event_decisions: set[int] = set()
        #: Unit indexes run by the runtime (declaratives, HANDLE labels).
        self.event_roots: set[int] = set()

    # -- units --------------------------------------------------------------

    def _collect_units(self, division: CobolDivision) -> None:
        top: list[Any] = sorted(
            [*division._sections.values(), *division.paragraphs],
            key=lambda item: item.location.line,
        )
        for item in top:
            if isinstance(item, CobolSection):
                sec = item.section_name.upper() if item.section_name else None
                first = len(self.units)
                self.units.append(_Unit(sec, None, item, []))
                for para in item.paragraphs:
                    self.units.append(
                        _Unit(
                            _para_name(para),
                            sec,
                            para,
                            list(para.statements),
                        )
                    )
                if sec:
                    self._unit_of_key.setdefault(sec, (first, len(self.units) - 1))
            elif isinstance(item, CobolParagraph):
                self.units.append(
                    _Unit(_para_name(item), None, item, list(item.statements))
                )
        for i, unit in enumerate(self.units):
            if unit.name and unit.section is not None:
                for key in (unit.name, f"{unit.name} OF {unit.section}"):
                    self._unit_of_key.setdefault(key, (i, i))
            elif unit.name and unit.node is not None and unit.section is None:
                if not isinstance(unit.node, CobolSection):
                    self._unit_of_key.setdefault(unit.name, (i, i))

    def span(self, key: str) -> tuple[int, int] | None:
        return self._unit_of_key.get(key.upper())

    def resolve(self, name: str | None, stmt: Any, attr: str) -> list[tuple[int, int]]:
        if not name:
            return []
        keys = self.index.resolve(
            name, statement_qualifier(stmt, attr), enclosing_section(stmt)
        )
        out = []
        for key in keys:
            span = self.span(key)
            if span is None and " OF " in key:
                span = self.span(key.split(" OF ")[0])
            if span is not None:
                out.append(span)
        return out

    # -- templates ----------------------------------------------------------

    def _t(self, kind: str, stmt: Any = None) -> int:
        self.t_succ.append([])
        self.t_stmt.append(stmt)
        self.t_kind.append(kind)
        if stmt is not None:
            self.t_of_stmt[id(stmt)] = len(self.t_succ) - 1
        return len(self.t_succ) - 1

    def _build_templates(self) -> None:
        self.unit_entry: list[int] = []
        self.unit_end: list[int] = []
        #: Per unit, the templates of its top-level statements in order.
        self.unit_tops: list[list[int]] = []
        #: Statement id -> its template.
        self.t_of_stmt: dict[int, int] = {}
        for _unit in self.units:
            self.unit_entry.append(self._t("entry"))
            self.unit_end.append(self._t("end"))
        for i, unit in enumerate(self.units):
            self._current_unit = i
            first = self._list(unit.statements, self.unit_end[i], top=True)
            self.t_succ[self.unit_entry[i]].append(("seq", first))
            # end of unit: handled per context (fall through or return)

    def _list(self, stmts: list[Any], cont: int, top: bool = False) -> int:
        nxt = cont
        built: list[int] = []
        for stmt in reversed(stmts):
            nxt = self._stmt(stmt, nxt)
            built.append(nxt)
        if top:
            self.unit_tops.append(list(reversed(built)))
        return nxt

    def _stmt(self, stmt: Any, cont: int) -> int:
        if isinstance(stmt, IfStatement):
            t = self._t("decision", stmt)
            then_first = self._list(list(stmt.then_statements or []), cont)
            else_first = self._list(list(stmt.else_statements or []), cont)
            self.t_succ[t].append(("out0", then_first))
            self.t_succ[t].append(("out1", else_first))
            return t
        if isinstance(stmt, EvaluateStatement):
            t = self._t("decision", stmt)
            k = 0
            for group in _when_groups(stmt):
                body = list(getattr(group[-1], "statements", None) or [])
                self.t_succ[t].append((f"out{k}", self._list(body, cont)))
                k += 1
            default = stmt.default_when
            other = list(default.statements or []) if default is not None else []
            self.t_succ[t].append((f"out{k}", self._list(other, cont)))
            return t
        if isinstance(stmt, SearchStatement):
            t = self._t("cond", stmt)
            for clause in stmt.when_clauses:
                when_body = (
                    clause.get("statements") if isinstance(clause, dict) else None
                )
                self.t_succ[t].append(("seq", self._list(list(when_body or []), cont)))
            self.t_succ[t].append(
                ("seq", self._list(list(stmt.at_end_clause or []), cont))
            )
            self.t_succ[t].append(("seq", cont))
            return t
        if isinstance(stmt, PerformStatement):
            return self._perform(stmt, cont)
        if isinstance(stmt, GoStatement):
            t = self._t("goto", stmt)
            if stmt.depending_on_variable:
                self.t_kind[t] = "cond"
                self.t_succ[t].append(("seq", cont))
            names = list(stmt.target_paragraphs or [])
            if not names and stmt.target_paragraph:
                names = [stmt.target_paragraph]
            for name in names:
                for first, _last in self.resolve(name, stmt, "target_qualifier"):
                    self.t_succ[t].append(("seq", self.unit_entry[first]))
            unit_name = self.units[self._current_unit].name or ""
            if not names or self.alters.get(unit_name):
                self.t_succ[t].append(("altered", self._current_unit))
                self.t_kind[t] = "cond"
                self.altered_gotos.add(id(stmt))
            elif not self.t_succ[t]:
                self.t_kind[t] = "stop"  # no such procedure: cobc rejects it
            return t
        if isinstance(stmt, (StopStatement, GobackStatement)):
            if isinstance(stmt, StopStatement) and str(stmt.stop_type).upper() != "RUN":
                t = self._t("plain", stmt)
                self.t_succ[t].append(("seq", cont))
                return t
            t = self._t("stop", stmt)
            return t
        if isinstance(stmt, ExitStatement):
            t = self._t("plain", stmt)
            kind = (stmt.exit_type or "").upper()
            if kind == "PROGRAM":
                self.t_kind[t] = "stop"
            elif kind in ("PARAGRAPH", "SECTION"):
                target = self._current_unit
                if kind == "SECTION":
                    sec = self.units[target].section
                    span = self.span(sec) if sec else None
                    if span is not None:
                        target = span[1]
                self.t_succ[t].append(("seq", self.unit_end[target]))
            elif kind.startswith("PERFORM"):
                # Inline PERFORM exit: conservatively anywhere after it in
                # the loop, or out of it.
                self.t_succ[t].append(("seq", cont))
                self.t_succ[t].append(("nextsent", self._current_unit))
            else:
                self.t_succ[t].append(("seq", cont))
            return t
        if isinstance(stmt, NextSentenceStatement):
            t = self._t("plain", stmt)
            self.t_succ[t].append(("nextsent", self._current_unit))
            self.t_succ[t].append(("seq", self.unit_end[self._current_unit]))
            return t
        if isinstance(stmt, (SortStatement, MergeStatement)) and (
            getattr(stmt, "input_procedure", None)
            or getattr(stmt, "output_procedure", None)
        ):
            t = self._t("event", stmt)
            for first_attr, thru_attr in (
                ("input_procedure", "input_procedure_thru"),
                ("output_procedure", "output_procedure_thru"),
            ):
                procedure = getattr(stmt, first_attr, None)
                if isinstance(procedure, str) and procedure:
                    thru = getattr(stmt, thru_attr, None)
                    self._range_call(
                        t, stmt, procedure, thru if isinstance(thru, str) else None
                    )
            self.t_succ[t].append(("seq", cont))
            return t
        clauses: list[list[Any]] = [
            getattr(stmt, attr)
            for attr in _CLAUSE_ATTRS
            if isinstance(getattr(stmt, attr, None), list)
        ]
        nested = _other_nested_lists(stmt)
        if clauses or nested:
            t = self._t("event" if _event_decision(stmt) else "cond", stmt)
            for body in [*clauses, *nested]:
                self.t_succ[t].append(("seq", self._list(list(body or []), cont)))
            self.t_succ[t].append(("seq", cont))
            return t
        t = self._t("plain", stmt)
        self.t_succ[t].append(("seq", cont))
        return t

    def _perform(self, stmt: PerformStatement, cont: int) -> int:
        looping = stmt.perform_type in ("UNTIL", "VARYING", "TIMES")
        if stmt.target_paragraph:
            t = self._t("cond" if looping else "call", stmt)
            self._range_call(t, stmt, stmt.target_paragraph, stmt.thru_paragraph)
            if not any(label == "range" for label, _ in self.t_succ[t]):
                # Not a procedure of this program: nothing to model.
                self.t_kind[t] = "plain"
                self.t_succ[t].append(("seq", cont))
                return t
            if looping:
                self.t_succ[t].append(("seq", cont))
            else:
                self.t_succ[t].append(("after", cont))
            return t
        body = list(stmt.inline_statements or [])
        if not looping:
            t = self._t("plain", stmt)
            self.t_succ[t].append(("seq", self._list(body, cont)))
            return t
        t = self._t("cond", stmt)
        self.t_succ[t].append(("seq", self._list(body, t)))
        self.t_succ[t].append(("seq", cont))
        return t

    def _range_call(self, t: int, stmt: Any, first: str, thru: str | None) -> None:
        starts = self.resolve(first, stmt, "target_qualifier")
        ends = self.resolve(thru, stmt, "thru_qualifier") if thru else starts
        for start in starts:
            for end in ends or starts:
                self.t_succ[t].append(("range", (start[0], end[1])))

    # -- expansion ----------------------------------------------------------

    def node(self, template: int, ctx: int) -> int:
        key = (template, ctx)
        self._ctxs.add(ctx)
        found = self._nodes.get(key)
        if found is not None:
            return found
        n = self.g.new()
        self._nodes[key] = n
        self._pending.append((template, ctx, n))
        return n

    def expand(self, alters: dict[str, list[str]]) -> _Graph:
        g = self.g
        g.units = self.units
        self._pending: list[tuple[int, int, int]] = []
        self._ctxs: set[int] = {-1}
        #: return node per context
        self._ret: dict[int, int] = {}
        roots: list[tuple[int, int]] = []
        for i, unit in enumerate(self.units):
            node = unit.node
            if isinstance(node, CobolSection) and node.is_declarative:
                span = self.span(unit.name or "") or (i, i)
                roots.append((self.unit_entry[i], span[1]))
                self.event_roots.update(range(span[0], span[1] + 1))
        entry = next(
            (i for i in range(len(self.units)) if i not in self.event_roots), None
        )
        self.entry_unit = entry
        if entry is not None:
            roots.insert(0, (self.unit_entry[entry], -1))
        for t, stmt in enumerate(self.t_stmt):
            if isinstance(stmt, EntryStatement):
                roots.append((t, -1))
        for template, ctx in roots:
            g.roots.append(self.node(template, ctx))
        end_unit = {t: i for i, t in enumerate(self.unit_end)}
        markers = set(self.unit_entry) | set(self.unit_end)
        self._drain(alters, end_unit, markers)
        # Code nothing reaches still gets nodes (never roots), so its
        # statements and decisions can be reported unreachable.
        for i in range(len(self.units)):
            if not any((self.unit_entry[i], c) in self._nodes for c in self._ctxs):
                self.node(self.unit_entry[i], -1)
                self._drain(alters, end_unit, markers)
        self._close_exits()
        entry_index = {t: i for i, t in enumerate(self.unit_entry)}
        for (template, _ctx), n in self._nodes.items():
            unit_index = entry_index.get(template)
            if unit_index is not None:
                g.unit_entry_nodes.setdefault(unit_index, []).append(n)
        return g

    def _drain(
        self, alters: dict[str, list[str]], end_unit: dict[int, int], markers: set[int]
    ) -> None:
        g = self.g
        while self._pending:
            template, ctx, n = self._pending.pop()
            stmt = self.t_stmt[template]
            if stmt is not None and template not in markers:
                line = _line(stmt)
                if line is not None:
                    g.statement_lines[n] = line
                g.node_stmt[n] = stmt
                if self.t_kind[template] == "decision":
                    key = (
                        "IF" if isinstance(stmt, IfStatement) else "EVALUATE",
                        line or 0,
                        _column(stmt),
                    )
                    g.decision_nodes.setdefault(key, n)
            kind = self.t_kind[template]
            if kind == "end":
                unit_index = end_unit[template]
                if ctx == unit_index:
                    g.edge(n, self._return(ctx))
                elif unit_index + 1 < len(self.units):
                    g.edge(n, self.node(self.unit_entry[unit_index + 1], ctx))
                else:
                    g.edge(n, g.exit)
                continue
            if kind == "stop":
                g.edge(n, g.exit)
                continue
            for position, (label, target) in enumerate(self.t_succ[template]):
                if label == "seq" or label.startswith("out"):
                    if label.startswith("out"):
                        outcome: int | None = int(label[3:])
                    elif kind == "cond":
                        # A clause / loop edge: numbered so a measured run
                        # can prune it (see InputDependenceReport.unreachable).
                        outcome = CLAUSE_OUTCOME_BASE + position
                    else:
                        outcome = None
                    g.edge(n, self.node(int(target), ctx), outcome)
                elif label == "after":
                    # The PERFORM's return lands here, through the return
                    # node of its range (wired below); nothing direct.
                    pass
                elif label == "range":
                    start, end = target
                    g.edge(n, self.node(self.unit_entry[start], end))
                    looping = self.t_kind[template] in ("cond", "event")
                    back = template if looping else self._after_of(template)
                    self._wire_return(end, back, ctx)
                    g.calls.setdefault(n, []).append((end, self.node(back, ctx)))
                elif label == "nextsent":
                    for later in self._top_level_after(template, int(target)):
                        g.edge(n, self.node(later, ctx))
                elif label == "altered":
                    unit = self.units[int(target)]
                    for name in alters.get(unit.name or "", []):
                        found = self.span(name)
                        if found is not None:
                            g.edge(n, self.node(self.unit_entry[found[0]], ctx))

    def entry_names(self) -> list[str]:
        names: list[str] = []
        entry = getattr(self, "entry_unit", None)
        if entry is None:
            return names
        for i in range(entry, len(self.units)):
            unit = self.units[i]
            if unit.name:
                names.append(unit.name)
            if unit.statements or not isinstance(unit.node, CobolSection):
                if i > entry or unit.statements:
                    break
        return names

    def _after_of(self, template: int) -> int:
        for label, target in self.t_succ[template]:
            if label == "after":
                return int(target)
        raise AssertionError("PERFORM without continuation")

    def _return(self, ctx: int) -> int:
        n = self._ret.get(ctx)
        if n is None:
            n = self.g.new()
            self._ret[ctx] = n
            self.g.ret_of[n] = ctx
            for back, back_ctx in self.returns.get(ctx, set()):
                self.g.edge(n, self.node(back, back_ctx))
        return n

    def _wire_return(self, end: int, back: int, ctx: int) -> None:
        targets = self.returns.setdefault(end, set())
        if (back, ctx) in targets:
            return
        targets.add((back, ctx))
        n = self._ret.get(end)
        if n is not None:
            self.g.edge(n, self.node(back, ctx))

    def _top_level_after(self, template: int, unit_index: int) -> list[int]:
        """Top-level statements of a unit after the one holding `template`:
        NEXT SENTENCE continues after the next period, which the AST does
        not record, so every later one is a candidate."""
        stmt = self.t_stmt[template]
        unit_node = self.units[unit_index].node
        while stmt is not None and getattr(stmt, "parent", None) is not unit_node:
            stmt = getattr(stmt, "parent", None)
        tops = self.unit_tops[unit_index]
        top = self.t_of_stmt.get(id(stmt)) if stmt is not None else None
        if top is None or top not in tops:
            return list(tops)
        return tops[tops.index(top) + 1 :]

    def _close_exits(self) -> None:
        """Nodes that cannot reach EXIT (endless loops) get an edge to it,
        so post-dominance is defined (adding edges only widens regions)."""
        g = self.g
        pred: list[list[int]] = [[] for _ in g.succ]
        for a, outs in enumerate(g.succ):
            for b, _ in outs:
                pred[b].append(a)
        reach = {g.exit}
        stack = [g.exit]
        while stack:
            n = stack.pop()
            for p in pred[n]:
                if p not in reach:
                    reach.add(p)
                    stack.append(p)
        for n in range(len(g.succ)):
            if n not in reach:
                g.edge(n, g.exit)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class InputDependenceAnalyzer:
    """See the module docstring."""

    #: Give up (claim nothing) on graphs larger than this many nodes.
    max_nodes = 400_000

    def analyze(
        self, ast: CobolProgram, extra_inputs: Iterable[str] = ()
    ) -> InputDependenceReport:
        """Analyze *ast*.

        Args:
            ast: The program.
            extra_inputs: Data names a caller sets from outside on top of the
                program's own boundaries (a test case's setup ``MOVE``
                targets, say): they are input-fed too.
        """
        division = ast.procedure_division
        if division is None:
            return InputDependenceReport([], [])
        records = _Records(ast)
        for name in extra_inputs:
            records.seeds |= records.roots_of_name(name)
        alters = _alterations(ast)
        builder = _Builder(division, alters)
        try:
            graph = builder.expand(alters)
        except RecursionError:  # pragma: no cover - pathological nesting
            return InputDependenceReport([], [], incomplete="nesting too deep")
        if len(graph.succ) > self.max_nodes:
            return InputDependenceReport([], [], incomplete="program too large")
        stmt_nodes: dict[int, list[int]] = {}
        stmt_of: dict[int, Any] = {}
        for n, stmt in graph.node_stmt.items():
            stmt_nodes.setdefault(id(stmt), []).append(n)
            stmt_of[id(stmt)] = stmt
        merged = _ContextMergedGraph(graph, stmt_nodes)
        # Code nothing reaches neither runs nor writes: leave it out of the
        # taint fixpoint, where it could only make live code look dependent.
        live = merged.reachable({})
        live_stmts = {k: s for k, s in stmt_of.items() if stmt_nodes[k][0] in live}
        names_of = {k: records.roots_named(s) for k, s in live_stmts.items()}
        writes_of = {k: records.roots_written(s) for k, s in live_stmts.items()}
        source = {k for k, s in live_stmts.items() if _is_source(s)}
        event_nodes = {
            n
            for n, stmt in graph.node_stmt.items()
            if _event_decision(stmt) or id(stmt) in builder.altered_gotos
        }
        # DECLARATIVES run on an I/O event: their whole span is controlled.
        controlled: set[int] = set()
        if builder.event_roots:
            unit_of = {id(u.node): i for i, u in enumerate(builder.units)}
            for n, stmt in graph.node_stmt.items():
                if _unit_index(unit_of, stmt) in builder.event_roots:
                    controlled.add(n)
        ipdom = _post_dominators(graph)
        decision_nodes = [
            n
            for n, stmt in graph.node_stmt.items()
            if len(graph.succ[n]) > 1 and id(stmt) in live_stmts
        ]
        tainted = set(records.seeds)
        tainted_decisions: set[int] = set()
        reasons: dict[int, str] = {}
        changed = True
        while changed:
            changed = False
            for k in live_stmts:
                if writes_of[k] <= tainted:
                    continue
                if (
                    k in source
                    or names_of[k] & tainted
                    or any(n in controlled for n in stmt_nodes[k])
                ):
                    tainted |= writes_of[k]
                    changed = True
            for n in decision_nodes:
                if n in tainted_decisions:
                    continue
                k = id(graph.node_stmt[n])
                why = None
                if n in event_nodes:
                    why = "depends on an input event"
                elif names_of[k] & tainted:
                    hit = sorted({records.label(r) for r in names_of[k] & tainted})
                    why = "reads input-fed " + ", ".join(hit[:3])
                elif n in controlled:
                    why = "runs only under an input-dependent decision"
                if why is None:
                    continue
                tainted_decisions.add(n)
                reasons[n] = why
                new = _region(graph, n, ipdom) - controlled
                if new:
                    controlled |= new
                    changed = True
        decisions: list[Decision] = []
        for stmt_key, stmt in stmt_of.items():
            if not isinstance(stmt, (IfStatement, EvaluateStatement)):
                continue
            line = _line(stmt)
            if line is None:
                continue
            dep = [n for n in stmt_nodes[stmt_key] if n in tainted_decisions]
            decisions.append(
                Decision(
                    kind="IF" if isinstance(stmt, IfStatement) else "EVALUATE",
                    line=line,
                    column=_column(stmt),
                    outcomes=_outcome_labels(stmt),
                    input_dependent=bool(dep),
                    reason=reasons[dep[0]] if dep else None,
                )
            )
        decisions.sort(key=lambda d: (d.line, d.column))
        named = set().union(*names_of.values()) if names_of else set()
        return InputDependenceReport(
            decisions=decisions,
            input_records=sorted({records.label(r) for r in tainted & named}),
            entry_names=builder.entry_names(),
            _graph=merged,
            _independent_clauses=[
                stmt_nodes[id(graph.node_stmt[n])][0]
                for n in decision_nodes
                if n == stmt_nodes[id(graph.node_stmt[n])][0]
                and not any(
                    c in tainted_decisions for c in stmt_nodes[id(graph.node_stmt[n])]
                )
                and not isinstance(graph.node_stmt[n], (IfStatement, EvaluateStatement))
            ],
        )


class _ContextMergedGraph(_Graph):
    """The expanded graph seen through statements: a decision is pruned in
    every context it was expanded in, and a statement is reached when any
    of its context copies is."""

    def __init__(self, graph: _Graph, stmt_nodes: dict[int, list[int]]) -> None:
        self.__dict__.update(graph.__dict__)
        self._copies: dict[int, list[int]] = {}
        for nodes in stmt_nodes.values():
            for n in nodes:
                self._copies[n] = nodes

    def reachable(self, pruned: Mapping[int, set[int]]) -> set[int]:
        expanded: dict[int, set[int]] = {}
        for n, cut in pruned.items():
            for copy in self._copies.get(n, [n]):
                expanded[copy] = cut
        seen = super().reachable(expanded)
        # Represent each statement by its first copy, so callers can test
        # membership with any node they were given.
        out = set(seen)
        for n in seen:
            for copy in self._copies.get(n, ()):
                out.add(copy)
        return out


# ---------------------------------------------------------------------------
# Data: storage roots and taint seeds
# ---------------------------------------------------------------------------


class _Records:
    """Names -> storage roots (01/77 records, registers, indexes)."""

    def __init__(self, ast: CobolProgram) -> None:
        self.roots_of: dict[str, set[str]] = {}
        self.seeds: set[str] = set()
        self._labels: dict[str, str] = {}
        data = ast.data_division
        if data is not None:
            for section in data.sections:
                if not isinstance(section, CobolSection):
                    continue
                kind = (section.section_name or "").upper()
                seed = kind in ("FILE", "LINKAGE", "COMMUNICATION", "SCREEN")
                for item in section.data_items:
                    self._add_record(item, kind, seed)
                for child in section.children:
                    if isinstance(child, RenamesItem):
                        roots = self._roots(child.renames_from) | self._roots(
                            child.renames_through
                        )
                        if child.name:
                            self.roots_of.setdefault(child.name.upper(), set()).update(
                                roots or {f"#{child.name.upper()}"}
                            )
        for register in _RUNTIME_REGISTERS | _OTHER_REGISTERS:
            self.roots_of.setdefault(register, set()).add(f"${register}")
        for register in _RUNTIME_REGISTERS:
            self.seeds.add(f"${register}")
        for name in _select_input_names(ast):
            roots = self._roots(name)
            self.seeds |= roots or {f"#{name}"}

    def _add_record(self, item: CobolDataItem, section: str, seed: bool) -> None:
        name = (item.name or "").upper()
        if item.redefines and item.level in (1, 77):
            roots = self._roots(item.redefines)
            root = next(iter(sorted(roots))) if roots else f"#{name}"
        else:
            root = f"{section}:{name}:{id(item)}"
        self._labels[root] = name
        if seed or item.is_external:
            self.seeds.add(root)
        for node in [item, *item.get_all_children()]:
            self._name(node, root)
            for child in node.children:
                if isinstance(child, ConditionNameItem) and child.name:
                    self._name_str(child.name, root)
            occurs = getattr(node, "occurs_clause", None)
            if occurs is not None:
                for index in [*(occurs.index_names or []), occurs.indexed_by]:
                    if index:
                        self.roots_of.setdefault(index.upper(), set()).add(
                            f"@{index.upper()}"
                        )

    def _name(self, node: CobolDataItem, root: str) -> None:
        if node.name and not node.is_filler:
            self._name_str(node.name, root)

    def _name_str(self, name: str, root: str) -> None:
        self.roots_of.setdefault(name.upper(), set()).add(root)

    def roots_of_name(self, name: str) -> set[str]:
        """Roots a data name (possibly qualified or subscripted) can mean;
        a name this program does not declare gets a root of its own."""
        roots = self._roots(name)
        return roots or {f"#{t}" for t in _tokens(name)[:1]}

    def _roots(self, name: str | None) -> set[str]:
        if not name:
            return set()
        out: set[str] = set()
        for token in _tokens(name):
            out |= self.roots_of.get(token, set())
        return out

    def label(self, root: str) -> str:
        return self._labels.get(root, root.lstrip("$#@").split(":")[0])

    def roots_named(self, stmt: Any) -> set[str]:
        out: set[str] = set()
        for token in _statement_tokens(stmt):
            out |= self.roots_of.get(token, set())
        return out

    def roots_written(self, stmt: Any) -> set[str]:
        if isinstance(stmt, _READ_ONLY_TYPES):
            return set()
        if isinstance(stmt, PerformStatement):
            names = [
                clause["variable"]
                for clause in [stmt.varying_clause, *stmt.after_clauses]
                if isinstance(clause, dict) and isinstance(clause.get("variable"), str)
            ]
            return set().union(*(self._roots(n) for n in names)) if names else set()
        if isinstance(stmt, MoveStatement):
            return set().union(*(self._roots(n) for n in stmt.targets), set())
        if isinstance(stmt, (AddStatement, SubtractStatement, MultiplyStatement)):
            names = [*stmt.targets, *stmt.givings]
            return set().union(*(self._roots(n) for n in names), set())
        if isinstance(stmt, DivideStatement):
            names = [*stmt.targets, *stmt.givings]
            if stmt.remainder:
                names.append(stmt.remainder)
            return set().union(*(self._roots(n) for n in names), set())
        if isinstance(stmt, ComputeStatement):
            return set().union(*(self._roots(n) for n in stmt.targets), set())
        if isinstance(stmt, IOReadStatement):
            return self._roots(stmt.into_target)
        if isinstance(stmt, (IOWriteStatement, IORewriteStatement)):
            return self._roots(getattr(stmt, "record_name", None))
        roots = self.roots_named(stmt)
        if isinstance(stmt, (CallStatement, ReturnStatement)):
            roots.add("$RETURN-CODE")
        return roots


def _select_input_names(ast: CobolProgram) -> set[str]:
    names: set[str] = set()
    env = ast.get_division("ENVIRONMENT")
    if env is None:
        return names
    for node in env.find_all_by_type("Statement"):
        if type(node).__name__ != "SelectStatement":
            continue
        for attr in ("file_status", "file_status_vsam", "relative_key"):
            value = getattr(node, attr, None)
            if isinstance(value, str) and value:
                names.update(_tokens(value))
    return names


def _alterations(ast: CobolProgram) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    division = ast.procedure_division
    if division is None:
        return out
    for stmt in _walk_statements(division):
        if isinstance(stmt, AlterStatement):
            for alt in stmt.alterations:
                src = str(alt.get("from_paragraph", "")).upper()
                dst = str(alt.get("to_paragraph", "")).upper()
                if src and dst and dst not in out.get(src, []):
                    out.setdefault(src, []).append(dst)
    return out


def _walk_statements(node: Any) -> Iterable[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        if type(current).__name__.endswith("Statement"):
            yield current
        stack.extend(getattr(current, "children", None) or [])


def _is_source(stmt: Any) -> bool:
    name = type(stmt).__name__
    if name in _SOURCE_TYPE_NAMES or name.startswith("Exec"):
        return True
    if isinstance(stmt, (IOAcceptStatement, CallStatement, ReturnStatement)):
        return True
    if isinstance(stmt, IOReadStatement):
        return True
    tokens = set(_statement_tokens(stmt))
    return bool(tokens & _ENVIRONMENT_FUNCTIONS)


def _event_decision(stmt: Any) -> bool:
    """A decision on something outside the program (not on its values)."""
    if isinstance(stmt, (IfStatement, EvaluateStatement)):
        return False
    if isinstance(stmt, (SortStatement, MergeStatement)):
        return True
    if isinstance(stmt, GoStatement):
        # An altered GO TO goes where the last ALTER pointed it.
        return not (stmt.target_paragraphs or stmt.target_paragraph)
    for attr in _CLAUSE_ATTRS:
        if isinstance(getattr(stmt, attr, None), list):
            if attr in _VALUE_CLAUSES:
                continue
            if attr in ("on_overflow", "not_on_overflow") and type(stmt).__name__ in (
                "StringStatement",
                "UnstringStatement",
            ):
                continue
            return True
    if _other_nested_lists(stmt) and not isinstance(
        stmt, (PerformStatement, SearchStatement)
    ):
        return True
    return False


def _other_nested_lists(stmt: Any) -> list[list[Any]]:
    """Statement lists hanging off a statement this module does not model
    explicitly (handled as an input event: conservative)."""
    if isinstance(
        stmt,
        (IfStatement, EvaluateStatement, SearchStatement, PerformStatement),
    ):
        return []
    out = []
    for attr, value in vars(stmt).items():
        if attr in _SKIP_ATTRS or attr in ("children", "parent"):
            continue
        if (
            isinstance(value, list)
            and value
            and all(type(v).__name__.endswith("Statement") for v in value)
            and attr not in ("using_parameters",)
        ):
            out.append(value)
    return out


def _unit_index(unit_of: dict[int, int], stmt: Any) -> int | None:
    node = getattr(stmt, "parent", None)
    while node is not None and not isinstance(node, (CobolParagraph, CobolSection)):
        node = getattr(node, "parent", None)
    return unit_of.get(id(node)) if node is not None else None


# ---------------------------------------------------------------------------
# Post-dominators and regions
# ---------------------------------------------------------------------------


def _post_dominators(graph: _Graph) -> list[int]:
    """Immediate post-dominator of every node (Cooper-Harvey-Kennedy on the
    reversed graph, rooted at EXIT). Unreached nodes get EXIT."""
    n_nodes = len(graph.succ)
    exit_node = graph.exit
    pred_rev: list[list[int]] = [[] for _ in range(n_nodes)]  # reversed-graph preds
    for a, outs in enumerate(graph.succ):
        for b, _ in outs:
            pred_rev[a].append(b)  # in reversed graph, a's preds are its succs
    rsucc: list[list[int]] = [[] for _ in range(n_nodes)]
    for a, outs in enumerate(graph.succ):
        for b, _ in outs:
            rsucc[b].append(a)
    # Reverse post-order of the reversed graph from EXIT.
    order: list[int] = []
    seen = [False] * n_nodes
    stack: list[tuple[int, int]] = [(exit_node, 0)]
    seen[exit_node] = True
    while stack:
        node, i = stack[-1]
        if i < len(rsucc[node]):
            stack[-1] = (node, i + 1)
            nxt = rsucc[node][i]
            if not seen[nxt]:
                seen[nxt] = True
                stack.append((nxt, 0))
        else:
            stack.pop()
            order.append(node)
    order.reverse()
    rank = [-1] * n_nodes
    for i, node in enumerate(order):
        rank[node] = i
    idom = [-1] * n_nodes
    idom[exit_node] = exit_node
    changed = True
    while changed:
        changed = False
        for node in order[1:]:
            new = -1
            for p in pred_rev[node]:
                if idom[p] == -1:
                    continue
                if new == -1:
                    new = p
                else:
                    a, b = p, new
                    while a != b:
                        while rank[a] > rank[b]:
                            a = idom[a]
                        while rank[b] > rank[a]:
                            b = idom[b]
                    new = a
            if new != -1 and idom[node] != new:
                idom[node] = new
                changed = True
    return [d if d != -1 else exit_node for d in idom]


def _region(graph: _Graph, decision: int, ipdom: list[int]) -> set[int]:
    """Nodes reachable from `decision` before its immediate post-dominator."""
    stop = ipdom[decision]
    region: set[int] = set()
    stack = [b for b, _ in graph.succ[decision]]
    while stack:
        n = stack.pop()
        if n == stop or n in region or n == graph.exit:
            continue
        region.add(n)
        stack.extend(b for b, _ in graph.succ[n])
    return region


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _para_name(para: CobolParagraph) -> str | None:
    name = para.paragraph_name
    if not name or name in (".",):
        return None
    return name.upper()


def _line(stmt: Any) -> int | None:
    location = getattr(stmt, "location", None)
    line = getattr(location, "line", None)
    return line if isinstance(line, int) and line > 0 else None


def _column(stmt: Any) -> int:
    location = getattr(stmt, "location", None)
    column = getattr(location, "column", None)
    return column if isinstance(column, int) else 0


def _when_groups(stmt: EvaluateStatement) -> list[list[Any]]:
    groups_of = getattr(stmt, "when_groups", None)
    groups = groups_of() if callable(groups_of) else [[c] for c in stmt.when_clauses]
    return [g for g in groups if g]


def _outcome_labels(stmt: Any) -> list[str]:
    if isinstance(stmt, IfStatement):
        return ["true", "false"]
    labels = [f"WHEN #{i + 1}" for i, _ in enumerate(_when_groups(stmt))]
    labels.append("WHEN OTHER" if stmt.default_when is not None else "no WHEN matched")
    return labels


def _tokens(text: str) -> list[str]:
    text = _QUOTED_RE.sub(" ", text)
    return [
        t.upper() for t in _IDENT_RE.findall(text) if not t.replace("-", "").isdigit()
    ]


def _statement_tokens(stmt: Any) -> list[str]:
    """Upper-cased identifier tokens of every string a statement holds,
    nested statements excluded."""
    out: list[str] = []
    seen: set[int] = set()
    stack: list[Any] = [stmt]
    first = True
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            out.extend(_tokens(value))
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            continue
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            for key, v in value.items():
                if key in ("statements",):
                    continue
                stack.append(v)
            continue
        if isinstance(value, (list, tuple, set)):
            stack.extend(value)
            continue
        if not first and type(value).__name__.endswith("Statement"):
            continue
        first = False
        attrs = getattr(value, "__dict__", None)
        if not attrs:
            continue
        for key, v in attrs.items():
            if key in _SKIP_ATTRS:
                continue
            stack.append(v)
    return out
