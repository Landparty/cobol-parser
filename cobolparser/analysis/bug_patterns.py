"""
Single-program bug patterns the other analyzers do not look for.

Each rule here finds one classic COBOL production bug that compiles cleanly
and that none of the per-concern analyzers reports: a MOVE that silently
cuts its value, a literal subscript past the end of a table, a NEXT SENTENCE
that jumps further than its author thought, a GO TO that leaves a PERFORM
range and never comes back, a FILE STATUS nobody reads, a numeric field read
before anything is stored in it, and the ALTER verb. The rules are lint rules
(:mod:`.lint` runs them); :class:`BugPatternAnalyzer` is usable on its own too.

The guiding rule is the package's own: **exact by construction, or
absent**. Every rule reports only what it can prove from the program text,
and stays quiet when an operand cannot be resolved (a name declared twice, a
variable subscript, a reference modification, a group item whose length is
not known). Each rule documents what it skips, so a quiet report is a clean
one *for what the rule checks*, never a guess.

Rules (rule id, ``kind``, severity):

- ``truncation``
    - ``MOVE_LOSES_DIGITS`` (warning): a MOVE whose sender has more integer
      digits than the numeric receiver keeps.
    - ``MOVE_LOSES_CHARACTERS``: a MOVE whose sender is longer than the
      alphanumeric receiver. A warning when the sender is a constant (a
      literal, or an item with a VALUE nothing ever changes) whose value
      does not fit; info when it is a variable, whose content may well fit
      (moving a 100-byte description into a 26-byte screen field is often
      deliberate). A constant judges by its value, not its PICTURE:
      ``PIC X(8) VALUE 'COACTUP'`` fits a 7-byte receiver. Decimal places
      and the sign are not reported here (``move-type-check`` speaks for
      categories).
    - ``ARITHMETIC_LOSES_DIGITS`` (warning): ADD / SUBTRACT, or a COMPUTE made
      only of additions and subtractions, whose operand has more integer
      digits than the receiving field, with no ON SIZE ERROR phrase.
- ``subscript-range``
    - ``SUBSCRIPT_OUT_OF_RANGE`` (error): a literal subscript below 1 or
      above the OCCURS bound of its dimension (``WS-ENT(11)`` on ``OCCURS
      10``). Only all-literal subscript lists whose count matches the
      table's dimensions are checked.
- ``next-sentence``
    - ``NEXT_SENTENCE_IN_END_IF`` (warning): NEXT SENTENCE inside an IF
      closed by END-IF, when statements follow the END-IF before the
      period. NEXT SENTENCE jumps past the next *period*, not past the
      END-IF, so those statements are skipped.
- ``perform-range``
    - ``PERFORM_THRU_BACKWARDS`` (error): ``PERFORM B THRU A`` where A comes
      before B in the source.
    - ``GO_TO_OUT_OF_PERFORM`` (warning): a GO TO from inside every PERFORM
      range that holds it to a procedure outside all of them. The PERFORM
      never returns; control runs on from the target. A target that ends the
      run (STOP RUN, GOBACK, EXIT PROGRAM, EXEC CICS RETURN / XCTL / ABEND,
      an abend CALL) is an exit, not a bug, and is not reported.
    - ``FALLS_INTO_PERFORMED`` (warning): the main line reaches the end of a
      paragraph with no STOP RUN / GOBACK / GO TO and falls into a paragraph
      the program also PERFORMs (the missing-STOP-RUN bug).
- ``file-status``
    - ``FILE_STATUS_NOT_CHECKED`` (warning): a SELECT declares FILE STATUS,
      the program does I/O on the file, and nothing ever reads the status
      item (nor its subfields, condition names, group or REDEFINES), with no
      DECLARATIVES to handle errors either.
- ``uninitialized``
    - ``NUMERIC_NEVER_SET`` (warning): a numeric WORKING-STORAGE /
      LOCAL-STORAGE item with no VALUE clause that the program reads but
      never stores into -- nor into its group, its REDEFINES, or by passing
      it to a CALL, an EXEC block or an INITIALIZE. Its content is whatever
      the storage held, often spaces: a data exception (S0C7) waiting for
      the first arithmetic.
- ``obsolete-verb``
    - ``ALTER`` (warning): the ALTER verb, removed from the 2002 standard;
      every GO TO it changes hides its real target from a reader.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .._literals import QUOTED_LITERAL_RE
from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolParagraph, CobolProgram, CobolSection
from ..models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    SubtractStatement,
)
from ..models.statements.base import (
    NESTED_BODY_ATTRS,
    CobolStatement,
    iter_clause_bodies,
    walk_statements,
)
from ..models.statements.control import (
    GoStatement,
    IfStatement,
    PerformStatement,
    StopStatement,
)
from ..models.statements.data import MoveStatement, SetStatement
from ..models.statements.misc import (
    AlterStatement,
    ExitStatement,
    GobackStatement,
    NextSentenceStatement,
    SelectStatement,
)
from ._abend import abend_call_target
from ._cics import cics_exit_kind, cics_terminator_kind
from ._procedures import (
    ProcedureEntry,
    ProcedureIndex,
    branch_terminates,
    enclosing_section,
    statement_qualifier,
)
from .field_widening import Capacity, capacity_of
from .program_flow import FlowEdgeType, ProgramFlowAnalyzer, ProgramFlowReport

#: Every rule this module runs, in report order.
BUG_PATTERN_RULES: tuple[str, ...] = (
    "truncation",
    "subscript-range",
    "next-sentence",
    "perform-range",
    "file-status",
    "uninitialized",
    "obsolete-verb",
)

#: One-line description per rule (SARIF ``shortDescription``, ``--help``).
BUG_PATTERN_DESCRIPTIONS: dict[str, str] = {
    "truncation": "MOVE or ADD/SUBTRACT/COMPUTE that silently cuts digits "
    "or characters",
    "subscript-range": "Literal subscript outside the table's OCCURS bounds",
    "next-sentence": "NEXT SENTENCE inside END-IF that skips statements after "
    "the END-IF",
    "perform-range": "PERFORM THRU backwards, GO TO out of a PERFORM range, or "
    "the main line falling into a PERFORMed paragraph",
    "file-status": "FILE STATUS declared but never checked",
    "uninitialized": "Numeric item read but never set and without VALUE",
    "obsolete-verb": "ALTER statement",
}

_SEVERITY: dict[str, str] = {
    "MOVE_LOSES_DIGITS": "warning",
    "MOVE_LOSES_CHARACTERS": "info",
    "ARITHMETIC_LOSES_DIGITS": "warning",
    "SUBSCRIPT_OUT_OF_RANGE": "error",
    "NEXT_SENTENCE_IN_END_IF": "warning",
    "PERFORM_THRU_BACKWARDS": "error",
    "GO_TO_OUT_OF_PERFORM": "warning",
    "FALLS_INTO_PERFORMED": "warning",
    "FILE_STATUS_NOT_CHECKED": "warning",
    "NUMERIC_NEVER_SET": "warning",
    "ALTER": "warning",
}

_NAME = r"[A-Za-z0-9][A-Za-z0-9-]*"
_PAREN_RE = re.compile(r"\([^()]*\)")
_QUALIFIER_SPLIT_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)
_NAME_RE = re.compile(rf"^{_NAME}$")
_NUMERIC_LITERAL_RE = re.compile(r"^([+-]?)(\d*)(?:[.,](\d*))?$")
_SUBSCRIPTED_RE = re.compile(rf"(?<![A-Za-z0-9-])({_NAME})\s*\(([^()]*)\)")
_ADDRESS_OF_RE = re.compile(rf"\bADDRESS\s+OF\s+({_NAME})", re.IGNORECASE)
_INTEGER_RE = re.compile(r"^[+]?\d+$")
_COMPUTE_TOKEN_RE = re.compile(rf"{_NAME}|\d+(?:\.\d+)?|[-+()]|\S")
_FIGURATIVE = frozenset(
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
        "ALL",
    }
)
#: Fields of the SQL communication area: DB2 stores into them.
_SQLCA_NAMES = frozenset(
    {"SQLCA", "SQLCODE", "SQLSTATE", "SQLERRD", "SQLWARN", "SQLERRM", "SQLCADE"}
)
_STORAGE_SECTIONS = frozenset({"WORKING-STORAGE", "LOCAL-STORAGE"})
_UNSAFE_USAGES = frozenset(
    {"INDEX", "POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "COMP-1", "COMP-2"}
)
#: xref roles that only read a data item. Every other role (write, a CALL
#: argument, a host variable, an unknown reference) may store into it.
_READ_ROLES = frozenset({"read", "condition", "subscript"})
_PERFORM_EDGES = frozenset(
    {
        FlowEdgeType.PERFORM,
        FlowEdgeType.PERFORM_THRU,
        FlowEdgeType.SORT_INPUT_PROCEDURE,
        FlowEdgeType.SORT_INPUT_PROCEDURE_THRU,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE,
        FlowEdgeType.SORT_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE,
        FlowEdgeType.MERGE_OUTPUT_PROCEDURE_THRU,
        FlowEdgeType.XML_PROCESSING_PROCEDURE,
        FlowEdgeType.XML_PROCESSING_PROCEDURE_THRU,
    }
)
_GOTO_EDGES = frozenset({FlowEdgeType.GOTO, FlowEdgeType.GOTO_DEPENDING})


@dataclass
class BugFinding:
    """One bug-pattern finding."""

    rule: str
    kind: str
    message: str
    location: SourceLocation | None
    symbol: str | None = None
    #: Defaults to the kind's severity (``_SEVERITY``).
    severity: str = ""

    def __post_init__(self) -> None:
        if not self.severity:
            self.severity = _SEVERITY[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "location": self.location.to_dict() if self.location else None,
            "symbol": self.symbol,
        }


@dataclass
class BugPatternReport:
    findings: list[BugFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"findings": [f.to_dict() for f in self.findings]}


# ---------------------------------------------------------------------------
# Statement walking
# ---------------------------------------------------------------------------


def _nested_lists(stmt: Any) -> Iterator[list[Any]]:
    """Every statement list nested directly inside *stmt* (the canonical
    ``iter_clause_bodies``; ``walk_statements`` is re-exported from the
    statement models)."""
    for body in iter_clause_bodies(stmt):
        yield body.statements


def _procedure_statements(node: Any) -> list[Any]:
    """The top-level statements of a paragraph, or of a section's paragraphs."""
    if isinstance(node, CobolParagraph):
        return list(node.statements)
    if isinstance(node, CobolSection):
        out: list[Any] = []
        for para in node.paragraphs:
            out.extend(para.statements)
        return out
    return []


def _is_run_end(stmt: Any) -> bool:
    """A statement after which the run unit (or this program) has ended."""
    if isinstance(stmt, StopStatement):
        return (stmt.stop_type or "RUN").upper() == "RUN"
    if isinstance(stmt, GobackStatement):
        return True
    if isinstance(stmt, ExitStatement):
        return (stmt.exit_type or "").upper() == "PROGRAM"
    return bool(cics_exit_kind(stmt) or abend_call_target(stmt))


def _is_unconditional_transfer(stmt: Any) -> bool:
    """A statement control never passes to the next statement after."""
    if isinstance(stmt, GoStatement):
        return True
    if isinstance(stmt, StopStatement):
        return (stmt.stop_type or "RUN").upper() == "RUN"
    if isinstance(stmt, GobackStatement):
        return True
    if isinstance(stmt, ExitStatement):
        return (stmt.exit_type or "").upper() == "PROGRAM"
    if cics_terminator_kind(stmt) or abend_call_target(stmt):
        return True
    return branch_terminates(stmt, _is_unconditional_transfer)


# ---------------------------------------------------------------------------
# Data items
# ---------------------------------------------------------------------------


def _ancestors(item: CobolDataItem) -> list[CobolDataItem]:
    """Enclosing data items, innermost first."""
    out: list[CobolDataItem] = []
    node = item.parent
    while isinstance(node, CobolDataItem):
        out.append(node)
        node = node.parent
    return out


def _is_elementary(item: CobolDataItem) -> bool:
    return not any(isinstance(c, CobolDataItem) for c in item.children) and (
        item.level not in (66, 88)
    )


@dataclass
class _Operand:
    name: str
    qualifiers: list[str]
    subscripts: str | None
    reference_modified: bool


def _parse_operand(text: str) -> _Operand | None:
    """A data reference's name, qualifiers and subscript text, or None."""
    text = (text or "").strip()
    if not text:
        return None
    groups = _PAREN_RE.findall(text)
    refmod = any(":" in g for g in groups)
    subscripts = next((g[1:-1] for g in groups if ":" not in g), None)
    bare = _PAREN_RE.sub(" ", text)
    parts = [p.strip() for p in _QUALIFIER_SPLIT_RE.split(bare) if p.strip()]
    if not parts or not all(_NAME_RE.match(p) for p in parts):
        return None
    return _Operand(
        name=parts[0].upper(),
        qualifiers=[p.upper() for p in parts[1:]],
        subscripts=subscripts,
        reference_modified=refmod,
    )


class _DataIndex:
    """Name -> declared data items of one program unit."""

    def __init__(self, ast: CobolProgram) -> None:
        from .unused_variables import collect_declared_items

        self.items = collect_declared_items(ast)
        self.by_name: dict[str, list[CobolDataItem]] = {}
        for item in self.items:
            self.by_name.setdefault(item.name.upper(), []).append(item)

    def resolve(self, operand: _Operand) -> CobolDataItem | None:
        """The one item *operand* names, or None when absent or ambiguous."""
        candidates = self.by_name.get(operand.name, [])
        if operand.qualifiers:
            wanted = set(operand.qualifiers)
            candidates = [
                c
                for c in candidates
                if wanted
                <= {a.name.upper() for a in _ancestors(c)}
                | {str(c.get_metadata("fd_file_name") or "").upper()}
            ]
        return candidates[0] if len(candidates) == 1 else None


def _item_capacity(item: CobolDataItem) -> Capacity | None:
    if not _is_elementary(item) or item.picture_clause is None:
        return None
    if str(item.usage or "").upper() in _UNSAFE_USAGES:
        return None
    return capacity_of(item.picture_clause.pattern, item.usage, None, False)


def _literal_text(text: str) -> str:
    """The characters of a quoted literal (doubled quotes undone)."""
    text = text.strip()
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        return text[1:-1].replace(text[0] * 2, text[0])
    return text


def _literal_capacity(text: str) -> Capacity | None:
    """The capacity a literal sender needs, or None for anything else."""
    text = text.strip()
    if not text:
        return None
    if text[0] in "'\"" and len(text) >= 2 and text[-1] == text[0]:
        inner = text[1:-1].replace(text[0] * 2, text[0])
        return Capacity(False, chars=len(inner))
    match = _NUMERIC_LITERAL_RE.match(text)
    if match and (match.group(2) or match.group(3)):
        integer = (match.group(2) or "").lstrip("0")
        decimal = (match.group(3) or "").rstrip("0")
        return Capacity(True, len(integer), len(decimal), signed=match.group(1) == "-")
    return None


# ---------------------------------------------------------------------------
# The analyzer
# ---------------------------------------------------------------------------


class BugPatternAnalyzer:
    """Run the bug-pattern rules over one program unit.

    Usage::

        report = BugPatternAnalyzer().analyze(ast)
        report.findings   # list[BugFinding]

    ``rules`` selects a subset of :data:`BUG_PATTERN_RULES`. Like the other
    analyzers it is program-unit scoped: ``ast.contained_programs`` are not
    examined (lint visits every unit).
    """

    def __init__(self, rules: Iterable[str] | None = None) -> None:
        selected = list(BUG_PATTERN_RULES if rules is None else rules)
        unknown = set(selected) - set(BUG_PATTERN_RULES)
        if unknown:
            raise ValueError(f"unknown bug-pattern rule(s): {sorted(unknown)}")
        self.rules = tuple(r for r in BUG_PATTERN_RULES if r in set(selected))

    def analyze(
        self, ast: CobolProgram, *, flow_report: ProgramFlowReport | None = None
    ) -> BugPatternReport:
        context = _Context(ast, flow_report)
        report = BugPatternReport()
        for rule in self.rules:
            report.findings.extend(context.run(rule))
        return report


class _Context:
    """Lazily built facts one program unit's rules share."""

    def __init__(self, ast: CobolProgram, flow: ProgramFlowReport | None) -> None:
        self.ast = ast
        self._flow = flow
        self._data: _DataIndex | None = None
        self._xref: Any = None
        self._index: ProcedureIndex | None = None
        self._statements: list[Any] | None = None
        self._addresses: set[str] | None = None

    # -- shared facts --------------------------------------------------------

    @property
    def data(self) -> _DataIndex:
        if self._data is None:
            self._data = _DataIndex(self.ast)
        return self._data

    @property
    def xref(self) -> Any:
        if self._xref is None:
            from .xref import XrefAnalyzer

            self._xref = XrefAnalyzer().analyze(self.ast)
        return self._xref

    @property
    def flow(self) -> ProgramFlowReport:
        if self._flow is None:
            self._flow = ProgramFlowAnalyzer().analyze(self.ast)
        return self._flow

    @property
    def procedures(self) -> ProcedureIndex | None:
        if self._index is None and self.ast.procedure_division is not None:
            self._index = ProcedureIndex.build(self.ast.procedure_division)
        return self._index

    def top_statements(self) -> list[Any]:
        """Top-level statements of every procedure, in source order."""
        division = self.ast.procedure_division
        if division is None:
            return []
        out: list[Any] = []
        for para in _all_paragraphs(division):
            out.extend(para.statements)
        return out

    def statements(self) -> list[Any]:
        if self._statements is None:
            self._statements = list(walk_statements(self.top_statements()))
        return self._statements

    def run(self, rule: str) -> list[BugFinding]:
        runners: dict[str, Callable[[], list[BugFinding]]] = {
            "truncation": self._truncation,
            "subscript-range": self._subscript_range,
            "next-sentence": self._next_sentence,
            "perform-range": self._perform_range,
            "file-status": self._file_status,
            "uninitialized": self._uninitialized,
            "obsolete-verb": self._obsolete_verb,
        }
        if self.ast.procedure_division is None:
            return []
        return runners[rule]()

    # -- truncation ----------------------------------------------------------

    def _capacity(self, text: str) -> tuple[Capacity | None, str | None]:
        """``(capacity, item name)`` of an operand; (None, None) when unknown.

        A literal has a capacity but no item name.
        """
        literal = _literal_capacity(text)
        if literal is not None:
            return literal, None
        item = self._item(text)
        if item is None:
            return None, None
        return _item_capacity(item), item.name

    def _item(self, text: str) -> CobolDataItem | None:
        operand = _parse_operand(text)
        if operand is None or operand.reference_modified:
            return None
        if operand.name in _FIGURATIVE or operand.name == "FUNCTION":
            return None
        return self.data.resolve(operand)

    def _address_taken(self) -> set[str]:
        """Names whose ADDRESS OF the program takes anywhere."""
        if self._addresses is None:
            found: set[str] = set()
            for stmt in self.statements():
                for text in _statement_strings(stmt):
                    found |= {m.upper() for m in _ADDRESS_OF_RE.findall(text)}
                if isinstance(stmt, SetStatement):
                    names: list[str] = []
                    if stmt.value_is_address_of and stmt.value:
                        names.append(stmt.value)
                    if stmt.targets_are_address_of:
                        names.extend(stmt.targets)
                    for name in names:
                        operand = _parse_operand(name)
                        if operand is not None:
                            found.add(operand.name)
            self._addresses = found
        return self._addresses

    def _runtime_set_names(self) -> set[str]:
        """Names SPECIAL-NAMES hands the runtime (CRT STATUS, CURSOR, ...)."""
        names: set[str] = set()
        env = self.ast.get_division("ENVIRONMENT")
        if env is None:
            return names

        def collect(value: Any) -> None:
            if isinstance(value, str):
                names.update(w.upper() for w in re.findall(_NAME, value))
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        for section in env.sections:
            if isinstance(section, CobolSection):
                collect(section.get_metadata("special_names"))
        return names

    def _overlaid(self, item: CobolDataItem) -> bool:
        """Whether *item*'s storage is shared with another item by REDEFINES."""
        family = {n.name.upper() for n in [item, *_ancestors(item)]}
        if any(n.redefines for n in [item, *_ancestors(item)]):
            return True
        return any(
            other.redefines and other.redefines.upper() in family
            for other in self.data.items
        )

    def _constant_value(self, text: str) -> tuple[bool, Capacity | None]:
        """``(is constant, capacity of its value)`` for a MOVE sender.

        A literal is a constant; so is an item with a VALUE clause that
        nothing in the program can change. Its value's capacity is what can
        be lost, not its PICTURE's (``PIC X(8) VALUE 'COACTUP'`` holds 7
        characters). A figurative VALUE (SPACES, ZERO) loses nothing: None.
        """
        literal = _literal_capacity(text)
        if literal is not None:
            if literal.numeric:
                return True, literal
            return True, Capacity(False, chars=len(_literal_text(text).rstrip()))
        item = self._item(text)
        if item is None or not item.value_clause or self._may_be_set(item):
            return False, None
        value = _literal_capacity(item.value_clause)
        if value is None:
            return True, None
        if not value.numeric:
            value = Capacity(
                False, chars=len(_literal_text(item.value_clause).rstrip())
            )
        return True, value

    def _truncation(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.statements():
            if isinstance(stmt, MoveStatement):
                findings.extend(self._move_truncation(stmt))
            elif isinstance(stmt, (AddStatement, SubtractStatement, ComputeStatement)):
                findings.extend(self._arithmetic_truncation(stmt))
        return findings

    def _move_truncation(self, stmt: MoveStatement) -> list[BugFinding]:
        if stmt.is_corresponding or not stmt.source:
            return []
        sender, sender_name = self._capacity(stmt.source)
        if sender is None:
            return []
        findings: list[BugFinding] = []
        for target in stmt.targets:
            receiver, receiver_name = self._capacity(target)
            if receiver is None or receiver_name is None:
                continue
            if sender.numeric != receiver.numeric and not sender.numeric:
                # Alphanumeric to numeric: a category question, which
                # move-type-check answers; a digit count would be a guess.
                continue
            lost = [
                loss
                for loss in sender.losses(receiver)
                if loss in ("characters", "high-order digits")
            ]
            if not lost:
                continue
            if lost == ["high-order digits"]:
                source_item = self._item(stmt.source)
                if source_item is not None and self._overlaid(source_item):
                    # Filled byte by byte through a REDEFINES (the classic
                    # two-byte FILE STATUS decoding): its digit count says
                    # nothing about the values it can hold.
                    continue
            constant, value = self._constant_value(stmt.source)
            if constant:
                if value is None or not any(
                    loss in ("characters", "high-order digits")
                    for loss in value.losses(receiver)
                ):
                    continue  # the constant's value fits
            digits = lost == ["high-order digits"]
            what = sender_name or stmt.source.strip()
            findings.append(
                BugFinding(
                    rule="truncation",
                    kind="MOVE_LOSES_DIGITS" if digits else "MOVE_LOSES_CHARACTERS",
                    message=(
                        f"MOVE {what} ({sender.describe()}) TO {receiver_name} "
                        f"({receiver.describe()}) loses {' and '.join(lost)}"
                        + (
                            ""
                            if digits or constant
                            else " when its value is longer than the receiver"
                        )
                    ),
                    location=stmt.location,
                    symbol=receiver_name,
                    severity="warning" if digits or constant else "info",
                )
            )
        return findings

    def _arithmetic_truncation(self, stmt: Any) -> list[BugFinding]:
        if stmt.on_size_error or stmt.not_on_size_error:
            return []
        if isinstance(stmt, ComputeStatement):
            sources = self._compute_sum_operands(stmt)
            receivers = list(stmt.targets)
            verb = "COMPUTE"
        else:
            if stmt.is_corresponding:
                return []
            sources = list(stmt.source_operands or [])
            receivers = list(stmt.givings or [])
            if receivers:
                sources += list(stmt.targets)
            else:
                receivers = list(stmt.targets)
            verb = "ADD" if isinstance(stmt, AddStatement) else "SUBTRACT"
        if not sources:
            return []
        shapes = [(text, *self._capacity(text)) for text in sources]
        findings: list[BugFinding] = []
        for target in receivers:
            receiver, receiver_name = self._capacity(target)
            if receiver is None or receiver_name is None or not receiver.numeric:
                continue
            for text, capacity, name in shapes:
                # A literal operand is left out: COMPUTE X = Y - 100 and
                # ADD 500 TO a negative item can fit, so its digit count
                # proves nothing.
                if capacity is None or not capacity.numeric or name is None:
                    continue
                if name is not None and name == receiver_name:
                    continue
                if capacity.integer_digits <= receiver.integer_digits:
                    continue
                findings.append(
                    BugFinding(
                        rule="truncation",
                        kind="ARITHMETIC_LOSES_DIGITS",
                        message=(
                            f"{verb} into {receiver_name} ({receiver.describe()}) "
                            f"from {name or text.strip()} ({capacity.describe()}) "
                            "can lose high-order digits, and there is no ON SIZE "
                            "ERROR phrase"
                        ),
                        location=stmt.location,
                        symbol=receiver_name,
                    )
                )
                break
        return findings

    @staticmethod
    def _compute_sum_operands(stmt: ComputeStatement) -> list[str]:
        """The operands of a COMPUTE built only of + and -, else []."""
        expression = stmt.expression
        if not isinstance(expression, str):
            return []
        tokens = _COMPUTE_TOKEN_RE.findall(expression)
        operands: list[str] = []
        for token in tokens:
            if token in "+-()":
                continue
            if _NAME_RE.match(token) and token.upper() not in _FIGURATIVE:
                if token.upper() == "FUNCTION":
                    return []
                operands.append(token)
            elif _NUMERIC_LITERAL_RE.match(token):
                operands.append(token)
            else:
                return []  # *, /, **, a subscript, ...: not a plain sum
        return operands

    # -- subscript-range -----------------------------------------------------

    def _dimensions(self, item: CobolDataItem) -> list[int] | None:
        """OCCURS upper bounds, outermost first, or None if any is unknown."""
        dims: list[int] = []
        for node in [*reversed(_ancestors(item)), item]:
            occurs = node.occurs_clause
            if occurs is None:
                continue
            if occurs.is_unbounded or occurs.max_times is None:
                return None
            dims.append(int(occurs.max_times))
        return dims

    def _subscript_range(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        seen: set[tuple[int, int, str]] = set()
        for stmt in self.statements():
            for text in _statement_strings(stmt):
                for match in _SUBSCRIPTED_RE.finditer(text):
                    name, inner = match.group(1).upper(), match.group(2)
                    if ":" in inner:
                        continue
                    candidates = self.data.by_name.get(name, [])
                    if len(candidates) != 1:
                        continue
                    dims = self._dimensions(candidates[0])
                    if not dims:
                        continue
                    parts = [p for p in re.split(r"[\s,]+", inner.strip()) if p]
                    if len(parts) != len(dims) or not all(
                        _INTEGER_RE.match(p) for p in parts
                    ):
                        continue
                    for position, (part, bound) in enumerate(
                        zip(parts, dims, strict=True), 1
                    ):
                        value = int(part)
                        if 1 <= value <= bound:
                            continue
                        key = (stmt.location.line, stmt.location.column, name)
                        if key in seen:
                            break
                        seen.add(key)
                        where = f"subscript {position} " if len(dims) > 1 else ""
                        findings.append(
                            BugFinding(
                                rule="subscript-range",
                                kind="SUBSCRIPT_OUT_OF_RANGE",
                                message=(
                                    f"{candidates[0].name}({inner.strip()}): "
                                    f"{where}{value} is outside OCCURS 1 to {bound}"
                                ),
                                location=stmt.location,
                                symbol=candidates[0].name,
                            )
                        )
                        break
        return findings

    # -- next-sentence -------------------------------------------------------

    def _next_sentence(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.statements():
            if not isinstance(stmt, NextSentenceStatement):
                continue
            skipped = _statements_skipped_by_next_sentence(stmt)
            if skipped is None:
                continue
            findings.append(
                BugFinding(
                    rule="next-sentence",
                    kind="NEXT_SENTENCE_IN_END_IF",
                    message=(
                        "NEXT SENTENCE inside an IF closed by END-IF jumps past "
                        f"the next period, skipping {skipped} after the END-IF "
                        "(and leaving any inline PERFORM around it); use CONTINUE "
                        "to leave the IF"
                    ),
                    location=stmt.location,
                )
            )
        return findings

    # -- perform-range -------------------------------------------------------

    def _perform_range(self) -> list[BugFinding]:
        index = self.procedures
        if index is None or not index.entries:
            return []
        flow = self.flow
        order = {entry.key: position for position, entry in enumerate(index.entries)}
        declarative = {n.key for n in flow.nodes if n.is_declarative}
        findings: list[BugFinding] = []
        findings.extend(self._backwards_thru(index, order))
        ranges = self._perform_ranges(index, order)
        findings.extend(self._goto_out_of_range(index, ranges, declarative))
        findings.extend(self._falls_into_performed(index, ranges, declarative))
        return findings

    def _members(
        self, index: ProcedureIndex, order: dict[str, int], start: str, end: str
    ) -> frozenset[str]:
        """Procedure keys from *start* through *end* (a section: its paragraphs)."""
        if start not in order or end not in order:
            return frozenset()
        last = order[end]
        end_entry = index.by_key[end]
        if end_entry.procedure_type == "SECTION":
            for entry in index.entries[last + 1 :]:
                if entry.section != end_entry.key:
                    break
                last = order[entry.key]
        first = order[start]
        if last < first:
            return frozenset()
        return frozenset(e.key for e in index.entries[first : last + 1])

    def _perform_ranges(
        self, index: ProcedureIndex, order: dict[str, int]
    ) -> list[tuple[str, frozenset[str]]]:
        """``(label, members)`` of every PERFORM / SORT / MERGE range."""
        ranges: dict[tuple[str, str], frozenset[str]] = {}
        for edge in self.flow.edges:
            if edge.edge_type not in _PERFORM_EDGES:
                continue
            start = edge.target
            end = edge.thru_target or edge.target
            members = self._members(index, order, start, end)
            if members:
                label = start if end == start else f"{start} THRU {end}"
                ranges[(start, end)] = members
                ranges.setdefault((label, label), members)
        out: list[tuple[str, frozenset[str]]] = []
        seen: set[frozenset[str]] = set()
        for (start, end), members in ranges.items():
            if members in seen:
                continue
            seen.add(members)
            out.append((start if start == end else f"{start} THRU {end}", members))
        return out

    def _backwards_thru(
        self, index: ProcedureIndex, order: dict[str, int]
    ) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.statements():
            if not isinstance(stmt, PerformStatement) or not stmt.thru_paragraph:
                continue
            if not stmt.target_paragraph:
                continue
            section = enclosing_section(stmt)
            start = index.resolve(
                stmt.target_paragraph,
                statement_qualifier(stmt, "target_qualifier"),
                section,
            )
            end = index.resolve(
                stmt.thru_paragraph,
                statement_qualifier(stmt, "thru_qualifier"),
                section,
            )
            if len(start) != 1 or len(end) != 1:
                continue
            if start[0] not in order or end[0] not in order:
                continue
            if order[end[0]] >= order[start[0]]:
                continue
            findings.append(
                BugFinding(
                    rule="perform-range",
                    kind="PERFORM_THRU_BACKWARDS",
                    message=(
                        f"PERFORM {stmt.target_paragraph} THRU {stmt.thru_paragraph}: "
                        f"{stmt.thru_paragraph} comes before "
                        f"{stmt.target_paragraph} in the source, so the range never "
                        "reaches its end and control runs on past the PERFORM"
                    ),
                    location=stmt.location,
                    symbol=stmt.target_paragraph,
                )
            )
        return findings

    def _terminates(self, key: str, index: ProcedureIndex, depth: int = 0) -> bool:
        """Whether procedure *key* holds a statement that ends the run, directly
        or in a procedure it PERFORMs or GOes TO (two levels deep)."""
        entry = index.by_key.get(key)
        if entry is None:
            return False
        statements = list(walk_statements(_procedure_statements(entry.node)))
        if any(_is_run_end(s) for s in statements):
            return True
        if depth >= 2:
            return False
        section = entry.section if entry.procedure_type == "PARAGRAPH" else entry.key
        for stmt in statements:
            names: list[str] = []
            if isinstance(stmt, GoStatement):
                names = list(stmt.target_paragraphs)
            elif isinstance(stmt, PerformStatement) and stmt.target_paragraph:
                names = [stmt.target_paragraph]
            for name in names:
                for target in index.resolve(name, None, section):
                    if target != key and self._terminates(target, index, depth + 1):
                        return True
        return False

    def _goto_out_of_range(
        self,
        index: ProcedureIndex,
        ranges: list[tuple[str, frozenset[str]]],
        declarative: set[str],
    ) -> list[BugFinding]:
        findings: list[BugFinding] = []
        seen: set[tuple[int, str]] = set()
        for edge in self.flow.edges:
            if edge.edge_type not in _GOTO_EDGES:
                continue
            source, target = edge.source, edge.target
            if source in declarative or target not in index.by_key:
                continue
            holding = [(label, m) for label, m in ranges if source in m]
            if not holding or any(target in m for _label, m in holding):
                continue
            if self._terminates(target, index):
                continue
            key = (edge.location.line, target)
            if key in seen:
                continue
            seen.add(key)
            label, _members = min(holding, key=lambda r: len(r[1]))
            findings.append(
                BugFinding(
                    rule="perform-range",
                    kind="GO_TO_OUT_OF_PERFORM",
                    message=(
                        f"GO TO {target} leaves the range of PERFORM {label} "
                        f"(from {source}); the PERFORM never returns and control "
                        f"runs on from {target}"
                    ),
                    location=edge.location,
                    symbol=target,
                )
            )
        return findings

    def _falls_into_performed(
        self,
        index: ProcedureIndex,
        ranges: list[tuple[str, frozenset[str]]],
        declarative: set[str],
    ) -> list[BugFinding]:
        performed: set[str] = set()
        starts: set[str] = set()
        for label, members in ranges:
            performed |= members
            starts.add(label.split(" THRU ")[0])
        leaves = [
            e
            for e in index.entries
            if e.key not in declarative
            and (
                e.procedure_type == "PARAGRAPH"
                or not isinstance(e.node, CobolSection)
                or not e.node.paragraphs
            )
        ]
        division = self.ast.procedure_division
        paragraphs = _all_paragraphs(division) if division is not None else []
        if paragraphs and not paragraphs[0].paragraph_name and paragraphs[0].statements:
            # Statements before the first paragraph name: the main line
            # starts there, ahead of every named procedure.
            leaves.insert(
                0,
                ProcedureEntry(
                    "", "PROCEDURE DIVISION", "PARAGRAPH", None, paragraphs[0]
                ),
            )
        if not leaves:
            return []
        for position, entry in enumerate(leaves):
            if entry.key in performed or entry.section in performed:
                return []  # the main line is itself a PERFORM range here
            if not isinstance(entry.node, CobolParagraph):
                return []
            statements = list(entry.node.statements)
            if statements and self._ends(statements[-1], index, entry.section):
                return []
            if position + 1 >= len(leaves):
                return []
            following = leaves[position + 1]
            target = (
                following.key
                if following.key in starts
                else (
                    following.section
                    if following.section in starts and following.section is not None
                    else None
                )
            )
            if target is None:
                continue
            if statements and self._performs(statements[-1], following, index):
                # PERFORM X 9 TIMES, then into X once more: the author
                # placed the PERFORM right above its target on purpose.
                return []
            last = statements[-1].location if statements else entry.location
            return [
                BugFinding(
                    rule="perform-range",
                    kind="FALLS_INTO_PERFORMED",
                    message=(
                        f"{entry.name} ends without STOP RUN, GOBACK or GO TO, so "
                        f"control falls into {target}, which the program also "
                        "PERFORMs"
                    ),
                    location=last,
                    symbol=entry.name,
                )
            ]
        return []

    @staticmethod
    def _performs(stmt: Any, entry: Any, index: ProcedureIndex) -> bool:
        """Whether *stmt* is a PERFORM of procedure *entry* (or its section)."""
        if not isinstance(stmt, PerformStatement) or not stmt.target_paragraph:
            return False
        keys = index.resolve(stmt.target_paragraph, None, enclosing_section(stmt))
        return entry.key in keys or (
            entry.section is not None and entry.section in keys
        )

    def _ends(self, stmt: Any, index: ProcedureIndex, section: str | None) -> bool:
        """Whether control never passes the last statement *stmt* of a paragraph."""
        if _is_unconditional_transfer(stmt):
            return True
        if isinstance(stmt, PerformStatement) and stmt.target_paragraph:
            if stmt.inline_statements:
                return False
            if stmt.perform_type not in ("SIMPLE", "TIMES"):
                return False
            for target in index.resolve(stmt.target_paragraph, None, section):
                if self._terminates(target, index):
                    return True
        return False

    # -- file-status ---------------------------------------------------------

    def _file_status(self) -> list[BugFinding]:
        from .xref import _contained_node_ids

        if self._has_declaratives():
            return []
        inner = _contained_node_ids(self.ast)
        selects = [
            node
            for node in self.ast.traverse_depth_first()
            if isinstance(node, SelectStatement)
            and id(node) not in inner
            and node.file_name
            and node.file_status
        ]
        if not selects:
            return []
        used_files = {
            e.name.upper()
            for e in self.xref.entries
            if e.kind == "file"
            and any(r.role == "file-operation" for r in e.references)
        }
        findings: list[BugFinding] = []
        for select in selects:
            if (select.file_name or "").upper() not in used_files:
                continue
            operand = _parse_operand(select.file_status or "")
            if operand is None:
                continue
            item = self.data.resolve(operand)
            if item is None or self._status_is_read(item):
                continue
            if _section_of(item) not in _STORAGE_SECTIONS or any(
                n.is_external or n.is_global for n in [item, *_ancestors(item)]
            ):
                # LINKAGE, EXTERNAL or GLOBAL: another program reads it.
                continue
            findings.append(
                BugFinding(
                    rule="file-status",
                    kind="FILE_STATUS_NOT_CHECKED",
                    message=(
                        f"file {select.file_name} declares FILE STATUS "
                        f"{item.name}, but the program never tests it: a failed "
                        "OPEN, READ or WRITE goes unnoticed"
                    ),
                    location=select.location,
                    symbol=select.file_name,
                )
            )
        return findings

    def _has_declaratives(self) -> bool:
        division = self.ast.procedure_division
        if division is None:
            return False
        return any(
            isinstance(s, CobolSection) and s.is_declarative for s in division.sections
        )

    def _related_entries(self, item: CobolDataItem) -> list[Any]:
        """xref entries for *item*, its group, its subfields and condition
        names, and anything that REDEFINES (or is REDEFINED by) them."""
        names = {item.name.upper()}
        family = [item, *_ancestors(item), *item.get_all_children()]
        names |= {n.name.upper() for n in family}
        for node in family:
            # Level-88 condition names: IF WS-OK tests the item.
            names |= {
                str(c.name).upper()
                for c in node.children
                if isinstance(c, ConditionNameItem) and getattr(c, "name", None)
            }
        for node in family:
            if node.redefines:
                names.add(node.redefines.upper())
        for other in self.data.items:
            if other.redefines and other.redefines.upper() in names:
                names.add(other.name.upper())
                names |= {c.name.upper() for c in other.get_all_children()}
        return [e for e in self.xref.entries if e.name.upper() in names]

    def _status_is_read(self, item: CobolDataItem) -> bool:
        for entry in self._related_entries(item):
            for ref in entry.references:
                if ref.statement == "SelectStatement":
                    continue
                if ref.role != "write":
                    return True
        return False

    # -- uninitialized -------------------------------------------------------

    def _uninitialized(self) -> list[BugFinding]:
        entries: dict[tuple[str, tuple[str, ...]], Any] = {}
        for entry in self.xref.entries:
            if entry.kind == "data-item":
                key = (entry.name.upper(), tuple(a.upper() for a in entry.ancestors))
                entries[key] = entry
        findings: list[BugFinding] = []
        for item in self.data.items:
            section = _section_of(item)
            if section not in _STORAGE_SECTIONS:
                continue
            if not _is_elementary(item) or item.is_filler or item.value_clause:
                continue
            capacity = _item_capacity(item)
            if capacity is None or not capacity.numeric:
                continue
            ancestors = _ancestors(item)
            if any(a.value_clause or a.is_external for a in ancestors) or (
                item.is_external
            ):
                continue
            key = (item.name.upper(), tuple(a.name.upper() for a in ancestors))
            entry = entries.get(key)
            if entry is None:
                continue
            reads = [r for r in entry.references if r.role in _READ_ROLES]
            if not reads or self._may_be_set(item):
                continue
            first = min(reads, key=lambda r: (r.location.line, r.location.column))
            findings.append(
                BugFinding(
                    rule="uninitialized",
                    kind="NUMERIC_NEVER_SET",
                    message=(
                        f"{item.name} is read here but nothing ever stores a value in it, and it has no "
                        "VALUE clause: its content is whatever the storage held "
                        "(often spaces, a data exception in arithmetic)"
                    ),
                    location=first.location,
                    symbol=item.name,
                )
            )
        return findings

    def _may_be_set(self, item: CobolDataItem) -> bool:
        """Whether anything can store into *item*: a non-read reference to it,
        its groups or REDEFINES, or an OCCURS DEPENDING ON it implies."""
        for entry in self._related_entries(item):
            for ref in entry.references:
                if ref.role not in _READ_ROLES:
                    return True
        family = {n.name.upper() for n in [item, *_ancestors(item)]}
        if family & self._address_taken():
            return True  # SET ptr TO ADDRESS OF item: stored through a pointer
        if family & (self._runtime_set_names() | _SQLCA_NAMES):
            return True  # CRT STATUS / CURSOR, SQLCODE: set by the runtime
        return any(
            node.redefines or node.get_metadata("fd_file_name")
            for node in [item, *_ancestors(item)]
        )

    # -- obsolete-verb -------------------------------------------------------

    def _obsolete_verb(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.statements():
            if isinstance(stmt, AlterStatement):
                changes = ", ".join(
                    f"{a.get('from_paragraph')} TO {a.get('to_paragraph')}"
                    for a in stmt.alterations
                )
                findings.append(
                    BugFinding(
                        rule="obsolete-verb",
                        kind="ALTER",
                        message=(
                            f"ALTER {changes}: ALTER was removed from the COBOL "
                            "2002 standard, and the GO TO it changes no longer "
                            "says where it goes; use a flag and IF / EVALUATE"
                        ),
                        location=stmt.location,
                        symbol=(
                            stmt.alterations[0].get("from_paragraph")
                            if stmt.alterations
                            else None
                        ),
                    )
                )
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_paragraphs(division: Any) -> list[CobolParagraph]:
    """Every paragraph of a PROCEDURE DIVISION in source order, the unnamed
    one holding statements written before the first paragraph name included
    (``ProcedureIndex`` leaves it out: it is not a procedure anyone can
    name)."""
    paragraphs: list[CobolParagraph] = list(division.paragraphs)
    for section in division.sections:
        if isinstance(section, CobolSection):
            paragraphs.extend(section.paragraphs)
    unique = list({id(p): p for p in paragraphs}.values())
    return sorted(unique, key=lambda p: (p.location.line, p.location.column))


def _section_of(item: CobolDataItem) -> str | None:
    node: Any = item
    while node is not None and not isinstance(node, CobolSection):
        node = node.parent
    if node is None or not node.section_name:
        return None
    return str(node.section_name).upper()


def _statement_strings(stmt: Any) -> Iterator[str]:
    """The operand text a statement carries itself (nested statements are
    visited on their own), with quoted literals blanked out."""
    nested = {id(s) for block in _nested_lists(stmt) for s in block}

    def walk(value: Any, depth: int) -> Iterator[str]:
        if depth > 6:
            return
        if isinstance(value, str):
            yield QUOTED_LITERAL_RE.sub('""', value)
        elif isinstance(value, dict):
            for item in value.values():
                yield from walk(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if id(item) in nested:
                    continue
                yield from walk(item, depth + 1)
        elif isinstance(value, CobolStatement):
            return
        elif hasattr(value, "to_dict") and not isinstance(value, CobolStatement):
            try:
                yield from walk(value.to_dict(), depth + 1)
            except Exception:  # noqa: BLE001 - a node that cannot serialize
                return

    for name, value in vars(stmt).items():
        if name in ("parent", "children", "location", "_metadata") or name.startswith(
            "_"
        ):
            continue
        if name in NESTED_BODY_ATTRS:
            continue
        yield from walk(value, 0)


def _container(stmt: Any) -> tuple[Any, list[Any]] | None:
    """``(node, statement list)`` that directly holds *stmt*."""
    parent = getattr(stmt, "parent", None)
    if parent is None:
        return None
    if isinstance(parent, CobolParagraph):
        return parent, list(parent.statements)
    for block in _nested_lists(parent):
        if any(s is stmt for s in block):
            return parent, block
    statements = getattr(parent, "statements", None)
    if isinstance(statements, list) and any(s is stmt for s in statements):
        # An EVALUATE WHEN clause node: its EVALUATE owns the scope.
        return parent, statements
    return None


def _statements_skipped_by_next_sentence(stmt: Any) -> str | None:
    """What a NEXT SENTENCE inside END-IF skips, or None when it skips
    nothing (or when that cannot be told)."""
    node = stmt
    saw_end_if = False
    while True:
        holder = _container(node)
        if holder is None:
            return None
        parent, block = holder
        position = next((i for i, s in enumerate(block) if s is node), None)
        if position is None:
            return None
        if node is not stmt and position + 1 < len(block):
            if not saw_end_if:
                return None
            following = block[position + 1]
            return f"{following.statement_type} and the rest of the sentence"
        if isinstance(parent, CobolParagraph):
            return None
        if not isinstance(parent, IfStatement):
            return None  # EVALUATE, SEARCH, inline PERFORM, ...: not judged
        if not parent.ended_by_end_if:
            return None  # a period-terminated IF: NEXT SENTENCE is the idiom
        saw_end_if = True
        if parent.period_after_end_if:
            return None  # END-IF. -- nothing between it and the period
        node = parent


__all__ = [
    "BUG_PATTERN_DESCRIPTIONS",
    "BUG_PATTERN_RULES",
    "BugFinding",
    "BugPatternAnalyzer",
    "BugPatternReport",
    "walk_statements",
]
