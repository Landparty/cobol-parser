"""Run analyzers over many COBOL files in one process.

``batch.py`` parses many files and hands every :class:`ParseResult` -- and
therefore every AST -- back to the caller. That is the right shape for a
caller that wants the trees. It is the wrong shape for "grade this whole
checkout": a 5,000-file shop's ASTs do not usefully fit in one process, and
pickling them out of each worker costs far more than the analysis does.

So this module inverts it. The parse *and* the analysis both happen inside
the worker, and what comes back is the small JSON-shaped report dict the
analyzers already produce. A worker's peak memory is one file's AST, and
the parent accumulates only reports.

THREE PROPERTIES THIS MODULE OWES ITS CALLER:

  FAULT ISOLATION IS PER FILE. A file that cannot be read, cannot be
  parsed, or trips an analyzer costs its own entry and nothing else. A
  scan of a real legacy checkout WILL hit files that do not parse -- a
  half-migrated member, a JCL file with a .cbl extension, an EBCDIC
  artifact -- and a scan that aborts on the first one can never be run at
  all. Every failure lands in ``failures`` with its reason.

  EVERY PROGRAM UNIT IS REPORTED. A file holding several ``PROGRAM-ID``s
  parses into one outer program carrying the rest as contained programs,
  and every analyzer here is program-scoped. Reporting only the outermost
  unit would present a contained program as clean because nothing looked
  at it -- the same argument ``analysis/lint.py`` makes for linting every
  unit, and it is stronger here, because a portfolio table's whole job is
  to say which programs need attention.

  NOTHING IS SILENTLY OMITTED. A requested analyzer that raised on one
  unit is named in that unit's ``failed_analyzers``, with the rest of its
  reports intact. A caller can always tell "clean" from "not looked at".

All worker functions are module-level, never closures or lambdas, for the
same reason ``batch.py`` says so: Windows spawn has to pickle them.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cobolparser.plugins.core import DialectType, ErrorRecoveryMode

#: Bumped whenever the SHAPE of a scan document changes. A consumer (the
#: COBOL Analyzer extension's workspace analysis) reads this before trusting
#: any other key, so a newer CLI shipped under an older extension degrades
#: with a message rather than by misreading a renamed field.
SCAN_VERSION = 1

#: The analyzers ``scan`` can run, each keyed by its own subcommand name so
#: a scan's ``reports`` key and the equivalent single-file subcommand cannot
#: drift apart in a user's mind or in the docs.
ANALYZERS: tuple[str, ...] = (
    "health",
    "redundancy",
    "complexity",
    "dead-code",
    "unused-variables",
    "lineage",
)

#: What ``scan`` runs when the caller names nothing. ``health`` is the
#: composite grade a portfolio view sorts on; ``redundancy`` is the only
#: analyzer that reports per-paragraph fingerprints, which is what makes
#: clone detection across files possible at all. The other three are
#: available but off by default: each is already summarized inside
#: ``health``, and their full item lists multiply a scan's output size by
#: the size of the shop for information a portfolio view does not show.
DEFAULT_ANALYZERS: tuple[str, ...] = ("health", "redundancy")


@dataclass
class ScanOptions:
    """Everything that changes what a scan produces, in one picklable object.

    A dataclass rather than eight positional worker arguments because it
    crosses a process boundary: adding a knob to a tuple of positionals is
    how a worker signature and its call site drift on the one platform
    (Windows spawn) that nobody runs the test suite on.
    """

    analyzers: tuple[str, ...] = DEFAULT_ANALYZERS
    dialect: DialectType = DialectType.IBM_ENTERPRISE
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL
    copybook_paths: tuple[str, ...] = ()
    min_clone_statements: int = 3
    encoding: str = "utf-8"
    errors: str = "replace"
    free_form: bool = False
    #: ``parse_cobol``'s layout override: ``None`` auto-detects, ``True``
    #: forces fixed-format normalization, ``False`` disables it. The CLI's
    #: ``--source-format fixed|free`` (and ``source_format:`` in cobol.yml)
    #: land here; ``free_form`` alone is only the lexer-mode hint that
    #: auto-detection may still override.
    preprocess_fixed: bool | None = None
    #: ``parse_cobol``'s ``debug_lines``: compile ``D``-in-column-7 lines as
    #: code (CLI ``--debug-lines``, cobol.yml ``project.debug_lines``).
    debug_lines: bool = False


@dataclass
class UnitScan:
    """One program unit's reports."""

    program_name: str
    #: 0 for the outermost unit, 1 for a program contained in it, and so on.
    #: A portfolio row shows the outermost unit's name for the file and can
    #: indent the rest under it without re-deriving the nesting.
    depth: int
    reports: dict[str, Any] = field(default_factory=dict)
    #: Analyzers that raised on THIS unit, each with the exception text. The
    #: unit's other reports are still present.
    failed_analyzers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "program_name": self.program_name,
            "depth": self.depth,
            "reports": self.reports,
        }
        if self.failed_analyzers:
            out["failed_analyzers"] = self.failed_analyzers
        return out


@dataclass
class FileScan:
    """One source file's scan: its units, or why it has none."""

    path: str
    units: list[UnitScan] = field(default_factory=list)
    #: Why this file produced no units at all -- unreadable, unparseable, or
    #: parsed to nothing. ``None`` on success. A file with an error and no
    #: units is a `failure`; a file can never be both.
    error: str | None = None
    #: Parse errors the file survived (COLLECT_ALL recovered and carried on).
    #: A unit analyzed out of a partially-recovered AST is worth grading but
    #: worth labelling, so a low score is not read as certain.
    parse_error_count: int = 0
    #: Why copybook expansion failed, when the file fell back to its
    #: unexpanded parse. That parse can be error-free -- a COPY statement
    #: parses fine without its member -- so without this the report would be
    #: graded against a record layout it never saw, with nothing to say so.
    copybook_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": self.path}
        if self.error is not None:
            out["error"] = self.error
            return out
        out["units"] = [unit.to_dict() for unit in self.units]
        if self.parse_error_count:
            out["parse_error_count"] = self.parse_error_count
        if self.copybook_error is not None:
            out["copybook_error"] = self.copybook_error
        return out


@dataclass
class ScanReport:
    """Every file's scan, plus the accounting that proves none went missing."""

    options: ScanOptions = field(default_factory=ScanOptions)
    files: list[FileScan] = field(default_factory=list)

    @property
    def ok_files(self) -> list[FileScan]:
        return [f for f in self.files if f.error is None]

    @property
    def failed_files(self) -> list[FileScan]:
        return [f for f in self.files if f.error is not None]

    def to_dict(self) -> dict[str, Any]:
        ok = self.ok_files
        failed = self.failed_files
        return {
            "scan_version": SCAN_VERSION,
            "analyzers": list(self.options.analyzers),
            "min_clone_statements": self.options.min_clone_statements,
            "summary": {
                # file_count == scanned + failed, always. The identity is
                # the point: a consumer can prove the scan accounted for
                # every file it was handed rather than trusting a list
                # length.
                "file_count": len(self.files),
                "scanned_file_count": len(ok),
                "failed_file_count": len(failed),
                "program_unit_count": sum(len(f.units) for f in ok),
            },
            "files": [f.to_dict() for f in ok],
            "failures": [f.to_dict() for f in failed],
        }


# ---------------------------------------------------------------------------
# One analyzer over one program unit
# ---------------------------------------------------------------------------


def _run_analyzer(
    name: str,
    unit: Any,
    options: ScanOptions,
    source_map: dict[int, tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Run one analyzer over one already-parsed program unit.

    Imports are local to each branch for the reason the CLI's own
    subcommands do it: a scan asking only for ``health`` should not pay to
    import the DCLGEN checker's SQL machinery, and a worker process pays
    every import once per process.
    """
    if name == "health":
        from .analysis.technical_debt import TechnicalDebtAnalyzer

        return TechnicalDebtAnalyzer().analyze(unit).to_dict()

    if name == "redundancy":
        from .analysis.redundancy import RedundancyAnalyzer

        return (
            RedundancyAnalyzer()
            .analyze(unit, min_clone_statements=options.min_clone_statements)
            .to_dict()
        )

    if name == "complexity":
        from .analysis.complexity import ComplexityAnalyzer

        return ComplexityAnalyzer().analyze(unit).to_dict()

    if name == "dead-code":
        from .analysis.dead_code import DeadCodeAnalyzer

        return DeadCodeAnalyzer().analyze(unit).to_dict()

    if name == "unused-variables":
        from .analysis.unused_variables import UnusedVariableAnalyzer

        return UnusedVariableAnalyzer().analyze(unit).to_dict()

    if name == "lineage":
        from .analysis.field_lineage import FieldFlowAnalyzer, apply_source_map

        # Edges carry a bare "line", not a "location", so the generic
        # stamp_report_origins pass below does not reach them.
        return apply_source_map(FieldFlowAnalyzer().analyze(unit), source_map).to_dict()

    raise ValueError(f"unknown analyzer: {name}")


def _scan_unit(
    unit: Any,
    depth: int,
    options: ScanOptions,
    source_map: dict[int, tuple[str, int]] | None = None,
) -> UnitScan:
    """Every requested analyzer over one unit, each failing on its own."""
    scan = UnitScan(program_name=unit.program_name or "", depth=depth)
    for name in options.analyzers:
        try:
            scan.reports[name] = _run_analyzer(name, unit, options, source_map)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            # Deliberately broad. An analyzer that trips over an exotic
            # program must cost its own report and nothing else: the whole
            # value of a portfolio scan is that it completes over a real
            # checkout, and a `raise` here would let one pathological file
            # blank the other 4,999.
            scan.failed_analyzers[name] = f"{type(exc).__name__}: {exc}"
    return scan


# ---------------------------------------------------------------------------
# One file (this is what runs in a worker)
# ---------------------------------------------------------------------------


def _units_with_depth(program: Any, depth: int = 0) -> list[tuple[Any, int]]:
    """``program_units()``, but carrying each unit's nesting depth.

    ``CobolProgram.program_units()`` flattens the tree and drops the depth,
    which a portfolio view needs in order to show a contained program as
    contained rather than as a second top-level program in the same file.
    Re-derived here rather than changed there: that method's flat list is
    what every existing analyzer consumes.
    """
    out = [(program, depth)]
    for contained in program.contained_programs:
        out.extend(_units_with_depth(contained, depth + 1))
    return out


def scan_one(path: str, options: ScanOptions) -> FileScan:
    """Parse and analyze one file. Never raises -- see the module docstring."""
    try:
        source = Path(path).read_text(encoding=options.encoding, errors=options.errors)
    except (OSError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError under ``errors="strict"``: one
        # undecodable file must cost its own entry, not abort the whole scan
        # (the same guard batch.py's workers have).
        return FileScan(path=path, error=f"could not read: {exc}")

    expansion_failures: list[str] = []
    try:
        result = _parse(source, path, options, expansion_failures)
    except Exception as exc:  # noqa: BLE001
        return FileScan(path=path, error=f"{type(exc).__name__}: {exc}")

    if result.ast is None:
        first = result.errors[0] if result.errors else None
        return FileScan(
            path=path,
            error=f"could not be parsed: {first}" if first else "could not be parsed",
        )

    scan = FileScan(
        path=path,
        parse_error_count=len(result.errors),
        copybook_error=expansion_failures[0] if expansion_failures else None,
    )
    source_map = getattr(result, "expansion_source_map", None)
    for unit, depth in _units_with_depth(result.ast):
        unit_scan = _scan_unit(unit, depth, options, source_map)
        if source_map:
            # With copybooks expanded, every report location counts lines of
            # the expanded text -- past the first COPY it is not the line the
            # code sits on in *path*, and inside a member it is not in *path*
            # at all. Give each one the same "origin" lint findings carry.
            from .analysis.lint import stamp_report_origins

            stamp_report_origins(unit_scan.reports, source_map)
        scan.units.append(unit_scan)
    return scan


def _parse(
    source: str,
    path: str,
    options: ScanOptions,
    expansion_failures: list[str] | None = None,
) -> Any:
    """Parse *source*, expanding copybooks when the caller supplied paths.

    Copybook expansion is not merely a nicety for a scan: an unexpanded
    program's LINKAGE and WORKING-STORAGE are missing whatever its COPY
    members declare, so `unused-variables` (and therefore `health`'s
    redundancy component, and therefore the grade a portfolio table sorts
    on) would grade a program against a record layout it cannot see. When
    expansion fails the file is NOT dropped -- the unexpanded parse still
    grades the procedure division correctly -- but the reason is appended
    to *expansion_failures*, which ``scan_one`` reports as the file's
    ``copybook_error``. (``parse_error_count`` cannot carry it: the
    unexpanded parse is usually error-free.)
    """
    kwargs: dict[str, Any] = {
        "dialect": options.dialect,
        "error_recovery": options.error_recovery,
    }
    if options.free_form:
        kwargs["free_form"] = True
    if options.preprocess_fixed is not None:
        kwargs["preprocess_fixed"] = options.preprocess_fixed
    if options.debug_lines:
        kwargs["debug_lines"] = True

    if options.copybook_paths:
        from cobolparser.preprocess.copybook_expander import parse_cobol_with_expansion

        try:
            return parse_cobol_with_expansion(
                source,
                path,
                copybook_paths=list(options.copybook_paths),
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            # A missing or circular member must not cost the whole file its
            # report -- fall back to the unexpanded parse, which is exactly
            # what a scan with no copybook paths at all would have produced.
            # But say so: before 2026-09-28 this was a bare `pass`, and the
            # file's reports were indistinguishable from an expanded scan.
            if expansion_failures is not None:
                expansion_failures.append(f"{type(exc).__name__}: {exc}")

    from cobolparser.parser import parse_cobol

    return parse_cobol(source, filename=path, **kwargs)


def _scan_one_packed(args: tuple[str, ScanOptions]) -> FileScan:
    """``executor.map`` cannot take a lambda under Windows spawn."""
    return scan_one(*args)


# ---------------------------------------------------------------------------
# Many files
# ---------------------------------------------------------------------------


def scan_files(
    paths: Iterable[str | Path],
    options: ScanOptions | None = None,
    workers: int | None = None,
    executor: ProcessPoolExecutor | None = None,
) -> ScanReport:
    """Analyze many COBOL files in parallel.

    Args:
        paths: The files to scan, in the order they should be reported.
        options: What to run and how to parse. Defaults to
            :data:`DEFAULT_ANALYZERS` over IBM Enterprise fixed-format source.
        workers: Worker processes. ``None`` uses ``os.cpu_count()``. ``1``
            takes a sequential path with no pool at all, which is what makes
            this testable and debuggable (a traceback from a worker process
            is a pickled string; one from here is a stack).
        executor: A pre-created pool to reuse. The caller owns its lifecycle.

    Returns:
        A :class:`ScanReport` whose ``files`` are in the input order.

    Raises:
        ValueError: If *workers* is not >= 1, or an unknown analyzer is named.
    """
    if workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")

    opts = options or ScanOptions()
    unknown = [name for name in opts.analyzers if name not in ANALYZERS]
    if unknown:
        raise ValueError(
            f"unknown analyzer(s): {', '.join(unknown)}. "
            f"Known: {', '.join(ANALYZERS)}"
        )

    path_list = [str(p) for p in paths]
    if not path_list:
        return ScanReport(options=opts)

    args = [(p, opts) for p in path_list]
    resolved_workers = workers if workers is not None else (os.cpu_count() or 1)

    if executor is None and resolved_workers == 1:
        return ScanReport(options=opts, files=[scan_one(p, opts) for p in path_list])

    # Same chunking rule as batch.parse_files: enough chunks per worker that
    # one slow file cannot leave a core idle at the tail of the run.
    chunksize = max(1, len(path_list) // (resolved_workers * 4))

    if executor is not None:
        files = list(executor.map(_scan_one_packed, args, chunksize=chunksize))
        return ScanReport(options=opts, files=files)

    with ProcessPoolExecutor(max_workers=resolved_workers) as pool:
        files = list(pool.map(_scan_one_packed, args, chunksize=chunksize))
    return ScanReport(options=opts, files=files)


# ---------------------------------------------------------------------------
# Cross-file clone grouping
# ---------------------------------------------------------------------------


@dataclass
class CrossFileCloneMember:
    """One paragraph in a cross-file clone group."""

    path: str
    program_name: str
    paragraph: str
    line: int
    #: Where the paragraph really is when the scan expanded copybooks
    #: (``line`` then counts lines of the expanded text); ``None`` otherwise.
    origin_file: str | None = None
    origin_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "program_name": self.program_name,
            "paragraph": self.paragraph,
            "line": self.line,
        }
        if self.origin_file is not None and self.origin_line is not None:
            out["origin"] = {"file": self.origin_file, "line": self.origin_line}
        return out


@dataclass
class CrossFileCloneGroup:
    """Paragraphs sharing a structural fingerprint, across program units."""

    clone_type: str  # "TYPE_1" (exact) or "TYPE_2" (renamed identifiers)
    statement_count: int
    fingerprint: str
    members: list[CrossFileCloneMember] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        """Distinct files this group spans.

        The number that separates "one program repeats itself" (already
        reported per-program by ``RedundancyAnalyzer``) from "this paragraph
        was copy-pasted across the shop", which is the finding nobody can
        make by hand.
        """
        return len({m.path for m in self.members})

    def to_dict(self) -> dict[str, Any]:
        return {
            "clone_type": self.clone_type,
            "statement_count": self.statement_count,
            "fingerprint": self.fingerprint,
            "file_count": self.file_count,
            "members": [m.to_dict() for m in self.members],
        }


def cross_file_clone_groups(
    report: ScanReport, *, min_members: int = 2
) -> list[CrossFileCloneGroup]:
    """Group every scanned paragraph by fingerprint, across files.

    Requires the scan to have run the ``redundancy`` analyzer; a unit
    without that report contributes nothing (rather than being silently
    counted as clone-free).

    TYPE-1 WINS. A paragraph that landed in an exact-match group is not also
    offered as a renamed match -- the same precedence
    ``RedundancyAnalyzer._find_clone_groups`` applies within one program, for
    the same reason: reporting one duplicated paragraph twice, once under
    each type, would make the count meaningless.
    """
    exact: dict[str, list[CrossFileCloneMember]] = {}
    renamed: dict[str, list[CrossFileCloneMember]] = {}
    sizes: dict[str, int] = {}
    # Identity of a paragraph for the Type-1 exclusion below. Keyed on the
    # source position rather than the name: two units in one file may each
    # declare a paragraph of the same name, and they are different code.
    type1_claimed: set[tuple[str, str, int]] = set()

    for file_scan in report.ok_files:
        for unit in file_scan.units:
            redundancy = unit.reports.get("redundancy")
            if not isinstance(redundancy, dict):
                continue
            for entry in redundancy.get("paragraph_fingerprints", []):
                origin = entry.get("origin") or {}
                member = CrossFileCloneMember(
                    path=file_scan.path,
                    program_name=unit.program_name,
                    paragraph=entry.get("name", ""),
                    line=int((entry.get("location") or {}).get("line", 0)),
                    origin_file=origin.get("file"),
                    origin_line=origin.get("line"),
                )
                sizes.setdefault(
                    entry.get("type1", ""), int(entry.get("statement_count", 0))
                )
                sizes.setdefault(
                    entry.get("type2", ""), int(entry.get("statement_count", 0))
                )
                exact.setdefault(entry.get("type1", ""), []).append(member)
                renamed.setdefault(entry.get("type2", ""), []).append(member)

    groups: list[CrossFileCloneGroup] = []
    for digest, members in exact.items():
        if len(members) < min_members:
            continue
        for member in members:
            type1_claimed.add((member.path, member.program_name, member.line))
        groups.append(
            CrossFileCloneGroup(
                clone_type="TYPE_1",
                statement_count=sizes.get(digest, 0),
                fingerprint=digest,
                members=members,
            )
        )

    for digest, members in renamed.items():
        survivors = [
            m for m in members if (m.path, m.program_name, m.line) not in type1_claimed
        ]
        if len(survivors) < min_members:
            continue
        groups.append(
            CrossFileCloneGroup(
                clone_type="TYPE_2",
                statement_count=sizes.get(digest, 0),
                fingerprint=digest,
                members=survivors,
            )
        )

    # Most duplicated code first, measured the way RedundancyReport already
    # measures it: statements x members, each member's own share.
    #
    # NOT by file_count, which is the obvious choice and the wrong one. Every
    # shop's programs open with a near-identical four-statement
    # `0000-MAIN-PROCESS` scaffold, so ranking on spread puts that boilerplate
    # -- seven files, twenty-eight statements of nothing -- above a
    # sixteen-statement paragraph copy-pasted verbatim into two programs,
    # which is the finding the feature exists for. Measured on the
    # legacy-application corpus, where exactly that inversion showed up.
    #
    # An exact match breaks a tie against a renamed one: both describe the
    # same volume, but TYPE_1 is the one a reader can act on without first
    # checking what was renamed. The fingerprint breaks the remaining ties so
    # the order is stable across runs and across machines.
    groups.sort(
        key=lambda g: (
            -g.statement_count * len(g.members),
            -len(g.members),
            g.clone_type,
            g.fingerprint,
        )
    )
    return groups


def parse_analyzer_list(raw: Sequence[str] | None) -> tuple[str, ...]:
    """Turn ``--analyzer health,redundancy`` (repeatable) into a tuple.

    Accepts both the repeated-flag and the comma-separated spellings because
    both are in every user's fingers, and preserves first-seen order while
    dropping duplicates so ``--analyzer health --analyzer health`` does not
    run the analyzer twice.
    """
    if not raw:
        return DEFAULT_ANALYZERS
    seen: list[str] = []
    for item in raw:
        for name in item.split(","):
            cleaned = name.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
    return tuple(seen) if seen else DEFAULT_ANALYZERS
