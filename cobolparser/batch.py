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

import os
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from cobolparser.cache import ParseCache, make_cache_key, make_config_fingerprint
from cobolparser.parser import CobolParser, ParseResult, parse_cobol
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode
from cobolparser.profiling import ProfilingResult


@dataclass
class BatchResult:
    """Result for a single file in a batch parse run."""

    path: Path
    result: ParseResult | None
    read_error: str | None  # str(exc) — always pickle-safe on Windows spawn
    profiling: ProfilingResult | None = None


# Module-level reusable parser for sequential fast-path
_REUSABLE_PARSER: CobolParser | None = None


def _get_reusable_parser(
    error_recovery: ErrorRecoveryMode, dialect: DialectType, free_form: bool
) -> CobolParser:
    """Get or create a reusable parser instance (avoids re-registering parsers)."""
    global _REUSABLE_PARSER
    if (
        _REUSABLE_PARSER is None
        or _REUSABLE_PARSER.error_recovery != error_recovery
        or _REUSABLE_PARSER.dialect != dialect
        or _REUSABLE_PARSER.free_form != free_form
    ):
        _REUSABLE_PARSER = CobolParser(
            error_recovery=error_recovery, dialect=dialect, free_form=free_form
        )
    return _REUSABLE_PARSER


def _parse_one(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool,
    top_n: int,
    prof_output_dir: str | None,
    cache_dir: str | None = None,
    cache_compress: bool = True,
    free_form: bool = False,
) -> BatchResult:
    """Read one file and parse it.

    Module-level (not a closure) for pickling on Windows spawn.
    Note: parse_cobol default is FAIL_FAST; we always pass error_recovery explicitly.

    When *cache_dir* is set, the worker first reads the source, looks up
    its content hash against the on-disk cache, and only invokes the
    parser on a miss. Hits avoid the entire parse pipeline.
    """
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))

    worker_cache: ParseCache | None = None
    cache_key: str | None = None
    if cache_dir is not None and not enable_profiling:
        # Profiling intentionally bypasses the cache so timings reflect a
        # real parse rather than a deserialization.
        worker_cache = ParseCache(cache_dir, compress=cache_compress)
        cache_key = make_cache_key(
            source=source,
            config_fingerprint=make_config_fingerprint(
                dialect=dialect,
                error_recovery=error_recovery,
                free_form=free_form,
            ),
        )
        cached = worker_cache.get(cache_key)
        if cached is not None:
            return BatchResult(path=path, result=cached, read_error=None)

    if not enable_profiling:
        result = parse_cobol(
            source,
            filename=path_str,
            error_recovery=error_recovery,
            dialect=dialect,
            free_form=free_form,
        )
        if worker_cache is not None and cache_key is not None:
            worker_cache.put(cache_key, result)
        return BatchResult(path=path, result=result, read_error=None)

    prof_output: str | None = None
    if prof_output_dir is not None:
        prof_output = str(Path(prof_output_dir) / (Path(path_str).stem + ".prof"))

    parse_result, prof = parse_cobol(
        source,
        filename=path_str,
        error_recovery=error_recovery,
        dialect=dialect,
        free_form=free_form,
        enable_profiling=True,
        top_n=top_n,
        prof_output=prof_output,
    )
    return BatchResult(path=path, result=parse_result, read_error=None, profiling=prof)


def _parse_one_reuse(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool,
    top_n: int,
    prof_output_dir: str | None,
    cache_dir: str | None = None,
    cache_compress: bool = True,
    free_form: bool = False,
) -> BatchResult:
    """Parse one file reusing a module-level parser (sequential mode only).

    Avoids re-creating CobolParser and re-registering division parsers for each file.
    """
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))

    worker_cache: ParseCache | None = None
    cache_key: str | None = None
    if cache_dir is not None and not enable_profiling:
        worker_cache = ParseCache(cache_dir, compress=cache_compress)
        cache_key = make_cache_key(
            source=source,
            config_fingerprint=make_config_fingerprint(
                dialect=dialect,
                error_recovery=error_recovery,
                free_form=free_form,
            ),
        )
        cached = worker_cache.get(cache_key)
        if cached is not None:
            return BatchResult(path=path, result=cached, read_error=None)

    parser = _get_reusable_parser(error_recovery, dialect, free_form)

    if not enable_profiling:
        result = parser.parse(source, filename=path_str, error_recovery=error_recovery)
        if worker_cache is not None and cache_key is not None:
            worker_cache.put(cache_key, result)
        return BatchResult(path=path, result=result, read_error=None)

    prof_output: str | None = None
    if prof_output_dir is not None:
        prof_output = str(Path(prof_output_dir) / (Path(path_str).stem + ".prof"))

    parse_result, prof = parser.parse(
        source,
        filename=path_str,
        error_recovery=error_recovery,
        enable_profiling=True,
        top_n=top_n,
        prof_output=prof_output,
    )
    return BatchResult(path=path, result=parse_result, read_error=None, profiling=prof)


def _parse_one_packed(args: tuple) -> BatchResult:
    """Unpack args tuple and call _parse_one.

    executor.map cannot use a lambda (not picklable on Windows spawn).
    This module-level wrapper is the correct pattern.
    """
    return _parse_one(*args)


def parse_files(
    paths: Iterable[str | Path],
    workers: int | None = None,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL,
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    encoding: str = "utf-8",
    errors: str = "replace",
    executor: ProcessPoolExecutor | None = None,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
    cache: ParseCache | None = None,
    free_form: bool = False,
) -> list[BatchResult]:
    """Parse multiple COBOL files in parallel.

    Args:
        paths: File paths to parse.
        workers: Worker processes. None → os.cpu_count() (or 1). Must be >= 1.
            Ignored when *executor* is provided.
        error_recovery: Passed to parse_cobol for each file.
        dialect: COBOL dialect, passed to parse_cobol for each file.
        encoding: Passed to Path.read_text(). Override for EBCDIC/Latin-1.
        errors: Passed to Path.read_text(). 'replace' avoids crashes on legacy files.
        executor: Optional pre-created ProcessPoolExecutor to reuse.  When
            provided the caller owns the executor lifecycle (shutdown/cleanup).
            Useful for amortising spawn overhead across many consecutive batches.
        enable_profiling: When True, attach a ProfilingResult to each BatchResult.
            Bypasses the cache so timings reflect a real parse.
        top_n: Number of top functions to include in each ProfilingResult.
        prof_output: Directory path to write per-file .prof binaries. Each file
            is written as <stem>.prof inside this directory. Must not end with
            ".prof" (that would be a file path, not a directory).
        cache: Optional :class:`~cobolparser.cache.ParseCache`. When provided,
            cache hits short-circuit the parse pipeline entirely. Lookups
            happen in the main process before scheduling any worker, so
            cache-hot batches never pay process-pool overhead. Workers
            re-open the cache to write entries on miss.
        free_form: Whether sources are free-form COBOL. Threaded through to
            parse_cobol; mismatches with the cache fingerprint cause a miss.

    Returns:
        list[BatchResult] in input order.

    Raises:
        ValueError: If workers <= 0 or prof_output ends with ".prof".
    """
    if workers is not None and workers <= 0:
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

    # Cache prepass: read each file once, look up the cached AST in the
    # main process. Hits are returned directly without scheduling any
    # worker. Only misses go through the parser. Profiling intentionally
    # skips the cache so timings reflect a real parse.
    cache_dir: str | None = None
    cache_compress: bool = True
    prepass: dict[int, BatchResult] = {}
    miss_indices: list[int] = list(range(len(path_list)))

    if cache is not None and cache.enabled and not enable_profiling:
        cache_dir = str(cache.root)
        cache_compress = cache.compress
        fingerprint = make_config_fingerprint(
            dialect=dialect,
            error_recovery=error_recovery,
            free_form=free_form,
        )
        miss_indices = []
        for idx, p in enumerate(path_list):
            try:
                source = Path(p).read_text(encoding=encoding, errors=errors)
            except OSError as exc:
                prepass[idx] = BatchResult(
                    path=Path(p), result=None, read_error=str(exc)
                )
                continue
            key = make_cache_key(source=source, config_fingerprint=fingerprint)
            cached = cache.get(key)
            if cached is not None:
                prepass[idx] = BatchResult(path=Path(p), result=cached, read_error=None)
            else:
                miss_indices.append(idx)

    if not miss_indices:
        # Every file was satisfied from cache or returned a read error.
        return [prepass[i] for i in range(len(path_list))]

    resolved_workers = workers if workers is not None else (os.cpu_count() or 1)
    args = [
        (
            path_list[i],
            encoding,
            errors,
            error_recovery,
            dialect,
            enable_profiling,
            top_n,
            prof_output,
            cache_dir,
            cache_compress,
            free_form,
        )
        for i in miss_indices
    ]

    if executor is None and resolved_workers == 1:
        # Sequential fast path: reuse parser instance, clean stack traces, no pickle overhead
        miss_results = [_parse_one_reuse(*a) for a in args]
    else:
        chunksize = max(1, len(miss_indices) // (resolved_workers * 4))
        if executor is not None:
            miss_results = list(
                executor.map(_parse_one_packed, args, chunksize=chunksize)
            )
        else:
            with ProcessPoolExecutor(max_workers=resolved_workers) as pool:
                miss_results = list(
                    pool.map(_parse_one_packed, args, chunksize=chunksize)
                )

    # Promote freshly-parsed results into the in-memory tier of the
    # caller's cache instance so subsequent get() calls hit memory.
    if cache is not None and cache.enabled and not enable_profiling:
        fingerprint = make_config_fingerprint(
            dialect=dialect,
            error_recovery=error_recovery,
            free_form=free_form,
        )
        for idx, br in zip(miss_indices, miss_results, strict=True):
            if br.result is not None and br.read_error is None:
                try:
                    source = Path(path_list[idx]).read_text(
                        encoding=encoding, errors=errors
                    )
                except OSError:
                    continue
                key = make_cache_key(source=source, config_fingerprint=fingerprint)
                cache._mem_put(key, br.result)

    merged: list[BatchResult] = [None] * len(path_list)  # type: ignore[list-item]
    for idx, br in zip(miss_indices, miss_results, strict=True):
        merged[idx] = br
    for idx, br in prepass.items():
        merged[idx] = br
    return merged


def parse_files_with_copybooks(
    paths: Iterable[str | Path],
    copybook_paths: list[str],
    workers: int | None = None,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL,
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    encoding: str = "utf-8",
    errors: str = "replace",
    max_nesting_depth: int = 100,
    copybook_cache_size: int = 1024,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
    cache: ParseCache | None = None,
    free_form: bool = False,
) -> list[BatchResult]:
    """Parse multiple COBOL files with shared copybook expansion cache.

    Optimized for large batch scenarios (3000+ programs, 50+ copybooks each)
    where many programs reference the same copybooks. The shared file content
    cache avoids redundant I/O and re-expansion of the same copybook content.

    This function runs sequentially in the main process to maximize cache hits.
    For CPU-bound scenarios where copybook expansion is minimal, use parse_files()
    with a ProcessPoolExecutor instead.

    Args:
        paths: File paths to parse.
        copybook_paths: Directories to search for copybook files.
        workers: Unused (reserved for future parallel copybook expansion).
        error_recovery: Passed to parser for each file.
        dialect: COBOL dialect, passed to parser for each file.
        encoding: File encoding for reading source files.
        errors: Error handling for file reads ('replace' avoids crashes).
        max_nesting_depth: Maximum copybook nesting depth.
        copybook_cache_size: Maximum entries in the shared expansion cache.
        enable_profiling: When True, attach a ProfilingResult to each BatchResult.
        top_n: Number of top functions to include in each ProfilingResult.
        prof_output: Directory path to write per-file .prof binaries.

    Returns:
        list[BatchResult] in input order.
    """
    if prof_output is not None and prof_output.endswith(".prof"):
        raise ValueError(
            "prof_output in batch mode must be a directory path, not a .prof file. "
            "Each file will be written as <stem>.prof inside that directory."
        )
    if enable_profiling and prof_output is not None:
        os.makedirs(prof_output, exist_ok=True)

    from cobolparser.preprocess.copybook_expander import expand_copybooks
    from cobolparser.preprocess.models import CopybookSearchPath
    from cobolparser.preprocess.path_resolver import PathResolver

    path_list = [str(p) for p in paths]
    if not path_list:
        return []

    # Create a shared search config with large cache
    search_config = CopybookSearchPath(
        directories=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        max_cache_entries=copybook_cache_size,
    )

    # Pre-build the file content cache (read each copybook file once)
    _file_content_cache: dict[str, str] = {}

    # Reusable path resolver to avoid recreating per file
    path_resolver = PathResolver(search_config)

    # Reusable parser to avoid re-registering division parsers per file
    parser = CobolParser(
        error_recovery=error_recovery, dialect=dialect, free_form=free_form
    )

    fingerprint = make_config_fingerprint(
        dialect=dialect,
        error_recovery=error_recovery,
        free_form=free_form,
    )

    results: list[BatchResult] = []
    for path_str in path_list:
        path = Path(path_str)
        try:
            source = path.read_text(encoding=encoding, errors=errors)
        except OSError as exc:
            results.append(BatchResult(path=path, result=None, read_error=str(exc)))
            continue

        # Expand copybooks with shared cache
        included_copybooks: list[str] = []
        try:
            expansion = expand_copybooks(
                source_code=source,
                copybook_paths=copybook_paths,
                max_nesting_depth=max_nesting_depth,
                validate_content=False,  # Skip validation for speed in batch mode
                path_resolver=path_resolver,
            )
            expanded_source = expansion.expanded_source
            included_copybooks = list(expansion.included_copybooks)
        except Exception:
            # If expansion fails, parse without expansion
            expanded_source = source

        # Cache lookup keyed by source + transitive copybook closure.
        cache_key: str | None = None
        if cache is not None and cache.enabled and not enable_profiling:
            cache_key = make_cache_key(
                source=source,
                config_fingerprint=fingerprint,
                copybook_files=included_copybooks,
            )
            cached = cache.get(cache_key)
            if cached is not None:
                results.append(BatchResult(path=path, result=cached, read_error=None))
                continue

        # Parse expanded source reusing the parser instance
        if not enable_profiling:
            result = parser.parse(
                expanded_source, filename=path_str, error_recovery=error_recovery
            )
            if cache is not None and cache.enabled and cache_key is not None:
                cache.put(cache_key, result)
            results.append(BatchResult(path=path, result=result, read_error=None))
        else:
            prof_file: str | None = None
            if prof_output is not None:
                prof_file = str(Path(prof_output) / (path.stem + ".prof"))
            parse_result, prof = parser.parse(
                expanded_source,
                filename=path_str,
                error_recovery=error_recovery,
                enable_profiling=True,
                top_n=top_n,
                prof_output=prof_file,
            )
            results.append(
                BatchResult(
                    path=path, result=parse_result, read_error=None, profiling=prof
                )
            )

    return results
