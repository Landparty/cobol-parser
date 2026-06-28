---
type: Test Reference
title: Tests
description: 5969 tests across 226 files with 81% coverage floor; pytest markers, fixtures, and CI matrix.
tags: [tests, pytest, coverage, ci, markers, fixtures]
timestamp: 2026-06-28T00:00:00Z
---

# Tests

> 5,969 tests across 226 files in 5 directories; 81% line coverage floor.

## Files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures: `parser()`, `samples_dir()` |
| `tests/test_all_samples.py` | Smoke-test: every file in `tests/samples/` must parse without error |
| `tests/integration/test_shamrice_examples.py` | Parametrized: all `*.cbl` in `examples/cobol/shamrice/` must parse FAIL_FAST clean |

## Directory Map

```
tests/
  conftest.py                  ← shared fixtures
  test_all_samples.py          ← smoke-tests all sample programs
  unit/                        ← unit tests — no external I/O required
    analysis/                  ← tests for all 15 analyzers
    cli/                       ← CLI subcommand tests
    generators/                ← CobolCheck and flowchart generator tests
    io_statements/             ← I/O parser unit tests
  integration/                 ← end-to-end parsing tests
    test_shamrice_examples.py  ← all shamrice/*.cbl must parse clean
    io/                        ← IO coverage reporting integration
    io_statements/             ← IO statement parsing, VSAM
  contracts/                   ← API contract tests — stability guarantees
    io_statements/             ← IO statement contracts
  regression/                  ← backward compatibility tests
  performance/                 ← benchmarks (factory, parser)
  samples/                     ← shared COBOL test fixtures
    copybook_programs/         ← programs with COPY statements
    copybooks/                 ← copybook files (.CPY)
    io/                        ← IO test samples
      positive/                ← valid IO operations
      negative/                ← invalid IO patterns
```

## Sample & Example Programs

| Directory | Contents |
|-----------|----------|
| `tests/samples/` | 48 COBOL programs covering all statement types |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + copybooks) |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs (ACCEPT variants, COMP types, SEARCH, SORT/MERGE, SQL, JSON/XML GENERATE, sub-programs) |

## Pytest Markers

| Marker | Meaning | How to run |
|--------|---------|------------|
| `integration` | Integration / end-to-end tests | `pytest -m integration` |
| `slow` | Slow-running tests | `pytest -m slow` |
| `contract` | API contract tests | `pytest -m contract` |
| `io` | I/O statement tests | `pytest -m io` |

Note: `regression/` and `performance/` have no dedicated markers — run by directory path.

## Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns | Description |
|---------|---------|-------------|
| `parser()` | `CobolParser` | Fresh parser instance with default config |
| `samples_dir()` | `pathlib.Path` | Absolute path to `tests/samples/` |

## Coverage Configuration

- **Tool:** `pytest-cov` with `--cov=cobolparser --cov-branch`
- **Floor:** `--cov-fail-under=81` (81% line coverage minimum)
- **Report:** `--cov-report=html` generates `htmlcov/` directory
- Running a subset of tests will fail the coverage check — expected behavior.

## How to Run

```bash
# All tests
python -m pytest tests/ -v

# Single file
python -m pytest tests/unit/test_lexer.py -v

# Single test
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs

# By marker
python -m pytest -m integration
python -m pytest -m "io and not slow"

# By directory (no marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/performance/ -v

# With coverage
python -m pytest tests/ --cov=cobolparser --cov-report=html

# Stop on first failure, verbose
python -m pytest tests/ -x -v
```

## CI Matrix

GitHub Actions runs on Python 3.11, 3.12, and 3.13 for each of:
1. `ruff check .` + `black --check .`
2. `mypy cobolparser/`
3. `pytest tests/ -v` (with coverage)

## Gotchas / Invariants

- `test_shamrice_examples.py` uses `ErrorRecoveryMode.FAIL_FAST` — any parse error on those 24 programs is a CI failure.
- `test_all_samples.py` parametrizes over every `.cbl` / `.cob` file in `tests/samples/` via a glob fixture.
- `performance/` contains benchmarks, not correctness tests. Not in CI by default.

## Refresh Checklist

- [ ] Verify test count (~5,969) by running `pytest tests/ --collect-only -q | grep "tests collected"`
- [ ] Check `conftest.py` for new fixtures
- [ ] Verify coverage floor (`--cov-fail-under`) in `pyproject.toml` `[tool.pytest.ini_options]`
- [ ] Check for new test markers in `pyproject.toml`
- [ ] Verify `examples/cobol/shamrice/` still has 24 `.cbl` files
