"""Boundary inventory: every external touchpoint of a program's PROCEDURE DIVISION.

Phase 2 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md`). Walks the
PROCEDURE DIVISION and emits one :class:`Boundary` per mockable statement
(CALL/DYNCALL, the eight file-op verbs, EXEC SQL/CICS/DLI, console ACCEPT),
using the same `(category, key)` convention mockymock's own ``mock_surface``
module uses -- the two are independent walks over the same AST that must
agree on keys, not a shared implementation (the dependency direction is
mockymock -> cobol-parser, never the reverse; see that module's own
docstring in the sibling repo).

Each boundary's record/field layout is resolved through a
:class:`~cobolparser.generators.data.program_layout.ProgramLayoutIndex`
built for the same program (Phase 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.sql_statements import (
    ExecSQLStatement,
    FetchStatement,
    _strip_sql_literals_and_comments,
)
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
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
    DisplayStatement,
    InitializeStatement,
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
from ..models.statements.misc import MergeStatement, SortStatement
from ..parsers.statements.ibm_exec_statements import ExecCicsStatement, ExecImsStatement
from ._names import RELAXED_IDENTIFIER_TOKEN_RE, callee_names
from .host_var_resolver import _QUALIFIED_HOST_VAR_RE
from .value_tracker import DynamicCallAnalyzer

if TYPE_CHECKING:
    # Deferred: cobolparser.generators (reached via generators/__init__.py's
    # own import chain) imports this module back at runtime -- see
    # generators/program_fixtures.py, which genuinely constructs
    # BoundaryInventoryAnalyzer -- so a top-level import here would be
    # circular. Every use below is a type annotation only; `from __future__
    # import annotations` keeps it a lazy string at runtime.
    from ..generators.data.program_layout import ProgramLayoutIndex

# -- statement-walk discipline ------------------------------------------------
#
# Mirrors the walking discipline mockymock's own `mock_surface.py` and this
# repo's `IOLogger` both converged on independently: a fixed set of
# nested-body attributes, recursed via getattr() (CobolStatement's base class
# defines none of them, so a plain getattr(..., None) never misfires on an
# unrelated statement type), plus two shapes that need special-casing.

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
    "on_exception",
    "not_on_exception",
    "on_overflow",
    "not_on_overflow",
    "on_size_error",
    "not_on_size_error",
)

# Which of the generic clause attributes above signal a *declared error
# handler* on a boundary statement (as opposed to just being a nested-body
# source) -- feeds Boundary.handlers, which later phases use to decide which
# error-status scenarios the program actually has a path for.
_HANDLER_LABELS: tuple[tuple[str, str], ...] = (
    ("at_end_clause", "AT_END"),
    ("invalid_key_clause", "INVALID_KEY"),
    ("on_exception", "ON_EXCEPTION"),
    ("on_overflow", "ON_OVERFLOW"),
    ("at_eop_clause", "AT_EOP"),
)

# ACCEPT sources that never read the console: system registers and runtime
# values GnuCOBOL resolves without touching stdin. Mirrors mockymock's
# `_NON_INTERACTIVE_ACCEPT_SOURCES` (re-derived independently, not imported --
# see module docstring).
_NON_INTERACTIVE_ACCEPT_SOURCES = frozenset(
    {
        "DATE",
        "DAY",
        "DAY-OF-WEEK",
        "TIME",
        "COMMAND-LINE",
        "ENVIRONMENT",
        "ENVIRONMENT-VALUE",
        "ARGUMENT-NUMBER",
        "ARGUMENT-VALUE",
    }
)

# SQL types that read data the program did not supply (a boundary that feeds
# the program). Everything else that mutates (INSERT/UPDATE/DELETE) is OUT;
# anything else again (OPEN/CLOSE/COMMIT/ROLLBACK/DECLARE/...) is status-only.
_SQL_IN_TYPES = frozenset({"SELECT", "FETCH"})
_SQL_OUT_TYPES = frozenset({"INSERT", "UPDATE", "DELETE"})


def _write_targets(statement: Any) -> list[str]:
    """Every name `statement` writes to, for the CALL argument-direction ladder.

    ``.targets`` is shared verbatim by MOVE, ADD/SUBTRACT/MULTIPLY/DIVIDE
    (`ArithmeticStatement`), COMPUTE, INITIALIZE, and SET -- a `CALCULATOR`
    subprogram writing its result via `COMPUTE LK-RESULT = ...` is exactly
    why arithmetic must count here, not just MOVE. ``.givings`` covers the
    arithmetic GIVING clause. ``.into_target``/``.into_targets`` covers
    READ INTO and STRING/UNSTRING (the latter a list of dicts).
    """
    names: list[str] = []
    givings = getattr(statement, "givings", None) or []
    if not (isinstance(statement, ArithmeticStatement) and givings):
        # ``ADD A TO B GIVING C`` keeps ``B`` in ``.targets``/``.target``,
        # but with GIVING only ``C`` is stored -- ``B`` is merely read.
        names.extend(getattr(statement, "targets", None) or [])
        single = getattr(statement, "target", None)
        if single:
            names.append(single)
    names.extend(givings)
    remainder = getattr(statement, "remainder", None)
    if isinstance(remainder, str) and remainder:
        names.append(remainder)
    into_target = getattr(statement, "into_target", None)
    if into_target:
        names.append(into_target)
    for entry in getattr(statement, "into_targets", None) or []:
        # UNSTRING's ``into_targets`` entries carry the receiving field under
        # "target" (see UnstringStatement.add_into_target); "name" is kept
        # for any hand-built dict shaped the older way.
        name = (
            (entry.get("target") or entry.get("name"))
            if isinstance(entry, dict)
            else None
        )
        if name:
            names.append(name)
        if isinstance(entry, dict):
            for key in ("delimiter_var", "count_var"):
                if entry.get(key):
                    names.append(entry[key])
    if isinstance(statement, (StringStatement, UnstringStatement)):
        # POINTER is read *and* written; TALLYING is incremented in place.
        for attr in ("pointer_variable", "tallying_variable"):
            value = getattr(statement, attr, None)
            if value:
                names.append(value)
    return names


def _write_shaped_read_names(statement: Any) -> list[str] | None:
    """Names a write-shaped statement *reads* (its own write targets excluded
    unless the verb also reads them), or None when this module cannot tell
    precisely for this statement type.

    - MOVE reads its ``.source``.
    - ADD/SUBTRACT/MULTIPLY/DIVIDE read every operand except the GIVING and
      REMAINDER receivers: without GIVING the TO/FROM/BY/INTO target is both
      read and written (``ADD A TO B`` computes ``B + A``).
    - COMPUTE reads every name in its expression.
    - STRING reads its sending operands, identifier delimiters and POINTER;
      UNSTRING its source, delimiters, POINTER and TALLYING counter.
    - SET reads its ``.value`` (and the target too for UP BY / DOWN BY).
    - INITIALIZE reads its REPLACING ... BY values.
    """
    if isinstance(statement, MoveStatement):
        source = statement.source
        return [source] if isinstance(source, str) and source else []
    if isinstance(statement, ArithmeticStatement):
        receivers = {name.upper() for name in statement.givings}
        remainder = getattr(statement, "remainder", None)  # DIVIDE only
        if isinstance(remainder, str) and remainder:
            receivers.add(remainder.upper())
        return [op for op in statement.operands if op.upper() not in receivers]
    if isinstance(statement, ComputeStatement):
        tree = statement.expression_tree
        names = (
            _condition_field_names(tree) if isinstance(tree, CobolExpression) else []
        )
        # The string form is always captured; tokenizing it over-approximates
        # (a FUNCTION name is included too) but every name is only ever
        # compared against the argument, and it covers tree shapes the walk
        # above skips.
        text = statement.expression
        if isinstance(text, str):
            names.extend(RELAXED_IDENTIFIER_TOKEN_RE.findall(text))
        return names
    if isinstance(statement, StringStatement):
        names = list(statement.operands) + list(statement.delimiters)
        if statement.pointer_variable:
            names.append(statement.pointer_variable)
        return names
    if isinstance(statement, UnstringStatement):
        names = list(statement.delimiters)
        for value in (
            statement.source_operand,
            statement.pointer_variable,
            statement.tallying_variable,
        ):
            if value:
                names.append(value)
        return names
    if isinstance(statement, SetStatement):
        names = [statement.value] if statement.value else []
        if statement.set_type in ("UP_BY", "DOWN_BY"):
            names.extend(statement.targets)
        return names
    if isinstance(statement, InitializeStatement):
        return [
            clause["by_value"]
            for clause in statement.replacing_clauses
            if clause.get("by_value")
        ]
    return None


def _procedure_using_names(ast: CobolProgram) -> list[str]:
    """The callee's ``PROCEDURE DIVISION USING`` operands, uppercased and in
    calling order -- without the ``RETURNING`` item the parser keeps in the
    same list (see ``ProgramSignatureExtractor``)."""
    procedure = ast.get_division("PROCEDURE")
    if procedure is None:
        return []
    names = [
        str(name).strip().upper()
        for name in procedure.get_metadata("using_parameters") or []
        if str(name).strip()
    ]
    if "RETURNING" in names:
        names = names[: names.index("RETURNING")]
    return names


def _condition_field_names(expr: CobolExpression | None) -> list[str]:
    """Every bare operand string anywhere in *expr*'s tree (over-approximates
    -- a literal like ``"Y"`` is included too -- but the caller only ever
    looks these up against a name map, so a stray literal simply never
    matches anything real). Shared with ``constraints.py``, which imports it
    from here (the dependency runs constraints -> boundary_inventory, never
    the other way round).

    Walks every expression shape the parser can nest an operand under --
    ``ConditionalExpression``/``ArithmeticExpression`` (``left_operand``/
    ``right_operand``, either a bare string or another expression) and
    ``FunctionCall`` (``arguments``) -- not just the top-level comparison, so
    a name buried in ``A + B = C`` or ``FUNCTION UPPER-CASE(WS-X)`` is not
    silently invisible to the read scan below.
    """
    if expr is None:
        return []
    if isinstance(expr, LogicalExpression):
        return _condition_field_names(expr.left_condition) + _condition_field_names(
            expr.right_condition
        )
    if isinstance(expr, (ConditionalExpression, ArithmeticExpression)):
        names = []
        for operand in (expr.left_operand, expr.right_operand):
            if isinstance(operand, str) and operand.strip():
                names.append(operand.strip())
            elif isinstance(operand, CobolExpression):
                names.extend(_condition_field_names(operand))
        return names
    if isinstance(expr, FunctionCall):
        names = []
        for argument in expr.arguments:
            if isinstance(argument, str) and argument.strip():
                names.append(argument.strip())
            elif isinstance(argument, CobolExpression):
                names.extend(_condition_field_names(argument))
        return names
    return []


def _condition_read_names(statement: Any) -> list[str]:
    """Names a branching statement *reads* in its own condition -- an IF's
    condition tree, a PERFORM UNTIL's guard, an EVALUATE's subjects and its
    WHEN selectors. None of these reach the statement's generic
    ``.operands`` bag (an IfStatement's is empty), so a CALL argument whose
    only later use is ``IF WS-RC = 'Y'`` used to look unread."""
    names: list[str] = []
    if isinstance(statement, IfStatement):
        names.extend(_condition_field_names(statement.condition))
    elif isinstance(statement, PerformStatement):
        until = statement.until_condition
        names.extend(_condition_field_names(getattr(until, "condition_tree", None)))
    elif isinstance(statement, EvaluateStatement):
        for subject in statement.subjects:
            if isinstance(subject, str):
                if subject.strip():
                    names.append(subject.strip())
            elif isinstance(subject, CobolExpression):
                names.extend(_condition_field_names(subject))
        for clause in statement.when_clauses:
            for selector in clause.selectors:
                if not isinstance(selector, dict):
                    continue
                for key in ("value", "start", "end"):
                    value = selector.get(key)
                    if isinstance(value, str) and value.strip():
                        names.append(value.strip())
                text = selector.get("text")
                if isinstance(text, str):
                    # Over-approximates (a literal word is included too),
                    # harmless since every name is looked up against the
                    # layout index.
                    names.extend(RELAXED_IDENTIFIER_TOKEN_RE.findall(text))
    return names


_WRITE_SHAPED_ATTRS = ("targets", "givings", "target", "into_target", "into_targets")


def _is_write_shaped(statement: Any) -> bool:
    """True for a statement type this module knows how to read *precisely*
    (MOVE/arithmetic/COMPUTE/INITIALIZE/SET/READ-INTO/STRING/UNSTRING).

    Its generic ``.operands`` list also contains its own write targets (a
    MOVE's ``.operands`` holds both source and target), so a write-shaped
    statement's "did this read `arg`" check must use only its own read-only
    attribute (MOVE's ``.source``), never the generic operands fallback --
    otherwise a plain write would be misread as a read of the same name.
    """
    return any(getattr(statement, attr, None) for attr in _WRITE_SHAPED_ATTRS)


_FILE_OP_SPECS = (
    (IOReadStatement, "READ"),
    (IOWriteStatement, "WRITE"),
    (IORewriteStatement, "REWRITE"),
    (IOOpenStatement, "OPEN"),
    (IOCloseStatement, "CLOSE"),
    (IODeleteStatement, "DELETE"),
    (IOStartStatement, "START"),
    (IOUnlockStatement, "UNLOCK"),
)


@dataclass(frozen=True)
class BoundaryRef:
    """Identifies one boundary site: what it is, and where in the source."""

    category: str  # CALL DYNCALL OPEN CLOSE READ WRITE REWRITE DELETE
    # START UNLOCK SQL CICS DLI ACCEPT
    key: str
    paragraph: str | None
    line: int | None


@dataclass
class CallArg:
    """One CALL/DYNCALL USING argument, with its resolved data direction."""

    name: str
    passing_mode: str  # REFERENCE | CONTENT | VALUE
    direction: str  # IN | OUT | BIDIRECTIONAL
    provenance: str  # "by-content-rule" | "callee-source" | "caller-dataflow"
    # | "assumed-bidirectional" | "giving-parameter"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passing_mode": self.passing_mode,
            "direction": self.direction,
            "provenance": self.provenance,
        }


@dataclass
class Boundary:
    """One mockable boundary statement, with its resolved layout/direction."""

    ref: BoundaryRef
    direction: str  # IN | OUT | STATUS_ONLY | BIDIRECTIONAL
    record_names: list[str] = field(default_factory=list)
    status_field: str | None = None
    handlers: list[str] = field(default_factory=list)
    call_args: list[CallArg] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.ref.category,
            "key": self.ref.key,
            "paragraph": self.ref.paragraph,
            "line": self.ref.line,
            "direction": self.direction,
            "record_names": list(self.record_names),
            "status_field": self.status_field,
            "handlers": list(self.handlers),
            "call_args": [a.to_dict() for a in self.call_args],
            "unresolved": list(self.unresolved),
        }


@dataclass
class BoundaryReport:
    program_name: str | None
    boundaries: list[Boundary] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "boundaries": [b.to_dict() for b in self.boundaries],
            "unresolved": list(self.unresolved),
        }


class BoundaryInventoryAnalyzer:
    """Walks a program's PROCEDURE DIVISION and inventories its boundaries.

    ``analyze(ast, index, callee_indexes=None)`` -- ``index`` is the Phase 1
    :class:`ProgramLayoutIndex` built for the *same* program; ``callee_indexes``
    optionally maps an uppercased called-program name to that callee's own
    index (built separately, e.g. from ``--callee-path`` or a sibling
    ``CobolProgram.contained_programs`` entry), enabling the CALL
    argument-direction ladder's "callee source available" rung.
    """

    def __init__(self) -> None:
        # Full normalized command texts of every SQL/CICS/DLI site in the
        # program under analysis, collected up-front by analyze() so
        # `_unique_prefix` keys are computed against every OTHER same-category
        # site's FULL text -- order-independent and prefix-unique -- rather
        # than against previously *assigned* (already-shortened) keys, which
        # made keys depend on walk order and let an early site keep a key
        # that was a prefix of a later sibling's text.
        self._exec_texts: dict[str, list[str]] = {}

    def analyze(
        self,
        ast: CobolProgram,
        index: ProgramLayoutIndex,
        *,
        callee_indexes: dict[str, ProgramLayoutIndex] | None = None,
        callee_asts: dict[str, CobolProgram] | None = None,
    ) -> BoundaryReport:
        report = BoundaryReport(program_name=ast.program_name)
        # Phase 1's own gaps (an unownable FILE SECTION record, a SELECT
        # with no matching FD/SD) are program-level layout facts, not
        # boundary-walk facts -- but they are exactly the kind of thing a
        # consumer of this report must not have silently dropped underneath
        # it, so they ride along on the boundary report too.
        report.unresolved.extend(index.unresolved)
        procedure = ast.get_division("PROCEDURE")
        if procedure is None:
            return report

        DynamicCallAnalyzer().analyze(ast)

        self._exec_texts = self._collect_exec_texts(procedure)

        for paragraph in self._all_paragraphs(procedure):
            statements = paragraph.statements
            for position, statement in enumerate(statements):
                self._visit(
                    statement,
                    paragraph.paragraph_name,
                    index,
                    report,
                    callee_indexes or {},
                    callee_asts or {},
                    enclosing_statements=statements,
                    position=position,
                )
        return report

    # -- traversal ------------------------------------------------------

    @staticmethod
    def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
        paragraphs = list(procedure_division.paragraphs)
        for section in procedure_division.sections:
            if isinstance(section, CobolParagraph):
                continue
            paragraphs.extend(section.paragraphs)
        return paragraphs

    def _collect_exec_texts(
        self, procedure_division: CobolDivision
    ) -> dict[str, list[str]]:
        """Pre-pass: the full normalized command text of every SQL/CICS/DLI
        site in the program, per category, so key assignment can compare each
        site against all OTHER sites' full texts (see ``__init__``)."""
        texts: dict[str, list[str]] = {"SQL": [], "CICS": [], "DLI": []}

        def visit(statement: Any) -> None:
            # Same dispatch precedence as _classify (SQL before CICS/DLI).
            if isinstance(statement, ExecSQLStatement):
                sql_type = (statement.sql_type or "").upper()
                texts["SQL"].append(statement.sql_text or sql_type)
            elif isinstance(statement, ExecCicsStatement):
                texts["CICS"].append(
                    f"{statement.cics_command} {statement.cics_text}".strip()
                )
            elif isinstance(statement, ExecImsStatement):
                texts["DLI"].append(
                    f"{statement.ims_command} {statement.ims_text}".strip()
                )
            for nested_list in self._nested_statement_lists(statement):
                for nested in nested_list:
                    visit(nested)

        for paragraph in self._all_paragraphs(procedure_division):
            for statement in paragraph.statements:
                visit(statement)
        return texts

    def _other_texts(self, category: str, text: str) -> list[str]:
        """All same-category sites' full texts, minus one occurrence of this
        site's own -- what its key's uniqueness must be judged against."""
        others = list(self._exec_texts.get(category, []))
        if text in others:
            others.remove(text)
        return others

    @staticmethod
    def _nested_statement_lists(statement: Any) -> list[list]:
        lists = [
            value
            for attr in _NESTED_STATEMENT_ATTRS
            if (value := getattr(statement, attr, None))
        ]
        if isinstance(statement, EvaluateStatement):
            for when in statement.when_clauses:
                if when.statements:
                    lists.append(when.statements)
            if statement.default_when is not None and statement.default_when.statements:
                lists.append(statement.default_when.statements)
        if isinstance(statement, SearchStatement):
            # SearchStatement.when_clauses is list[dict] with a "statements"
            # key -- a different shape than EvaluateStatement's WhenClause
            # nodes. Its AT END body is already covered by "at_end_clause".
            for when_dict in statement.when_clauses:
                if when_dict.get("statements"):
                    lists.append(when_dict["statements"])
        return lists

    def _visit(
        self,
        statement: Any,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
        callee_indexes: dict[str, ProgramLayoutIndex],
        callee_asts: dict[str, CobolProgram],
        *,
        enclosing_statements: list,
        position: int,
    ) -> None:
        self._classify(
            statement,
            paragraph_name,
            index,
            report,
            callee_indexes,
            callee_asts,
            enclosing_statements,
            position,
        )
        for nested_list in self._nested_statement_lists(statement):
            for nested_position, nested_statement in enumerate(nested_list):
                self._visit(
                    nested_statement,
                    paragraph_name,
                    index,
                    report,
                    callee_indexes,
                    callee_asts,
                    enclosing_statements=nested_list,
                    position=nested_position,
                )

    # -- per-statement classification ------------------------------------

    def _classify(
        self,
        statement: Any,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
        callee_indexes: dict[str, ProgramLayoutIndex],
        callee_asts: dict[str, CobolProgram],
        enclosing_statements: list,
        position: int,
    ) -> None:
        line = statement.location.line if statement.location else None

        def ref(category: str, key: str) -> BoundaryRef:
            return BoundaryRef(
                category=category, key=key, paragraph=paragraph_name, line=line
            )

        for statement_type, category in _FILE_OP_SPECS:
            if isinstance(statement, statement_type):
                self._classify_file_op(statement, category, ref, index, report)
                return

        if isinstance(statement, (SortStatement, MergeStatement)):
            # SORT/MERGE USING reads whole files and GIVING writes them, but
            # neither is a boundary mockymock's mock surface knows (#498,
            # pending a decision on its key/category).  Say so, rather than
            # report full coverage for a program whose only I/O this is.
            verb = "SORT" if isinstance(statement, SortStatement) else "MERGE"
            for phrase, files in (
                ("USING", statement.using_files),
                ("GIVING", statement.giving_files),
            ):
                for file_name in files:
                    report.unresolved.append(
                        f"{verb} {phrase} file {file_name.upper()} in "
                        f"{paragraph_name} is not modelled as a boundary: no "
                        "fixture or expectation is generated for it"
                    )
            return

        if isinstance(statement, CallStatement):
            self._classify_call(
                statement,
                ref,
                index,
                report,
                callee_indexes,
                callee_asts,
                enclosing_statements,
                position,
            )
            return

        if isinstance(statement, ExecSQLStatement):
            self._classify_sql(statement, ref, index, report)
            return

        if isinstance(statement, ExecCicsStatement):
            self._classify_cics(statement, ref, index, report)
            return

        if isinstance(statement, ExecImsStatement):
            self._classify_dli(statement, ref, index, report)
            return

        if isinstance(statement, IOAcceptStatement):
            self._classify_accept(statement, ref, index, report)
            return

        # DisplayStatement and everything else: not a mockable boundary.
        _ = DisplayStatement  # referenced for clarity of scope, no action

    @staticmethod
    def _handlers_present(statement: Any) -> list[str]:
        return [
            label for attr, label in _HANDLER_LABELS if getattr(statement, attr, None)
        ]

    def _classify_file_op(
        self,
        statement: Any,
        category: str,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
    ) -> None:
        handlers = self._handlers_present(statement)

        if category in ("OPEN", "CLOSE"):
            for file_name in getattr(statement, "file_names", []) or []:
                if not file_name:
                    continue
                # OPEN/CLOSE carry no data payload but do set the file's
                # declared FILE STATUS field -- resolved the same way the
                # READ/DELETE/START/UNLOCK branch below does, so a later
                # phase (ScenarioPlanner's "OPEN -> FILE STATUS 35" error
                # family) can actually target it.
                facts = index.file_facts(file_name)
                report.boundaries.append(
                    Boundary(
                        ref=ref(category, file_name.upper()),
                        direction="STATUS_ONLY",
                        status_field=(
                            facts.file_status_field if facts is not None else None
                        ),
                        handlers=handlers,
                    )
                )
            return

        if category in ("WRITE", "REWRITE"):
            record_name = getattr(statement, "record_name", None)
            if not record_name:
                report.unresolved.append(
                    f"{category} in {ref(category, '').paragraph}: no record name"
                )
                return
            # WRITE/REWRITE name the whole *record* (COBOL syntax, not the
            # FD) -- a group item, which flatten_record/resolve() never
            # indexes on its own name (it only emits FieldSpecs for
            # elementary leaves). record_named() looks up the group itself.
            record = index.record_named(record_name)
            record_names = [record.name] if record else []
            if not record:
                report.unresolved.append(
                    f"{category} {record_name}: record not resolvable in layout index"
                )
            report.boundaries.append(
                Boundary(
                    ref=ref(category, record_name.upper()),
                    direction="OUT",
                    record_names=record_names,
                    handlers=handlers,
                )
            )
            return

        # READ / DELETE / START / UNLOCK: keyed on the file name.
        file_name = getattr(statement, "file_name", None)
        if not file_name:
            report.unresolved.append(f"{category}: no file name")
            return

        record_names = []
        status_field = None
        facts = index.file_facts(file_name)
        if facts is not None:
            status_field = facts.file_status_field

        if category == "READ":
            into_target = getattr(statement, "into_target", None)
            if into_target:
                # INTO names a whole record (typically a WORKING-STORAGE
                # group the FD's record gets copied into), not a field.
                into_record = index.record_named(into_target)
                if into_record:
                    record_names = [into_record.name]
            if not record_names:
                record_names = [r.name for r in index.records_for_file(file_name)]
            if not record_names:
                report.unresolved.append(
                    f"READ {file_name}: no record layout resolvable"
                )
            report.boundaries.append(
                Boundary(
                    ref=ref(category, file_name.upper()),
                    direction="IN",
                    record_names=record_names,
                    status_field=status_field,
                    handlers=handlers,
                )
            )
            return

        # DELETE / START / UNLOCK: no data payload, status-only.
        if facts is not None and facts.record_key:
            record_names = [facts.record_key]
        report.boundaries.append(
            Boundary(
                ref=ref(category, file_name.upper()),
                direction="STATUS_ONLY",
                record_names=record_names,
                status_field=status_field,
                handlers=handlers,
            )
        )

    # -- CALL / DYNCALL ---------------------------------------------------

    def _classify_call(
        self,
        statement: CallStatement,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
        callee_indexes: dict[str, ProgramLayoutIndex],
        callee_asts: dict[str, CobolProgram],
        enclosing_statements: list,
        position: int,
    ) -> None:
        is_dynamic = bool(getattr(statement, "is_dynamic", False))
        name = statement.called_program or ""
        category = "DYNCALL" if is_dynamic else "CALL"
        # Static CALL keys keep the literal's original case (COBOL program
        # names are written case-sensitively); dynamic CALL keys -- COBOL
        # identifiers -- are uppercased. Mirrors mockymock's own asymmetry so
        # both walks agree on the same key for the same site.
        key = name.upper() if is_dynamic else name

        handlers = self._handlers_present(statement)
        call_args = self._resolve_call_args(
            statement,
            index,
            callee_indexes,
            callee_asts,
            enclosing_statements,
            position,
        )

        boundary = Boundary(
            ref=ref(category, key),
            direction="",  # per-arg; no single statement-level direction
            handlers=handlers,
            call_args=call_args,
        )
        if is_dynamic:
            possible = callee_names(getattr(statement, "possible_values", None) or [])
            if not name:
                report.unresolved.append("dynamic CALL with no identifier captured")
            elif not possible:
                report.unresolved.append(
                    f"dynamic CALL {name}: no possible target values resolved"
                )
        elif not name:
            report.unresolved.append("CALL with no program name captured")

        report.boundaries.append(boundary)

    def _resolve_call_args(
        self,
        statement: CallStatement,
        index: ProgramLayoutIndex,
        callee_indexes: dict[str, ProgramLayoutIndex],
        callee_asts: dict[str, CobolProgram],
        enclosing_statements: list,
        position: int,
    ) -> list[CallArg]:
        args: list[CallArg] = []
        callee_index = None
        callee_ast = None
        if not statement.is_dynamic and statement.called_program:
            key = statement.called_program.upper().strip("\"'")
            callee_index = callee_indexes.get(key)
            callee_ast = callee_asts.get(key)

        for i, param in enumerate(statement.using_parameters):
            mode = (param.passing_mode or "REFERENCE").upper()
            if mode in ("CONTENT", "VALUE"):
                args.append(
                    CallArg(
                        name=param.name,
                        passing_mode=mode,
                        direction="OUT",
                        provenance="by-content-rule",
                    )
                )
                continue

            if callee_index is not None and callee_ast is not None:
                direction = self._callee_source_direction(i, callee_index, callee_ast)
                if direction is not None:
                    args.append(
                        CallArg(
                            name=param.name,
                            passing_mode=mode,
                            direction=direction,
                            provenance="callee-source",
                        )
                    )
                    continue

            direction, provenance = self._caller_dataflow_direction(
                param.name, index, enclosing_statements, position
            )
            args.append(
                CallArg(
                    name=param.name,
                    passing_mode=mode,
                    direction=direction,
                    provenance=provenance,
                )
            )

        for name in (statement.returning_parameter, statement.giving_parameter):
            if name:
                args.append(
                    CallArg(
                        name=name,
                        passing_mode="REFERENCE",
                        direction="IN",
                        provenance="giving-parameter",
                    )
                )

        return args

    @staticmethod
    def _callee_source_direction(
        position: int, callee_index: ProgramLayoutIndex, callee_ast: CobolProgram
    ) -> str | None:
        """Rung 2: does the callee write to its Nth LINKAGE 01 at all?

        v1 simplification (stated in the parent plan): writes-at-all -> IN
        (the callee produces a value the caller needs back), reads-only ->
        OUT (the caller's own value passes through unchanged). No attempt is
        made here to distinguish "writes after reading" (BIDIRECTIONAL);
        that refinement is left to a later phase.
        """
        linkage_records = callee_index.linkage_records()
        # The Nth argument binds to the Nth name of the callee's
        # `PROCEDURE DIVISION USING`, not to its Nth LINKAGE 01 in source
        # order -- the two differ whenever LINKAGE is declared in another
        # order or holds items no USING names (SET ADDRESS OF targets).
        # Declaration order is only the fallback for a callee with no USING.
        formals = _procedure_using_names(callee_ast)
        if formals:
            if position >= len(formals):
                return None
            by_name = {record.name.upper(): record for record in linkage_records}
            found = by_name.get(formals[position])
            if found is None:
                return None
            linkage_root = found
        else:
            if position >= len(linkage_records):
                return None
            linkage_root = linkage_records[position]
        candidate_names = {linkage_root.name.upper()}
        for child in linkage_root.get_all_children():
            candidate_names.add(child.name.upper())

        for statement in callee_ast.get_all_statements():
            for target in _write_targets(statement):
                if target and target.upper() in candidate_names:
                    return "IN"
        return "OUT"

    @staticmethod
    def _caller_dataflow_direction(
        arg_name: str,
        index: ProgramLayoutIndex,
        enclosing_statements: list,
        position: int,
    ) -> tuple[str, str]:
        """Rung 3: last write before the CALL / first read after it, in the
        enclosing paragraph's own statement list (source order).

        A write to a *parent group* counts as a write to `arg_name` (and vice
        versa for a read) -- checked by comparing `FieldSpec.path` prefixes
        through the layout index, not by bare string equality.
        """
        resolved_arg = index.resolve(arg_name)
        arg_path = resolved_arg.spec.path if resolved_arg else (arg_name.upper(),)

        def touches(name: str | None) -> bool:
            if not name:
                return False
            if name.upper() == arg_name.upper():
                return True
            other = index.resolve(name)
            other_path = other.spec.path if other else (name.upper(),)
            shorter, longer = sorted((arg_path, other_path), key=len)
            return longer[: len(shorter)] == shorter

        wrote_before = any(
            touches(t)
            for statement in enclosing_statements[:position]
            for t in _write_targets(statement)
        )

        read_after = False
        write_after = False
        uncertain_after = False
        for statement in enclosing_statements[position + 1 :]:
            if _is_write_shaped(statement):
                # A write-shaped statement's generic ``.operands`` also holds
                # its own write targets, so its reads come from the per-type
                # read list -- checked *before* its writes, since a verb
                # like ``ADD X TO ARG`` reads ARG before storing into it.
                reads = _write_shaped_read_names(statement)
                if reads is None:
                    # A write-shaped type this module cannot read precisely:
                    # an operand naming arg that is not one of its write
                    # targets may be a read -- do not grade it OUT on a guess.
                    writes = _write_targets(statement)
                    if any(
                        touches(op)
                        for op in getattr(statement, "operands", None) or []
                        if op not in writes
                    ):
                        uncertain_after = True
                        break
                elif any(touches(name) for name in reads):
                    read_after = True
                    break
                if any(touches(t) for t in _write_targets(statement)):
                    write_after = True
                    break
                continue
            if any(touches(t) for t in _write_targets(statement)):
                write_after = True
                break
            if any(touches(op) for op in getattr(statement, "operands", None) or []):
                read_after = True
                break
            if any(touches(name) for name in _condition_read_names(statement)):
                read_after = True
                break

        if uncertain_after:
            return "BIDIRECTIONAL", "assumed-bidirectional"
        if wrote_before and not read_after:
            return "OUT", "caller-dataflow"
        if read_after and not wrote_before:
            return "IN", "caller-dataflow"
        if wrote_before and read_after:
            return "BIDIRECTIONAL", "caller-dataflow"
        if write_after:
            # Written only after the call, never before or read from --
            # nothing observed the caller-supplied value, so it is the
            # callee that must be producing it.
            return "IN", "caller-dataflow"
        return "BIDIRECTIONAL", "assumed-bidirectional"

    # -- EXEC SQL / CICS / DLI -------------------------------------------

    @staticmethod
    def _unique_prefix(match_text: str, others: list[str]) -> str:
        """Shortest word-prefix of `match_text` no other same-category site
        shares -- mirrors mockymock's `generator._unique_prefix` (re-derived
        independently; see module docstring)."""
        words = match_text.split()
        if not words:
            return ""
        # The prefix is built from whitespace-split words, so the other
        # texts must be compared in the same collapsed form: a raw text
        # still holds its line breaks (`... MAPSET ( X ) \n FROM ...`), so
        # a prefix spanning one never matched it and two multi-line sites
        # differing only after a line break got the same key.
        others = [" ".join(other.split()) for other in others]
        for length in range(1, len(words) + 1):
            prefix = " ".join(words[:length])
            if not any(o.startswith(prefix) for o in others):
                return prefix
        return " ".join(words)

    @staticmethod
    def _resolve_display_name(name: str, index: ProgramLayoutIndex) -> str | None:
        """Resolve *name* whether it names an elementary field or a whole
        record/group -- an SQL host variable, ACCEPT target, or CICS/DLI
        operand can legally be either, but `index.resolve()` alone only ever
        finds elementary fields (`flatten_record` emits no `FieldSpec` for a
        group item; `record_named()` exists precisely to fill that gap --
        see .okf/generators.md)."""
        resolved = index.resolve(name)
        if resolved:
            return resolved.spec.qualified_name
        record = index.record_named(name)
        return record.name if record else None

    def _classify_sql(
        self,
        statement: ExecSQLStatement,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
    ) -> None:
        sql_type = (statement.sql_type or "").upper()
        # into_variables is unreliable in practice -- an inline
        # "SELECT ... INTO :a FROM t WHERE x = :b" places both :a and :b in
        # host_variables, not into_variables (verified empirically; see
        # .okf/analysis.md). host_variables is therefore the only layout
        # source this uses, for every SQL statement shape.
        host_vars = list(statement.host_variables) + list(
            getattr(statement, "into_variables", []) or []
        )
        # The parser strips a structure qualifier off host_variables
        # (`:REC-A.AMT` arrives as `AMT`), which leaves a name declared under
        # more than one structure unresolvable. Re-read the qualifiers from
        # the SQL text, as HostVariableResolver does, and resolve the dotted
        # `REC-A.AMT` form -- `index.resolve()` accepts it directly.
        qualified: dict[str, list[str]] = {}
        scrubbed = _strip_sql_literals_and_comments(statement.sql_text or "")
        for match in _QUALIFIED_HOST_VAR_RE.finditer(scrubbed):
            if match.group(1):
                dotted = f"{match.group(1)}{match.group(2)}".upper()
                forms = qualified.setdefault(match.group(2).upper(), [])
                if dotted not in forms:
                    forms.append(dotted)
        names: list[str] = []
        for var in dict.fromkeys(v.lstrip(":") for v in host_vars if v):
            names.extend(qualified.get(var.upper(), [var]))
        record_names: list[str] = []
        for var in dict.fromkeys(names):
            display_name = self._resolve_display_name(var, index)
            if display_name:
                record_names.append(display_name)
            else:
                report.unresolved.append(
                    f"SQL host variable {var} not resolvable in layout index"
                )

        if sql_type in _SQL_IN_TYPES or isinstance(statement, FetchStatement):
            direction = "IN"
        elif sql_type in _SQL_OUT_TYPES:
            direction = "OUT"
        else:
            direction = "STATUS_ONLY"

        text = statement.sql_text or sql_type
        if text:
            key = self._unique_prefix(text, self._other_texts("SQL", text))
        else:
            key = sql_type

        report.boundaries.append(
            Boundary(
                ref=ref("SQL", key),
                direction=direction,
                record_names=record_names,
                status_field="SQLCODE",
            )
        )

    def _classify_cics(
        self,
        statement: ExecCicsStatement,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
    ) -> None:
        # EXEC CICS has no fixed INTO/FROM attributes -- its data-transfer
        # operand is one of many command-specific keywords captured
        # generically in `.options` (option keyword -> argument text).
        # Resolving it precisely per CICS command is out of scope for this
        # phase; best-effort: try every option value against the layout
        # index, and record what wasn't resolvable rather than guess a
        # direction with false confidence.
        record_names: list[str] = []
        for option_value in statement.options.values():
            if not option_value:
                continue
            display_name = self._resolve_display_name(option_value, index)
            if display_name:
                record_names.append(display_name)

        text = f"{statement.cics_command} {statement.cics_text}".strip()
        if text:
            key = self._unique_prefix(text, self._other_texts("CICS", text))
        else:
            key = statement.cics_command

        unresolved: list[str] = []
        if not record_names:
            unresolved.append(
                "CICS command data-transfer operand not resolvable "
                "(best-effort v1: no fixed INTO/FROM attribute to key off)"
            )

        report.boundaries.append(
            Boundary(
                ref=ref("CICS", key),
                direction="BIDIRECTIONAL",
                record_names=record_names,
                unresolved=unresolved,
            )
        )

    def _classify_dli(
        self,
        statement: ExecImsStatement,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
    ) -> None:
        # Same best-effort posture as CICS: arguments is a positional list
        # (PCB reference, I/O area, SSAs) with no fixed role per position.
        record_names: list[str] = []
        for argument in statement.arguments:
            display_name = self._resolve_display_name(argument, index)
            if display_name:
                record_names.append(display_name)

        text = f"{statement.ims_command} {statement.ims_text}".strip()
        if text:
            key = self._unique_prefix(text, self._other_texts("DLI", text))
        else:
            key = statement.ims_command

        unresolved: list[str] = []
        if not record_names:
            unresolved.append(
                "DLI call argument not resolvable to a layout field "
                "(best-effort v1: positional arguments, no fixed role)"
            )

        report.boundaries.append(
            Boundary(
                ref=ref("DLI", key),
                direction="BIDIRECTIONAL",
                record_names=record_names,
                unresolved=unresolved,
            )
        )

    def _classify_accept(
        self,
        statement: IOAcceptStatement,
        ref: Any,
        index: ProgramLayoutIndex,
        report: BoundaryReport,
    ) -> None:
        # from_source keeps a format qualifier (`FROM DATE YYYYMMDD` ->
        # "DATE YYYYMMDD", `FROM DAY YYYYDDD`), so the source is its first
        # word; compared whole, those read as console input.
        source_words = (statement.from_source or "").upper().split()
        source = source_words[0] if source_words else ""
        if source in _NON_INTERACTIVE_ACCEPT_SOURCES:
            return  # not a boundary: resolved without touching stdin

        target = (statement.target or "").upper()
        if not target:
            report.unresolved.append("ACCEPT with no target captured")
            return

        if target == "OMITTED":
            # ACCEPT OMITTED: a real COBOL idiom -- waits for console input
            # (still a boundary: it blocks on stdin) but stores nothing, so
            # there is deliberately no field to resolve. Not a gap.
            report.boundaries.append(
                Boundary(ref=ref("ACCEPT", target), direction="IN")
            )
            return

        display_name = self._resolve_display_name(target, index)
        record_names = [display_name] if display_name else []
        if not display_name:
            report.unresolved.append(
                f"ACCEPT target {target} not resolvable in layout index"
            )

        report.boundaries.append(
            Boundary(
                ref=ref("ACCEPT", target),
                direction="IN",
                record_names=record_names,
            )
        )


__all__ = [
    "BoundaryRef",
    "CallArg",
    "Boundary",
    "BoundaryReport",
    "BoundaryInventoryAnalyzer",
]
