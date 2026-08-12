# cobolparser — Repository Audit, Follow-Up Pass (2026-08-12)

> **Post-hoc status note (2026-08-12, later the same day):** every
> High/Medium bug below is fixed at HEAD — commit `b495f26` ("fix: resolve
> findings from the 2026-08-12 follow-up audit", merged via PR #139).
> Re-verified by direct reproduction during the cross-repo bug review.
> This report is preserved as written; read `reports/open-findings.md`
> for what is actually still open.

This is a second audit pass performed after `reports/audit-2026-08-12.md`'s
findings were fixed and merged (PR #137, `047ab64..3809ac6`). That report is
no longer current — every High/Medium bug it listed is fixed at HEAD
(`3809ac6`). This report does **not** repeat those findings. It covers two
things instead:

1. **A correctness review of the fix diff itself** (`047ab64..3809ac6`) —
   did each fix actually resolve its finding, and did any fix introduce a
   new defect?
2. **A fresh scan of areas the first audit did not cover in depth**: the
   CLI, dialects/plugins config, AST models (`cobolparser/models/`), the
   `gen-fixtures` generator pipeline beyond its already-fixed findings, six
   analysis modules that weren't deeply reviewed before, and every
   individual verb-specific statement parser under
   `cobolparser/parsers/statements/`.

**Baseline health at HEAD (`3809ac6`), confirmed by this pass:**
`python -m pytest tests/` — 8,073 passed, 1 skipped, 1 xfailed, 0 failed
(91.52% coverage, floor 81%); `ruff check .` clean; `black --check .`
clean; `mypy cobolparser/` clean (126 files). The fix PR introduced no test
regressions.

**Headline items (fix-first):**

1. **A missing terminating period before certain statements can silently
   delete the next paragraph from the AST.** CLOSE, SET, CANCEL, OPEN, and
   SORT/MERGE's key/file-name lists all keep consuming IDENTIFIER tokens
   past a missing period, swallow the next paragraph's *name* as a bogus
   operand, and the entire paragraph — including all its statements —
   disappears from the parse tree with zero error or warning (§1, Bug 1).
   This is the same failure class MOVE/ADD/SUBTRACT were fixed for in the
   prior audit (P-B1), just left out of that fix for five sibling parsers.
2. **`ENTRY ... USING` silently drops all parameters when `USING` is on a
   continuation line** — a normal COBOL layout (§1, Bug 2).
3. **The just-merged MOVE fix has a narrow reintroduction of its own bug
   class**: a negative literal subscript right after `(` gets a stray
   space (§1, Bug 3).
4. **`gen-fixtures` `mode="all"` can report a `WHEN OTHER` (or `WHEN ANY`)
   arm as "covered" when the generated fixture never actually reaches
   it** — a zero-constraint arm is happily merged into any other
   scenario regardless of contradiction (§2, Bug 1). This undermines the
   "targeted + merged + missed == total, no silent gaps" guarantee that is
   this subsystem's core selling point.
5. **`cobol-parser io-coverage render` is completely broken** — a
   one-level-too-shallow path computation makes every invocation crash
   with an uncaught `ModuleNotFoundError` (§3, Bug 1).

---

## 1. Statement parsers (`cobolparser/parsers/statements/`)

### High-severity bugs

- **Bug 1 — Five operand-list parsers lack the paragraph-boundary guard
  that MOVE/ADD/SUBTRACT already have, so a missing terminating period
  silently deletes the next paragraph.**
  `_utils.py`'s `looks_like_paragraph_boundary` guard was added (per the
  prior audit) to DISPLAY/MOVE/COMPUTE/STRING/UNSTRING/INSPECT and the
  arithmetic verbs' additional-target loops specifically so an
  unterminated statement can't swallow the next paragraph header. It was
  never extended to these operand-collector loops, which share the exact
  same "keep consuming IDENTIFIERs until a keyword/period" shape and only
  check `is_statement_boundary` (known verb keywords), which a
  user-defined paragraph name is never a member of:
  - `close_parser.py:36-53` (file-name loop)
  - `set_parser.py:45-82` (target loop)
  - `simple_statement_parsers.py:161-186` (`CancelStatementParser`
    program-name loop)
  - `open_parser.py:58-95` (file-name loop)
  - `sort_merge_parsers.py:17-123` (`_parse_keys` / `_parse_file_list`,
    shared by SORT and MERGE)

  Reproduced (CLOSE):
  ```cobol
  MAIN-PARA.
      CLOSE FILE-A
  NEXT-PARA.
      DISPLAY 'IN NEXT PARA'.
  ```
  Confirmed via `parse_cobol`: `errors == []`, one paragraph in the AST
  (`MAIN-PARA`, 2 statements), and
  `CloseStatement.file_names == ["FILE-A", "NEXT-PARA"]`. `NEXT-PARA` is
  gone as a paragraph; its `DISPLAY` statement is silently re-parented
  under `MAIN-PARA`. The identical shape reproduces for SET
  (`SetStatement.targets` absorbs the next paragraph name and
  `set_type` stays `null` because the TO/UP/DOWN keyword slot never gets
  filled).

- **Bug 2 — `ENTRY ... USING` silently drops all parameters when `USING`
  is on a continuation line.** `entry_parser.py:99-104`
  (`_parse_using_clause`) peeks the next token for `"USING"` without
  calling `skip_whitespace()` first — every other clause-lookahead in the
  codebase does this. When `ENTRY 'name'` and `USING` are on different
  source lines, the peeked token is whitespace/newline, `"USING"` never
  matches, and the parameter list is silently empty.

  Reproduced:
  ```cobol
  ENTRY 'ALTENTRY'
      USING PARM-A PARM-B.
  ```
  → `EntryStatement(entry_name='ALTENTRY', using_parameters=[])`. The
  identical statement written on one line parses correctly, confirming
  the missing whitespace-skip is the cause.

### Medium-severity bugs

- **Bug 3 — The MOVE source-join fix (P-B1, `move_parser.py`) has a
  narrow reintroduction of the same bug class for signed subscripts.**
  `move_parser.py:225-251` (`_join_source_parts`)'s leading-unary-sign
  special case (line 248, `out in ("-", "+")`) only fires when the sign is
  the very first token of the *entire* source expression. It doesn't fire
  when a sign token immediately follows a freshly opened `(` inside a
  subscript, so a negative literal subscript gets a stray space:
  ```cobol
  MOVE WS-TAB(-1) TO WS-Y.
  ```
  → `MoveStatement.source == 'WS-TAB(- 1)'` (confirmed by direct
  reproduction). The top-level case (`MOVE -5 TO WS-Y.` → `'-5'`) is
  correct; only the after-`(` case is wrong. Any consumer that parses
  subscripts out of `MoveStatement.source` (`ProgramLayoutIndex.resolve`,
  numeric-literal regexes in `const_fold.py`) sees a corrupted subscript
  text.

- **Bug 4 — `string_unstring_parsers.py`'s `_parse_overflow_stmts`
  (lines 24-47) is a bespoke, weaker clause-body loop.** Unlike the
  shared `collect_clause_stmts` / `_parse_size_error_stmts` helpers (which
  skip one token and retry when a nested statement fails to parse), this
  STRING/UNSTRING-only ON OVERFLOW helper breaks the entire clause body on
  the first token whose value isn't in `STATEMENT_KEYWORDS`. Not
  independently confirmed as data loss, but it's the same "similar
  statements diverge subtly" pattern as Bug 1, and worth folding into the
  shared helper used elsewhere for INVALID KEY / ON SIZE ERROR bodies.

### Verified clean

`accept_parser.py`, `arithmetic_parsers.py` (including the shared
expression-tree parser), `if_parser.py`, `perform_parser.py`,
`read_parser.py`, `rewrite_parser.py`, `search_parser.py`, `start_parser.py`,
`stop_parser.py`, `unlock_parser.py`, `write_parser.py`,
`initialize_inspect_parsers.py`, `go_parser.py`, `_utils.py`.

---

## 2. `gen-fixtures` generator pipeline

### High-severity bug

- **Bug 1 — `ScenarioPlanner` can merge a zero-constraint `WHEN OTHER` /
  `WHEN ANY` arm into a scenario that contradicts it, then report the arm
  as covered.** `generators/scenarios.py:333` (`_compatible`) treats two
  scenarios as mergeable whenever their `field_constraints` touch disjoint
  field sets. `constraints.py:421` deliberately models `WHEN_OTHER` with
  zero constraints (`arms["WHEN_OTHER"] = []`), and `:849` does the same
  for an EVALUATE `Any` selector — so a `WHEN OTHER` arm's `touched_fields`
  is empty, making it "compatible" with *every* other scenario, including
  ones that pin the exact field the earlier named `WHEN`s test. `_merge_candidates`
  (`:343`) then greedily merges it into the first open scenario.

  Reproduced end-to-end: a 3-arm `EVALUATE WS-CODE WHEN "A" / WHEN "B" /
  WHEN OTHER` fed from a READ boundary, planned with `mode="all"`, yields
  scenario `"PROCESS-PARA: WHEN A"` with
  `arm_keys = ['.../WHEN_1', '.../WHEN_OTHER']` and witness
  `{'IN-REC.WS-CODE': 'A'}`. `ScenarioCoverage` reports `missed: 0` and
  `WHEN_OTHER` as `status: "merged", merged_into: "PROCESS-PARA: WHEN A"`
  — but a fixture with `WS-CODE = "A"` can never reach the `WHEN OTHER`
  branch; the branch is never actually exercised by any generated
  scenario despite being reported as targeted. `ScenarioCoverage`'s
  documented invariant ("targeted + merged + missed == total") implies
  each bucket represents *true* coverage, not merely non-conflicting field
  sets — any zero-constraint arm is vulnerable to this, not just
  `WHEN OTHER`. Fix direction: refuse to merge a zero-constraint arm into
  a scenario whose witnesses could satisfy an earlier, more specific arm's
  condition (i.e. treat "no explicit constraints" as "this arm's implicit
  precondition is that no other arm's condition holds," not "this arm
  imposes no constraints at all").

### Investigated and ruled out (no bug found)

- `values.py`'s `_format_number` overflow-correction reliably repairs the
  float-precision loss in the numeric-domain ceiling computation
  (`domains.py`, `scenarios.py`) even for wide PICTUREs (PIC 9(18)
  tested) — no PICTURE-violating value reaches rendered output.
- `program_fixtures.py:576-582`'s `static_names` set comprehension has
  hash-randomized iteration order, but it's only ever consulted via
  `.get(key)`, never iterated into output order — no determinism leak
  into `bundle.to_json()`.

### Verified clean

`generators/data/layout.py`, `values.py`, `dataset.py`, `copybook.py`,
`program_layout.py` (beyond the already-fixed A-B4), `bundle.py`
(including `write_csv_dir`'s path-sanitization/containment check),
`domains.py`'s grid-based `pick()`/exclusion logic.

---

## 3. CLI, dialects, plugins, profiling

### High-severity bug

- **Bug 1 — `cobol-parser io-coverage render` is completely broken.**
  `cli/coverage.py:155-156` computes the `tools/io_coverage` directory as
  `Path(__file__).parent.parent / "tools" / "io_coverage"`, which resolves
  to `cobolparser/tools/io_coverage` — one level too shallow; the real
  directory is the repo-root `tools/io_coverage`. Reproduced: `python -m
  cobolparser.cli.coverage render --input coverage.json` crashes with an
  uncaught `ModuleNotFoundError: No module named 'render_markdown'` and a
  raw traceback instead of a clean CLI error.

### Medium-severity bugs

- **Bug 2 — `--profile-output` crashes with a raw traceback if its parent
  directory doesn't exist, for every single-file subcommand.**
  `profiling.py:115-116` (`ProfilerContext.__exit__`) calls
  `self._profiler.dump_stats(self._prof_output)` with no directory
  creation or exception handling. Reproduced:
  `cobol-parser parse tests/samples/accept_display_operations.cbl
  --profile --profile-output /tmp/nonexistent_dir/out.prof` raises an
  uncaught `FileNotFoundError`. This affects `parse`, `analyze`,
  `dead-code`, and `program-flow`. By contrast, `batch.py:231-232` calls
  `os.makedirs(prof_output, exist_ok=True)` first — the JSON `--output`
  path (`cli/parse.py`'s `_json_out`) is also wrapped in
  `try/except OSError`. Only the profiling-binary output path in the
  single-file subcommands is unguarded.
- **Bug 3 — `cli/coverage.py cmd_validate` (lines 136-138) imports
  `scripts.validate_io_coverage`, which only resolves because Python adds
  the CWD to `sys.path` when invoked via `-m` from the repo root.** Run
  from any other working directory, this raises an uncaught `ImportError`
  — the same fragility class as Bug 1, not yet triggered by the default
  invocation pattern.
- **Bug 4 — `cli/coverage.py cmd_status` (lines 28-34) silently falls back
  to `./io-coverage.json` in the CWD when `--artifact FOO.json` doesn't
  exist, with no message that a fallback occurred**, and the resulting
  "not found" error doesn't name the path the user actually asked for. If
  a stale `io-coverage.json` happens to exist in CWD, it's silently used
  instead of erroring on the missing `--artifact` path.
- **Bug 5 — `PluginManager` is fully wired for registration but never
  consulted during parsing.** `CobolParser(plugin_manager=...)`
  (`plugins/core.py:190-224`, `parser.py:91,99`) accepts and stores a
  `PluginManager`; nothing in `parser.py` or anywhere else calls
  `get_active_plugins()`/`get_plugin()`. A caller can register plugins and
  they are silently never invoked — an extensibility API that looks live
  but is inert.
- **Bug 6 — `cobolparser/dialects/ibm_enterprise.py`'s `IBMEnterpriseCobol`
  class is entirely unreachable from the real parsing pipeline**, contrary
  to CLAUDE.md's description of it as the module doing "COMP-3, EXEC
  SQL/CICS/IMS DLI handling." Actual EXEC SQL/CICS/IMS parsing goes
  through `parsers/statements/ibm_exec_statements.py`; only
  `IBM_LE_SERVICE_CATEGORIES` from this module is reused elsewhere
  (`language_env_analyzer.py`). One latent bug lives inside the dead
  class, harmless only because it's unreachable:
  `ExecIMSStatement.set_command` (lines 128-133) sets `ims_call_type` for
  only 6 of the 14 commands `IMS_COMMANDS`/`is_ims_command` recognize —
  `CHKP`, `ROLLB`, `TERM`, `ENQUEUE`, `DEQUEUE`, `PURG`, `XRST`, `XDLT`,
  `XRPL` all leave `ims_call_type == "UNKNOWN"`.

### Verified clean

`cli/parse.py`'s argument handling, batch dedup/glob logic, `--errors`/
`--stats` exit-code semantics, and `_resolve_path` — all correct and
consistent.

---

## 4. AST models (`cobolparser/models/`)

### Medium-severity bugs

- **Bug 1 — `IOWriteStatement.advancing_mode` is set by the parser but
  never serialized in `to_dict()`.** `models/statements/io.py:205`
  declares the attribute; `parsers/statements/write_parser.py:99` sets it
  directly on the object; `IOWriteStatement.to_dict()`
  (`io.py:278-303`) never emits an `"advancing_mode"` key. Tests that
  inspect the object directly
  (`tests/unit/test_write_advancing.py:113`,
  `tests/unit/io_statements/test_write_close_parsers.py:101`) see the
  value; any `to_dict()`/`to_json()` consumer never does. Impact is
  mitigated because the same information is duplicated inside
  `advancing_clause["type"]`, but it's a real object/JSON divergence.
- **Bug 2 — `ASTNodeFactory.create()` assumes every `ASTNode` subclass's
  `__init__` takes `location` as the first positional argument.**
  `core/ast_factory.py:203-204` calls `node_class(location, **kwargs)`.
  True for statement classes, false for most structural/data classes:
  `CobolDataItem(name, level, location)`, `CobolSection(section_name,
  location)`, `CobolDivision(division_name, location)`,
  `CobolProgram(program_name, location)`, `PictureClause(pattern,
  location)`. Calling `factory.create(CobolDataItem, loc, name="X",
  level=1)` silently binds `location` to the `name` parameter instead of
  raising — Python doesn't type-check positional binding. Not reachable
  today (`create_node()` is only exercised on statement classes with
  location-only constructors), but a real landmine for any future caller
  reaching for the "centralized, validated" factory on a data/structural
  node — exactly what the class's own docstring example (`DisplayStatement`)
  invites for other classes too.

### Already tracked, re-confirmed current (not new)

`CobolFileDescription` (`models/program.py:861-1061`) remains fully built
and never instantiated — `open-findings.md` already tracks this as a
known dead-code/API-surface inconsistency.

### Verified clean

`ast_base.py` (cache invalidation on add/remove_child propagates correctly
to ancestors), `sql_statements.py`, `data_items.py`'s `PictureClause` /
`OccursClause` / `CobolDataItem` (all key-clauses cross-referenced against
`divisions/data_clauses.py` and confirmed wired), and the
`statements/{base,arithmetic,call,control,data}.py` `to_dict()`
implementations — every field set by a parser was cross-referenced against
its `to_dict()` read with no mismatches found.

---

## 5. Analysis modules not covered by the prior audit

### Medium-severity bugs

- **Bug 1 — `io_coverage_reporter.py`: the catalog's own `status` column
  is read but never used.** `load_catalog()`
  (`analysis/io_coverage_reporter.py`, line 178) reads an explicit
  `status` field (e.g. an `unsupported` marker for a deliberately
  unimplemented IBM extension) into `IoVariationCoverage.status`, but
  `generate_artifact()` (lines 280-320) derives the emitted status purely
  from whether matching tests exist. `CoverageStatus.UNSUPPORTED` is
  defined but unreachable anywhere in the module. A catalog row explicitly
  marked `unsupported` is reported as a plain `gap` (or `covered`, if a
  loosely-matching test id happens to exist) — the distinction between
  "not implemented on purpose" and "implemented but untested" is lost.
- **Bug 2 — `linkage_checker.py` never collects nested/contained
  programs' LINKAGE SECTION or `PROCEDURE DIVISION USING` clause**,
  despite the module's docstring claiming multi-program support.
  `_collect_linkage_items` (line 154) and `_collect_procedure_using` (line
  ~170) only read `ast.data_division`/`ast.procedure_division` off the
  top-level `CobolProgram`, never recursing into `ast.contained_programs`
  — unlike `_collect_entry_statements` (line 192) and
  `_validate_call_statements` (line 212), which do recurse over
  `.children` (which includes contained programs via
  `add_contained_program`/`add_child`). A nested subprogram's own
  LINKAGE SECTION 01-items never register, so `UNREFERENCED_LINKAGE` can
  never fire for them and `VALUE_TO_LINKAGE` can't catch a BY VALUE misuse
  of a nested program's linkage parameter.
- **Bug 3 — `ims_segment_analyzer.py`'s `_resolve_ssa_segment` silently
  picks one candidate on an ambiguous multi-value segment name, unlike its
  sibling method.** `_resolve_func_code` (lines 313-318) explicitly joins
  multiple possible values (`"GU/ISRT"`) to signal ambiguity when a
  MOVE-tracked variable could hold more than one value.
  `_resolve_ssa_segment` (lines 341-344) instead does
  `sorted(self._variable_values[var])[0]` — silently returning one
  alphabetically-first candidate with no ambiguity marker. A variable set
  to `'SEGB'` on one branch and `'SEGA'` on another reports
  `segment_names=["SEGA"]` as if certain.
- **Bug 4 — `io_logger.py`'s SQL `INTO` fallback regex runs against raw,
  un-scrubbed `sql_text`, unlike the primary parser path.** The parser's
  `_extract_into_variables` runs against `scrubbed` text (string
  literals/comments stripped); `io_logger.py:344-349`'s fallback (used
  when `stmt.into_variables` is empty) searches `stmt.sql_text` directly
  with `_SQL_INTO_HOST_VARS_RE`. An `INTO :x`-shaped substring that only
  appears inside a quoted string literal — which the real parser correctly
  ignores — still matches here, fabricating a spurious host-variable
  operation.

### Verified clean

`io_diagnostics.py`, `language_env_analyzer.py`, `host_var_resolver.py`,
`dead_code.py` (aside from the already-tracked reachability-gating item),
`program_flow/{graph,cycles,edges,models,analyzer}.py` (aside from the
already-tracked cycle-dedup item) — minor harmless redundancy noted in
`graph.py`'s THRU-range adjacency building, not a defect.

---

## 6. Correctness review of the merged fix diff (`047ab64..3809ac6`)

All fixes for P-B2..P-B6, A-A1..A-A7, A-B1..A-B4, D-H1, and S-1 were
verified correct and complete by independent reconstruction/reproduction,
**except** the MOVE subscript-sign case documented as Bug 3 in §1 above,
which is a narrow reintroduction of the P-B1 bug class the fix was meant
to eliminate. No other regressions found in the diff.

---

## Recommended fix order

1. **§1 Bug 1** — extend `looks_like_paragraph_boundary` to
   `close_parser.py`, `set_parser.py`, `CancelStatementParser`,
   `open_parser.py`, and `sort_merge_parsers.py`'s key/file-name loops.
   Silent paragraph deletion is the most severe defect in this pass.
2. **§1 Bug 2** — add `skip_whitespace()` before the `USING` lookahead in
   `entry_parser.py`.
3. **§2 Bug 1** — stop `ScenarioPlanner._compatible`/`_merge_candidates`
   from merging zero-constraint arms (`WHEN OTHER`, EVALUATE `Any`) into
   scenarios whose witnesses could satisfy an earlier, more specific arm.
4. **§1 Bug 3** — extend the leading-unary-sign special case in
   `move_parser.py`'s `_join_source_parts` to fire right after an opening
   `(`, not just at the start of the whole source.
5. **§3 Bug 1** — fix the `tools/io_coverage` path depth in
   `cli/coverage.py:155-156`.
6. **§3 Bugs 2-4** — guard `--profile-output` with `os.makedirs`, make
   `cmd_validate`'s import CWD-independent, and make `cmd_status`'s
   fallback explicit.
7. Remaining medium items (§3 Bugs 5-6, §4, §5) in one pass; §1 Bug 4 as a
   drive-by cleanup.
