# Test Coverage Analysis — 2026-05-18

Snapshot from `coverage.json` (generated 2026-05-07, coverage.py 7.13.5, branch coverage on).

## Headline numbers

| Metric              | Covered / Total | %      |
|---------------------|-----------------|--------|
| Lines (statements)  | 13,049 / 13,660 | 92.54% |
| Branches            | 4,692 / 5,512   | 85.12% |
| Files at 100/100    | 15 / 92         | 16%    |
| Partial branches    | 728             | —      |

The 81% line floor enforced by `--cov-fail-under` is well clear, but the gap between line (~93%) and branch (~85%) coverage is the headline story: a sizeable fraction of statements only execute on the happy path. **820 branches go untaken** across the codebase.

## Coverage by package

| Package                              | Line %  | Branch % |
|--------------------------------------|---------|----------|
| `cobolparser/dialects`               | 99.51%  | 96.67%   |
| `cobolparser/plugins`                | 98.10%  | 87.50%   |
| `cobolparser/models`                 | 97.68%  | 87.04%   |
| `cobolparser/generators`             | 97.28%  | 94.03%   |
| `cobolparser/core`                   | 96.40%  | 91.03%   |
| `cobolparser/analysis`               | 95.85%  | 87.43%   |
| `cobolparser/parsers`                | 94.69%  | 81.43%   |
| `cobolparser/<root>` (batch, lexer)  | 94.27%  | 86.97%   |
| `cobolparser/preprocess`             | 94.08%  | 87.32%   |
| `cobolparser/cli`                    | 92.96%  | 80.00%   |

The two weakest packages are also the two with the most user-facing surface area: **parsers** (where bad branch coverage means parser bugs slip through) and **cli** (where untested branches are usually error paths a real user hits first).

## The 10 files we should focus on

These each fall below 90% lines *or* 80% branches and account for most of the missing coverage.

| File                                                     | Lines       | Branch      | Missing lines | Why it matters                                    |
|----------------------------------------------------------|------------:|------------:|--------------:|---------------------------------------------------|
| `cobolparser/batch.py`                                   | **61.05%** | **64.29%** | 32            | Public batch API — `parse_files_with_copybooks` mostly untested |
| `cobolparser/analysis/io_sequence.py`                    | 77.56%      | **64.29%** | 21            | OPEN/READ/WRITE/CLOSE state-machine violations    |
| `cobolparser/analysis/io_logger.py`                      | 82.31%      | 71.28%      | 22            | SQL/file/console IO collection                    |
| `cobolparser/preprocess/path_resolver.py`                | 84.93%      | 82.05%      | 19            | Security-sensitive (path traversal, size limits)  |
| `cobolparser/cli/coverage.py`                            | 85.43%      | 73.33%      | 14            | CLI subcommands — `cmd_render` (csv/output paths) |
| `cobolparser/parsers/statements/call_parser.py`          | 85.59%      | 82.50%      | 20            | `NOT ON EXCEPTION` branches, USING modifiers      |
| `cobolparser/parsers/divisions/environment.py`           | 86.87%      | **75.90%** | 20            | SELECT clause variants                            |
| `cobolparser/parsers/statements/perform_parser.py`       | 87.47%      | 86.00%      | 36            | `WITH TEST`, inline VARYING/UNTIL, TIMES          |
| `cobolparser/parsers/divisions/procedure.py`             | 87.62%      | 81.54%      | 28            | Section/paragraph boundary handling               |
| `cobolparser/parsers/statements/if_parser.py`            | 87.63%      | **78.57%** | 14            | Nested IF / `END-IF` recovery                     |

Two additional files have unusually weak branch coverage despite OK line coverage and deserve a second pass: `cobolparser/parsers/statements/unlock_parser.py` (88%/60%) and `cobolparser/parsers/statements/set_parser.py` (88%/74%).

## Concrete gaps and proposed tests

### 1. `batch.py` — the worst-covered file in the codebase (61% / 64%)

Missing lines: 78–79, 87, 118, 169–170, 212–243, 246–263. Two structural gaps:

**a. `parse_files_with_copybooks` is almost entirely uncovered.** `test_profiling_batch.py` exercises the profiling on/off branches but with empty copybook paths and a single file. We need integration tests that drive:
- A program with real `COPY` statements resolving against `tests/samples/copybooks/`.
- Multiple programs sharing the same copybook (verifies the shared cache path on lines 308–311).
- A program where copybook expansion *fails* (lines 335–337 fallback — currently 0% hit).
- The `prof_output` directory creation branch (line 290) and reusable `parser.parse(...)` with profiling enabled (lines 346–360).

**b. Multi-worker parallel paths (`resolved_workers > 1`).** Lines 231–240 are untested because all current tests either use `workers=1` (sequential fast path on line 229) or pass a pre-built executor (line 235). We need:
- A test with `workers=2` and 4+ files that proves `pool.map` is exercised (line 238–240).
- A test verifying the auto-resolved-worker branch when `workers=None` *and* `cpu_count()` returns >1 — currently neither line 212 alternative is exercised in a multi-worker scenario.

### 2. `analysis/io_sequence.py` — IO state-machine validator (78% / 64%)

Missing branches cover *real semantic conditions*, not edge cases: lines 294–311 and 319–322 (the `_get_open_files` / `_get_close_files` helpers) handle legacy AST shapes — dict entries, singular `file_name`, and the `operands` fallback. Today these are only smoke-tested via `test_io_sequence_gaps.py`; the missing branches `[290,294]` `[294,295]` `[294,305]` etc. mean we don't exercise the full chain (file_names absent → open_files absent → file_name absent → operands fallback). Specifically:

- Test OPEN/CLOSE on a node where `file_names = []` and `open_files = []` but `operands = ["X"]`. This proves the operands fallback works.
- Test OPEN where every legacy shape is empty — the function should return `[]` and `_handle_open` should not raise.
- Lines 213–214 and 233–234: whitespace-only file names in OPEN/CLOSE (the `if not file_name.strip(): continue` guard) — covered by `test_io_sequence_gaps.py` but a regression test with `"  "` (multiple spaces) and `"\t"` would lock the contract.

### 3. `analysis/io_logger.py` — IO operation collector (82% / 71%)

22 missing lines clustered around the empty-host-variables fallback (380–386), each FILE-IO statement type's `from_clause`/`record_name` branch (407–408, 425–426, 442, 475–476), and the `IOStartStatement` / `IOUnlockStatement` branches (504, 517).

Suggested: a single integration-style test that parses one COBOL program containing each statement variant (READ INTO, READ no INTO, WRITE FROM, WRITE no FROM, REWRITE, DELETE, START with key, UNLOCK record) and asserts the collected `IOOperation` list matches a snapshot. This would also future-proof the schema.

### 4. `preprocess/path_resolver.py` — security-sensitive (85% / 82%)

These gaps deserve targeted tests because they're **security paths**:

- **Line 233** — `CopybookSizeExceededError` raised from `find_copybook_file`. No test currently triggers the legacy tier-3 size check.
- **Line 83** — `PathTraversalError` re-wrap for non-traversal exceptions in `validate_path_within_directory`.
- **Lines 286–290** — `os.scandir` raises `OSError` and `entry.is_file()` is `False`. Easy to trigger with a broken symlink or unreadable dir.
- **Lines 301–305** — `_build_directory_index` with `case_sensitive=False` (current tests only exercise the case-sensitive arm). The case-insensitive branch is the real-world default for mainframe-style names.
- **Lines 344–367** — Tier 2 index hits with the case-insensitive lookup and the extension-search loop (`for ext in extensions`). Today only the slow tier-3 path is widely tested.

These are all unit-testable with `tmp_path`; no parser needed.

### 5. `cli/coverage.py` — uncovered output paths (85% / 73%)

The missing lines (82, 121–133, 149, 263, 270) are all the **output-to-file** branches: `cmd_render` when `args.output` is set, `cmd_validate` failure-listing, and the `--format csv` / `--format summary` arms. Today tests only assert successful stdout output. A single parameterised test per subcommand that round-trips through a `tmp_path` file would close most of this gap.

### 6. Parser branch coverage (parsers package — 81% branch)

A pattern emerges across the parsers: line coverage looks fine because the happy path covers most code, but recovery and modifier branches are skipped:

- `call_parser.py` — `NOT ON EXCEPTION` exists in fixtures but the `not_on_exception` body assignment (line 198) is only partially exercised. Need a test with non-empty NOT ON EXCEPTION body and assert the AST captures it. USING modifier branches (lines 290–294 in `_parse_using_clause`) are also gappy.
- `perform_parser.py` — 36 missing lines (most of any parser). The `WITH TEST BEFORE/AFTER` clause (both inline and after-paragraph-name), inline `VARYING ... FROM ... BY ... UNTIL` with non-trivial expressions, and the `n TIMES` literal coercion paths (lines 174, 224–225, 243–244). Many tests use bare PERFORM verbs; very few use combinations.
- `if_parser.py` — branch `[X, Y]` pairs around nested `ELSE`/`END-IF` recovery. Recommended fixture: a deeply nested IF with mismatched END-IFs to drive the recovery code.
- `environment.py` — SELECT clauses for `ORGANIZATION`, `ACCESS MODE`, `RECORD KEY`, `RELATIVE KEY`, `FILE STATUS`. Each has a parser branch (lines 311–332) with parallel missing branches. A single SELECT statement with all five clauses would close ~20 missing branches.
- `data.py` — 33 missing lines across LEVEL 66/88, FD/SD without level numbers (lines 230–241), and EXEC SQL DECLARE TABLE inside DATA DIVISION (lines 261–264). The DCLGEN path is documented as supported but not tested.

### 7. `unlock_parser.py` — 60% branch (smallest file, easiest fix)

Only 32 statements and 10 branches but only 6 covered. The missing branches almost certainly correspond to:
- `peek()` returning None after consuming UNLOCK,
- RECORDS keyword (plural) variant,
- UNLOCK with no period.

Three one-line test cases would push this to 100%.

## Strategic recommendations

### High-leverage, low-effort

1. **One PR for `batch.py` to ~90%.** Add ~10 integration tests across `parse_files` (multi-worker) and `parse_files_with_copybooks` (real copybooks, cache reuse, expansion failure). Closes a 30-percentage-point gap on a public-API file.
2. **One PR for `path_resolver.py` to ~95%.** All gaps are unit-testable with `tmp_path`. Closes security-relevant branches.
3. **One PR for `cli/coverage.py` and `cli/parse.py` output-to-file branches.** Same parameterised-fixture pattern across both files.

### Structural

4. **Raise the floor from 81% to 90% in two steps.** The current 81% is so far below actual (92.54%) that it provides no regression signal. Raise to 88% now (passes today, prevents drift) and 90% after the three PRs above land.
5. **Add a branch-coverage floor.** Branch coverage isn't gated. With branch at 85% but several files in the 60–75% range, branch regressions are silent. Suggest `--cov-fail-under=88` for lines *and* a separate check that no individual file drops below 75% branch (script in `tools/`).
6. **Per-file minimums for security/IO modules.** `path_resolver.py`, `io_sequence.py`, and `io_logger.py` should have stricter floors (95% line, 90% branch) — they validate invariants other code relies on.

### Test-design observations

7. **A lot of existing tests are line-driven, not contract-driven.** Files like `test_perform_coverage_gaps.py`, `test_perform_deeper_coverage.py`, `test_perform_parser_comprehensive.py` exist *because* coverage was low, but each adds shallow assertions ("parser doesn't crash"). The remaining 36 missing lines in `perform_parser.py` despite three coverage-focused test files suggests the new tests should make **semantic assertions** ("WITH TEST BEFORE sets `stmt.test_timing == 'BEFORE'`") rather than just exercising lines.
8. **Combinatorial test fixtures.** Several parsers fail to cover clause *combinations* even when individual clauses are tested. A small generator (or `pytest.mark.parametrize` matrix) for SELECT/PERFORM/CALL clause combinations would catch interaction bugs that the current one-clause-at-a-time tests miss.

## Files already at 100/100 (keep them there)

`__init__.py` files, `_errors.py`, `analysis/io_diagnostics.py`, several `models/statements/*.py`, `core/ast_factory.py`, `dialects/__init__.py`, and a handful of small leaves. These are the proof that this codebase *can* hit 100% — the long tail of 80–95% files is where the test investment will pay off.
