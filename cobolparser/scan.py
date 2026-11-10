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
    "lint",
)

#: Analyzers that run once per *file* rather than once per unit: ``lint``
#: already covers every program unit in a file (a contained program left
#: unexamined would read as clean), so per unit it would report each
#: contained program's findings again. Their report is ``FileScan.reports``.
FILE_ANALYZERS: frozenset[str] = frozenset({"lint"})

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
    #: Source encoding: None detects it the way a copybook's is (#522).
    encoding: str | None = None
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
    #: Conditional-compilation symbols, as ``(name, value)`` pairs (CLI
    #: ``--define``, cobol.yml ``project.define``). Without them a scan
    #: analysed a different program than the single-file subcommands did:
    #: code under ``>>IF DBG DEFINED`` vanished and its PERFORM targets read
    #: as dead (#324).
    defined_symbols: tuple[tuple[str, str], ...] = ()
    #: A directory for :class:`~cobolparser._facts_cache.FactsCache`: a file
    #: whose source, copybooks and copybook directories are unchanged since
    #: a scan with the same options gets that scan's report back without
    #: being parsed. None (the default) caches nothing.
    cache_dir: str | None = None
    #: Per-file wall-clock limit, enforced by :func:`scan_files`: a file
    #: still being scanned after this many seconds has its worker process
    #: terminated and becomes a failure (``error="timed out after N s
    #: ..."``); the rest of the scan carries on. With it set every file runs
    #: in a worker process, even at ``workers=1``. :func:`scan_one` alone
    #: does not enforce it. None (the default) = no limit.
    timeout_seconds: float | None = None
    #: Files larger than this many bytes on disk are not read; each becomes
    #: a failure (``error="skipped: file is N bytes, ..."``). Checked by
    #: :func:`scan_one`, before the cache. None (the default) = no limit.
    max_file_bytes: int | None = None

    def cache_settings(self) -> tuple[Any, ...]:
        """Every option that changes a file's report (not the cache itself).

        The limits are left out: a file they stop is a failure, a failure
        is never cached, so they cannot change a stored report (and adding
        them did not invalidate caches written before they existed).
        """
        return tuple(
            (name, getattr(self, name))
            for name in self.__dataclass_fields__
            if name not in _NOT_CACHE_SETTINGS
        )


#: ``ScanOptions`` fields that never change a cached (successful) report.
_NOT_CACHE_SETTINGS = frozenset({"cache_dir", "timeout_seconds", "max_file_bytes"})


@dataclass
class UnitScan:
    """One program unit's reports."""

    program_name: str
    #: 0 for the outermost unit (and a stacked one), 1 for a program nested
    #: in it, and so on.
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitScan:
        return cls(
            program_name=data["program_name"],
            depth=int(data["depth"]),
            reports=dict(data.get("reports") or {}),
            failed_analyzers=dict(data.get("failed_analyzers") or {}),
        )


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
    #: Lossy-decode warnings: bytes of the source its encoding could not
    #: map, replaced with U+FFFD (#522). Serialized only when non-empty.
    decode_warnings: list[str] = field(default_factory=list)
    #: Reports of the :data:`FILE_ANALYZERS` that ran (``lint``: a
    #: ``LintReport.to_dict()``, every finding stamped with its on-disk
    #: ``origin``). Serialized only when non-empty.
    reports: dict[str, Any] = field(default_factory=dict)
    #: True when the report came from :attr:`ScanOptions.cache_dir` rather
    #: than a parse. Not serialized per file; counted in the summary.
    from_cache: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileScan:
        """The inverse of :meth:`to_dict`."""
        return cls(
            path=data["path"],
            units=[UnitScan.from_dict(u) for u in data.get("units") or []],
            error=data.get("error"),
            parse_error_count=int(data.get("parse_error_count") or 0),
            copybook_error=data.get("copybook_error"),
            decode_warnings=list(data.get("decode_warnings") or []),
            reports=dict(data.get("reports") or {}),
        )

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
        if self.decode_warnings:
            out["decode_warnings"] = list(self.decode_warnings)
        if self.reports:
            out["reports"] = dict(self.reports)
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
                **(
                    {"cached_file_count": sum(f.from_cache for f in self.files)}
                    if self.options.cache_dir
                    else {}
                ),
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
        if name in FILE_ANALYZERS:
            continue
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
    what every existing analyzer consumes. The depth is the *source*
    nesting (``CobolProgram.nesting_depth``), so a stacked program -- a
    separate compilation unit after the previous one's ``END PROGRAM`` --
    is at depth 0, not contained in the first program (#532).
    """
    out = [(program, depth)]
    for contained in program.contained_programs:
        nested = getattr(contained, "nesting_depth", None)
        out.extend(
            _units_with_depth(
                contained, depth + 1 if not isinstance(nested, int) else nested
            )
        )
    return out


def scan_one(path: str, options: ScanOptions) -> FileScan:
    """Parse and analyze one file. Never raises -- see the module docstring.

    With :attr:`ScanOptions.cache_dir`, a file nothing it depends on has
    changed in is answered from the cache, and a fresh report is stored.
    :attr:`ScanOptions.max_file_bytes` is checked first, so an oversize file
    is neither read nor served from the cache.
    """
    from ._file_limits import oversize_reason

    oversize = oversize_reason(path, options.max_file_bytes)
    if oversize is not None:
        return FileScan(path=path, error=oversize)
    if not options.cache_dir:
        return _scan_one(path, options)
    from ._facts_cache import FactsCache, directory_stamps, stamp

    cache = FactsCache(options.cache_dir, "scan", options.cache_settings())
    held = cache.get(path)
    if held is not None:
        try:
            cached = FileScan.from_dict(held)
        except (KeyError, TypeError, ValueError):
            pass
        else:
            cached.path = path
            cached.from_cache = True
            return cached
    own = stamp(path)
    sources: set[str] = set()
    scan = _scan_one(path, options, sources)
    if scan.error is None:
        stamps = {path: own, **{s: stamp(s) for s in sources if s != path}}
        stamps.update(directory_stamps(options.copybook_paths))
        cache.put(path, scan.to_dict(), stamps)
    return scan


def _scan_one(
    path: str, options: ScanOptions, sources: set[str] | None = None
) -> FileScan:
    """:func:`scan_one` without the cache. Adds every file the parse read
    (the program and the copybooks expanded into it) to *sources*."""
    from .preprocess import PreprocessingError
    from .preprocess.copybook_expander import read_program_source

    decode_warnings: list[str] = []
    try:
        source = read_program_source(
            path,
            options.encoding,
            warnings=decode_warnings,
            encoding_errors=options.errors,
        )
    except (OSError, ValueError, PreprocessingError) as exc:
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
        decode_warnings=decode_warnings,
    )
    source_map = getattr(result, "expansion_source_map", None)
    if sources is not None and source_map:
        sources.update(file for file, _ in source_map.values())
    if sources is not None:
        # A member that only COPYs another adds no line to the map (#763).
        sources.update(getattr(result, "expansion_copybooks", None) or [])
    for unit, depth in _units_with_depth(result.ast):
        unit_scan = _scan_unit(unit, depth, options, source_map)
        if source_map:
            # With copybooks expanded, every report location counts lines of
            # the expanded text -- past the first COPY it is not the line the
            # code sits on in *path*, and inside a member it is not in *path*
            # at all. Give each one the same "origin" lint findings carry.
            from .analysis.lint import stamp_report_origins

            stamp_report_origins(unit_scan.reports, source_map)
            _stamp_body_origins(unit_scan.reports.get("redundancy"), source_map)
        scan.units.append(unit_scan)
    if "lint" in options.analyzers:
        scan.reports["lint"] = _lint_file(path, result, options, source_map)
    return scan


def _lint_file(
    path: str,
    result: Any,
    options: ScanOptions,
    source_map: dict[int, tuple[str, int]] | None,
) -> dict[str, Any]:
    """The ``lint`` subcommand's report for one parse: every unit, the parse
    errors as findings, and each finding placed on disk (its file, line and
    editor column). A lint that raises is a failed rule, never a lost file."""
    from .analysis.lint import (
        LintAnalyzer,
        LintReport,
        add_line_length_findings,
        add_parse_errors,
        apply_source_map,
        source_column_offsets,
    )

    try:
        report = LintAnalyzer().analyze(result.ast)
        add_parse_errors(report, list(result.errors))
        if not source_map:
            source_map = {
                f.location.line: (path, f.location.line)
                for f in report.findings
                if f.location is not None
            }
        apply_source_map(
            report, source_map, source_column_offsets(path, options.preprocess_fixed)
        )
        # After the map: line-length findings are placed on disk already.
        add_line_length_findings(
            report,
            path,
            getattr(result, "expansion_source_map", None),
            options.preprocess_fixed,
            getattr(result, "expansion_copybooks", None) or (),
        )
    except Exception as exc:  # noqa: BLE001 -- see the module docstring
        report = LintReport(
            failed_rules=[{"rule": "lint", "error": f"{type(exc).__name__}: {exc}"}]
        )
    return report.to_dict()


def _stamp_body_origins(
    redundancy: Any, source_map: dict[int, tuple[str, int]]
) -> None:
    """Give each paragraph fingerprint whose whole body comes from one file a
    ``body_origin``: that file and the line its first statement is on there.

    Every expanded line of the body's span must map to the same file, so a
    body that mixes a copybook with the program's own statements gets none
    (those statements are the program's text, duplicated or not). The
    header's ``origin`` cannot answer this: a program that writes the header
    itself and copies in only the body has its own header line there (#470).
    """
    if not isinstance(redundancy, dict):
        return
    for entry in redundancy.get("paragraph_fingerprints", []):
        span = entry.get("body_lines")
        if not isinstance(span, list) or len(span) != 2:
            continue
        first, last = int(span[0]), int(span[1])
        origins = [source_map.get(line) for line in range(first, last + 1)]
        start = origins[0]
        if start is None or any(o is None or o[0] != start[0] for o in origins):
            continue
        entry["body_origin"] = {"file": start[0], "line": start[1]}


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
    defines = dict(options.defined_symbols)

    if options.copybook_paths:
        from cobolparser.parser import parse_cobol_with_expansion

        try:
            return parse_cobol_with_expansion(
                source,
                path,
                copybook_paths=list(options.copybook_paths),
                # The expander evaluates the directives itself, so the
                # symbols reach the members COPYd under them too.
                defined_symbols=defines or None,
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

    if not defines:
        return parse_cobol(source, filename=path, **kwargs)

    # parse_cobol takes no symbols; evaluate the directives first, as the
    # CLI's single-file path does, keeping >>SOURCE FORMAT for the parser's
    # own normalization.
    from cobolparser.preprocess import preprocess_conditional_compilation

    conditional_warnings: list[str] = []
    source = preprocess_conditional_compilation(
        source,
        defines,
        warnings=conditional_warnings,
        keep_source_format_directives=True,
    )
    result = parse_cobol(source, filename=path, **kwargs)
    result.warnings[:0] = conditional_warnings
    return result


def _scan_one_packed(args: tuple[str, ScanOptions]) -> FileScan:
    """``executor.map`` cannot take a lambda under Windows spawn."""
    return scan_one(*args)


def _warm_scan_worker(options: ScanOptions) -> None:
    """A per-file-timeout worker's warm-up: parse a tiny program and run
    the requested analyzers on it, so their lazy imports and first-use
    set-up are not charged to the first real file's deadline."""
    from .batch import _WARMUP_PROGRAM

    result = _parse(_WARMUP_PROGRAM, "<warm-up>", options)
    if result.ast is None:
        return
    for unit, depth in _units_with_depth(result.ast):
        _scan_unit(unit, depth, options)
    if "lint" in options.analyzers:
        from .analysis import lint  # noqa: F401


def _scan_limit_failure(path_list: list[str]) -> Any:
    """``run_with_timeouts``' *failure* callback: the file's ``error``."""

    def failure(index: int, reason: str) -> FileScan:
        return FileScan(path=path_list[index], error=reason)

    return failure


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
            is a pickled string; one from here is a stack) -- unless
            :attr:`ScanOptions.timeout_seconds` is set, which runs every
            file in one of *workers* worker processes it can terminate.
        executor: A pre-created pool to reuse. The caller owns its lifecycle.
            Cannot be combined with :attr:`ScanOptions.timeout_seconds`.

    Returns:
        A :class:`ScanReport` whose ``files`` are in the input order.

    Raises:
        ValueError: If *workers* is not >= 1, an unknown analyzer is named, a
            limit is not positive, or a timeout is combined with *executor*.
    """
    from ._file_limits import run_with_timeouts, validate_limits

    if workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")

    opts = options or ScanOptions()
    validate_limits(opts.timeout_seconds, opts.max_file_bytes)
    if opts.timeout_seconds is not None and executor is not None:
        raise ValueError(
            "ScanOptions.timeout_seconds cannot be combined with executor: a "
            "worker of a caller-owned pool cannot be terminated without "
            "breaking the pool"
        )
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

    if opts.timeout_seconds is not None:
        files = run_with_timeouts(
            scan_one,
            args,
            timeout_seconds=opts.timeout_seconds,
            workers=resolved_workers,
            failure=_scan_limit_failure(path_list),
            warmup=_warm_scan_worker,
            warmup_args=(opts,),
        )
        return ScanReport(options=opts, files=files)

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
    #: Where the paragraph's statements really are, when every one of them
    #: comes from one file (``body_origin`` on the fingerprint); ``None``
    #: otherwise or without expansion.
    body_origin_file: str | None = None
    body_origin_line: int | None = None

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

    @property
    def source_key(self) -> tuple[str, int]:
        """Where this paragraph's text actually lives on disk.

        The copybook position when the paragraph was expanded from one, else
        its own position in the scanned file. Two members with the same key
        are one piece of source included twice, not two copies of it (#352).
        The body's position wins over the header's: a program that writes
        the header and copies in only the statements shares them all the
        same (#470).
        """
        if self.body_origin_file is not None and self.body_origin_line is not None:
            return (self.body_origin_file, int(self.body_origin_line))
        if self.origin_file is not None and self.origin_line is not None:
            return (self.origin_file, int(self.origin_line))
        return (self.path, self.line)


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

    @property
    def source_count(self) -> int:
        """Distinct on-disk copies of the paragraph among the members.

        Lower than ``len(members)`` when some members are the same copybook
        paragraph included by several programs: those inclusions share one
        source, so they count once. This, not the member count, is how many
        copies there are to keep in step, and what grouping and ranking use.
        """
        return len({m.source_key for m in self.members})

    def to_dict(self) -> dict[str, Any]:
        return {
            "clone_type": self.clone_type,
            "statement_count": self.statement_count,
            "fingerprint": self.fingerprint,
            "file_count": self.file_count,
            "source_count": self.source_count,
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

    ONE SOURCE, ONE COPY. *min_members* counts distinct on-disk sources
    (``CrossFileCloneMember.source_key``), not members: a PROCEDURE DIVISION
    copybook paragraph included by every program is shared code, not
    copy-paste, and on its own forms no group (#352). Its inclusions still
    appear as members of a group that has another real copy, so a reader
    sees every program the duplicated text reaches.
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
                body_origin = entry.get("body_origin") or {}
                member = CrossFileCloneMember(
                    path=file_scan.path,
                    program_name=unit.program_name,
                    paragraph=entry.get("name", ""),
                    line=int((entry.get("location") or {}).get("line", 0)),
                    origin_file=origin.get("file"),
                    origin_line=origin.get("line"),
                    body_origin_file=body_origin.get("file"),
                    body_origin_line=body_origin.get("line"),
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

    def distinct_sources(members: list[CrossFileCloneMember]) -> int:
        return len({m.source_key for m in members})

    for digest, members in exact.items():
        if distinct_sources(members) < min_members:
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
        if distinct_sources(survivors) < min_members:
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
    # measures it: statements x copies, each copy's own share. A copy is a
    # distinct source, not a member: one copybook included by three hundred
    # programs is three hundred members and one copy, and ranking on members
    # would put the shop's shared error handler on top of every scan (#352).
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
            -g.statement_count * g.source_count,
            -g.source_count,
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
