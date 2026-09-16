# cobolparser — Open Findings (as of 2026-09-09, post-review)

> **Status of `reports/audit-2026-09-16.md`:** all four findings in that
> pass are **fixed at HEAD** — the HIGH `ConstantFolder` one (both halves of
> the "exact by construction" gate decided exactness in inexact decimal
> arithmetic, so a COMPUTE could fold to a wrong integer digit and emit it
> as a `field_equals` expectation), the `config/_yaml.py` comment stripper
> mis-advancing past a backslash escape, a `# pragma: no cover` in
> `encoding.py` claiming a guard that is never called on that branch, and
> stale counts in `CLAUDE.md`. Pinned by
> `tests/regression/test_audit_2026_09_16.py`; design notes in `.okf/log.md`'s
> 2026-09-16 entry. That pass also **re-verified eight of the LOW / carried-
> forward items below and found all eight still reproduce** — this file is
> accurate, not stale.

> **2026-09-09 cross-repo bug review:** 46 further defects fixed in the
> same branch — see `CHANGELOG.md` → Unreleased → Fixed and the `.okf/log.md`
> entry of that date; pinned by
> `tests/regression/test_review_2026_09_09_{preprocess,parser,analysis,generators}.py`.
> The one item that review left open is the first LOW entry below.

> **Status of `reports/audit-2026-09-07.md`:** every finding in that pass is
> **fixed at HEAD** — the two HIGH fabricated-answer bugs (a non-literal
> comparison operand used as a literal; `domains.solve()` returning witnesses
> for constraints it did not model), the four `unused-variables` false
> positives, the `ConstraintReport.unsupported` rollup, the two
> `views.py` / `layout_offsets.py` disagreements, and the test suite finally
> running in CI. Pinned by `tests/regression/test_audit_2026_09_07.py`; design
> notes in `.okf/log.md`'s 2026-09-07 entry. One of that report's LOW items
> was **withdrawn as wrong** during the fix pass (the `COMPUTE` "unbalanced
> parentheses" diagnostic is correct; the reproduction generated a
> 124-character line that `normalize_fixed_format` rightly truncated at
> column 72).


> **Status of `reports/audit-2026-08-12-followup.md`:** all of that pass's
> headline items are **fixed at HEAD** (commit `b495f26`, merged via
> PR #139) — the CLOSE/SET/CANCEL/OPEN/SORT/MERGE paragraph-swallow, the
> `ENTRY ... USING` continuation-line drop, the MOVE signed-subscript
> reintroduction, the `WHEN OTHER` false-merge in `ScenarioPlanner`, and
> the `io-coverage render` path bug. Re-verified by direct reproduction
> during the 2026-08-12 cross-repo bug review.
>
> **That same bug review found and fixed five further defects** (see
> `CHANGELOG.md` Unreleased → Fixed and
> `tests/regression/test_bug_review_2026_08_12.py`): float64 precision
> loss through the `gen-fixtures` witness pipeline (a `PIC 9(18)` witness
> rendered one-off while `ScenarioCoverage` still reported the arm
> targeted), `COMPUTE`'s `**` serializing as `* *`, `DivideStatement`
> dropping the BY/INTO distinction (now recorded as `division_mode`, and
> const_fold folds the unambiguous forms), typed literals losing their
> prefix in MOVE/DISPLAY text (`X"41"` → `"41"`), and reference
> modification gaining spaces (`WS-X(2 : 3)`).

This file tracks only what is currently open. It replaces this file's own
prior form — a running journal of a months-long audit that accumulated
per-finding writeups and dated status updates for HIGH findings H1-H11 and
MEDIUM findings M1-M16, all of which are now fixed and pinned by regression
tests — and the older `reports/audit-2026-07-06.md`, `-07.md`, `-08.md`,
`-09.md`, and `cobol-parser-example-parse-gaps.md` reports, which no longer
exist in this repo. For the full fixed-finding history, see `CHANGELOG.md`
("Unreleased → Fixed") and this file's own git history.

Two spot-checks during this cleanup turned up items that had gone stale
since they were written and are dropped rather than carried forward: the
Tier-2 copybook path-resolver containment gap (formerly "H6") now has
dedicated regression coverage (`TestH6PathResolverContainment` in
`tests/regression/test_open_findings_high_regressions.py`), and CI's
Cython-extension build is no longer implicit — the `build` job in
`.github/workflows/ci.yml` runs `python setup.py build_ext --inplace`
explicitly on every push/PR.

---

## Coverage must be measured on a pure-Python build (operational note)

Not a defect -- recorded because it was briefly mistaken for one during the
2026-09-07 audit, and the mistake is easy to repeat.

coverage.py cannot see into a compiled Cython extension. Once
`setup.py build_ext --inplace` has run, the pure-Python bodies those
extensions shadow read as unexecuted, and the reported total collapses.
Measured on the same suite, same commit:

| build | reported total | `--cov-fail-under=90` |
|---|---|---|
| `build_ext --inplace` run | 54.32% | fails |
| `COBOLPARSER_SKIP_EXT=1` | **91.76%** | passes |

So `ci.yml` splits them: `build` runs the suite `--no-cov` on the 3.11/3.12/
3.13 matrix *after* `build_ext` (that job exists to exercise the extensions),
and a separate `coverage` job installs pure-Python and enforces the floor.
The same reasoning already sat in `pyproject.toml`'s cibuildwheel
`test-command` comment.

The trap: comparing a coverage number taken with extensions built against one
taken without looks like data loss -- a subset appearing to out-cover its own
superset -- and invites a hunt for a phantom bug in the tooling. Check which
build produced each number first.

---

## M17 — `data.py`/`environment.py` branch-coverage debt

Both `cobolparser/parsers/divisions/data.py` and
`cobolparser/parsers/divisions/environment.py` roughly doubled in size
between the 2026-07-06 and 2026-07-09 audit passes (48→86 missing branches
in `data.py`; 40→69 in `environment.py`, measured against the same ~89% of
the suite at the time). Branch-coverage *percentage* was flat-to-improved
(new code was reasonably tested), but the absolute untested-branch count —
the thing that determines how much of the DATA/ENVIRONMENT-division clause
surface is unverified — was worse than at the original baseline. Not a bug;
tracked here as test-coverage debt. Counts above are from the last time
this was measured (2026-07-09) and have not been re-measured since.

---

## LOW

- **Numeric-edited fields are written to record images as plain numbers**
  (found 2026-09-09, still open): `encoding.py` assumes an edited picture's
  generated text is already the edited form, but `ValueFactory` produces
  plain `_format_number` text, so `$$$,$$9` holding 2208 is written as
  `"2208   "` rather than `" $2,208"` and `9(5)DB` holding -38848 as
  `"-38848 "` rather than `"38848DB"`. Needs an edit-mask renderer (zero
  suppression, floating insertion, `.`/`,`/`B`/`0`, `+ - CR DB`) and the
  matching de-edit in `decoding.py`. CSV output is unaffected.
- ~~**`*>` inline comments** still lex as `MULTIPLY_OP` + `GREATER`~~ —
  **fixed** (lexer 2026-08-07; normalizer quote-state scan 2026-09-09).
- **`TokenType.ALL` is dead** — `"ALL"` always lexes as a
  `FIGURATIVE_CONSTANT`; zero references to `TokenType.ALL` anywhere in the
  codebase. Currently masked for `INSPECT ... REPLACING ALL` (the statement
  parser special-cases the string value `"ALL"` regardless of token type),
  but any future construct that needs to distinguish the `ALL` keyword from
  the figurative constant has no way to.
- **Dead code**: `lexer.py:1485` `_compress_doubled_quotes` — defined, never
  called in production (only referenced directly by a test for coverage).
- **Unknown column-7 indicator characters** (anything other than
  space/`*`/`/`/`-`/`D`) are silently treated as live code by
  `normalize_fixed_format`, in both the pure-Python and active Cython path.
- ~~**A comment line interrupting an open continued literal silently severs
  it**~~ — **fixed 2026-09-09**: the normalizer defers the comment line's
  placeholder while a literal is open, so the next `-` record rejoins it
  (`tests/regression/test_review_2026_09_09_preprocess.py`).
- **`CallStatement.possible_values` (`DynamicCallAnalyzer`) returns `[]`
  ambiguously** — no way to distinguish "analyzer never tracked this
  variable" from "tracked, resolved to zero possible values" (the latter
  state is structurally unreachable in the current code, which is itself
  part of the ambiguity).
- **`ProfilerContext` over-reports peak memory when tracemalloc is already
  active** — `tracemalloc.reset_peak()` is never called in
  `profiling.py`, so if tracemalloc was started by something else before
  `ProfilerContext.__enter__` runs, the reported peak includes
  pre-existing allocations. (Not reachable via two literal nested
  `ProfilerContext`s in this process — `cProfile.Profile.enable()` raises
  immediately on a second concurrent instance — but reachable via any
  other concurrent tracemalloc consumer, e.g. another profiling harness.)
- **`CobolFileDescription` AST class is fully built (including `to_dict()`)
  but never instantiated** — FD/SD clauses are parsed into a raw
  `metadata["fd_clauses"]` dict on the associated `01`-level item instead.
  Data isn't lost (round-trips via metadata), so this is a dead-code/API
  surface inconsistency, not a silent drop.
- **Newly-recognized-but-unsupported verbs (INITIATE, TERMINATE, CHAIN,
  GOTO, NOTE, RECOVER, SUPPRESS, ...) warn explicitly** via
  `_UNSUPPORTED_VERBS` but still produce no AST node — downgraded from
  "silent drop" to "warned, unmodeled." Tracking here only as a reminder
  these constructs still aren't captured in the AST, not as a live bug.
- ~~**Every `COPY` statement inserts one extra phantom line into the
  copybook-expansion pipeline**~~ — **fixed.**
  `_expand_source_recursive` now strips exactly one trailing newline from
  the expanded member before the splice (and before `copybook_line_count`
  is taken, since that count pads the spliced-in origins to match), so the
  member's own line terminator no longer doubles up with the one the COPY
  statement's line already ended in. Expanded line counts are exact:
  `len(source) - len(COPY lines) + len(member lines)`, for any nesting
  depth. Note that `location.line` against the *original* file is answered
  by `ParseResult.expansion_source_map`, not by guessing at an offset —
  that map is what removed the need for this arithmetic at all.

---

## Test / tooling gaps

- ~~**12 permanently-skipped copybook-expansion tests**~~ — **stale, dropped
  2026-09-07.** The `pytest.skip("Implementation pending - Phase 6/7")`
  string no longer appears anywhere under `tests/`; the suite reports 3
  skips, all from elsewhere. The entry had been carried forward unverified
  since 2026-08-10.
- ~~**The test suite runs nowhere in CI**~~ — **fixed 2026-09-07.** pytest now
  runs in `ci.yml`'s `build` job on every PR, after `build_ext` so it
  exercises the Cython extensions; a dedicated `coverage` job enforces the
  90% floor on the pure-Python build. See `reports/audit-2026-09-07.md` (M3).
- Branch-coverage holes are tracked under M17 above.


---

## Carried forward from the 2026-08-12 audit (`audit-2026-08-12.md`)

All High/Medium bugs from that audit were fixed in the same PR. Still open,
in rough priority order (identifiers reference the audit report's sections):

- **P-D2** — the three checked-in Cython `.c` files are not generated from
  one canonical environment: `_lexer_fast.c` was regenerated 2026-08-12 in
  a zstd-less Linux env, while `_preprocess_fast.c`/`_data_fast.c` still
  carry the earlier Windows/zstd-variant output. Regenerate all three from
  one canonical environment (ideally in CI) to stop spurious diffs.
- **P-D3** — `setup.py` sets Cython `wraparound=False` while the `.pyx`
  files use negative slice indices (`line[:-1]`, `token_value[:-1]`) —
  formally undefined behavior; currently correct but fragile across Cython
  upgrades. Replace with explicit-length slices.
- **P-C1** — `parse_picture_clause_fast` in `_data_fast.pyx` is dead and
  lacks the 2026-07-21 missing-terminator LEVEL_NUMBER lookahead fix;
  wiring it up later would re-introduce a silent data-item drop. Delete or
  fix-and-wire.
- **P-D4** — statement `column` numbers are normalized-text coordinates
  (columns 1–7 stripped), systematically -7 from fixed-format source
  columns; undocumented. Document or translate.
- ~~**P-D5**~~ — fixed 2026-08-26: `_node_validators` is now per-instance
  state, and `create()` consults a registered validator after node
  construction (`tests/unit/test_ast_factory.py`).
- ~~**P-D6**~~ — fixed 2026-08-26: `find_all_by_type` now returns a copy of
  its per-type cache (`tests/unit/test_ast_base.py`).
- **P-C3/P-C4/P-C6** — test-only legacy char-cursor lexer API
  (`read_string_literal` et al.), uncalled `TokenStream.transaction()`,
  and dead newline-strip branches in both lexer variants.
- **A-design** — `MoveTypeChecker`'s flat name→category catalog collapses
  duplicate data names (no ambiguity accounting); `DeadCodeAnalyzer`
  explicit references are not reachability-gated (dead subgraphs shield
  each other); `domains._apply_enum` ignores relational ops on
  88-enumerated domains and can leak raw `THROUGH:n` markers as witnesses;
  `detect_cycles` dedups by node *set*, merging genuinely distinct cycles.
- **A-B2 residual** — `_unique_prefix` uses `startswith` without a word
  boundary ("SELECT A" also prefixes "SELECT AB ..."); and
  `value_tracker._extract_literal_value`'s permissive identifier fallback
  is now gated at its caller but still pinned by direct-call tests
  (`tests/unit/test_value_tracker_coverage.py:106-118`) — delete both
  together in a follow-up.
- **S-2 (info)** — batch workers have no per-file memory/time cap;
  document that batch input should be size-bounded.
- **S-3 (info)** — CLI `-o` overwrites without confirmation (standard, but
  keep it a conscious choice).
- **T-misc** — dead `[[tool.mypy.overrides]]` for `tests.*` in
  pyproject.toml (mypy only ever runs on `cobolparser/`); pre-commit runs
  both `ruff-format` and black (latent formatter fight; they agree today).
