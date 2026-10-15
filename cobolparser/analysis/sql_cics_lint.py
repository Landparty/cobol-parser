"""Security and hygiene lint for embedded SQL and CICS.

A COBOL program that talks to DB2 and CICS carries two failure surfaces the
COBOL compiler says nothing about, because neither ``EXEC SQL`` nor ``EXEC
CICS`` is COBOL: the precompiler rewrites the block and moves on.  Whether
the program then looked at what came back is nobody's job to check.  This
module makes it somebody's job.

What it reports, and why each one is a real defect rather than a style note:

``SQL_NO_SQLCODE_CHECK``
    An executable ``EXEC SQL`` statement whose outcome is never looked at:
    nothing in the statements that follow it mentions ``SQLCODE``,
    ``SQLSTATE`` or ``SQLCA``, and no ``WHENEVER SQLERROR`` handler is in
    effect.  DB2 does not raise; it sets a number and returns.  An UPDATE
    that matched no rows, a FETCH that hit -911, an INSERT rejected on a
    duplicate key -- all of them fall straight through to the next statement,
    and the program commits whatever it was going to commit.  This is the
    single most common real defect in DB2 COBOL, and the cheapest to find.

``SQL_DYNAMIC_CONCATENATION``
    A host variable handed to ``PREPARE`` or ``EXECUTE IMMEDIATE`` whose
    content was assembled by ``STRING`` from a data item, or moved in from
    another data item.  That is SQL injection with a mainframe accent: the
    text is a statement, and something that is not a literal decided part of
    it.  Parameter markers (``EXECUTE ... USING :HV``) are the fix and are
    never flagged.

``SQL_HARDCODED_CREDENTIALS``
    A literal user id or password in ``EXEC SQL CONNECT``.  It is in the
    source, in the listing, in the load library, and in every copy anybody
    ever took of any of them.

``SQL_SELECT_WITHOUT_INTO``
    A singleton ``SELECT`` with no ``INTO`` and no cursor.  The precompiler
    accepts it; the row goes nowhere.

``CICS_NO_RESP_HANDLING``
    An ``EXEC CICS`` command with no ``RESP``/``RESP2``, no ``NOHANDLE`` and
    no ``HANDLE CONDITION`` in effect.  The default action for most CICS
    conditions is to abend the task, so the failure mode is not a wrong
    answer but a dropped transaction, mid-update.

``CICS_ABEND_WITHOUT_HANDLER``
    ``EXEC CICS ABEND`` with no ``HANDLE ABEND`` established.  Reported as
    info: it is frequently deliberate, and worth seeing rather than worth
    fixing.

What it deliberately does *not* do is guess.  Three things in the parsed
form of an EXEC block are lossy, and each one is answered with an entry in
:attr:`SqlCicsReport.unchecked` rather than with a finding:

* A credential operand with neither a colon nor quotes (``USING
  WS-PASSWORD``) is a data item written without its host-variable colon,
  or a mistake; one that matches a declared DATA DIVISION item is reported
  as unchecked, not as a hardcoded password. (EXEC SQL text keeps a
  literal's quotes -- ``USING 'S3CRET'`` -- since 2026-09-28; before that
  the two forms reduced to the same tokens.)
* ``STRING`` operands lose their quotes the same way, so a ``STRING`` whose
  operands name nothing declared cannot be told from a ``STRING`` of pure
  literals.
* A CICS command with a ``HANDLE CONDITION`` in effect that names only
  specific conditions (``NOTFND``, ``DUPREC``, ...) cannot be graded, because
  nothing in the AST says which conditions *this* command can raise.  Only
  the catch-all ``ERROR`` handler counts as coverage; anything narrower is
  reported as unchecked.

Two conservatisms are worth stating plainly, since they shape the findings:

* ``WHENEVER`` and the CICS handler commands are tracked in **source
  order**, which is what the precompiler does -- not in execution order.
  That is correct for ``WHENEVER`` by definition and an approximation for
  ``PUSH HANDLE``/``POP HANDLE``.
* The search for a status-code check spans the SQL statement's own paragraph
  and, transitively, every paragraph ``PERFORM``ed from it.  A check that
  happens only in the paragraph the program falls through into is not seen,
  and the statement is reported.
* The text handed to ``PREPARE`` / ``EXECUTE IMMEDIATE`` is traced through
  every ``STRING`` and ``MOVE`` into it anywhere in the program unit, unless
  a ``MOVE`` written directly in the same paragraph, before the statement,
  overwrites the whole item. Then only that MOVE and what can run between it
  and the statement count (``_WriterFlow``), so a buffer reused for a
  constant statement is not blamed on an earlier ``STRING``.

Typical usage::

    from cobolparser import parse_cobol
    from cobolparser.analysis.sql_cics_lint import SqlCicsAnalyzer

    report = SqlCicsAnalyzer().analyze(parse_cobol(source).ast)
    for violation in report.violations:
        print(violation.severity, violation.kind, violation.message)
    report.unchecked   # what this run could not speak for, and why
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import ASTNode, SourceLocation
from ..models.program import CobolParagraph, CobolProgram, CobolSection
from ..models.sql_statements import (
    DeclareCursorStatement,
    ExecSQLStatement,
    _strip_sql_literals_and_comments,
)
from ..models.statements import MoveStatement, PerformStatement, StringStatement
from ..models.statements.base import CobolStatement
from ..parsers.statements.ibm_exec_statements import ExecCicsStatement

#: Severity ordering, shared with :mod:`.lint` so an EXEC finding grades on
#: the same scale as every other rule.
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: Stable ``kind`` strings. Callers filter on these; the wording of a
#: message may change, these may not.
KIND_NO_SQLCODE_CHECK = "SQL_NO_SQLCODE_CHECK"
KIND_DYNAMIC_CONCATENATION = "SQL_DYNAMIC_CONCATENATION"
KIND_HARDCODED_CREDENTIALS = "SQL_HARDCODED_CREDENTIALS"
KIND_SELECT_WITHOUT_INTO = "SQL_SELECT_WITHOUT_INTO"
KIND_CICS_NO_RESP = "CICS_NO_RESP_HANDLING"
KIND_CICS_ABEND_NO_HANDLER = "CICS_ABEND_WITHOUT_HANDLER"

#: Severity per kind, so a consumer can grade a finding without a lookup
#: table of its own.
SEVERITY_BY_KIND: dict[str, str] = {
    KIND_NO_SQLCODE_CHECK: SEVERITY_WARNING,
    KIND_DYNAMIC_CONCATENATION: SEVERITY_ERROR,
    KIND_HARDCODED_CREDENTIALS: SEVERITY_ERROR,
    KIND_SELECT_WITHOUT_INTO: SEVERITY_WARNING,
    KIND_CICS_NO_RESP: SEVERITY_WARNING,
    KIND_CICS_ABEND_NO_HANDLER: SEVERITY_INFO,
}

#: Naming any of these in a statement counts as having looked at the outcome
#: of the SQL that preceded it. ``SQLCA`` is included because
#: ``CALL 'DB2ERROR' USING SQLCA`` is the house style of a good half of the
#: DB2 shops in existence: the check is real, it just lives in a subprogram.
_SQL_STATUS_WORDS = frozenset({"SQLCODE", "SQLSTATE", "SQLCA"})

#: ``sql_type`` values that are precompiler declarations rather than
#: executable statements. None of them sets SQLCODE at run time, so demanding
#: a status check after one would be a pure false positive.
_NON_EXECUTABLE_SQL_TYPES = frozenset(
    {"DECLARE CURSOR", "DECLARE TABLE", "INCLUDE", "WHENEVER"}
)

#: The same idea for blocks the parser classifies as ``UNKNOWN``: matched
#: against the leading words of the block's own text.
_NON_EXECUTABLE_PREFIXES: tuple[str, ...] = (
    "BEGIN DECLARE SECTION",
    "END DECLARE SECTION",
)

_DECLARE_GLOBAL_TEMPORARY_RE = re.compile(
    r"^DECLARE\s+GLOBAL\s+TEMPORARY\s+TABLE\b", re.IGNORECASE
)

#: ``DECLARE`` is non-executable only in these forms; ``DECLARE GLOBAL
#: TEMPORARY TABLE`` executes and sets SQLCODE like any other statement.
_DECLARE_NON_EXECUTABLE_RE = re.compile(
    r"^DECLARE\s+\S+\s+(?:.*\b)?(?:CURSOR|STATEMENT|VARIABLE)\b|^DECLARE\s+\S+\s+TABLE\b",
    re.IGNORECASE,
)

#: CICS commands that manage the condition handlers rather than request a
#: resource. They set the state this analyzer tracks; grading them against it
#: would be circular.
_CICS_HANDLER_COMMANDS = frozenset({"HANDLE", "IGNORE", "PUSH", "POP"})

#: CICS commands exempt from :data:`KIND_CICS_NO_RESP`, each with the reason
#: it is exempt. Kept explicit -- an exemption nobody can justify is how a
#: lint rule quietly stops finding anything.
CICS_NO_RESP_EXEMPT: dict[str, str] = {
    "RETURN": (
        "control returns to CICS and never to the next COBOL statement, so a "
        "RESP value could not be inspected even if one were requested"
    ),
    "XCTL": "control transfers to another program and never comes back",
    "ABEND": (
        "terminates the task by design; its own finding is "
        f"{KIND_CICS_ABEND_NO_HANDLER}"
    ),
    "SEND": (
        "terminal/BMS output, whose conditions are configuration faults that "
        "abend the task rather than outcomes a program branches on; flagging "
        "every SEND in a BMS program would bury the findings that matter"
    ),
    "ASKTIME": "no exceptional condition is defined for it",
    "SUSPEND": "no exceptional condition is defined for it",
}

#: Credential-bearing keywords in ``EXEC SQL CONNECT``: what a literal
#: there is, and the host variable that should hold it instead.
_CONNECT_CREDENTIAL_KEYWORDS: dict[str, tuple[str, str]] = {
    "USING": ("password", ":WS-PASSWORD"),
    "PASSWORD": ("password", ":WS-PASSWORD"),
    "USER": ("authorization id", ":WS-USERID"),
}

#: ``KEYWORD operand`` inside a CONNECT. The separator is optional because
#: the EXEC text collector attaches a host variable's colon to the preceding
#: word (``USER:WS-UID``).
_CONNECT_OPERAND_RE = re.compile(
    r"\b(USING|PASSWORD|USER)\b\s*([^\s,]+)",
    re.IGNORECASE,
)

#: ``WHENEVER <condition> <action>``. ``NOT FOUND`` is two words; the rest
#: are one.
_WHENEVER_RE = re.compile(
    r"^\s*WHENEVER\s+(NOT\s+FOUND|SQLERROR|SQLWARNING)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: A host-variable ``INTO`` in a singleton SELECT. Tolerant of the missing
#: space the EXEC text collector leaves behind (``INTO:WS-NAME``).
_INTO_HOST_VAR_RE = re.compile(r"\bINTO\s*:", re.IGNORECASE)

#: ``EXECUTE IMMEDIATE`` -- the only ``EXECUTE`` form that takes statement
#: *text*. Plain ``EXECUTE stmt USING :hv`` passes parameter markers and is
#: the safe idiom.
_EXECUTE_IMMEDIATE_RE = re.compile(r"^\s*EXECUTE\s+IMMEDIATE\b", re.IGNORECASE)

#: A COBOL literal as the parser preserves it in a MOVE: quoted text, a
#: number, or a figurative constant.
_FIGURATIVE_CONSTANTS = frozenset(
    {
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "QUOTE",
        "QUOTES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "NULL",
        "NULLS",
        "ALL",
    }
)

#: Attributes that hold nested statements without being AST children. Same
#: list ``CobolProgram.get_all_statements`` walks -- an SQL statement inside
#: an ``AT END`` clause is still an SQL statement.
_NESTED_STATEMENT_ATTRS: tuple[str, ...] = (
    "then_statements",
    "else_statements",
    "when_clauses",
    "default_when",
    "statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "on_exception",
    "not_on_exception",
    "on_overflow",
    "not_on_overflow",
    "on_size_error",
    "not_on_size_error",
)


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass
class SqlCicsViolation:
    """One embedded-SQL or CICS defect.

    Attributes:
        kind: One of the ``KIND_*`` constants in this module.
        severity: ``error``, ``warning`` or ``info`` -- always
            :data:`SEVERITY_BY_KIND` for *kind*.
        message: One sentence saying what is wrong and what to do about it.
        location: Where the offending statement is.
        symbol: What the finding is *about*: the SQL statement type
            (``SELECT``, ``PREPARE``, ...), the CICS command verb (``READ``,
            ``LINK``, ...), or, for a dynamic-SQL finding, the host variable
            whose content is untrusted.
        detail: Machine-readable specifics -- the traced assignment, the
            option keyword, the active handler -- for a consumer that wants
            more than the sentence.
    """

    kind: str
    severity: str
    message: str
    location: SourceLocation
    symbol: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the violation."""
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location is not None
                else None
            ),
            "symbol": self.symbol,
            "detail": dict(self.detail),
        }


@dataclass
class SqlCicsReport:
    """Everything one run found, and everything it could not speak for.

    Attributes:
        violations: The findings, in source order.
        unchecked: One sentence per thing this run could not check, naming
            the line it gave up on and why.  A quiet report with a populated
            ``unchecked`` is not a clean program -- it is an unexamined one.
        sql_statements: ``EXEC SQL`` blocks found in the PROCEDURE DIVISION,
            precompiler declarations included.  A ``DECLARE TABLE`` or
            ``INCLUDE`` written in the DATA DIVISION is not counted: it is
            not executable, so this analyzer has nothing to say about it.
        cics_statements: ``EXEC CICS`` blocks found, handler-management
            commands included.
    """

    violations: list[SqlCicsViolation] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    sql_statements: int = 0
    cics_statements: int = 0

    @property
    def has_violations(self) -> bool:
        """True when anything at all was found."""
        return bool(self.violations)

    def worst_severity(self) -> str | None:
        """The highest severity present, or ``None`` for a clean report."""
        for severity in (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO):
            if any(v.severity == severity for v in self.violations):
                return severity
        return None

    def violations_of_kind(self, kind: str) -> list[SqlCicsViolation]:
        """Every violation whose ``kind`` is *kind*."""
        return [v for v in self.violations if v.kind == kind]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the report (backs the JSON output of the CLI)."""
        return {
            "violation_count": len(self.violations),
            "unchecked_count": len(self.unchecked),
            "worst_severity": self.worst_severity(),
            "sql_statements": self.sql_statements,
            "cics_statements": self.cics_statements,
            "violations": [v.to_dict() for v in self.violations],
            "unchecked": list(self.unchecked),
        }


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------


@dataclass
class _Block:
    """One paragraph, flattened into the statements it executes.

    ``name`` is the paragraph name; a parser-synthesised fragment (statements
    written before the first paragraph header) has an empty or punctuation-
    only name and is merged into the block before it, so a check written on
    the line after the SQL is not missed just because the program has no
    paragraph headers.
    """

    name: str
    statements: list[ASTNode] = field(default_factory=list)
    #: ``id()`` of the statements written directly in the paragraph (not
    #: inside an IF/EVALUATE/AT END body), i.e. the ones that always run.
    unconditional: set[int] = field(default_factory=set)


@dataclass
class _CicsHandlerState:
    """The CICS condition/abend handlers in effect at one point in source.

    Attributes:
        conditions: Condition name -> label, for handlers established by
            ``HANDLE CONDITION`` with a label.  ``ERROR`` is the catch-all.
        abend_handler: Whether a ``HANDLE ABEND`` with a LABEL or PROGRAM is
            in effect.
    """

    conditions: dict[str, str] = field(default_factory=dict)
    abend_handler: bool = False

    def copy(self) -> _CicsHandlerState:
        """A snapshot, for ``PUSH HANDLE``."""
        return _CicsHandlerState(dict(self.conditions), self.abend_handler)


# ---------------------------------------------------------------------------
# The analyzer
# ---------------------------------------------------------------------------


class SqlCicsAnalyzer:
    """Lints one program unit's ``EXEC SQL`` and ``EXEC CICS`` blocks.

    Scoped to the program unit it is handed, like every other analyzer here:
    ``ast.contained_programs`` are not walked, so a caller that wants every
    unit in a file runs the analyzer once per unit.
    """

    def analyze(self, ast: CobolProgram) -> SqlCicsReport:
        """Lint *ast* and return everything found and everything skipped."""
        report = SqlCicsReport()
        blocks, by_name = _build_blocks(ast)
        ordered = [
            (block_index, position, statement)
            for block_index, block in enumerate(blocks)
            for position, statement in enumerate(block.statements)
        ]

        sql_nodes = [s for _, _, s in ordered if isinstance(s, ExecSQLStatement)]
        cics_nodes = [s for _, _, s in ordered if isinstance(s, ExecCicsStatement)]
        report.sql_statements = len(sql_nodes)
        report.cics_statements = len(cics_nodes)

        if ast.procedure_division is None:
            report.unchecked.append(
                "this program unit has no PROCEDURE DIVISION; no EXEC SQL or "
                "EXEC CICS statement was examined"
            )
            return report
        if not sql_nodes and not cics_nodes:
            return report

        declared_names = _declared_data_names(ast)
        writers = _assignment_index(ordered)
        flow = _WriterFlow(blocks, by_name, writers)

        whenever: dict[str, str] = {}
        status_cache: dict[int, bool] = {}
        cics_state = _CicsHandlerState()
        cics_stack: list[_CicsHandlerState] = []

        for block_index, position, statement in ordered:
            if isinstance(statement, ExecSQLStatement):
                if _is_whenever(statement):
                    _apply_whenever(statement, whenever, report)
                    continue
                self._check_sql(
                    statement,
                    block_index=block_index,
                    position=position,
                    blocks=blocks,
                    by_name=by_name,
                    whenever=whenever,
                    flow=flow,
                    declared_names=declared_names,
                    status_cache=status_cache,
                    report=report,
                )
            elif isinstance(statement, ExecCicsStatement):
                self._check_cics(statement, cics_state, cics_stack, report)

        report.violations.sort(key=_violation_order)
        return report

    # -- SQL ---------------------------------------------------------------

    def _check_sql(
        self,
        statement: ExecSQLStatement,
        *,
        block_index: int,
        position: int,
        blocks: list[_Block],
        by_name: dict[str, list[int]],
        whenever: dict[str, str],
        flow: _WriterFlow,
        declared_names: set[str],
        status_cache: dict[int, bool],
        report: SqlCicsReport,
    ) -> None:
        """Grade one executable ``EXEC SQL`` block."""
        text = " ".join(statement.sql_text.split())
        upper = text.upper()

        if upper.startswith("CONNECT"):
            _check_connect(statement, upper, declared_names, report)

        if _is_singleton_select_without_into(statement, upper):
            report.violations.append(
                SqlCicsViolation(
                    kind=KIND_SELECT_WITHOUT_INTO,
                    severity=SEVERITY_BY_KIND[KIND_SELECT_WITHOUT_INTO],
                    message=(
                        "singleton SELECT has no INTO clause and no cursor, so "
                        "the row it retrieves is discarded; add INTO :host-var "
                        "(or declare a cursor and FETCH)"
                    ),
                    location=statement.location,
                    symbol="SELECT",
                    detail={"sql": text},
                )
            )

        if _is_dynamic_text_statement(statement, upper):
            _check_dynamic_sql(
                statement,
                lambda name: flow.reaching(name, block_index, position),
                declared_names,
                report,
            )

        if _is_non_executable(statement, upper):
            return

        handler = whenever.get("SQLERROR")
        if handler is not None and handler.upper() != "CONTINUE":
            return
        if _status_checked(block_index, position, blocks, by_name, status_cache):
            return

        report.violations.append(
            SqlCicsViolation(
                kind=KIND_NO_SQLCODE_CHECK,
                severity=SEVERITY_BY_KIND[KIND_NO_SQLCODE_CHECK],
                message=(
                    f"EXEC SQL {_sql_label(statement)} result is never checked: "
                    "nothing after it in this paragraph (or in a paragraph it "
                    "PERFORMs) references SQLCODE, SQLSTATE or SQLCA before "
                    "the next SQL statement overwrites them, and no "
                    "WHENEVER SQLERROR handler is in effect; test SQLCODE "
                    "immediately after the statement"
                ),
                location=statement.location,
                symbol=_sql_label(statement),
                detail={
                    "sql": text,
                    "whenever_sqlerror": whenever.get("SQLERROR"),
                    "scope": "paragraph + PERFORMed paragraphs",
                },
            )
        )

    # -- CICS --------------------------------------------------------------

    def _check_cics(
        self,
        statement: ExecCicsStatement,
        state: _CicsHandlerState,
        stack: list[_CicsHandlerState],
        report: SqlCicsReport,
    ) -> None:
        """Grade one ``EXEC CICS`` command, or let it update the handlers."""
        command = (statement.cics_command or "").upper()
        options = {key.upper(): value for key, value in statement.options.items()}
        line = statement.location.line if statement.location else 0

        if not command:
            report.unchecked.append(
                f"line {line}: EXEC CICS block whose command verb could not be "
                "identified; its error handling was not checked"
            )
            return
        if "EXEC" in options or "CICS" in options:
            # The collector ran past this block's END-EXEC and swallowed the
            # next one (an unterminated block, or a line truncated at column
            # 72). Whatever the option list says, it is not this command's.
            report.unchecked.append(
                f"line {line}: EXEC CICS {command} block ran into the following "
                "EXEC block, so its options could not be decomposed; its error "
                "handling was not checked"
            )
            return

        if command in _CICS_HANDLER_COMMANDS:
            _apply_cics_handler(command, options, state, stack, report, line)
            return

        if command == "ABEND":
            if not state.abend_handler:
                report.violations.append(
                    SqlCicsViolation(
                        kind=KIND_CICS_ABEND_NO_HANDLER,
                        severity=SEVERITY_BY_KIND[KIND_CICS_ABEND_NO_HANDLER],
                        message=(
                            "EXEC CICS ABEND with no HANDLE ABEND established: "
                            "the task ends with no chance to release resources "
                            "or log context; establish EXEC CICS HANDLE ABEND "
                            "LABEL(...) if the abend should be recoverable"
                        ),
                        location=statement.location,
                        symbol="ABEND",
                        detail={"options": sorted(options)},
                    )
                )
            return

        if command in CICS_NO_RESP_EXEMPT:
            return
        if "RESP" in options or "RESP2" in options or "NOHANDLE" in options:
            return
        if "ERROR" in state.conditions:
            return
        if state.conditions:
            report.unchecked.append(
                f"line {line}: EXEC CICS {command} has no RESP/NOHANDLE, and the "
                "HANDLE CONDITION in effect covers only "
                f"{', '.join(sorted(state.conditions))} -- nothing in the AST "
                "says which conditions this command can raise, so its error "
                "handling could not be graded"
            )
            return

        report.violations.append(
            SqlCicsViolation(
                kind=KIND_CICS_NO_RESP,
                severity=SEVERITY_BY_KIND[KIND_CICS_NO_RESP],
                message=(
                    f"EXEC CICS {command} has no RESP or RESP2 option, no "
                    "NOHANDLE, and no HANDLE CONDITION in effect: a condition "
                    "raised here takes the CICS default action and abends the "
                    "task; add RESP(WS-RESP) and test it against DFHRESP values"
                ),
                location=statement.location,
                symbol=command,
                detail={"options": sorted(options)},
            )
        )


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _sql_label(statement: ExecSQLStatement) -> str:
    """A short name for an SQL statement: its type, or its first word."""
    sql_type = (statement.sql_type or "").upper()
    if sql_type and sql_type != "UNKNOWN":
        return sql_type
    # The first *word*: the EXEC text collector glues a host variable's
    # colon to the word before it (``SET:WS-X = ...``).
    word = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)", statement.sql_text)
    return word.group(1).upper() if word else "EXEC SQL"


def _is_whenever(statement: ExecSQLStatement) -> bool:
    """True for a ``WHENEVER`` directive."""
    if (statement.sql_type or "").upper() == "WHENEVER":
        return True
    return statement.sql_text.upper().lstrip().startswith("WHENEVER")


def _apply_whenever(
    statement: ExecSQLStatement,
    whenever: dict[str, str],
    report: SqlCicsReport,
) -> None:
    """Fold one ``WHENEVER`` directive into the handler state."""
    text = " ".join(statement.sql_text.split())
    match = _WHENEVER_RE.match(text)
    line = statement.location.line if statement.location else 0
    if match is None:
        report.unchecked.append(
            f"line {line}: WHENEVER directive '{text}' could not be decomposed "
            "into a condition and an action; SQL statements after it were "
            "checked as if no handler were in effect"
        )
        return
    condition = " ".join(match.group(1).split()).upper()
    whenever[condition] = " ".join(match.group(2).split()).upper()


def _is_non_executable(statement: ExecSQLStatement, upper: str) -> bool:
    """True for a precompiler declaration -- nothing to check a status of."""
    if isinstance(statement, DeclareCursorStatement):
        return True
    if _DECLARE_GLOBAL_TEMPORARY_RE.match(upper):
        # The parser files this under DECLARE TABLE, but it executes (it
        # creates the table) and sets SQLCODE like any other statement.
        return False
    if (statement.sql_type or "").upper() in _NON_EXECUTABLE_SQL_TYPES:
        return True
    if any(upper.startswith(prefix) for prefix in _NON_EXECUTABLE_PREFIXES):
        return True
    return _DECLARE_NON_EXECUTABLE_RE.match(upper) is not None


def _is_singleton_select_without_into(statement: ExecSQLStatement, upper: str) -> bool:
    """True for a ``SELECT`` that keeps nothing and feeds no cursor."""
    if isinstance(statement, DeclareCursorStatement):
        return False
    if (statement.sql_type or "").upper() != "SELECT":
        return False
    if statement.into_variables or statement.cursor_name:
        return False
    # ``into_variables`` reads ``INTO:WS-NAME`` as written by the EXEC text
    # collector since 2026-09-28; the direct text check stays as a backstop.
    # Scrubbed: ``WHERE B = 'INTO :Z'`` is a literal, not an INTO clause.
    return _INTO_HOST_VAR_RE.search(_strip_sql_literals_and_comments(upper)) is None


def _is_dynamic_text_statement(statement: ExecSQLStatement, upper: str) -> bool:
    """True for ``PREPARE`` and ``EXECUTE IMMEDIATE`` -- the text-takers."""
    sql_type = (statement.sql_type or "").upper()
    if sql_type == "PREPARE" or upper.startswith("PREPARE"):
        return True
    return _EXECUTE_IMMEDIATE_RE.match(upper) is not None


def _check_connect(
    statement: ExecSQLStatement,
    upper: str,
    declared_names: set[str],
    report: SqlCicsReport,
) -> None:
    """Report literal credentials in an ``EXEC SQL CONNECT``."""
    line = statement.location.line if statement.location else 0
    for match in _CONNECT_OPERAND_RE.finditer(upper):
        keyword = match.group(1).upper()
        operand = match.group(2).strip()
        if operand.startswith(":"):
            continue  # a host variable: exactly what should be there
        if _normalize_name(operand) in declared_names:
            # A quoted literal keeps its quotes in EXEC SQL text, so a bare
            # word here is a data item referenced without its colon. A name
            # the DATA DIVISION declares is not something to call a
            # hardcoded password.
            report.unchecked.append(
                f"line {line}: EXEC SQL CONNECT ... {keyword} {operand} names a "
                "declared data item but carries no host-variable colon; whether "
                "it is a literal or a mis-written host variable could not be "
                "determined, so it was not reported as a hardcoded credential"
            )
            continue
        what, suggestion = _CONNECT_CREDENTIAL_KEYWORDS[keyword]
        report.violations.append(
            SqlCicsViolation(
                kind=KIND_HARDCODED_CREDENTIALS,
                severity=SEVERITY_BY_KIND[KIND_HARDCODED_CREDENTIALS],
                message=(
                    f"EXEC SQL CONNECT hardcodes the {what} in {keyword}: it "
                    "ships in the source, the listing and the load module, and "
                    "rotating it means a recompile; move it to a host variable "
                    f"({keyword} {suggestion}) filled from a secured external "
                    "source"
                ),
                location=statement.location,
                symbol="CONNECT",
                detail={"keyword": keyword, "credential": what},
            )
        )


def _check_dynamic_sql(
    statement: ExecSQLStatement,
    reaching: Callable[[str], list[ASTNode]],
    declared_names: set[str],
    report: SqlCicsReport,
) -> None:
    """Trace each host variable handed to PREPARE / EXECUTE IMMEDIATE.

    One finding per host variable, however many statements wrote it: the
    defect is that untrusted text reaches this ``PREPARE``, and every writer
    that carries it there is listed in ``detail["assignments"]``. *reaching*
    names the writers whose text can still be in the item when this
    statement runs (see ``_WriterFlow``).
    """
    line = statement.location.line if statement.location else 0
    label = _sql_label(statement)
    for raw in statement.host_variables:
        name = _normalize_name(raw)
        if not name:
            continue
        assignments = reaching(name)
        if not assignments:
            report.unchecked.append(
                f"line {line}: the statement text {label} executes comes from "
                f":{raw}, which no STRING or MOVE in this program unit assigns; "
                "its content could not be traced (it may be set by ACCEPT, "
                "READ, a CALL or a copybook VALUE clause), so it was neither "
                "cleared nor reported"
            )
            continue

        unsafe: list[dict[str, Any]] = []
        for assignment in assignments:
            if isinstance(assignment, StringStatement):
                sources = [
                    operand
                    for operand in assignment.operands
                    if _normalize_name(operand) in declared_names
                ]
                if not sources:
                    # Every operand is a literal, or names something this
                    # program unit does not declare -- and the lexer dropped
                    # the quotes that would tell those two apart.
                    report.unchecked.append(
                        f"line {line}: :{raw} is built by the STRING at line "
                        f"{_line_of(assignment)}, but none of its operands names "
                        "a declared data item and the lexer drops the quotes "
                        "around a literal, so whether any of them is untrusted "
                        "could not be determined"
                    )
                    continue
                unsafe.append(
                    {
                        "kind": "STRING",
                        "line": _line_of(assignment),
                        "sources": sources,
                    }
                )
            elif isinstance(assignment, MoveStatement):
                source = (assignment.source or "").strip()
                if _is_literal(source):
                    continue  # a constant statement is not an injection path
                unsafe.append(
                    {
                        "kind": "MOVE",
                        "line": _line_of(assignment),
                        "sources": [source],
                    }
                )

        if not unsafe:
            continue
        report.violations.append(
            _concatenation_violation(
                statement,
                label=label,
                host_variable=raw,
                how=_describe_assignments(unsafe),
                detail={
                    "host_variable": raw,
                    "built_by": sorted({entry["kind"] for entry in unsafe}),
                    "sources": [
                        source for entry in unsafe for source in entry["sources"]
                    ],
                    "assignments": unsafe,
                },
            )
        )


def _describe_assignments(unsafe: list[dict[str, Any]]) -> str:
    """One phrase naming where a dynamic statement's text came from."""
    if len(unsafe) == 1:
        entry = unsafe[0]
        sources = ", ".join(entry["sources"])
        if entry["kind"] == "STRING":
            return f"concatenated by the STRING at line {entry['line']} from {sources}"
        return f"moved in from {sources} by the MOVE at line {entry['line']}"
    parts = [
        f"the {entry['kind']} at line {entry['line']} from "
        f"{', '.join(entry['sources'])}"
        for entry in unsafe
    ]
    return "assembled by " + "; ".join(parts)


def _concatenation_violation(
    statement: ExecSQLStatement,
    *,
    label: str,
    host_variable: str,
    how: str,
    detail: dict[str, Any],
) -> SqlCicsViolation:
    """Build one :data:`KIND_DYNAMIC_CONCATENATION` finding."""
    return SqlCicsViolation(
        kind=KIND_DYNAMIC_CONCATENATION,
        severity=SEVERITY_BY_KIND[KIND_DYNAMIC_CONCATENATION],
        message=(
            f"EXEC SQL {label} executes the text in :{host_variable}, which is "
            f"{how}: any value reaching that field becomes SQL, which is an "
            "injection path; use a fixed statement with parameter markers and "
            "pass the values with USING :host-var"
        ),
        location=statement.location,
        symbol=host_variable,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# CICS helpers
# ---------------------------------------------------------------------------


def _apply_cics_handler(
    command: str,
    options: dict[str, str | None],
    state: _CicsHandlerState,
    stack: list[_CicsHandlerState],
    report: SqlCicsReport,
    line: int,
) -> None:
    """Fold one handler-management command into the handler state."""
    if command == "PUSH":
        # PUSH HANDLE suspends every handler in effect until the matching POP.
        stack.append(state.copy())
        state.conditions.clear()
        state.abend_handler = False
        return

    if command == "POP":
        if not stack:
            report.unchecked.append(
                f"line {line}: EXEC CICS POP HANDLE with no matching PUSH "
                "HANDLE in this program unit; the handler state after it is "
                "whatever the caller established, so commands that follow were "
                "checked as if no handler were in effect"
            )
            state.conditions.clear()
            state.abend_handler = False
            return
        restored = stack.pop()
        state.conditions = restored.conditions
        state.abend_handler = restored.abend_handler
        return

    if "ABEND" in options:
        if "CANCEL" in options:
            state.abend_handler = False
        elif "LABEL" in options or "PROGRAM" in options:
            state.abend_handler = True
        elif "RESET" in options:
            report.unchecked.append(
                f"line {line}: EXEC CICS HANDLE ABEND RESET reinstates a handler "
                "established elsewhere (possibly by a caller); the abend "
                "handler state after it is "
                f"{'active' if state.abend_handler else 'unknown'}"
            )
        return

    if "AID" in options:
        # HANDLE AID routes attention identifiers, not conditions.
        return

    if "CONDITION" not in options:
        report.unchecked.append(
            f"line {line}: EXEC CICS {command} is neither CONDITION, ABEND nor "
            "AID; the handler state it establishes was not modelled"
        )
        return

    conditions = [key for key in options if key != "CONDITION"]
    for condition in conditions:
        label = options.get(condition)
        if command == "IGNORE" or not label:
            # IGNORE CONDITION cancels the handler; HANDLE CONDITION with a
            # bare condition name restores the CICS default action. Neither
            # leaves anything for this analyzer to credit.
            state.conditions.pop(condition, None)
        else:
            state.conditions[condition] = label
    if not conditions:
        report.unchecked.append(
            f"line {line}: EXEC CICS {command} CONDITION names no condition; the "
            "handler state it establishes was not modelled"
        )


# ---------------------------------------------------------------------------
# Traversal helpers
# ---------------------------------------------------------------------------


def _build_blocks(ast: CobolProgram) -> tuple[list[_Block], dict[str, list[int]]]:
    """Flatten the PROCEDURE DIVISION into source-ordered paragraph blocks.

    Returns the blocks and an index from paragraph *and* section name to the
    blocks that name covers, so a ``PERFORM`` of either can be followed.
    """
    blocks: list[_Block] = []
    by_name: dict[str, list[int]] = {}
    division = ast.procedure_division
    if division is None:
        return blocks, by_name

    entities: list[CobolSection | CobolParagraph] = [
        *division._sections.values(),
        *division.paragraphs,
    ]
    entities.sort(key=_line_of)

    def add_paragraph(paragraph: CobolParagraph, section: str | None) -> None:
        name = (paragraph.paragraph_name or "").strip().upper()
        statements = list(_iter_statements(paragraph.statements))
        unconditional = {id(statement) for statement in paragraph.statements}
        if not _is_real_paragraph_name(name) and blocks:
            # A parser-synthesised fragment (statements written before the
            # first paragraph header get one anonymous paragraph each).
            # Merging keeps "the statements that follow it" honest.
            blocks[-1].statements.extend(statements)
            blocks[-1].unconditional |= unconditional
            return
        index = len(blocks)
        blocks.append(
            _Block(name=name, statements=statements, unconditional=unconditional)
        )
        if name:
            by_name.setdefault(name, []).append(index)
        if section:
            by_name.setdefault(section, []).append(index)

    for entity in entities:
        if isinstance(entity, CobolSection):
            section_name = (entity.section_name or "").strip().upper()
            for paragraph in entity.paragraphs:
                add_paragraph(paragraph, section_name or None)
        elif isinstance(entity, CobolParagraph):
            add_paragraph(entity, None)
    return blocks, by_name


def _is_real_paragraph_name(name: str) -> bool:
    """True when *name* is a paragraph label rather than parser punctuation."""
    return bool(name) and any(character.isalnum() for character in name)


def _iter_statements(nodes: Any) -> Iterator[ASTNode]:
    """Yield every statement under *nodes* in source (pre-)order.

    Walks AST children *and* the attributes that hold nested statements
    without parenting them, so an ``EXEC SQL`` inside an ``IF`` or an
    ``AT END`` clause is seen.
    """
    seen: set[int] = set()

    def walk(node: Any) -> Iterator[ASTNode]:
        if isinstance(node, (list, tuple)):
            for item in node:
                yield from walk(item)
            return
        if not isinstance(node, ASTNode):
            return
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, CobolStatement):
            yield node
        for child in node.children:
            yield from walk(child)
        for attribute in _NESTED_STATEMENT_ATTRS:
            value = getattr(node, attribute, None)
            if value:
                yield from walk(value)

    yield from walk(nodes)


def _status_checked(
    block_index: int,
    position: int,
    blocks: list[_Block],
    by_name: dict[str, list[int]],
    cache: dict[int, bool],
    visited: set[int] | None = None,
) -> bool:
    """True when something after *position* looks at the SQL status.

    "After" means later in the same paragraph, or anywhere in a paragraph
    (or section) reached by a ``PERFORM`` written after it. *cache* memoises
    the per-statement scan, which is otherwise repeated once per SQL
    statement in the same paragraph.

    The search stops at the next executable ``EXEC SQL`` written directly
    in a paragraph (one inside an IF body may not run): it resets the
    SQLCA, so a check written after it tests *that* statement's outcome,
    not this one's.
    """
    return (
        _scan_for_status(block_index, position, blocks, by_name, cache, visited) is True
    )


def _scan_for_status(
    block_index: int,
    position: int,
    blocks: list[_Block],
    by_name: dict[str, list[int]],
    cache: dict[int, bool],
    visited: set[int] | None = None,
) -> bool | None:
    """``True`` status checked, ``False`` SQLCA overwritten first, else ``None``."""
    if visited is None:
        visited = set()
    block = blocks[block_index]
    for statement in block.statements[position + 1 :]:
        checked = cache.get(id(statement))
        if checked is None:
            checked = _references_sql_status(statement)
            cache[id(statement)] = checked
        if checked:
            return True
        if id(statement) in block.unconditional and _resets_sqlca(statement):
            return False
        if isinstance(statement, PerformStatement):
            for index in _perform_block_indexes(statement, by_name):
                if index in visited:
                    continue
                visited.add(index)
                found = _scan_for_status(index, -1, blocks, by_name, cache, visited)
                if found is not None:
                    return found
    return None


def _resets_sqlca(statement: ASTNode) -> bool:
    """True for an executable ``EXEC SQL`` -- one that sets SQLCODE anew."""
    if not isinstance(statement, ExecSQLStatement) or _is_whenever(statement):
        return False
    upper = " ".join(statement.sql_text.split()).upper()
    return not _is_non_executable(statement, upper)


def _perform_block_indexes(
    statement: PerformStatement, by_name: dict[str, list[int]]
) -> list[int]:
    """The blocks one PERFORM runs, in source order.

    ``PERFORM A THRU C`` runs every paragraph from A through C, not just the
    two named ends: a status check in a paragraph between them is reached.
    """
    target = _procedure_name(getattr(statement, "target_paragraph", None))
    if not target:
        return []
    starts = by_name.get(target, [])
    thru = _procedure_name(getattr(statement, "thru_paragraph", None))
    if not thru or not starts:
        return list(starts)
    first = min(starts)
    ends = [index for index in by_name.get(thru, []) if index >= first]
    if not ends:
        # The range end is unknown or precedes its start; credit only the
        # two named procedures, as before.
        return sorted(set(starts) | set(by_name.get(thru, [])))
    return list(range(first, max(ends) + 1))


def _procedure_name(value: Any) -> str:
    """An upper-cased PERFORM operand, or "" when absent."""
    return value.strip().upper() if isinstance(value, str) else ""


def _references_sql_status(node: ASTNode) -> bool:
    """True when *node*'s operands name SQLCODE, SQLSTATE or SQLCA."""
    return bool(_words_of(node) & _SQL_STATUS_WORDS)


def _words_of(node: Any, seen: set[int] | None = None) -> set[str]:
    """Every identifier-shaped word in *node*'s own attributes.

    Deliberately generic: statements keep their operands in differently named
    attributes (``source``, ``targets``, ``left_operand``, ``expression``,
    ``selectors``, ``using_parameters``), and a check that enumerated them
    would miss the next statement class somebody adds.
    """
    if seen is None:
        seen = set()
    if id(node) in seen:
        return set()
    seen.add(id(node))

    words: set[str] = set()
    if isinstance(node, str):
        return {part.upper() for part in re.split(r"[^A-Za-z0-9_-]+", node) if part}
    if isinstance(node, (list, tuple, set)):
        for item in node:
            words |= _words_of(item, seen)
        return words
    if isinstance(node, dict):
        for item in node.values():
            words |= _words_of(item, seen)
        return words
    attributes = getattr(node, "__dict__", None)
    if not attributes:
        return words
    for key, value in attributes.items():
        if key in ("parent", "_metadata", "_type_cache", "location"):
            continue
        words |= _words_of(value, seen)
    return words


def _assignment_index(
    ordered: list[tuple[int, int, ASTNode]],
) -> dict[str, list[ASTNode]]:
    """Map each data item name to the STRINGs and MOVEs that write it."""
    writers: dict[str, list[ASTNode]] = {}
    for _, _, statement in ordered:
        if isinstance(statement, StringStatement):
            target = _normalize_name(statement.into_target or "")
            if target:
                writers.setdefault(target, []).append(statement)
        elif isinstance(statement, MoveStatement):
            for raw in statement.targets:
                target = _normalize_name(raw)
                if target:
                    writers.setdefault(target, []).append(statement)
    return writers


class _WriterFlow:
    """Which STRINGs and MOVEs can still be in an item at one statement.

    The program-wide answer (every writer anywhere) is the fallback. It is
    narrowed only when the item is overwritten whole, unconditionally,
    earlier in the same paragraph: a ``MOVE`` to the bare item (no
    reference modification, no subscript, not ``CORRESPONDING``) written
    directly in the paragraph, so it always runs first. That MOVE replaces
    every byte, so writers before it -- and writers elsewhere in the
    program -- cannot reach the statement. What still can:

    * the MOVE itself, and every writer between it and the statement in
      the same paragraph (conditional ones included);
    * every writer in a paragraph a ``PERFORM`` in that stretch runs,
      transitively;
    * when the paragraph-level statement holding it contains an inline
      ``PERFORM`` loop anywhere, every writer in that statement, since a
      later pass may run them before it (conservative: the loop need not
      enclose this statement).

    A ``STRING`` never cuts the trace: it leaves the bytes past what it
    transfers untouched, so earlier content can survive it.
    """

    def __init__(
        self,
        blocks: list[_Block],
        by_name: dict[str, list[int]],
        writers: dict[str, list[ASTNode]],
    ) -> None:
        self._blocks = blocks
        self._by_name = by_name
        self._writers = writers

    def reaching(self, name: str, block_index: int, position: int) -> list[ASTNode]:
        """The writers of *name* that can reach ``statements[position]``."""
        everywhere = self._writers.get(name, [])
        if not everywhere:
            return []
        block = self._blocks[block_index]
        statements = block.statements
        # The statement written directly in the paragraph that holds this
        # one (itself, when it is not nested in an IF/EVALUATE/loop).
        top = next(
            (
                index
                for index in range(position, -1, -1)
                if id(statements[index]) in block.unconditional
            ),
            None,
        )
        if top is None:
            return everywhere
        kill = next(
            (
                index
                for index in range(top - 1, -1, -1)
                if id(statements[index]) in block.unconditional
                and _overwrites_whole(statements[index], name)
            ),
            None,
        )
        if kill is None:
            return everywhere
        top_end = next(
            (
                index
                for index in range(top + 1, len(statements))
                if id(statements[index]) in block.unconditional
            ),
            len(statements),
        )
        in_loop = any(
            isinstance(node, PerformStatement)
            and getattr(node, "inline_statements", None)
            for node in statements[top:top_end]
        )
        stretch = statements[kill : top_end if in_loop else position]
        reached = {id(node) for node in stretch}
        visited: set[int] = set()
        pending = [node for node in stretch if isinstance(node, PerformStatement)]
        while pending:
            perform = pending.pop()
            for index in _perform_block_indexes(perform, self._by_name):
                if index in visited:
                    continue
                visited.add(index)
                for node in self._blocks[index].statements:
                    reached.add(id(node))
                    if isinstance(node, PerformStatement):
                        pending.append(node)
        return [writer for writer in everywhere if id(writer) in reached]


def _overwrites_whole(statement: ASTNode, name: str) -> bool:
    """True for a MOVE that replaces every byte of the item *name*."""
    if not isinstance(statement, MoveStatement) or statement.is_corresponding:
        return False
    return any(
        "(" not in raw and _normalize_name(raw) == name for raw in statement.targets
    )


def _declared_data_names(ast: CobolProgram) -> set[str]:
    """Every DATA DIVISION item name in this program unit, upper-cased."""
    names: set[str] = set()
    for item in ast.get_data_items():
        name = _normalize_name(getattr(item, "name", "") or "")
        if name:
            names.add(name)
    return names


def _normalize_name(raw: str) -> str:
    """Reduce a reference to the bare item name it addresses.

    Strips a host-variable colon, a subscript or reference modification, and
    any ``OF``/``IN`` qualification, so ``:WS-STMT(1:80)`` and
    ``WS-STMT OF WS-REC`` both reduce to ``WS-STMT``.
    """
    text = raw.strip().lstrip(":")
    text = text.split("(", 1)[0]
    parts = re.split(r"\s+(?:OF|IN)\s+", text, flags=re.IGNORECASE)
    return parts[0].strip().upper()


def _is_literal(source: str) -> bool:
    """True when a MOVE source is a literal rather than a data item."""
    if not source:
        return False
    if source[0] in "'\"":
        return True
    if source.upper() in _FIGURATIVE_CONSTANTS:
        return True
    return bool(re.fullmatch(r"[+-]?[0-9][0-9.]*", source))


def _line_of(node: Any) -> int:
    """The source line of *node*, or 0 when it carries no location."""
    location = getattr(node, "location", None)
    return location.line if location is not None else 0


def _violation_order(violation: SqlCicsViolation) -> tuple[int, int, str]:
    """Source order, then kind, so a report is stable run to run."""
    location = violation.location
    line = location.line if location is not None else 0
    column = location.column if location is not None else 0
    return (line, column, violation.kind)
