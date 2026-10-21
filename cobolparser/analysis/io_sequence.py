"""
File I/O sequencing validation for COBOL programs.

Walks the AST in execution order and reports violations of the required
OPEN → {READ/WRITE/REWRITE/DELETE/START} → CLOSE lifecycle for each file.

Common bugs caught:
- READ/WRITE/REWRITE/DELETE/START against a file that was never OPENed
- OPEN of a file that is already open (double-open)
- CLOSE of a file that was never opened or already closed
- Files left open at program exit (STOP RUN / GOBACK)
- A verb the OPEN mode does not allow (READ / START on OUTPUT or EXTEND,
  WRITE on INPUT or on a sequential file open I-O, REWRITE / DELETE on a
  file not open I-O: file status 47 / 48 / 49), and an OPEN of a file
  closed WITH LOCK earlier in the run (status 38)
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from ..models.ast_base import ASTNode, SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..models.statements import (
    EvaluateStatement,
    ExitStatement,
    GobackStatement,
    GoStatement,
    IfStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
    MergeStatement,
    PerformStatement,
    SelectStatement,
    SortStatement,
    StopStatement,
)
from ._files import (
    record_to_file_map,
    report_to_file_map,
    report_writer_files,
    resolve_file_name,
)
from ._procedures import ProcedureIndex, statement_qualifier


class IOViolationKind(Enum):
    """Categories of file I/O sequencing violations."""

    READ_BEFORE_OPEN = auto()
    WRITE_BEFORE_OPEN = auto()
    REWRITE_BEFORE_OPEN = auto()
    DELETE_BEFORE_OPEN = auto()
    START_BEFORE_OPEN = auto()
    DOUBLE_OPEN = auto()
    CLOSE_NOT_OPEN = auto()
    DOUBLE_CLOSE = auto()
    FILE_LEFT_OPEN = auto()  # open at STOP RUN / GOBACK / end-of-program
    # A verb the file's OPEN mode does not allow (#548): status 47 / 48 / 49.
    READ_WRONG_MODE = auto()
    START_WRONG_MODE = auto()
    WRITE_WRONG_MODE = auto()
    REWRITE_WRONG_MODE = auto()
    DELETE_WRONG_MODE = auto()
    OPEN_AFTER_LOCK = auto()  # OPEN of a file closed WITH LOCK (status 38)


@dataclass
class IOSequenceViolation:
    """A single file I/O sequencing violation."""

    kind: IOViolationKind
    file_name: str
    location: SourceLocation | None
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "file_name": self.file_name,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location
                else None
            ),
            "message": self.message,
        }


@dataclass
class IOSequenceReport:
    """Result of an I/O sequencing analysis."""

    violations: list[IOSequenceViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict:
        return {
            "has_violations": self.has_violations,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
        }


# Maps verb-to-ViolationKind for unopened-file errors
_OP_TO_VIOLATION: dict[str, IOViolationKind] = {
    "READ": IOViolationKind.READ_BEFORE_OPEN,
    "WRITE": IOViolationKind.WRITE_BEFORE_OPEN,
    "REWRITE": IOViolationKind.REWRITE_BEFORE_OPEN,
    "DELETE": IOViolationKind.DELETE_BEFORE_OPEN,
    "START": IOViolationKind.START_BEFORE_OPEN,
    # Report Writer verbs write the report file (#499).
    "INITIATE": IOViolationKind.WRITE_BEFORE_OPEN,
    "GENERATE": IOViolationKind.WRITE_BEFORE_OPEN,
    "TERMINATE": IOViolationKind.WRITE_BEFORE_OPEN,
}

# Maps verb -> (the OPEN modes it is allowed under, the ViolationKind, the
# file status the runtime returns otherwise). WRITE is further refused on a
# sequential file open I-O (``_write_modes``).
_MODE_RULES: dict[str, tuple[frozenset[str], IOViolationKind, str]] = {
    "READ": (frozenset({"INPUT", "I-O"}), IOViolationKind.READ_WRONG_MODE, "47"),
    "START": (frozenset({"INPUT", "I-O"}), IOViolationKind.START_WRONG_MODE, "47"),
    "WRITE": (
        frozenset({"OUTPUT", "EXTEND", "I-O"}),
        IOViolationKind.WRITE_WRONG_MODE,
        "48",
    ),
    "REWRITE": (frozenset({"I-O"}), IOViolationKind.REWRITE_WRONG_MODE, "49"),
    "DELETE": (frozenset({"I-O"}), IOViolationKind.DELETE_WRONG_MODE, "49"),
}
_SEQUENTIAL_ORGANIZATIONS = frozenset(
    {"SEQUENTIAL", "LINE SEQUENTIAL", "RECORD SEQUENTIAL"}
)

# A file's possible states at a point of the walk. Before an IF/EVALUATE
# every file has exactly one; after one, it holds every state an arm that
# falls out of the branch could have left it in. An open file's state
# carries its OPEN mode (``"open:INPUT"``; ``"open:"`` when the mode is not
# known), so arms that open it in different modes merge into two states
# and no mode violation is claimed unless every path breaks the rule. A
# file closed WITH LOCK is ``locked``: closed, and not reopenable this run.
_OPEN_PREFIX = "open:"
_CLOSED = "closed"
_LOCKED = "locked"
_UNOPENED = "unopened"
_NEVER_OPENED: frozenset[str] = frozenset({_UNOPENED})


def _open_state(mode: str | None) -> str:
    return _OPEN_PREFIX + (mode or "").upper()


def _is_open(state: str) -> bool:
    return state.startswith(_OPEN_PREFIX)


def _any_open(states: frozenset[str]) -> bool:
    return any(_is_open(state) for state in states)


# Upper-cased file name -> the states it may be in; a file not in the map
# has never been opened on any path.
_Status = dict[str, frozenset[str]]
_FrozenStatus = frozenset[tuple[str, frozenset[str]]]


# A step of the execution walk. The walk is written as generators that
# ``yield`` the sub-step they would otherwise call recursively and receive its
# return value back; ``_drive`` runs them off an explicit stack, so a long
# PERFORM chain costs heap, not Python recursion depth.
_Step = Generator["_Step", Any, Any]

_PerformKey = tuple[int, int]
# (range, file states, inside an IF/EVALUATE arm). The last part decides
# whether a STOP RUN the range reaches reports FILE_LEFT_OPEN.
_StateKey = tuple[int, int, _FrozenStatus, bool]

# How an IF/EVALUATE arm ends (``_run_arm``), and how a whole branch does
# (``_fork``): it falls out to the next statement, jumps away with a GO TO,
# or ends the program.
_FALLS = "falls"
_JUMPS = "jumps"
_ENDS = "ends"
_ViolationKey = tuple[Any, ...]


def _merge_into(table: dict[str, _Status], name: str, state: _Status) -> None:
    """Union *state* into ``table[name]`` (see ``IOSequenceAnalyzer._merge``)."""
    previous = table.get(name)
    table[name] = (
        dict(state)
        if previous is None
        else IOSequenceAnalyzer._merge([previous, state])
    )


def _violation_key(v: IOSequenceViolation) -> _ViolationKey:
    loc = v.location
    where = (
        None
        if loc is None
        else (getattr(loc, "file", None), loc.line, getattr(loc, "column", None))
    )
    return (v.kind, v.file_name, where, v.message)


@dataclass
class _Recording:
    """Effects of one PERFORM range while it runs (see ``_run_perform``).

    Effects land on the innermost recording; a finished range's recording
    is merged into the one that PERFORMed it.
    """

    entered: set[_PerformKey] = field(default_factory=set)
    guarded: set[_PerformKey] = field(default_factory=set)
    violations: dict[_ViolationKey, IOSequenceViolation] = field(default_factory=dict)
    # Conditional GO TO target -> the file states at the GO TO(s).
    gotos: dict[str, _Status] = field(default_factory=dict)


@dataclass(frozen=True)
class _RangeSummary:
    """What running a PERFORM range from one entry state did.

    Reusable at any later call site with the same entry state, provided the
    re-entrancy guard would decide the same way: none of ``entered`` is on
    the PERFORM stack, and every key in ``guarded`` (a PERFORM the run
    skipped because an enclosing frame was already running it) still is.
    """

    status_out: _FrozenStatus
    terminated: bool
    violations: tuple[IOSequenceViolation, ...]
    gotos: tuple[tuple[str, _FrozenStatus], ...]
    entered: frozenset[_PerformKey]
    guarded: frozenset[_PerformKey]


class IOSequenceAnalyzer:
    """Analyzes a parsed COBOL AST for file I/O sequencing violations.

    The analyzer walks statements in (approximate) execution order,
    maintaining a set of currently-open files: it starts at the entry
    procedure, follows fall-through and unconditional GO TOs, and inlines
    out-of-line ``PERFORM`` targets (including THRU ranges) at their call
    sites.  It emits a violation for each rule broken.

    Note: this is a conservative static analysis.  Dynamic file names (variables)
    are tracked by their variable name string as-is.  The arms of an IF /
    EVALUATE are forked: each arm runs from the state at the branch, and the
    arms are merged afterwards, so a file may be "open on some paths".  An arm
    that ends in a STOP RUN / GOBACK / EXIT PROGRAM at its own top
    level (or a PERFORMed paragraph's) never reaches the statement after the
    branch and is left out of the merge -- the ``IF bad-status CLOSE f STOP
    RUN`` error exit -- and no FILE_LEFT_OPEN is claimed at that STOP RUN.
    An arm that ends in a GO TO is kept in the merge: its state is where the
    walk will meet the GO TO target, whether by fall-through or later.
    A violation is reported only when it holds on *every* merged path
    (READ of a file open on no path, OPEN of a file open on every path, ...),
    except FILE_LEFT_OPEN, which a file open on any path still earns.
    Other conditional phrases (AT END, INVALID KEY, ...) are not forked.
    Paragraphs unreachable from the entry procedure are not walked at all.
    A violation is reported once per source location, however many call
    sites reach it.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import IOSequenceAnalyzer

        result = parse_cobol(source)
        analyzer = IOSequenceAnalyzer()
        report = analyzer.analyze(result.ast)
        for v in report.violations:
            print(v.message)
    """

    def __init__(self) -> None:
        self._status: _Status = {}
        # IF/EVALUATE arms being run (``_fork``), innermost last.
        self._fork_depth = 0
        self._violations: list[IOSequenceViolation] = []
        self._linear: list[CobolParagraph] = []
        self._name_first: dict[str, int] = {}
        self._name_last: dict[str, int] = {}
        # Procedures are keyed the way ``ProcedureIndex`` keys them: a bare
        # name when it is unique, ``"<para> OF <section>"`` when two sections
        # share it. ``_section_of`` runs parallel to ``_linear``, and
        # ``_current_section`` is the section of the paragraph being walked,
        # which an unqualified GO TO / PERFORM target resolves against.
        self._procedures: ProcedureIndex | None = None
        self._section_of: list[str | None] = []
        self._current_section: str | None = None
        self._perform_stack: list[_PerformKey] = []
        self._perform_set: set[_PerformKey] = set()
        # One entry per PERFORM range currently being run for the first time
        # from its entry state, innermost last.
        self._recordings: list[_Recording] = []
        # (range, file states) -> summaries of earlier runs, so a
        # range PERFORMed from many places is walked once per entry state
        # instead of once per call path (exponential in nesting depth).
        self._summaries: dict[_StateKey, list[_RangeSummary]] = {}
        self._seen_violations: set[_ViolationKey] = set()
        self._terminated = False
        # GO TO targets met inside a conditional branch (``AT END GO TO
        # 9000-EOF``, ``IF ... GO TO ...``), walked once the fall-through
        # chain has looped back on itself.
        self._pending_gotos: list[str] = []  # resolved procedure keys
        # The file states at the GO TO(s) that queued each pending target,
        # merged into the walk's state when it resumes there: by then the
        # walk may have reopened the file in another mode (#548).
        self._pending_states: dict[str, _Status] = {}
        # True once the walk ended because it looped back to a paragraph it
        # had already run, with no STOP RUN/GOBACK reached: whatever is
        # still open then was open *inside* a loop, not at program end.
        self._ended_in_cycle = False
        # FILE SECTION record name -> owning FD/SD name (upper-cased). WRITE
        # and REWRITE name a record, never a file, so without this map they
        # could never be checked against the open-file set at all.
        self._record_to_file: dict[str, str] = {}
        # Report Writer report / report-group name -> its report file.
        self._report_to_file: dict[str, str] = {}
        # SELECT file name -> ORGANIZATION (upper-cased; a SELECT without
        # the clause is the default, SEQUENTIAL). Only WRITE under I-O
        # depends on it. A file whose SELECT is not in the AST (one in a
        # COPY member that was not expanded) is absent: its organization is
        # unknown, so its WRITE under I-O is not judged.
        self._organization: dict[str, str] = {}

    def analyze(self, ast: CobolProgram) -> IOSequenceReport:
        """Analyze the AST and return an IOSequenceReport.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            IOSequenceReport containing all detected violations.
        """
        self._status = {}
        self._fork_depth = 0
        self._violations = []
        self._linear = []
        self._name_first = {}
        self._name_last = {}
        self._procedures = None
        self._section_of = []
        self._current_section = None
        self._perform_stack = []
        self._perform_set = set()
        self._recordings = []
        self._summaries = {}
        self._seen_violations = set()
        self._terminated = False
        self._pending_gotos = []
        self._pending_states = {}
        self._ended_in_cycle = False
        self._record_to_file = record_to_file_map(ast)
        self._report_to_file = report_to_file_map(ast)
        self._organization = {
            select.file_name.upper(): (select.organization or "SEQUENTIAL").upper()
            for select in ast.find_all_by_type("SelectStatement")
            if isinstance(select, SelectStatement) and select.file_name
        }

        proc_division = ast.procedure_division
        if proc_division is not None:
            self._collect_procedures(proc_division)
            if self._linear:
                self._run_chain(0)
        # Any files still open at end-of-program are violations -- unless
        # the walk never reached the end of the program: it stopped at a
        # loop it could not see out of, so "still open" is only "open at the
        # point the walk gave up".
        leftover = () if self._ended_in_cycle else self._maybe_open_files()
        for file_name in leftover:
            self._emit(
                IOSequenceViolation(
                    kind=IOViolationKind.FILE_LEFT_OPEN,
                    file_name=file_name,
                    location=None,
                    message=(
                        f"File '{file_name}' is still open at end of program "
                        "(missing CLOSE statement)"
                    ),
                )
            )
        return IOSequenceReport(violations=list(self._violations))

    # ------------------------------------------------------------------
    # Internal traversal (execution order)
    # ------------------------------------------------------------------
    #
    # The walk approximates execution order rather than source order: it
    # starts at the entry procedure and follows fall-through, inlines
    # out-of-line PERFORM targets (and THRU ranges) at their call sites, and
    # follows a paragraph's own unconditional GO TO. Without this, the
    # canonical correct COBOL shape — OPEN/READ in a main paragraph that
    # PERFORMs a WRAP-UP paragraph declared after it — produced
    # CLOSE_NOT_OPEN + FILE_LEFT_OPEN false positives, because the CLOSE was
    # visited in declaration order before its PERFORM site. IF / EVALUATE
    # arms are forked and merged (``_fork``, see the class docstring); a PERFORM
    # recursion guard and per-chain visited sets keep GO TO cycles finite.

    def _collect_procedures(self, proc_division: CobolDivision) -> None:
        """Build the source-ordered paragraph list and name → range maps.

        Sections and top-level paragraphs are interleaved by source line
        (paragraphs may legally precede the first SECTION header — same
        observation ``dead_code.py`` makes). A section's name maps to the
        range spanning all its paragraphs, so ``PERFORM section-name`` and
        THRU endpoints resolve correctly.
        """

        def _line(node: ASTNode) -> int:
            loc = getattr(node, "location", None)
            return loc.line if loc is not None else 0

        entities: list[CobolSection | CobolParagraph] = [
            *proc_division._sections.values(),
            *proc_division.paragraphs,
        ]
        entities.sort(key=_line)

        self._procedures = ProcedureIndex.build(proc_division)
        keys = {id(e.node): e.key for e in self._procedures.entries}

        for entity in entities:
            if isinstance(entity, CobolSection):
                # A DECLARATIVES section is a USE procedure the runtime
                # invokes on an I/O error (or before a report group); it is
                # not on the fall-through path and cannot be PERFORMed, so
                # walking it inline reported its WRITE/CLOSE against a file
                # state it never runs in (WRITE before OPEN, and so on).
                if entity.is_declarative:
                    continue
                sec_name = (entity.section_name or "").upper()
                start = len(self._linear)
                for para in entity.paragraphs:
                    self._register_paragraph(para, keys, sec_name or None)
                if sec_name and entity.paragraphs:
                    self._name_first.setdefault(sec_name, start)
                    self._name_last[sec_name] = max(
                        self._name_last.get(sec_name, start), len(self._linear) - 1
                    )
            elif isinstance(entity, CobolParagraph):
                self._register_paragraph(entity, keys, None)

    def _register_paragraph(
        self, para: CobolParagraph, keys: dict[int, str], section: str | None
    ) -> None:
        idx = len(self._linear)
        self._linear.append(para)
        self._section_of.append(section)
        # A paragraph the index dropped (a second same-named paragraph in
        # one section, which the compiler rejects) keeps its bare name.
        name = keys.get(id(para)) or (para.paragraph_name or "").upper()
        if name:
            self._name_first.setdefault(name, idx)
            self._name_last.setdefault(name, idx)

    def _resolve(self, name: str | None, qualifier: str | None = None) -> str:
        """The procedure key a reference to *name* means from the paragraph
        being walked.

        COBOL resolves an unqualified paragraph name to the one in the
        referencing section first, so with a ``SEC-EXIT`` in every section a
        ``GO TO SEC-EXIT`` stays in its own section (issue #335). A reference
        the compiler would reject as ambiguous takes the first candidate.
        """
        upper = (name or "").upper()
        if self._procedures is None:
            return upper
        for key in self._procedures.resolve(name, qualifier, self._current_section):
            if key in self._name_first:
                return key
        return upper

    def _run_chain(self, start_idx: int) -> None:
        """Fall-through execution from *start_idx*, following GO TOs.

        When the chain loops back to a paragraph it already ran -- the
        ``READ ... AT END GO TO END-P`` / ``GO TO LOOP-P`` idiom -- the walk
        resumes at a GO TO target it met inside a conditional branch and has
        not run yet (from the state the walk is in at that point, merged
        with the state at the GO TO), since that is how such a loop is
        left. Without it, the CLOSE in the loop's
        exit paragraph was never seen and the file was reported left open.
        """
        visited: set[int] = set()
        idx: int | None = start_idx
        while not self._terminated:
            if idx is not None and idx in visited:
                idx = self._next_pending(visited)
                if idx is None:
                    self._ended_in_cycle = True
                    return
            if idx is None or not 0 <= idx < len(self._linear):
                return
            visited.add(idx)
            outcome, target = self._drive(self._run_paragraph(idx))
            if self._terminated or outcome == "stop":
                return
            if outcome == "goto":
                idx = self._name_first.get(target or "")
                continue
            idx += 1

    def _next_pending(self, visited: set[int]) -> int | None:
        """The next conditional GO TO target the chain has not run yet."""
        while self._pending_gotos:
            name = self._pending_gotos.pop(0)
            idx = self._name_first.get(name)
            if idx is not None and idx not in visited:
                saved = self._pending_states.get(name)
                if saved is not None:
                    self._status = self._merge([self._status, saved])
                return idx
        return None

    @staticmethod
    def _drive(step: _Step) -> Any:
        """Run *step* to completion off an explicit stack; return its value."""
        stack: list[_Step] = [step]
        value: Any = None
        while stack:
            try:
                sub = stack[-1].send(value)
            except StopIteration as done:
                stack.pop()
                value = done.value
                continue
            stack.append(sub)
            value = None
        return value

    def _run_paragraph(self, idx: int) -> _Step:
        """Process paragraph *idx*'s statements; report how it ends.

        Returns ``("fall", None)``, ``("stop", None)``, or
        ``("goto", target-key)``.
        """
        para = self._linear[idx]
        self._current_section = self._section_of[idx]
        for stmt in para.statements:
            if self._terminated:
                break
            if (
                isinstance(stmt, GoStatement)
                and stmt.target_paragraph
                and not stmt.depending_on_variable
            ):
                return (
                    "goto",
                    self._resolve(
                        stmt.target_paragraph,
                        statement_qualifier(stmt, "target_qualifier"),
                    ),
                )
            if self._is_program_end(stmt):
                yield self._process_statement(stmt)
                self._terminate_program(getattr(stmt, "location", None))
                self._terminated = True
                return ("stop", None)
            outcome = yield self._process_statement(stmt)
            if outcome == _ENDS:
                # Every arm of this IF/EVALUATE ends the program: what
                # follows it in the paragraph is never run.
                self._status = {}
                self._terminated = True
                return ("stop", None)
        return ("fall", None)

    @staticmethod
    def _is_program_end(stmt: ASTNode) -> bool:
        """STOP RUN / GOBACK / EXIT PROGRAM at a paragraph's top level."""
        if isinstance(stmt, GobackStatement):
            return True
        if isinstance(stmt, StopStatement):
            return stmt.stop_type == "RUN"
        if isinstance(stmt, ExitStatement):
            return getattr(stmt, "exit_type", None) == "PROGRAM"
        return False

    def _process_statement(self, stmt: ASTNode) -> _Step:
        """Dispatch *stmt* and its nested statements in declaration order,
        inlining out-of-line PERFORM targets -- and SORT/MERGE INPUT/OUTPUT
        PROCEDUREs, which the sort runs exactly like a PERFORM of the named
        range -- at their call sites.

        Returns how an IF/EVALUATE *stmt* ends (see ``_fork``), else None.
        """
        visited: set[int] = set()

        def _visit(node: ASTNode) -> _Step:
            if id(node) in visited or self._terminated:
                return None
            visited.add(id(node))
            if isinstance(node, (IfStatement, EvaluateStatement)):
                return (yield self._fork(node, _visit))
            self._dispatch(node)
            if isinstance(node, GoStatement):
                # Reached through _visit, so nested in a branch or handler
                # (a paragraph's own top-level GO TO never gets here).
                qualifier = statement_qualifier(node, "target_qualifier")
                for name in node.target_paragraphs:
                    if name:
                        self._add_pending_goto(
                            self._resolve(
                                name,
                                qualifier if name == node.target_paragraph else None,
                            )
                        )
            if (
                isinstance(node, PerformStatement)
                and node.target_paragraph
                and not node.inline_statements
            ):
                yield self._run_perform(
                    node.target_paragraph,
                    node.thru_paragraph,
                    statement_qualifier(node, "target_qualifier"),
                    statement_qualifier(node, "thru_qualifier"),
                )
            elif isinstance(node, SortStatement):
                if node.input_procedure:
                    yield self._run_perform(
                        node.input_procedure, node.input_procedure_thru
                    )
                if node.output_procedure:
                    yield self._run_perform(
                        node.output_procedure, node.output_procedure_thru
                    )
            elif isinstance(node, MergeStatement):
                if node.output_procedure:
                    yield self._run_perform(
                        node.output_procedure, node.output_procedure_thru
                    )
            if hasattr(node, "children"):
                for child in node.children:
                    yield _visit(child)
            return None

        return (yield _visit(stmt))

    @staticmethod
    def _arms(node: IfStatement | EvaluateStatement) -> list[list[ASTNode]]:
        """The statement lists one execution of *node* may run, one per arm.

        An IF without ELSE, and an EVALUATE without WHEN OTHER, has an empty
        arm: no WHEN matched / the condition was false.
        """
        if isinstance(node, IfStatement):
            return [list(node.then_statements), list(node.else_statements)]
        arms: list[list[ASTNode]] = [
            list(group[-1].statements) for group in node.when_groups()
        ]
        arms.append(list(node.default_when.statements) if node.default_when else [])
        return arms

    def _fork(
        self,
        node: IfStatement | EvaluateStatement,
        visit: Callable[[ASTNode], _Step],
    ) -> _Step:
        """Run each arm of *node* from the state at the branch, then merge.

        An arm that ends the program (see ``_run_arm``) is left out of the
        merge. An arm that jumps away with a GO TO is kept: the walk meets
        its target later (by fall-through in a ``THRU ...-EXIT`` range, or as
        a queued GO TO target), and the state it carries there is the
        merged one. Returns ``_ENDS`` when every arm ends the program,
        ``_JUMPS`` when none falls out but some jump, else ``_FALLS``.
        """
        entry = dict(self._status)
        kept: list[_Status] = []
        every: list[_Status] = []
        endings: set[str] = set()
        self._fork_depth += 1
        try:
            for arm in self._arms(node):
                self._status = dict(entry)
                ending = yield self._run_arm(arm, visit)
                if self._terminated:
                    # A PERFORMed paragraph ran a top-level STOP RUN /
                    # GOBACK: that ends this arm's path, not every path
                    # through here.
                    self._terminated = False
                    ending = _ENDS
                endings.add(ending)
                every.append(self._status)
                if ending != _ENDS:
                    kept.append(self._status)
        finally:
            self._fork_depth -= 1
        # Every arm ends the program: whatever follows is dead from here.
        # Merge every arm anyway, so the walk carries on from a state it
        # could be in.
        self._status = self._merge(kept or every)
        if _FALLS in endings:
            return _FALLS
        return _JUMPS if _JUMPS in endings else _ENDS

    def _run_arm(
        self, stmts: list[ASTNode], visit: Callable[[ASTNode], _Step]
    ) -> _Step:
        """Run one branch arm; return how it ends (``_FALLS`` / ``_JUMPS`` /
        ``_ENDS``)."""
        for stmt in stmts:
            if self._terminated:
                return _ENDS
            if isinstance(stmt, (IfStatement, EvaluateStatement)):
                ending = yield self._fork(stmt, visit)
                if ending != _FALLS:
                    return ending
                continue
            yield visit(stmt)
            if (
                isinstance(stmt, GoStatement)
                and stmt.target_paragraph
                and not stmt.depending_on_variable
            ):
                # The target is queued (``_add_pending_goto``) by ``visit``.
                return _JUMPS
            if self._is_program_end(stmt):
                # Not ``_terminate_program``: the arm is the error exit of a
                # guard, and a file it leaves open -- the one whose OPEN just
                # failed -- is not a finding.
                return _ENDS
        return _ENDS if self._terminated else _FALLS

    @staticmethod
    def _merge(states: list[_Status]) -> _Status:
        """Union of each file's possible states across *states*."""
        merged: _Status = {}
        for key in {k for state in states for k in state}:
            merged[key] = frozenset().union(
                *(state.get(key, _NEVER_OPENED) for state in states)
            )
        return merged

    def _states(self, key: str) -> frozenset[str]:
        return self._status.get(key, _NEVER_OPENED)

    def _maybe_open_files(self) -> list[str]:
        return sorted(k for k, v in self._status.items() if _any_open(v))

    def _run_perform(
        self,
        target: str,
        thru: str | None,
        target_qualifier: str | None = None,
        thru_qualifier: str | None = None,
    ) -> _Step:
        """Execute a ``PERFORM target [THRU end]`` range at the call site.

        The first run of a range from a given entry state (every file's
        possible states) is recorded as a ``_RangeSummary``; a later PERFORM of the
        same range from the same state replays the summary instead of
        walking the paragraphs again.
        """
        target_key = self._resolve(target, target_qualifier)
        start = self._name_first.get(target_key)
        if start is None:
            return
        end_key = self._resolve(thru, thru_qualifier) if thru else target_key
        end = self._name_last.get(end_key, self._name_last.get(target_key, start))
        if end < start:
            end = start
        key = (start, end)
        if key in self._perform_set:
            # Re-entrant PERFORM: recursion guard. The range being recorded
            # made this decision off the current stack.
            if self._recordings:
                self._recordings[-1].guarded.add(key)
            return

        state: _StateKey = (
            start,
            end,
            frozenset(self._status.items()),
            self._fork_depth > 0,
        )
        for summary in self._summaries.get(state, ()):
            if summary.entered.isdisjoint(self._perform_set) and (
                summary.guarded <= self._perform_set
            ):
                self._replay(summary)
                return

        rec = _Recording(entered={key})
        self._recordings.append(rec)
        self._perform_stack.append(key)
        self._perform_set.add(key)
        caller_section = self._current_section
        try:
            yield self._walk_range(start, end)
        finally:
            self._current_section = caller_section
            self._perform_stack.pop()
            self._perform_set.discard(key)
            self._recordings.pop()
        if self._recordings:
            # Whatever this range did, the range that PERFORMed it did too.
            outer = self._recordings[-1]
            outer.entered |= rec.entered
            outer.guarded |= rec.guarded
            for vkey, violation in rec.violations.items():
                outer.violations.setdefault(vkey, violation)
            for name, at_goto in rec.gotos.items():
                _merge_into(outer.gotos, name, at_goto)
        self._summaries.setdefault(state, []).append(
            _RangeSummary(
                status_out=frozenset(self._status.items()),
                terminated=self._terminated,
                violations=tuple(rec.violations.values()),
                gotos=tuple(
                    (name, frozenset(at_goto.items()))
                    for name, at_goto in rec.gotos.items()
                ),
                entered=frozenset(rec.entered),
                # A guard hit on a range this run itself entered is internal
                # to it; only the enclosing frames' ranges are a dependency.
                guarded=frozenset(rec.guarded - rec.entered),
            )
        )

    def _walk_range(self, start: int, end: int) -> _Step:
        """Run paragraphs *start*..*end*, following GO TOs inside the range."""
        visited: set[int] = set()
        i = start
        while i <= end and not self._terminated and i not in visited:
            visited.add(i)
            outcome, gtarget = yield self._run_paragraph(i)
            if outcome == "stop":
                return
            if outcome == "goto":
                t = self._name_first.get(gtarget or "")
                # Follow a GO TO only within the performed range; a jump
                # out of the range ends the PERFORM conservatively.
                if t is not None and start <= t <= end:
                    i = t
                    continue
                return
            i += 1

    def _replay(self, summary: _RangeSummary) -> None:
        """Apply a recorded range's effects at another call site."""
        self._status = dict(summary.status_out)
        for violation in summary.violations:
            self._emit(violation)
        for name, at_goto in summary.gotos:
            self._add_pending_goto(name, dict(at_goto))
        if self._recordings:
            rec = self._recordings[-1]
            rec.entered |= summary.entered
            rec.guarded |= summary.guarded
        if summary.terminated:
            self._terminated = True

    def _emit(self, violation: IOSequenceViolation) -> None:
        """Report *violation* once, and to every range being recorded."""
        vkey = _violation_key(violation)
        if self._recordings:
            self._recordings[-1].violations.setdefault(vkey, violation)
        if vkey not in self._seen_violations:
            self._seen_violations.add(vkey)
            self._violations.append(violation)

    def _add_pending_goto(self, name: str, at_goto: _Status | None = None) -> None:
        """Queue a conditional GO TO target for ``_run_chain``, with the
        file states at the GO TO (*at_goto*, default the current ones)."""
        state = dict(self._status) if at_goto is None else at_goto
        if self._recordings:
            _merge_into(self._recordings[-1].gotos, name, state)
        _merge_into(self._pending_states, name, state)
        if name not in self._pending_gotos:
            self._pending_gotos.append(name)

    def _dispatch(self, node: ASTNode) -> None:
        """Handle a single node if it is an IO-relevant statement."""
        loc = getattr(node, "location", None)

        if isinstance(node, IOOpenStatement):
            self._handle_open(node, loc)
        elif isinstance(node, IOCloseStatement):
            self._handle_close(node, loc)
        elif isinstance(node, IOReadStatement):
            self._check_open(node.file_name or "", "READ", loc)
        elif isinstance(node, IOWriteStatement):
            # WRITE names a record, not a file. The parser never sets
            # file_name for it, so the record is resolved to the FD that
            # owns it (FILE SECTION metadata); a record no FD claims stays
            # unchecked rather than guessed.
            self._check_open(
                self._file_for(node.file_name, node.record_name) or "", "WRITE", loc
            )
        elif isinstance(node, IORewriteStatement):
            # Same as WRITE: REWRITE names the record.
            self._check_open(
                self._file_for(node.file_name, node.record_name) or "",
                "REWRITE",
                loc,
            )
        elif isinstance(node, IODeleteStatement):
            self._check_open(node.file_name or "", "DELETE", loc)
        elif isinstance(node, IOStartStatement):
            self._check_open(node.file_name or "", "START", loc)
        else:
            # INITIATE / GENERATE / TERMINATE write the file whose
            # ``FD ... REPORT IS`` names the report: it must be open.
            for file_name in report_writer_files(node, self._report_to_file):
                self._check_open(file_name, getattr(node, "statement_type", ""), loc)
        # GOBACK / STOP RUN are intentionally NOT handled here. _dispatch()
        # is reached for every nested statement, including ones in an
        # IF/EVALUATE arm, where it ends only that arm's path: _run_arm
        # drops the arm from the merge instead (the common
        # `IF NOT WS-FILE-OK STOP RUN END-IF` guard right after an OPEN).
        # Only a GOBACK/STOP RUN reached as a paragraph's own top-level
        # statement ends the walk; that case is handled by
        # _terminate_program(), called from _run_paragraph.

    def _file_for(self, file_name: str | None, record_name: str | None) -> str | None:
        """The file a WRITE/REWRITE targets, via its record's FD."""
        return resolve_file_name(file_name, record_name, self._record_to_file)

    def _terminate_program(self, loc: SourceLocation | None) -> None:
        """Record FILE_LEFT_OPEN for still-open files and clear I/O state.

        Called only when a GOBACK / STOP RUN is a paragraph's own top-level
        statement (see ``_is_program_end``) -- i.e. unconditionally reached.
        Inside an IF/EVALUATE arm (a PERFORMed abend paragraph under an
        ``IF bad-status`` guard) no FILE_LEFT_OPEN is claimed, the same as
        for a STOP RUN written in the arm itself (see ``_run_arm``).
        Only STOP RUN terminates the program -- STOP 'literal' merely pauses
        pending operator action and execution then continues, so it must not
        reset the open-file state (same distinction dead_code.py's and
        program_flow/scanner.py's _is_terminator draw).
        """
        leftover = [] if self._fork_depth else self._maybe_open_files()
        for file_name in leftover:
            self._emit(
                IOSequenceViolation(
                    kind=IOViolationKind.FILE_LEFT_OPEN,
                    file_name=file_name,
                    location=loc,
                    message=(
                        f"File '{file_name}' is still open when program "
                        "terminates (STOP RUN / GOBACK)"
                    ),
                )
            )
        self._status = {}

    def _handle_open(self, node: IOOpenStatement, loc: SourceLocation | None) -> None:
        """Process an OPEN statement."""
        files = self._get_open_files(node)
        modes = getattr(node, "file_modes", None) or {}
        for file_name in files:
            if not file_name.strip():
                continue  # Skip empty/whitespace names
            key = file_name.upper()
            states = self._states(key)
            if states == frozenset({_LOCKED}):
                # Closed WITH LOCK on every path: the OPEN fails (status
                # 38) and the file stays closed -- no FILE_LEFT_OPEN either.
                self._emit(
                    IOSequenceViolation(
                        kind=IOViolationKind.OPEN_AFTER_LOCK,
                        file_name=file_name,
                        location=loc,
                        message=(
                            f"OPEN of file '{file_name}' that was closed WITH "
                            "LOCK earlier in the run (file status 38)"
                        ),
                    )
                )
                continue
            if all(_is_open(state) for state in states):
                self._emit(
                    IOSequenceViolation(
                        kind=IOViolationKind.DOUBLE_OPEN,
                        file_name=file_name,
                        location=loc,
                        message=f"File '{file_name}' is already open (duplicate OPEN)",
                    )
                )
            # Open on every path now, whether or not it was before.
            self._status[key] = frozenset({_open_state(modes.get(file_name))})

    def _handle_close(self, node: IOCloseStatement, loc: SourceLocation | None) -> None:
        """Process a CLOSE statement."""
        files = self._get_close_files(node)
        options = getattr(node, "close_options", None) or {}
        for file_name in files:
            if not file_name.strip():
                continue  # Skip empty/whitespace names
            # CLOSE f REEL / UNIT closes only the current volume: the file
            # itself stays open (a later READ, or a plain CLOSE f, is legal).
            opts = options.get(file_name) or {}
            if opts.get("reel") or opts.get("unit"):
                continue
            key = file_name.upper()
            states = self._states(key)
            if _any_open(states):
                # Closed on every path now; one where it was never open is
                # not reported (see the class docstring).
                closed = _LOCKED if opts.get("with_lock") else _CLOSED
                self._status[key] = frozenset({closed})
            elif _CLOSED in states or _LOCKED in states:
                self._emit(
                    IOSequenceViolation(
                        kind=IOViolationKind.DOUBLE_CLOSE,
                        file_name=file_name,
                        location=loc,
                        message=f"CLOSE of file '{file_name}' that is already closed (duplicate CLOSE)",
                    )
                )
            else:
                self._emit(
                    IOSequenceViolation(
                        kind=IOViolationKind.CLOSE_NOT_OPEN,
                        file_name=file_name,
                        location=loc,
                        message=(f"CLOSE of file '{file_name}' that was never opened"),
                    )
                )

    def _check_open(
        self, file_name: str, verb: str, loc: SourceLocation | None
    ) -> None:
        """Emit a violation if *file_name* is not currently open, or is
        open on every path in a mode that does not allow *verb*."""
        if not file_name:
            return  # Cannot determine file name statically
        key = file_name.upper()
        states = self._states(key)
        if _any_open(states):
            self._check_mode(file_name, key, states, verb, loc)
            return
        kind = _OP_TO_VIOLATION.get(verb, IOViolationKind.READ_BEFORE_OPEN)
        self._emit(
            IOSequenceViolation(
                kind=kind,
                file_name=file_name,
                location=loc,
                message=(f"{verb} on file '{file_name}' before it was OPENed"),
            )
        )

    def _check_mode(
        self,
        file_name: str,
        key: str,
        states: frozenset[str],
        verb: str,
        loc: SourceLocation | None,
    ) -> None:
        """Emit a ``*_WRONG_MODE`` violation when every path has *key* open
        in a known mode that refuses *verb* (#548)."""
        rule = _MODE_RULES.get(verb)
        if rule is None or not all(_is_open(state) for state in states):
            return
        allowed, kind, status = rule
        if verb == "WRITE" and (
            # No SELECT in sight: I-O may be an indexed / relative file's
            # legal WRITE mode, so it is not refused.
            self._organization.get(key, "")
            in _SEQUENTIAL_ORGANIZATIONS
        ):
            # A sequential file open I-O can be READ and REWRITten, never
            # written to: WRITE needs OUTPUT or EXTEND.
            allowed = allowed - {"I-O"}
        modes = {state[len(_OPEN_PREFIX) :] for state in states}
        if "" in modes or modes & allowed:
            return
        shown = " / ".join(sorted(modes))
        self._emit(
            IOSequenceViolation(
                kind=kind,
                file_name=file_name,
                location=loc,
                message=(
                    f"{verb} on file '{file_name}' opened {shown}, which does "
                    f"not allow it (file status {status})"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Helpers to extract file names from IO nodes
    # ------------------------------------------------------------------

    @staticmethod
    def _get_open_files(node: IOOpenStatement) -> list[str]:
        """Return the list of file names in an OPEN statement.

        IOOpenStatement uses ``file_names`` (a list) populated via add_file().
        We fall back to the legacy ``open_files`` attribute and finally to
        ``operands`` for forward-compatibility.
        """
        names: list[str] = []
        # Primary path: IOOpenStatement.file_names (list[str])
        if hasattr(node, "file_names") and node.file_names:
            names.extend(node.file_names)
            return names
        # Legacy / alternative path: open_files (list of str or dict)
        if hasattr(node, "open_files") and node.open_files:
            for entry in node.open_files:
                if isinstance(entry, dict):
                    name = entry.get("file_name") or entry.get("name") or ""
                    if name:
                        names.append(str(name))
                elif isinstance(entry, str):
                    names.append(entry)
            if names:
                return names
        # Singular file_name attribute
        if hasattr(node, "file_name") and node.file_name:
            names.append(node.file_name)
            return names
        # Last resort: operands list
        if hasattr(node, "operands"):
            names.extend(node.operands)
        return names

    @staticmethod
    def _get_close_files(node: IOCloseStatement) -> list[str]:
        """Return the list of file names in a CLOSE statement."""
        names: list[str] = []
        if hasattr(node, "file_names") and node.file_names:
            names.extend(node.file_names)
        elif hasattr(node, "file_name") and node.file_name:
            names.append(node.file_name)
        if not names and hasattr(node, "operands"):
            names.extend(node.operands)
        return names
