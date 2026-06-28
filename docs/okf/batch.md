# Batch & Profiling

> Parallel multi-file parsing and performance profiling utilities.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/batch.py` | `parse_files()` and `parse_files_with_copybooks()` using `ProcessPoolExecutor` for parallel and sequential batch parsing |
| `cobolparser/profiling.py` | `ProfilerContext` wraps any parse call with cProfile, tracemalloc, and optional psutil CPU accounting |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `parse_files()` | `batch.py` | `parse_files(paths: Iterable[str \| Path], workers: int \| None = None, ...) -> list[BatchResult]` — parallel parsing with optional profiling and .prof output |
| `parse_files_with_copybooks()` | `batch.py` | `parse_files_with_copybooks(paths, copybook_paths: list[str], ...) -> list[BatchResult]` — sequential batch with copybook expansion and shared cache |
| `BatchResult` | `batch.py` | Dataclass: `path: Path`, `result: ParseResult \| None`, `read_error: str \| None`, `profiling: ProfilingResult \| None` |
| `ProfilerContext` | `profiling.py` | Context manager: wraps a parse call; `.result` is `ProfilingResult` after exit |
| `ProfilingResult` | `profiling.py` | Dataclass: `wall_clock_s: float`, `cpu_user_s: float \| None`, `cpu_system_s: float \| None`, `peak_memory_mb: float`, `top_functions: list[FunctionProfile]`, `prof_file: str \| None` |
| `FunctionProfile` | `profiling.py` | Dataclass: `function: str`, `calls: int`, `total_time_s: float`, `cumul_time_s: float`, `per_call_total_s: float`, `per_call_cumul_s: float` |

## Data Flow / Lifecycle

### Batch Parsing with `parse_files()`

1. Caller invokes `parse_files(paths, workers=None, error_recovery=..., ...)` with a list of file paths.
2. Path validation:
   - Convert all paths to strings.
   - If empty, return `[]` immediately.
   - If `workers <= 0`, raise `ValueError`.
3. Executor selection:
   - If `executor` provided, use caller-managed executor (caller responsible for `.shutdown()`).
   - If `workers == 1` and no executor, use sequential fast path: reuse a module-level `CobolParser` instance to avoid re-registering division parsers and pickling overhead.
   - Otherwise, create a `ProcessPoolExecutor(max_workers=workers or os.cpu_count())` in a context manager.
4. Worker function dispatch:
   - Each file is sent to a worker via `executor.map(_parse_one_packed, args)`.
   - Worker function `_parse_one()` (module-level, not a closure, for Windows spawn-based pickling):
     - Reads file content with `Path.read_text(encoding=..., errors=...)`.
     - On read error, returns `BatchResult(path, result=None, read_error=str(exc))`.
     - Parses with `parse_cobol()` (or `ProfilingContext` if profiling enabled).
     - Returns `BatchResult(path, result=ParseResult, read_error=None, profiling=prof)`.
5. Result collection:
   - Results returned in input order via `.map()`.
   - Profiling results (if enabled) attached to each `BatchResult`.
   - Per-file `.prof` binary written to `prof_output/<stem>.prof` if `prof_output` specified.

### Batch Parsing with `parse_files_with_copybooks()`

1. Caller invokes `parse_files_with_copybooks(paths, copybook_paths=[...], ...)` with copybook search directories.
2. Configuration:
   - Build a `CopybookSearchPath` with `max_nesting_depth` and `max_cache_entries`.
   - Create a module-level `CobolParser` instance to reuse across all files (avoids parser re-creation overhead).
   - Create a module-level `PathResolver` to reuse copybook path resolution.
3. Sequential file processing (in main process):
   - For each file path:
     - Read source code with `Path.read_text()`.
     - On read error, append `BatchResult(path, result=None, read_error=str(exc))` and continue.
     - Expand copybooks via `expand_copybooks(source_code, copybook_paths=...)` with the shared resolver.
     - On expansion error (best-effort degradation), log warning and fall back to raw source.
     - Parse expanded source with reused parser instance.
     - Append `BatchResult(path, result=ParseResult, read_error=None, profiling=prof or None)`.
4. Result return:
   - Return `list[BatchResult]` in input order.
   - Cache is implicit in the `PathResolver` (file content cached by path).

### Profiling with `ProfilerContext`

1. Caller enters context manager: `with ProfilerContext(top_n=50, prof_output=None) as prof:`.
2. On `__enter__`:
   - Start `tracemalloc` if not already running (save state to restore later).
   - Record `wall_start = time.perf_counter()`.
   - If `psutil` available, capture `Process().cpu_times()` before profiling.
   - Enable `cProfile.Profile()`.
   - Return self.
3. Caller code executes (e.g., `parse_cobol(source)`).
4. On `__exit__`:
   - Disable cProfile.
   - Compute wall-clock time as `time.perf_counter() - wall_start`.
   - Get peak memory from tracemalloc; restore tracing state.
   - If psutil available, compute CPU user + system delta.
   - Extract top-N functions from cProfile stats, sorted by cumulative time.
   - Write `.prof` binary if `prof_output` specified.
   - Construct `ProfilingResult` with all metrics and attach to `self.result`.
5. Caller accesses `prof.result` (a `ProfilingResult` dataclass).

## Public API (exported symbols)

```python
from cobolparser import parse_files
from cobolparser.batch import parse_files_with_copybooks, BatchResult
from cobolparser.profiling import ProfilerContext, ProfilingResult, FunctionProfile
```

### Example: Parallel Batch Parsing

```python
from cobolparser import parse_files

results = parse_files(["a.cbl", "b.cbl", "c.cbl"], workers=4)
for batch_result in results:
    if batch_result.read_error:
        print(f"Read error: {batch_result.path} — {batch_result.read_error}")
    elif batch_result.result.success:
        print(f"Parsed: {batch_result.path}")
    else:
        for error in batch_result.result.errors:
            print(f"Parse error in {batch_result.path}: {error}")
```

### Example: Batch Parsing with Copybooks

```python
from cobolparser.batch import parse_files_with_copybooks

results = parse_files_with_copybooks(
    ["prog1.cbl", "prog2.cbl"],
    copybook_paths=["/usr/share/cobol/copybooks", "/local/copybooks"],
    copybook_cache_size=2048
)
for result in results:
    if result.read_error:
        print(f"Error: {result.path} — {result.read_error}")
    else:
        print(f"Parsed: {result.path}")
```

### Example: Profiling a Single Parse

```python
from cobolparser import parse_cobol
from cobolparser.profiling import ProfilerContext

with ProfilerContext(top_n=20) as prof:
    result = parse_cobol(source_code)

print(f"Wall-clock: {prof.result.wall_clock_s}s")
print(f"Peak memory: {prof.result.peak_memory_mb}MB")
for fn in prof.result.top_functions[:5]:
    print(f"  {fn.function}: {fn.cumul_time_s:.3f}s ({fn.calls} calls)")
```

### Example: Executor Reuse Across Batches

```python
from concurrent.futures import ProcessPoolExecutor
from cobolparser import parse_files

batch_files = [["a.cbl", "b.cbl"], ["c.cbl", "d.cbl"]]

with ProcessPoolExecutor(max_workers=4) as executor:
    for batch in batch_files:
        results = parse_files(batch, executor=executor)
        # Process results...
```

## Gotchas / Invariants

- **Windows multiprocessing:** Code using `parse_files()` with `workers > 1` must be inside `if __name__ == "__main__":` (or a function called from there) because `ProcessPoolExecutor` spawns new Python processes. On Windows, this triggers a re-import of the main module, and top-level code runs twice.
- **Module-level workers:** Worker functions (`_parse_one`, `_parse_one_reuse`, `_parse_one_packed`) are defined at module level, not as closures or lambdas, because Windows spawn-mode pickling cannot serialize closures. This is intentional and required for Windows compatibility.
- **Sequential vs parallel:** When `workers=1`, batch parsing automatically uses the sequential fast path with a reusable parser instance (no executor spawned). This is faster for small batches but disables parallel parsing.
- **Executor lifecycle:** When `executor` is provided, the caller owns cleanup (must call `.shutdown(wait=True)` or use context manager). `parse_files()` does not shut down a caller-provided executor.
- **BatchResult.result vs read_error:** `BatchResult.result` is `None` when `read_error` is populated. Always check `read_error` first before accessing `result`.
- **ProfilingResult.cpu_user_s and cpu_system_s:** These fields are `None` when `psutil` is not installed (optional via `pip install -e ".[profiling]"`). Code must check for `None` before using CPU metrics.
- **Copybook cache:** `parse_files_with_copybooks()` uses a shared file content cache within the `PathResolver` to avoid redundant I/O when many programs reference the same copybook. Cache size is bounded by `copybook_cache_size` parameter (default 1024).
- **Copybook expansion best-effort:** If copybook expansion fails in `parse_files_with_copybooks()`, the failure is logged (at WARNING level) and the raw source is parsed instead. This prevents a single bad COPY statement from aborting the entire batch.
- **prof_output directory mode:** When passing `prof_output` to batch functions, provide a **directory path**, not a file path. Each file will be written as `<stem>.prof` inside that directory. Passing `"profile.prof"` will raise `ValueError`.
- **Profiling overhead:** Enabling profiling (`enable_profiling=True`) adds measurable overhead (5-10% wall-clock time on typical COBOL programs). Use selectively.

## Refresh Checklist

- [ ] Verify `BatchResult` fields in `batch.py`: path, result, read_error, profiling (with default None)
- [ ] Verify `parse_files()` signature in `batch.py` — check workers, error_recovery, dialect, encoding, errors, executor, enable_profiling, top_n, prof_output parameters
- [ ] Verify `parse_files_with_copybooks()` signature — check copybook_paths, max_nesting_depth, copybook_cache_size parameters
- [ ] Verify `ProfilerContext` signature — check top_n and prof_output parameters
- [ ] Verify `ProfilingResult` fields: wall_clock_s, cpu_user_s, cpu_system_s (nullable), peak_memory_mb, top_functions, prof_file
- [ ] Verify `FunctionProfile` fields: function, calls, total_time_s, cumul_time_s, per_call_total_s, per_call_cumul_s
- [ ] Check if Windows spawn mode is still mentioned as a constraint in worker function comments
- [ ] Verify psutil is in `[profiling]` extra in setup.py (not a hard dependency)
- [ ] Verify module-level worker functions (_parse_one, _parse_one_reuse, _parse_one_packed) still exist in batch.py
- [ ] Verify CopybookSearchPath and PathResolver are still used in parse_files_with_copybooks
