# Performance Profiling — cobol-parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional cProfile-based profiling to `parse_cobol()`, `CobolParser.parse()`, and `parse_files()`, returning a `ProfilingResult` tuple alongside the standard parse output.

**Architecture:** A standalone `cobolparser/profiling.py` module provides `FunctionProfile`, `ProfilingResult`, and `ProfilerContext`. The `ProfilerContext` context manager wraps the outermost parse call with `cProfile.Profile`, captures CPU times via psutil (optional), and measures peak memory allocation via `tracemalloc`. No existing parse logic is modified — all new behaviour is gated by `enable_profiling=False` (default). The public API uses `@overload` so the return type is statically correct without profiling.

**Tech Stack:** Python 3.11+, `cProfile`/`pstats` (stdlib), `tracemalloc` (stdlib), `psutil>=5.9` (optional extra), `pytest`, existing project tooling (`ruff`, `black`, `mypy`).

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| **Create** | `cobolparser/profiling.py` | `FunctionProfile`, `ProfilingResult`, `ProfilerContext` |
| **Create** | `tests/unit/test_profiling.py` | Unit tests for profiling module |
| **Create** | `tests/integration/test_profiling_api.py` | End-to-end API tests |
| **Create** | `tests/integration/test_profiling_cli.py` | CLI `--profile` flag tests |
| **Modify** | `cobolparser/parser.py` | Extract `_parse_core()`, add overloads to `parse()` and `parse_cobol()` |
| **Modify** | `cobolparser/batch.py` | Add `profiling` field to `BatchResult`, update `parse_files()` |
| **Modify** | `cobolparser/__init__.py` | Export `ProfilingResult`, `FunctionProfile` |
| **Modify** | `cobolparser/cli/parse.py` | Add `--profile`, `--profile-top-n`, `--profile-output` flags |
| **Modify** | `pyproject.toml` | Add `profiling = ["psutil>=5.9"]` optional extra |

---

## Task 1: Create `cobolparser/profiling.py`

**Files:**
- Create: `cobolparser/profiling.py`
- Create: `tests/unit/test_profiling.py`

- [ ] **Step 1.1: Write failing unit tests**

Create `tests/unit/test_profiling.py`:

```python
"""Unit tests for cobolparser.profiling module."""
from __future__ import annotations

import json
import os
import time

import pytest

from cobolparser.profiling import FunctionProfile, ProfilingResult, ProfilerContext


# ---------------------------------------------------------------------------
# FunctionProfile
# ---------------------------------------------------------------------------

def test_function_profile_to_dict():
    fp = FunctionProfile(
        function="parser.py:100(parse)",
        calls=3,
        total_time_s=0.01,
        cumul_time_s=0.05,
        per_call_total_s=0.003_333,
        per_call_cumul_s=0.016_667,
    )
    d = fp.to_dict()
    assert d["function"] == "parser.py:100(parse)"
    assert d["calls"] == 3
    assert d["total_time_s"] == pytest.approx(0.01)
    assert d["cumul_time_s"] == pytest.approx(0.05)
    assert d["per_call_total_s"] == pytest.approx(0.003_333)
    assert d["per_call_cumul_s"] == pytest.approx(0.016_667)


# ---------------------------------------------------------------------------
# ProfilingResult
# ---------------------------------------------------------------------------

def test_profiling_result_to_dict_with_psutil_values():
    fp = FunctionProfile("f.py:1(fn)", 1, 0.01, 0.05, 0.01, 0.05)
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=0.08,
        cpu_system_s=0.02,
        peak_memory_mb=5.0,
        top_functions=[fp],
        prof_file=None,
    )
    d = result.to_dict()
    assert d["wall_clock_s"] == pytest.approx(0.1)
    assert d["cpu_user_s"] == pytest.approx(0.08)
    assert d["cpu_system_s"] == pytest.approx(0.02)
    assert d["peak_memory_mb"] == pytest.approx(5.0)
    assert d["prof_file"] is None
    assert len(d["top_functions"]) == 1
    assert d["top_functions"][0]["function"] == "f.py:1(fn)"


def test_profiling_result_to_dict_none_cpu():
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=None,
        cpu_system_s=None,
        peak_memory_mb=3.0,
        top_functions=[],
        prof_file=None,
    )
    d = result.to_dict()
    assert d["cpu_user_s"] is None
    assert d["cpu_system_s"] is None


def test_profiling_result_to_json_valid():
    result = ProfilingResult(
        wall_clock_s=0.1,
        cpu_user_s=None,
        cpu_system_s=None,
        peak_memory_mb=3.0,
        top_functions=[],
        prof_file=None,
    )
    parsed = json.loads(result.to_json())
    assert parsed["wall_clock_s"] == pytest.approx(0.1)
    assert parsed["cpu_user_s"] is None


def test_profiling_result_to_json_compact():
    result = ProfilingResult(0.1, None, None, 1.0, [], None)
    compact = result.to_json(compact=True)
    pretty = result.to_json(compact=False)
    assert "\n" not in compact
    assert len(compact) < len(pretty)


def test_profiling_result_prof_file_in_dict(tmp_path):
    prof_path = str(tmp_path / "out.prof")
    result = ProfilingResult(0.1, None, None, 1.0, [], prof_file=prof_path)
    assert result.to_dict()["prof_file"] == prof_path


# ---------------------------------------------------------------------------
# ProfilerContext
# ---------------------------------------------------------------------------

def test_profiler_context_produces_result():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        _ = sum(range(10_000))
    assert ctx.result is not None


def test_profiler_context_wall_clock_positive():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        time.sleep(0.01)
    assert ctx.result.wall_clock_s >= 0.005  # generous lower bound


def test_profiler_context_peak_memory_non_negative():
    ctx = ProfilerContext(top_n=10)
    with ctx:
        _ = list(range(1_000))
    assert ctx.result.peak_memory_mb >= 0.0


def test_profiler_context_top_n_respected():
    ctx = ProfilerContext(top_n=3)
    with ctx:
        _ = sum(range(100_000))
    assert len(ctx.result.top_functions) <= 3


def test_profiler_context_top_n_zero_gives_empty():
    ctx = ProfilerContext(top_n=0)
    with ctx:
        _ = sum(range(1_000))
    assert ctx.result.top_functions == []


def test_profiler_context_function_profile_fields():
    ctx = ProfilerContext(top_n=50)
    with ctx:
        _ = [x * 2 for x in range(5_000)]
    fp = ctx.result.top_functions[0]
    assert fp.calls >= 1
    assert fp.cumul_time_s >= 0.0
    assert fp.total_time_s >= 0.0
    assert "(" in fp.function and ")" in fp.function  # "filename:lineno(funcname)"


def test_profiler_context_writes_prof_file(tmp_path):
    prof_path = str(tmp_path / "test.prof")
    ctx = ProfilerContext(top_n=5, prof_output=prof_path)
    with ctx:
        _ = sum(range(1_000))
    assert os.path.exists(prof_path)
    assert ctx.result.prof_file == prof_path


def test_profiler_context_no_prof_file_by_default():
    ctx = ProfilerContext(top_n=5)
    with ctx:
        pass
    assert ctx.result.prof_file is None


def test_profiler_context_nested_tracemalloc_safe():
    """ProfilerContext must not stop an outer tracemalloc session."""
    import tracemalloc
    tracemalloc.start()
    try:
        ctx = ProfilerContext(top_n=5)
        with ctx:
            _ = list(range(100))
        # outer session still running
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```
python -m pytest tests/unit/test_profiling.py -v
```

Expected: `ModuleNotFoundError: No module named 'cobolparser.profiling'`

- [ ] **Step 1.3: Create `cobolparser/profiling.py`**

```python
"""Performance profiling support for cobolparser.

ProfilerContext wraps any parse call with cProfile, tracemalloc, and
optional psutil CPU accounting. Import psutil lazily so the package remains
usable without it.
"""
from __future__ import annotations

import cProfile
import io
import json
import pstats
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil as _psutil

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSUTIL_AVAILABLE = False


@dataclass
class FunctionProfile:
    """Timing profile for a single function from cProfile."""

    function: str  # "filename:lineno(funcname)"
    calls: int
    total_time_s: float  # time in body only (excluding callees)
    cumul_time_s: float  # cumulative time including callees
    per_call_total_s: float
    per_call_cumul_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "calls": self.calls,
            "total_time_s": self.total_time_s,
            "cumul_time_s": self.cumul_time_s,
            "per_call_total_s": self.per_call_total_s,
            "per_call_cumul_s": self.per_call_cumul_s,
        }


@dataclass
class ProfilingResult:
    """Structured profiling output from a profiled parse call."""

    wall_clock_s: float
    cpu_user_s: float | None  # None when psutil is not installed
    cpu_system_s: float | None  # None when psutil is not installed
    peak_memory_mb: float  # tracemalloc peak allocation within the profiled call
    top_functions: list[FunctionProfile]
    prof_file: str | None  # path to .prof binary, or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_clock_s": self.wall_clock_s,
            "cpu_user_s": self.cpu_user_s,
            "cpu_system_s": self.cpu_system_s,
            "peak_memory_mb": self.peak_memory_mb,
            "prof_file": self.prof_file,
            "top_functions": [f.to_dict() for f in self.top_functions],
        }

    def to_json(self, compact: bool = False) -> str:
        if compact:
            return json.dumps(self.to_dict(), separators=(",", ":"))
        return json.dumps(self.to_dict(), indent=2)


class ProfilerContext:
    """Context manager that profiles a parse call with cProfile + tracemalloc.

    Usage::

        ctx = ProfilerContext(top_n=50, prof_output="/tmp/parse.prof")
        with ctx:
            result = parser.parse(source)
        profiling: ProfilingResult = ctx.result
    """

    def __init__(self, top_n: int = 50, prof_output: str | None = None) -> None:
        self._top_n = top_n
        self._prof_output = prof_output
        self._profiler = cProfile.Profile()
        self._wall_start: float = 0.0
        self._cpu_before: Any = None
        self._was_tracing: bool = False
        self.result: ProfilingResult | None = None

    def __enter__(self) -> "ProfilerContext":
        # Memory: start tracemalloc only if not already running
        self._was_tracing = tracemalloc.is_tracing()
        if not self._was_tracing:
            tracemalloc.start()

        self._wall_start = time.perf_counter()

        if _PSUTIL_AVAILABLE:
            self._cpu_before = _psutil.Process().cpu_times()

        self._profiler.enable()
        return self

    def __exit__(self, *_: Any) -> None:
        self._profiler.disable()
        wall_clock_s = time.perf_counter() - self._wall_start

        # Memory peak within this call
        _, peak_bytes = tracemalloc.get_traced_memory()
        if not self._was_tracing:
            tracemalloc.stop()
        peak_memory_mb = peak_bytes / (1024 * 1024)

        # CPU user + system delta via psutil
        cpu_user_s: float | None = None
        cpu_system_s: float | None = None
        if _PSUTIL_AVAILABLE and self._cpu_before is not None:
            cpu_after = _psutil.Process().cpu_times()
            cpu_user_s = max(0.0, cpu_after.user - self._cpu_before.user)
            cpu_system_s = max(0.0, cpu_after.system - self._cpu_before.system)

        # Write .prof binary if requested
        if self._prof_output:
            self._profiler.dump_stats(self._prof_output)

        # Extract top-N functions by cumulative time from cProfile stats
        top_functions: list[FunctionProfile] = []
        if self._top_n > 0:
            stream = io.StringIO()
            stats = pstats.Stats(self._profiler, stream=stream)
            # stats.stats: {(file, lineno, name): (cc, nc, tt, ct, callers)}
            sorted_entries = sorted(
                stats.stats.items(),
                key=lambda kv: kv[1][3],  # ct = cumulative time
                reverse=True,
            )[: self._top_n]
            for (filename, lineno, funcname), (cc, nc, tt, ct, _) in sorted_entries:
                top_functions.append(
                    FunctionProfile(
                        function=f"{filename}:{lineno}({funcname})",
                        calls=nc,
                        total_time_s=tt,
                        cumul_time_s=ct,
                        per_call_total_s=tt / nc if nc else 0.0,
                        per_call_cumul_s=ct / cc if cc else 0.0,
                    )
                )

        self.result = ProfilingResult(
            wall_clock_s=wall_clock_s,
            cpu_user_s=cpu_user_s,
            cpu_system_s=cpu_system_s,
            peak_memory_mb=peak_memory_mb,
            top_functions=top_functions,
            prof_file=self._prof_output,
        )
```

- [ ] **Step 1.4: Run unit tests — expect all pass**

```
python -m pytest tests/unit/test_profiling.py -v
```

Expected: all tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add cobolparser/profiling.py tests/unit/test_profiling.py
git commit -m "feat: add profiling module with ProfilerContext, ProfilingResult, FunctionProfile"
```

---

## Task 2: Add `psutil` optional dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 2.1: Add `profiling` extra to `pyproject.toml`**

In `pyproject.toml`, find the `[project.optional-dependencies]` section (currently has `dev` and `docs`) and add:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-xdist>=3.0.0",
    "ruff>=0.1.0",
    "black>=23.0.0",
    "mypy>=1.5.0",
]
docs = [
    "sphinx>=7.0.0",
    "sphinx-rtd-theme>=1.3.0",
]
profiling = [
    "psutil>=5.9",
]
```

- [ ] **Step 2.2: Install the optional extra (dev environment)**

```
pip install -e ".[profiling]"
```

Expected: `psutil` installed, no errors.

- [ ] **Step 2.3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add psutil optional dependency under [profiling] extra"
```

---

## Task 3: Refactor `CobolParser.parse()` and add profiling support

**Files:**
- Modify: `cobolparser/parser.py` (lines 126–202 are the `parse()` body to extract)
- Create: `tests/integration/test_profiling_api.py`

- [ ] **Step 3.1: Write failing integration tests**

Create `tests/integration/test_profiling_api.py`:

```python
"""Integration tests: parse_cobol() and CobolParser.parse() with profiling."""
from __future__ import annotations

import json

import pytest

from cobolparser import parse_cobol, CobolParser
from cobolparser.profiling import ProfilingResult

_SIMPLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY 'HI'.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# CobolParser.parse() overloads
# ---------------------------------------------------------------------------

def test_parse_without_profiling_returns_parse_result():
    parser = CobolParser()
    result = parser.parse(_SIMPLE)
    # Must NOT be a tuple
    assert not isinstance(result, tuple)
    assert result.success


def test_parse_with_profiling_returns_tuple():
    parser = CobolParser()
    out = parser.parse(_SIMPLE, enable_profiling=True)
    assert isinstance(out, tuple) and len(out) == 2
    parse_result, profiling = out
    assert parse_result.success
    assert isinstance(profiling, ProfilingResult)


def test_parse_profiling_wall_clock_positive():
    parser = CobolParser()
    _, profiling = parser.parse(_SIMPLE, enable_profiling=True)
    assert profiling.wall_clock_s > 0


def test_parse_profiling_peak_memory_non_negative():
    parser = CobolParser()
    _, profiling = parser.parse(_SIMPLE, enable_profiling=True)
    assert profiling.peak_memory_mb >= 0.0


def test_parse_profiling_top_functions_non_empty():
    parser = CobolParser()
    _, profiling = parser.parse(_SIMPLE, enable_profiling=True)
    assert len(profiling.top_functions) > 0


def test_parse_profiling_top_n_respected():
    parser = CobolParser()
    _, profiling = parser.parse(_SIMPLE, enable_profiling=True, top_n=3)
    assert len(profiling.top_functions) <= 3


def test_parse_profiling_prof_file(tmp_path):
    prof_path = str(tmp_path / "hello.prof")
    parser = CobolParser()
    _, profiling = parser.parse(_SIMPLE, enable_profiling=True, prof_output=prof_path)
    import os
    assert os.path.exists(prof_path)
    assert profiling.prof_file == prof_path


def test_parse_statistics_still_populated():
    """ParseStatistics.parse_time_seconds must be set even when profiling."""
    parser = CobolParser()
    parse_result, profiling = parser.parse(_SIMPLE, enable_profiling=True)
    assert parse_result.statistics.parse_time_seconds > 0
    assert parse_result.statistics.parse_time_seconds == pytest.approx(
        profiling.wall_clock_s, rel=0.5
    )


# ---------------------------------------------------------------------------
# Module-level parse_cobol() overloads
# ---------------------------------------------------------------------------

def test_parse_cobol_without_profiling_returns_parse_result():
    result = parse_cobol(_SIMPLE)
    assert not isinstance(result, tuple)
    assert result.success


def test_parse_cobol_with_profiling_returns_tuple():
    out = parse_cobol(_SIMPLE, enable_profiling=True)
    assert isinstance(out, tuple) and len(out) == 2
    parse_result, profiling = out
    assert parse_result.success
    assert isinstance(profiling, ProfilingResult)


def test_parse_cobol_profiling_to_json():
    _, profiling = parse_cobol(_SIMPLE, enable_profiling=True)
    data = json.loads(profiling.to_json())
    assert "wall_clock_s" in data
    assert "top_functions" in data
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```
python -m pytest tests/integration/test_profiling_api.py -v
```

Expected: `TypeError` — `parse()` and `parse_cobol()` don't accept `enable_profiling`.

- [ ] **Step 3.3: Extract `_parse_core()` from `CobolParser.parse()`**

In `cobolparser/parser.py`, rename the current `parse()` method body to `_parse_core()` — a private method with the identical signature and body — then replace `parse()` with a dispatcher. The current `parse()` at lines 126–202 becomes `_parse_core()`:

```python
# Add this import at the top of parser.py (with the other typing imports):
from typing import Literal, overload

# Add this import after the existing cobolparser imports:
from cobolparser.profiling import ProfilerContext, ProfilingResult
```

Then in the `CobolParser` class, after the existing imports, add the overloads and refactored method. Replace the entire `def parse(...)` block with:

```python
@overload
def parse(
    self,
    source: str,
    filename: str = ...,
    error_recovery: ErrorRecoveryMode | None = ...,
    enable_profiling: Literal[False] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> ParseResult: ...

@overload
def parse(
    self,
    source: str,
    filename: str = ...,
    error_recovery: ErrorRecoveryMode | None = ...,
    enable_profiling: Literal[True] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> tuple[ParseResult, ProfilingResult]: ...

def parse(
    self,
    source: str,
    filename: str = "<string>",
    error_recovery: ErrorRecoveryMode | None = None,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
) -> ParseResult | tuple[ParseResult, ProfilingResult]:
    """Parse COBOL source code into AST.

    Args:
        source: COBOL source code
        filename: Source filename for error reporting
        error_recovery: Error recovery mode (FAIL_FAST or COLLECT_ALL).
                       Defaults to FAIL_FAST if not specified.
        enable_profiling: When True, returns (ParseResult, ProfilingResult) tuple.
        top_n: Maximum number of functions to include in ProfilingResult.top_functions.
        prof_output: If set, write cProfile .prof binary to this path.

    Returns:
        ParseResult, or (ParseResult, ProfilingResult) when enable_profiling=True.
    """
    if enable_profiling:
        ctx = ProfilerContext(top_n=top_n, prof_output=prof_output)
        with ctx:
            result = self._parse_core(source, filename, error_recovery)
        # Keep ParseStatistics in sync for backward compatibility
        result.statistics.parse_time_seconds = ctx.result.wall_clock_s
        result.statistics.total_time_ms = ctx.result.wall_clock_s * 1000.0
        return result, ctx.result  # type: ignore[return-value]
    return self._parse_core(source, filename, error_recovery)

def _parse_core(
    self,
    source: str,
    filename: str = "<string>",
    error_recovery: ErrorRecoveryMode | None = None,
) -> ParseResult:
    """Internal parse implementation (called directly or wrapped by ProfilerContext)."""
    # Set error recovery mode if provided
    if error_recovery is not None:
        self.error_recovery = error_recovery

    self.statistics.reset()
    self.statistics.start_timing()
    self.errors.clear()
    self.warnings.clear()
    self._error_limit_reached = False

    try:
        # Preprocess and tokenize
        cleaned_source = self._skip_to_identification_division(source)

        # Auto-detect fixed-format if not explicitly specified
        actual_free_form = self.free_form
        if not self.free_form:
            detected_fixed = _detect_fixed_format(cleaned_source)
            if detected_fixed:
                cleaned_source = normalize_fixed_format(cleaned_source.splitlines())
                actual_free_form = True
            else:
                actual_free_form = False

        lexer = CobolLexer(
            cleaned_source, filename, self.dialect, free_form=actual_free_form
        )
        self.tokens = lexer.tokenize()

        if lexer.has_errors():
            for error in lexer.get_errors():
                self.add_error(
                    ParseError(
                        f"Lexer error: {error.message}",
                        line_number=error.location.line if error.location else 1,
                        column=error.location.column if error.location else 1,
                    )
                )
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return self._create_result(None)

        # Initialize TokenStream and parse program
        self.stream = TokenStream(self.tokens)
        program = self.parse_program()

        self.statistics.end_timing()
        self.statistics.lines_parsed = len(source.splitlines())
        self.statistics.tokens_processed = len(self.tokens)

        return self._create_result(program)

    except Exception as e:
        self.add_error(
            ParseError(f"Parser error: {str(e)}", line_number=1, column=1)
        )
        return self._create_result(None)
```

- [ ] **Step 3.4: Run integration tests — expect all pass**

```
python -m pytest tests/integration/test_profiling_api.py -v
```

Expected: all `test_parse_without_profiling_*` and `test_parse_with_profiling_*` and `CobolParser` tests pass. The `parse_cobol()` tests will still fail (Task 4 next).

- [ ] **Step 3.5: Commit**

```bash
git add cobolparser/parser.py
git commit -m "feat: extract CobolParser._parse_core(), add profiling overloads to parse()"
```

---

## Task 4: Add profiling overloads to module-level `parse_cobol()`

**Files:**
- Modify: `cobolparser/parser.py` (lines 394–450, `parse_cobol()` function)

- [ ] **Step 4.1: Replace `parse_cobol()` with overloaded version**

In `cobolparser/parser.py`, replace the existing `parse_cobol()` function (lines 394–450) with:

```python
@overload
def parse_cobol(
    source: str,
    filename: str = ...,
    dialect: DialectType = ...,
    error_recovery: ErrorRecoveryMode = ...,
    free_form: bool = ...,
    preprocess_fixed: bool | None = ...,
    enable_profiling: Literal[False] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> ParseResult: ...


@overload
def parse_cobol(
    source: str,
    filename: str = ...,
    dialect: DialectType = ...,
    error_recovery: ErrorRecoveryMode = ...,
    free_form: bool = ...,
    preprocess_fixed: bool | None = ...,
    enable_profiling: Literal[True] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> tuple[ParseResult, ProfilingResult]: ...


def parse_cobol(
    source: str,
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
    free_form: bool = False,
    preprocess_fixed: bool | None = None,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
) -> ParseResult | tuple[ParseResult, ProfilingResult]:
    """Convenience function to parse COBOL source code.

    Automatically detects fixed-format COBOL and preprocesses if needed.

    Args:
        source: COBOL source code or path to COBOL file
        filename: Source filename for error reporting
        dialect: COBOL dialect
        error_recovery: Error recovery mode
        free_form: Whether source is in free-form format
        preprocess_fixed: Whether to preprocess fixed-format COBOL (auto-detect if None)
        enable_profiling: When True, returns (ParseResult, ProfilingResult) tuple.
        top_n: Maximum functions in ProfilingResult.top_functions.
        prof_output: If set, write cProfile .prof binary to this path.

    Returns:
        ParseResult, or (ParseResult, ProfilingResult) when enable_profiling=True.
    """
    import os

    # Handle file paths
    if os.path.isfile(source):
        with open(source, encoding="utf-8", errors="replace") as f:
            file_content = f.read()
        if filename == "<string>":
            filename = source
        source = file_content

    # Auto-detect fixed-format if not explicitly specified
    if preprocess_fixed is None:
        detected_fixed = _detect_fixed_format(source)
        preprocess_fixed = detected_fixed
        if not detected_fixed and not free_form:
            free_form = True

    if preprocess_fixed:
        try:
            source = normalize_fixed_format(source.splitlines())
        except ValueError as exc:
            err = ParseError(str(exc), line_number=0, column=0)
            stats = ParseStatistics()
            failed: ParseResult = ParseResult(
                ast=None, errors=[err], warnings=[], statistics=stats
            )
            if enable_profiling:
                empty_profiling = ProfilingResult(
                    wall_clock_s=0.0,
                    cpu_user_s=None,
                    cpu_system_s=None,
                    peak_memory_mb=0.0,
                    top_functions=[],
                    prof_file=None,
                )
                return failed, empty_profiling  # type: ignore[return-value]
            return failed
        free_form = True

    parser = CobolParser(
        dialect=dialect, error_recovery=error_recovery, free_form=free_form
    )
    return parser.parse(  # type: ignore[return-value]
        source,
        filename,
        enable_profiling=enable_profiling,  # type: ignore[call-overload]
        top_n=top_n,
        prof_output=prof_output,
    )
```

- [ ] **Step 4.2: Run all profiling API tests — expect all pass**

```
python -m pytest tests/integration/test_profiling_api.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 4.3: Verify existing tests still pass**

```
python -m pytest tests/ -v --ignore=tests/integration/test_profiling_api.py --ignore=tests/unit/test_profiling.py -x -q
```

Expected: no regressions.

- [ ] **Step 4.4: Commit**

```bash
git add cobolparser/parser.py
git commit -m "feat: add profiling overloads to parse_cobol() module-level function"
```

---

## Task 5: Add profiling to `BatchResult` and `parse_files()`

**Files:**
- Modify: `cobolparser/batch.py`

- [ ] **Step 5.1: Update `BatchResult` to carry `ProfilingResult`**

In `cobolparser/batch.py`, add the import and update the dataclass. At the top with the existing imports, add:

```python
from cobolparser.profiling import ProfilerContext, ProfilingResult
```

Replace the `BatchResult` dataclass (lines 34–41) with:

```python
@dataclass
class BatchResult:
    """Result for a single file in a batch parse run."""

    path: Path
    result: ParseResult | None
    read_error: str | None  # str(exc) — always pickle-safe on Windows spawn
    profiling: ProfilingResult | None = None
```

- [ ] **Step 5.2: Update `_parse_one()` to accept and perform profiling**

Replace the current `_parse_one()` function (lines 63–87) with:

```python
def _parse_one(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output_dir: str | None = None,
) -> BatchResult:
    """Read one file and parse it.

    Module-level (not a closure) for pickling on Windows spawn.
    """
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc), profiling=None)

    if enable_profiling:
        prof_file = (
            str(Path(prof_output_dir) / f"{path.stem}.prof")
            if prof_output_dir
            else None
        )
        ctx = ProfilerContext(top_n=top_n, prof_output=prof_file)
        with ctx:
            result = parse_cobol(
                source,
                filename=path_str,
                error_recovery=error_recovery,
                dialect=dialect,
            )
        return BatchResult(path=path, result=result, read_error=None, profiling=ctx.result)

    result = parse_cobol(
        source,
        filename=path_str,
        error_recovery=error_recovery,
        dialect=dialect,
    )
    return BatchResult(path=path, result=result, read_error=None, profiling=None)
```

- [ ] **Step 5.3: Update `_parse_one_reuse()` similarly**

Replace `_parse_one_reuse()` (lines 90–109) with:

```python
def _parse_one_reuse(
    path_str: str,
    encoding: str,
    errors: str,
    error_recovery: ErrorRecoveryMode,
    dialect: DialectType,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output_dir: str | None = None,
) -> BatchResult:
    """Parse one file reusing a module-level parser (sequential mode only)."""
    path = Path(path_str)
    try:
        source = path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        return BatchResult(path=path, result=None, read_error=str(exc), profiling=None)

    parser = _get_reusable_parser(error_recovery, dialect)

    if enable_profiling:
        prof_file = (
            str(Path(prof_output_dir) / f"{path.stem}.prof")
            if prof_output_dir
            else None
        )
        ctx = ProfilerContext(top_n=top_n, prof_output=prof_file)
        with ctx:
            result = parser.parse(source, filename=path_str, error_recovery=error_recovery)
        return BatchResult(path=path, result=result, read_error=None, profiling=ctx.result)

    result = parser.parse(source, filename=path_str, error_recovery=error_recovery)
    return BatchResult(path=path, result=result, read_error=None, profiling=None)
```

- [ ] **Step 5.4: Update `_parse_one_packed()` to pass all args**

Replace `_parse_one_packed()` (lines 112–118) — it's just an unpacker, no logic change needed:

```python
def _parse_one_packed(args: tuple) -> BatchResult:
    """Unpack args tuple and call _parse_one.

    executor.map cannot use a lambda (not picklable on Windows spawn).
    """
    return _parse_one(*args)
```

(No change to body — the tuple now carries extra fields.)

- [ ] **Step 5.5: Update `parse_files()` signature and args construction**

Replace `parse_files()` (lines 121–174) with:

```python
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
    prof_output_dir: str | None = None,
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
        executor: Optional pre-created ProcessPoolExecutor to reuse.
        enable_profiling: When True, each BatchResult.profiling is populated.
        top_n: Top functions per file in ProfilingResult.
        prof_output_dir: Directory to write per-file .prof binaries (e.g. "stem.prof").

    Returns:
        list[BatchResult] in input order.

    Raises:
        ValueError: If workers <= 0, or if prof_output_dir is a .prof file path.
    """
    if workers is not None and workers <= 0:
        raise ValueError("workers must be >= 1 or None")
    if (
        enable_profiling
        and prof_output_dir is not None
        and prof_output_dir.endswith(".prof")
    ):
        raise ValueError(
            "prof_output_dir must be a directory path in batch mode, not a .prof file. "
            "Per-file binaries are written as <dir>/<stem>.prof."
        )

    path_list = [str(p) for p in paths]
    if not path_list:
        return []

    resolved_workers = workers if workers is not None else (os.cpu_count() or 1)
    args = [
        (p, encoding, errors, error_recovery, dialect, enable_profiling, top_n, prof_output_dir)
        for p in path_list
    ]

    if executor is None and resolved_workers == 1:
        return [_parse_one_reuse(*a) for a in args]

    chunksize = max(1, len(path_list) // (resolved_workers * 4))

    if executor is not None:
        return list(executor.map(_parse_one_packed, args, chunksize=chunksize))

    with ProcessPoolExecutor(max_workers=resolved_workers) as pool:
        results = list(pool.map(_parse_one_packed, args, chunksize=chunksize))
    return results
```

- [ ] **Step 5.6: Run existing batch tests and profiling API tests**

```
python -m pytest tests/ -k "batch or profiling" -v
```

Expected: all pass, `BatchResult` has `profiling` field.

- [ ] **Step 5.7: Commit**

```bash
git add cobolparser/batch.py
git commit -m "feat: add profiling support to BatchResult and parse_files()"
```

---

## Task 6: Export `ProfilingResult` and `FunctionProfile` from `cobolparser/__init__.py`

**Files:**
- Modify: `cobolparser/__init__.py`

- [ ] **Step 6.1: Add exports to `__init__.py`**

Find the existing public exports in `cobolparser/__init__.py`. Add the following import alongside them:

```python
from cobolparser.profiling import ProfilingResult, FunctionProfile
```

Place it near the top with the other parser/result imports (e.g., after the `parse_cobol` import line).

- [ ] **Step 6.2: Verify import works**

```
python -c "from cobolparser import ProfilingResult, FunctionProfile; print('ok')"
```

Expected: `ok`

- [ ] **Step 6.3: Commit**

```bash
git add cobolparser/__init__.py
git commit -m "feat: export ProfilingResult and FunctionProfile from cobolparser public API"
```

---

## Task 7: Add `--profile` CLI flags and merge into JSON output

**Files:**
- Modify: `cobolparser/cli/parse.py`
- Create: `tests/integration/test_profiling_cli.py`

- [ ] **Step 7.1: Write failing CLI tests**

Create `tests/integration/test_profiling_cli.py`:

```python
"""Integration tests: CLI --profile flag."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> tuple[int, dict]:
    """Run cobol-parser CLI and parse JSON output."""
    cmd = [sys.executable, "-m", "cobolparser.cli", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# We need a real COBOL file for the CLI tests
_SAMPLE = Path(__file__).parent.parent / "samples" / "hello_world.cbl"


def _get_sample() -> Path:
    """Return a guaranteed-existing sample file."""
    # Use any .cbl file from tests/samples/
    samples = list(Path(__file__).parent.parent.glob("samples/**/*.cbl"))
    assert samples, "No .cbl sample files found in tests/samples/"
    return samples[0]


def test_profile_flag_adds_profiling_key():
    sample = _get_sample()
    rc, stdout, stderr = _run_cli("parse", str(sample), "--profile")
    assert rc == 0, f"CLI failed: {stderr}"
    data = json.loads(stdout)
    assert "profiling" in data, f"No 'profiling' key in output: {list(data.keys())}"


def test_profile_section_has_required_fields():
    sample = _get_sample()
    rc, stdout, _ = _run_cli("parse", str(sample), "--profile")
    assert rc == 0
    profiling = json.loads(stdout)["profiling"]
    assert "wall_clock_s" in profiling
    assert "cpu_user_s" in profiling
    assert "cpu_system_s" in profiling
    assert "peak_memory_mb" in profiling
    assert "top_functions" in profiling
    assert "prof_file" in profiling


def test_profile_wall_clock_positive():
    sample = _get_sample()
    rc, stdout, _ = _run_cli("parse", str(sample), "--profile")
    assert rc == 0
    profiling = json.loads(stdout)["profiling"]
    assert profiling["wall_clock_s"] > 0


def test_profile_top_n_flag():
    sample = _get_sample()
    rc, stdout, _ = _run_cli("parse", str(sample), "--profile", "--profile-top-n", "3")
    assert rc == 0
    profiling = json.loads(stdout)["profiling"]
    assert len(profiling["top_functions"]) <= 3


def test_profile_output_flag(tmp_path):
    sample = _get_sample()
    prof_path = str(tmp_path / "out.prof")
    rc, stdout, _ = _run_cli(
        "parse", str(sample), "--profile", "--profile-output", prof_path
    )
    assert rc == 0
    import os
    assert os.path.exists(prof_path)
    data = json.loads(stdout)
    assert data["profiling"]["prof_file"] == prof_path


def test_without_profile_flag_no_profiling_key():
    sample = _get_sample()
    rc, stdout, _ = _run_cli("parse", str(sample))
    assert rc == 0
    data = json.loads(stdout)
    assert "profiling" not in data
```

- [ ] **Step 7.2: Run tests to confirm they fail**

```
python -m pytest tests/integration/test_profiling_cli.py -v
```

Expected: failures because `--profile` flag doesn't exist yet.

- [ ] **Step 7.3: Add shared arg-builder helper and flags to CLI**

In `cobolparser/cli/parse.py`, add after the existing shared helpers (e.g., after `_add_compact_arg`):

```python
def _add_profile_args(p: argparse.ArgumentParser) -> None:
    """Add --profile, --profile-top-n, --profile-output to a subcommand parser."""
    p.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable performance profiling; adds 'profiling' key to JSON output.",
    )
    p.add_argument(
        "--profile-top-n",
        type=int,
        default=50,
        metavar="N",
        dest="profile_top_n",
        help="Number of top functions to include in profiling output (default: 50).",
    )
    p.add_argument(
        "--profile-output",
        default=None,
        metavar="FILE",
        dest="profile_output",
        help="Write cProfile .prof binary to FILE (for use with snakeviz).",
    )
```

- [ ] **Step 7.4: Call `_add_profile_args()` from subcommand builders**

In each `_build_*_parser()` function that wraps a parse operation, add `_add_profile_args(p)` before `p.set_defaults(func=...)`. The subcommands to update are:

- `_build_parse_parser()` (the main `parse` subcommand)
- `_build_analyze_parser()`
- `_build_dead_code_parser()`
- `_build_program_flow_parser()`

Search for `p.set_defaults(func=_cmd_parse)` and similar lines to find these builders.

- [ ] **Step 7.5: Update `_do_parse()` to pass profiling args**

In `_do_parse()` (currently lines 204–236), update the call to `parse_cobol()`:

```python
def _do_parse(args: argparse.Namespace) -> Any:
    """Shared parse logic used by parse and analyze subcommands."""
    source = _read_source(args.file)
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)

    copybook_paths = getattr(args, "copybook_path", [])
    defines = _parse_defines(getattr(args, "define", []))

    if defines:
        from ..preprocess import preprocess_conditional_compilation
        source = preprocess_conditional_compilation(source, defines)

    enable_profiling: bool = getattr(args, "profile", False)
    top_n: int = getattr(args, "profile_top_n", 50)
    prof_output: str | None = getattr(args, "profile_output", None)

    parse_kwargs: dict[str, Any] = {
        "dialect": dialect,
        "error_recovery": error_recovery,
        "free_form": getattr(args, "free_form", False),
    }

    if copybook_paths:
        from ..preprocess.copybook_expander import parse_cobol_with_expansion
        result = parse_cobol_with_expansion(
            source,
            filename=args.file,
            copybook_paths=copybook_paths,
            **parse_kwargs,
        )
        profiling_result = None
    elif enable_profiling:
        result, profiling_result = parse_cobol(
            source,
            filename=args.file,
            enable_profiling=True,
            top_n=top_n,
            prof_output=prof_output,
            **parse_kwargs,
        )
    else:
        result = parse_cobol(source, filename=args.file, **parse_kwargs)
        profiling_result = None

    return result, profiling_result
```

Note: `_do_parse()` now returns a `(ParseResult, ProfilingResult | None)` tuple. All callers must be updated.

- [ ] **Step 7.6: Update `_cmd_parse()` to unpack the new tuple and merge profiling**

Replace the current `_cmd_parse()` (lines 239–274) with:

```python
def _cmd_parse(args: argparse.Namespace) -> None:
    result, profiling_result = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    # --find-type: query AST by node type
    if args.find_type:
        matched = result.ast.find_all_by_type(args.find_type)
        output: Any = [n.to_dict() for n in matched]
        _json_out(output, args.compact, getattr(args, "output", None))
        return

    # Resolve path or output full AST
    if args.path:
        output = _resolve_path(result.ast, args.path)
    else:
        output = result.ast.to_dict()

    # Wrap with errors/stats if requested
    if args.errors or args.stats:
        wrapper: dict[str, Any] = {"ast": output}
        if args.errors:
            wrapper["errors"] = [str(e) for e in result.errors]
            wrapper["warnings"] = result.warnings
        if args.stats:
            wrapper["statistics"] = {
                "lines_processed": result.statistics.lines_processed,
                "tokens_processed": result.statistics.tokens_processed,
                "parse_time_seconds": result.statistics.parse_time_seconds,
                "memory_peak_mb": result.statistics.memory_peak_mb,
            }
        output = wrapper

    # Merge profiling into output dict
    if profiling_result is not None:
        if not isinstance(output, dict):
            output = {"result": output}
        output["profiling"] = profiling_result.to_dict()

    _json_out(output, args.compact, getattr(args, "output", None))
```

- [ ] **Step 7.7: Update other `_cmd_*` functions that call `_do_parse()`**

Run `grep -n "_do_parse" cobolparser/cli/parse.py` to find all callers. The known callers beyond `_cmd_parse` are `_cmd_analyze`, `_cmd_dead_code`, and `_cmd_program_flow`. In each, the current pattern is:

```python
result = _do_parse(args)
```

Replace with:

```python
result, _profiling = _do_parse(args)
```

These subcommands capture profiling but don't display it (`_profiling` is discarded). This keeps the unpacking consistent with `_cmd_parse` and avoids `ValueError: too many values to unpack`.

- [ ] **Step 7.8: Run CLI tests**

```
python -m pytest tests/integration/test_profiling_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 7.9: Run full test suite**

```
python -m pytest tests/ -v -q
```

Expected: all tests pass, coverage >= 81%.

- [ ] **Step 7.10: Commit**

```bash
git add cobolparser/cli/parse.py tests/integration/test_profiling_cli.py
git commit -m "feat: add --profile, --profile-top-n, --profile-output CLI flags to parse subcommand"
```

---

## Verification Checklist

- [ ] `python -m pytest tests/unit/test_profiling.py tests/integration/test_profiling_api.py tests/integration/test_profiling_cli.py -v` — all pass
- [ ] `parse_cobol(src, enable_profiling=True)` returns `tuple[ParseResult, ProfilingResult]`
- [ ] `parse_cobol(src)` returns plain `ParseResult` (no tuple)
- [ ] `cobol-parser parse FILE --profile` outputs JSON with `"profiling"` key
- [ ] `cobol-parser parse FILE --profile --profile-output out.prof` creates `out.prof`
- [ ] `python -c "import pstats; pstats.Stats('out.prof').print_stats()"` succeeds
- [ ] `ProfilingResult.to_json()` is valid JSON; all float fields non-negative
- [ ] Without psutil: `cpu_user_s` and `cpu_system_s` are `None` in output, no exception
- [ ] `python -m pytest tests/ -v -q` — full suite passes, coverage >= 81%
