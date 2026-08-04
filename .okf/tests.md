---
type: Reference
title: Tests
description: Test layout, pytest markers, coverage floor (81%), and shared fixtures for the cobolparser test suite.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-08-04T00:00:00Z
---

# Overview

7,793 passed / 13 skipped / 1 xfailed (2026-08-04: +454 tests across Phases
1-7 of the `gen-fixtures` program-scoped test-data initiative —
`ProgramLayoutIndex` (Phase 1), `BoundaryInventoryAnalyzer` (Phase 2),
`ProgramFixtureGenerator` + the `gen-fixtures` CLI subcommand (Phase 3),
`ConstraintExtractor` + the `domains.py` solver (Phase 4), `ScenarioPlanner`
(Phase 5), wiring `--scenarios branches|all` into a populated
`FixtureBundle` plus a hand-written schema doc (Phase 6, +15 tests: see
`docs/fixture-bundle-schema.md`), and per-scenario tier 1/2 `Expectation`s —
`call_count` derived exactly from each scenario's own generated sequence,
`field_equals` from the new `analysis.const_fold.ConstantFolder` single-pass
walk seeded with that scenario's own mocked inputs (Phase 7, +104 tests:
`test_const_fold.py` (44 unit tests over MOVE/arithmetic/COMPUTE folding,
loop/branch poisoning, PERFORM chaining, control-flow stops, and the
ACCEPT/READ/DISPLAY/WRITE observation boundary), `test_const_fold_corpus.py`
(50 tests parametrised over `examples/cobol/shamrice/*.cbl`, plus an ad hoc
sweep of the full 459-file NIST corpus given the higher correctness stakes
of arithmetic folding — that sweep surfaced and fixed a latent `IndexError`
in Phase 1's `ProgramLayoutIndex.resolve()` on an all-punctuation name), and
+10 in `test_program_fixtures.py` for `TestTier1CallCountExpectations` and
`TestTier2FieldEqualsExpectations`); see [generators.md](generators.md) and
[analysis.md](analysis.md). Phase 4 also fixed a pre-existing, unrelated
parser bug it uncovered: `>=`/`<=`/`<>` were silently mis-parsed as
`>`/`<`/`<` with a garbled operand in every IF/PERFORM UNTIL condition (see
[parser.md](parser.md)) — zero regressions across the 783 IF/PERFORM/
shamrice/NIST tests re-run after that fix. Earlier,
2026-07-09: CobolCheck test generation — `CoverageAnalyzer`,
`TestPlanGenerator`, `CobolCheckGenerator`, the `generate-tests` CLI
subcommand, and their ~180 dedicated tests — was removed, superseded by
the mockymock framework. Earlier the same day: +30 in
`tests/regression/test_open_findings_medium_regressions.py`, one test
class per MEDIUM finding M1, M2, M3, M4, M5, M7, M8, M9, M14, M16 fixed
that day, plus a Cython/pure-Python parity check — see
[parser.md](parser.md)'s "open-findings.md MEDIUM-severity fixes"
section and [preprocessing.md](preprocessing.md)/[lexer.md](lexer.md)
for the M4/M5/M7/M8/M14 write-ups; also includes the earlier same-day +21
in `tests/regression/test_open_findings_high_regressions.py` for HIGH
findings H1-H8). Coverage floor: **81% line coverage** enforced by
`--cov-fail-under=81` in `pyproject.toml`; full-suite run measured
91.43%. Branch coverage is enabled.

Running only a subset of tests will trigger a coverage failure — that is expected.

# Directory Layout

```
tests/
  conftest.py                  # shared fixtures: parser(), samples_dir()
  test_all_samples.py          # smoke-tests all sample COBOL programs
  unit/                        # individual components
    analysis/                  # IO coverage reporter, diagnostics, all analyzers
    cli/                       # CLI command tests
    generators/                # Flowchart generator tests
    test_copybook_data_generator.py  # copybook -> CSV: flattening, categories, value constraints, options, dataset surface
    test_program_layout_index.py  # ProgramLayoutIndex: FD/record resolution, FD-vs-SD tagging, FileFacts, name resolution, record_named(), multi-program units, from_file errors (see generators.md)
    test_program_fixtures.py  # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON byte-for-cell round trip, one directory per scenario), TestScenarioModes: witness pinning / empty-input / boundary min-max / scenario_coverage presence, TestTier1CallCountExpectations, TestTier2FieldEqualsExpectations: call_count/field_equals wiring end-to-end (see generators.md)
    test_scenario_planner.py  # ScenarioPlanner: THEN/ELSE targeting, disjoint-field merging, unsatisfiable-arm handling, fixed families (empty-input/error-status/boundary-values), exact coverage accounting (see generators.md)
    io_statements/             # IO parser unit tests
    cli/
      test_gen_fixtures_cli.py  # gen-fixtures: flags, --list-boundaries, --format json|csv-dir, --strict exit codes (see cli.md)
    analysis/
      test_boundary_inventory.py  # BoundaryInventoryAnalyzer: per-category key/layout/direction, nested-body reachability (IF/EVALUATE/SEARCH), CALL argument-direction ladder, ACCEPT filtering, IOLogger cross-check (see analysis.md)
      test_constraints.py  # ConstraintExtractor: relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan, EVALUATE TRUE + 88s, WHEN OTHER, SEARCH WHEN, PERFORM-UNTIL SequenceConstraint (see analysis.md)
      test_domains.py  # domains.solve(): numeric/text/enum domains, witness-satisfies-constraint property, Unsatisfiable never returns a value (see analysis.md)
      test_const_fold.py  # ConstantFolder: MOVE/ADD/SUBTRACT/MULTIPLY/COMPUTE folding, GIVING forms, loop/branch write-poisoning, DIVIDE's unconditional poison, the ADD-X-TO-X self-reference gap, PERFORM (inline/paragraph/THRU) chaining, GO TO/STOP RUN stopping the walk, ACCEPT/READ preserving a seeded value, DISPLAY/WRITE as the only observation points (see analysis.md)
  integration/                 # end-to-end parsing
    test_shamrice_examples.py  # parametrised: all *.cbl in examples/cobol/shamrice/ must parse error-free
    test_nist_cobol85_support.py  # parametrised: all 459 NIST *.CBL must parse error-free (strict-xfail KNOWN_ISSUES ratchet); copybook validation
    test_copybook_csv_generation.py  # parametrised over the sample + NIST *.CPY corpora: no copybook may crash gen-data; a copybook with no record layout must raise CopybookLayoutError, and every generated cell must be assignable to its field (see generators.md)
    test_program_layout_corpus.py  # parametrised over examples/cobol/shamrice/: ProgramLayoutIndex must build without raising and report zero unexpected unresolved/ambiguities entries
    test_boundary_inventory_corpus.py  # parametrised over examples/cobol/shamrice/: BoundaryInventoryAnalyzer must build without raising and report zero unexpected unresolved entries
    test_gen_fixtures_corpus.py  # parametrised over examples/cobol/shamrice/: ProgramFixtureGenerator must build a bundle without raising, every generated cell fits its field's category, and determinism holds across the corpus
    test_constraint_extractor_corpus.py  # parametrised over examples/cobol/shamrice/: every branch/loop either produces constraints or a reason in unsupported (no silent drop); every solved witness is layout-valid (see analysis.md)
    test_scenario_planner_corpus.py  # parametrised over examples/cobol/shamrice/ x {branches,all}: coverage accounting sums to the arm count for every program; every miss/merge carries a reason/target (see generators.md)
    test_const_fold_corpus.py  # parametrised over examples/cobol/shamrice/: ConstantFolder must fold without raising, and every known value is layout-valid (also smoke-tested ad hoc against the full 459-file NIST corpus -- see analysis.md)
    io/                        # IO coverage reporting integration
    io_statements/             # IO statement parsing, VSAM
  contracts/                   # API contract tests — stability guarantees
    test_fixture_bundle_contract.py  # FixtureBundle: exported names, bundle_version, generator signatures, to_dict() key sets, reproducibility; TestScenarioModeContract: generate_with_scenarios(_from_file) signatures, happy-mode byte-identity with generate, scenario_coverage population/absence, seed reproducibility, unknown-mode ValueError (see generators.md, docs/fixture-bundle-schema.md)
    io_statements/
  regression/                  # backward compatibility
                               #   test_swallow_sweep.py: generic cross-product
                               #   sweep -- one period-less snippet per
                               #   registered statement parser x a DISPLAY
                               #   'MARKER'. sentinel, asserting the marker
                               #   survives as CobolParagraph's next top-level
                               #   statement. Fails automatically if a new
                               #   parser is registered without a fixture
                               #   (2026-07-21) -- see parser.md's "Generic
                               #   swallow-sweep regression" section
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
                               #   test_open_findings_high_regressions.py:
                               #   H1-H8 from reports/open-findings.md (SET
                               #   ADDRESS OF, COMPUTE unbalanced parens, PERFORM
                               #   trailing-identifier + bare excepts, MoveType-
                               #   Checker unresolved_count, PathResolver Tier-2
                               #   containment, lexer unterminated-string warning,
                               #   CLOSE combined per-file options) (2026-07-09)
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
* [generators.md](generators.md) — flowchart, copybook → CSV, program layout
  index, and program fixture bundle generator tests
* [analysis.md](analysis.md) — `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) — `tests/integration/` covers end-to-end parsing
