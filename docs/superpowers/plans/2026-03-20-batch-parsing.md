# Batch Parsing API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `parse_files()` batch function that parses 500–5,000 COBOL files in parallel using `ProcessPoolExecutor`, exposing results as an ordered `list[BatchResult]`.

**Architecture:** A new `cobolparser/batch.py` module contains module-level worker functions `_parse_one` and `_parse_one_packed`, and the public `parse_files()` function. File I/O happens inside workers to avoid pickling large strings. `__init__.py` exports `parse_files` and `BatchResult` alongside the existing `parse_cobol`.

**Tech Stack:** Python 3.13+, `concurrent.futures.ProcessPoolExecutor`, `pathlib.Path`, `dataclasses`, `pytest`

**Spec:** `docs/superpowers/specs/2026-03-20-batch-parsing-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `cobolparser/batch.py` | `BatchResult` dataclass, `_parse_one`, `_parse_one_packed`, `parse_files()` |
| **Modify** | `cobolparser/__init__.py` | Export `parse_files` and `BatchResult` |
| **Create** | `tests/integration/test_batch.py` | All batch tests |

---

## Task 1: `batch.py` — `BatchResult`, worker, and `parse_files()`

**Files:**
- Create: `cobolparser/batch.py`
- Create: `tests/integration/test_batch.py`

- [ ] **Step 1: Write the failing tests for `BatchResult` fields and `parse_files` basics**

Create `tests/integration/test_batch.py` with all imports at the top:

```python
"""Integration tests for the batch parsing API."""
import pytest
from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.batch import BatchResult, parse_files
from cobolparser.plugins.core import ErrorRecoveryMode


SAMPLES_DIR = Path(__file__).parent.parent / "samples"


class TestBatchResult:
    def test_fields_success(self, tmp_path):
        p = tmp_path / "foo.cbl"
        br = BatchResult(path=p, result=object(), read_error=None)
        assert br.path == p
        assert br.read_error is None

    def test_fields_error(self, tmp_path):
        p = tmp_path / "missing.cbl"
        br = BatchResult(path=p, result=None, read_error="FileNotFoundError: no such file")
        assert br.result is None
        assert isinstance(br.read_error, str)

    def test_importable_from_package(self):
        from cobolparser import parse_files as pf, BatchResult as BR  # noqa: F401
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python -m pytest tests/integration/test_batch.py -v
```

Expected: `ModuleNotFoundError: No module named 'cobolparser.batch'`

- [ ] **Step 3: Create `cobolparser/batch.py`**

```python
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

    result = parse_cobol(
        source,
        filename=path_str,
        error_recovery=error_recovery,
        dialect=dialect,
    )
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/integration/test_batch.py::TestBatchResult -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add cobolparser/batch.py tests/integration/test_batch.py
git commit -m "feat: add batch.py with BatchResult, _parse_one worker, and parse_files()"
```

---

## Task 2: Export from `cobolparser/__init__.py`

**Files:**
- Modify: `cobolparser/__init__.py`

- [ ] **Step 1: Run the import test to confirm it fails before the export is added**

```bash
python -m pytest tests/integration/test_batch.py::TestBatchResult::test_importable_from_package -v
```

Expected: FAIL — `ImportError: cannot import name 'parse_files' from 'cobolparser'`

- [ ] **Step 2: Add exports to `__init__.py`**

After the `from .parser import (...)` block (~line 102), add:

```python
from .batch import (
    parse_files,
    BatchResult,
)
```

In the `__all__` list (after `"parse_cobol"`), add:

```python
    "parse_files",
    "BatchResult",
```

- [ ] **Step 3: Run to verify it passes**

```bash
python -m pytest tests/integration/test_batch.py::TestBatchResult::test_importable_from_package -v
```

Expected: PASSED

- [ ] **Step 4: Commit**

```bash
git add cobolparser/__init__.py
git commit -m "feat: export parse_files and BatchResult from cobolparser package"
```

---

## Task 3: Correctness parity and error handling tests

**Files:**
- Modify: `tests/integration/test_batch.py`

- [ ] **Step 1: Write the remaining test classes**

Append to `tests/integration/test_batch.py`:

```python
class TestParseFilesCorrectness:
    """parse_files() must produce identical output to parse_cobol() per file."""

    def test_parity_with_parse_cobol(self):
        files = sorted(SAMPLES_DIR.glob("*.cbl"))
        if not files:
            pytest.skip("No sample files found")

        # Reference: parse each file individually with COLLECT_ALL
        # (parse_cobol defaults to FAIL_FAST, so we pass it explicitly here too)
        reference = {}
        for f in files:
            source = f.read_text(encoding="utf-8", errors="replace")
            reference[f] = parse_cobol(
                source,
                filename=str(f),
                error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            )

        batch = parse_files(files, workers=1, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert len(batch) == len(files)
        for br in batch:
            assert br.read_error is None, f"{br.path}: unexpected read error"
            ref = reference[br.path]
            assert br.result.ast.to_dict() == ref.ast.to_dict(), f"{br.path}: AST mismatch"
            assert len(br.result.errors) == len(ref.errors), f"{br.path}: error count mismatch"

    def test_results_in_input_order(self):
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:8]
        if len(files) < 2:
            pytest.skip("Need at least 2 sample files")
        results = parse_files(files, workers=min(4, len(files)))
        for br, f in zip(results, files):
            assert br.path == f


class TestParseFilesErrorHandling:
    def test_missing_file_does_not_abort_batch(self, tmp_path):
        """One bad path should not abort the whole batch."""
        good_files = sorted(SAMPLES_DIR.glob("*.cbl"))[:3]
        if not good_files:
            pytest.skip("No sample files found")

        missing = tmp_path / "does_not_exist.cbl"
        mixed = [good_files[0], missing, good_files[1]]

        results = parse_files(mixed, workers=1)

        assert len(results) == 3
        assert results[0].read_error is None
        assert results[0].result is not None
        assert results[1].read_error is not None
        assert results[1].result is None
        assert results[2].read_error is None
        assert results[2].result is not None

    def test_empty_input_returns_empty_list(self):
        assert parse_files([]) == []

    def test_workers_zero_raises(self):
        with pytest.raises(ValueError, match="workers must be >= 1 or None"):
            parse_files([], workers=0)

    def test_workers_negative_raises(self):
        with pytest.raises(ValueError):
            parse_files([], workers=-1)


class TestParseFilesWorkersParity:
    def test_workers_1_matches_workers_gt_1(self):
        """Multi-worker results must match single-worker results exactly."""
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:6]
        if not files:
            pytest.skip("No sample files found")

        r1 = parse_files(files, workers=1)
        r4 = parse_files(files, workers=min(4, len(files)))

        assert len(r1) == len(r4)
        for a, b in zip(r1, r4):
            assert a.path == b.path
            assert (a.result is None) == (b.result is None)
            if a.result is not None:
                assert a.result.ast.to_dict() == b.result.ast.to_dict()
```

- [ ] **Step 2: Run all batch tests**

```bash
python -m pytest tests/integration/test_batch.py -v
```

Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_batch.py
git commit -m "test: correctness parity, error handling, and workers parity for batch API"
```

---

## Task 4: Final verification

- [ ] **Step 1: Run the full test suite with coverage**

```bash
python -m pytest tests/ -v --cov=cobolparser --cov-fail-under=81 2>&1 | tail -30
```

Expected: all tests PASSED, coverage >= 81%, no regressions.

- [ ] **Step 2: Quick timing check (informational)**

```bash
python -c "
import time
from pathlib import Path
from cobolparser.batch import parse_files

files = sorted(Path('tests/samples').glob('*.cbl'))
print(f'Parsing {len(files)} files...')

t0 = time.perf_counter()
parse_files(files, workers=1)
t1 = time.perf_counter()
seq_ms = (t1 - t0) * 1000
print(f'workers=1 (sequential): {seq_ms:.1f}ms')

t0 = time.perf_counter()
import os; n = os.cpu_count() or 1
parse_files(files, workers=n)
t1 = time.perf_counter()
par_ms = (t1 - t0) * 1000
print(f'workers={n} (parallel): {par_ms:.1f}ms')
print()
print('Note: on small sample sets, process-spawn overhead (~200ms on Windows)')
print('dominates. Speedup is visible on 500+ files where parse time >> spawn cost.')
"
```

- [ ] **Step 3: Final commit (only if anything remains unstaged)**

```bash
git add cobolparser/batch.py cobolparser/__init__.py tests/integration/test_batch.py
git commit -m "feat: batch parsing API complete — parse_files() with ProcessPoolExecutor"
```
