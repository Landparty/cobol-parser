"""How many times each boundary statement runs, when that is knowable.

`gen-fixtures` asserts a `call_count` per mocked boundary. That count is only
safe to state when the boundary's statement sits on the program's
unconditional path: a CALL inside an IF arm runs zero or one times depending
on the data, and an ACCEPT inside `PERFORM UNTIL` runs as often as the loop
spins. This module walks the entry paragraph chain the way
:class:`~cobolparser.analysis.const_fold.ConstantFolder` does and gives every
statement it reaches either an exact execution count or "unknown":

* the main line, and every SIMPLE PERFORM it reaches (inline or out of line,
  THRU ranges and SECTIONs included), counts once per time it is reached --
  a paragraph PERFORMed twice runs twice;
* `PERFORM n TIMES` with a literal *n* multiplies its body's count by *n*;
* IF / EVALUATE / SEARCH arms, conditional handlers (AT END, INVALID KEY,
  ON EXCEPTION, ...), `PERFORM UNTIL` / `VARYING` / variable `TIMES` bodies
  and SORT / MERGE procedures are unknown;
* once a branch arm or loop body could transfer control (GO TO, EXIT
  PARAGRAPH / SECTION / PERFORM, NEXT SENTENCE, STOP RUN, GOBACK, EXIT
  PROGRAM), everything after it is unknown too: the walk cannot tell whether
  it still runs;
* an EXIT PARAGRAPH / SECTION, or a GO TO forward inside the range, on the
  certain path of a PERFORMed range (n TIMES included) just moves on inside
  that range: what it skips never runs, every other count stays exact (#827);
* a GO TO on the certain path is followed only forward, into code not yet
  walked. A jump back is a loop with a data-dependent trip count, so no
  count is reported at all; the same for a GO TO out of a PERFORMed
  paragraph, GO TO DEPENDING ON, and any GO TO in a program using ALTER.

One exception keeps the ubiquitous status check from blanking every count
after the first OPEN: an IF whose condition reads nothing but boundary
status fields (FILE STATUS fields, their level-88s, SQLCODE / SQLSTATE /
EIBRESP), and an INVALID KEY handler or a CALL's ON EXCEPTION / ON OVERFLOW,
is decided by the status the scenario's own fixtures supply. A scenario that
supplies a success status never takes those handlers, so a STOP RUN inside
one does not make the code after it uncertain. For the IF, which arm success
takes is worked out by evaluating the condition with every status field at
its success value ('00', SQLCODE 0, SQLSTATE '00000', EIBRESP 0, a level-88
by testing its own VALUEs against those): only the arm success provably does
*not* take is exempt. ``IF WS-FS = '00' ... GOBACK`` ends the run on success,
so what follows it is uncertain, as after any other conditional transfer; a
condition that cannot be evaluated exempts neither arm. A FILE STATUS field counts only
while the last boundary that set it ran on the certain path and could not
hit end of file: after a READ that reads to the end, the field holds '10' in
every scenario (and at once for empty input), so a check on it is data.
Scenarios that override a status to an error take the arm; what their counts
should be is a separate question.

Statements the walk never reaches (only reachable through GO TO, inside
DECLARATIVES, ...) have no count either: "exact, or absent".
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ..models.program import CobolProgram
from ..models.sql_statements import ExecSQLStatement
from ..models.statements.base import (
    ConditionalExpression,
    LogicalExpression,
    iter_clause_bodies,
)
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.io import IOAcceptStatement
from ..models.statements.misc import AlterStatement, ExitStatement, GobackStatement
from ..parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)
from .boundary_inventory import (
    _FILE_OP_SPECS,
    BoundaryRef,
    BoundaryReport,
    _condition_field_names,
)
from .const_fold import (
    _MAX_WALK_STEPS,
    _SECTION_KEY,
    _entry_paragraph,
    _fall_through_chain,
    _nested_statement_lists,
    _ordered_paragraphs,
    _perform_body_statements,
    _procedure_ranges,
    _procedure_span,
    _range_statements,
    _transfer_kind,
)

if TYPE_CHECKING:
    # generators/__init__.py reaches this module through program_fixtures,
    # so a top-level import of the layout index would be circular.
    from ..generators.data.program_layout import ProgramLayoutIndex

#: Statement types `BoundaryInventoryAnalyzer` turns into boundaries -- the
#: only ones a BoundaryRef's (paragraph, line) is matched against, so a
#: MOVE inside an AT END handler on the READ's own line cannot blur the
#: READ's count.
_BOUNDARY_TYPES: tuple[type, ...] = (
    *(statement_type for statement_type, _ in _FILE_OP_SPECS),
    CallStatement,
    ExecSQLStatement,
    ExecCicsStatement,
    ExecImsStatement,
    IOAcceptStatement,
)

_FILE_CATEGORIES = frozenset(category for _, category in _FILE_OP_SPECS)


def _category_of(stmt: Any) -> str | None:
    for statement_type, category in _FILE_OP_SPECS:
        if isinstance(stmt, statement_type):
            return category
    return None


#: Status registers that are not declared FILE STATUS fields but are set by
#: a mocked boundary all the same.
_STATUS_REGISTERS = frozenset({"SQLCODE", "SQLSTATE", "EIBRESP", "EIBRESP2"})

#: Handlers that fire only on an error status the scenario's fixture supplies.
_STATUS_HANDLERS = frozenset({"invalid_key_clause"})
_CALL_STATUS_HANDLERS = frozenset({"on_exception", "on_overflow"})

#: What each status register holds when its boundary succeeds.
_REGISTER_SUCCESS: dict[str, str | Decimal] = {
    "SQLCODE": Decimal(0),
    "SQLSTATE": "00000",
    "EIBRESP": Decimal(0),
    "EIBRESP2": Decimal(0),
}
#: The success FILE STATUS a scenario's fixture supplies.
_FILE_STATUS_SUCCESS = "00"

_RELATIONS = frozenset(
    {"EQUAL", "NOT_EQUAL", "GREATER", "LESS", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"}
)
#: ``'00' < WS-FS`` reads as ``WS-FS > '00'``.
_FLIPPED = {
    "GREATER": "LESS",
    "LESS": "GREATER",
    "GREATER_OR_EQUAL": "LESS_OR_EQUAL",
    "LESS_OR_EQUAL": "GREATER_OR_EQUAL",
}
_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
#: Characters whose relative order is the same in ASCII and EBCDIC.
_PORTABLE_ORDER = frozenset("0123456789 ")

_LITERAL_RE = re.compile(r"""^(['"].*|[+-]?\d[\d.,]*)$""", re.DOTALL)
_FIGURATIVES = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
        "TRUE",
        "FALSE",
        "ALL",
    }
)


@dataclass
class InvocationCounts:
    """Execution counts of the statements one walk reached.

    `count_at()` answers for a source position; :meth:`for_boundary` for a
    boundary site. Both return ``None`` -- never a guess -- when any
    statement there is not exactly countable.
    """

    #: ``id(statement)`` -> times it runs, for statements on the certain path.
    exact: dict[int, int] = field(default_factory=dict)
    #: ``id(statement)`` of every statement reached somewhere uncertain.
    unknown: set[int] = field(default_factory=set)
    #: ``id(statement)`` of each statement of a body a success status never
    #: runs (the failure arm of a status check, an INVALID KEY / ON EXCEPTION
    #: handler): what a STOP RUN there does says nothing about a scenario
    #: whose fixtures supply success. Read by `ConstantFolder` (#591).
    success_skipped: set[int] = field(default_factory=set)
    #: (UPPERCASED paragraph or "", line) -> statements of a boundary type.
    _by_site: dict[tuple[str, int], list[Any]] = field(default_factory=dict)
    #: line -> every statement starting there (any paragraph, any type).
    _by_line: dict[int, list[Any]] = field(default_factory=dict)

    def for_boundary(self, ref: BoundaryRef) -> int | None:
        if ref.line is None:
            return None
        return self._agree(self._by_site.get(((ref.paragraph or "").upper(), ref.line)))

    def count_at(self, line: int, statement_type: type) -> int | None:
        """The count of the *statement_type* statement(s) starting on *line*."""
        candidates = [
            stmt
            for stmt in self._by_line.get(line, [])
            if isinstance(stmt, statement_type)
        ]
        return self._agree(candidates)

    def statements_at(self, line: int, statement_type: type) -> list[Any]:
        """The *statement_type* statements starting on *line*."""
        return [
            stmt
            for stmt in self._by_line.get(line, [])
            if isinstance(stmt, statement_type)
        ]

    def _agree(self, statements: list[Any] | None) -> int | None:
        if not statements:
            return None
        counts: set[int] = set()
        for stmt in statements:
            key = id(stmt)
            if key in self.unknown or key not in self.exact:
                return None
            counts.add(self.exact[key])
        return counts.pop() if len(counts) == 1 else None


@dataclass
class _Frame:
    statements: Iterator[Any]
    #: Times each statement in this frame runs, or None when unknown.
    multiplier: int | None
    #: The PERFORM target entered to reach this frame (cycle guard).
    entered: str | None = None
    #: Inside a `PERFORM n TIMES` body: a transfer here leaves the loop
    #: early, so counts already multiplied would overstate.
    looped: bool = False
    #: An out-of-line PERFORM's range: the procedure names (paragraphs and
    #: section markers, as in ``ordered_names``) its statements come from, so
    #: an EXIT PARAGRAPH / SECTION or a forward GO TO inside the range can
    #: resume the frame where control goes (#827).
    range_names: list[str] | None = None


@dataclass
class _RegionEnd:
    """Pushed below a conditional region's frames; popped once they finish."""

    exempt: bool
    saved_transfer: bool


class _Walk:
    def __init__(
        self,
        ast: CobolProgram,
        sites: dict[tuple[str, int], list[_StatusSite]],
        index: ProgramLayoutIndex | None,
    ) -> None:
        self.ordered_names, self.by_name = _ordered_paragraphs(ast)
        self.status_sites = sites
        #: Status field -> True while the last boundary that set it ran on
        #: the certain path and cannot have hit end of file.
        self.status_ok: dict[str, bool] = {}
        #: ``id(statement)`` -> (UPPERCASED paragraph, line), boundary types.
        self.site_of: dict[int, tuple[str, int]] = {}
        self.index = index
        self.result = InvocationCounts()
        self.stack: list[_Frame | _RegionEnd] = []
        self.visiting: set[str] = set()
        self.stopped = False
        #: Past a point the walk cannot prove control reaches every time.
        self.uncertain = False
        #: A transfer was seen inside the conditional region being walked.
        self.region_transfer = False
        #: Counts are wrong somewhere; report nothing.
        self.poisoned = False
        self.steps = 0
        #: ALTER retargets a GO TO at run time; no GO TO can be followed.
        self.has_alter = any(
            isinstance(stmt, AlterStatement) for stmt in ast.get_all_statements()
        )
        #: ``id(statement)`` -> UPPERCASED paragraph, for top-level statements.
        self.paragraph_of: dict[int, str] = {
            id(stmt): name
            for name, paragraph in self.by_name.items()
            for stmt in paragraph.statements
        }

    # -- bookkeeping ------------------------------------------------------

    def record(self, stmt: Any, multiplier: int | None) -> None:
        key = id(stmt)
        site = self.site_of.get(key)
        if site is not None:
            category = _category_of(stmt)
            for site_category, field_name, data_driven in self.status_sites.get(
                site, []
            ):
                if site_category == category:
                    self.status_ok[field_name] = (
                        multiplier is not None and not data_driven
                    )
        if multiplier is None:
            self.result.unknown.add(key)
        else:
            self.result.exact[key] = self.result.exact.get(key, 0) + multiplier

    def push_region(self, bodies: list[list[Any]], *, exempt: bool) -> None:
        bodies = [body for body in bodies if body]
        if not bodies:
            return
        if exempt:
            for body in bodies:
                self.result.success_skipped.update(id(stmt) for stmt in body)
        self.stack.append(
            _RegionEnd(exempt=exempt, saved_transfer=self.region_transfer)
        )
        self.region_transfer = False
        for body in reversed(bodies):
            self.stack.append(_Frame(iter(body), None))

    def end_region(self, end: _RegionEnd) -> None:
        if end.exempt:
            # A success status never runs these arms, so a transfer in one
            # says nothing about the code around them either -- nor about a
            # sibling arm pushed below this region.
            self.region_transfer = end.saved_transfer
            return
        if self.region_transfer:
            self.uncertain = True
        self.region_transfer = self.region_transfer or end.saved_transfer

    # -- the walk ---------------------------------------------------------

    def run(self, ast: CobolProgram) -> InvocationCounts:
        self._index_sites(ast)
        entry = _entry_paragraph(ast)
        if entry is None:
            return self.result
        self.push_chain(entry)
        while self.stack and not self.stopped:
            top = self.stack[-1]
            if isinstance(top, _RegionEnd):
                self.stack.pop()
                self.end_region(top)
                continue
            stmt = next(top.statements, None)
            if stmt is None:
                self.stack.pop()
                if top.entered is not None:
                    self.visiting.discard(top.entered)
                continue
            self.steps += 1
            if self.steps > _MAX_WALK_STEPS:
                self.poisoned = True
                break
            self.visit(stmt, top)
        if self.poisoned:
            self.result.exact.clear()
        return self.result

    def visit(self, stmt: Any, frame: _Frame) -> None:
        multiplier = None if self.uncertain else frame.multiplier
        self.record(stmt, multiplier)

        if self._transfers(stmt):
            if frame.multiplier is None:
                self.region_transfer = True
            elif self.skip_within_range(stmt, frame):
                # The frame resumes where control goes inside the range: the
                # statements skipped never run, the others keep their count.
                pass
            elif frame.looped:
                self.poisoned = True
            elif _transfer_kind(stmt) == "skip":
                self.uncertain = True
            elif isinstance(stmt, GoStatement):
                self.follow_go_to(stmt)
            else:
                # STOP RUN / GOBACK / EXIT PROGRAM ends the run.
                self.stopped = True
            return

        if isinstance(stmt, PerformStatement):
            self.visit_perform(stmt, frame, multiplier)
        elif isinstance(stmt, IfStatement):
            self.push_if(stmt)
        else:
            self.push_handlers(stmt)
            if isinstance(stmt, (EvaluateStatement, SearchStatement)):
                bodies = [
                    body.statements
                    for body in iter_clause_bodies(stmt, include_handlers=False)
                ]
                self.push_region(bodies, exempt=False)

        for first, thru in _procedure_ranges(stmt):
            body = _range_statements(first, thru, self.by_name, self.ordered_names)
            if body is None:
                self.uncertain = True
            else:
                self.push_region([body], exempt=False)

    def skip_within_range(self, stmt: Any, frame: _Frame) -> bool:
        """Resume *frame* past *stmt* when it jumps forward inside the range.

        In a PERFORMed range, EXIT PARAGRAPH goes to the next paragraph,
        EXIT SECTION to the next section, and a GO TO to a later procedure of
        the range goes there; reaching the range's end returns from the
        PERFORM. None of that changes how often the code before it runs, or
        whether the code after the PERFORM runs (#827), so the frame's
        iterator is moved instead of the counts being dropped. False, changing
        nothing, for any other transfer.
        """
        names = frame.range_names
        paragraph = self.paragraph_of.get(id(stmt))
        if names is None or paragraph is None or paragraph not in names:
            return False
        here = names.index(paragraph)
        resume: int | None = None
        if isinstance(stmt, ExitStatement) and stmt.exit_type == "PARAGRAPH":
            resume = here + 1
        elif isinstance(stmt, ExitStatement) and stmt.exit_type == "SECTION":
            resume = next(
                (
                    i
                    for i in range(here + 1, len(names))
                    if names[i].startswith(_SECTION_KEY)
                ),
                len(names),
            )
        elif isinstance(stmt, GoStatement) and not (
            self.has_alter or stmt.depending_on_variable
        ):
            targets = list(stmt.target_paragraphs) or (
                [stmt.target_paragraph] if stmt.target_paragraph else []
            )
            if len(targets) == 1:
                key = targets[0].upper()
                marker = f"{_SECTION_KEY}{key}"
                target = key if key in names else marker
                if target in names[here + 1 :]:
                    resume = names.index(target, here + 1)
        if resume is None:
            return False
        frame.statements = iter(
            [
                inner
                for name in names[resume:]
                if name in self.by_name
                for inner in self.by_name[name].statements
            ]
        )
        return True

    def push_if(self, stmt: IfStatement) -> None:
        """An IF's arms; only the arm a success status never takes is exempt.

        A condition reading nothing but boundary status fields is decided by
        the scenario's fixtures, so it is evaluated with every one of them at
        success. The arm success *takes* is walked like any conditional arm:
        a transfer in it (``IF WS-FS = '00' ... GOBACK``) makes what follows
        uncertain. When the condition cannot be evaluated, neither is exempt.
        """
        selected = (
            self.success_selects(stmt.condition)
            if self.status_only(stmt.condition)
            else None
        )
        arms = [
            (stmt.then_statements, selected is False),
            (stmt.else_statements, selected is True),
        ]
        # Pushed last arm first, so the THEN arm is still walked first.
        for body, exempt in reversed(arms):
            self.push_region([body], exempt=exempt)

    def follow_go_to(self, stmt: GoStatement) -> None:
        """A GO TO on the certain path: keep walking at its target.

        Only a jump forward into code not yet walked is followed. A jump
        back into walked code is a loop whose trip count depends on the
        data, so every count already taken could be short: report nothing.
        The same goes for a GO TO out of a PERFORMed paragraph (where control
        goes after the range ends is not modelled), GO TO DEPENDING ON, and
        any GO TO in a program that ALTERs one.
        """
        targets = list(stmt.target_paragraphs) or (
            [stmt.target_paragraph] if stmt.target_paragraph else []
        )
        if (
            self.has_alter
            or stmt.depending_on_variable
            or len(targets) != 1
            or any(isinstance(f, _Frame) and f.entered is not None for f in self.stack)
        ):
            self.poisoned = True
            return
        target = self._paragraph_named(targets[0])
        if target is None or any(
            id(walked) in self.result.exact or id(walked) in self.result.unknown
            for walked in target.statements
        ):
            self.poisoned = True
            return
        self.stack.clear()
        self.visiting.clear()
        self.push_chain(target)

    def push_chain(self, paragraph: Any) -> None:
        """*paragraph* and every paragraph control falls into after it."""
        for chained in reversed(
            _fall_through_chain(paragraph, self.ordered_names, self.by_name)
        ):
            self.stack.append(_Frame(iter(chained.statements), 1))

    def _paragraph_named(self, name: str) -> Any:
        key = name.upper()
        if key in self.by_name:
            return self.by_name[key]
        marker = f"{_SECTION_KEY}{key}"
        if marker not in self.ordered_names:
            return None
        for following in self.ordered_names[self.ordered_names.index(marker) + 1 :]:
            if following.startswith(_SECTION_KEY):
                return None
            if following in self.by_name:
                return self.by_name[following]
        return None

    def push_handlers(self, stmt: Any) -> None:
        exempt_attrs = _STATUS_HANDLERS | (
            _CALL_STATUS_HANDLERS if isinstance(stmt, CallStatement) else frozenset()
        )
        normal: list[list[Any]] = []
        exempt: list[list[Any]] = []
        for body in iter_clause_bodies(stmt):
            if body.kind == "handler":
                target = exempt if body.attr in exempt_attrs else normal
                target.append(body.statements)
        self.push_region(normal, exempt=False)
        self.push_region(exempt, exempt=True)

    def visit_perform(
        self, stmt: PerformStatement, frame: _Frame, multiplier: int | None
    ) -> None:
        body = stmt.inline_statements or _perform_body_statements(
            stmt, self.by_name, self.ordered_names
        )
        if body is None:
            # An unknown target could do anything, including transfer away.
            self.uncertain = True
            return
        target = (
            None if stmt.inline_statements else (stmt.target_paragraph or "").upper()
        )
        times = _literal_times(stmt)
        if stmt.perform_type == "SIMPLE" or times is not None:
            if target is not None:
                if target in self.visiting:
                    self.uncertain = True  # a PERFORM cycle: no exact count
                    return
                self.visiting.add(target)
            looped = frame.looped or stmt.perform_type != "SIMPLE"
            inner = None
            if multiplier is not None:
                inner = multiplier * (times if times is not None else 1)
            self.stack.append(
                _Frame(iter(body), inner, target, looped, self._range_names(stmt))
            )
            return
        # UNTIL / VARYING / a TIMES count held in a data item: zero or more.
        self.push_region([body], exempt=False)

    def _range_names(self, stmt: PerformStatement) -> list[str] | None:
        """The ``ordered_names`` slice an out-of-line PERFORM runs, else None."""
        if stmt.inline_statements or not stmt.target_paragraph:
            return None
        start = _procedure_span(
            stmt.target_paragraph.upper(), self.ordered_names, last=False
        )
        end = _procedure_span(
            (stmt.thru_paragraph or stmt.target_paragraph).upper(),
            self.ordered_names,
            last=True,
        )
        if start is None or end is None or end < start:
            return None
        return self.ordered_names[start : end + 1]

    # -- predicates -------------------------------------------------------

    @staticmethod
    def _transfers(stmt: Any) -> bool:
        if _transfer_kind(stmt) is not None:
            return True
        if isinstance(stmt, (GoStatement, StopStatement, GobackStatement)):
            return True
        return isinstance(stmt, ExitStatement) and stmt.exit_type == "PROGRAM"

    def status_only(self, condition: Any) -> bool:
        """True when *condition* reads boundary status fields and nothing else."""
        saw_status = False
        for raw in _condition_field_names(condition):
            name = raw.strip()
            upper = name.upper()
            if not name or _LITERAL_RE.match(name) or upper in _FIGURATIVES:
                continue
            qualified = self._qualified(name)
            if self.status_ok.get(qualified) or upper in _STATUS_REGISTERS:
                saw_status = True
                continue
            return False
        return saw_status

    def success_selects(self, condition: Any) -> bool | None:
        """*condition*'s value with every status field it reads at success.

        ``None`` when that cannot be worked out exactly: an operand that is
        neither a status field nor a literal, a literal of the wrong kind for
        the field, an ordering between characters whose collating order
        differs between ASCII and EBCDIC, a class test, ...
        """
        if isinstance(condition, LogicalExpression):
            left = self.success_selects(condition.left_condition)
            if condition.operator == "NOT":
                if condition.right_condition is not None or left is None:
                    return None
                return not left
            right = self.success_selects(condition.right_condition)
            if condition.operator == "AND":
                if left is False or right is False:
                    return False
                return True if left and right else None
            if condition.operator == "OR":
                if left is True or right is True:
                    return True
                return False if left is False and right is False else None
            return None
        if not isinstance(condition, ConditionalExpression):
            return None
        first = condition.left_operand
        second = condition.right_operand
        if condition.operator == "CONDITION_NAME":
            if not isinstance(first, str):
                return None
            return self._condition_name_holds(first)
        if (
            condition.operator not in _RELATIONS
            or not isinstance(first, str)
            or not isinstance(second, str)
        ):
            return None
        operator = condition.operator
        value = self._success_value(first)
        literal_text = second
        if value is None:
            value = self._success_value(second)
            literal_text = first
            operator = _FLIPPED.get(operator, operator)
        if value is None:
            return None
        return _compare(value, operator, _literal_like(literal_text, value))

    def _success_value(self, name: str) -> str | Decimal | None:
        """What status field *name* holds on success; None if not one."""
        upper = name.strip().upper()
        if upper in _REGISTER_SUCCESS:
            return _REGISTER_SUCCESS[upper]
        if not self.status_ok.get(self._qualified(name)):
            return None
        if self.index is not None:
            try:
                resolved = self.index.resolve(name.strip())
            except Exception:  # noqa: BLE001 - same policy as _qualified
                resolved = None
            if resolved is not None and str(resolved.spec.category) == "numeric":
                return Decimal(0)
        return _FILE_STATUS_SUCCESS

    def _condition_name_holds(self, name: str) -> bool | None:
        """Whether level-88 *name* is true with its field at success."""
        if self.index is None:
            return None
        try:
            resolved = self.index.resolve(name.strip())
            raw_values = self.index.condition_raw_values(name.strip())
        except Exception:  # noqa: BLE001 - same policy as _qualified
            return None
        if resolved is None or not raw_values:
            return None
        value = self._success_value(str(resolved.spec.qualified_name))
        if value is None:
            return None
        # ``VALUE '04' THRU '09'`` arrives as ('04', 'THROUGH:09').
        ranges: list[tuple[str, str | None]] = []
        for raw in raw_values:
            if raw.upper().startswith("THROUGH:"):
                if not ranges or ranges[-1][1] is not None:
                    return None
                ranges[-1] = (ranges[-1][0], raw[len("THROUGH:") :])
            else:
                ranges.append((raw, None))
        outcomes: list[bool | None] = []
        for low, high in ranges:
            if high is None:
                outcomes.append(
                    _compare(value, "EQUAL", _literal_like(low, value, unquoted=True))
                )
                continue
            above = _compare(
                value, "GREATER_OR_EQUAL", _literal_like(low, value, unquoted=True)
            )
            below = _compare(
                value, "LESS_OR_EQUAL", _literal_like(high, value, unquoted=True)
            )
            if above is False or below is False:
                outcomes.append(False)
            else:
                outcomes.append(True if above and below else None)
        if any(outcome is True for outcome in outcomes):
            return True
        return False if all(outcome is False for outcome in outcomes) else None

    def _qualified(self, name: str) -> str:
        if self.index is not None:
            try:
                resolved = self.index.resolve(name)
            except Exception:  # noqa: BLE001 - a garbage token is "not status"
                resolved = None
            if resolved is not None:
                # A level-88 resolves to the field it tests.
                return str(resolved.spec.qualified_name).upper()
        return name.upper()

    def _index_sites(self, ast: CobolProgram) -> None:
        procedure = ast.get_division("PROCEDURE")
        if procedure is None:
            return
        paragraphs = list(procedure.paragraphs)
        for section in procedure.sections:
            paragraphs.extend(getattr(section, "paragraphs", []) or [])
        seen: set[int] = set()
        for paragraph in paragraphs:
            name = (paragraph.paragraph_name or "").upper()
            pending = list(paragraph.statements)
            while pending:
                stmt = pending.pop()
                if id(stmt) in seen:
                    continue
                seen.add(id(stmt))
                line = stmt.location.line if stmt.location else None
                if line is not None:
                    self.result._by_line.setdefault(line, []).append(stmt)
                    if isinstance(stmt, _BOUNDARY_TYPES):
                        self.result._by_site.setdefault((name, line), []).append(stmt)
                        self.site_of[id(stmt)] = (name, line)
                for nested in _nested_statement_lists(stmt):
                    pending.extend(nested)


def _literal_like(
    text: str, like: str | Decimal, *, unquoted: bool = False
) -> str | Decimal | None:
    """*text* as a value comparable with *like*, or None when it is not one.

    A quoted literal compares only with a character field and an unquoted
    number only with a numeric one. *unquoted* marks a level-88 VALUE as the
    layout index keeps it, quotes already gone, so either kind reads.
    """
    stripped = text.strip()
    upper = stripped.upper()
    if upper in ("ZERO", "ZEROS", "ZEROES"):
        return Decimal(0) if isinstance(like, Decimal) else "0" * max(len(like), 1)
    if upper in ("SPACE", "SPACES"):
        return None if isinstance(like, Decimal) else " "
    if upper in _FIGURATIVES:
        return None
    if not unquoted and stripped[:1] in ("'", '"'):
        quote = stripped[0]
        if isinstance(like, Decimal) or len(stripped) < 2 or stripped[-1] != quote:
            return None
        return stripped[1:-1].replace(quote * 2, quote)
    if isinstance(like, Decimal):
        number = re.sub(r"^([+-])\s+", r"\1", stripped)
        if not _NUMBER_RE.match(number):
            return None
        try:
            return Decimal(number)
        except InvalidOperation:  # pragma: no cover - the regex vets it
            return None
    return stripped if unquoted else None


def _compare(
    value: str | Decimal, operator: str, literal: str | Decimal | None
) -> bool | None:
    """``value <operator> literal`` the way COBOL compares them, or None."""
    if isinstance(value, Decimal) and isinstance(literal, Decimal):
        a: Any = value
        b: Any = literal
    elif isinstance(value, str) and isinstance(literal, str):
        # Character comparison pads the shorter operand with spaces.
        width = max(len(value), len(literal))
        a, b = value.ljust(width), literal.ljust(width)
        if operator not in ("EQUAL", "NOT_EQUAL") and not set(a + b) <= (
            _PORTABLE_ORDER
        ):
            return None
    else:
        return None
    if operator == "EQUAL":
        return bool(a == b)
    if operator == "NOT_EQUAL":
        return bool(a != b)
    if operator == "GREATER":
        return bool(a > b)
    if operator == "LESS":
        return bool(a < b)
    if operator == "GREATER_OR_EQUAL":
        return bool(a >= b)
    if operator == "LESS_OR_EQUAL":
        return bool(a <= b)
    return None


def _literal_times(stmt: PerformStatement) -> int | None:
    if stmt.perform_type != "TIMES":
        return None
    count = stmt.times_count
    if isinstance(count, int) and not isinstance(count, bool):
        return count if count >= 0 else None
    if isinstance(count, str) and count.strip().isdigit():
        return int(count.strip())
    return None


#: A status a scenario's own fixture keeps at success, until the data says
#: otherwise.
_StatusSite = tuple[str, str, bool]  # (category, status field, data-driven)


def status_sites(
    report: BoundaryReport, index: ProgramLayoutIndex | None
) -> dict[tuple[str, int], list[_StatusSite]]:
    """(UPPERCASED paragraph, line) -> the status each boundary there sets.

    The status field is qualified and UPPERCASED. *data-driven* marks a
    READ that can reach end of file (an AT END handler, or no INVALID KEY
    handler): reading to the end sets the status to '10' in every scenario,
    and an empty-input scenario starts there, so what such a READ leaves in
    the field is decided by the data, not by a status the scenario chose.
    SQL boundaries are left out: SQLCODE / SQLSTATE are status registers.
    """

    def qualified(name: str) -> str:
        resolved = index.resolve(name) if index is not None else None
        return str(resolved.spec.qualified_name).upper() if resolved else name.upper()

    sites: dict[tuple[str, int], list[_StatusSite]] = {}
    for boundary in report.boundaries:
        ref = boundary.ref
        if ref.line is None or ref.category not in _FILE_CATEGORIES:
            continue
        field_name = boundary.status_field
        if not field_name and index is not None:
            facts = index.file_facts(ref.key)
            field_name = facts.file_status_field if facts is not None else None
        if not field_name:
            continue
        data_driven = ref.category == "READ" and (
            "AT_END" in boundary.handlers or "INVALID_KEY" not in boundary.handlers
        )
        sites.setdefault(((ref.paragraph or "").upper(), ref.line), []).append(
            (ref.category, qualified(field_name), data_driven)
        )
    return sites


def is_plain_eof_loop(
    ast: CobolProgram, stmt: PerformStatement, index: ProgramLayoutIndex | None
) -> bool:
    """True when *stmt* loops until one flag, with nothing that leaves early.

    `PERFORM UNTIL WS-EOF = 'Y'` runs until end of file. `UNTIL WS-EOF = 'Y'
    OR WS-CNT >= 3`, or a body that can GO TO / EXIT PERFORM / STOP, may stop
    first, so the file is not necessarily read to the end.
    """
    tree = stmt.until_condition.condition_tree if stmt.until_condition else None
    if tree is None:
        return False
    tested: set[str] = set()
    for raw in _condition_field_names(tree):
        name = raw.strip()
        if not name or _LITERAL_RE.match(name) or name.upper() in _FIGURATIVES:
            continue
        resolved = index.resolve(name) if index is not None else None
        tested.add(
            str(resolved.spec.qualified_name).upper() if resolved else name.upper()
        )
    if len(tested) != 1:
        return False
    ordered_names, by_name = _ordered_paragraphs(ast)
    body = stmt.inline_statements or _perform_body_statements(
        stmt, by_name, ordered_names
    )
    if body is None:
        return False
    pending = list(body)
    seen_targets: set[str] = set()
    while pending:
        inner = pending.pop()
        if _Walk._transfers(inner):
            return False
        if isinstance(inner, PerformStatement) and not inner.inline_statements:
            target = (inner.target_paragraph or "").upper()
            if target in seen_targets:
                continue
            seen_targets.add(target)
            performed = _perform_body_statements(inner, by_name, ordered_names)
            if performed is None:
                return False
            pending.extend(performed)
        for first, thru in _procedure_ranges(inner):
            procedure = _range_statements(first, thru, by_name, ordered_names)
            if procedure is None:
                return False
            pending.extend(procedure)
        for nested in _nested_statement_lists(inner):
            pending.extend(nested)
    return True


def count_invocations(
    ast: CobolProgram,
    report: BoundaryReport,
    index: ProgramLayoutIndex | None = None,
) -> InvocationCounts:
    """Walk *ast*'s entry chain and count what runs on its certain path."""
    return _Walk(ast, status_sites(report, index), index).run(ast)


__all__ = [
    "InvocationCounts",
    "count_invocations",
    "is_plain_eof_loop",
    "status_sites",
]
