---
type: Reference
title: Tests
description: Test layout, pytest markers, coverage floor (81%), and shared fixtures for the cobolparser test suite.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-07-08T00:00:00Z
---

# Overview

~6,738 tests across 242 files in 5 directories (2026-07-09: +13 in
`tests/regression/test_tier6_silent_drop_audit.py`, which also pins that
`REWRITE ... FROM` / `START ... KEY` operands land in the node's `operands`
list). Coverage floor: **81% line coverage**
enforced by `--cov-fail-under=81` in `pyproject.toml`. Branch coverage is enabled.

Running only a subset of tests will trigger a coverage failure — that is expected.

# Directory Layout

```
tests/
  conftest.py                  # shared fixtures: parser(), samples_dir()
  test_all_samples.py          # smoke-tests all sample COBOL programs
  unit/                        # individual components
    analysis/                  # IO coverage reporter, diagnostics, all analyzers
    cli/                       # CLI command tests
    generators/                # CobolCheck and flowchart generator tests
    io_statements/             # IO parser unit tests
  integration/                 # end-to-end parsing
    test_shamrice_examples.py  # parametrised: all *.cbl in examples/cobol/shamrice/ must parse error-free
    test_nist_cobol85_support.py  # parametrised: all 459 NIST *.CBL must parse error-free (strict-xfail KNOWN_ISSUES ratchet); copybook validation
    io/                        # IO coverage reporting integration
    io_statements/             # IO statement parsing, VSAM
  contracts/                   # API contract tests — stability guarantees
    io_statements/
  regression/                  # backward compatibility
                               #   test_evaluate_traversal_regression.py:
                               #   EVALUATE WHEN branches must be AST children
                               #   (find_all_by_type reaches nested statements;
                               #   duplicate WHEN OTHER reuses one default clause)
                               #   test_tier5_silent_drip_audit.py: SORT/MERGE/
                               #   ENTRY/CALL-handler silent-drop fixes (2026-07-08)
                               #   test_normalize_line_number_preservation.py:
                               #   normalize_fixed_format / preprocess_conditional_
                               #   compilation line-number preservation + Cython
                               #   parity (2026-07-08)
  performance/                 # benchmarks (factory, parser)
  samples/                     # shared COBOL fixtures
    copybook_programs/         # programs with COPY statements
    copybooks/                 # .CPY files
    io/
      positive/                # valid IO operations
      negative/                # invalid IO patterns
```

# pytest Markers

| Marker | Meaning |
|--------|---------|
| `integration` | Integration tests |
| `slow` | Slow-running tests |
| `contract` | API contract tests |
| `io` | IO statement tests (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK) |

```bash
python -m pytest -m "integration"    # integration tests only
python -m pytest -m "slow"           # slow tests only
python -m pytest -m "contract"       # API contract tests only
python -m pytest -m "io"             # IO statement tests only
```

# Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns |
|---------|---------|
| `parser()` | Fresh `CobolParser` instance |
| `samples_dir()` | `Path` to `tests/samples/` |

# Running Tests

```bash
# All tests with coverage (81% min)
python -m pytest tests/ -v

# Single file
python -m pytest tests/unit/test_lexer.py -v

# Single test
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs

# By directory (no dedicated marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/contracts/ -v
python -m pytest tests/performance/ -v
```

# Example Corpora

| Path | Contents |
|------|----------|
| `tests/samples/` | ~48 COBOL programs covering all statement types |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + 51 .CPY copybooks); 457/459 parse error-free — pinned by `test_nist_cobol85_support.py` (2 strict-xfail `KNOWN_ISSUES`: OBNC1M needs Area A/B awareness, SM101A needs copybook expansion by design; both SM101A and SM207A parse clean with expansion). Minimal repros for the fixed edge cases live in `tests/regression/test_nist_edge_case_fixes.py` |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs from shamrice/COBOL-Examples; all parse cleanly under FAIL_FAST |

# Coverage Requirement Detail

From `pyproject.toml`:

```toml
addopts = [
    "--strict-markers",
    "--cov=cobolparser",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=81",
]
```

Branch coverage is also enabled (`[tool.coverage.run] branch = true`).
Stored baselines live in `baselines/` (`current-coverage.json`, `final.json`).

# CI/CD

GitHub Actions (`.github/workflows/ci.yml`) on push/PR to `main`:

1. **lint** — `ruff check .` + `black --check .` (Python 3.13)
2. **typecheck** — `mypy cobolparser/` (Python 3.13)
3. **test** — `pytest tests/ -v` on matrix: Python 3.11, 3.12, 3.13

# See Also

* [cli.md](cli.md) — `tests/unit/cli/` covers CLI subcommands
* [analysis.md](analysis.md) — `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) — `tests/integration/` covers end-to-end parsing
