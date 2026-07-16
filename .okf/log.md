# OKF Update Log

## 2026-07-15 (division-parser god-class refactor)

* [parser.md](parser.md): `DataDivisionParser`
  (`parsers/divisions/data.py`, ~1,467 lines) decomposed into collaborators
  `data_clauses.py` (`DataItemClauseParser`), `data_file_description.py`
  (`FileDescriptionClauseParser`), and `data_special_entries.py`
  (`SpecialEntryParser`). The division parser keeps its import path and the
  `_parse_picture_clause`/`_parse_value_clause`/`_parse_usage_clause`
  wrappers required by the `_data_fast` Cython callback surface. Division
  Parsers table updated; behavior-preserving, no public API change.
* [parser.md](parser.md): `EnvironmentDivisionParser`
  (`parsers/divisions/environment.py`, ~1,133 lines) decomposed into
  `environment_sections.py` (`ConfigurationSectionParser`,
  `InputOutputSectionParser`) and `environment_select.py`
  (`SelectClauseParser`). The division parser keeps its import path and
  delegates; behavior-preserving, no public API change.
* [parser.md](parser.md): `ProcedureDivisionParser`
  (`parsers/divisions/procedure.py`, ~912 lines) decomposed into
  `procedure_registry.py` (`create_statement_registry()`),
  `procedure_boundaries.py` (boundary predicates), and
  `procedure_recovery.py` (`StatementRecoveryHandler`,
  `STRAY_MARKERS`/`UNSUPPORTED_VERBS`). The division parser keeps its
  import path and the paragraph/section dispatch loop; the "Adding a New
  Statement Parser" flow now registers parsers in `procedure_registry.py`.
  Behavior-preserving, no public API change.

## 2026-07-14 (program_flow god-class refactor)

* [analysis.md](analysis.md): `cobolparser/analysis/program_flow.py` (~987-line
  `ProgramFlowAnalyzer` class) decomposed into the package
  `cobolparser/analysis/program_flow/` with focused collaborators —
  `models.py`, `scanner.py` (`ProcedureScanner`), `edges.py`
  (`EdgeCollector` + edge-type category sets), `cycles.py`, `graph.py`,
  `analyzer.py`. Behavior-preserving: public API, import paths, and
  `to_dict()` output unchanged (verified byte-identical against the old
  implementation across all sample programs).

## 2026-07-09 (H9 fixed: missing-period paragraph-boundary swallow)

Follow-up to the same-day H1-H8 pass below: fixed H9, the one HIGH finding
that pass had deliberately left open. A statement missing its terminating
period, immediately followed by what should be a new paragraph header, had
the paragraph name absorbed as a trailing operand instead of starting a
new paragraph — confirmed by direct repro in `DISPLAY`'s item list,
`MOVE`'s target list, `COMPUTE`'s expression capture, `STRING`'s operand
list, `UNSTRING`'s `INTO` target list, and `INSPECT`'s `TALLYING`
counter-name loop / outer "consume to period" trailer (not IF-specific,
not a single-statement bug; `SET`, the fixed-arity arithmetic
target/GIVING slots, and `IF` were probed and found already safe). Fixed
via a new `looks_like_paragraph_boundary()` predicate in
`parsers/statements/_utils.py` that mirrors COBOL's own
paragraph-name-vs-operand disambiguator (first token on its source line,
immediately followed by a period/SECTION, not a DATA DIVISION name) rather
than trying to resolve the ambiguity from grammar shape alone — the raw
grammar cannot tell "last operand of an unterminated statement" from "next
paragraph name" since both are just `IDENTIFIER` then `PERIOD`. Applied
only to the six statement parsers confirmed by direct repro, not
universally, per the original finding's own "needs its own scoped
investigation" framing (see [parser.md](parser.md) for the full
per-file breakdown and the deliberately-out-of-scope call sites).
Recovery now warns (matching the H7/H8 "warn, don't silently
reinterpret" precedent) rather than staying silent; where a fix site has
both an inner sub-parser check and an outer trailer that both see the
same un-consumed token (`INSPECT` TALLYING, `UNSTRING` INTO), only the
outer one emits the warning to avoid duplicates.

* **Updated** [parser.md](parser.md): replaced the H9 "not fixed" bullet
  (end of the "open-findings.md HIGH-severity fixes (2026-07-09, H1-H8)"
  section) with the fix writeup — files touched
  (`_utils.py`, `display_parser.py`, `move_parser.py`,
  `arithmetic_parsers.py`, `string_unstring_parsers.py`,
  `initialize_inspect_parsers.py`, `core/interfaces.py`,
  `parsers/divisions/procedure.py`), the first-on-line +
  not-a-data-name disambiguation rule, the
  `ParseContext.known_data_names` threading mechanism, the inner/outer
  warning-dedup split for `INSPECT`/`UNSTRING`, and the deliberate scope
  boundary (only 6 of the 16 `is_statement_boundary()` call sites
  touched; the undeclared-identifier-on-a-continuation-line case remains
  an acknowledged residual ambiguity).
* `reports/open-findings.md`: H9 marked "FIXED 2026-07-09" in place (same
  traceability convention as H1-H8); the HIGH-section summary line updated
  from "H1-H8 fixed... H9 not fixed" to "H1-H9 are all fixed".
* `CHANGELOG.md` (Unreleased → Fixed): added the H9 writeup as its own
  bullet, and updated the H1-H8 entry's "noted but intentionally not fixed
  here" paragraph to point at it instead of describing it as still open.
* Pinned by 9 new tests in
  `tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`
  (one repro per fixed statement/clause shape, plus two guard cases proving the
  DATA DIVISION cross-check prevents false positives on undeclared
  same-line operands and declared continuation-line operands). Full suite
  (6759 tests) and `ruff`/`black`/`mypy` all still pass.

## 2026-07-09 (open-findings.md HIGH-severity remediation: H1-H8 fixed, H9 discovered)

Implemented fixes for all 8 HIGH findings in `reports/open-findings.md`'s
2026-07-08 re-verification pass, each pinned by a dedicated test class in
new file `tests/regression/test_open_findings_high_regressions.py` (21
tests total). Full per-finding writeup: `CHANGELOG.md` (Unreleased →
Fixed). `reports/open-findings.md` itself updated in place — H1-H8 marked
resolved (left visible for traceability, per the file's own convention for
prior audits), and a new H9 finding recorded for the one thing discovered
but *not* fixed in this pass.

* **Updated** [lexer.md](lexer.md): added a "Warnings (non-fatal
  diagnostics)" section. `CobolLexer` (pure-Python and `_lexer_fast`
  Cython) now tracks `self.warnings`, exposed via `has_warnings()`/
  `get_warnings()`; `CobolParser.parse()` forwards them into
  `ParseResult.warnings` (prefixed `"Lexer warning: "`). First producer:
  an unterminated string literal in the free-form path (the only lexing
  mode `parse_cobol()` ever uses) used to close silently at the line
  boundary with `errors=0, warnings=0` — now warns instead, without
  promoting to a hard error (H7).
* **Updated** [parser.md](parser.md): new "open-findings.md HIGH-severity
  fixes (2026-07-09, H1-H8)" section, summarizing H1 (`SET ADDRESS OF`
  target-loop `OF`-type gap), H2 (COMPUTE unbalanced-paren boundary-guard
  bypass — additive to the 2026-07-06 COMPUTE-swallow fix already
  documented above it), H3/H4 (PERFORM trailing-TIMES-candidate silent
  discard + 5 unlogged bare excepts in `perform_parser.py`), and H8
  (`CLOSE`'s per-file option if/elif chain converted to a loop so combined
  options like `REEL WITH NO REWIND` all survive). Also records **H9**
  (not fixed): a statement with no terminating period, immediately
  followed by what should be a new paragraph header, gets its name
  absorbed as a trailing operand instead of starting a new paragraph —
  discovered while verifying H7's "unclosed IF" sub-claim (which, on
  investigation, turned out to be legal, correctly-parsed COBOL, not a
  bug). Distinct root cause, not IF-specific, deliberately left unfixed
  (high-blast-radius paragraph-boundary surgery, out of scope for this
  bounded 8-finding pass).
* **Updated** [analysis.md](analysis.md): `MoveTypeChecker` gained
  `MoveTypeReport.unresolved_count` (H5) — previously an unresolvable
  source/target `DataCategory` caused a silent early `return`/`continue`
  with no counter anywhere, so 3 MOVEs on undeclared identifiers produced
  `violations: [], error_count: 0, warning_count: 0`, a false all-clear.
  Also corrected a pre-existing doc error in the same section: the method
  is `.check(ast)`, not `.analyze(ast)`.
* **Updated** [preprocessing.md](preprocessing.md): new "Copybook Path
  Resolution (`path_resolver.py`)" section documenting the 3-tier
  resolution strategy and the H6 fix — the Tier-2 directory-index fast
  path returned an indexed path after only a size check, never calling
  `validate_path_within_directory()` (which Tier 3 does call), so a
  symlink inside a search directory pointing outside it would bypass
  containment checking. Now validated via a new
  `_validate_indexed_result()` at both Tier-2 hit points. Also fixed in
  the same pass: the `".."` traversal guard was substring matching
  (false-flagged `weird..name.cpy`); now a path-segment check.
* **Updated** [tests.md](tests.md): +21 tests
  (`tests/regression/test_open_findings_high_regressions.py`); full suite
  now 6,750 passed / 13 skipped / 5 xfailed, 92.61% coverage.
* Also fixed while verifying H2: `tests/samples/arithmetic_operations.cbl`
  had a `FUNCTION MAX(WS-NUM-1, WS-NUM-2, WS-NUM-3)` line whose closing
  `)` landed in fixed-format column 73 and was silently truncated by
  `normalize_fixed_format` — previously masked by the very H2 bug (the
  truncated, permanently-unbalanced expression silently absorbed the next
  statement instead of erroring); the H2 fix correctly surfaces this now,
  so the sample was corrected (spaces after commas removed to fit column
  72) rather than the detection being weakened.

## 2026-07-09 (silent-drops-and-gaps audit: OCCURS KEY, program-flow clause bodies, REWRITE/START/ACCEPT/STOP operands, DATA warn channel)

Follow-up to the 2026-07-08 audit. Four parallel re-audits (DATA division,
analysis modules, statement parsers, AST serialization) each briefed on the
prior fix lists. AST-serialization review found nothing new; the other three
each surfaced genuine, runtime-reproduced silent drops. Full audit:
`reports/audit-2026-07-09.md`.

* **Updated** [parser.md](parser.md) / [ast-models.md](ast-models.md):
  OCCURS `ASCENDING/DESCENDING KEY IS ...` was dropped entirely, and because
  the OCCURS parser looked for `INDEXED` immediately after DEPENDING, a KEY
  clause sitting between them (standard COBOL order) also caused the following
  `INDEXED BY` to be eaten by the clause loop's `else: consume()`. `INDEXED BY
  a b` also kept only the last index name. Now parsed in both `data.py` and the
  `_data_fast.pyx` mirror (`.c` regenerated with Cython 3.2.4); `OccursClause`
  gained `key_clauses` (list of `{direction, keys}`) and `index_names` (all
  indexes; `indexed_by` keeps the first for compatibility), both serialized.
* **Updated** [analysis.md](analysis.md): `ProgramFlowAnalyzer`'s hand-rolled
  `scan()` recursed only into a subset of container statements (PERFORM inline,
  CALL handlers, IF/EVALUATE/SEARCH/RETURN) and never descended into IO
  (`AT END`/`INVALID KEY`/`AT EOP`), arithmetic (`ON SIZE ERROR`), or
  STRING/UNSTRING (`ON OVERFLOW`) clause bodies. A PERFORM/GO TO/CALL nested
  there produced no edge, cascading into **false `unreachable_nodes`** reports
  and missing flowchart arrows (contrast `DeadCodeAnalyzer`, which uses
  `get_all_statements()`). Fixed with a final `else` branch mirroring
  `coverage_analyzer._nested_statements`'s clause-attribute list.
* **Updated** [parser.md](parser.md) / [ast-models.md](ast-models.md): four
  statement-parser operand drops — `REWRITE rec FROM data` dropped the FROM
  source (`IORewriteStatement` gained `from_clause`); `START f KEY IS ...
  data-name` dropped the KEY data-name (`IOStartStatement` gained `key_name`);
  `ACCEPT x FROM DATE YYYYMMDD` dropped the format phrase and re-parsed it as a
  **phantom paragraph** (now captured into `from_source`); `STOP RUN RETURNING
  x` dropped the return code (`StopStatement` gained `returning`, and a bare
  numeric `STOP n` operand is now captured). `ACCEPT`/`UNLOCK` with a missing
  operand no longer consume the following statement's verb (`is_statement_
  boundary` guard).
* **Updated** [parser.md](parser.md): the DATA division clause loop's
  `else: consume()` fallback now emits an "Unparsed token ... in data item"
  warning for meaningful (non-whitespace) tokens — symmetric with the
  ENVIRONMENT division's SELECT handling. Previously any unsupported data-item
  clause (GROUP-USAGE, VOLATILE, DYNAMIC LENGTH, DESCENDING KEY, ...) vanished
  with `warnings=[]`.
* **Updated** [tests.md](tests.md): +13 tests
  (`tests/regression/test_tier6_silent_drop_audit.py`).

## 2026-07-08 (residual of the 2026-07-07 C2 fix: unsupported-verb boundary gap)

* **Updated** [parser.md](parser.md): closed the mockymock-audit-flagged
  residual of the 2026-07-07 C2 silent-drop fix — "an unknown verb directly
  after a period-less statement can still be swallowed with no warning
  (period-terminated layouts are covered)". C2's
  `ProcedureDivisionParser._warn_unsupported_statement` only fires when the
  top-level dispatch loop directly sees the offending token, which requires
  a period to hand control back to that loop at the right place. Without a
  period, the *previous* statement's own trailing-token loop (MOVE's target
  list, the arithmetic operand collector, etc.) decides for itself whether
  to stop, via `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`) —
  and those sets were missing several verbs `_UNSUPPORTED_VERBS` already
  knew how to *label*, so the following statement's tokens were silently
  absorbed as bogus operands before ever reaching the label logic.
  Reproduced and fixed for: `DISABLE`, `ENABLE`, `PURGE`, `RAISE`, `READY`,
  `RECEIVE`, `RESET`, `RESUME`, `SEND`, `SERVICE`, `TRANSFORM` (string
  already in `_UNSUPPORTED_VERBS` but missing from the boundary sets);
  `EXECUTE`/`EXHIBIT`/`INVOKE` (string was already in `STATEMENT_KEYWORDS`,
  but the dedicated lexer `TokenType` was missing from
  `STATEMENT_TOKEN_TYPES`, which `MoveStatementParser`'s type-first check
  needs); `COMMIT`/`ROLLBACK` (have registered parsers, yet were in neither
  set — a fully-supported statement vanished, worse than the
  unsupported-verb case); and `CHAIN`, `ENTER`, `EXAMINE`, `GOTO` (fused
  one-word spelling only), `INITIATE`, `NOTE`, `RECOVER`, `SUPPRESS`,
  `TERMINATE` (real verbs with dedicated `TokenType`s, previously absent
  from every "known verb" set in this file).
  `ProcedureDivisionParser._UNSUPPORTED_VERBS` gained the newly-recognized
  unsupported verbs (not `COMMIT`/`ROLLBACK`, which now dispatch normally).
  Pure clause words that never start a statement (`ON`, `OTHERWISE`,
  `NEXT`, `THEN`, scope-terminator tokens, `DISPLAY-1`) were deliberately
  left out.
* **Updated** [parser.md](parser.md): `PURGE`/`RAISE`/`RESUME` have no
  dedicated lexer `TokenType` at all — they lex as plain `IDENTIFIER`,
  indistinguishable from a data-name — so adding their strings to
  `STATEMENT_KEYWORDS` only closed the gap for parsers whose trailing loop
  already consults it (MOVE, arithmetic). Ten *other* list-collecting loops
  never consulted `STATEMENT_KEYWORDS`/`is_statement_boundary` at all, and
  kept silently folding these three verbs into their list:
  `display_parser.py` (item list),
  `simple_statement_parsers.py::CancelStatementParser` (program-name list),
  `set_parser.py` (target list), `open_parser.py`/`close_parser.py`
  (file-name lists), `initialize_inspect_parsers.py::InitializeStatementParser`
  (target list) — none of these six *main* parse loops consulted the shared
  predicate at all; and `string_unstring_parsers.py::UnstringStatementParser
  ._parse_into_targets` (INTO target list), `sort_merge_parsers.py::
  _parse_keys` / `_parse_file_list` (KEY field list / USING·GIVING file
  lists, shared by SORT and MERGE),
  `initialize_inspect_parsers.py::InspectStatementParser._parse_tallying`
  (TALLYING counter-name loop) — these four are separate nested helper
  loops with their own hand-rolled boundary keyword list (or, for
  `_parse_tallying`, no boundary check at all) that predates/bypasses the
  `is_statement_boundary()` check their statement's *outer* loop already
  had (2026-07-06/2026-07-08 fixes). Each of the ten now breaks on
  `is_statement_boundary(token)` before accepting a bare `IDENTIFIER` as a
  list item.
* **Updated** [parser.md](parser.md): a related, more severe pre-existing
  bug (independent of the `STATEMENT_KEYWORDS` gaps above, found by the
  same sweep) — `PerformStatementParser._parse_until_condition_only` (the
  out-of-line `PERFORM paragraph-name UNTIL condition` form, no inline
  body) had **no boundary check whatsoever**: only a literal period or
  `END-PERFORM` stopped it. A period-less `PERFORM ... UNTIL cond` silently
  swallowed every remaining token in the program into the condition
  string — verified with a normal `DISPLAY`/`STOP RUN` pair, not just an
  unsupported verb, both of which vanished from the AST with
  `result.success == True`, `warnings == []`. Now stops at the same
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` boundary the sibling
  `_collect_until_condition_tokens` helper (used by the inline PERFORM
  UNTIL/VARYING forms) already used.
* **Updated** [parser.md](parser.md): a fourth finding, in
  `EvaluateStatementParser` — two independent unguarded loops.
  `_parse_subjects` (subject list before the first `WHEN`) had no boundary
  check, same shape as the ten list-collecting loops above: a malformed/
  period-less `EVALUATE` with no `WHEN` folded a following verb into
  `stmt.subjects` as free text. Fixed the same way as the sibling
  `_parse_selectors` (already correct): `self._is_statement_keyword()`.
  More severe: the *outer* clause-scan loop between `_parse_subjects` and
  the `WHEN` dispatch treated any non-`WHEN`/`END-EVALUATE` token as noise
  to skip past, so a malformed `EVALUATE` could consume forward past entire
  intervening statements hunting for a literal `"WHEN"` — verified with a
  trailing `MOVE 1 TO WS-Y` followed by a second, well-formed `EVALUATE
  WS-Y ... WHEN 1 ... END-EVALUATE`: the first EVALUATE annexed the
  *second* EVALUATE's `WHEN` clause as its own, silently erasing the MOVE
  and merging two EVALUATEs into one, with `errors == []` and
  `warnings == []` (the missing-WHEN error that normally flags a malformed
  EVALUATE never fired, because *a* WHEN was found — just the wrong one's).
  Fixed with the same `self._is_statement_keyword()` break. Probed and
  confirmed safe: `IfStatementParser`'s condition collector (with/without
  `THEN`/`END-IF`) already stops correctly on a following verb.
* **Updated** [tests.md](tests.md) implicitly: +1 new regression file,
  `tests/regression/test_tier7_unsupported_verb_boundary.py` (9 tests
  total, including 2 for the EVALUATE finding). Full suite: 6729 passed,
  0 failed.

## 2026-07-08 (silent-drops-and-gaps audit: SORT/MERGE/ENTRY/CALL swallows, line-number drift, batch/CLI fault isolation)

* **Updated** [parser.md](parser.md): SORT/MERGE's "remaining clauses" loop
  and ENTRY's USING-clause loop now stop at `is_statement_boundary()` instead
  of an `else: consume()` fallback that swallowed a following un-punctuated
  statement (same bug class as the 2026-07-06 INSPECT/STRING/UNSTRING fix,
  but these three parsers were missed at the time). `CallStatementParser`'s
  ON EXCEPTION/NOT ON EXCEPTION/ON OVERFLOW handler-body dispatch
  (`_parse_nested_stmts`) now warns on an unsupported verb via the new
  `_warn_and_skip_handler_statement`, matching the top-level
  `_warn_unsupported_statement` behavior from the 2026-07-07 C2 fix, which
  this nested dispatch loop had never received.
* **Updated** [preprocessing.md](preprocessing.md): `normalize_fixed_format`
  and `preprocess_conditional_compilation` both used to drop certain
  physical lines from their output entirely (blank/comment lines; `>>DEFINE`/
  `>>IF`/`>>ELSE`/`>>END-IF` directive lines; lines inside a skipped `>>IF`
  block) instead of emitting an empty placeholder — silently shifting every
  later line's number in lexer/parser error and warning locations. Every
  real COBOL program has blank/comment lines, so this affected essentially
  all diagnostics past the first one, not just an edge case. Fixed in both
  the pure-Python implementation and the Cython `_preprocess_fast.pyx`
  mirror (checked-in `.c` regenerated).
* **Updated** [lexer.md](lexer.md): `_lexer_fast.pyx`'s `is_line_start_quote`
  check used `str.strip()` (broad whitespace definition) where the
  pure-Python lexer used an explicit `" \t"`-only loop — a stray control
  byte before an unterminated quote could make the compiled build classify
  a VALUE-clause-continuation candidate differently from the fallback path.
  Aligned to the narrower pure-Python check.
* **Produced** [batch.md](batch.md): new OKF concept file (was referenced by
  `scripts/okf_staleness_check.py`'s `OKF_MAP` but never created). Documents
  `parse_files`/`parse_files_with_copybooks` and their per-file fault
  isolation, including two gaps fixed today:
  `parse_files_with_copybooks` had no exception guard around
  `parser.parse(...)` (one poisoned file could abort the whole batch,
  discarding every other file's result — the 2026-07-07 C8 fix only
  reached `parse_files`'s workers) and only caught `OSError` (not
  `ValueError`/`UnicodeDecodeError` under `errors="strict"`) on file reads.
* **Updated** [analysis.md](analysis.md): `IOCoverageReporter.load_pytest_results`
  now raises `ValueError` for a non-dict JSON root instead of an uncaught
  `AttributeError` from the unconditional `data.get("tests", [])` that
  followed.
* **Updated** [cli.md](cli.md): `coverage generate` now catches
  `json.JSONDecodeError`/`ValueError` from the reporter (the same M10 bug
  class already fixed for `coverage status`, but missed here);
  `generate-tests -o` write failures now go through the standard
  `_fail(...)` path instead of an uncaught traceback (it was the one
  output-writing subcommand that bypassed the shared `_text_out()` helper).
* **Updated** [tests.md](tests.md): test count refreshed to ~6,725 tests
  across 241 files (two new regression files:
  `test_tier5_silent_drip_audit.py`, `test_normalize_line_number_preservation.py`).
* Full audit: `reports/audit-2026-07-08.md`.

## 2026-07-07 (mockymock corpus-sweep fixes: SUBTRACT GIVING, DISPLAY subscript, WRITE FROM literal)

* **Updated** [parser.md](parser.md): fixed three content-drop bugs found
  by re-running mocky-mock's corpus sweep (`scripts/corpus_sweep.py`)
  against `legacy-application` now that the EVALUATE blank-selector fix
  (below) is on `main` — all 26 corpus/fixture/example programs now parse
  and `mockymock generate` cleanly with zero refusals (previously 3
  programs carried a `PARSE_WARNING`: `ACCTMNT.cbl`, `GLRECON.cbl`,
  `LOANPMT.cbl`). `SubtractStatementParser`'s `FROM` branch now checks for
  a trailing `GIVING` (mirroring `AddStatementParser`'s `TO` branch), so
  `SUBTRACT a FROM b GIVING c` no longer drops `c`.
  `_utils.consume_keyword_and_operand` now skips leading `NEWLINE` tokens
  before checking for its keyword, not just after, so a clause keyword on
  its own continuation line is no longer missed (this was the actual
  trigger in `LOANPMT.cbl` — `GIVING` on the line after `FROM`).
  `DisplayStatementParser` now folds a following `(subscript)` into the
  preceding identifier as one item instead of aborting the item list on
  the bare `LEFT_PAREN` (`ACCTMNT.cbl`'s `DISPLAY ... SQLERRD(3)`).
  `WriteStatementParser`'s `FROM` clause now also accepts a string literal
  source, not just an identifier (`GLRECON.cbl`'s `WRITE rec FROM
  'literal text'`).
* **Updated** [tests.md](tests.md): test count refreshed to ~6,709 tests
  across 239 files (new `tests/unit/test_display_parser.py`).
* **Addressed PR #80 review comments:** `_consume_subscript` now preserves
  nested parens literally (`TAB(FUNCTION MOD(3 2))` no longer flattens to
  `TAB(FUNCTION MOD 3 2)`) instead of only tracking paren depth without
  recording the parens; `consume_keyword_and_operand` now calls
  `skip_whitespace` (covers `WHITESPACE`/`COMMENT`/`CONTINUATION` too, not
  just `NEWLINE`) so a fixed-format continuation token before an optional
  clause keyword can't hide it, even though `normalize_fixed_format`
  already merges continuation lines before today's standard entry point
  reaches the lexer.

## 2026-07-07 (audit HIGH/MEDIUM remediation: H1, H2, H4, H5, H6a/c, H7, M5, M8, M10)

* **Updated** [parser.md](parser.md): `_parse_size_error_stmts` now
  dispatches ON SIZE ERROR / NOT ON SIZE ERROR bodies through the statement
  registry — every verb is captured, not just DISPLAY/MOVE (H1).
  `perform_parser.py` parses `PERFORM VARYING ... AFTER ...` dimensions
  into `PerformStatement.after_clauses` (H2). ENVIRONMENT division SELECT
  parsing captures ALTERNATE RECORD KEY / PADDING / RESERVE / SHARING /
  LOCK MODE / PASSWORD / RECORD DELIMITER / second FILE STATUS variable,
  populates `assign_device_type`, and warns on unknown SELECT clause
  tokens (H5). `DECIMAL-POINT IS COMMA` warns that it is not honored (H4).
  `BaseDivisionParser` gained a `host` attribute so all division parsers
  can reach `add_warning`/`add_error`.
* **Updated** [ast-models.md](ast-models.md):
  `PerformStatement.after_clauses` (+ `add_after_clause`, serialized when
  non-empty); `CobolExpression.to_dict()` now includes `operands`.
* **Updated** [preprocessing.md](preprocessing.md): the COPY statement
  lexer records warnings for COPY statements it recognizes but drops
  (missing terminating period → never expanded, H6a; unterminated
  `==pseudo-text==`, H6c) and gained a left-side word-boundary check;
  `extract_copy_statements(..., warnings=)` and
  `preprocess_conditional_compilation(..., warnings=)` surface diagnostics
  (unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
  `>>DEFINE`, unclosed `>>IF`, unknown `>>` directives — H7) into
  `ExpansionStatistics.warnings` / `ParseResult.warnings`.
* **Updated** [cli.md](cli.md): `--define` conditional-compilation warnings
  print to stderr; `coverage status` reports malformed artifact JSON with
  exit 1 instead of a traceback (M10).
* Regression suite: `tests/regression/test_tier4_audit_remediations.py`
  (29 tests). `interface-contract.md` documents real `success`/`ast`
  semantics (M8); `MemoryConfiguration` docstring flags its no-op fields
  (M5).

## 2026-07-07 (audit critical silent-drop fixes: C1–C8, H3, H6)

* **Updated** [parser.md](parser.md): multi-program compilation units are now
  parsed — `parse_program()` consumes `END PROGRAM [name] [.]` and starts a
  new `CobolProgram` at each subsequent IDENTIFICATION DIVISION, attaching
  extras to `ast.contained_programs` with a summary warning (C1). Unknown
  verbs (no registered statement parser) now emit a `ParseResult.warnings`
  entry instead of a silent `logger.debug` skip
  (`procedure.py:_warn_unsupported_statement`, C2). New
  `xml_json_parser.py` handles XML/JSON GENERATE/PARSE (C3) — previously
  mis-parsed as Report Writer GENERATE. `STATEMENT_KEYWORDS` gained
  ALLOCATE/EXHIBIT/FREE/INVOKE/JSON/XML.
* **Updated** [ast-models.md](ast-models.md): `CobolProgram.contained_programs`;
  `condition_names` (level-88) on `CobolDataItem.to_dict()` and
  `renames_items` (level-66) on `CobolSection.to_dict()` (C5);
  `CallStatement.to_dict()` includes `not_on_exception` and handler
  statements are AST children so `find_all_by_type()` sees them (C6);
  `GoStatement.target_paragraphs` keeps all computed-GO-TO targets plus the
  DEPENDING ON variable (C4); new `XmlJsonStatement` node;
  `IOWriteStatement.advancing_clause` populated by the WRITE parser (H3).
* **Updated** [cli.md](cli.md): `parse` exits 2 on a recovered-but-errored
  parse, `batch` exits 2 when any file failed, analyzer subcommands warn on
  stderr when analyzing a partial AST (C7). Batch workers contain
  parse-time exceptions as per-file `read_error` instead of aborting the
  pool (C8).
* **Updated** [preprocessing.md](preprocessing.md):
  `parse_cobol_with_expansion` propagates `expansion.statistics.warnings`
  onto `ParseResult.warnings` (H6).
* Pinned by `tests/regression/test_tier3_silent_drop_fixes.py` (31 tests).
  Full audit: `reports/audit-2026-07-07.md`.

## 2026-07-06 (fixed-format numeric-literal continuation mangled)

* **Updated** [preprocessing.md](preprocessing.md): documented that
  `normalize_fixed_format` joins non-literal continuation lines (indicator
  `-` in column 7) with **no** intervening space, per the COBOL rule that a
  continuation line's first non-blank character is the successor of the
  continued line's last non-blank character. The `else` branch (taken when
  no alphanumeric literal is open) previously did `" " + text_slice.lstrip()`,
  injecting a space before every chunk. A numeric literal split one character
  per continuation line — NIST `NC205A.CBL` writes `-999.777` and `45678`
  this way — normalised to `- 9  9  9  .  7  7  7`: spaced digits plus a
  free-standing `.` that the free-form lexer read as a statement terminator,
  truncating the `MOVE` source and dropping the `TO CONT-B` target. The AST
  silently lost the whole `MOVE -999.777 TO CONT-B` while `result.success`
  stayed `True` (no error surfaced). Changed both branches to
  `text_slice.strip()` (no leading space, both ends trimmed) in the
  pure-Python `preprocess/__init__.py` **and** the Cython
  `_preprocess_fast.pyx` (checked-in `.c` regenerated via
  `setup.py build_ext --inplace`). Alphanumeric literals split with `-` were
  already correct via the open-quote (`pending_literal`) path. The
  pure-Python impl is now reachable as
  `cobolparser.preprocess._normalize_fixed_format_pure` (mirrors
  `lexer._CobolLexerPure`) so both paths can be tested. This resolves the
  `NC205A.CBL` strict-xfail `KNOWN_ISSUES` entry that the same-day H3 MOVE
  fix (below) had just added — NC205A now parses error-free, so its entry is
  removed from `tests/integration/test_nist_cobol85_support.py`
  (`SM206A`/`SM208A`, distinct `COPY REPLACING`/`REPLACE` gaps, remain).
  Pinned by `tests/regression/test_continued_literal_normalization.py`.

## 2026-07-06 (INSPECT/STRING/UNSTRING swallow + EXEC missing-END-EXEC — audit H2)

* **Updated** [parser.md](parser.md): closed the last four rows of audit
  2026-07-06 H2's "swallow the following statement" class.
  - Added a shared `is_statement_boundary(token)` predicate in
    `parsers/statements/_utils.py` (unions `STATEMENT_TOKEN_TYPES` /
    `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`)
    so INSPECT/STRING/UNSTRING share one boundary check instead of the
    per-parser inline copies MOVE/arithmetic use.
  - `InspectStatementParser`'s trailing "consume to period" loop and the
    `StringStatementParser`/`UnstringStatementParser` main-loop
    `else: consume()` fall-throughs now `break` on that predicate, so an
    un-punctuated INSPECT/STRING/UNSTRING immediately followed by another
    statement (or an enclosing `END-IF`/`ELSE`) no longer devours it up to
    the next period. Behavior stays `errors=0` (a legal COBOL sentence may
    hold several statements without separating periods).
  - EXEC SQL/CICS/IMS is intentionally left off that predicate: embedded
    SQL/CICS text legitimately contains COBOL keywords (SET/DELETE/UPDATE/
    CALL/OPEN/CLOSE), so a content boundary would truncate valid SQL. The
    mandatory `END-EXEC` is the only safe delimiter, so
    `collect_exec_sql_text` now detects a missing `END-EXEC` (stream
    exhausted first) and records a non-fatal "Unterminated EXEC block"
    parse error via the stream's parse context — turning the previous
    silent "consume the rest of the program with `errors=0`" into a
    reported error (`result.success == False`). Well-formed blocks and the
    NIST/shamrice/sample corpora (all `END-EXEC`-terminated) are unaffected.
  - Pinned by four new classes in
    `tests/regression/test_tier2_silent_drop_regressions.py`
    (`TestInspectDoesNotSwallowFollowingStatement`,
    `TestStringDoesNotSwallowFollowingStatement`,
    `TestUnstringDoesNotSwallowFollowingStatement`,
    `TestExecMissingEndExecReportsError`). Full suite: 6579 passed.
  - Still-open H2 row: MOVE *source* path (`MOVE A` with no `TO`) — not part
    of this change.

## 2026-07-06 (H5 — unterminated literal no longer aborts the whole parse)

* **Updated** [preprocessing.md](preprocessing.md): documented that
  `normalize_fixed_format(..., merge_continued_literals=False)` is a
  non-raising best-effort fallback and how the parser uses it for recovery.
  Audit finding H5 (`reports/audit-2026-07-06.md`): a single unterminated
  string literal at EOF made `normalize_fixed_format` raise `ValueError`,
  which — called unconditionally before error recovery was active — collapsed
  the whole parse to `ast=None` even under `ErrorRecoveryMode.COLLECT_ALL`.
  Two entry points were affected: `CobolParser._parse_core` (the raise fell
  through to the generic `except Exception` safety net) and the `parse_cobol`
  convenience function (which caught the raise but returned `ast=None`
  regardless of mode, despite a comment claiming graceful COLLECT_ALL
  handling). Fixed by making `_parse_core` the single owner of
  normalize-and-recover: it records the unterminated-literal error and, unless
  `FAIL_FAST`, re-normalizes with `merge_continued_literals=False` (which the
  lexer already tokenizes permissively) so a partial AST survives. `parse_cobol`
  now defers to the parser on the raise instead of returning early — which also
  sidesteps a latent bug where injecting into the result would crash on the
  `(ParseResult, ProfilingResult)` tuple returned when `enable_profiling=True`.
  The direct-call contract (`normalize_fixed_format` still raises by default) is
  unchanged. Pinned by
  `tests/unit/test_critical_fixes.py::TestUnterminatedLiteralDoesNotAbortParse`
  (COLLECT_ALL via both `parse_cobol` and `CobolParser.parse`; FAIL_FAST still
  aborts). No `.pyx`/`.c` change was needed — both paths already accept
  `merge_continued_literals`.
## 2026-07-06 (MOVE silently accepted malformed input — audit H3)

* **Updated** [parser.md](parser.md): the MOVE parser accepted incomplete
  input and produced a plausible-but-wrong node with `errors == 0` — `MOVE A
  TO.` gave a `MoveStatement` with `targets: []`; `MOVE A` (no `TO`) and a
  stream truncated at `MOVE A TO` were also accepted (audit finding H3).
  `MoveStatementParser.parse` now pulls the active `ParseContext` via
  `_utils.get_parse_context` and calls `report_parse_error` (the same
  record-and-continue path GO/CALL use) when `TO` is missing or when zero
  receiving fields follow `TO` (`target_count == 0`). Well-formed MOVEs stay
  clean, including multi-target, subscripted targets, literals, figurative
  constants, and `MOVE CORRESPONDING`. A missing **source** (`MOVE TO X`) is
  intentionally not flagged — indistinguishable from stray `*>`-comment /
  `REPLACE` pseudo-text the preprocessor does not strip; an earlier
  missing-source check faulted a valid shamrice program. Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`. The stricter check exposed
  three NIST programs previously passing the error-free guarantee *only* via
  this silent acceptance, now strict-xfail `KNOWN_ISSUES`: `SM206A` /`SM208A`
  (`COPY REPLACING` / `REPLACE` pseudo-text substitution not implemented) and
  `NC205A` (continuation-line handling shatters the split literal `-999.777`
  — a preprocessing defect, filed separately).

## 2026-07-06 (COMPUTE swallowing a following statement)

* **Updated** [parser.md](parser.md): the prior same-day fix (below)
  explicitly covered MOVE/SUBTRACT/MULTIPLY/DIVIDE but not COMPUTE.
  `ComputeStatementParser.parse()`'s expression-token-collection loop is a
  standalone inline loop (not `parse_arithmetic_operands()`), so it never
  inherited the boundary check: at `paren_depth == 0` it only stopped at a
  `PERIOD` or a value in `("ON", "NOT", "END-COMPUTE")`, with no check
  against `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES`. A `COMPUTE` with
  no trailing period, immediately followed by another statement (e.g. a
  multi-line `CALL ... USING`), had that statement's tokens silently
  appended to the COMPUTE expression string — the following statement
  vanished from the AST with `result.success == True` and no error
  reported. Found via a real DEPTMQP program (mockymock e2e work):
  `COMPUTE MQ-OPEN-OPTIONS = ...` directly followed by `CALL 'MQOPEN'
  USING ...`, which blocked all DEPTMQP/DEPTMQC testcases since mockymock
  rejects a whole compiled test file if any one testcase's MOCK doesn't
  match a boundary. Fixed by adding a `STATEMENT_KEYWORDS`/
  `CONTROL_FLOW_BOUNDARIES`/`SCOPE_TERMINATORS` check to the expression
  loop. The `SCOPE_TERMINATORS` half of that check fixes a second,
  distinct trigger of the same gap: a COMPUTE nested inside a clause body
  (e.g. `READ ... AT END COMPUTE X = Y + 1 END-READ`) with no trailing
  period before the *enclosing* scope terminator had that terminator
  folded into the expression string instead of ending the clause —
  `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES` alone don't cover
  `END-READ`/`END-CALL`/etc. Pinned by
  `tests/regression/test_tier2_silent_drop_regressions.py::TestComputeDoesNotSwallowFollowingCall`
  and `::TestComputeDoesNotSwallowEnclosingScopeTerminator`.

## 2026-07-06 (MOVE/SUBTRACT/MULTIPLY/DIVIDE swallowing a following statement)

* **Updated** [parser.md](parser.md): `MoveStatementParser`'s target loop
  now stops on the shared `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`
  (`_utils.py`) instead of a hand-rolled list missing `EXEC`/`EXECUTE`;
  `SubtractStatementParser` and the shared MULTIPLY/DIVIDE helper now call
  `parse_size_error_clauses` instead of the deleted `skip_to_period()`.
  Also fixed two more bugs this exposed in `_parse_size_error_stmts`: its
  DISPLAY mini-parser didn't stop at `NOT ON SIZE ERROR` or other
  boundaries (also fixed a latent `DISPLAY 'ADD'`-style truncation), and its
  outer dispatch loop's fallback branch unconditionally consumed tokens
  instead of stopping at `NOT`/scope-terminators, so a `NOT ON SIZE ERROR`
  clause was merged into the preceding `ON SIZE ERROR` clause instead of
  populating `not_on_size_error`. Also added `TokenType.FIGURATIVE_CONSTANT`
  to
  `ARITHMETIC_OPERAND_TOKEN_TYPES` (a pre-existing, previously-unreached gap
  the fix surfaced via `tests/samples/arithmetic_operations.cbl`'s
  `DIVIDE ... BY ZERO`). Previously, a MOVE/SUBTRACT/MULTIPLY/DIVIDE
  statement with no trailing period, immediately followed by another
  statement (most notably `EXEC SQL`), silently swallowed that statement's
  leading tokens — `result.success` stayed `True` with zero errors reported.
  Found via a real ACCTMNT.cbl banking program (mockymock e2e work): two
  EXEC SQL blocks vanished from the AST. The same class also hit a `CALL
  'CBLTDLI' USING DLI-REPL` in an IMS sample's `ELSE` branch, previously
  misattributed to "ELSE branches aren't traversed" —
  `tests/unit/test_ims_segment_analyzer.py::TestRealWorldBankingAccounts`
  updated (4 → 5 expected calls, new `test_repl_detected_in_else_branch`).
  Pinned by `tests/regression/test_tier2_silent_drop_regressions.py`
  (Group 6).

## 2026-07-05 (IO clause bodies parsed into the AST)

* **Updated** [parser.md](parser.md): documented the new "IO clause bodies"
  behaviour — `collect_clause_stmts` in
  `cobolparser/parsers/statements/_utils.py` now parses the statements
  inside `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID KEY` clause
  bodies via the statement registry instead of discarding the tokens and
  returning `[]`. Clause statements land on the IO node's clause lists and
  as AST children (traversal + serialization). WRITE gained INVALID KEY
  parsing; START now matches comparison keywords by value and consumes the
  KEY data-name; MOVE/DISPLAY/CALL-USING operand loops stop at scope
  terminators. Pinned by `tests/unit/io_statements/test_clause_bodies.py`.

## 2026-07-05 (CALL handler-body termination)

* **Updated** [parser.md](parser.md): documented how
  `CallStatementParser._parse_nested_stmts` terminates ON EXCEPTION /
  NOT ON EXCEPTION / ON OVERFLOW bodies — boundary values (`NOT`,
  `END-CALL`), an inter-statement period, and a post-nested-parse
  `previous_meaningful_token` PERIOD check (a nested statement may consume
  the sentence period itself). `_parse_using_clause` stops at
  `SCOPE_TERMINATORS` so `END-CALL` is not captured as a USING parameter.
  Previously the handler body swallowed following top-level statements
  (`STOP RUN` after `END-CALL.` ended up inside `on_exception`) —
  mockymock then refused to mock them as nested-in-boundary. Pinned by
  `tests/regression/test_call_handler_body_termination.py`.

## 2026-07-05 (program_flow typing fix)

* No concept change needed: `ProgramFlowAnalyzer`'s inner `scan()` helper
  in `analysis/program_flow.py` swapped its mypy-invalid
  `source_id: str = proc_name` default for `str | None = None` with an
  in-body `proc_name` fallback — behaviorally identical, `mypy
  cobolparser/` now clean. [analysis.md](analysis.md) documents behavior,
  not this internal signature, so only this log entry records it.

## 2026-07-05 (multi-mode OPEN file capture)

* **Updated** [parser.md](parser.md): `open_parser.py` now consumes
  subsequent mode keywords (`OPEN INPUT A OUTPUT B EXTEND C`) instead of
  breaking at them, so `IOOpenStatement.file_names` captures the files of
  every mode group; `open_mode` still reports only the first group's mode.
  Previously every file after the second mode keyword was silently dropped
  — mockymock's OPEN-site mock matching (which keys on `file_names`) was
  the motivating consumer. Pinned by
  `tests/unit/io_statements/test_open_read_parsers.py` (multi-mode-group
  tests).

## 2026-07-04 (copybook path on-disk casing)

* **Updated** [preprocessing.md](preprocessing.md): `find_copybook_file()`
  now canonicalises the found file's basename to the on-disk casing via
  `os.scandir` (helper `_on_disk_casing` in `preprocess/path_resolver.py`).
  Previously, on case-insensitive filesystems (Windows/macOS), the
  extension probe order (`.cpy` before `.CPY`) leaked probe-cased paths
  (`MEM.cpy` for an on-disk `MEM.CPY`) into
  `CopybookExpansion.included_copybooks` and warnings. The tier-2
  `PathResolver` directory index already used scandir entry names and was
  unaffected. Pinned by
  `tests/unit/test_path_resolver_gaps.py::TestOnDiskCasing`; the SM207A
  regression tests dropped their `os.path.normcase` tolerance and compare
  paths exactly.

## 2026-07-04 (numeric VALUE clause fix)

* **Updated** [parser.md](parser.md): documented the LEVEL_NUMBER-as-literal
  gotcha in `parsers/divisions/data.py`. `_parse_value_clause` and the
  level-88 value collector now accept `LEVEL_NUMBER` tokens as numeric
  literals, consume an optional `IS`, and handle `MINUS`/`PLUS` sign tokens
  — previously `VALUE 5`, `VALUE 42`, `VALUE IS <n>`, `VALUE -5`, and
  `88 ... VALUE 1` all silently lost the literal and could spawn bogus
  anonymous data items. Motivated by mockymock's working-storage reset,
  which restores items to their declared VALUE clause. Regression suite:
  `tests/regression/test_numeric_value_clause.py`.

## 2026-07-04 (later)

* **NIST known-issues burn-down** (parser/lexer/preprocess fixes; corpus
  now 457/459 error-free, and both SM101A and SM207A parse clean with
  copybook expansion):
  - `parsers/divisions/base.py`: new shared `at_division_boundary()` —
    composite header tokens always match; bare keywords only when the next
    significant token is `DIVISION`. `BaseDivisionParser.parse` now skips
    newlines inside split headers.
  - `parsers/divisions/identification.py`: comment-entries containing bare
    division keywords (OBNC1M's `AUTOMATIC DATA AND ...`) no longer end the
    division; uses `at_division_boundary()`.
  - `parsers/divisions/data.py`: section scanner stops at split division
    headers (NC113M's three-line `PROCEDURE / DIVISION / .`) instead of
    consuming them as noise.
  - `parsers/statements/arithmetic_parsers.py`: COMPUTE accepts
    `{identifier [ROUNDED]}...` receiver lists incl. subscripts (NC252A).
  - `lexer.py` + `_lexer_fast.pyx` (`.c` regenerated, Cython 3.2.4):
    trailing period after a numeric literal is a sentence terminator, not a
    decimal point, unless followed by a digit.
  - `preprocess/__init__.py` `validate_copybook_content`: continued string
    literals (column-7 `-` re-opening quote) no longer flagged unbalanced.
  - `preprocess/path_resolver.py`: `COPY member OF library` falls back to
    the plain search path when no `<dir>/<library>/` subdirectory exists.
  - Tests: `tests/regression/test_nist_edge_case_fixes.py` (minimal repros);
    `KNOWN_ISSUES` in `test_nist_cobol85_support.py` shrunk to OBNC1M
    (Area A/B phony-program, architectural) + SM101A (expansion by design);
    `KNOWN_COPYBOOK_ISSUES` now empty; new SM207A expansion test.

## 2026-07-04

* **Updated** [tests.md](tests.md): added
  `tests/integration/test_nist_cobol85_support.py` to the layout and the
  Example Corpora table. The NIST COBOL-85 corpus (459 `.CBL` + 51 `.CPY`)
  is now strictly pinned: every program must parse error-free under
  COLLECT_ALL; the 4 programs the parser cannot yet handle (`NC113M`,
  `OBNC1M`, `NC252A`, `SM101A`) are strict-xfail `KNOWN_ISSUES` entries so
  the list only ever shrinks. `SM101A` additionally must parse clean with
  copybook expansion, and all `.CPY` files must pass
  `validate_copybook_content` (2 strict-xfail validator limitations).

## 2026-07-03

* **Updated** [ast-models.md](ast-models.md): `find_all_by_type()` /
  `find_first_by_type()` now also match a node's concrete class name
  (`"MoveStatement"`, `"CallStatement"`, `"ExecSQLStatement"`, ...), not just
  the `node_type` attribute. All statement subclasses share the generic
  `node_type` `"Statement"`, so class-name matching is what lets the CLI
  `analyze` subcommand list CALL statements and `--find-type` select specific
  statement kinds (previously both silently returned nothing for statement
  class names). Source: `cobolparser/models/ast_base.py` (`_matches_type`).
* **Updated** [cli.md](cli.md) for the output-identification change: every
  CLI output is now self-describing. Added an "Output Identification" section
  (JSON documents lead with `source_file` + `program_id`; `tokenize` output
  wrapped as `{"source_file", "tokens"}`; `parse` path/`--find-type`
  extraction wrapped as `{"source_file", "program_id", "path"/"node_type",
  "result"/"matches"}`; batch entries carry `program_id`; Mermaid flowcharts
  gained a `%% Program: <name>` header) and corrected the Tokenize
  subcommand's documented output shape. Source: `cobolparser/cli/parse.py`
  (`_identification`, `_emit_report`), `cobolparser/generators/flowchart.py`;
  contract pinned by `tests/unit/cli/test_output_identification.py`.

## 2026-06-30

* **Logged untracked drift from commit `cad4db6` (2026-06-29, "Add integration
  contract documentation for backend API")**: that commit added
  [integration.md](integration.md) and updated [lexer.md](lexer.md) and
  [index.md](index.md), but never got a log.md entry. Backfilling it now:
  - **Produced** [integration.md](integration.md): documents the backend
    adapter contract (`backend/src/parsers/cobol/parser.py`) — entry points
    (`CobolParser(...).parse()`, optional `DynamicCallAnalyzer`/
    `ProgramFlowAnalyzer` analyzers, `CobolParseError`), `ParseResult`/
    `CobolProgram` attribute contract, the `program_structure` output dict
    shape, the `dependencies.*` → Neo4j relationship mapping
    (`CALLS`/`COPYBOOK`/`USES_DB2`/`USES_CICS`/`USES_MQ`), the backend's
    `ParserResult` dataclass, and handled file extensions. Defers to the
    canonical `interface-contract.md` (repo root) via the `resource:`
    frontmatter field for full detail (e.g. copybook-specific
    `is_copybook`/`source_kind`/`copybook_name` fields and the
    `VALIDATION_FAILED`/`PERMISSION_ERROR` error-message prefixes are in the
    canonical doc but intentionally summarized out of the OKF concept).
  - **Updated** [lexer.md](lexer.md) Cython Acceleration section: replaced the
    bare 3-module table with one that lists the actual pure-Python file each
    `.pyx` overrides and the specific accelerated symbols (confirmed against
    `cobolparser/_lexer_fast.pyx`: `check_division_header`,
    `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`,
    `read_number_from_text`, `tokenize`; `_preprocess_fast.pyx`:
    `normalize_fixed_format`; `_data_fast.pyx`:
    `parse_picture_clause_fast`, `parse_data_item_clauses_fast`). Added the
    guarded `try/except ImportError` activation pattern, the `~3x` throughput
    figure (from `setup.py`), and the `pip install -e ".[fast]"` extra
    (`pyproject.toml`).
  - **Updated** [index.md](index.md): added the "Integration" section linking
    to integration.md.
  - Corrected `timestamp` on lexer.md and integration.md from `2026-06-28` to
    `2026-06-29` to match the commit that actually authored their current
    content.
* **Fixed pre-existing gaps in [cli.md](cli.md)** found while verifying
  concept files against current source (none of these came from a dated
  commit since the last log entry — they predate the OKF bundle itself,
  ranging from 2026-04-17 to 2026-05-06):
  - `analyze` subcommand was documented as running "all static analyzers"
    (dead code, IO, MOVE-type, linkage, LE); it actually only runs
    `DynamicCallAnalyzer` and reports dynamic `CALL` target info
    (`called_program`/`is_dynamic`/`possible_values`) — corrected.
  - `program-flow` was missing its `--format json|mermaid|dot` flag (added in
    commit `842f246`, wired to `generators/flowchart.py`'s
    `MermaidFlowchartGenerator`/`DotFlowchartGenerator`).
  - `parse`, `batch`, `program-flow`, `analyze`, and `dead-code` were missing
    the shared `--profile`/`--profile-top-n`/`--profile-output` flags (added
    in commit `5f2468c`/`13a3f1f`).
  - `batch` was missing `--glob` (repeatable), `--workers`, and `--encoding`.
  - `tokenize` output shape was missing the `column` field.
  Bumped cli.md `timestamp` to 2026-06-30.

## 2026-06-28

* **Initialization**: Created OKF bundle for cobolparser v1.1.0.
  Concepts produced: [lexer](lexer.md), [parser](parser.md),
  [preprocessing](preprocessing.md), [ast-models](ast-models.md),
  [analysis](analysis.md), [cli](cli.md), [tests](tests.md).
