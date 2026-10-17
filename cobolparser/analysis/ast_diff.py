"""
Structural (semantic) diff between two parsed COBOL programs.

A line-based ``diff`` over COBOL source answers "what lines moved", which is
almost never the question: COBOL is column-sensitive, so a reformat, a
renumbered sequence area or a re-indented Area B shifts every line without
changing a single thing the program does. This module answers the other
question -- *what changed in the program's behavior* -- by comparing two
:class:`~..models.program.CobolProgram` ASTs and reporting the differences
as a flat, sorted list of :class:`DiffChange` records.

What is compared
================

* **Program level** -- ``PROGRAM-ID``, which divisions exist, the
  ``PROCEDURE DIVISION USING`` interface.
* **Files** -- one entry per ``SELECT``/``FD`` file name: added, removed,
  and every organizational fact that changed (ORGANIZATION, ACCESS MODE,
  RECORD KEY, ALTERNATE RECORD KEYs, RELATIVE KEY, FILE STATUS, ASSIGN,
  OPTIONAL, plus the FD's own presence, record size, recording mode and
  FD-vs-SD kind).
* **Data items** -- every DATA DIVISION entry, keyed by section plus its
  qualified path (``WORKING-STORAGE:WS-TAB.WS-ENT``): added, removed,
  PICTURE / USAGE / level / VALUE / OCCURS / REDEFINES changed, plus the
  SIGN / JUSTIFIED / SYNCHRONIZED / BLANK WHEN ZERO / EXTERNAL / GLOBAL
  flags and level-88 condition names and their values -- and the *order*
  of each group's subordinate items (``data-item-moved``, with the byte
  offsets before and after): swapping two fields of a record changes every
  offset after them, the byte layout of a file, CALL interface or host
  structure.
* **Procedures** -- paragraphs and sections: added, removed, renamed,
  moved (reordered without a body change -- reported *separately* from a
  body change, so a pure reshuffle never reads as a rewrite) and
  body-changed.
* **Statements** -- inside every matched paragraph: added, removed, and
  changed, with the changes a reviewer actually looks for called out by
  their own ``kind`` rather than buried in a generic "statement changed":
  a PERFORM whose target moved, a CALL whose callee moved, a MOVE whose
  target moved, and a changed condition (IF / EVALUATE WHEN / PERFORM
  UNTIL / SEARCH WHEN).

Matching algorithm
==================

The interesting problem is deciding which node in the old program *is*
which node in the new one once things have been renamed or reordered.
Three stages, in order, each one only ever looking at what the stage
before it left over:

1. **By name, exact and case-insensitive.** COBOL names are
   case-insensitive, so ``Main-Para`` and ``MAIN-PARA`` are the same
   paragraph. This settles the overwhelming majority of pairs.
2. **By structural similarity of the body.** Every leftover paragraph
   (and section) is reduced to a *fingerprint*: the ordered sequence of
   its statements' node kinds together with their primary operands, with
   nested branch bodies flattened in and tagged by the branch they sit in
   (``IF/THEN``, ``EVALUATE/WHEN2``, ``READ/AT-END``). Two leftovers are
   scored with :class:`difflib.SequenceMatcher` over those fingerprints;
   candidate pairs are considered best-score-first (ties broken by name,
   so the result never depends on dict or set ordering) and greedily
   paired while the score is at or above ``rename_threshold``. An
   identical fingerprint under a different name is a **rename**, not an
   add plus a remove.
3. **Whatever is still unmatched** is a genuine add or a genuine remove.

Two deliberate refusals in stage 2. An empty body never rename-matches --
two paragraphs that both contain nothing are not evidence of anything, and
:class:`~difflib.SequenceMatcher` happily scores two empty sequences 1.0.
And a pair that scored *below* the threshold is reported as remove + add,
never as a speculative rename: an add+remove for a renamed paragraph is
honest and easy to read past, while a wrong rename actively misleads. The
near-miss is not thrown away either -- it goes into
:attr:`DiffReport.caveats` with its score, so a reader can see that the
diff considered the pair and declined.

Positions are compared as *relative order*, not line numbers: the matched
procedures of both programs (and the matched subordinates of each group) are run through :class:`difflib.SequenceMatcher`
and only the ones outside its matching blocks are reported as moved. So
inserting one paragraph at the top does not report every following
paragraph as moved, and a reformat that shifts every line reports nothing
at all.

Determinism
===========

The same pair of programs always produces byte-identical
:meth:`DiffReport.to_dict` output. Changes are sorted by category, then
symbol, then kind, then the remaining fields; caveats are deduplicated and
sorted; nothing iterates a set without sorting it first.

Caveats
=======

A quiet report must never be mistaken for "nothing changed". Anything this
diff could not compare exactly -- a contained program unit, a nested
statement clause the flattener does not recognise, REPORT SECTION group
clauses, level-66 RENAMES entries, ENVIRONMENT/IDENTIFICATION content
beyond what is listed above, a duplicate procedure name, a near-miss
rename -- is recorded on :attr:`DiffReport.caveats` with its reason rather
than silently dropped.

Example:
    ```python
    from cobolparser import parse_cobol
    from cobolparser.analysis.ast_diff import ProgramDiffer

    old = parse_cobol(old_source, filename="v1.cbl")
    new = parse_cobol(new_source, filename="v2.cbl")
    report = ProgramDiffer().diff(old.ast, new.ast)

    print(report.to_text())
    for change in report.changes:
        print(change.kind, change.symbol, change.detail)
    ```
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .._storage import (
    BINARY_FIXED_USAGES,
    BINARY_NATIVE_USAGES,
    DOUBLE_FLOAT_USAGES,
    PACKED_USAGES,
    SINGLE_FLOAT_USAGES,
)
from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem, PictureClause
from ..models.program import CobolParagraph, CobolProgram, CobolSection
from ..models.sql_statements import ExecSQLStatement
from ..models.statements.arithmetic import ComputeStatement
from ..models.statements.base import CobolExpression, CobolStatement
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import (
    DisplayStatement,
    InspectStatement,
    MoveStatement,
    UnstringStatement,
)
from ..models.statements.io import IOAcceptStatement, IOOpenStatement
from ..models.statements.misc import SelectStatement
from ..parsers.statements.ibm_exec_statements import ExecCicsStatement
from .program_flow.condition_text import render_condition_text
from .program_flow.statement_text import summarize_statement

#: Attributes that hold a nested list of statements on some statement node,
#: paired with the path segment used for the branch they represent. Ordered
#: (not a set) so the flattened sequence is reproducible. ``then``/``else``
#: and the EVALUATE/SEARCH WHEN arms are handled structurally instead, since
#: their conditions are part of the comparison.
_CLAUSE_ATTRS: tuple[tuple[str, str], ...] = (
    ("at_end_clause", "AT-END"),
    ("not_at_end_clause", "NOT-AT-END"),
    ("invalid_key_clause", "INVALID-KEY"),
    ("not_invalid_key_clause", "NOT-INVALID-KEY"),
    ("on_size_error", "ON-SIZE-ERROR"),
    ("not_on_size_error", "NOT-ON-SIZE-ERROR"),
    ("on_overflow", "ON-OVERFLOW"),
    ("not_on_overflow", "NOT-ON-OVERFLOW"),
    ("on_exception", "ON-EXCEPTION"),
    ("not_on_exception", "NOT-ON-EXCEPTION"),
    ("at_eop_clause", "AT-EOP"),
    ("not_at_eop_clause", "NOT-AT-EOP"),
    ("no_data_clause", "NO-DATA"),
    ("with_data_clause", "WITH-DATA"),
)

#: Scalar ``CobolDataItem`` attributes compared one-for-one, with the change
#: ``kind`` each one emits. PICTURE / OCCURS / level are handled separately
#: because they need their own rendering.
_DATA_FLAG_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("usage", "usage-changed", "USAGE"),
    ("value_clause", "value-changed", "VALUE"),
    ("redefines", "redefines-changed", "REDEFINES"),
    ("sign_clause", "sign-changed", "SIGN"),
    ("justified", "justified-changed", "JUSTIFIED"),
    ("synchronized", "synchronized-changed", "SYNCHRONIZED"),
    ("blank_when_zero", "blank-when-zero-changed", "BLANK WHEN ZERO"),
    ("is_external", "external-changed", "EXTERNAL"),
    ("is_global", "global-changed", "GLOBAL"),
)

#: ``SelectStatement`` attributes compared one-for-one for a matched file.
_SELECT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("organization", "file-organization-changed", "ORGANIZATION"),
    ("access_mode", "file-access-changed", "ACCESS MODE"),
    ("record_key", "file-key-changed", "RECORD KEY"),
    ("relative_key", "file-relative-key-changed", "RELATIVE KEY"),
    ("file_status", "file-status-changed", "FILE STATUS"),
    ("assign_to", "file-assign-changed", "ASSIGN"),
    ("is_optional", "file-optional-changed", "OPTIONAL"),
)


# ---------------------------------------------------------------------------
# Public report shapes
# ---------------------------------------------------------------------------


@dataclass
class DiffChange:
    """One difference between the two programs."""

    kind: str
    category: str  # "program" | "file" | "data" | "procedure"
    symbol: str
    detail: str
    old: str | None = None
    new: str | None = None
    old_location: SourceLocation | None = None
    new_location: SourceLocation | None = None

    @property
    def sign(self) -> str:
        """``+`` for an addition, ``-`` for a removal, ``~`` otherwise."""
        if self.kind.endswith("-added"):
            return "+"
        if self.kind.endswith("-removed"):
            return "-"
        return "~"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "category": self.category,
            "symbol": self.symbol,
            "detail": self.detail,
            "old": self.old,
            "new": self.new,
            "old_location": (
                self.old_location.to_dict() if self.old_location else None
            ),
            "new_location": (
                self.new_location.to_dict() if self.new_location else None
            ),
        }

    def _sort_key(self) -> tuple[str, ...]:
        """Total order over every field, so equal (category, symbol, kind)
        triples still sort reproducibly instead of relying on list order."""
        return (
            self.category,
            self.symbol,
            self.kind,
            self.old or "",
            self.new or "",
            self.detail,
            str(self.old_location.line if self.old_location else -1).zfill(8),
            str(self.new_location.line if self.new_location else -1).zfill(8),
        )


@dataclass
class DiffReport:
    """The full set of differences between two programs."""

    changes: list[DiffChange] = field(default_factory=list)
    old_program: str | None = None
    new_program: str | None = None
    caveats: list[str] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        return len(self.changes)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    def changes_by_category(self) -> dict[str, list[DiffChange]]:
        """Changes grouped by category, categories in sorted order."""
        grouped: dict[str, list[DiffChange]] = {}
        for change in self.changes:
            grouped.setdefault(change.category, []).append(change)
        return {key: grouped[key] for key in sorted(grouped)}

    def counts_by_kind(self) -> dict[str, int]:
        """How many changes of each ``kind``, kinds in sorted order."""
        counts: dict[str, int] = {}
        for change in self.changes:
            counts[change.kind] = counts.get(change.kind, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def to_dict(self) -> dict[str, Any]:
        by_category = {
            key: len(value) for key, value in self.changes_by_category().items()
        }
        return {
            "old_program": self.old_program,
            "new_program": self.new_program,
            "changes": [change.to_dict() for change in self.changes],
            "caveats": list(self.caveats),
            "summary": {
                "total_changes": self.change_count,
                "by_category": by_category,
                "by_kind": self.counts_by_kind(),
            },
        }

    def to_text(self) -> str:
        """A readable ``+``/``-``/``~`` summary, for CLI ``--format text``."""
        old_name = self.old_program or "(unnamed)"
        new_name = self.new_program or "(unnamed)"
        lines = [f"PROGRAM {old_name} -> {new_name}"]
        if not self.changes:
            lines.append("No structural changes.")
        else:
            plural = "" if self.change_count == 1 else "s"
            lines.append(f"{self.change_count} change{plural}")
            for category, changes in self.changes_by_category().items():
                lines.append("")
                lines.append(f"{category}:")
                for change in changes:
                    lines.append(
                        f"  {change.sign} [{change.kind}] {change.symbol}: "
                        f"{change.detail}"
                    )
        if self.caveats:
            lines.append("")
            lines.append("caveats:")
            for caveat in self.caveats:
                lines.append(f"  ! {caveat}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FlatStatement:
    """One statement of a flattened paragraph body."""

    path: str  # "" at top level, "IF/THEN", "IF/THEN/EVALUATE/WHEN1", ...
    kind: str  # statement_type, e.g. "MOVE", or a synthetic "WHEN"
    signature: tuple[Any, ...]
    text: str
    location: SourceLocation | None
    node: Any = None

    @property
    def key(self) -> tuple[Any, ...]:
        """The hashable value the sequence matcher compares on."""
        return (self.path, self.kind, self.signature)


@dataclass
class _Procedure:
    """One paragraph or section of a PROCEDURE DIVISION, in source order."""

    name: str  # uppercased
    display_name: str  # as written
    kind: str  # "paragraph" | "section"
    index: int  # ordinal within the program's procedure list
    parent: str | None  # owning section name, uppercased
    location: SourceLocation
    body: list[_FlatStatement]

    @property
    def fingerprint(self) -> list[tuple[Any, ...]]:
        return [item.key for item in self.body]


@dataclass
class _DataEntry:
    """One DATA DIVISION entry (data item or level-88 condition name)."""

    key: str  # "<SECTION>:<QUALIFIED.PATH>"
    symbol: str  # qualified path, as written
    section: str
    item: Any  # CobolDataItem | ConditionNameItem
    is_condition: bool
    location: SourceLocation
    # Keys of the subordinate data items, in source order (no level-88s).
    children: list[str] = field(default_factory=list)


class _OffsetLookup:
    """Record-relative byte offsets of data items, one layout per record."""

    def __init__(self) -> None:
        self._layouts: dict[int, dict[str, int | None]] = {}

    def offset(self, item: Any) -> int | None:
        """*item*'s byte offset in its 01/77 record, or ``None`` when the
        layout cannot say exactly (an OCCURS DEPENDING ON before it, ...)."""
        if not isinstance(item, CobolDataItem):
            return None
        path = [item.layout_name]
        root = item
        while isinstance(root.parent, CobolDataItem):
            root = root.parent
            path.append(root.layout_name)
        path[-1] = root.name
        layout = self._layouts.get(id(root))
        if layout is None:
            from ..generators.data.layout_offsets import compute_record_layout

            layout = {}
            try:
                for entry in compute_record_layout(root):
                    offset = None if entry.offset_ambiguous else entry.byte_offset
                    layout.setdefault(entry.qualified_name, offset)
            except Exception:  # noqa: BLE001 - offsets are a detail, never fatal
                layout = {}
            self._layouts[id(root)] = layout
        return layout.get(".".join(reversed(path)))


@dataclass
class _FileEntry:
    """One file: its SELECT (if any) joined to its FD/SD (if any)."""

    name: str
    select: SelectStatement | None = None
    fd_clauses: dict[str, Any] | None = None
    fd_record_type: str | None = None
    location: SourceLocation | None = None


# ---------------------------------------------------------------------------
# Flattening / fingerprinting
# ---------------------------------------------------------------------------


def _text_of(value: Any) -> str:
    """Render a condition/subject/selector operand as comparable text."""
    if value is None:
        return ""
    if isinstance(value, CobolExpression):
        return render_condition_text(value)
    if isinstance(value, dict):
        return ", ".join(f"{key}={value[key]!r}" for key in sorted(value))
    return str(value)


def _selector_text(selector: Any) -> str:
    """Compact text for one EVALUATE ``WHEN`` selector."""
    if not isinstance(selector, dict):
        return _text_of(selector)
    sel_type = selector.get("type", "")
    if sel_type == "Range":
        return f"RANGE:{selector.get('start', '')}..{selector.get('end', '')}"
    if sel_type == "Condition":
        return f"COND:{selector.get('text', '')}"
    value = str(selector.get("value", ""))
    # The lexer strips quotes, so WHEN SPACES and WHEN 'SPACES' share a
    # value; the parser's markers are what tell them apart (#313).
    if selector.get("figurative"):
        return f"FIG:{value}"
    if selector.get("identifier"):
        return f"ID:{value}"
    if selector.get("quoted"):
        return f"{sel_type}:'{value.replace(chr(39), chr(39) * 2)}'"
    return f"{sel_type}:{value}"


def _statement_signature(stmt: Any) -> tuple[Any, ...]:
    """The comparable identity of one statement, ignoring its nested bodies.

    Nested bodies are compared separately (they are flattened out into
    their own entries), so a change inside an IF is reported as a change to
    the statement inside it, not as "the whole IF changed".
    """
    kind = _statement_kind(stmt)

    if isinstance(stmt, MoveStatement):
        return (
            kind,
            stmt.source or "",
            tuple(stmt.targets),
            bool(stmt.is_corresponding),
        )
    if isinstance(stmt, PerformStatement):
        return (
            kind,
            stmt.target_paragraph or "",
            stmt.thru_paragraph or "",
            stmt.perform_type,
            str(stmt.times_count) if stmt.times_count is not None else "",
            _text_of(stmt.until_condition),
            _text_of(stmt.varying_clause),
            tuple(_text_of(clause) for clause in stmt.after_clauses),
            stmt.test_timing,
        )
    if isinstance(stmt, CallStatement):
        return (
            kind,
            stmt.called_program or "",
            # CALL 'WS-A' (static, the literal names the program) vs
            # CALL WS-A (dynamic, the data item's value names it).
            bool(stmt.is_dynamic),
            tuple(
                (param.name, getattr(param, "passing_mode", ""))
                for param in stmt.using_parameters
            ),
            stmt.returning_parameter or "",
            stmt.giving_parameter or "",
        )
    if isinstance(stmt, GoStatement):
        targets = stmt.target_paragraphs or (
            [stmt.target_paragraph] if stmt.target_paragraph else []
        )
        return (kind, tuple(targets), stmt.depending_on_variable or "")
    if isinstance(stmt, IfStatement):
        return (kind, _text_of(stmt.condition))
    if isinstance(stmt, EvaluateStatement):
        return (kind, tuple(_text_of(subject) for subject in stmt.subjects))
    if isinstance(stmt, SearchStatement):
        return (
            kind,
            stmt.table_name or "",
            stmt.varying_variable or "",
            # SEARCH vs SEARCH ALL (serial vs binary search) lives only in
            # the metadata; it changes which element is found.
            bool(stmt.get_metadata("is_search_all")),
        )
    if isinstance(stmt, IOOpenStatement):
        return (
            kind,
            stmt.open_mode or "",
            tuple(stmt.file_names),
            tuple(sorted(stmt.file_modes.items())),
        )
    if isinstance(stmt, ExecSQLStatement):
        return (kind, " ".join((stmt.sql_text or "").split()).upper())
    if isinstance(stmt, ExecCicsStatement):
        return (
            kind,
            " ".join((stmt.cics_text or "").split()).upper(),
            tuple(sorted((k, str(v)) for k, v in (stmt.options or {}).items())),
        )
    if isinstance(stmt, ComputeStatement):
        return (
            kind,
            tuple(stmt.targets),
            " ".join(_text_of(stmt.expression).split()),
            # Which target is rounded, and how: ``COMPUTE B ROUNDED C`` and
            # ``COMPUTE B C ROUNDED`` store different values (#517).
            tuple(stmt.rounding_of(target) for target in stmt.targets),
        )
    if isinstance(stmt, InspectStatement):
        return (
            kind,
            stmt.target or "",
            stmt.inspect_type or "",
            _json_key(stmt.tallying_clauses),
            _json_key(stmt.replacing_clauses),
            stmt.converting_from or "",
            stmt.converting_to or "",
            stmt.converting_before or "",
            stmt.converting_after or "",
        )
    if isinstance(stmt, UnstringStatement):
        return (
            kind,
            stmt.source_operand or "",
            tuple(stmt.delimiters),
            # DELIMITED BY ALL ',' treats a run of delimiters as one.
            tuple(getattr(stmt, "delimiter_all", []) or []),
            _json_key(stmt.into_targets),
            stmt.pointer_variable or "",
            stmt.tallying_variable or "",
        )
    if isinstance(stmt, IOAcceptStatement):
        return (
            kind,
            stmt.target or "",
            stmt.from_source or "",
            stmt.environment_name or "",
        )
    if isinstance(stmt, DisplayStatement):
        return (
            kind,
            tuple(stmt.display_items),
            stmt.output_device or "",
            bool(stmt.with_no_advancing),
        )
    # No dedicated branch: compare on the operands *and* the rendered text,
    # so a statement model that keeps its semantics off ``operands``
    # (COMPUTE's expression, INSPECT's clauses, OPEN's mode, an EXEC SQL
    # block's text, ...) still reports an edit rather than reading as
    # unchanged. The text is a rendering, so this can over-report a
    # cosmetic difference; it can no longer under-report a real one.
    # The rendered text is a truncated summary that omits most clauses
    # (STRING's INTO target, READ's INTO/KEY, WRITE's FROM, ...), so the
    # statement's own serialized fields are compared too.
    return (
        kind,
        tuple(str(operand) for operand in getattr(stmt, "operands", [])),
        _statement_text(stmt),
        _clause_key(stmt),
    )


def _clause_key(stmt: Any) -> str:
    """The statement's ``to_dict()`` minus locations and nested statements.

    Nested bodies (``AT END``, ``ON SIZE ERROR``, ...) are flattened and
    compared on their own, so they are dropped here rather than reporting
    the enclosing statement as changed too.
    """
    try:
        data = stmt.to_dict()
    except Exception:  # noqa: BLE001 - a rendering, never a failure
        return ""
    return _json_key(_strip_positions(data))


def _strip_positions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_positions(item)
            for key, item in value.items()
            if key != "location"
        }
    if isinstance(value, list):
        return [
            _strip_positions(item)
            for item in value
            if not (
                isinstance(item, dict)
                and item.get("node_type") in _STATEMENT_NODE_TYPES
            )
        ]
    return value


#: ``to_dict()`` ``node_type`` values of statement nodes (EXEC CICS / IMS
#: keep their own).
_STATEMENT_NODE_TYPES = frozenset({"Statement", "EXEC_CICS", "EXEC_IMS"})


def _json_key(value: Any) -> str:
    """A stable, comparable rendering of a clause list of plain dicts."""
    return json.dumps(value, sort_keys=True, default=str)


def _statement_kind(stmt: Any) -> str:
    return str(getattr(stmt, "statement_type", None) or type(stmt).__name__)


def _statement_text(stmt: Any) -> str:
    """A compact one-line rendering of *stmt* for the human ``detail`` text.

    Shares :func:`~.program_flow.statement_text.summarize_statement` with the
    flowchart renderer, plus the loop guard of an inline PERFORM -- which
    that renderer collapses to "PERFORM (inline)", leaving both sides of a
    changed-loop-condition report reading identically. The comparison
    itself is structural (see :func:`_statement_signature`); this text is
    only ever displayed.
    """
    text = summarize_statement(stmt)
    if isinstance(stmt, PerformStatement) and stmt.until_condition is not None:
        condition = _text_of(stmt.until_condition)
        if condition and condition not in text:
            text = f"{text} UNTIL {condition}"
    elif (
        isinstance(stmt, CallStatement)
        and stmt.called_program
        and not stmt.is_dynamic
        and text.startswith(f"CALL {stmt.called_program}")
    ):
        # The flowchart renders both CALL 'X' and CALL X as "CALL X"; a
        # static -> dynamic change would then read identically on both sides.
        text = (
            f"CALL '{stmt.called_program}'" + text[len(f"CALL {stmt.called_program}") :]
        )
    elif isinstance(stmt, UnstringStatement) and text == "UNSTRING":
        # The flowchart collapses UNSTRING to its verb.
        all_flags = list(stmt.delimiter_all) + [False] * len(stmt.delimiters)
        delimiters = " OR ".join(
            f"ALL {delimiter}" if is_all else delimiter
            for delimiter, is_all in zip(stmt.delimiters, all_flags, strict=False)
        )
        targets = " ".join(
            str(target.get("target", "")) for target in stmt.into_targets
        )
        parts = ["UNSTRING", stmt.source_operand or ""]
        if delimiters:
            parts.append(f"DELIMITED BY {delimiters}")
        if targets:
            parts.append(f"INTO {targets}")
        text = " ".join(part for part in parts if part)
    return text


def _join_path(prefix: str, segment: str) -> str:
    return f"{prefix}/{segment}" if prefix else segment


class _Flattener:
    """Flattens a paragraph body into a comparable linear sequence.

    Branch bodies are inlined behind a path tag (``IF/THEN``,
    ``EVALUATE/WHEN2``, ``READ/AT-END``) so a statement in one arm never
    silently matches a statement in another, while the sequence as a whole
    stays a flat list the sequence matcher can align.

    Every statement it walks is recorded, and afterwards any statement
    hanging off a node it visited that it did *not* itself reach is
    reported as a caveat -- an unrecognised nesting shape must be visible,
    not quietly excluded from the comparison.
    """

    def __init__(self) -> None:
        self.caveats: list[str] = []
        self._visited: set[int] = set()
        self._roots: list[Any] = []

    def flatten(self, statements: list[Any]) -> list[_FlatStatement]:
        out: list[_FlatStatement] = []
        for stmt in statements:
            self._roots.append(stmt)
            self._walk(stmt, "", out)
        return out

    def check_unvisited(self) -> None:
        """Record a caveat for every nested statement never walked."""
        seen: set[str] = set()
        for root in self._roots:
            for node in self._descendant_statements(root):
                if id(node) in self._visited:
                    continue
                line = node.location.line if node.location else "?"
                note = (
                    f"statement '{_statement_kind(node)}' nested inside "
                    f"'{_statement_kind(root)}' at line {line} is not "
                    "decomposed by this diff; its content is not compared"
                )
                if note not in seen:
                    seen.add(note)
                    self.caveats.append(note)

    @staticmethod
    def _descendant_statements(node: Any) -> list[Any]:
        found: list[Any] = []
        stack: list[Any] = list(getattr(node, "children", []) or [])
        visited: set[int] = set()
        while stack:
            current = stack.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            if isinstance(current, CobolStatement):
                found.append(current)
            stack.extend(getattr(current, "children", []) or [])
        return found

    def _emit(
        self,
        out: list[_FlatStatement],
        path: str,
        kind: str,
        signature: tuple[Any, ...],
        text: str,
        node: Any,
    ) -> None:
        out.append(
            _FlatStatement(
                path=path,
                kind=kind,
                signature=signature,
                text=text,
                location=getattr(node, "location", None),
                node=node,
            )
        )

    def _walk(self, stmt: Any, path: str, out: list[_FlatStatement]) -> None:
        self._visited.add(id(stmt))
        self._emit(
            out,
            path,
            _statement_kind(stmt),
            _statement_signature(stmt),
            _statement_text(stmt),
            stmt,
        )

        if isinstance(stmt, IfStatement):
            self._walk_all(stmt.then_statements, _join_path(path, "IF/THEN"), out)
            self._walk_all(stmt.else_statements, _join_path(path, "IF/ELSE"), out)
        elif isinstance(stmt, EvaluateStatement):
            self._walk_evaluate(stmt, path, out)
        elif isinstance(stmt, SearchStatement):
            self._walk_search(stmt, path, out)

        if isinstance(stmt, PerformStatement) and stmt.inline_statements:
            self._walk_all(
                stmt.inline_statements, _join_path(path, "PERFORM/BODY"), out
            )

        for attr, segment in _CLAUSE_ATTRS:
            nested = getattr(stmt, attr, None)
            if nested:
                self._walk_all(nested, _join_path(path, segment), out)

    def _walk_all(
        self, statements: list[Any], path: str, out: list[_FlatStatement]
    ) -> None:
        for stmt in statements or []:
            self._walk(stmt, path, out)

    def _walk_evaluate(
        self, stmt: EvaluateStatement, path: str, out: list[_FlatStatement]
    ) -> None:
        for position, clause in enumerate(stmt.when_clauses, start=1):
            selectors = tuple(_selector_text(selector) for selector in clause.selectors)
            arm_path = _join_path(path, f"EVALUATE/WHEN{position}")
            self._visited.add(id(clause))
            self._emit(
                out,
                arm_path,
                "WHEN",
                ("WHEN", selectors),
                f"WHEN {', '.join(selectors)}" if selectors else "WHEN",
                clause,
            )
            self._walk_all(clause.statements, arm_path, out)
        if stmt.default_when is not None:
            self._visited.add(id(stmt.default_when))
            self._walk_all(
                stmt.default_when.statements,
                _join_path(path, "EVALUATE/WHEN-OTHER"),
                out,
            )

    def _walk_search(
        self, stmt: SearchStatement, path: str, out: list[_FlatStatement]
    ) -> None:
        for position, clause in enumerate(stmt.when_clauses, start=1):
            condition = _text_of(clause.get("condition"))
            arm_path = _join_path(path, f"SEARCH/WHEN{position}")
            self._emit(
                out,
                arm_path,
                "WHEN",
                ("WHEN", (condition,)),
                f"WHEN {condition}",
                stmt,
            )
            self._walk_all(clause.get("statements") or [], arm_path, out)


def _flatten_body(statements: list[Any], caveats: list[str]) -> list[_FlatStatement]:
    flattener = _Flattener()
    flat = flattener.flatten(statements)
    flattener.check_unvisited()
    caveats.extend(flattener.caveats)
    return flat


# ---------------------------------------------------------------------------
# The differ
# ---------------------------------------------------------------------------


class ProgramDiffer:
    """Computes a structural diff between two parsed COBOL programs.

    Args:
        rename_threshold: How similar two leftover bodies must be, on a
            0.0-1.0 :class:`difflib.SequenceMatcher` ratio over their
            statement fingerprints, before an unmatched pair is reported
            as a rename instead of a removal plus an addition. Defaults to
            ``0.8``. Raising it to ``1.0`` accepts only byte-identical
            bodies as renames; lowering it below ~0.5 starts inventing
            renames between paragraphs that merely share a shape.
    """

    def __init__(self, *, rename_threshold: float = 0.8) -> None:
        self.rename_threshold = rename_threshold

    # -- entry point -------------------------------------------------------

    def diff(self, old: CobolProgram, new: CobolProgram) -> DiffReport:
        """Diff *old* against *new*, returning every difference found."""
        changes: list[DiffChange] = []
        caveats: list[str] = []

        self._note_scope_caveats(old, "old", caveats)
        self._note_scope_caveats(new, "new", caveats)

        self._diff_program(old, new, changes)
        self._diff_files(old, new, changes, caveats)
        self._diff_data(old, new, changes, caveats)
        self._diff_procedures(old, new, changes, caveats)

        changes.sort(key=lambda change: change._sort_key())
        return DiffReport(
            changes=changes,
            old_program=old.program_name or None,
            new_program=new.program_name or None,
            caveats=sorted(set(caveats)),
        )

    # -- caveats about what is out of scope --------------------------------

    @staticmethod
    def _note_scope_caveats(
        program: CobolProgram, side: str, caveats: list[str]
    ) -> None:
        if program.contained_programs:
            count = len(program.contained_programs)
            caveats.append(
                f"the {side} program contains {count} further program "
                "unit(s); only the outermost unit is compared -- diff each "
                "contained unit separately"
            )
        if program.identification_division is not None:
            caveats.append(
                "IDENTIFICATION DIVISION content other than PROGRAM-ID "
                "(AUTHOR, DATE-WRITTEN, remarks) is not compared"
            )
        if program.environment_division is not None:
            caveats.append(
                "ENVIRONMENT DIVISION content other than FILE-CONTROL SELECT "
                "entries (CONFIGURATION SECTION, SPECIAL-NAMES, I-O-CONTROL) "
                "is not compared"
            )

    # -- program level -----------------------------------------------------

    def _diff_program(
        self, old: CobolProgram, new: CobolProgram, changes: list[DiffChange]
    ) -> None:
        old_id = old.program_name or ""
        new_id = new.program_name or ""
        if old_id.upper() != new_id.upper():
            changes.append(
                DiffChange(
                    kind="program-id-changed",
                    category="program",
                    symbol="PROGRAM-ID",
                    detail=f"PROGRAM-ID changed from {old_id or '(none)'} to "
                    f"{new_id or '(none)'}",
                    old=old_id or None,
                    new=new_id or None,
                    old_location=old.location,
                    new_location=new.location,
                )
            )

        old_divisions = {division.division_name for division in old.divisions}
        new_divisions = {division.division_name for division in new.divisions}
        for name in sorted(new_divisions - old_divisions):
            division = new.get_division(name)
            changes.append(
                DiffChange(
                    kind="division-added",
                    category="program",
                    symbol=f"{name} DIVISION",
                    detail=f"{name} DIVISION added",
                    new=name,
                    new_location=division.location if division else None,
                )
            )
        for name in sorted(old_divisions - new_divisions):
            division = old.get_division(name)
            changes.append(
                DiffChange(
                    kind="division-removed",
                    category="program",
                    symbol=f"{name} DIVISION",
                    detail=f"{name} DIVISION removed",
                    old=name,
                    old_location=division.location if division else None,
                )
            )

        old_using = self._procedure_using(old)
        new_using = self._procedure_using(new)
        if old_using != new_using:
            changes.append(
                DiffChange(
                    kind="procedure-using-changed",
                    category="program",
                    symbol="PROCEDURE DIVISION USING",
                    detail="PROCEDURE DIVISION USING changed from "
                    f"[{', '.join(old_using) or 'none'}] to "
                    f"[{', '.join(new_using) or 'none'}]",
                    old=", ".join(old_using) or None,
                    new=", ".join(new_using) or None,
                )
            )

    @staticmethod
    def _procedure_using(program: CobolProgram) -> list[str]:
        division = program.procedure_division
        if division is None:
            return []
        params = division.get_metadata("using_parameters") or []
        return [str(param).upper() for param in params]

    # -- files -------------------------------------------------------------

    def _diff_files(
        self,
        old: CobolProgram,
        new: CobolProgram,
        changes: list[DiffChange],
        caveats: list[str],
    ) -> None:
        old_files = self._collect_files(old, "old", caveats)
        new_files = self._collect_files(new, "new", caveats)

        for name in sorted(set(new_files) - set(old_files)):
            entry = new_files[name]
            changes.append(
                DiffChange(
                    kind="file-added",
                    category="file",
                    symbol=name,
                    detail=f"file {name} added",
                    new=name,
                    new_location=entry.location,
                )
            )
        for name in sorted(set(old_files) - set(new_files)):
            entry = old_files[name]
            changes.append(
                DiffChange(
                    kind="file-removed",
                    category="file",
                    symbol=name,
                    detail=f"file {name} removed",
                    old=name,
                    old_location=entry.location,
                )
            )

        for name in sorted(set(old_files) & set(new_files)):
            self._diff_file_entry(old_files[name], new_files[name], changes)

    def _diff_file_entry(
        self, old: _FileEntry, new: _FileEntry, changes: list[DiffChange]
    ) -> None:
        name = old.name

        def record(kind: str, label: str, old_value: Any, new_value: Any) -> None:
            changes.append(
                DiffChange(
                    kind=kind,
                    category="file",
                    symbol=name,
                    detail=f"{name} {label} changed from "
                    f"{_render_value(old_value)} to {_render_value(new_value)}",
                    old=_optional_text(old_value),
                    new=_optional_text(new_value),
                    old_location=old.location,
                    new_location=new.location,
                )
            )

        if old.select is not None and new.select is not None:
            for attr, kind, label in _SELECT_FIELDS:
                old_value = getattr(old.select, attr)
                new_value = getattr(new.select, attr)
                if _normalize(old_value) != _normalize(new_value):
                    record(kind, label, old_value, new_value)
            old_alt = _alternate_key_text(old.select)
            new_alt = _alternate_key_text(new.select)
            if old_alt != new_alt:
                record(
                    "file-alternate-keys-changed",
                    "ALTERNATE RECORD KEY",
                    old_alt,
                    new_alt,
                )
        elif old.select is None and new.select is not None:
            record("file-select-added", "SELECT entry", None, new.select.file_name)
        elif old.select is not None and new.select is None:
            record("file-select-removed", "SELECT entry", old.select.file_name, None)

        if old.fd_clauses is None and new.fd_clauses is not None:
            changes.append(
                DiffChange(
                    kind="fd-added",
                    category="file",
                    symbol=name,
                    detail=f"{name} gained an FD/SD file description",
                    new=new.fd_record_type,
                    new_location=new.location,
                )
            )
        elif old.fd_clauses is not None and new.fd_clauses is None:
            changes.append(
                DiffChange(
                    kind="fd-removed",
                    category="file",
                    symbol=name,
                    detail=f"{name} lost its FD/SD file description",
                    old=old.fd_record_type,
                    old_location=old.location,
                )
            )
        elif old.fd_clauses is not None and new.fd_clauses is not None:
            if old.fd_record_type != new.fd_record_type:
                record(
                    "fd-type-changed",
                    "file description kind",
                    old.fd_record_type,
                    new.fd_record_type,
                )
            old_record = _render_value(old.fd_clauses.get("record"))
            new_record = _render_value(new.fd_clauses.get("record"))
            if old_record != new_record:
                record("fd-record-changed", "RECORD clause", old_record, new_record)
            old_mode = old.fd_clauses.get("recording_mode")
            new_mode = new.fd_clauses.get("recording_mode")
            if _normalize(old_mode) != _normalize(new_mode):
                record(
                    "fd-recording-mode-changed", "RECORDING MODE", old_mode, new_mode
                )

    @staticmethod
    def _collect_files(
        program: CobolProgram, side: str, caveats: list[str]
    ) -> dict[str, _FileEntry]:
        entries: dict[str, _FileEntry] = {}

        environment = program.environment_division
        if environment is not None:
            for node in environment.find_all_by_type("SelectStatement"):
                if not isinstance(node, SelectStatement) or not node.file_name:
                    continue
                name = node.file_name.upper()
                if name in entries and entries[name].select is not None:
                    caveats.append(
                        f"the {side} program declares SELECT {name} more than "
                        "once; only the first is compared"
                    )
                    continue
                entries.setdefault(name, _FileEntry(name=name))
                entries[name].select = node
                if entries[name].location is None:
                    entries[name].location = node.location

        data = program.data_division
        if data is not None:
            file_section = data._sections.get("FILE")
            if file_section is not None:
                for record in file_section.data_items:
                    fd_name = record.get_metadata("fd_file_name")
                    if not fd_name:
                        continue
                    name = str(fd_name).upper()
                    entry = entries.setdefault(name, _FileEntry(name=name))
                    if entry.fd_clauses is not None:
                        continue
                    entry.fd_clauses = record.get_metadata("fd_clauses") or {}
                    entry.fd_record_type = record.get_metadata("fd_record_type") or "FD"
                    if entry.location is None:
                        entry.location = record.location

        return entries

    # -- data items --------------------------------------------------------

    def _diff_data(
        self,
        old: CobolProgram,
        new: CobolProgram,
        changes: list[DiffChange],
        caveats: list[str],
    ) -> None:
        old_sections = self._data_section_names(old)
        new_sections = self._data_section_names(new)
        for name in sorted(set(new_sections) - set(old_sections)):
            changes.append(
                DiffChange(
                    kind="data-section-added",
                    category="data",
                    symbol=f"{name} SECTION",
                    detail=f"{name} SECTION added to the DATA DIVISION",
                    new=name,
                )
            )
        for name in sorted(set(old_sections) - set(new_sections)):
            changes.append(
                DiffChange(
                    kind="data-section-removed",
                    category="data",
                    symbol=f"{name} SECTION",
                    detail=f"{name} SECTION removed from the DATA DIVISION",
                    old=name,
                )
            )

        old_entries = self._collect_data(old, "old", caveats)
        new_entries = self._collect_data(new, "new", caveats)

        for key in sorted(set(new_entries) - set(old_entries)):
            entry = new_entries[key]
            kind = "condition-name-added" if entry.is_condition else "data-item-added"
            label = "level-88 condition name" if entry.is_condition else "data item"
            changes.append(
                DiffChange(
                    kind=kind,
                    category="data",
                    symbol=entry.symbol,
                    detail=f"{label} {entry.symbol} added to "
                    f"{entry.section} SECTION",
                    new=entry.symbol,
                    new_location=entry.location,
                )
            )
        for key in sorted(set(old_entries) - set(new_entries)):
            entry = old_entries[key]
            kind = (
                "condition-name-removed" if entry.is_condition else "data-item-removed"
            )
            label = "level-88 condition name" if entry.is_condition else "data item"
            changes.append(
                DiffChange(
                    kind=kind,
                    category="data",
                    symbol=entry.symbol,
                    detail=f"{label} {entry.symbol} removed from "
                    f"{entry.section} SECTION",
                    old=entry.symbol,
                    old_location=entry.location,
                )
            )

        for key in sorted(set(old_entries) & set(new_entries)):
            self._diff_data_entry(old_entries[key], new_entries[key], changes)
        self._report_data_moves(old_entries, new_entries, changes)

    @staticmethod
    def _report_data_moves(
        old_entries: dict[str, _DataEntry],
        new_entries: dict[str, _DataEntry],
        changes: list[DiffChange],
    ) -> None:
        """Report the subordinate items whose order within their group
        changed (#545).

        Like ``_report_moves`` for procedures: each group's matched
        subordinates are run through :class:`difflib.SequenceMatcher`, and
        only the ones outside its matching blocks moved -- inserting a field
        does not report every later field. The byte offsets before and after
        are in the detail, since they are what makes a reorder break a file
        or interface.
        """
        offsets = _OffsetLookup()
        for key in sorted(set(old_entries) & set(new_entries)):
            old_group, new_group = old_entries[key], new_entries[key]
            if old_group.is_condition or new_group.is_condition:
                continue
            old_order = [k for k in old_group.children if k in new_entries]
            new_order = [k for k in new_group.children if k in old_entries]
            if old_order == new_order:
                continue
            matcher = SequenceMatcher(None, old_order, new_order, autojunk=False)
            stable = {
                old_order[block.a + offset]
                for block in matcher.get_matching_blocks()
                for offset in range(block.size)
            }
            for child_key in new_order:
                if child_key in stable:
                    continue
                old_child, new_child = old_entries[child_key], new_entries[child_key]
                old_where = f"position {old_order.index(child_key) + 1}"
                new_where = f"position {new_order.index(child_key) + 1}"
                detail = (
                    f"data item {new_child.symbol} moved from {old_where} to "
                    f"{new_where} in {new_group.symbol}"
                )
                old_offset = offsets.offset(old_child.item)
                new_offset = offsets.offset(new_child.item)
                if old_offset is not None and new_offset is not None:
                    detail += f" (byte offset {old_offset} -> {new_offset})"
                    old_where += f", offset {old_offset}"
                    new_where += f", offset {new_offset}"
                changes.append(
                    DiffChange(
                        kind="data-item-moved",
                        category="data",
                        symbol=new_child.symbol,
                        detail=detail,
                        old=old_where,
                        new=new_where,
                        old_location=old_child.location,
                        new_location=new_child.location,
                    )
                )

    def _diff_data_entry(
        self, old: _DataEntry, new: _DataEntry, changes: list[DiffChange]
    ) -> None:
        symbol = new.symbol

        def record(kind: str, label: str, old_value: Any, new_value: Any) -> None:
            changes.append(
                DiffChange(
                    kind=kind,
                    category="data",
                    symbol=symbol,
                    detail=f"{symbol} {label} changed from "
                    f"{_render_value(old_value)} to {_render_value(new_value)}",
                    old=_optional_text(old_value),
                    new=_optional_text(new_value),
                    old_location=old.location,
                    new_location=new.location,
                )
            )

        if old.is_condition or new.is_condition:
            old_values = ", ".join(getattr(old.item, "values", []) or [])
            new_values = ", ".join(getattr(new.item, "values", []) or [])
            if old_values != new_values:
                record("condition-value-changed", "VALUE", old_values, new_values)
            return

        old_item: CobolDataItem = old.item
        new_item: CobolDataItem = new.item

        if old_item.level != new_item.level:
            record("level-changed", "level number", old_item.level, new_item.level)

        old_picture = _picture_text(old_item)
        new_picture = _picture_text(new_item)
        # `X(2)` and `XX` are one PICTURE: compare the character positions,
        # report the strings as coded.
        if _picture_positions(old_picture) != _picture_positions(new_picture):
            record("picture-changed", "PICTURE", old_picture, new_picture)

        for attr, kind, label in _DATA_FLAG_FIELDS:
            old_value = getattr(old_item, attr, None)
            new_value = getattr(new_item, attr, None)
            if attr == "usage":
                # IBM synonyms (`COMP-3` / `COMPUTATIONAL-3` / `PACKED-DECIMAL`)
                # are one storage format, not a change.
                if _canonical_usage(old_value) == _canonical_usage(new_value):
                    continue
            elif _normalize(old_value) == _normalize(new_value):
                continue
            record(kind, label, old_value, new_value)

        old_occurs = _occurs_text(old_item)
        new_occurs = _occurs_text(new_item)
        if old_occurs != new_occurs:
            record("occurs-changed", "OCCURS", old_occurs, new_occurs)

    @staticmethod
    def _data_section_names(program: CobolProgram) -> list[str]:
        division = program.data_division
        if division is None:
            return []
        return sorted(division._sections)

    def _collect_data(
        self, program: CobolProgram, side: str, caveats: list[str]
    ) -> dict[str, _DataEntry]:
        entries: dict[str, _DataEntry] = {}
        division = program.data_division
        if division is None:
            return entries

        for section_name, section in division._sections.items():
            if any(
                getattr(child, "node_type", None) == "RenamesItem"
                for child in section.children
            ):
                caveats.append(
                    f"the {side} program's {section_name} SECTION has level-66 "
                    "RENAMES entries, which this diff does not compare"
                )
            for item in section.data_items:
                self._collect_data_item(item, section_name, "", entries, side, caveats)
        return entries

    def _collect_data_item(
        self,
        item: CobolDataItem,
        section: str,
        prefix: str,
        entries: dict[str, _DataEntry],
        side: str,
        caveats: list[str],
    ) -> str:
        if item.get_metadata("report_clauses") or item.get_metadata("rd_clauses"):
            caveats.append(
                f"the {side} program has REPORT SECTION group clauses "
                "(TYPE/LINE/COLUMN/SOURCE/SUM), which this diff does not compare"
            )

        name = _data_name(item)
        path = f"{prefix}.{name}" if prefix else name
        base = f"{section}:{path.upper()}"
        key = self._unique_key(base, entries, side, caveats)
        entry = entries[key] = _DataEntry(
            key=key,
            symbol=_disambiguated(path, base, key),
            section=section,
            item=item,
            is_condition=False,
            location=item.location,
        )

        for child in item.children:
            if isinstance(child, CobolDataItem):
                entry.children.append(
                    self._collect_data_item(
                        child, section, path, entries, side, caveats
                    )
                )
            elif isinstance(child, ConditionNameItem):
                child_path = f"{path}.{child.name}"
                child_base = f"{section}:{child_path.upper()}"
                child_key = self._unique_key(child_base, entries, side, caveats)
                entries[child_key] = _DataEntry(
                    key=child_key,
                    symbol=_disambiguated(child_path, child_base, child_key),
                    section=section,
                    item=child,
                    is_condition=True,
                    location=child.location,
                )
        return key

    @staticmethod
    def _unique_key(
        key: str, entries: dict[str, _DataEntry], side: str, caveats: list[str]
    ) -> str:
        """Disambiguate a repeated path (several FILLERs under one group).

        A FILLER has no name to match on, so repeated ones are keyed
        positionally -- which means inserting a FILLER shifts the ones after
        it. That is honest (they *are* different slots) but worth saying.
        """
        if key not in entries:
            return key
        if key.rsplit(".", 1)[-1].startswith("FILLER"):
            caveats.append(
                f"the {side} program has several FILLER entries under the same "
                "group; they are matched by position, so inserting one reports "
                "the following FILLERs as changed"
            )
        position = 2
        while f"{key}#{position}" in entries:
            position += 1
        return f"{key}#{position}"

    # -- procedures --------------------------------------------------------

    def _diff_procedures(
        self,
        old: CobolProgram,
        new: CobolProgram,
        changes: list[DiffChange],
        caveats: list[str],
    ) -> None:
        old_procs = self._collect_procedures(old, "old", caveats)
        new_procs = self._collect_procedures(new, "new", caveats)

        pairs, unmatched_old, unmatched_new = self._match_procedures(
            old_procs, new_procs, caveats
        )

        for old_proc, new_proc, matched_by in pairs:
            if matched_by == "fingerprint":
                changes.append(
                    DiffChange(
                        kind=f"{new_proc.kind}-renamed",
                        category="procedure",
                        symbol=new_proc.display_name,
                        detail=f"{new_proc.kind} {old_proc.display_name} renamed to "
                        f"{new_proc.display_name} (body unchanged or nearly so)",
                        old=old_proc.display_name,
                        new=new_proc.display_name,
                        old_location=old_proc.location,
                        new_location=new_proc.location,
                    )
                )

        self._report_moves(pairs, changes)

        for old_proc, new_proc, _ in pairs:
            if new_proc.kind == "section":
                if old_proc.fingerprint != new_proc.fingerprint:
                    changes.append(
                        DiffChange(
                            kind="section-body-changed",
                            category="procedure",
                            symbol=new_proc.display_name,
                            detail=f"section {new_proc.display_name} body changed",
                            old_location=old_proc.location,
                            new_location=new_proc.location,
                        )
                    )
                continue
            if old_proc.fingerprint != new_proc.fingerprint:
                changes.append(
                    DiffChange(
                        kind="paragraph-body-changed",
                        category="procedure",
                        symbol=new_proc.display_name,
                        detail=f"paragraph {new_proc.display_name} body changed",
                        old_location=old_proc.location,
                        new_location=new_proc.location,
                    )
                )
                self._diff_statements(old_proc, new_proc, changes)

        for proc in unmatched_new:
            changes.append(
                DiffChange(
                    kind=f"{proc.kind}-added",
                    category="procedure",
                    symbol=proc.display_name,
                    detail=f"{proc.kind} {proc.display_name} added",
                    new=proc.display_name,
                    new_location=proc.location,
                )
            )
        for proc in unmatched_old:
            changes.append(
                DiffChange(
                    kind=f"{proc.kind}-removed",
                    category="procedure",
                    symbol=proc.display_name,
                    detail=f"{proc.kind} {proc.display_name} removed",
                    old=proc.display_name,
                    old_location=proc.location,
                )
            )

    def _collect_procedures(
        self, program: CobolProgram, side: str, caveats: list[str]
    ) -> list[_Procedure]:
        division = program.procedure_division
        if division is None:
            return []

        top_level: list[Any] = sorted(
            [*division._sections.values(), *division.paragraphs],
            key=lambda node: node.location.line,
        )

        procedures: list[_Procedure] = []
        seen: set[str] = set()

        def add(
            display_name: str,
            kind: str,
            parent: str | None,
            location: SourceLocation,
            statements: list[Any],
        ) -> None:
            name = display_name.upper()
            if name in seen:
                caveats.append(
                    f"the {side} program declares the {kind} name "
                    f"{display_name} more than once; only the first is compared"
                )
                return
            seen.add(name)
            procedures.append(
                _Procedure(
                    name=name,
                    display_name=display_name,
                    kind=kind,
                    index=len(procedures),
                    parent=parent,
                    location=location,
                    body=_flatten_body(statements, caveats),
                )
            )

        for node in top_level:
            if isinstance(node, CobolSection):
                section_name = node.section_name or ""
                section_statements: list[Any] = []
                for paragraph in node.paragraphs:
                    section_statements.extend(paragraph.statements)
                if section_name:
                    add(
                        section_name,
                        "section",
                        None,
                        node.location,
                        section_statements,
                    )
                for paragraph in node.paragraphs:
                    if paragraph.paragraph_name and paragraph.paragraph_name != ".":
                        add(
                            paragraph.paragraph_name,
                            "paragraph",
                            section_name.upper() or None,
                            paragraph.location,
                            paragraph.statements,
                        )
            elif isinstance(node, CobolParagraph):
                if node.paragraph_name and node.paragraph_name != ".":
                    add(
                        node.paragraph_name,
                        "paragraph",
                        None,
                        node.location,
                        node.statements,
                    )

        return procedures

    def _match_procedures(
        self,
        old_procs: list[_Procedure],
        new_procs: list[_Procedure],
        caveats: list[str],
    ) -> tuple[
        list[tuple[_Procedure, _Procedure, str]], list[_Procedure], list[_Procedure]
    ]:
        """Pair up procedures: by name first, then by body fingerprint."""
        pairs: list[tuple[_Procedure, _Procedure, str]] = []
        new_by_name = {proc.name: proc for proc in new_procs}
        matched_new: set[str] = set()

        for old_proc in old_procs:
            candidate = new_by_name.get(old_proc.name)
            if candidate is not None and candidate.kind == old_proc.kind:
                pairs.append((old_proc, candidate, "name"))
                matched_new.add(candidate.name)

        matched_old = {old.name for old, _, _ in pairs}
        leftover_old = [p for p in old_procs if p.name not in matched_old]
        leftover_new = [p for p in new_procs if p.name not in matched_new]

        scored: list[tuple[float, str, str, _Procedure, _Procedure]] = []
        for old_proc in leftover_old:
            for new_proc in leftover_new:
                if old_proc.kind != new_proc.kind:
                    continue
                # An empty body is no evidence of anything: SequenceMatcher
                # scores two empty sequences 1.0, which would rename-match
                # every stub paragraph to every other one.
                if not old_proc.body or not new_proc.body:
                    continue
                ratio = SequenceMatcher(
                    None, old_proc.fingerprint, new_proc.fingerprint, autojunk=False
                ).ratio()
                scored.append((ratio, old_proc.name, new_proc.name, old_proc, new_proc))

        # Best score first; name order breaks ties so the greedy pass never
        # depends on iteration order of the inputs.
        scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))

        used_old: set[str] = set()
        used_new: set[str] = set()
        near_misses: dict[tuple[str, str], float] = {}
        for ratio, old_name, new_name, old_proc, new_proc in scored:
            if old_name in used_old or new_name in used_new:
                continue
            if ratio >= self.rename_threshold:
                used_old.add(old_name)
                used_new.add(new_name)
                pairs.append((old_proc, new_proc, "fingerprint"))
            else:
                near_misses.setdefault((old_name, new_name), ratio)

        for (old_name, new_name), ratio in sorted(near_misses.items()):
            if old_name in used_old or new_name in used_new:
                continue
            caveats.append(
                f"{old_name} and {new_name} scored {ratio:.2f} body similarity, "
                f"below the {self.rename_threshold:.2f} rename threshold; "
                "reported as a removal plus an addition rather than a rename"
            )

        unmatched_old = [p for p in leftover_old if p.name not in used_old]
        unmatched_new = [p for p in leftover_new if p.name not in used_new]
        return pairs, unmatched_old, unmatched_new

    @staticmethod
    def _report_moves(
        pairs: list[tuple[_Procedure, _Procedure, str]], changes: list[DiffChange]
    ) -> None:
        """Report the matched procedures whose relative order changed.

        Order is compared with :class:`difflib.SequenceMatcher` over the two
        orderings of the matched pairs, so only the procedures that actually
        had to move to reconcile the two sequences are reported -- inserting
        one paragraph does not report every later paragraph as moved.
        """
        if not pairs:
            return
        by_old = sorted(pairs, key=lambda pair: pair[0].index)
        by_new = sorted(pairs, key=lambda pair: pair[1].index)
        old_sequence = [pair[0].name for pair in by_old]
        new_sequence = [pair[0].name for pair in by_new]

        stable: set[str] = set()
        matcher = SequenceMatcher(None, old_sequence, new_sequence, autojunk=False)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                stable.add(old_sequence[block.a + offset])

        for old_proc, new_proc, _ in sorted(pairs, key=lambda pair: pair[1].index):
            reordered = old_proc.name not in stable
            reparented = old_proc.parent != new_proc.parent
            if not reordered and not reparented:
                continue
            old_where = _position_text(old_proc)
            new_where = _position_text(new_proc)
            changes.append(
                DiffChange(
                    kind=f"{new_proc.kind}-moved",
                    category="procedure",
                    symbol=new_proc.display_name,
                    detail=f"{new_proc.kind} {new_proc.display_name} moved from "
                    f"{old_where} to {new_where}",
                    old=old_where,
                    new=new_where,
                    old_location=old_proc.location,
                    new_location=new_proc.location,
                )
            )

    # -- statements --------------------------------------------------------

    def _diff_statements(
        self, old_proc: _Procedure, new_proc: _Procedure, changes: list[DiffChange]
    ) -> None:
        symbol = new_proc.display_name
        matcher = SequenceMatcher(
            None, old_proc.fingerprint, new_proc.fingerprint, autojunk=False
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            old_items = old_proc.body[i1:i2]
            new_items = new_proc.body[j1:j2]
            paired = min(len(old_items), len(new_items)) if tag == "replace" else 0
            for offset in range(paired):
                before = old_items[offset]
                after = new_items[offset]
                if before.kind == after.kind and before.path == after.path:
                    changes.append(self._changed_statement(symbol, before, after))
                else:
                    changes.append(self._removed_statement(symbol, before))
                    changes.append(self._added_statement(symbol, after))
            for item in old_items[paired:]:
                changes.append(self._removed_statement(symbol, item))
            for item in new_items[paired:]:
                changes.append(self._added_statement(symbol, item))

    @staticmethod
    def _added_statement(symbol: str, item: _FlatStatement) -> DiffChange:
        return DiffChange(
            kind="statement-added",
            category="procedure",
            symbol=symbol,
            detail=f"{_where(item)}statement added: {item.text}",
            new=item.text,
            new_location=item.location,
        )

    @staticmethod
    def _removed_statement(symbol: str, item: _FlatStatement) -> DiffChange:
        return DiffChange(
            kind="statement-removed",
            category="procedure",
            symbol=symbol,
            detail=f"{_where(item)}statement removed: {item.text}",
            old=item.text,
            old_location=item.location,
        )

    @staticmethod
    def _changed_statement(
        symbol: str, before: _FlatStatement, after: _FlatStatement
    ) -> DiffChange:
        """Classify a changed statement, naming the interesting cases."""
        kind = "statement-changed"
        label = "statement changed"
        old_node = before.node
        new_node = after.node

        if isinstance(old_node, MoveStatement) and isinstance(new_node, MoveStatement):
            if old_node.targets != new_node.targets:
                kind, label = "move-target-changed", "MOVE target changed"
            elif (old_node.source or "") != (new_node.source or ""):
                kind, label = "move-source-changed", "MOVE source changed"
        elif isinstance(old_node, PerformStatement) and isinstance(
            new_node, PerformStatement
        ):
            if (old_node.target_paragraph, old_node.thru_paragraph) != (
                new_node.target_paragraph,
                new_node.thru_paragraph,
            ):
                kind, label = "perform-target-changed", "PERFORM target changed"
            elif _text_of(old_node.until_condition) != _text_of(
                new_node.until_condition
            ):
                kind, label = "condition-changed", "PERFORM UNTIL condition changed"
        elif isinstance(old_node, CallStatement) and isinstance(
            new_node, CallStatement
        ):
            if (old_node.called_program or "", bool(old_node.is_dynamic)) != (
                new_node.called_program or "",
                bool(new_node.is_dynamic),
            ):
                kind, label = "call-target-changed", "CALL target changed"
            else:
                kind, label = "call-arguments-changed", "CALL arguments changed"
        elif isinstance(old_node, GoStatement) and isinstance(new_node, GoStatement):
            kind, label = "goto-target-changed", "GO TO target changed"
        elif isinstance(old_node, IfStatement) and isinstance(new_node, IfStatement):
            kind, label = "condition-changed", "IF condition changed"
        elif before.kind == "WHEN":
            kind, label = "condition-changed", "WHEN condition changed"
        elif isinstance(old_node, EvaluateStatement) and isinstance(
            new_node, EvaluateStatement
        ):
            kind, label = "condition-changed", "EVALUATE subject changed"

        return DiffChange(
            kind=kind,
            category="procedure",
            symbol=symbol,
            detail=f"{_where(before)}{label}: {before.text} -> {after.text}",
            old=before.text,
            new=after.text,
            old_location=before.location,
            new_location=after.location,
        )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


#: The parser names an entry written without a data-name
#: ``ANONYMOUS-<level>-<line>``; the line number is not part of its identity.
_ANONYMOUS_NAME_RE = re.compile(r"ANONYMOUS-\d+-\d+", re.IGNORECASE)


def _data_name(item: CobolDataItem) -> str:
    """The name a data entry is matched on across the two programs.

    An entry with no data-name is an implicit FILLER (``05 PIC X(3).``, a
    report group's ``01 TYPE IS PAGE HEADING.``); the parser's synthetic
    name embeds its source line, so keying on it reported every such entry
    removed and re-added whenever a line above it moved. It is keyed as
    FILLER instead: positionally, like any other FILLER.
    """
    if _ANONYMOUS_NAME_RE.fullmatch(item.name or ""):
        return "FILLER"
    return item.name


def _disambiguated(path: str, base_key: str, key: str) -> str:
    """Carry a positional key's ``#n`` suffix into the reported symbol.

    Two FILLERs under one group share a path; without the suffix the report
    would name both of them ``WS-GRP.FILLER`` and a reader could not tell
    which one changed.
    """
    if key == base_key:
        return path
    return f"{path}#{key.rsplit('#', 1)[1]}"


def _where(item: _FlatStatement) -> str:
    return f"in {item.path}: " if item.path else ""


def _position_text(proc: _Procedure) -> str:
    text = f"position {proc.index + 1}"
    if proc.parent:
        text += f" of section {proc.parent}"
    return text


def _normalize(value: Any) -> Any:
    """Compare strings case-insensitively (COBOL names/clauses are)."""
    if isinstance(value, str):
        return value.strip().upper()
    return value


def _render_value(value: Any) -> str:
    if value is None or value == "":
        return "(none)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ", ".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _render_value(value)


def _picture_text(item: CobolDataItem) -> str:
    picture = item.picture_clause
    if picture is None:
        return ""
    return str(picture.pattern or "").upper()


def _picture_positions(picture: str) -> str:
    """A PICTURE string with every repeat factor written out, so two
    spellings of the same picture (`X(2)` / `XX`, `S9(3)V9(2)` / `S999V99`)
    compare equal."""
    return "".join(PictureClause._expand_symbols(picture))


def _canonical_usage(usage: Any) -> str:
    """One spelling per USAGE: the IBM Enterprise COBOL synonyms (`BINARY` /
    `COMP-4` / `COMPUTATIONAL` are `COMP`, `PACKED-DECIMAL` is `COMP-3`, ...).
    `COMP-5` stays distinct from `COMP`: it is not truncated to its PICTURE,
    so changing one into the other changes what the program computes."""
    upper = str(usage or "DISPLAY").strip().upper()
    for spellings, canonical in (
        (BINARY_FIXED_USAGES, "COMP"),
        (BINARY_NATIVE_USAGES, "COMP-5"),
        (PACKED_USAGES, "COMP-3"),
        (SINGLE_FLOAT_USAGES, "COMP-1"),
        (DOUBLE_FLOAT_USAGES, "COMP-2"),
    ):
        if upper in spellings:
            return canonical
    return upper.replace("COMPUTATIONAL", "COMP")


def _occurs_text(item: CobolDataItem) -> str:
    occurs = item.occurs_clause
    if occurs is None:
        return ""
    parts = [f"{occurs.min_times}..{occurs.max_times}"]
    if occurs.depending_on:
        parts.append(f"DEPENDING ON {occurs.depending_on.upper()}")
    if occurs.index_names:
        parts.append(
            "INDEXED BY " + " ".join(name.upper() for name in occurs.index_names)
        )
    elif occurs.indexed_by:
        parts.append(f"INDEXED BY {occurs.indexed_by.upper()}")
    for clause in occurs.key_clauses:
        keys = " ".join(str(key).upper() for key in clause.get("keys", []))
        parts.append(f"{clause.get('direction', '')} KEY {keys}")
    return " ".join(parts)


def _alternate_key_text(select: SelectStatement) -> str:
    """Render every ALTERNATE RECORD KEY as one comparable string.

    Key order is the order they were declared in (it is part of the file's
    definition), but each key's own clause dict is rendered field-sorted so
    the text does not depend on dict construction order.
    """
    entries = [
        ", ".join(f"{key}={alternate[key]}" for key in sorted(alternate))
        for alternate in select.alternate_keys
    ]
    return "; ".join(entries)
