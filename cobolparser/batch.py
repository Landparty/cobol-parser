"""Batch COBOL parsing using ProcessPoolExecutor.

Provides parse_files() for parsing 500-5000 COBOL files in parallel.
File I/O happens inside workers to avoid pickling large strings.
All worker functions are module-level (not lambdas/closures) for
Windows spawn-based pickling compatibility.

Also provides parse_files_with_copybooks() for efficient batch parsing
when copybook expansion is needed — uses a shared file content cache
to avoid redundant I/O when the same copybook is referenced by many programs.

Executor reuse example (avoids spawn overhead on large repeated batches)::

    from concurrent.futures import ProcessPoolExecutor
    from cobolparser.batch import parse_files

    with ProcessPoolExecutor(max_workers=4) as executor:
        batch1 = parse_files(files1, executor=executor)
        batch2 = parse_files(files2, executor=executor)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cobolparser._file_limits import (
    oversize_reason,
    run_with_timeouts,
    validate_limits,
)
from cobolparser.parser import CobolParser, ParseResult, parse_cobol
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode
from cobolparser.preprocess import PreprocessingError
from cobolparser.preprocess.copybook_expander import read_program_source
from cobolparser.profiling import ProfilingResult

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result for a single file in a batch parse run."""

    path: Path
    result: ParseResult | None
    read_error: str | None  # str(exc) — always pickle-safe on Windows spawn
    profiling: ProfilingResult | None = None
    #: ``parse_files_with_copybooks`` only: why copybook expansion failed for
    #: this file, which was then parsed unexpanded (``"<ExcType>: <message>"``).
    #: ``None`` when expansion succeeded or was never attempted.
    copybook_error: str | None = None


# Module-level reusable parser for sequential fast-path
_REUSABLE_PARSER: CobolParser | None = None


def _get_reusable_parser(
    error_recovery: ErrorRecoveryMode, dialect: DialectType, debug_lines: bool = False
) -> CobolParser:
    """Get or create a reusable parser instance (avoids re-registering parsers)."""
    global _REUSABLE_PARSER
    if (
        _REUSABLE_PARSER is None
        or _REUSABLE_PARSER.error_recovery != error_recovery
        or _REUSABLE_PARSER.dialect != dialect
        or _REUSABLE_PARSER.debug_lines != debug_lines
    ):
        _REUSABLE_PARSER = CobolParser(
            error_recovery=error_recovery, dialect=dialect, debug_lines=debug_lines
        )
    return _REUSABLE_PARSER


def _prof_file_names(path_list: list[str]) -> list[str]:
    """One ``.prof`` basename per input path, unique within the batch.

    Each file's profile is ``<stem>.prof``; when two inputs share a stem
    (``a/PROG.cbl`` and ``b/PROG.cbl``, or ``PROG.cbl`` and ``PROG.cob``) the
    later ones get ``<stem>-2.prof``, ``<stem>-3.prof``, ... instead of all
    writing -- and silently overwriting -- the same file.
    """
    used: set[str] = set()
    names: list[str] = []
    for path_str in path_list:
        stem = Path(path_str).stem
        name = stem + ".prof"
        n = 2
        while name.lower() in used:
            name = f"{stem}-{n}.prof"
            n += 1
        used.add(name.lower())
        names.append(name)
    return names


def _read_program(
    path_str: str, encoding: str | None, errors: str, warnings: list[str]
) -> str:
    """One program's text, decoded the way a copybook is (#522): the
    encoding detected unless named, a lossy decode noted in *warnings*."""
    return read_program_source(
        path_str, encoding, warnings=warnings, encoding_errors=errors
    )


def _with_decode_warnings(batch: BatchResult, warnings: list[str]) -> BatchResult:
    """Put a lossy-decode warning on the parse result, where a caller looks."""
    if batch.result is not None:
        for warning in warnings:
            if warning not in batch.result.warnings:
                batch.result.warnings.append(warning)
    return batch


def _parse_one(
    path_str: str,
    encoding: str | None,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool,
    top_n: int,
    prof_output_dir: str | None,
    prof_name: str | None = None,
    debug_lines: bool = False,
    max_file_bytes: int | None = None,
) -> BatchResult:
    """Read one file and parse it.

    Module-level (not a closure) for pickling on Windows spawn.
    Note: parse_cobol default is FAIL_FAST; we always pass error_recovery explicitly.
    """
    path = Path(path_str)
    oversize = oversize_reason(path_str, max_file_bytes)
    if oversize is not None:
        return BatchResult(path=path, result=None, read_error=oversize)
    decode_warnings: list[str] = []
    try:
        source = _read_program(path_str, encoding, errors, decode_warnings)
    except (OSError, ValueError, PreprocessingError) as exc:
        # ValueError covers UnicodeDecodeError under errors="strict" — before
        # this, a single undecodable file aborted the entire batch instead of
        # becoming a per-file failure.
        return BatchResult(path=path, result=None, read_error=str(exc))

    try:
        if not enable_profiling:
            result = parse_cobol(
                source,
                filename=path_str,
                error_recovery=error_recovery,
                dialect=dialect,
                debug_lines=debug_lines,
            )
            return _with_decode_warnings(
                BatchResult(path=path, result=result, read_error=None),
                decode_warnings,
            )

        prof_output: str | None = None
        if prof_output_dir is not None:
            prof_output = str(
                Path(prof_output_dir) / (prof_name or Path(path_str).stem + ".prof")
            )

        parse_result, prof = parse_cobol(
            source,
            filename=path_str,
            error_recovery=error_recovery,
            dialect=dialect,
            debug_lines=debug_lines,
            enable_profiling=True,
            top_n=top_n,
            prof_output=prof_output,
        )
        return _with_decode_warnings(
            BatchResult(
                path=path, result=parse_result, read_error=None, profiling=prof
            ),
            decode_warnings,
        )
    except Exception as exc:  # noqa: BLE001 — one poisoned file must not
        # abort the batch; the exception is recorded per-file instead.
        return BatchResult(
            path=path,
            result=None,
            read_error=f"parse error: {type(exc).__name__}: {exc}",
        )


def _parse_one_reuse(
    path_str: str,
    encoding: str | None,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool,
    top_n: int,
    prof_output_dir: str | None,
    prof_name: str | None = None,
    debug_lines: bool = False,
    max_file_bytes: int | None = None,
) -> BatchResult:
    """Parse one file reusing a module-level parser (one process at a time:
    the sequential path, or a per-file-timeout worker).

    Avoids re-creating CobolParser and re-registering division parsers for each file.
    """
    path = Path(path_str)
    oversize = oversize_reason(path_str, max_file_bytes)
    if oversize is not None:
        return BatchResult(path=path, result=None, read_error=oversize)
    decode_warnings: list[str] = []
    try:
        source = _read_program(path_str, encoding, errors, decode_warnings)
    except (OSError, ValueError, PreprocessingError) as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))

    try:
        parser = _get_reusable_parser(error_recovery, dialect, debug_lines)

        if not enable_profiling:
            result = parser.parse(
                source, filename=path_str, error_recovery=error_recovery
            )
            return _with_decode_warnings(
                BatchResult(path=path, result=result, read_error=None),
                decode_warnings,
            )

        prof_output: str | None = None
        if prof_output_dir is not None:
            prof_output = str(
                Path(prof_output_dir) / (prof_name or Path(path_str).stem + ".prof")
            )

        parse_result, prof = parser.parse(
            source,
            filename=path_str,
            error_recovery=error_recovery,
            enable_profiling=True,
            top_n=top_n,
            prof_output=prof_output,
        )
        return _with_decode_warnings(
            BatchResult(
                path=path, result=parse_result, read_error=None, profiling=prof
            ),
            decode_warnings,
        )
    except Exception as exc:  # noqa: BLE001 — record per-file, don't abort batch
        return BatchResult(
            path=path,
            result=None,
            read_error=f"parse error: {type(exc).__name__}: {exc}",
        )


def _parse_one_packed(args: tuple) -> BatchResult:
    """Unpack args tuple and call _parse_one.

    executor.map cannot use a lambda (not picklable on Windows spawn).
    This module-level wrapper is the correct pattern.
    """
    return _parse_one(*args)


#: A program small enough to parse in milliseconds: what a per-file-timeout
#: worker parses once before taking work, so the parser's first-use set-up
#: and lazy imports are not charged to the first real file's deadline.
_WARMUP_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WARMUP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(4).
       PROCEDURE DIVISION.
           MOVE 'A' TO WS-A.
           STOP RUN.
"""


def _warm_parser(
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    debug_lines: bool,
    copybooks: bool = False,
) -> None:
    """A timeout worker's warm-up: build and exercise the reused parser."""
    _get_reusable_parser(error_recovery, dialect, debug_lines).parse(
        _WARMUP_PROGRAM, filename="<warm-up>", error_recovery=error_recovery
    )
    if copybooks:
        from cobolparser.preprocess.copybook_expander import (  # noqa: F401
            expand_copybooks,
        )


def _limit_failure(path_list: list[str]) -> Any:
    """``run_with_timeouts``' *failure* callback: a ``BatchResult`` whose
    ``read_error`` is the reason (a timeout, or a worker that died)."""

    def failure(index: int, reason: str) -> BatchResult:
        return BatchResult(path=Path(path_list[index]), result=None, read_error=reason)

    return failure


def parse_files(
    paths: Iterable[str | Path],
    workers: int | None = None,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL,
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    encoding: str | None = None,
    errors: str = "replace",
    executor: ProcessPoolExecutor | None = None,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
    debug_lines: bool = False,
    timeout_seconds: float | None = None,
    max_file_bytes: int | None = None,
) -> list[BatchResult]:
    """Parse multiple COBOL files in parallel.

    Args:
        paths: File paths to parse.
        workers: Worker processes. None → os.cpu_count() (or 1). Must be >= 1.
            Ignored when *executor* is provided.
        error_recovery: Passed to parse_cobol for each file.
        dialect: COBOL dialect, passed to parse_cobol for each file.
        encoding: Source encoding. None (the default) detects it the way a
            copybook's is detected; name one to override (#522).
        errors: 'replace' (default) substitutes U+FFFD for undecodable bytes
            and adds a warning to the result; 'strict' makes such a file a
            read error.
        executor: Optional pre-created ProcessPoolExecutor to reuse.  When
            provided the caller owns the executor lifecycle (shutdown/cleanup).
            Useful for amortising spawn overhead across many consecutive batches.
        enable_profiling: When True, attach a ProfilingResult to each BatchResult.
        top_n: Number of top functions to include in each ProfilingResult.
        prof_output: Directory path to write per-file .prof binaries. Each file
            is written as <stem>.prof inside this directory (<stem>-2.prof,
            ... for a later file sharing a stem). Must not end with ".prof"
            (that would be a file path, not a directory).
        debug_lines: ``parse_cobol``'s ``debug_lines``: compile fixed-format
            debugging lines (``D`` in column 7) as code for every file.
        timeout_seconds: Per-file wall-clock limit. A file still parsing
            after this long has its worker process terminated and comes
            back with ``read_error="timed out after N s ..."``; the rest of
            the batch carries on. Every file then runs in one of *workers*
            worker processes (even ``workers=1``: a thread cannot be
            stopped). Cannot be combined with *executor*. None = no limit.
        max_file_bytes: Files larger than this on disk are not read; they
            come back with ``read_error="skipped: file is N bytes, ..."``.
            None = no limit.

    Returns:
        list[BatchResult] in input order.

    Raises:
        ValueError: If workers <= 0, prof_output ends with ".prof", a limit
            is not positive, or *timeout_seconds* is given with *executor*.
    """
    if workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")
    validate_limits(timeout_seconds, max_file_bytes)
    if timeout_seconds is not None and executor is not None:
        raise ValueError(
            "timeout_seconds cannot be combined with executor: a worker of a "
            "caller-owned pool cannot be terminated without breaking the pool"
        )

    if prof_output is not None and prof_output.endswith(".prof"):
        raise ValueError(
            "prof_output in batch mode must be a directory path, not a .prof file. "
            "Each file will be written as <stem>.prof inside that directory."
        )
    if enable_profiling and prof_output is not None:
        os.makedirs(prof_output, exist_ok=True)

    path_list = [str(p) for p in paths]

    if not path_list:
        return []

    resolved_workers = workers if workers is not None else (os.cpu_count() or 1)
    args = [
        (
            p,
            encoding,
            errors,
            error_recovery,
            dialect,
            enable_profiling,
            top_n,
            prof_output,
            prof_name,
            debug_lines,
            max_file_bytes,
        )
        for p, prof_name in zip(path_list, _prof_file_names(path_list), strict=True)
    ]

    if timeout_seconds is not None:
        # Long-lived worker processes, one file at a time each, so the
        # module-level reused parser is safe (and saves re-registration).
        return run_with_timeouts(
            _parse_one_reuse,
            args,
            timeout_seconds=timeout_seconds,
            workers=resolved_workers,
            failure=_limit_failure(path_list),
            warmup=_warm_parser,
            warmup_args=(error_recovery, dialect, debug_lines),
        )

    if executor is None and resolved_workers == 1:
        # Sequential fast path: reuse parser instance, clean stack traces, no pickle overhead
        return [_parse_one_reuse(*a) for a in args]

    chunksize = max(1, len(path_list) // (resolved_workers * 4))

    if executor is not None:
        # Caller-managed executor: use it directly without a context manager
        results = list(executor.map(_parse_one_packed, args, chunksize=chunksize))
        return results

    with ProcessPoolExecutor(max_workers=resolved_workers) as pool:
        results = list(pool.map(_parse_one_packed, args, chunksize=chunksize))
    return results


def _attach_expansion(
    result: ParseResult,
    warnings: list[str],
    source_map: dict[int, tuple[str, int]] | None,
) -> None:
    """Carry an expansion's warnings and source map onto its ParseResult.

    The same two things ``parse_cobol_with_expansion`` attaches, so a batch
    result and a single-file one cannot disagree about where a line came from.
    """
    for warning in warnings:
        if warning not in result.warnings:
            result.warnings.append(warning)
    result.expansion_source_map = source_map


def _attach_expansion_debug_lines(
    result: ParseResult, expansion: Any, filename: str
) -> None:
    """The dropped-debugging-lines warning the expansion hid from the parser."""
    if expansion is None:
        return
    from cobolparser.preprocess.copybook_expander import warn_dropped_debug_lines

    warn_dropped_debug_lines(result, expansion, filename)


@dataclass(frozen=True)
class _CopybookJob:
    """Everything one ``parse_files_with_copybooks`` file needs besides its
    path: one picklable object, so a timeout worker gets the same settings
    the in-process loop uses (and a hashable key for its per-process state).
    """

    copybook_paths: tuple[str, ...]
    error_recovery: ErrorRecoveryMode
    dialect: DialectType
    encoding: str | None
    errors: str
    max_nesting_depth: int
    copybook_cache_size: int
    enable_profiling: bool
    top_n: int
    prof_output: str | None
    debug_lines: bool
    max_file_bytes: int | None


@dataclass
class _CopybookState:
    """What every file of one run shares: the path resolver (resolution and
    directory-index caches) and the parser (registered once)."""

    path_resolver: Any
    parser: CobolParser


def _new_copybook_state(job: _CopybookJob) -> _CopybookState:
    from cobolparser.preprocess.models import CopybookSearchPath
    from cobolparser.preprocess.path_resolver import PathResolver

    search_config = CopybookSearchPath(
        directories=list(job.copybook_paths),
        max_nesting_depth=job.max_nesting_depth,
        max_cache_entries=job.copybook_cache_size,
    )
    return _CopybookState(
        path_resolver=PathResolver(search_config),
        parser=CobolParser(
            error_recovery=job.error_recovery,
            dialect=job.dialect,
            debug_lines=job.debug_lines,
        ),
    )


#: A timeout worker's shared state for the run it serves. A worker lives
#: for one ``parse_files_with_copybooks`` call, so this is as fresh as the
#: in-process loop's state; keyed by the job in case that ever changes.
_WORKER_COPYBOOK_STATE: tuple[_CopybookJob, _CopybookState] | None = None


def _worker_copybook_state(job: _CopybookJob) -> _CopybookState:
    global _WORKER_COPYBOOK_STATE
    if _WORKER_COPYBOOK_STATE is None or _WORKER_COPYBOOK_STATE[0] != job:
        _WORKER_COPYBOOK_STATE = (job, _new_copybook_state(job))
    return _WORKER_COPYBOOK_STATE[1]


def _warm_copybook_worker(job: _CopybookJob) -> None:
    """A timeout worker's warm-up: build the shared state, parse once."""
    state = _worker_copybook_state(job)
    state.parser.parse(
        _WARMUP_PROGRAM, filename="<warm-up>", error_recovery=job.error_recovery
    )
    from cobolparser.preprocess.copybook_expander import (  # noqa: F401
        expand_copybooks,
    )


def _parse_one_with_copybooks(
    path_str: str,
    prof_name: str,
    job: _CopybookJob,
    state: _CopybookState | None = None,
) -> BatchResult:
    """One file of ``parse_files_with_copybooks``: read, expand, parse.

    *state* is the run's shared resolver and parser; ``None`` (in a timeout
    worker) uses the worker's own. Never raises.
    """
    from cobolparser.preprocess.copybook_expander import expand_copybooks

    if state is None:
        state = _worker_copybook_state(job)
    path = Path(path_str)
    oversize = oversize_reason(path_str, job.max_file_bytes)
    if oversize is not None:
        return BatchResult(path=path, result=None, read_error=oversize)
    decode_warnings: list[str] = []
    try:
        source = _read_program(path_str, job.encoding, job.errors, decode_warnings)
    except (OSError, ValueError, PreprocessingError) as exc:
        # ValueError covers UnicodeDecodeError under errors="strict".
        return BatchResult(path=path, result=None, read_error=str(exc))

    # Expand copybooks with shared cache, the way parse_cobol_with_expansion
    # does (#255): the source map and the expansion warnings reach the
    # result, so the two entry points cannot disagree about a line.
    expansion_warnings: list[str] = []
    source_map: dict[int, tuple[str, int]] | None = None
    copybook_error: str | None = None
    expansion: Any = None
    try:
        expansion = expand_copybooks(
            source_code=source,
            copybook_paths=list(job.copybook_paths),
            max_nesting_depth=job.max_nesting_depth,
            validate_content=False,  # Skip validation for speed in batch mode
            path_resolver=state.path_resolver,
            # Directives decide which COPY statements exist: one inside an
            # excluded >>IF must not be resolved (parse_cobol_with_expansion
            # does the same). The parser's own directive pass would
            # otherwise run only after the fact.
            process_conditionals=True,
            preserve_source_locations=True,
            source_file=path_str,
            debug_lines=job.debug_lines,
        )
        expanded_source = expansion.expanded_source
        expansion_warnings = decode_warnings + list(
            getattr(expansion.statistics, "warnings", []) or []
        )
        source_map = getattr(expansion, "source_location_map", None)
    except Exception as exc:
        # Copybook expansion is best-effort in batch mode: a single bad
        # COPY must not abort the whole run, so we fall back to parsing the
        # raw source (codebase-graph relies on the unexpanded parse for a
        # file's CALL edges). Every COPY in the file goes unexpanded, not
        # just the bad one, so the reason must reach the caller: it is kept
        # as BatchResult.copybook_error and as a warning on the result,
        # not only logged (#255).
        logger.warning(
            "Copybook expansion failed for %s; parsing without expansion: %r",
            path_str,
            exc,
            exc_info=True,
        )
        copybook_error = f"{type(exc).__name__}: {exc}"
        expansion_warnings = decode_warnings + [
            f"copybook expansion failed ({copybook_error}); "
            "the file was parsed without expanding any COPY statement"
        ]
        expanded_source = source

    # Parse expanded source reusing the parser instance. Guarded the same
    # way as _parse_one/_parse_one_reuse: one poisoned file must not abort
    # the whole batch, so a parse-time exception is recorded per-file
    # instead of propagating out of the function.
    parser = state.parser
    try:
        if not job.enable_profiling:
            result = parser.parse(
                expanded_source, filename=path_str, error_recovery=job.error_recovery
            )
            _attach_expansion(result, expansion_warnings, source_map)
            _attach_expansion_debug_lines(result, expansion, path_str)
            return BatchResult(
                path=path,
                result=result,
                read_error=None,
                copybook_error=copybook_error,
            )
        prof_file: str | None = None
        if job.prof_output is not None:
            prof_file = str(Path(job.prof_output) / prof_name)
        parse_result, prof = parser.parse(
            expanded_source,
            filename=path_str,
            error_recovery=job.error_recovery,
            enable_profiling=True,
            top_n=job.top_n,
            prof_output=prof_file,
        )
        _attach_expansion(parse_result, expansion_warnings, source_map)
        _attach_expansion_debug_lines(parse_result, expansion, path_str)
        return BatchResult(
            path=path,
            result=parse_result,
            read_error=None,
            profiling=prof,
            copybook_error=copybook_error,
        )
    except Exception as exc:  # noqa: BLE001 — record per-file, don't abort batch
        return BatchResult(
            path=path,
            result=None,
            read_error=f"parse error: {type(exc).__name__}: {exc}",
        )


def parse_files_with_copybooks(
    paths: Iterable[str | Path],
    copybook_paths: list[str],
    workers: int | None = None,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL,
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    encoding: str | None = None,
    errors: str = "replace",
    max_nesting_depth: int = 100,
    copybook_cache_size: int = 1024,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
    debug_lines: bool = False,
    timeout_seconds: float | None = None,
    max_file_bytes: int | None = None,
) -> list[BatchResult]:
    """Parse multiple COBOL files with shared copybook path resolution.

    Optimized for large batch scenarios (3000+ programs, 50+ copybooks each)
    where many programs reference the same copybooks. A single ``PathResolver``
    (with its resolution and directory-index caches) is reused across every
    file, and copybook file reads go through the module-level LRU file cache
    in ``cobolparser.preprocess.copybook_expander``, so repeated lookups of
    the same copybooks avoid redundant filesystem work.

    This function runs sequentially in the main process to maximize cache hits.
    For CPU-bound scenarios where copybook expansion is minimal, use parse_files()
    with a ProcessPoolExecutor instead.

    Args:
        paths: File paths to parse.
        copybook_paths: Directories to search for copybook files.
        workers: Unused without *timeout_seconds* (reserved for future
            parallel copybook expansion). With it, the number of worker
            processes (None -> 1, so the caches stay shared).
        error_recovery: Passed to parser for each file.
        dialect: COBOL dialect, passed to parser for each file.
        encoding: Source encoding; None (default) detects it (#522).
        errors: 'replace' (default, lossy decode warned) or 'strict'.
        max_nesting_depth: Maximum copybook nesting depth.
        copybook_cache_size: Maximum entries in the shared expansion cache.
        enable_profiling: When True, attach a ProfilingResult to each BatchResult.
        top_n: Number of top functions to include in each ProfilingResult.
        prof_output: Directory path to write per-file .prof binaries.
        debug_lines: Compile fixed-format debugging lines (``D`` in column 7)
            as code, through both the copybook expansion and the parse.
        timeout_seconds: Per-file wall-clock limit (expansion plus parse). A
            file that overruns has its worker process terminated and comes
            back with ``read_error="timed out after N s ..."``; the rest
            carry on. The files then run in worker processes (each keeps its
            own resolver and parser for the run). None = no limit.
        max_file_bytes: Programs larger than this on disk are not read (a
            ``read_error`` starting ``"skipped:"``). Copybooks are not
            checked. None = no limit.

    Returns:
        list[BatchResult] in input order.
    """
    validate_limits(timeout_seconds, max_file_bytes)
    if timeout_seconds is not None and workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")
    if prof_output is not None and prof_output.endswith(".prof"):
        raise ValueError(
            "prof_output in batch mode must be a directory path, not a .prof file. "
            "Each file will be written as <stem>.prof inside that directory."
        )
    if enable_profiling and prof_output is not None:
        os.makedirs(prof_output, exist_ok=True)

    path_list = [str(p) for p in paths]
    if not path_list:
        return []

    job = _CopybookJob(
        copybook_paths=tuple(copybook_paths),
        error_recovery=error_recovery,
        dialect=dialect,
        encoding=encoding,
        errors=errors,
        max_nesting_depth=max_nesting_depth,
        copybook_cache_size=copybook_cache_size,
        enable_profiling=enable_profiling,
        top_n=top_n,
        prof_output=prof_output,
        debug_lines=debug_lines,
        max_file_bytes=max_file_bytes,
    )
    prof_names = _prof_file_names(path_list)

    if timeout_seconds is not None:
        return run_with_timeouts(
            _parse_one_with_copybooks,
            [(p, n, job) for p, n in zip(path_list, prof_names, strict=True)],
            timeout_seconds=timeout_seconds,
            workers=workers or 1,
            failure=_limit_failure(path_list),
            warmup=_warm_copybook_worker,
            warmup_args=(job,),
        )

    # In-process: one resolver (shared caches) and one parser (registered
    # once) for every file of this call.
    state = _new_copybook_state(job)
    return [
        _parse_one_with_copybooks(p, n, job, state)
        for p, n in zip(path_list, prof_names, strict=True)
    ]
