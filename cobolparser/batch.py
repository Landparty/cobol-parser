"""Batch COBOL parsing using ProcessPoolExecutor.

Provides parse_files() for parsing 500-5000 COBOL files in parallel.
File I/O happens inside workers to avoid pickling large strings.
All worker functions are module-level (not lambdas/closures) for
Windows spawn-based pickling compatibility.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cobolparser.parser import parse_cobol, ParseResult
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode


@dataclass
class BatchResult:
    """Result for a single file in a batch parse run."""
    path: Path
    result: ParseResult | None
    read_error: str | None  # str(exc) — always pickle-safe on Windows spawn


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

    try:
        result = parse_cobol(
            source,
            filename=path_str,
            error_recovery=error_recovery,
            dialect=dialect,
        )
        return BatchResult(path=path, result=result, read_error=None)
    except Exception as exc:
        return BatchResult(path=path, result=None, read_error=str(exc))


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
) -> list[BatchResult]:
    """Parse multiple COBOL files in parallel.

    Args:
        paths: File paths to parse.
        workers: Worker processes. None → os.cpu_count() (or 1). Must be >= 1.
        error_recovery: Passed to parse_cobol for each file.
        dialect: COBOL dialect, passed to parse_cobol for each file.
        encoding: Passed to Path.read_text(). Override for EBCDIC/Latin-1.
        errors: Passed to Path.read_text(). 'replace' avoids crashes on legacy files.

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
    args = [
        (p, encoding, errors, error_recovery, dialect)
        for p in path_list
    ]

    if resolved_workers == 1:
        # Sequential fast path: clean stack traces, no pickle overhead
        return [_parse_one(*a) for a in args]

    chunksize = max(1, len(path_list) // (resolved_workers * 4))

    with ProcessPoolExecutor(max_workers=resolved_workers) as executor:
        results = list(executor.map(_parse_one_packed, args, chunksize=chunksize))
    return results
