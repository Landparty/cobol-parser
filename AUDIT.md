# cobol-parser: Codebase Audit and Refactor Plan

| | |
|---|---|
| **Date** | 2026-09-27 |
| **Commit audited** | `cde5468` (`main`, after PR #231) |
| **Version** | 1.9.0 released; 1.10.0 pending in release PR #201 |
| **Scope** | `cobolparser/` (171 modules, about 80k lines), `tests/` (394 files), CI/release workflows, packaging, docs |
| **Status** | Read-only audit. No production file was changed. |

## How this audit was done

Every number below comes from something run at this commit. Anything I could
not reproduce is marked **requires validation**.

**Commands run:**
- **Tests:** `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"`, then `python -m pytest tests/ -n auto -p no:randomly`.
  - Result: **11,320 passed, 15 skipped, 1 xfailed**.
  - Coverage: **93.04%** (32,078 statements, branch coverage on).
- **Lint and types:** `ruff check .`, `black --check .` and `mypy cobolparser/`.
  - Run at the CI-pinned versions (ruff 0.15.0, black 26.3.0, mypy 1.20.0): all clean.
  - Run at the latest versions (ruff 0.16.9, black 26.5.1, mypy 2.3.1): all clean.
- **Complexity:** `radon cc` over the package. Average cyclomatic complexity is B (5.19); **99 functions are rated D–F**.
- **Security scan:** `bandit -r cobolparser`. 0 High, 1 Medium, 58 Low. After review, all are false positives or intentional (see §2.4).
- **Dependencies:** `pip-audit`. The library has **zero runtime dependencies**. The only CVEs it flagged are in the audit container's own packages (urllib3, wheel), not in anything this project pins.

**Profiling and targeted checks:**
- cProfile on the three largest NIST programs.
- Synthetic scaling programs, 500 to 2,000 paragraphs.
- A parity check of the pure-Python and Cython paths over all 562 corpus programs, with the extensions built in a scratch copy.
- A NIST corpus parse-rate run.

**Churn:** the checkout is a shallow clone with 196 commits (since 2026-08-20). Churn figures cover that window only.

**Prior audits:** `reports/open-findings.md` and four earlier audit reports exist. I re-checked their open items rather than re-reporting fixed ones, and cite the older ID where an item carries forward.

---

## 1. Executive summary

- **The codebase is healthy and well tested.**
  - 93% line+branch coverage over 11.3k passing tests.
  - Strict mypy, ruff and black are all clean.
  - Zero runtime dependencies.
  - 99.8% of the NIST COBOL-85 corpus parses cleanly (458/459; README claims 99.1%).
  - Security review found no auth, secret-handling or path-traversal problems. It did find one High DoS: the COPY scanner is quadratic in whitespace runs (§2.4).
- **One silent wrong-output bug should be fixed before 1.10.0.** A hex literal in a VALUE clause loses its `X` prefix, so `gen-data` writes `41` for `VALUE X"4142"` instead of `AB` (§2.1).
- **Three analyzers scale badly on hostile or large input.**
  - io-sequence is exponential in PERFORM nesting depth and raises `RecursionError` on a 400-paragraph PERFORM chain.
  - recursion-check is superlinear: 0.31 s at 500 paragraphs, 8.0 s at 1,500.
  - The COPY-strip preprocessor spends about 35% of total parse time on files that have no COPY statement at all.
  - All three are cheap to fix (§2.2, §3.1–3.3).
- **The main structural debt is concentration.**
  - `cli/parse.py` is 3,628 lines.
  - About 10 separate recursive statement walkers and 3 name normalizers can drift apart.
  - 99 functions are rated D–F; the worst is `DataItemClauseParser.parse_data_item` at CC 102.
  - Those same hotspots take most of the fix churn: `_utils.py` had 13 fix commits and `_normalize.py` 9, in 5 weeks.
- **Documentation and process lag the code.**
  - Seven CLI subcommands are undocumented in README and CLAUDE.md.
  - The README badges are stale.
  - A 1.4 MB stale `coverage.json` is committed.
  - The CHANGELOG `Unreleased` section runs to about 2,850 lines.
  - The pending release PR's CI shows `action_required`: it has not run (§2.3).

---

## 2. Critical issues (fix before the next release)

None of these is a security emergency. They are what I would block the 1.10.0 cut on.

### 2.1 `VALUE X"…"` loses its hex prefix, producing wrong generated data (verified)

**Evidence:** `parse_value_clause` in `cobolparser/parsers/divisions/data_clauses.py:1373` returns `quote_literal(token.value)`, which drops the literal's `X`/`N`/`Z`/`G` prefix. The data item's `value_clause` then serializes as `"4142"`, with no way to tell it apart from the alphanumeric literal `"4142"`.

**Reproduction:**

```
$ printf '01 REC.\n 05 A PIC X(2) VALUE X"4142".\n 05 B PIC X(3) VALUE "ABC".\n' > hex.cpy
$ cobol-parser gen-data hex.cpy --rows 1 --seed 1
A,B
41,ABC            <- expected AB (0x41 0x42)
```

The PROCEDURE DIVISION path is already correct: the same program's `MOVE X"4142" TO A` keeps `source: 'X"4142"'`. Only the DATA DIVISION VALUE path is affected.

The bug was spotted, and left unfixed, in commit `e45a3b6` ("Separately noted, not fixed here…").

**Impact:** anything that reads `value_clause` gets the wrong value:
- `gen-data`, `gen-fixtures`, and `ConstantFolder` seeds from VALUE clauses.
- The backend consumer, per `interface-contract.md`.

This is silent: there is no warning and no caveat.

**Fix:** keep the prefix in `parse_value_clause`, the way the MOVE path does. Then teach `unquote_literal` or `ValueFactory` to decode hex and national literals. Add a regression test that round-trips through `gen-data`.

**Effort:** S (½–1 day).

### 2.2 io-sequence analyzer: exponential time and `RecursionError` (verified)

**Evidence:** `cobolparser/analysis/io_sequence.py:372-392`.
- `_run_perform` → `_run_paragraph` → `_visit` recurses once per PERFORM level.
- The re-entrancy guard (`key in self._perform_stack`, `:383`) stops recursion but never memoizes a range it has already walked.

**Measured:**

| Input | Result |
|---|---|
| Straight PERFORM chain of 400 or 600 paragraphs | `RecursionError` |
| Each paragraph PERFORMs the next one twice, depth 12 | 0.05 s |
| Same, depth 14 | 0.16 s |
| Same, depth 16 | 0.63 s |
| Same, depth 18 | 2.59 s |

Time grows about 4× per +2 depth.

**Impact:**
- `LintAnalyzer` catches the `RecursionError` and lists `io-sequence` under `failed_rules`. So under `lint` it degrades honestly, but the `io-sequence` subcommand itself crashes.
- The exponential case can hang `lint` and `scan`, and so hang the VS Code extension's Analyze Workspace, on generated or unusual code.

**Fix:** see §3.3.

**Effort:** M (2–3 days).

### 2.3 Release gating: the release PR's CI has not run, and pushes to `main` never run the test suite (verified)

**Evidence:**
- **The release PR's CI is blocked.** GitHub Actions run 36317854780 (CI on release PR #201, "chore(main): release 1.10.0") has conclusion `action_required`. It was opened by `github-actions[bot]` and is waiting for approval, so no job has run on the release head.
- **Pushes to `main` skip the suite.** `.github/workflows/ci.yml` gates `build` and `coverage` on `if: github.event_name != 'push'` (lines 39 and 72). A push to `main` therefore runs lint and typecheck only.
- **The publish job doesn't test either.** The wheel job (`release-please.yml`, `build-binary-wheels`) runs only the cibuildwheel smoke subset: 3 test files, per `pyproject.toml`'s `test-command`.

**Impact:**
- The code that ships to PyPI is only covered by the suite through the feature PRs that were merged into it.
- A bad merge resolution, or two PRs that each pass alone but conflict semantically, would publish without a full test run.

**Fix:**
- Approve or re-run CI on #201 before merging it.
- Either run the `build` and `coverage` jobs on push to `main` too, or add `needs:` on a full-suite job to `build-binary-wheels`.

**Effort:** S (<½ day).

### 2.4 Security findings

There is no auth, payment or PII handling in this library. Its attack surface is **untrusted COBOL source, copybooks, config and data files**. Findings are ordered by severity. Items marked *verified* I re-ran myself; the rest come from the security agent's reproductions.

| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| S1 | **High** | **Quadratic-time DoS in the COPY scanner** *(verified)* | `CopyStatementLexer.tokenize_copy_statements` (`preprocess/copy_statement_parser.py:591-632`) calls `_match_keyword("COPY")` at every position. That skips the whole following whitespace run (`_skip_separators`, `:470`), fails, rewinds and advances one character. A program with `COPY OK.` plus 250 / 500 / 1,000 blank lines took **0.68 s / 2.69 s / 10.78 s** in `parse_cobol_with_expansion`, about 4× per doubling. The agent measured a 28 KB file at 168 s, and `gen-data` on a 60 KB copybook of blank lines at 112 s, because every copybook uses this lexer. The backend vendors this library. | On a failed match, jump past the whole whitespace run. Better, locate candidates with `re.finditer(r"\bCOPY\b", re.I)`. Solves §3.1 too. |
| S2 | Medium | **`max_total_size` is not checked after `REPLACING` expands the text** | `copybook_expander.py:1273-1282` counts raw copybook bytes before REPLACING. The agent ran a 48 KB copybook with `REPLACING ==XX== BY ==<long>==` under `max_total_size=1_000_000` and got **5.5 MB** of output. Under the 100 MB default, 192 KB of input produced **54 MB of output, took 54 s and used 475 MB RSS** without tripping the limit. | Enforce the limit on the post-REPLACING text and on the final assembled output. |
| S3 | Medium | **Uncaught `RecursionError` on deeply nested `EVALUATE`** *(verified)* | 1,000 nested `EVALUATE A WHEN 1`: `cobol-parser parse` exits rc=1 with a raw `RecursionError` traceback. The agent also saw 300 levels parse with `success=True` and then fail in `to_json()` (`models/statements/control.py:174`); my simpler 300-level shape serialized fine, so that half **requires validation**. IF, PERFORM and parentheses nested 3,000 deep are fine. | Cap nesting depth in the EVALUATE parser and report a `ParseError`. Catch `RecursionError` at the CLI and serialization boundary. |
| S4 | Low | **Mermaid label injection from a CALL literal** *(code verified)* | `generators/flowchart.py:337` interpolates `target` raw into `(["{target}"])`, with no `_escape_mermaid_label`. A crafted `CALL 'A"]);click …'` breaks out of the label. It is mitigated by upper-casing and Mermaid's default `securityLevel: strict`. The DOT generator escapes the same input correctly. | Apply `_escape_mermaid_label(target)`. |
| S5 | Low | **CSV formula injection** | `generators/data/decoding.py:295` and `generators/data/dataset.py:59,83` write cells starting with `= + - @` verbatim. A `VALUE "=1+1"`, or a decoded record, reaches a spreadsheet as a formula. | Add an opt-in `--safe-csv` flag, or at least document it. |
| S6 | Low | **A `cobol.yml` in any parent directory can redirect copybook reads** | `config/project.py:399-416` walks up to 32 levels with no ownership or VCS-root stop, and `:202-212` accepts absolute paths. A `copybook_path: ["/etc"]` in a parent directory made `expand` inline `/etc/hostname`. This matters on shared hosts (`/tmp/cobol.yml`) and in CI. | Stop the search at the VCS root or `$HOME`, and ignore files owned by another uid, as git's `safe.directory` does. |
| S7 | Low | **Backtracking-prone regexes** | `generators/data/copybook.py:34-35` (`^\s*` under `re.M` spans newlines) and `preprocess/_normalize.py:1047` (`(?:\s+(.*?))?\s*$`). Matched directly on 80 KB of whitespace they took 26 s and 4.4 s. | Use `[ \t]*`, and `rstrip()` before matching the tail. |
| S8 | Low | **Stray debug file shipped as package data** *(verified)* | `cobolparser/error_log.txt` is tracked in git (128 bytes of stale `DEBUG:` output) and is not excluded by `exclude-package-data`, so it would ship in wheels. | Delete it. |

**Checked and found sound:**
- **Copybook path containment.** These were all rejected with `PathTraversalError` or `CopybookNotFoundError`: `../`, absolute member and library names, symlinked directories and files, `LIB/../../`, quoted `../`, NUL bytes, backslashes and URL encoding. The only minor oracle: the error type differs by whether the file exists, and the message echoes the resolved path.
- **Copybook fan-out and cycles.** `A→B→A` raises `CircularReferenceError`. A 4¹² fan-out stops at the size limit in 1.3 s.
- **No dangerous primitives in the package.** There is no `eval`, `exec`, `pickle.load`, `subprocess`, `shell=True` or `yaml.load` in `cobolparser/`.
- **Closed-source exclusion rules** are correct, apart from S8.
- **Every bandit hit is a false positive.**
  - The `assert`s are type narrowing after existing checks, and nothing security-relevant changes under `-O`.
  - B608 at `environment_select.py:205` is a warning string, not SQL.
  - The B105 "passwords" are COBOL keywords.

**Requires validation:** whether the backend runs `parse_cobol_with_expansion` or `to_dict()` on *uploaded* source. That decides whether S1–S3 are remotely triggerable, and so their final severity.

---

## 3. High-priority refactors

| # | Refactor | Evidence | Effort |
|---|---|---|---|
| 3.1 | COPY-strip fast path | see below | S (½ day) |
| 3.2 | recursion-check: hoist per-cycle edge index | see below | S (½ day) |
| 3.3 | io-sequence: memoize and make iterative | §2.2 | M (2–3 days) |
| 3.4 | Pure-Python ↔ Cython corpus parity test; re-baseline the speedup claim | see below | S–M (1–2 days) |
| 3.5 | One statement walker and one name normalizer | see below | L (1–2 weeks, incremental) |
| 3.6 | Split `cli/parse.py` | see below | M (3–5 days) |
| 3.7 | Break up the F-rated parser functions | see below | L (ongoing, one per PR) |

### 3.1 COPY-strip fast path (measured)

**Evidence:** `cobolparser/preprocess/replace_statement.py:454` gates the full scan on `if "COPY" not in source.upper()`.
- The literal `" COPY - NOT FOR DISTRIBUTION"` and words like `COPYRIGHT` defeat that guard. They appear in every NIST program.
- The file then goes through a pure-Python, character-at-a-time scanner: `CopyStatementLexer.tokenize_copy_statements`, `preprocess/copy_statement_parser.py:591`, which calls `_match_keyword("COPY")` at every position (`:627`).

**Measured on NC105A (3,119 lines):**
- The strip step takes 74 ms against a total parse of about 200 ms, although the file contains no COPY statement.
- With `COPY` textually absent, it takes 0.1 ms.
- The profiling agent measured the same step at 36–52% of parse time on the three largest NIST files.

**Fix:** prefilter with a word-boundary regex (`\bCOPY\b`) on the non-comment text. Or, better, have the scanner jump from one regex hit to the next instead of stepping character by character.

**Related:** `_EXEC_SQL_TAIL_RE.search(self.source[:keyword_start])` (`copy_statement_parser.py:633`) copies the whole source prefix once per INCLUDE, which is O(n²) for many INCLUDEs.

### 3.2 recursion-check is superlinear (measured)

**Evidence:** `RecursionRiskAnalyzer._closed_by_perform_range_end` (`cobolparser/analysis/recursion_risk.py:194`) is called once per cycle.
- Each call rebuilds `pair_edges` from *every* flow edge (`:220-223`).
- It then runs an O(hops²) i/j loop (`:230-236`).

**Measured on synthetic programs:**

| Paragraphs | Time |
|---|---|
| 500 | 0.31 s |
| 1,000 | 1.01 s |
| 1,500 | 8.03 s |
| 2,000 | 22.75 s (profiling agent's run, under load) |

`classify_cycles` (`program_flow/cycles.py:80`) also grows about 4× per doubling.

**Fix:** build `pair_edges` once per report and precompute each paragraph's set of PERFORM-range ends.

### 3.3 io-sequence: memoize and make iterative

**Fix:**
- Replace the Python recursion with an explicit work stack.
- Cache the effect of a `(start, end)` PERFORM range on file state, so an identical range is replayed from the cache rather than re-walked.

**Minor cleanups in the same file:**
- `_pending_gotos.pop(0)` (`io_sequence.py:295`) should be a `deque`.
- `_perform_stack` membership (`:383`) should be tested against a companion set.

### 3.4 Cython parity and the speedup claim (measured)

The accelerators are `_lexer_fast.pyx`, which overrides 6 lexer methods, and `_preprocess_fast.pyx:99`, which is a full 510-line **reimplementation** of `normalize_fixed_format`.

**What is tested today:**
- Parity is guarded only by per-bug regression tests, for example `tests/regression/test_normalize_line_number_preservation.py:88,152`.
- Most of those skip when the extensions aren't built.
- A full-corpus comparison run for this audit (562 programs; normalize output, tokens, `to_dict()`, errors and warnings) found **0 differences today**. Co-change discipline is good: 9 of 9 preprocess `.pyx` commits also touched `_normalize.py`.

**The speedup claim doesn't hold:**
- `tests/performance/bench_cython_vs_pure.py:171` asserts at least 3.0×.
- It measured **1.34×**, failing its own threshold.
- It is never run: the filename doesn't match `python_files = ["test_*.py"]` (`pyproject.toml:80`).
- Across the corpus: lexer 6.27 s fast vs 6.47 s pure; normalize 0.59 s fast vs 0.52 s pure.
- These timings were taken on a loaded machine, so treat them as indicative. Even so, the documented "~3x lexer speedup" (`setup.py` docstring) is not reproduced.

**Fix:**
- Add a `test_cython_parity.py` that diffs both paths over `examples/cobol` in the `build` CI job.
- Either rename the benchmark so it runs, or delete its 3× assertion and re-baseline the claim in CLAUDE.md and `setup.py`.

**Also noted:** `lexer.py:2137` still says the subclass "overrides the three" methods; it overrides six.

### 3.5 Consolidate statement walkers and name normalization (judgement, grounded in code)

**Statement walkers.** `CobolProgram.get_all_statements` (`models/program.py:424`) is used by 25 modules. About 10 other modules hand-roll their own recursive walk, each with its own list of nested-clause attributes:
- `sql_cics_lint.py:1010`
- `ast_diff.py:643`
- `constraints.py:1326`
- `const_fold.py:521`
- `io_sequence.py:341`
- `boundary_inventory.py:413,465`
- `complexity.py:341`
- `program_flow/scanner.py:252`

Two of those lists already differ: `scanner.py:41 _CLAUSE_BODY_ATTRS` has 10 entries and `const_fold.py:141 _HANDLER_BODY_ATTRS` has 12. That is exactly the kind of drift behind the 2026-08 "paragraph-swallow" class of bugs.

**Name normalizers.** There are three with different semantics:
- `analysis/_names.py:31 base_data_name` splits on whitespace, so `WS-TAB(3)` comes back unchanged.
- `const_fold.py:173 _base_name` is regex-based.
- `sql_cics_lint.py:1154 _normalize_name`.

**Fix:** give `ASTNode` or `CobolStatement` one `iter_child_statements()` that owns the clause-attribute list, and move every analyzer onto it and onto `_names.py`.

### 3.6 Split `cli/parse.py` (3,628 lines, 99 functions, 34 `_cmd_*` handlers)

It is already partly factored: `_parse_or_fail` is at `:459` with 17 call sites, and `_emit_report` is at `:290`.

What remains:
- Near-copy handlers, such as `_cmd_io_sequence`, `_cmd_move_type_check` and `_cmd_linkage_check` (`:2332-2372`), that could be table-driven.
- Large option builders: `_build_gen_data_parser` (169 lines) and `_build_decode_parser` (142 lines).

It is also the highest-churn file in the window: 25 commits.

**Fix:** split into a `cli/commands/{parse,analyze,data,codebase,jcl}.py` package, with a registry of `(name, analyzer, method)` for the simple analyzer commands.

### 3.7 F-rated functions (radon)

The top five, which are also churn hotspots:

| Function | Location | CC |
|---|---|---|
| `DataItemClauseParser.parse_data_item` | `data_clauses.py:266` | F (102) |
| `PerformStatementParser.parse` | `perform_parser.py:150` | F (86) |
| `CallStatementParser.parse` | `call_parser.py:35` | F (74) |
| `XrefAnalyzer._data_statement_roles` | `xref.py:987` | F (69) |
| `_CobolLexerPure.tokenize_program_text` | `lexer.py:1094` | F (64) |

**Fix:** extract per-clause handlers into a dispatch table, one function per PR, with no behaviour change. The existing suite is strong enough to make that safe.

---

## 4. Medium-priority improvements

| # | Issue | Evidence | Effort |
|---|---|---|---|
| 4.1 | **Seven CLI subcommands are undocumented** in README and CLAUDE.md: `diff`, `codebase-graph`, `copybook-impact`, `jcl`, `program-signature`, `xref`, `sql-cics-check` | registered at `cli/parse.py:2739, 2823, 2926, 2992, 3538, 3551, 3563`; only `.okf/cli.md` lists them | S |
| 4.2 | **README is stale.** It says "8000+ tests" (actual 11,320), "coverage 81%+ enforced" (actual floor 90%) and "99.1% NIST" (measured 99.8%). Install omits `pip install cobol-parser` and `COBOLPARSER_SKIP_EXT` | `README.md:3,6,7` | S |
| 4.3 | **A stale `coverage.json` is committed** (1.45 MB; 92.44% over 14,946 statements, dated 2026-07-09) and is not in `.gitignore` | `coverage.json`; `.gitignore:45-53` | S |
| 4.4 | **The CHANGELOG `Unreleased` section runs to about 2,854 lines** (`CHANGELOG.md:8`–`2861`), and a second stale `## [Unreleased]` sits at `:4311`. Whether release-please folds a hand-written Unreleased block into the release or strands it above new entries **requires validation** against PR #201's diff | `CHANGELOG.md` | S |
| 4.5 | **`scan` silently drops copybook-expansion failures.** `except Exception: pass` falls back to an unexpanded parse with no caveat, although `batch.py:363` logs the same case. Users see analyzer results for code with its copybooks missing | `cobolparser/scan.py:320-324` | S |
| 4.6 | **The containment check on the indexed-extension path is untested.** Uncovered: `path_resolver.py:454-462` (index lookup with an extension → `_validate_indexed_result`), plus `:210-215` and `:352-353` | coverage JSON | S |
| 4.7 | **`MemoryConfiguration.max_memory_mb` is advertised but not enforced.** The docstring admits it (`plugins/core.py:34-42`), but CLAUDE.md's Public API example and `__init__.py:18` present it as a working limit | as cited | S (docs) / M (enforce) |
| 4.8 | **Generic exceptions become `ParseError` at line 1, col 1**, logged only at DEBUG, so the real location and type are lost | `cobolparser/parser.py:627-632` | S |
| 4.9 | **Lowest-covered parsers** by branch: `data_report_description.py` 78.1%, `set_parser.py` 78.8%, `procedure_boundaries.py` 81.7%, `data_special_entries.py` 82.4%, `if_parser.py` 83.4%. Prior item M17 has improved: `data.py` now has 11 missing lines and 25 missing branches, `environment.py` 4 and 4 | coverage JSON | M |
| 4.10 | **The parse-error fallback for COMPUTE and PERFORM UNTIL drops the expression tree** with no warning, so downstream analyzers silently lose structure | `arithmetic_parsers.py:822`, `perform_parser.py:56` | S |
| 4.11 | **191 function-local imports**, 9 of them commented as avoiding circular imports (e.g. `models/program.py:820,1151`, `analysis/__init__.py:10`). These are latent cycles between models, analysis, plugins and generators | grep | M |

---

## 5. Low-priority nice-to-haves

| # | Item | Evidence |
|---|---|---|
| 5.1 | **Deprecated API:** `datetime.utcnow()` is deprecated since Python 3.12 (CI tests 3.12 and 3.13) | `analysis/io_coverage_reporter.py:261,287`; `tools/metrics/io_ticket_tracker.py:25-28`; `tools/io_coverage/generate_artifact.py:187` |
| 5.2 | **Deprecated test pattern:** class-scoped fixtures defined as instance methods raise `PytestRemovedIn10Warning`; enum classes named `Test*` raise `PytestCollectionWarning` | `tests/unit/test_ims_segment_analyzer.py:1106,1115,1209,1218,1291,1300`; `tests/contracts/test_evaluate_coverage_gate.py:35`; `analysis/io_coverage_reporter.py:27` |
| 5.3 | **Dead code, still present** (re-verified from `open-findings.md`): `TokenType.ALL` has zero uses (`lexer.py:94`); `_compress_doubled_quotes` is test-only (`lexer.py:1568`); `parse_picture_clause_fast` (`_data_fast.pyx:25`, prior P-C1); `peek_value` and `get_error_recovery_mode` have no callers (`parsers/statements/_utils.py:563,1013`); `CobolFileDescription` is never instantiated (`models/program.py:947`) | grep |
| 5.4 | **Dead config:** the `docs` extra installs Sphinx, but there is no `conf.py` anywhere (`pyproject.toml:40-43`). The `[[tool.mypy.overrides]]` for `tests.*` never applies, and mypy 2.x now warns "unused section" (`pyproject.toml:238`) | as cited |
| 5.5 | **Legacy `typing` imports** (`Optional`/`List`/…) in 6 modules with 24 uses, against the style guide's `X \| None` / `list[]` | `models/ast_base.py:13`, `core/interfaces.py:4`, `models/program.py`, `models/statements/{base,arithmetic,control}.py` |
| 5.6 | **Dev tool floors are loose** (`ruff>=0.1.0`, `black>=23`, `mypy>=1.5`) while CI pins exact versions. A local `pip install -e .[dev]` got ruff 0.16.9, black 26.5.1 and mypy 2.3.1. Clean today, but lint drift is possible | `pyproject.toml:31-39` vs `ci.yml:21,32` |
| 5.7 | **cibuildwheel is pinned at v2.21.3.** Whether a newer major exists, and whether Python 3.14 wheels are wanted, **requires validation** | `release-please.yml` |
| 5.8 | **`ProfilerContext` never calls `tracemalloc.reset_peak()`,** so it over-reports peak memory when tracemalloc is already running (prior LOW, still reproduces by inspection) | `profiling.py:84-104` |
| 5.9 | **Small O(n) patterns:** `path.insert(0, …)` in a loop (`models/ast_base.py:200`) | — |
| 5.10 | **`CLAUDE.md` is 61 KB and duplicates the OKF.** Stale counts: "34 statement parser files" (actual 33 verb files plus 2 helpers); "~11,140 tests / 389 files" (actual 11,336 collected / 394 files) | `CLAUDE.md:66,171,545` |
| 5.11 | **The pre-commit config runs both `ruff-format` and `black`,** a latent formatter conflict (prior T-misc) | `.pre-commit-config.yaml` |

---

## 6. Areas that are actually well built

- **Correctness culture.** Earlier audits are fixed and pinned by named regression suites (`tests/regression/test_audit_2026_09_*.py`). Recent fixes are checked against GnuCOBOL as an oracle; see the commit messages for `fe6156d`, `253ae40` and `a8f666a`.
- **Honest reporting by design.** Analyzers report what they could not check (`LintReport.caveats` / `failed_rules`, `DclgenReport.unchecked`, `ProgramLayoutIndex.unresolved`, `ScenarioCoverage` with a reason on every miss). A quiet report is never mistaken for a clean program. That is rare and valuable in static-analysis tooling.
- **Type and lint hygiene.** Strict mypy (`disallow_untyped_defs`, `warn_unreachable`, `strict_equality`) is clean across 171 modules at both the pinned and the latest tool versions.
- **Zero runtime dependencies.** That includes a stdlib-only strict YAML-subset reader (`config/_yaml.py`) that *rejects* anchors, tags and duplicate keys with a line number instead of guessing.
- **Fault isolation.** `batch.py` and `scan.py` isolate failures per file and per analyzer, so one bad program or one crashing rule does not cost the rest of the report.
- **Cython parity.** There were zero behavioural differences across 562 programs, and the checked-in `.c` files are regenerated in the same commits as their `.pyx`.
- **Closed-source packaging.** It is careful and self-verifying: a leak check runs against every one of the 9 built wheels, and `setup.py` has a well-documented directive split after a real segfault root-cause.
- **Knowledge management.** The OKF bundle plus a staleness map is test-enforced (`tests/test_okf_staleness_map.py`, 28 passing) and pre-commit gated. Documentation for internals is *more* current than the user-facing README.
- **Test breadth.** There are unit, integration, contract, regression and performance tiers, plus a NIST corpus and one enterprise program per IBM program type (`tests/samples/enterprise/`).

---

## 7. Risk matrix

**Likelihood** is how likely the issue is to bite a real user in the next release cycle, and **Impact** is how bad it is when it does. Both are scored 1–5. **Score = L × I**: 15 or more is Critical, 8–14 High, 4–7 Medium, 3 or less Low.

| ID | Finding | L | I | Score | Band | Effort |
|---|---|---|---|---|---|---|
| 2.1 | Hex VALUE prefix lost; wrong generated data | 3 | 5 | **15** | Critical | S |
| 2.3 | Release PR CI not run; no full suite on `main` | 3 | 5 | **15** | Critical | S |
| 2.2 | io-sequence exponential / RecursionError | 3 | 4 | **12** | High | M |
| 3.1 | COPY-strip ~35% of parse on COPY-less files | 5 | 2 | **10** | High | S |
| 3.2 | recursion-check superlinear (8 s at 1.5k paragraphs) | 3 | 3 | **9** | High | S |
| 3.5 | ~10 divergent statement walkers / 3 name normalizers | 3 | 3 | **9** | High | L |
| 4.5 | `scan` hides copybook-expansion failure | 3 | 3 | **9** | High | S |
| 3.4 | No corpus parity test; 3× speedup claim not reproduced | 2 | 4 | **8** | High | S–M |
| 3.7 | F-rated parser functions are churn hotspots | 4 | 2 | **8** | High | L |
| 4.6 | Untested path-containment branch | 2 | 4 | **8** | High | S |
| 4.1/4.2 | Undocumented subcommands, stale README | 5 | 1 | **5** | Medium | S |
| 4.4 | CHANGELOG structure vs release-please | 2 | 2 | **4** | Medium | S |
| 4.7 | Advertised-but-unenforced memory limit | 2 | 2 | **4** | Medium | S |
| 4.8 | Exceptions collapse to line 1 col 1 | 2 | 2 | **4** | Medium | S |
| 3.6 | `cli/parse.py` size | 3 | 1 | **3** | Low | M |
| 5.1 | `datetime.utcnow()` deprecation | 2 | 1 | **2** | Low | S |
| 5.3 | Dead code (5 items) | 1 | 1 | **1** | Low | S |

Security rows (same scale):

| ID | Finding | L | I | Score | Band | Effort |
|---|---|---|---|---|---|---|
| S1 | Quadratic COPY scanner (DoS) | 3 | 5 | **15** | Critical | S |
| S2 | REPLACING bypasses `max_total_size` | 2 | 4 | **8** | High | S |
| S3 | Nested EVALUATE → RecursionError | 2 | 3 | **6** | Medium | S |
| S6 | Parent-dir `cobol.yml` hijack | 1 | 3 | **3** | Low | S |
| S4/S5 | Mermaid / CSV output injection | 1 | 2 | **2** | Low | S |
| S7 | Backtracking regexes | 1 | 2 | **2** | Low | S |
| S8 | Stray `error_log.txt` in package | 2 | 1 | **2** | Low | XS |



---

## 8. Recommended order of work (proposal only; nothing has been changed)

1. **Before 1.10.0:**
   - Fix 2.1 (hex VALUE), with a regression test.
   - Get CI to run on #201 (2.3).
   - Fix S1 (quadratic COPY scanner, which also delivers the §3.1 speedup), S2 (post-REPLACING size limit) and S8 (stray file).
2. **Next sprint:**
   - Performance fixes 3.1, 3.2 and 3.3, each with a scaling test that asserts a time bound.
   - The corpus parity test (3.4).
   - Surface the scan copybook failure as a caveat (4.5).
   - Cover the path-resolver branch (4.6).
3. **Ongoing:**
   - Walker and normalizer consolidation (3.5).
   - The CLI split (3.6).
   - F-function decomposition (3.7), one PR each.
   - Docs refresh (4.1–4.4).
   - Low items as drive-bys.
