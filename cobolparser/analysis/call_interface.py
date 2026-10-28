"""
Cross-program CALL interface checking.

:class:`~.linkage_checker.LinkageChecker` compares a CALL with its callee
only when both sit in the same source file, and only by argument count and
passing mode. The commoner case is a separately compiled callee in another
member, and the commoner failure is a mismatch of *shape*: a caller passes
a 20-byte record to a callee whose LINKAGE item is 30 bytes long, and the
callee reads (or worse, writes) ten bytes of whatever follows. Nothing
fails at compile time; the program abends (S0C4/S0C7) or corrupts storage
in production.

:class:`CallInterfaceChecker` reads many files, collects every callee's
calling interface (:class:`~.program_signature.ProgramSignatureExtractor`:
each PROCEDURE DIVISION USING and ENTRY, its operands' byte lengths, usages
and BY VALUE / BY REFERENCE modes) and every caller's CALL sites with the
shape of each argument, and compares them pairwise:

- ``argument-count`` (error) -- more or fewer operands than the entry
  declares.
- ``passing-mode`` (error) -- BY VALUE where the callee declares BY
  REFERENCE, or BY REFERENCE / BY CONTENT where it declares BY VALUE.
- ``length`` -- the argument is shorter than the callee's operand (error:
  the callee addresses bytes past it) or longer (info: harmless, often
  deliberate, but the tail is invisible to the callee).
- ``usage`` (warning) -- two elementary items with different storage
  (COMP-3 against zoned DISPLAY, BINARY against COMP-5, ...) or different
  categories (numeric against alphanumeric DISPLAY).
- ``returning`` (warning) -- a RETURNING on one side only.

Nothing is guessed. An argument whose length cannot be computed (a numeric
literal, ``ADDRESS OF``, a variable reference modification, a name declared
twice) is compared by count and mode only and listed in
:attr:`CallInterfaceReport.unchecked`; a CALL to a program not among the
files is counted in :attr:`CallInterfaceReport.external_calls`, not
reported as a problem; a dynamic CALL is checked against every target its
:class:`~.value_tracker.DynamicCallAnalyzer` value set names, and an
incomplete set says so.

Memory stays flat: each file is reduced to its interfaces and call sites
(small dataclasses) as it is parsed, so only one AST is live at a time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..batch import BatchResult, parse_files, parse_files_with_copybooks
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements.call import CallStatement
from ._names import callee_names
from .codebase import (
    _PARALLEL_THRESHOLD,
    _node_statements,
    _normalize_program_name,
    program_graph_ids,
)
from .program_signature import EntryPoint, ProgramSignatureExtractor, _byte_length
from .value_tracker import DynamicCallAnalyzer

#: Finding kinds, most severe first in the order they are checked.
KIND_ARGUMENT_COUNT = "argument-count"
KIND_PASSING_MODE = "passing-mode"
KIND_LENGTH = "length"
KIND_USAGE = "usage"
KIND_RETURNING = "returning"

SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

#: Files parsed per batch: each chunk's ASTs are reduced to interfaces and
#: call sites before the next chunk is parsed.
_CHUNK_SIZE = 32

#: OO member units are not CALL targets (their class is).
_OO_MEMBER_KINDS = frozenset({"FACTORY", "OBJECT", "METHOD"})

#: USAGE spellings that occupy the same storage, by storage class.
_USAGE_CLASS: dict[str, str] = {
    "DISPLAY": "DISPLAY",
    "COMP": "BINARY",
    "COMPUTATIONAL": "BINARY",
    "COMP-4": "BINARY",
    "COMPUTATIONAL-4": "BINARY",
    "BINARY": "BINARY",
    "COMP-3": "PACKED-DECIMAL",
    "COMPUTATIONAL-3": "PACKED-DECIMAL",
    "PACKED-DECIMAL": "PACKED-DECIMAL",
    "COMP-5": "COMP-5",
    "COMPUTATIONAL-5": "COMP-5",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-2": "COMP-2",
}

_SUBSCRIPT_RE = re.compile(r"\(([^()]*)\)")
_QUALIFIER_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)
_HEX_LITERAL_RE = re.compile(r"^X(['\"])([0-9A-Fa-f]*)\1$")


@dataclass(frozen=True)
class OperandShape:
    """What one side of a CALL knows about one operand."""

    #: The operand as written (a data name, a literal, ``OMITTED``, ...).
    text: str
    byte_length: int | None = None
    #: Storage class (``DISPLAY`` / ``BINARY`` / ``PACKED-DECIMAL`` /
    #: ``COMP-5`` / ...) for an elementary item, None for a group or a
    #: literal.
    storage: str | None = None
    #: ``numeric`` / ``alphanumeric`` for an elementary DISPLAY item.
    category: str | None = None
    #: Why the length is unknown, when it is.
    unknown_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"text": self.text, "byte_length": self.byte_length}
        if self.storage is not None:
            out["storage"] = self.storage
        if self.category is not None:
            out["category"] = self.category
        return out


@dataclass(frozen=True)
class _Interface:
    """One callable entry of one program, reduced to what a caller needs."""

    program_id: str
    entry: str
    path: str
    parameters: tuple[OperandShape, ...]
    modes: tuple[str, ...]
    returning: str | None


@dataclass(frozen=True)
class _CallSite:
    caller: str
    path: str
    line: int
    targets: tuple[str, ...]
    is_dynamic: bool
    incomplete: bool
    arguments: tuple[OperandShape, ...]
    modes: tuple[str, ...]
    returning: str | None
    #: Target name -> the nested program's graph id COBOL scope sends the
    #: CALL to, when it reaches one.
    scoped: tuple[tuple[str, str], ...] = ()


@dataclass
class CallInterfaceFinding:
    """One disagreement between a CALL and the entry it reaches."""

    kind: str
    severity: str
    message: str
    caller: str
    callee: str
    path: str
    line: int
    callee_path: str
    #: 1-based operand position, None for count / RETURNING findings.
    position: int | None = None
    argument: OperandShape | None = None
    parameter: OperandShape | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "caller": self.caller,
            "callee": self.callee,
            "path": self.path,
            "line": self.line,
            "callee_path": self.callee_path,
        }
        if self.position is not None:
            out["position"] = self.position
        if self.argument is not None:
            out["argument"] = self.argument.to_dict()
        if self.parameter is not None:
            out["parameter"] = self.parameter.to_dict()
        return out


@dataclass
class CallInterfaceReport:
    findings: list[CallInterfaceFinding] = field(default_factory=list)
    #: CALL sites matched to an entry among the files (one per target).
    checked_calls: int = 0
    #: CALL target name -> number of CALL sites whose callee is not among
    #: the files (a system routine, a program outside the tree).
    external_calls: dict[str, int] = field(default_factory=dict)
    #: What could not be checked, one line each.
    unchecked: list[str] = field(default_factory=list)
    #: Files that did not parse cleanly, ``{"path", "error"}``.
    errors: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(SEVERITIES, 0)
        for finding in self.findings:
            out[finding.severity] += 1
        return out

    def worst_severity(self) -> str | None:
        for severity in SEVERITIES:
            if any(f.severity == severity for f in self.findings):
                return severity
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                "total": len(self.findings),
                **self.counts(),
                "checked_calls": self.checked_calls,
                "external_calls": sum(self.external_calls.values()),
            },
            "external_calls": dict(sorted(self.external_calls.items())),
            "unchecked": list(self.unchecked),
            "errors": list(self.errors),
        }

    def to_text(self) -> str:
        lines = []
        for f in self.findings:
            lines.append(f"{f.path}:{f.line}: {f.severity}: [{f.kind}] {f.message}")
        counts = self.counts()
        lines.append(
            f"{len(self.findings)} finding(s) ({counts['error']} error, "
            f"{counts['warning']} warning, {counts['info']} info) over "
            f"{self.checked_calls} checked CALL(s); "
            f"{sum(self.external_calls.values())} CALL(s) to programs not "
            "among the files"
        )
        for note in self.unchecked:
            lines.append(f"unchecked: {note}")
        for error in self.errors:
            lines.append(f"error: {error['path']}: {error['error']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Operand shapes
# ---------------------------------------------------------------------------


def _storage_of(item: CobolDataItem) -> tuple[str | None, str | None]:
    """``(storage class, category)`` of an elementary item, else (None, None)."""
    picture = item.picture_clause
    usage = (item.usage or "DISPLAY").upper()
    storage = _USAGE_CLASS.get(usage)
    if picture is None:
        # COMP-1 / COMP-2 / POINTER and friends have no PICTURE.
        if storage in ("COMP-1", "COMP-2") or usage in ("POINTER", "PROCEDURE-POINTER"):
            return storage or usage, None
        return None, None
    if storage is None:
        return usage, None
    category: str | None = None
    if storage == "DISPLAY":
        pattern = (picture.pattern or "").upper()
        if pattern and "9" in pattern and not set(pattern) & set("XAN"):
            category = "numeric"
        elif pattern and set(pattern) & set("XA"):
            category = "alphanumeric"
    return storage, category


def _item_shape(text: str, item: CobolDataItem) -> OperandShape:
    storage, category = _storage_of(item)
    children = [c for c in getattr(item, "children", None) or [] if c is not None]
    if children and item.picture_clause is None:
        storage, category = None, None
    length = _byte_length(item)
    return OperandShape(
        text=text,
        byte_length=length,
        storage=storage,
        category=category,
        unknown_reason=None if length is not None else "its length cannot be computed",
    )


class _DataIndex:
    """Name -> declarations of one program unit, for argument lookup."""

    def __init__(self, unit: CobolProgram) -> None:
        self._by_name: dict[str, list[CobolDataItem]] = {}
        for item in unit.get_data_items():
            if isinstance(item, CobolDataItem) and item.name and not item.is_filler:
                self._by_name.setdefault(item.name.upper(), []).append(item)

    def lookup(self, name: str, qualifiers: list[str]) -> list[CobolDataItem]:
        candidates = self._by_name.get(name.upper(), [])
        if not qualifiers:
            return candidates
        wanted = [q.upper() for q in qualifiers]
        out = []
        for item in candidates:
            ancestors = []
            node = getattr(item, "parent", None)
            while isinstance(node, CobolDataItem):
                ancestors.append((node.name or "").upper())
                node = getattr(node, "parent", None)
            # Each qualifier must name an ancestor, innermost first.
            at = 0
            for qualifier in wanted:
                while at < len(ancestors) and ancestors[at] != qualifier:
                    at += 1
                if at == len(ancestors):
                    break
                at += 1
            else:
                out.append(item)
        return out


def _argument_shape(text: str, index: _DataIndex) -> OperandShape:
    """The shape of one CALL argument as the caller writes it."""
    stripped = text.strip()
    upper = stripped.upper()
    if upper == "OMITTED":
        return OperandShape(text=stripped, unknown_reason="it is OMITTED")
    if upper.startswith(("ADDRESS OF", "LENGTH OF")):
        return OperandShape(
            text=stripped, unknown_reason="it is a special register (ADDRESS/LENGTH OF)"
        )
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        return OperandShape(
            text=stripped,
            byte_length=len(stripped) - 2,
            storage="DISPLAY",
            category="alphanumeric",
        )
    hex_literal = _HEX_LITERAL_RE.match(stripped)
    if hex_literal:
        return OperandShape(text=stripped, byte_length=len(hex_literal.group(2)) // 2)
    if re.fullmatch(r"[+-]?\d*\.?\d+", stripped) or upper in (
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
    ):
        return OperandShape(
            text=stripped,
            unknown_reason="it is a numeric literal or figurative constant, "
            "whose passed length the compiler chooses",
        )

    groups = _SUBSCRIPT_RE.findall(stripped)
    bare = _SUBSCRIPT_RE.sub(" ", stripped)
    parts = [p.strip() for p in _QUALIFIER_RE.split(bare) if p.strip()]
    if not parts:
        return OperandShape(text=stripped, unknown_reason="it names no data item")
    items = index.lookup(parts[0], parts[1:])
    if not items:
        return OperandShape(
            text=stripped, unknown_reason="it is not declared in the calling program"
        )
    if len(items) > 1:
        return OperandShape(
            text=stripped,
            unknown_reason="its name is declared more than once; qualify it",
        )
    item = items[0]
    shape = _item_shape(stripped, item)
    refmod = [g for g in groups if ":" in g]
    if refmod:
        start, _, length = refmod[-1].partition(":")
        length = length.strip()
        if length.isdigit():
            return OperandShape(text=stripped, byte_length=int(length))
        return OperandShape(
            text=stripped,
            unknown_reason="its reference modification has no literal length",
        )
    occurs = item.occurs_clause
    if occurs is not None and not groups:
        return OperandShape(
            text=stripped,
            unknown_reason="it is a table element passed without a subscript",
        )
    return shape


def _parameter_shape(parameter: Any) -> OperandShape:
    if not parameter.declared:
        return OperandShape(
            text=parameter.name, unknown_reason="it is not declared in LINKAGE SECTION"
        )
    usage = (parameter.usage or "DISPLAY").upper()
    storage = None if parameter.is_group else _USAGE_CLASS.get(usage, usage)
    category = None
    if storage == "DISPLAY" and parameter.picture:
        pattern = parameter.picture.upper()
        if "9" in pattern and not set(pattern) & set("XAN"):
            category = "numeric"
        elif set(pattern) & set("XA"):
            category = "alphanumeric"
    return OperandShape(
        text=parameter.name,
        byte_length=parameter.byte_length,
        storage=storage,
        category=category,
        unknown_reason=(
            None if parameter.byte_length is not None else "its length is unknown"
        ),
    )


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


class CallInterfaceChecker:
    """Compare every CALL with the interface of the program it reaches.

    Usage::

        report = CallInterfaceChecker().check_files(["A.cbl", "B.cbl"])
        report.findings        # list[CallInterfaceFinding]
        report.unchecked       # what could not be compared
        report.external_calls  # CALL targets outside the files

    :meth:`check_results` takes parses the caller already made (one
    :class:`~cobolparser.batch.BatchResult` per file); :meth:`check_programs`
    takes ``(path, CobolProgram)`` pairs.
    """

    def __init__(
        self,
        *,
        copybook_paths: list[str] | None = None,
        workers: int | None = None,
        debug_lines: bool = False,
    ) -> None:
        self.copybook_paths = list(copybook_paths or [])
        self.workers = workers
        self.debug_lines = debug_lines

    # -- public API -------------------------------------------------------

    def check_files(self, paths: list[str]) -> CallInterfaceReport:
        """Parse *paths* (in chunks, so few ASTs are live at once) and check."""
        return self.check_results(self._parse(list(paths)))

    def _parse(self, paths: list[str]) -> Iterable[BatchResult]:
        for start in range(0, len(paths), _CHUNK_SIZE):
            chunk = paths[start : start + _CHUNK_SIZE]
            workers = self.workers
            if workers is None and len(chunk) < _PARALLEL_THRESHOLD:
                workers = 1  # a process pool costs more than it saves here
            if self.copybook_paths:
                yield from parse_files_with_copybooks(
                    chunk,
                    copybook_paths=self.copybook_paths,
                    workers=workers,
                    debug_lines=self.debug_lines,
                )
            else:
                yield from parse_files(
                    chunk, workers=workers, debug_lines=self.debug_lines
                )

    def check_results(self, results: Iterable[BatchResult]) -> CallInterfaceReport:
        report = CallInterfaceReport()
        interfaces: dict[str, list[_Interface]] = {}
        calls: list[_CallSite] = []
        for result in results:
            path = str(result.path)
            parse = result.result
            ast = parse.ast if parse is not None else None
            if ast is None:
                reason = result.read_error or (
                    str(parse.errors[0]) if parse and parse.errors else "no AST"
                )
                report.errors.append({"path": path, "error": reason})
                report.unchecked.append(
                    f"{path}: not parsed ({reason}); its interfaces and CALLs "
                    "are not checked"
                )
                continue
            if parse is not None and parse.errors:
                report.errors.append(
                    {
                        "path": path,
                        "error": f"{len(parse.errors)} parse error(s); "
                        f"first: {parse.errors[0]}",
                    }
                )
            self._absorb(path, ast, interfaces, calls)
        self._compare(interfaces, calls, report)
        return report

    def check_programs(
        self, programs: Iterable[tuple[str, CobolProgram]]
    ) -> CallInterfaceReport:
        report = CallInterfaceReport()
        interfaces: dict[str, list[_Interface]] = {}
        calls: list[_CallSite] = []
        for path, ast in programs:
            self._absorb(str(path), ast, interfaces, calls)
        self._compare(interfaces, calls, report)
        return report

    # -- collection -------------------------------------------------------

    @staticmethod
    def _absorb(
        path: str,
        ast: CobolProgram,
        interfaces: dict[str, list[_Interface]],
        calls: list[_CallSite],
    ) -> None:
        units = [u for u in ast.program_units() if u.unit_kind not in _OO_MEMBER_KINDS]
        graph_ids = program_graph_ids(units, path)
        for unit in units:
            DynamicCallAnalyzer().analyze(unit)
        for unit in units:
            program_id = graph_ids[id(unit)]
            signature = ProgramSignatureExtractor().analyze(unit)
            entries: list[EntryPoint] = list(signature.entry_points)
            names_seen = {e.name.upper() for e in entries}
            if (unit.program_name or "").upper() not in names_seen:
                # No USING at all: the primary entry takes no operands.
                entries.insert(
                    0,
                    EntryPoint(name=unit.program_name or program_id, kind="none"),
                )
            for entry in entries:
                key = (
                    program_id
                    if entry.name.upper() == (unit.program_name or "").upper()
                    else _normalize_program_name(entry.name)
                )
                interfaces.setdefault(key, []).append(
                    _Interface(
                        program_id=program_id,
                        entry=_normalize_program_name(entry.name),
                        path=path,
                        parameters=tuple(_parameter_shape(p) for p in entry.parameters),
                        modes=tuple(
                            (p.by_clause or "REFERENCE").upper()
                            for p in entry.parameters
                        ),
                        returning=entry.returning,
                    )
                )
            index = _DataIndex(unit)
            for owner, statement in _node_statements(unit):
                if not isinstance(statement, CallStatement):
                    continue
                site = _call_site(statement, program_id, path, owner, index, graph_ids)
                if site is not None:
                    calls.append(site)

    # -- comparison -------------------------------------------------------

    @staticmethod
    def _compare(
        interfaces: dict[str, list[_Interface]],
        calls: list[_CallSite],
        report: CallInterfaceReport,
    ) -> None:
        unknown_notes: set[str] = set()
        for site in calls:
            where = f"{site.path}:{site.line}: {site.caller}"
            if site.is_dynamic and site.incomplete:
                report.unchecked.append(
                    f"{where}: dynamic CALL whose possible targets are not all "
                    "known; only the known ones were checked"
                )
            if site.is_dynamic and not site.targets:
                report.unchecked.append(
                    f"{where}: dynamic CALL with no resolvable target; not checked"
                )
            scoped = dict(site.scoped)
            for target in site.targets:
                key = scoped.get(target, target)
                candidates = interfaces.get(key, [])
                if not candidates:
                    report.external_calls[target] = (
                        report.external_calls.get(target, 0) + 1
                    )
                    continue
                if len({c.path for c in candidates}) > 1:
                    report.unchecked.append(
                        f"{where}: CALL {target}: the target is declared in "
                        f"{len({c.path for c in candidates})} files; not checked"
                    )
                    continue
                report.checked_calls += 1
                _compare_one(site, target, candidates[0], report, unknown_notes)
        report.unchecked.extend(sorted(unknown_notes))
        report.findings.sort(
            key=lambda f: (f.path, f.line, f.callee, f.position or 0, f.kind)
        )


def _call_site(
    statement: CallStatement,
    program_id: str,
    path: str,
    owner: CobolProgram,
    index: _DataIndex,
    graph_ids: dict[int, str],
) -> _CallSite | None:
    line = statement.location.line if statement.location else 0
    if statement.is_dynamic:
        targets = tuple(sorted(callee_names(statement.possible_values)))
        incomplete = bool(statement.get_metadata("possible_values_incomplete"))
    else:
        target = _normalize_program_name(statement.called_program or "")
        if not target:
            return None
        targets = (target,)
        incomplete = False
    scoped = []
    for target in targets:
        nested = owner.nested_program_called(target)
        if nested is not None and id(nested) in graph_ids:
            scoped.append((target, graph_ids[id(nested)]))
    return _CallSite(
        caller=program_id,
        path=path,
        line=line,
        targets=targets,
        is_dynamic=statement.is_dynamic,
        incomplete=incomplete,
        arguments=tuple(
            _argument_shape(p.name, index) for p in statement.using_parameters
        ),
        modes=tuple(
            (p.passing_mode or "REFERENCE").upper() for p in statement.using_parameters
        ),
        returning=statement.returning_parameter,
        scoped=tuple(scoped),
    )


def _compare_one(
    site: _CallSite,
    target: str,
    callee: _Interface,
    report: CallInterfaceReport,
    unknown_notes: set[str],
) -> None:
    def add(
        kind: str,
        severity: str,
        message: str,
        position: int | None = None,
        argument: OperandShape | None = None,
        parameter: OperandShape | None = None,
    ) -> None:
        report.findings.append(
            CallInterfaceFinding(
                kind=kind,
                severity=severity,
                message=message,
                caller=site.caller,
                callee=callee.program_id,
                path=site.path,
                line=site.line,
                callee_path=callee.path,
                position=position,
                argument=argument,
                parameter=parameter,
            )
        )

    call = f"CALL '{target}'"
    passed, declared = len(site.arguments), len(callee.parameters)
    if passed != declared:
        add(
            KIND_ARGUMENT_COUNT,
            "error",
            f"{call} passes {passed} argument(s) but {callee.entry} "
            f"declares {declared}",
        )

    for position, (argument, mode, parameter, declared_mode) in enumerate(
        zip(site.arguments, site.modes, callee.parameters, callee.modes, strict=False),
        start=1,
    ):
        if argument.text.upper() == "OMITTED":
            continue
        if declared_mode == "VALUE" and mode != "VALUE":
            add(
                KIND_PASSING_MODE,
                "error",
                f"{call} passes argument {position} ({argument.text}) BY {mode} "
                f"but {callee.entry} declares {parameter.text} BY VALUE",
                position,
                argument,
                parameter,
            )
        elif declared_mode == "REFERENCE" and mode == "VALUE":
            add(
                KIND_PASSING_MODE,
                "error",
                f"{call} passes argument {position} ({argument.text}) BY VALUE "
                f"but {callee.entry} declares {parameter.text} BY REFERENCE",
                position,
                argument,
                parameter,
            )

        if argument.byte_length is None or parameter.byte_length is None:
            reason = argument.unknown_reason or parameter.unknown_reason
            subject = (
                f"argument {argument.text}"
                if argument.byte_length is None
                else f"{callee.entry}'s {parameter.text}"
            )
            unknown_notes.add(
                f"{site.path}:{site.line}: {call} argument {position}: length not "
                f"compared ({subject}: {reason})"
            )
        elif argument.byte_length < parameter.byte_length:
            add(
                KIND_LENGTH,
                "error",
                f"{call} argument {position} ({argument.text}) is "
                f"{argument.byte_length} byte(s) but {callee.entry}'s "
                f"{parameter.text} is {parameter.byte_length}: the callee "
                f"addresses {parameter.byte_length - argument.byte_length} "
                "byte(s) past it",
                position,
                argument,
                parameter,
            )
        elif argument.byte_length > parameter.byte_length:
            add(
                KIND_LENGTH,
                "info",
                f"{call} argument {position} ({argument.text}) is "
                f"{argument.byte_length} byte(s) but {callee.entry}'s "
                f"{parameter.text} is {parameter.byte_length}: the callee sees "
                "only the first part of it",
                position,
                argument,
                parameter,
            )

        if (
            argument.storage
            and parameter.storage
            and argument.storage != parameter.storage
        ):
            add(
                KIND_USAGE,
                "warning",
                f"{call} argument {position} ({argument.text}) is "
                f"{argument.storage} but {callee.entry}'s {parameter.text} is "
                f"{parameter.storage}",
                position,
                argument,
                parameter,
            )
        elif (
            argument.category
            and parameter.category
            and argument.category != parameter.category
        ):
            add(
                KIND_USAGE,
                "warning",
                f"{call} argument {position} ({argument.text}) is "
                f"{argument.category} but {callee.entry}'s {parameter.text} is "
                f"{parameter.category}",
                position,
                argument,
                parameter,
            )

    if callee.returning and not site.returning:
        add(
            KIND_RETURNING,
            "warning",
            f"{call} has no RETURNING but {callee.entry} returns "
            f"{callee.returning}",
        )
    elif site.returning and not callee.returning:
        add(
            KIND_RETURNING,
            "warning",
            f"{call} RETURNING {site.returning} but {callee.entry} declares no "
            "RETURNING item",
        )
