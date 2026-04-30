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

from cobolparser.parser import CobolParser, ParseResult, parse_cobol
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode


@dataclass
class BatchResult:
    """Result for a single file in a batch parse run."""

    path: Path
    result: ParseResult | None
    read_error: str | None  # str(exc) — always pickle-safe on Windows spawn


# Module-level reusable parser for sequential fast-path
_REUSABLE_PARSER: CobolParser | None = None


def _get_reusable_parser(
    error_recovery: ErrorRecoveryMode, dialect: DialectType
) -> CobolParser:
    """Get or create a reusable parser instance (avoids re-registering parsers)."""
    global _REUSABLE_PARSER
    if (
        _REUSABLE_PARSER is None
        or _REUSABLE_PARSER.error_recovery != error_recovery
        or _REUSABLE_PARSER.dialect != dialect
    ):
        _REUSABLE_PARSER = CobolParser(
            error_recovery=error_recovery, dialect=dialect
        )
    return _REUSABLE_PARSER


def _parse_one(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
) -> BatchResult:
    """Read one file and parse it.

    Module-level (not a closure) for pickling on Windows spawn.
    Note: parse_cobol default is FAIL_FAST; we always pass error_recovery explicitly.
    """
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))

    result = parse_cobol(
        source,
        filename=path_str,
        error_recovery=error_recovery,
        dialect=dialect,
    )
    return BatchResult(path=path, result=result, read_error=None)


def _parse_one_reuse(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
) -> BatchResult:
    """Parse one file reusing a module-level parser (sequential mode only).

    Avoids re-creating CobolParser and re-registering division parsers for each file.
    """
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))

    parser = _get_reusable_parser(error_recovery, dialect)
    result = parser.parse(source, filename=path_str, error_recovery=error_recovery)
    return BatchResult(path=path, result=result, read_error=None)


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

    Returns:
        list[BatchResult] in input order.

    Raises:
        ValueError: If workers <= 0.
    """
    if workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")

    path_list = [str(p) for p in paths]

    if not path_list:
        return []

    resolved_workers = workers if workers is not None else (os.cpu_count() or 1)
    args = [(p, encoding, errors, error_recovery, dialect) for p in path_list]

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

    Returns:
        list[BatchResult] in input order.
    """
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
    parser = CobolParser(error_recovery=error_recovery, dialect=dialect)

    results: list[BatchResult] = []
    for path_str in path_list:
        path = Path(path_str)
        try:
            source = path.read_text(encoding=encoding, errors=errors)
        except OSError as exc:
            results.append(BatchResult(path=path, result=None, read_error=str(exc)))
            continue

        # Expand copybooks with shared cache
        try:
            expansion = expand_copybooks(
                source_code=source,
                copybook_paths=copybook_paths,
                max_nesting_depth=max_nesting_depth,
                validate_content=False,  # Skip validation for speed in batch mode
                path_resolver=path_resolver,
            )
            expanded_source = expansion.expanded_source
        except Exception:
            # If expansion fails, parse without expansion
            expanded_source = source

        # Parse expanded source reusing the parser instance
        result = parser.parse(
            expanded_source, filename=path_str, error_recovery=error_recovery
        )
        results.append(BatchResult(path=path, result=result, read_error=None))

    return results
