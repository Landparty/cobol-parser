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
  deliberate, but the tail is invisible to the callee). A shorter argument
  passed to a maximum-size buffer (an operand of at least
  :data:`MAX_BUFFER_BYTES`, the ``PIC X(32767)`` idiom of a routine that is
  told the real length some other way) is info, not error.
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
incomplete set says so. That value set is flow-insensitive (every MOVE to
the identifier, wherever it is), so when it names more than one program a
finding is against a *possible* target: it carries ``possible_targets`` and
its severity is capped at warning.

Memory stays flat: each file is reduced to its interfaces and call sites
(small dataclasses) as it is parsed, so only one AST is live at a time.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from ..batch import BatchResult, parse_files, parse_files_with_copybooks
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements.call import CallStatement
from ._copy_holes import items_with_copy_holes
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

#: A callee operand this long is a maximum-size buffer: ``PIC X(32767)``,
#: ``X(32760)``, ``X(65535)``. A routine declares one to take any caller's
#: area and is told the real length another way (a length operand, a
#: delimiter), so a shorter argument is the design, not an overrun.
MAX_BUFFER_BYTES = 32760

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
    #: The copybook the CALL was written in, when it came from one (then
    #: ``line`` counts that file's lines, not *path*'s).
    origin_file: str | None = None


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
    #: A dynamic CALL whose value set names more than one program: every
    #: name in it. The finding is against one *possible* target (the value
    #: set is flow-insensitive: any MOVE to the identifier anywhere), so its
    #: severity is capped at warning. Empty for a static or one-target CALL.
    possible_targets: tuple[str, ...] = ()
    #: The copybook the CALL sits in, when it was COPYed into *path*: then
    #: ``line`` is that copybook's line. None for a CALL in *path* itself.
    origin_file: str | None = None

    @property
    def file(self) -> str:
        """The file ``line`` counts lines in."""
        return self.origin_file or self.path

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
        if self.possible_targets:
            out["possible_targets"] = list(self.possible_targets)
        if self.origin_file is not None:
            out["origin_file"] = self.origin_file
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
            lines.append(f"{f.file}:{f.line}: {f.severity}: [{f.kind}] {f.message}")
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
        #: Groups whose layout misses a COPY member that was not expanded.
        self.holed = items_with_copy_holes(unit)
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
    if id(item) in index.holed:
        return OperandShape(
            text=stripped,
            unknown_reason="its layout holds a COPY that was not expanded "
            "(pass --copybook-path)",
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
                    skip_missing_copybooks=True,
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
            self._absorb(
                path,
                ast,
                interfaces,
                calls,
                source_map=parse.expansion_source_map if parse else None,
            )
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
        source_map: dict[int, tuple[str, int]] | None = None,
    ) -> None:
        """Collect *ast*'s entries into *interfaces* and its CALLs into *calls*.

        *source_map* is the copybook expander's per-line record
        (``ParseResult.expansion_source_map``): with it, each CALL's line is
        put back on the file on disk -- the program's own line, or the
        copybook's (``origin_file``) for a CALL COPYed in. Without it the
        lines count the parsed text, which is what ``lint --callee-path``
        wants: it maps them itself (:func:`~.lint.apply_source_map`).
        """
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
                    calls.append(_on_disk(site, source_map))

    # -- comparison -------------------------------------------------------

    @staticmethod
    def _compare(
        interfaces: dict[str, list[_Interface]],
        calls: list[_CallSite],
        report: CallInterfaceReport,
    ) -> None:
        unknown_notes: set[str] = set()
        for site in calls:
            where = f"{site.origin_file or site.path}:{site.line}: {site.caller}"
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


def _on_disk(
    site: _CallSite, source_map: dict[int, tuple[str, int]] | None
) -> _CallSite:
    """*site* with its line moved from the expanded text to the file on disk.

    A line the map does not cover keeps its parsed number: no map means no
    expansion happened, and the parsed text is the file.
    """
    if not source_map or site.line <= 0:
        return site
    origin = source_map.get(site.line)
    if origin is None:
        return site
    origin_file, origin_line = origin
    same = os.path.normcase(os.path.abspath(origin_file)) == os.path.normcase(
        os.path.abspath(site.path)
    )
    return replace(site, line=origin_line, origin_file=None if same else origin_file)


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
    # A dynamic CALL with several candidate targets reaches one of them at
    # run time, which one depends on flow the value set does not track: a
    # mismatch with one candidate is a "may", not an "is".
    possible = site.targets if site.is_dynamic and len(site.targets) > 1 else ()

    def add(
        kind: str,
        severity: str,
        message: str,
        position: int | None = None,
        argument: OperandShape | None = None,
        parameter: OperandShape | None = None,
    ) -> None:
        if possible:
            severity = "warning" if severity == "error" else severity
        report.findings.append(
            CallInterfaceFinding(
                kind=kind,
                severity=severity,
                message=message,
                caller=site.caller,
                callee=callee.program_id,
                path=site.path,
                line=site.line,
                origin_file=site.origin_file,
                callee_path=callee.path,
                position=position,
                argument=argument,
                parameter=parameter,
                possible_targets=possible,
            )
        )

    call = (
        f"dynamic CALL (possible target '{target}', one of {len(possible)})"
        if possible
        else f"CALL '{target}'"
    )
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
                f"{site.origin_file or site.path}:{site.line}: {call} argument {position}: length not "
                f"compared ({subject}: {reason})"
            )
        elif (
            argument.byte_length < parameter.byte_length
            and parameter.byte_length >= MAX_BUFFER_BYTES
        ):
            add(
                KIND_LENGTH,
                "info",
                f"{call} argument {position} ({argument.text}) is "
                f"{argument.byte_length} byte(s) but {callee.entry}'s "
                f"{parameter.text} is a maximum-size buffer of "
                f"{parameter.byte_length}: fine as long as the callee is told "
                "the real length and stays inside it",
                position,
                argument,
                parameter,
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


# ---------------------------------------------------------------------------
# One program against callees found on a search path (the lint rule)
# ---------------------------------------------------------------------------

#: File names tried for a CALLed program NAME in each callee directory.
CALLEE_EXTENSIONS: tuple[str, ...] = ("", ".cbl", ".CBL", ".cob", ".COB")


def find_callee_file(name: str, callee_paths: Iterable[str]) -> str | None:
    """The source file of program *name* in *callee_paths* (``NAME``,
    ``NAME.cbl``, ``name.cob``, ...), first directory first, else None."""
    import os

    for directory in callee_paths:
        try:
            entries = set(os.listdir(directory))
        except OSError:
            continue
        for candidate in (name, name.lower()):
            for ext in CALLEE_EXTENSIONS:
                if candidate + ext in entries:
                    return os.path.join(directory, candidate + ext)
    return None


@dataclass
class CalleeCheck:
    """What :meth:`CalleeResolver.check_program` found for one program."""

    report: CallInterfaceReport
    #: CALL targets with no source file in the callee directories.
    not_found: list[str] = field(default_factory=list)


class CalleeResolver:
    """Check one already-parsed program's CALLs against callees looked up
    by name in *callee_paths* -- what ``lint``'s ``call-check`` rule runs.

    Each callee file is parsed once per resolver and reduced to its
    interfaces, so a multi-file lint run that CALLs one subprogram from a
    hundred programs parses it once. A program's own contained programs
    are reached first, as COBOL scope says.
    """

    def __init__(
        self,
        callee_paths: Iterable[str],
        *,
        copybook_paths: Iterable[str] | None = None,
        debug_lines: bool = False,
    ) -> None:
        self.callee_paths = list(callee_paths)
        self.copybook_paths = list(copybook_paths or [])
        self.debug_lines = debug_lines
        # path -> interfaces of that file (None: it did not parse)
        self._parsed: dict[str, dict[str, list[_Interface]] | None] = {}

    def _interfaces_of(self, path: str) -> dict[str, list[_Interface]] | None:
        if path not in self._parsed:
            results = list(
                parse_files_with_copybooks(
                    [path],
                    copybook_paths=self.copybook_paths,
                    workers=1,
                    debug_lines=self.debug_lines,
                    skip_missing_copybooks=True,
                )
                if self.copybook_paths
                else parse_files([path], workers=1, debug_lines=self.debug_lines)
            )
            parse = results[0].result if results else None
            if (
                parse is None
                or parse.ast is None
                or parse.ast.procedure_division is None
            ):
                self._parsed[path] = None
            else:
                interfaces: dict[str, list[_Interface]] = {}
                CallInterfaceChecker._absorb(path, parse.ast, interfaces, [])
                self._parsed[path] = interfaces
        return self._parsed[path]

    def check_program(self, path: str, ast: CobolProgram) -> CalleeCheck:
        interfaces: dict[str, list[_Interface]] = {}
        calls: list[_CallSite] = []
        CallInterfaceChecker._absorb(path, ast, interfaces, calls)
        not_found: list[str] = []
        unparsed: list[str] = []
        wanted = sorted({t for site in calls for t in site.targets} - set(interfaces))
        for name in wanted:
            found = find_callee_file(name, self.callee_paths)
            if found is None:
                not_found.append(name)
                continue
            callee = self._interfaces_of(found)
            if callee is None:
                unparsed.append(f"{name} ({found})")
                continue
            for key, entries in callee.items():
                interfaces.setdefault(key, []).extend(entries)
        report = CallInterfaceReport()
        CallInterfaceChecker._compare(interfaces, calls, report)
        for note in unparsed:
            report.unchecked.append(f"CALL {note}: the callee did not parse")
        return CalleeCheck(report=report, not_found=not_found)
