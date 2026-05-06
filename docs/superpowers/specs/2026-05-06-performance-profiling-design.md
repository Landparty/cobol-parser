# Performance Profiling — Design Spec

**Date:** 2026-05-06  
**Scope:** `cobol-parser` and `jcl-parser` (independent, parallel implementations)  
**Status:** Approved

---

## Context

The COBOL and JCL parsers are used in the LegacyLens backend to process large legacy codebases. As programs grow in size and complexity, understanding where parse time and memory are spent becomes essential for optimization and SLA planning. There is currently no way to introspect parse performance beyond a single wall-clock `parse_time_seconds` value in `ParseStatistics`.

This spec adds an optional, non-intrusive profiling mode to both parsers that captures CPU time (user + system via psutil), wall-clock time, peak memory, and a ranked cProfile function breakdown — returned alongside the existing parse result in a structured `ProfilingResult` object.

---

## Architecture

### Approach

Each parser gets its own standalone `profiling.py` module. No shared cross-parser dependency is introduced — the parsers are independently vendored into the backend and must remain self-contained.

The `ProfilerContext` context manager wraps only the outermost parse call. It starts `cProfile.Profile`, captures `psutil.Process.cpu_times()` before/after, and on exit converts `pstats.Stats` to a ranked list of `FunctionProfile` objects. No existing parser code is modified — profiling is entirely additive.

### Dependencies

- **psutil** — added as an optional dependency under `[profiling]` extras in `pyproject.toml`. Gracefully absent: if not installed, `cpu_user_s` and `cpu_system_s` are `None`.
- **tracemalloc** — stdlib; always used for per-call peak memory (measures allocations within the profiled block, not process-wide RSS). psutil is not used for memory.
- **cProfile**, **pstats** — stdlib; always available.

---

## Data Structures

### `FunctionProfile` (dataclass)

```python
@dataclass
class FunctionProfile:
    function: str          # "filename:lineno(funcname)"
    calls: int
    total_time_s: float    # time spent in body only (excluding callees)
    cumul_time_s: float    # cumulative time including callees
    per_call_total_s: float
    per_call_cumul_s: float
```

### `ProfilingResult` (dataclass)

```python
@dataclass
class ProfilingResult:
    wall_clock_s: float
    cpu_user_s: float | None      # None if psutil not installed
    cpu_system_s: float | None    # None if psutil not installed
    peak_memory_mb: float         # tracemalloc peak allocation within the profiled call
    top_functions: list[FunctionProfile]   # top N by cumulative time (default 50)
    prof_file: str | None         # path to .prof binary, or None

    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self, compact: bool = False) -> str: ...
```

---

## Python API

### `parse_cobol()` (module-level function)

Uses `@overload` for static precision — return type is unchanged when profiling is off:

```python
@overload
def parse_cobol(
    source: str, ...,
    enable_profiling: Literal[False] = ...,
    top_n: int = 50,
    prof_output: str | None = None,
) -> ParseResult: ...

@overload
def parse_cobol(
    source: str, ...,
    enable_profiling: Literal[True],
    top_n: int = 50,
    prof_output: str | None = None,
) -> tuple[ParseResult, ProfilingResult]: ...
```

### `CobolParser.parse()`

Same overloads added to the method. The `ProfilerContext` wraps the internal parse call, replacing the existing `self.statistics.start_timing()` / `end_timing()` when profiling is active (wall-clock from `ProfilingResult` is authoritative; `ParseStatistics.parse_time_seconds` is still populated for backward compatibility).

### `parse_files()` / `parse_files_with_copybooks()`

Both accept `enable_profiling`, `top_n`, and `prof_output`. `BatchResult` gains:

```python
profiling: ProfilingResult | None = None
```

Profiling is per-file. In parallel mode (`ProcessPoolExecutor`), `ProfilingResult` objects are collected per worker result and attached to the corresponding `BatchResult`. `ProfilingResult` is a plain dataclass of floats/strings and is picklable across processes.

`prof_output` in batch mode is treated as a **directory path** — each file writes `<stem>.prof` into that directory. If `prof_output` is a file path (ends in `.prof`), it is only valid in single-file mode; batch mode raises `ValueError`.

---

## CLI

Three new flags added to all parse-related subcommands (`parse`, `batch`, `tokenize`, `analyze`, `dead-code`, `program-flow`):

```
--profile              Enable profiling (default: off)
--profile-top-n N      Top functions to include in JSON output (default: 50)
--profile-output FILE  Write .prof binary to FILE (for snakeviz, pyprof2calltree)
```

### JSON output (--profile with JSON subcommands)

Profiling data merged as a top-level `"profiling"` key:

```json
{
  "program_id": "HELLO",
  "divisions": { ... },
  "profiling": {
    "wall_clock_s": 0.042,
    "cpu_user_s": 0.038,
    "cpu_system_s": 0.004,
    "peak_memory_mb": 18.3,
    "prof_file": "/tmp/hello.prof",
    "top_functions": [
      {
        "function": "parser.py:147(parse_program)",
        "calls": 1,
        "cumul_time_s": 0.031,
        "total_time_s": 0.002,
        "per_call_cumul_s": 0.031,
        "per_call_total_s": 0.002
      }
    ]
  }
}
```

### Text output (batch, non-JSON subcommands)

A compact profiling block is appended after the normal text output:

```
--- Profiling ---
wall_clock:   0.042s
cpu_user:     0.038s
cpu_system:   0.004s
peak_memory:  18.3 MB
top functions (by cumulative time):
  0.031s  parser.py:147(parse_program)
  0.008s  lexer.py:89(tokenize)
  ...
```

---

## Files to Create / Modify

### New Files
- `cobolparser/profiling.py` — `ProfilingResult`, `FunctionProfile`, `ProfilerContext`

### Modified Files
- `cobolparser/parser.py` — add `enable_profiling`, `top_n`, `prof_output` args + overloads to `parse_cobol()` and `CobolParser.parse()`
- `cobolparser/batch.py` — add profiling args to `parse_files()` / `parse_files_with_copybooks()`; add `profiling` field to `BatchResult`
- `cobolparser/cli/parse.py` — add `--profile`, `--profile-top-n`, `--profile-output` to all applicable subcommand builders; merge profiling into JSON output
- `cobolparser/__init__.py` — export `ProfilingResult`, `FunctionProfile`
- `pyproject.toml` — add `psutil` under `[project.optional-dependencies]` as `profiling = ["psutil>=5.9"]`

### Tests to Add
- `tests/unit/test_profiling.py` — unit tests for `ProfilerContext`, `ProfilingResult.to_dict()`, graceful degradation without psutil
- `tests/integration/test_profiling_api.py` — end-to-end: `parse_cobol(..., enable_profiling=True)` returns correct tuple, `top_functions` is non-empty, metrics are positive
- `tests/integration/test_profiling_cli.py` — CLI `--profile` flag produces valid JSON with `"profiling"` key

---

## Verification

1. `python -m pytest tests/unit/test_profiling.py tests/integration/test_profiling_api.py tests/integration/test_profiling_cli.py -v` — all pass
2. `parse_cobol(source, enable_profiling=True)` returns `tuple[ParseResult, ProfilingResult]`; without the flag returns plain `ParseResult`
3. `cobol-parser parse FILE --profile --json` outputs JSON with `"profiling"` key containing `wall_clock_s`, `cpu_user_s`, `cpu_system_s`, `peak_memory_mb`, and `top_functions`
4. `cobol-parser parse FILE --profile --profile-output out.prof` writes a valid `.prof` binary loadable by `snakeviz out.prof`
5. `ProfilingResult.to_json()` is valid JSON; all numeric fields are non-negative
6. Without psutil installed: `cpu_user_s` and `cpu_system_s` are `null` in JSON; no exception raised
7. `python -m pytest tests/ -v` — full suite still passes (no regressions)
