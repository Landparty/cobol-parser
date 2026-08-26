# cobolparser — Open Findings (as of 2026-08-12, post-bug-review)

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

- **`*>` inline comments** still lex as `MULTIPLY_OP` + `GREATER`, not
  recognized as a comment marker.
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
- **A comment line interrupting an open continued literal silently severs
  it**: `normalize_fixed_format`'s comment branch flushes and resets
  `pending_literal`, so the next continuation line is treated as a
  non-literal continuation instead of merging. If quotes stay balanced
  across the interruption this corrupts the literal with no error; if they
  don't, it raises a confusing unrelated "unterminated string literal at
  EOF" error instead of a clear diagnostic.
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
- **Every `COPY` statement inserts one extra phantom line into the
  copybook-expansion pipeline** (found while fixing issue #123's
  comment-driven `location.line` drift — see `CHANGELOG.md` and
  `.okf/preprocessing.md`, "Line-Number Preservation"). In
  `copybook_expander.py::_expand_source_recursive`, the splice
  `expanded_source[:statement_start] + expanded_copybook +
  expanded_source[statement_end:]` (around `copybook_expander.py:927-931`)
  inserts `expanded_copybook` — which still carries the copybook file's own
  trailing `"\n"` — into a span that already ends in a newline (the COPY
  statement's own terminating period line), so each copybook contributes
  one extra blank physical line beyond its real content. Confirmed
  empirically to be exactly `+1` per `COPY` statement, not a one-time
  constant:

  | fixture | copybook lines | `COPY`s | content growth | measured offset | excess |
  |---|---|---|---|---|---|
  | 1 copybook, 2 lines | 2 | 1 | +1 | +2 | +1 |
  | 1 copybook, 4 lines (incl. 2 comments) | 4 | 1 | +3 | +4 | +1 |
  | 2 copybooks, 2+1 lines | 3 | 2 | +1 | +3 | +2 |

  This makes the *base* offset between a copybook-expanded `location.line`
  and the true original-file line number larger than the copybooks' real
  combined content by one line per `COPY` — on top of, and independent
  from, the per-comment drift issue #123 fixed. It is constant per file
  (doesn't grow with unrelated comments/blanks elsewhere), so it does not
  reintroduce the drift bug, but it does mean `location.line` still cannot
  be used directly against the original source file for any file with a
  `COPY` statement — a real original-file location map remains the only
  fix that removes the need to guess at this offset at all.

---

## Test / tooling gaps

- **12 permanently-skipped copybook-expansion tests**:
  `tests/unit/test_copybook_expansion.py` (3, lines 296/300/308),
  `tests/contracts/test_copybook_expansion_contracts.py` (5, lines
  226/230/234/242/246), `tests/integration/test_copybook_expansion_integration.py`
  (4, lines 180/184/650/654) — all `pytest.skip("Implementation pending -
  Phase 6/7")`. Count confirmed current as of 2026-08-10.
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
