---
type: Module Reference
title: Batch & Profiling
description: Parallel multi-file parsing via ProcessPoolExecutor and cProfile/tracemalloc profiling utilities.
tags: [batch, parallel, profiling, cprofile, tracemalloc, process-pool]
timestamp: 2026-06-28T00:00:00Z
---

# Batch & Profiling

> Parallel multi-file parsing and performance profiling utilities.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/batch.py` | `parse_files()` and `parse_files_with_copybooks()` using `ProcessPoolExecutor` |
| `cobolparser/profiling.py` | `ProfilerContext` wraps any parse call with cProfile, tracemalloc, and optional psutil CPU accounting |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `parse_files()` | `batch.py` | `parse_files(paths, workers=None, ...) -> list[BatchResult]` — parallel parsing |
| `parse_files_with_copybooks()` | `batch.py` | `parse_files_with_copybooks(paths, copybook_paths, ...) -> list[BatchResult]` — sequential batch with copybook expansion and shared cache |
| `BatchResult` | `batch.py` | Dataclass: `path: Path`, `result: ParseResult \| None`, `read_error: str \| None`, `profiling: ProfilingResult \| None` |
| `ProfilerContext` | `profiling.py` | Context manager: wraps a parse call; `.result` is `ProfilingResult` after exit |
| `ProfilingResult` | `profiling.py` | Dataclass: `wall_clock_s: float`, `cpu_user_s: float \| None`, `cpu_system_s: float \| None`, `peak_memory_mb: float`, `top_functions: list[FunctionProfile]`, `prof_file: str \| None` |
| `FunctionProfile` | `profiling.py` | Dataclass: `function: str`, `calls: int`, `total_time_s: float`, `cumul_time_s: float`, `per_call_total_s: float`, `per_call_cumul_s: float` |

## Data Flow / Lifecycle

### Batch Parsing with `parse_files()`

1. Caller invokes `parse_files(paths, workers=None, ...)` with a list of file paths.
2. If `workers == 1`, uses sequential fast path with a reusable `CobolParser` instance.
3. Otherwise, creates `ProcessPoolExecutor(max_workers=workers or os.cpu_count())`.
4. Worker function `_parse_one()` (module-level, not a closure — required for Windows spawn-mode pickling):
   - Reads file content with `Path.read_text(encoding=..., errors=...)`
   - On read error, returns `BatchResult(path, result=None, read_error=str(exc))`
   - Parses with `parse_cobol()` (or `ProfilerContext` if profiling enabled)
5. Results returned in input order via `.map()`.

### Batch Parsing with `parse_files_with_copybooks()`

1. Caller invokes `parse_files_with_copybooks(paths, copybook_paths=[...], ...)`.
2. Sequential processing in main process (not parallel) with a shared `CobolParser` and `PathResolver`. See [preprocessing.md](preprocessing.md).
3. For each file, expands copybooks via `expand_copybooks()` then parses. On expansion error, falls back to raw source (best-effort degradation).

### Profiling with `ProfilerContext`

1. `with ProfilerContext(top_n=50, prof_output=None) as prof:` — starts tracemalloc, cProfile, records wall time and (if psutil available) CPU times.
2. Caller code executes.
3. On `__exit__`: disables profiler, computes metrics, constructs `ProfilingResult` at `prof.result`.

## Public API (exported symbols)

```python
from cobolparser import parse_files
from cobolparser.batch import parse_files_with_copybooks, BatchResult
from cobolparser.profiling import ProfilerContext, ProfilingResult, FunctionProfile
```

## Examples

```python
# Parallel batch
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"], workers=4)
for r in results:
    if r.read_error:
        print(f"Read error: {r.path} — {r.read_error}")
    elif r.result.success:
        print(f"OK: {r.path}")

# Batch with copybooks
from cobolparser.batch import parse_files_with_copybooks

results = parse_files_with_copybooks(
    ["prog1.cbl", "prog2.cbl"],
    copybook_paths=["/usr/share/cobol/copybooks"],
)

# Profiling a single parse
from cobolparser import parse_cobol
from cobolparser.profiling import ProfilerContext

with ProfilerContext(top_n=20) as prof:
    result = parse_cobol(source_code)

print(f"Wall: {prof.result.wall_clock_s:.3f}s  Peak: {prof.result.peak_memory_mb:.1f}MB")

# Executor reuse across batches
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor(max_workers=4) as executor:
    for batch in [["a.cbl", "b.cbl"], ["c.cbl", "d.cbl"]]:
        results = parse_files(batch, executor=executor)
```

## Gotchas / Invariants

- **Windows multiprocessing:** Code using `parse_files()` with `workers > 1` must be inside `if __name__ == "__main__":` — `ProcessPoolExecutor` spawns new Python processes on Windows.
- **Module-level workers:** `_parse_one`, `_parse_one_reuse`, `_parse_one_packed` are defined at module level, not as closures — Windows spawn-mode pickling cannot serialize closures.
- **`workers=1` fast path:** Uses sequential single-process execution; faster for small batches, disables parallelism.
- **Executor lifecycle:** When `executor` is provided, the caller owns cleanup (`.shutdown(wait=True)`). `parse_files()` does not shut down a caller-provided executor.
- **`BatchResult.result` vs `read_error`:** `result` is `None` when `read_error` is set. Always check `read_error` first.
- **`ProfilingResult.cpu_user_s` and `cpu_system_s`:** `None` when `psutil` is not installed (optional `pip install -e ".[profiling]"`).
- **Copybook cache:** `parse_files_with_copybooks()` uses a shared file content cache within `PathResolver` keyed by absolute path. Cache size bounded by `copybook_cache_size` parameter (default 1024).
- **`prof_output` directory mode:** Provide a **directory path**, not a `.prof` file. Each file written as `<stem>.prof` inside the directory.
- **Profiling overhead:** 5-10% wall-clock overhead typical. Use selectively.

## Refresh Checklist

- [ ] Verify `BatchResult` fields: path, result, read_error, profiling
- [ ] Verify `parse_files()` signature: workers, error_recovery, dialect, encoding, errors, executor, enable_profiling, top_n, prof_output
- [ ] Verify `parse_files_with_copybooks()`: copybook_paths, max_nesting_depth, copybook_cache_size
- [ ] Verify `ProfilerContext` signature: top_n, prof_output
- [ ] Verify `ProfilingResult` fields: wall_clock_s, cpu_user_s, cpu_system_s (nullable), peak_memory_mb, top_functions, prof_file
- [ ] Verify module-level worker functions still exist in `batch.py`
- [ ] Verify psutil is in `[profiling]` extra in setup.py
