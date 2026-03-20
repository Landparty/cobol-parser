# Batch Parsing API — Design Spec

**Date:** 2026-03-20
**Status:** Approved

---

## Problem

The parser currently exposes only `parse_cobol(source)` — a single-file API. Batch workloads
processing 500–5,000 COBOL files run entirely single-threaded, leaving all but one CPU core
idle. At ~3 ms/file, a 2,500-file run takes ~7.5 seconds. The goal is to bring this to ~1 second
on typical 8-core hardware with zero changes to the existing parser.

---

## Solution

Add a `parse_files()` batch function backed by `ProcessPoolExecutor`. COBOL parsing is
embarrassingly parallel — no shared state between files — so near-linear scaling with core count
is achievable with minimal design complexity.

---

## Public API

```python
from cobolparser import parse_files
from cobolparser.batch import BatchResult

results: list[BatchResult] = parse_files(
    paths,                                    # Iterable[str | Path]
    workers=None,                             # None → os.cpu_count() (explicit, not executor default)
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    dialect=DialectType.IBM_ENTERPRISE,       # forwarded to parse_cobol
    encoding="utf-8",                         # passed to Path.read_text()
    errors="replace",                         # passed to Path.read_text()
)
```

**`workers` validation:**
- `None` → resolved to `os.cpu_count()` (or `1` if `os.cpu_count()` returns `None`)
- `workers >= 1` → used as-is
- `workers <= 0` → raises `ValueError("workers must be >= 1 or None")`

**`encoding` / `errors` note:** These are passed directly to `Path.read_text()`. The default
`"utf-8"` / `"replace"` is chosen to avoid crashing on legacy files — callers processing
mainframe exports (EBCDIC, Latin-1) should always override `encoding`.

### `BatchResult`

A dataclass with three fields:

| Field | Type | Description |
|-------|------|-------------|
| `path` | `Path` | Absolute path of the file |
| `result` | `ParseResult \| None` | Parse output; `None` if the file could not be read |
| `read_error` | `str \| None` | `str(exc)` of the file-read exception; `None` on success |

**Why `str` for `read_error` instead of `Exception`:** On Windows, multiprocessing uses spawn
(not fork), so all return values must be picklable. Exception objects with chained context can
fail to pickle. Storing `str(exc)` is always safe and sufficient for error reporting.

Results are returned **in input order**.

### Why file I/O inside the worker

Reading happens inside the worker process rather than the main process. This:
- Avoids pickling potentially large source strings across the process boundary
- Lets the OS distribute I/O across cores alongside CPU work
- Keeps the main process lean

---

## Architecture

```
cobolparser/
  batch.py          ← new module
  __init__.py       ← export parse_files, BatchResult alongside parse_cobol
```

### `batch.py` internals

```
parse_files(paths, workers, ...)
  │
  ├── [] → return []                          (empty-input fast path)
  ├── workers == 1 → sequential loop          (single-worker fast path, clean stack traces)
  └── ProcessPoolExecutor(max_workers=resolved_workers)
        └── executor.map(_parse_one, args_list, chunksize=chunksize)
              └── _parse_one(path_str, encoding, errors, error_recovery, dialect)
                    ├── Path(path_str).read_text(encoding=encoding, errors=errors)
                    ├── parse_cobol(source, filename=path_str,
                    │              error_recovery=error_recovery,
                    │              dialect=dialect)          ← keyword args, never positional
                    └── return BatchResult(path, result, read_error=None)
                    [on OSError/IOError] → return BatchResult(path, None, read_error=str(exc))
```

**`chunksize` is adaptive:** `max(1, len(paths) // (resolved_workers * 4))`. This ensures good
load balancing for small batches while reducing IPC overhead for large ones.

`_parse_one` is a **module-level function** (not a lambda or closure) — required for pickling
on Windows, which uses spawn rather than fork.

**`ParseResult` picklability:** `CobolProgram` and its children must be picklable for the
worker return to succeed on Windows. This must be validated before merging: the correctness
parity test (see Tests) implicitly verifies this since it exercises the full worker round-trip.

---

## Edge Cases

| Case | Behaviour |
|------|-----------|
| Empty `paths` | Return `[]` immediately, no workers spawned |
| `workers=1` | Skip executor, run sequentially — clean stack traces, no pickle overhead |
| `workers=None` | Resolved to `os.cpu_count()` (or `1` if unavailable) — **not** executor default |
| `workers <= 0` | Raise `ValueError("workers must be >= 1 or None")` |
| File not found / permission denied | `BatchResult(result=None, read_error=str(exc))`; rest of batch continues |
| Parse errors inside a file | Captured in `BatchResult.result.errors`; never raises |

---

## Tests

New file: `tests/integration/test_batch.py`

| Test | Assertion |
|------|-----------|
| Correctness parity | `parse_files(all_samples)` produces identical AST/errors to calling `parse_cobol()` on each file individually (also implicitly validates `ParseResult` picklability on Windows) |
| Bad file path | A nonexistent path in the list yields `read_error` as a non-None string, `result=None`; other results unaffected |
| `workers=1` equivalence | Results with `workers=1` match results with `workers=4` |
| `workers=0` validation | `parse_files([], workers=0)` raises `ValueError` |

**Coverage:** `batch.py` is a small module (~100 lines); the four tests are expected to cover
it fully. The 81% project-wide `--cov-fail-under` gate should remain satisfied.

---

## Non-Goals

- No file-change caching or fingerprinting (use case is one-shot runs)
- No streaming / incremental results (synchronous `list` return is sufficient)
- No progress callbacks or `tqdm`-compatible hooks
- No changes to `CobolParser`, `lexer.py`, or any existing module
