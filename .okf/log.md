# OKF Update Log

## 2026-08-11 (DeadCodeAnalyzer ALTER subject falsely marked referenced)

Dead Code & Program Flow module audit finding #6: `DeadCodeAnalyzer.
_collect_alter_refs` (`cobolparser/analysis/dead_code.py`) added *both*
names from `ALTER paragraph-name TO PROCEED TO target-name` to the
reference set, but `paragraph-name` (the ALTER's subject — the paragraph
whose internal GO TO gets rewritten) is not an incoming jump; only
`target-name` is. This hid genuinely dead paragraphs whenever a program
named them only as an ALTER subject, and put `DeadCodeAnalyzer` out of
step with `ProgramFlowAnalyzer`'s `unreachable_nodes`, whose ALTER edge
(`program_flow/edges.py::process_alter`) already only flowed
subject to target and never had this bug. Fixed by dropping the
`from_paragraph` add; only `to_paragraph` counts as referenced now.
Updated: [analysis.md](analysis.md) (DeadCodeAnalyzer section). Pinned by
`TestAlterReferences.test_alter_never_called_paragraph_is_dead`
(`tests/unit/analysis/test_dead_code.py`).

## 2026-08-10 (reports/open-findings.md consolidated)

At the user's request, cleaned up `reports/open-findings.md`: it had grown
into a 796-line journal of dated status updates and full per-finding
writeups for every HIGH (H1-H11) and MEDIUM (M1-M16) finding, all of which
are already fixed and pinned by regression tests, plus references to
`reports/audit-2026-07-06/07/08/09.md` and
`cobol-parser-example-parse-gaps.md`, which no longer exist in the repo
(already superseded and deleted in an earlier pass). Rewrote it in place as
a single ~130-line file listing only what's currently open: M17
(branch-coverage debt), the LOW-severity list, and the test/tooling gaps
list. Two items were dropped as stale during the cleanup rather than
carried forward: the Tier-2 path-resolver containment gap (formerly "H6")
now has dedicated regression coverage
(`TestH6PathResolverContainment` in
`tests/regression/test_open_findings_high_regressions.py`), and CI's
Cython-extension build is no longer implicit — the `build` job added
2026-08-06 (see below) runs `build_ext --inplace` explicitly. Fixed-finding
history remains available in `CHANGELOG.md` ("Unreleased → Fixed") and this
file's own git history; no code changed.

## 2026-08-10 (Copybook-triggered comment-line drift in normalize_fixed_format)

GitHub issue #123: `program-flow`'s `location.line` drifted backward from a
paragraph's real source line by one per full-line comment anywhere earlier
in the file, but only when a `COPY` statement preceded it — traced to
`normalize_fixed_format`'s `flush_parts()` silently dropping (no
placeholder at all) a full-width, blank-indicator physical line whose
program-text is itself entirely blank. That exact shape never arises in a
plain fixed-format parse, only after `copy_statement_parser.
remove_comment_lines` blanks a `*`-comment line ahead of a second
`normalize_fixed_format` pass over copybook-expanded source. Fixed in both
`cobolparser/preprocess/__init__.py` and `cobolparser/_preprocess_fast.pyx`
by tracking whether a logical line was actually started rather than
inferring it from whether its merged text is non-empty. Rebuilt the Cython
extension in-place to regenerate `_preprocess_fast.c`. Updated:
[preprocessing.md](preprocessing.md) (Line-Number Preservation section).

## 2026-08-06 (CI no longer runs the full pytest suite automatically)

Requested change: too many tests (~5,969) to run on every push/PR; run them
locally instead. In `.github/workflows/ci.yml`, replaced the `test` job's
automatic-on-push/PR pytest run with a new `build` job (matrix Python
3.11/3.12/3.13: `pip install -e ".[dev,fast]"` + `python setup.py build_ext
--inplace`, no tests) that runs on every push/PR as before. The original
`test` job (`pytest tests/ -v`) is kept in the file but gated with
`if: github.event_name == 'workflow_dispatch'`, so it's available as a
manual Actions-tab trigger when CI needs to confirm the full suite, without
slowing down normal push/PR runs. Updated: [tests.md](tests.md) (CI/CD
section), root `CLAUDE.md` (CI/CD section).

## 2026-08-06 (Unbounded OCCURS count in test-data generation)

Code-review finding: `generators/data/layout.py::_occurrence_indexes` read
the OCCURS numeral straight from the parser with no upper bound, then
materialized `list(range(1, times + 1))`. Confirmed live: `05 TBL OCCURS
5000000 TIMES PIC X.` made `flatten_record()` take ~47s and add ~2.6GB
resident memory. `DataGeneratorOptions.max_occurs` defaults to no cap for
both `gen-data` and `gen-fixtures`, and `gen-fixtures` didn't even expose
the `--max-occurs` flag that `gen-data` did.

Fixed with a hard ceiling, `_MAX_OCCURS_HARD_CAP = 10_000` in
`generators/data/layout.py`, applied inside `_occurrence_indexes`
regardless of caller config (i.e. it also clamps an explicit `max_occurs`
larger than the ceiling) — same pattern as the existing
`_MAX_RANGE_EXPANSION` cap on level-88 THRU ranges. Added the missing
`--max-occurs` flag to the `gen-fixtures` CLI, threaded into its
`DataGeneratorOptions`. Re-ran the 5,000,000-occurrence repro after the fix:
0.18s / ~5MB, 10,000 specs. New tests:
`test_pathological_occurs_count_is_hard_capped` and
`test_max_occurs_beyond_hard_cap_is_still_clamped` in
`tests/unit/test_copybook_data_generator.py`;
`test_max_occurs_flag_defaults_to_none`,
`test_max_occurs_flag_parses`, `test_max_occurs_flag_is_accepted_end_to_end`
in `tests/unit/cli/test_gen_fixtures_cli.py`. Updated:
[generators.md](generators.md) (flattening rules table note).

## 2026-08-06 (ConstantFolder RecursionError on long PERFORM chains)

Code-review finding: `const_fold.py`'s `_walk_perform` followed a chain of
out-of-line `PERFORM`s (`P1` performs `P2` performs `P3` ... `PN`) by
recursing through Python's own call stack, one frame per paragraph — a few
hundred chained paragraphs (well under `sys.getrecursionlimit()`'s default
of 1000) raised an uncaught `RecursionError`, and every `gen-fixtures` call
reaches this path unconditionally (both `generate()` and
`generate_with_scenarios()`). Reproduced: 300 chained paragraphs folded
fine, 500 crashed. `_poison_written_names` had the identical defect for a
`PERFORM`-to-paragraph chain reached from inside a poisoned loop/branch body
— reproduced separately at ~1500 chained paragraphs (a higher threshold
since it recurses through fewer stack frames per paragraph). Both converted
to an explicit frame stack, the same fix `program_flow/cycles.py` already
uses for its own paragraph-graph traversal; recursion is still used for
genuinely nested statement lists (bounded by real source nesting, not
paragraph-chain length), left alone deliberately. New regression tests:
`tests/unit/analysis/test_const_fold.py::TestPerformChaining` — 2000-chain
tests for both paths, plus a sequential-re-PERFORM-of-the-same-paragraph
test pinning that the `visiting` add/discard lifetime (now bracketing a
frame push/pop instead of a recursive call/return) is unchanged. Full
detail: [analysis.md](analysis.md) (`ConstantFolder` section). Also
updated: `CHANGELOG.md`.

## 2026-08-05 (EJECT compiler-directing statement unrecognized)

User report: "make sure the ejects in the program are ignored, and
copybooks [too]." Confirmed via direct `parse_cobol()` repro: `EJECT` (the
source-listing page-eject directive) had no `TokenType`, no keyword entry,
and no statement parser, so it lexed as a bare `IDENTIFIER`. Two concrete
failures: (1) `EJECT.` (trailing period, the common real-world style) was
indistinguishable from a paragraph name to `is_paragraph_or_section_start`
and silently split the enclosing paragraph in two around a bogus empty
`EJECT` paragraph; (2) `EJECT` with no period fell through to the
"unsupported statement" recovery path and emitted a spurious "Unparsed
tokens ... clause or statement not fully supported" warning. Both
reproduced identically through COPY-expanded copybook text (copybooks with
shared paragraphs or multiple record layouts commonly use EJECT between
sections), confirmed with a dedicated repro before concluding it needed no
copybook-specific fix.

Fixed the same way `CONTINUE` (a genuine no-op) is handled: `TokenType.EJECT`
+ `KEYWORDS` entry (`lexer.py`), added to `STATEMENT_TOKEN_TYPES`/
`STATEMENT_KEYWORDS` (`_utils.py`), a new `EjectStatementParser` ->
`EjectStatement` no-op node (`simple_statement_parsers.py` /
`models/statements/misc.py`), registered in `create_statement_registry()`
right after `ContinueStatementParser`. New test:
`tests/regression/test_eject_statement.py`. Updated:
`tests/unit/test_procedure_registry_dispatch_order.py` and
`tests/regression/test_swallow_sweep.py` (both have completeness guards
that fail on an unfixtured newly-registered parser). Full detail:
[parser.md](parser.md) ("EJECT compiler-directing statement was
unrecognized"). Also updated: `CLAUDE.md` (Statement Parsers / AST
Statement Models tables), `CHANGELOG.md`.

## 2026-08-04 (PR #108 Copilot review: dead --describe flag, MANIFEST.json type mismatch)

GitHub Copilot's automated review of PR #108 left two comments; verified
both against the actual code before acting (per this repo's own "check the
claim, don't just trust or dismiss the bot" discipline) — both were real.

* **`gen-fixtures --describe` was a silent no-op.** Registered on the
  argument parser (`cobolparser/cli/parse.py`) with help text "Emit the
  resolved bundle as JSON (implied by --format json)" but `args.describe`
  was never read anywhere in `_cmd_gen_fixtures` — confirmed by grepping
  the whole file for `.describe` and finding only `gen-data`'s own,
  unrelated, correctly-wired `--describe` handling. Not in `CLAUDE.md`'s
  own `gen-fixtures` command-line documentation, not exercised by any
  test. Removed the flag entirely (its own help text already admits
  `--format json`, the default, already does what it would do — nothing
  distinct was left to implement).
* **`write_csv_dir()`'s `MANIFEST.json` changed a field's type.** Every
  fixture's `"sequence"` (normally `list[dict[str, str]]`) was replaced
  with a hint string (`"see <scenario-slug>/"`). A consumer that ran
  `MANIFEST.json` through the same deserializer as a real bundle JSON —
  reasonable, since every other key matches — would silently iterate the
  string character-by-character in place of real rows, rather than hit a
  clean type error. Fixed: `sequence` now stays `[]`; a new `csv_path` key
  per fixture (the CSV's path relative to the output dir, or `null` for a
  fixture with no CSV) carries the same information the hint string did,
  without the type mismatch.

Both fixed in `cobolparser/cli/parse.py` / `cobolparser/generators/data/bundle.py`.
New test: `test_program_fixtures.py::TestWriteCsvDir::test_manifest_sequence_stays_a_list_not_a_hint_string`
(zips the real `Scenario`/`BoundaryFixture` objects against their `to_dict()`
counterparts in the manifest, positionally, to check `csv_path` against
each fixture's *actual* layout/sequence state, not just spot-check one
value). Updated: [cli.md](cli.md) (removed the `--describe` flag from
`gen-fixtures`'s command line and documented the manifest fix),
[generators.md](generators.md) (`write_csv_dir` section),
`docs/fixture-bundle-schema.md` (`write_csv_dir` section), `CHANGELOG.md`.

## 2026-08-04 (interface-contract.md: pin the mocky-mock generators surface)

`interface-contract.md` gained a new "Generators Surface (mocky-mock)"
section, documenting the second external consumer of this repo alongside
the LegacyLens backend adapter it already covered: mocky-mock's `mockymock
generate --with-data` / `mockymock fixtures` subcommands (Phase 8 of the
`gen-fixtures` program-scoped test-data initiative) call
`cobolparser.generators.ProgramFixtureGenerator`/`DataGeneratorOptions`/
`generate_with_scenarios_from_file` directly and consume
`FixtureBundle.to_dict()`/`.to_json()`, gated on `bundle_version`. This is a
documentation-only change (no `cobolparser/` source touched, so
`scripts/okf_staleness_check.py`'s `OKF_MAP` — which only tracks
`cobolparser/*`/`tests/` source prefixes, not root-level docs — has nothing
to flag for it); the entry exists per this repo's own convention of logging
every `.okf`-bundle-adjacent change, not because the staleness gate fired.
No detail is duplicated here that isn't already canonical in
[`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
new section links to it rather than restating its key tables, so the two
documents can't drift apart from a future bundle-shape change landing in
only one of them.

## 2026-08-04 (READ terminal status: unsafe placeholder field name)

Found integrating mockymock's `gen-fixtures` Phase 8 (`generate
--with-data`): `ProgramFixtureGenerator`'s READ `terminal` dict fell back to
a literal placeholder field name, `"FILE-STATUS"`, whenever a READ boundary
had no resolvable `FILE STATUS` clause — confirmed live, not theoretical,
against `INVUPDT.cbl`'s `INV-FILE`, which declares no `FILE STATUS` clause
at all. A consumer that splices that placeholder into a real `MOVE`
target — exactly what mockymock's `.cut` scaffolder does — generates COBOL
that fails to compile, since `"FILE-STATUS"` is not a data-name that exists
in the target program.

* **Root cause**: the `terminal` computation had its own ad hoc fallback
  (`status_field or "FILE-STATUS"`) instead of reusing `_status_dict`'s
  already-correct two-step resolution (`boundary.status_field`, then
  `index.file_facts(key).file_status_field`, else give up).
* **Fixed** `cobolparser/generators/program_fixtures.py`: extracted the
  shared two-step lookup into `_resolve_status_field(boundary, index) ->
  str | None`, used by both `_status_dict` and the `terminal` computation.
  `terminal` is now `None` (never a placeholder string) when neither step
  resolves — "exact by construction, or absent," the same rule this
  initiative's `ConstantFolder` (Phase 7) already follows.
* **A second bug in the same code path**, found while fixing the first:
  the READ fixture's `call_count` expectation derived "did an AT-END
  invocation happen" from whether `terminal` was truthy — after the fix
  above, that conflates "the sequence exhausts" (a fact about the program's
  `AT END` handler, independent of whether a status field can be named)
  with "we know a field name to report it in." A program that reads to EOF
  with an unresolvable status field still genuinely invokes the boundary
  one more time; undercounting it would make `VERIFY ... WAS CALLED n
  TIMES` wrong. Fixed by checking `"AT_END" in boundary.handlers` directly
  or a `has_terminal_invocation` flag, independent of `terminal`'s
  resolution.
* **Updated** [generators.md](generators.md): the Tier 1 `call_count`
  formula and the READ per-category generation-rules row both still
  described the old, buggy behavior verbatim (`terminal` set to
  `{status_field or "FILE-STATUS": "10"}`, `times = len(sequence) + (1 if
  terminal else 0)`) — corrected to match the fix.
* **Tests**: `tests/unit/test_program_fixtures.py` gained
  `TestTerminalStatusFieldResolution` (both the safe-`None` and the
  real-field-resolves cases, using `tests/samples/file_operations.cbl`'s
  `SEQ-FILE`/`WS-SEQ-STATUS`) and a corrected assertion in the pre-existing
  `test_empty_input_scenario_call_count_is_one_not_zero` (previously
  asserted the placeholder dict; now asserts `terminal is None` with the
  count still `1`). Full suite: 7,795 passed / 13 skipped / 1 xfailed,
  91.44% coverage. Commit `b3e2b32`, `CHANGELOG.md` Bug Fixes.

## 2026-08-03 (normalize_fixed_format column-73+ overflow warning)

Fixed a silent-truncation bug found during a whole-branch review of
mocky-mock's not-yet-merged `export` command: `normalize_fixed_format`'s
`line[TEXT_START_COL - 1 : TEXT_END_COL]` slice never bounds-checked the
line length, so any non-comment line longer than 72 columns had its
columns-73+ tail silently dropped — no warning, no error, no signal to the
caller. Repro: a hand-written 77-column `DISPLAY "X" WS-FIELD.` line (56
columns of indentation) silently became `DISPLAY "X" WS-F` (no closing
quote, no period) with mocky-mock still writing it to its "durable
deliverable" output and exiting 0. Confirmed as a live, not just
theoretical, bug: `legacy-application/cobol/ACCTMNT.cbl:388` already splits
the identifier `WS-PARM-DORM-DAYS` into `WS-PARM-DORM-D` + dropped `AYS`
this same way.

* **Updated** [preprocessing.md](preprocessing.md): documented the new
  `warnings: list[str] | None = None` parameter and the mid-token detection
  rule (column 72 *and* column 73 both non-blank — content actually split a
  token, as opposed to a traditional 80-column identification field like
  NIST CCVS85's `IC1014.2`, which must **not** warn; empirically checked
  against both `legacy-application/cobol/*.cbl` and the vendored
  `examples/nist-cobol85` corpus before picking this rule over a naive "any
  non-blank content past column 72" check, which would have fired on nearly
  every line of the NIST corpus).
* **Changed** `cobolparser/preprocess/__init__.py` and
  `cobolparser/_preprocess_fast.pyx` (mirrored, rebuilt via `python setup.py
  build_ext --inplace`, regenerated `.c` committed) — both now track the
  1-based physical line number and append one `f"Line {n}: content beyond
  column 72 was dropped mid-token: {dropped!r}"` message per qualifying
  line when a `warnings` list is passed. Comment lines are never checked
  (their text is discarded whether truncated or not). Default `None`
  preserves the exact old (silently-truncating) behavior for every existing
  caller.
* **Added**
  `tests/regression/test_normalize_column_overflow_warning.py`: pins the
  mid-token-warns / traditional-field-does-not-warn / comment-line-does-not-
  warn / `debug_lines_as_comments=False` D-line flip / no-`warnings`-arg
  backward-compatibility cases, plus a pure-vs-Cython parity test over the
  `warnings` list itself (the existing parity tests only ever compared the
  returned string).
* **mocky-mock side** (separate repo): `mockymock/cli/checks.py` now
  threads a `warnings` list through its `normalize_fixed_format` calls and
  exposes it on `StaticCheckResult`; `mockymock export` (only — `run`/`lint`
  intentionally left unchanged, out of scope for this fix) refuses instead
  of silently writing a corrupted "durable deliverable" and exiting 0. See
  mocky-mock's own `.okf/log.md` for that side of the fix.
## 2026-08-02 (generators/data/ package split: final whole-branch-review fixes)

Seven-task, zero-behavior-change refactor split `cobolparser/generators/
copybook_data.py` into a modular package `cobolparser/generators/data/`
(`options.py`, `errors.py`, `layout.py`, `values.py`, `dataset.py`,
`copybook.py`, `__init__.py`), with `copybook_data.py` reduced to a
backwards-compatible re-export shim — see the entry below for the original
feature. Each of the 7 tasks passed its own task-level review; a final
whole-branch review then caught a handful of doc/cosmetic gaps no single
task's diff could see on its own. Fixed here in one pass, no source-logic
changes:

* **Updated** [generators.md](generators.md): corrected `FieldSpec`'s
  description from "namedtuple" to "dataclass" — `layout.py` defines it
  with `@dataclass`, and `_assign_columns()` relies on that mutability to
  assign `spec.column` in place after construction, which a namedtuple
  could not support. Frontmatter `timestamp` bumped.
* **Relocated** the subsystem's module docstring (overview, `Typical
  use::` example, determinism/seed-replay guarantee, and the four "Design
  notes" bullets on REDEFINES/OCCURS/edited-pictures/FILLER defaults) from
  `copybook_data.py` onto `cobolparser/generators/data/__init__.py` — the
  new canonical home for the subsystem. The refactor had deleted it from
  `copybook_data.py` (flagged during Task 6 as a possible gap for Task 7)
  with no relocation target; Task 7 did not carry it forward, so the final
  review caught it. Also added the package's missing `from __future__
  import annotations` for consistency with every other module in `data/`
  (flagged during Task 1, deferred to final review).
* Removed a vestigial `if TYPE_CHECKING: pass` block (and its now-unused
  `TYPE_CHECKING` import) left in `data/values.py` from the Task 3
  extraction (flagged during Task 3, deferred to final review) — guarded
  nothing, served no purpose.
* Softened `copybook_data.py`'s shim docstring: it claimed the vendored
  backend copy (`backend/_vendor/cobol-parser/`) imports from this path.
  Checked directly against the sibling repo — the vendored copy predates
  the `gen-data` feature entirely (no `copybook_data.py`, no `data/`
  package, no reference anywhere), so that claim was dropped. The other
  two reasons already in the docstring (the unit test, `cli/parse.py`'s
  lazy import) were independently re-verified correct and kept.
* **Updated** root `CLAUDE.md`: the `cobolparser/generators/` section had
  lost its behavioral summary (honors PICTURE/USAGE/OCCURS/REDEFINES/
  level-88/VALUE, deterministic per `seed`, backs `gen-data`) when Task 7
  rewrote the bullet to describe the new file layout. Restored the
  behavioral sentence alongside the file-structure description rather
  than reverting Task 7's structural update.
* **Moved** `CHANGELOG.md`'s Task-7 "internal restructure" bullet from
  `## Unreleased` → `### Added` to `## Unreleased` → `### Changed` (Keep a
  Changelog, which this file's header cites: a no-API-change internal
  restructure is a "Changed", not an "Added"). Placed at the top of that
  section, alongside this repo's other god-class/module-decomposition
  refactor entries, consistent with the section's newest-first ordering.

Full suite green after the fix wave: 7327 passed / 13 skipped / 1 xfailed
(unchanged), coverage 92.11% (up from the pre-fix-wave 92.10% — removing
`values.py`'s dead `if TYPE_CHECKING: pass` block also removes an
always-missed branch/statement, so the uptick is an expected side effect
of finding 3, not a regression). `ruff check .`, `black --check .`, and
`mypy cobolparser/` all clean.

## 2026-08-02 (copybook → CSV synthetic test-data generation)

New feature: `cobolparser/generators/copybook_data.py` plus a
`cobol-parser gen-data` CLI subcommand. Flattens a copybook record layout
into CSV columns and generates rows of values constrained by each field's
PICTURE, `USAGE`, level-88 domain, and `VALUE` clause.

* **Created** [generators.md](generators.md) — new concept file covering both
  generator modules. `flowchart.py` was previously undocumented in the OKF
  (only mentioned in passing from cli.md's `program-flow --format`); it now
  has a home alongside `copybook_data.py`. Documents the public API, the
  copybook-fragment parsing strategy (program-skeleton wrapper, free-form
  Area-B shift, synthesised record root for level-02-only copybooks), the
  flattening rules table, the four-level value-precedence chain, and the
  determinism/seed-replay guarantee.
* **Updated** [index.md](index.md): added a Generators entry under
  "Analysis & Generation".
* **Updated** [cli.md](cli.md): added the `## Gen-Data` subcommand section
  between Expand and Analyze — flags, the two JSON modes (`--list-records`,
  `--describe`), and the note that this subcommand emits **CSV** on stdout
  rather than the JSON every other subcommand emits, so it is deliberately
  outside the "Output Identification" convention documented at the top of
  that file.
* **Updated** [tests.md](tests.md): added the three new test files to the
  directory layout and a generators.md cross-reference.

Two parser behaviours were confirmed against source while writing this and
are worth recording, since both shaped the generator's design:

* `ConditionNameItem.values` records `VALUE 2 THRU 4` as
  `["2", "THROUGH:4"]` — the range end is *marked*, not expanded. Consumers
  wanting the domain must expand it themselves (`_condition_values` does,
  capped at 64 entries).
* `PictureClause.is_signed` reports only an explicit `S`. A numeric-edited
  picture carrying `+`/`-`/`CR`/`DB` (e.g. `PIC -ZZ,ZZ9.99`) holds a sign but
  reports `is_signed=False`; the generator compensates in `_is_signed()`.
  Noted in [ast-models.md](ast-models.md) under Data Items.

## 2026-07-27 (validate_copybook_content: multiline missing-period regex + comment-only misreport)

User-reported pair of bugs in `cobolparser/preprocess/__init__.py`'s
`validate_copybook_content`, both specific to copybooks that start with (or
contain) comment lines — confirmed by direct script reproduction before any
fix was written, per this repo's TDD convention.

* **Updated** [preprocessing.md](preprocessing.md): documented both fixes
  under "Copybook Expansion".
  1. `_DATA_DEF_RE` used bare `\s`, which matches newlines. Since
     `remove_comment_lines` blanks comment lines to whitespace *before*
     `validate_copybook_content` runs, `^\s*` could bridge across those
     blanked lines and `[^\s]+` (not excluding `.`) swallowed a trailing
     period — producing false "missing terminating period" warnings on
     correctly-terminated lines, misattributed to the wrong line (reproduced:
     a copybook with 2 leading comment lines + 2 correctly-terminated code
     lines got both flagged, warnings attached to line 1 and line 4 instead
     of neither). Fixed by switching internal `\s`/`\s+`/`\s*` to
     `[ \t]`/`[ \t]+`/`[ \t]*` (can't cross a line) and the value token to
     `[^\s]*[^\s.]` ("non-whitespace, not ending in a period" — excludes
     only a trailing period, not a PICTURE's own internal decimal point).
     An initial `[^\s.]+` draft excluded periods everywhere in the token,
     which silently broke detection for decimal-point PICs like
     `PIC 9(5).99` with a genuinely missing terminator — caught by the
     advisor review before landing, fixed, and pinned with two more tests.
  2. The "contains only comments" check was dead code in the real pipeline:
     `remove_comment_lines` already blanks every comment line before
     `validate_copybook_content` sees the content, so a genuinely
     comment-only copybook fell into the earlier "is empty" branch instead —
     misleading, since comment-only is a legitimate documentation-only
     pattern. Fixed by adding an optional `raw_content` parameter (the
     pre-strip source); `_expand_source_recursive` now captures and passes
     it so the correct message is reported.
* Added regression tests to
  `tests/unit/test_preprocess_init_coverage.py::TestValidateCopybookContent`
  (6 new cases, written and confirmed failing before each fix) and
  strengthened `tests/unit/test_copybook_expander_coverage.py::
  TestExpandCopybooks::test_content_validation` to assert the exact message
  instead of just "warnings is non-empty".
* Full suite green: 7102 passed / 13 skipped / 1 xfailed, 92.20% coverage
  (up from 7096, no regressions). `ruff check`, `black --check`, and
  `mypy cobolparser/` clean on touched files.

## 2026-07-24 (targeted follow-up round: CALL BY-mode persistence, COMPUTE comma targets; vendor sync)

User-scoped follow-up after reviewing the five-fix sweep below ("one more
targeted round: SEARCH WHEN conditions, CALL BY CONTENT/REFERENCE groups,
READ/WRITE INTO clauses"). Checked those plus COMPUTE (an obvious sibling
of the just-fixed ADD/SUBTRACT/MULTIPLY/DIVIDE target lists). Found and
fixed two more real bugs, confirmed two candidates needed no fix:

* **Updated** [parser.md](parser.md): CALL's `BY REFERENCE`/`CONTENT`/
  `VALUE` passing mode didn't persist across a comma-separated parameter
  list within one BY-phrase group (`passing_mode` was reset to the
  REFERENCE default every loop iteration instead of only when a fresh
  `BY` keyword appeared) — a silent semantic corruption (parameter names
  intact, mode wrong), not a data-drop. COMPUTE's multi-target comma list
  (`COMPUTE A, B = expr`) had zero comma handling and was a **hard parse
  failure** ("COMPUTE statement missing '=' operator", no AST node at
  all) — worse than every other fix in this bug class, which were all
  silent/warned drops rather than outright failures. SEARCH's
  WHEN-condition collector and READ/WRITE's INTO/FROM clauses were
  checked and confirmed (by direct repro, not grammar inspection alone)
  to need no fix — neither takes a list per the standard grammar.
* **Updated** [ast-models.md](ast-models.md): new note on
  `CallStatement.using_parameters`' mode-persistence fix.
* Extended `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py` to
  29 tests (was 22): `TestCallByModePersistsAcrossCommaList` (3),
  `TestComputeCommaTargets` (4).
* Full suite green: 7096 passed / 13 skipped / 1 xfailed, 92.20% coverage
  (up from 7089, no regressions). `ruff check .`, `black --check .`, and
  `mypy cobolparser/` all clean on touched files.
* **Vendor sync**: `backend/_vendor/cobol-parser/cobolparser/` was stale
  (predated even PR #99-#101) — user approved syncing it. Copied via
  `cp -r cobolparser/. ../backend/_vendor/cobol-parser/cobolparser/`
  (note the trailing `/.`: a bare `cp -r src/ dst/` against an
  **already-existing** `dst/` nests `dst/src/` instead of overwriting —
  hit this on the first attempt, caught via `diff -rq`, corrected).
  Also found and removed one genuinely stale leftover file in the vendor
  copy predating this repo's own 2026-07-14 `program_flow.py` →
  `program_flow/` package refactor (the source repo has no flat
  `program_flow.py` anymore; the vendor copy still had both the stale
  file and the new package, an ambiguous same-name module+package
  situation `cp -r` alone doesn't clean up since it only adds/overwrites,
  never deletes). Verified post-sync via a standalone import + parse
  smoke test against the vendored copy directly (not the full backend
  service, whose own dependencies weren't verified in this pass).
  `diff -rq` confirms full parity with `cobol-parser/cobolparser/`
  (excluding `__pycache__`) after the fix. Re-synced a second time after
  the CALL/COMPUTE fixes above landed.
* `CHANGELOG.md` (Unreleased → Fixed) and `reports/open-findings.md`
  updated in the same pass.

## 2026-07-24 (follow-up comma-list sweep: INITIALIZE, SORT/MERGE KEY/USING/GIVING, arithmetic GIVING)

Continuing the gap audit (user request: "make sure there is no gaps in the
cobolparser") after reconciling the doc debt below, re-verified the
comma-truncation bug class the 2026-07-22/23 sweep fixed elsewhere against
parsers that sweep didn't touch. Found and fixed four more real instances,
via direct `parse_cobol()` repro (not spec-recitation) before writing any
fix, per this repo's established methodology. A subsequent advisor
second-opinion review of this same pass surfaced a fifth, adjacent
instance (MULTIPLY/DIVIDE format-1 multi-target, distinct from the GIVING
multi-target fix already made) that the repro sweep itself had not
covered — confirmed empirically the same way, then fixed and pinned
alongside the other four rather than left as a known gap.

* **Updated** [parser.md](parser.md): new "Follow-up comma-list sweep:
  INITIALIZE, SORT/MERGE KEY/USING/GIVING, arithmetic GIVING (2026-07-24)"
  section. `INITIALIZE id-1, id-2, ...` (warned drop, now fixed).
  `SORT`/`MERGE` `KEY field-1, field-2 ...` — **fully silent**
  (`errors=[], warnings=[]`), the worst instance of this bug class found
  to date. `SORT`/`MERGE` `USING`/`GIVING file-1, file-2 ...` — also fully
  silent, same shared `_parse_file_list` helper. `ADD`/`SUBTRACT`/
  `MULTIPLY`/`DIVIDE ... GIVING id-3, id-4 ...` (multi-target GIVING list,
  symmetric with the TO/FROM multi-target fix from 2026-07-22/23, which
  did not extend to GIVING).
* **Updated** [ast-models.md](ast-models.md): new field notes for
  `ArithmeticStatement.givings: list[str]` and `MultiplyStatement`/
  `DivideStatement` now populating `.target`/`.targets` for format 1.
* New test file `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`
  (22 tests) pins all five fixes plus back-compat coverage for the
  pre-existing single-target/space-separated forms, including an explicit
  guard that format-2 (GIVING) MULTIPLY/DIVIDE do NOT gain a spurious
  `.target`.
* **Methodology note kept in parser.md:** the SORT/MERGE test's first
  draft used a fixture line that itself exceeded fixed-format column 72,
  producing a `giving_files: ['WS']`-shaped truncation that initially
  looked like a fifth bug. Confirmed via direct lexer/column inspection
  that this was a test-fixture artifact (this repo's own documented
  column-72 truncation semantics, correctly applied) before concluding
  so — fixed by reformatting the fixture across two lines, not by
  changing parser code. Recorded as a reminder for future fixture
  authoring in this repo, not as a finding.
* Full suite green after all five fixes: 7089 passed / 13 skipped / 1
  xfailed, 92.20% coverage (up from the 7067/92.19% baseline — +22 new
  tests, no regressions). `ruff check .` and `mypy cobolparser/` clean
  (107 source files; the shared `_BinaryArithmeticNode` structural
  `Protocol` gained a `set_target` method to type-check the format-1 fix);
  `black --check .` clean on all touched files (one pre-existing,
  unrelated formatting drift in
  `tests/regression/test_tier2_silent_drop_regressions.py`, not touched by
  this pass, left alone as out of scope).
* `CHANGELOG.md` (Unreleased → Fixed) and `reports/open-findings.md`
  updated in the same pass.

## 2026-07-24 (OKF reconciliation for PR #99-#101: statement-support verification sweep + EOF sentinel fix)

Nine fixes landed on `main` 2026-07-22/23 (PR #99, #100, #101 — commits
`5492c40`, `824f654`, `64ff7b9`, `316f0ce`, `82a82ec`, `68f68c0`,
`ddbc688`, `50b6028`, `4a8daa3`) with no matching OKF/`CHANGELOG.md`/
`open-findings.md` update. Reconciled retroactively while auditing this
repo for outstanding gaps (user request: "make sure there is no gaps in
the cobolparser").

* **Updated** [parser.md](parser.md): new "Statement-Support Verification
  Sweep (2026-07-22/23)" section — comma-separated list truncation across
  seven parsers (CALL USING incl. OMITTED, SET, UNSTRING INTO, DISPLAY
  items, computed GO TO, CANCEL, ENTRY USING), UNSTRING `DELIMITED BY ...
  OR ...` + `TALLYING IN`, EXEC CICS command-verb-on-next-line loss + EXEC
  SQL/DLI operator-rejoin spacing, INSPECT BEFORE+AFTER (both qualifiers,
  either order), PIC N(n) sizing, USAGE IS optional-IS handling, START KEY
  OR EQUAL TO trailing TO, WRITE AT END-OF-PAGE/NOT AT END-OF-PAGE, OPEN
  per-file `file_modes`, ADD/SUBTRACT ROUNDED/multi-target/CORRESPONDING +
  DIVIDE REMAINDER, DISPLAY UPON clause-continuation + period handling,
  ENTRY comma, ACCEPT FROM ENVIRONMENT name, STOP period consumption, and
  the EOF-sentinel phantom trailing paragraph (three distinct root causes
  now on record for that one symptom: DISPLAY UPON, STOP, and this EOF fix).
* **Updated** [ast-models.md](ast-models.md): new field notes for
  `ArithmeticStatement.targets`/`.rounded`/`.is_corresponding`,
  `DivideStatement.remainder`, `UnstringStatement.tallying_variable` +
  multi-delimiter `.delimiters`, `IOOpenStatement.file_modes`,
  `IOWriteStatement.not_at_eop_clause`, `IOAcceptStatement.
  environment_name`, and `PIC N(n)` sizing.
* Full suite re-verified green before and independent of this doc pass:
  7067 passed / 13 skipped / 1 xfailed, 92.19% coverage (no source changes
  in this pass — documentation only).
* `reports/open-findings.md` and `CHANGELOG.md` (Unreleased) also updated
  in the same pass.

## 2026-07-21 (generic swallow-sweep regression test added)

* **Added** `tests/regression/test_swallow_sweep.py`: formalizes the manual
  "period-less verb + marker statement" probe used throughout the
  2026-07-05..09 Silent-Drop Audit sections into a permanent, generic sweep
  — one fixture per class in `create_statement_registry()` (46), cross-product
  with a `DISPLAY 'MARKER'.` sentinel, asserting the marker survives as its
  own top-level entry in `CobolParagraph.statements` (not merely somewhere in
  `get_all_statements()`'s tree-wide recursion, which would false-pass a
  marker absorbed into a clause body — see design rationale in the test
  module docstring). A completeness guard fails the suite if a future
  statement parser is registered with no matching fixture. Validated during
  development by disabling `MoveStatementParser`'s boundary check and
  confirming exactly one targeted failure (no collateral damage), then
  reverting. A second validation pass caught a real gap: the initial
  ADD/SUBTRACT/MULTIPLY/DIVIDE fixtures used a plain scalar target, which is
  safe-by-construction (consumed in one shot regardless of any boundary
  check) and stayed green even with `_consume_arithmetic_target` mutated —
  redesigned around a subscripted `GIVING` target so they route through the
  shared `consume_optional_subscript` paren-depth loop instead, confirmed by
  mutating that loop (all four failed together, then reverted).
* **Updated** [parser.md](parser.md): new "Generic swallow-sweep regression"
  section cross-referencing this test from the audit trail it formalizes.
* **Updated** [tests.md](tests.md): added the new file to the `regression/`
  directory-layout annotations.

## 2026-07-21 (procedure_registry.py dispatch-order invariant test)

* **Updated** [parser.md](parser.md): added
  `tests/unit/test_procedure_registry_dispatch_order.py`, closing a gap
  flagged in review — `create_statement_registry()`'s first-match dispatch
  order is order-sensitive by design ("more specific before general") but
  had no automated invariant test, so a misordered future registration
  would have failed silently at runtime instead of at test/review time.
  Investigated every `matches()` implementation in
  `cobolparser/parsers/statements/` to find genuine first-token overlaps;
  confirmed the only real overlap in the current registry is the IBM EXEC
  family (`EXEC SQL`/`EXEC CICS`/`EXEC IMS`/`EXEC DLI` all start with
  `EXEC`, disambiguated on the second token) — every other registered verb
  matches a distinct `TokenType`. The new test file: (1) pins
  `create_statement_registry()`'s exact parser order in `EXPECTED_ORDER` so
  any accidental reorder/insertion/removal in `procedure_registry.py` fails
  immediately; (2) parametrizes `DISPATCH_CASES` — one real
  `Token`/`TokenStream` case per registered parser (46 total) — asserting
  `find_parser()` returns the correct class against the actual production
  registry, so a future parser with an overly broad `matches()` inserted in
  the wrong slot is caught by a wrong-class assertion instead of a silent
  mis-parse; (3) a guard test asserting `DISPATCH_CASES` covers every class
  the registry actually registers, so the invariant test itself can't
  silently drift out of sync. Verified the order-pin test actually catches
  breakage by temporarily swapping two adjacent registrations in a scratch
  copy — the test failed with a clear index-level diff, then the swap was
  reverted. Updated the "Adding a New Statement Parser" checklist in
  parser.md with a step to update this test. Pinned by
  `tests/unit/test_procedure_registry_dispatch_order.py`.

## 2026-07-21 (copybook REPLACING/`>>IF` ran before sequence-area stripping)

* **Updated** [preprocessing.md](preprocessing.md): user asked to confirm
  that fixed-format sequence-number (columns 1-6) and identification
  (columns 73-80) columns are always ignored "even in the copybooks."
  Confirmed the *default* expansion path already strips them correctly, but
  found a real gap via direct reproduction (not merely theorized —
  `expand_copybooks` run against copybooks with real 6-digit sequence
  numbers and column-72-flush REPLACING targets): `_expand_source_recursive`
  ran `apply_replacing_clauses`, `preprocess_conditional_compilation`,
  `validate_copybook_content`, and `validate_level_numbers` on the raw
  80-column copybook line, stripping sequence/identification columns only
  *afterward*. A length-changing `REPLACING` therefore shifted the
  column-72 boundary relative to the original line: a shrinking replacement
  (`==LONGPLACEHOLDERTAG==` by `==X==`) pulled the identification-area text
  into the kept window and inserted it into the parsed program; a growing
  replacement (`==SHORTTAG==` by a longer value) truncated real code,
  dropping the replaced text's terminating period. Separately, `>>IF`/
  `>>END-IF` inside a copybook using real (non-blank) sequence numbers were
  never recognized as directives (the check saw the sequence-number digits
  before `>>`), so conditional blocks never evaluated.
  Fix: `_expand_source_recursive`'s copybook-content branch now strips
  sequence/identification columns and blanks comment lines immediately
  after reading the file — before REPLACING, conditional compilation, or
  either validator sees it. `apply_replacing_clauses` gained an
  `indicator_position: int = 6` parameter (mirroring
  `normalize_continuation_lines`) so it locates the indicator column
  correctly on both raw (index 6) and pre-stripped (index 0) content, and
  `_expand_source_recursive` gained `already_stripped: bool = False` so its
  own internal strip is skipped when the caller already normalized the
  content (skipping it unconditionally would double-strip and eat 6 more
  real characters off every line). One pre-existing unit test
  (`test_copybook_expander_coverage.py::test_content_validation`) used a
  synthetic single-line copybook (`"* Just a comment"`, comment marker at
  column 1, not column 7) that only worked by coincidence against the old
  naive `.strip().startswith("*")` check; corrected the fixture to use a
  real fixed-format comment line (6-space sequence area + column-7 `*`).
  Pinned by
  `tests/regression/test_copybook_sequence_area_before_replacing.py`. Full
  suite green (6818 passed / 13 skipped / 1 xfailed).

## 2026-07-21 (PICTURE clause with no terminating period drops the next data item)

* **Updated** [parser.md](parser.md): `parse_picture_clause`
  (`parsers/divisions/data_clauses.py`) unconditionally treated a NEWLINE as
  "more picture pattern may follow" (needed for legitimate multi-line
  PICTURE clauses). When a clause's terminating period was missing, the loop
  crossed the newline and picked up the *next* data item's own
  `level-number data-name` pair as more pattern content — the lexer types
  every 1-2 digit integer as `LEVEL_NUMBER` regardless of context, and
  `LEVEL_NUMBER` is one of the token types the picture-pattern loop collects.
  The next item (and all its children) vanished from the AST with
  `result.success == True` and `result.warnings == []`.
  Root cause confirmed via a minimal repro (`cobolparser.parse_cobol` on a
  `REDEFINES ... PIC 9(08)` entry whose terminating period lands at column
  73): `normalize_fixed_format` extracts only columns 8-72, silently
  truncating the period. Empirically verified against real GnuCOBOL 3.2 (via
  mockymock's `mockymock-cobc` Docker container, plain fixed-format `cobc`,
  no `-free`) that the same source **fails to compile** there too
  (`group item 'Variable-name' cannot have PICTURE clause` / `syntax error,
  unexpected Literal`) — GnuCOBOL applies the same column-72 truncation
  (cobolparser's semantics already match) but never silently accepts the
  result the way cobolparser did. The bug is not fixed-format-specific: a
  plain missing period in free-form source hits the identical defect.
  Fix: `parse_picture_clause`'s NEWLINE branch now looks ahead past the
  newline for a LEVEL_NUMBER that cannot legally be more PICTURE content —
  either its value contains a digit other than `0`/`9` (the only two
  digit-shaped PICTURE symbols), or it's immediately followed by an
  `IDENTIFIER` (never legal inside a PICTURE pattern — occurrence counts
  are always parenthesized, e.g. `9(05)`) — and stops the clause there
  instead of consuming the newline, recording a `ParseResult.warnings`
  entry — consistent with the "dropped-content signal" contract mockymock's
  `check_whole_program` PARSE_WARNING refusal gate already depends on
  (`mocky-mock/.okf/integration.md` Gotchas). The Cython `_data_fast` fast
  path delegates PICTURE parsing back to this same method, so both paths are
  fixed together with no `.pyx`/`.c` change needed. Pinned by five new
  tests written first and confirmed failing against the old behavior:
  `tests/regression/test_picture_clause_missing_terminator.py`
  (`TestFixedFormatColumnTruncation` — the literal repro — and
  `TestFreeFormMissingPeriod` — the same defect with no column truncation
  involved). Full suite green (6813 passed / 13 skipped / 1 xfailed).
  **Follow-up (same day, advisor review):** the initial fix keyed only on
  "LEVEL_NUMBER followed by IDENTIFIER", missing an *anonymous* next item
  with no data-name at all (`05  REDEFINES ...` — no IDENTIFIER token
  follows the level number), which still silently corrupted the previous
  item's pattern and misattached the anonymous item's children to it. Added
  the digit-content signal above (any digit other than `0`/`9` can never be
  legal PICTURE content, so the token is unconditionally a real level
  number) to close that gap without reintroducing a false positive on the
  legitimate `PIC 9\n99.`-style multi-line continuation (every character of
  an all-`0`/`9` LEVEL_NUMBER stays ambiguous, so the IDENTIFIER check still
  gates that case). Also strengthened the original tests to assert
  parent/child re-attachment explicitly (not just node presence — the
  original bug's defining symptom was children reattaching to the *wrong*
  parent) and added `TestAnonymousNextItem`. Full suite green (6815 passed
  / 13 skipped / 1 xfailed).

## 2026-07-21 (SUBTRACT ... FROM and GIVING subscripted targets dropped)

* **Updated** [parser.md](parser.md): two sibling gaps in the same bug class
  as the ADD ... TO fix above, both in
  `parsers/statements/arithmetic_parsers.py` /
  `parsers/statements/_utils.py`:
  1. `SubtractStatementParser`'s `FROM` branch consumed an identifier
     target with a bare `stmt.set_target(tok.value); token_stream.consume()`
     instead of `_consume_arithmetic_target`, so `SUBTRACT 1 FROM
     VARIABLE (H, I, 1)` captured only `VARIABLE` and left `( H , I , 1 )`
     unconsumed as an "Unparsed tokens" content-drop warning. Fixed by
     routing the `IDENTIFIER` case through `_consume_arithmetic_target`
     (numeric-literal/level-number/figurative-constant targets, which can
     never carry a subscript, keep the original bare-consume branch).
  2. `_utils.consume_keyword_and_operand` — shared by every arithmetic
     statement's `GIVING` clause (ADD, SUBTRACT, MULTIPLY, DIVIDE) — only
     accepted a single bare `IDENTIFIER` token, so `ADD 1 TO A GIVING
     RESULT (H, I, 1)` dropped `(H, I, 1)` from the `GIVING` target too.
     Fixed by extracting the paren-depth-tracking subscript loop
     `_consume_arithmetic_target` already had into a new shared
     `consume_optional_subscript` helper in `_utils.py`, used by both
     `consume_keyword_and_operand` and (now refactored to call it)
     `_consume_arithmetic_target` itself.
  Pinned by three new tests written first and confirmed failing (dropped
  subscript, non-empty `warnings`/wrong return value) against the old
  behavior: `tests/unit/test_arithmetic_migration.py::test_subtract_statement_with_subscripted_target`,
  `::test_add_statement_with_subscripted_giving_target`, and
  `tests/unit/test_utils_clause_collection.py::TestConsumeKeywordAndOperand::test_consumes_subscripted_target`.
  Full unit (4625 passed / 4 skipped / 1 xfailed) and regression+integration
  (1870 passed / 4 skipped) suites all still green; `ruff`/`black`/`mypy`
  clean on the touched files.

## 2026-07-21 (ADD ... TO subscripted target dropped)

* **Updated** [parser.md](parser.md): `AddStatementParser`'s `TO` branch
  (`parsers/statements/arithmetic_parsers.py`) consumed its target via a
  private `_consume_identifier` helper that accepted only a bare
  `IDENTIFIER` token — unlike `COMPUTE`'s `_consume_arithmetic_target`
  (already shared), which folds a trailing `(subscript[, subscript]...)`
  group into the target string. `ADD 1 TO TABLE-ITEM (I, J, K)` therefore
  captured only `TABLE-ITEM` as the target and left `( I , J , K )`
  unconsumed as an "Unparsed tokens" content-drop warning; in a
  two-statement paragraph the recovery was bad enough to drop a
  *following* subscripted `ADD` statement from the AST entirely. Fixed by
  switching `AddStatementParser` to call the same `_consume_arithmetic_target`
  helper COMPUTE uses instead of its own bare-identifier method (removed);
  `AddStatement.target` now produces the same `"NAME ( SUB1 , SUB2 )"`
  shape COMPUTE already does for subscripted targets. Pinned by two new
  tests in `tests/unit/test_arithmetic_migration.py`
  (`test_add_statement_with_subscripted_target`,
  `test_add_statement_with_subscripted_target_and_giving`), written first
  and confirmed failing (dropped/truncated statement, non-empty
  `warnings`) against the old behavior before the fix. Full unit
  (4620 passed / 4 skipped / 1 xfailed), regression, and integration
  suites (1870 passed) all still green; `ruff`/`mypy` clean on the
  touched files.

## 2026-07-20 (WRITE ADVANCING mnemonic-name / SPECIAL-NAMES mnemonic clauses)

* **WRITE `ADVANCING` now accepts a mnemonic-name or identifier target**
  (`parsers/statements/write_parser.py`): `BEFORE|AFTER [ADVANCING]
  {integer-1 | identifier-1 | mnemonic-name-1}` previously only handled
  `integer-1` — an `IDENTIFIER` token (a line-count data-name, or a
  SPECIAL-NAMES mnemonic-name like a printer channel) was left
  unconsumed, and the leftover token was then mis-parsed by the procedure
  division scanner as a bogus paragraph header (`WRITE rec AFTER
  ADVANCING TOP-OF-PAGE.` produced an empty `advancing_clause` plus a
  phantom `TOP-OF-PAGE` paragraph). A trailing `LINE`/`LINES` after the
  identifier distinguishes `identifier-1` (`unit="LINES"`) from
  `mnemonic-name-1` (`unit="MNEMONIC"`, no suffix). `PAGE` still hits the
  existing CHANNEL path.
* **SPECIAL-NAMES mnemonic-name clauses are now captured**
  (`parsers/divisions/environment_sections.py`): `implementor-name IS
  mnemonic-name [ON STATUS IS cond] [OFF STATUS IS cond]` (e.g. `C01 IS
  TOP-OF-PAGE`, `CONSOLE IS CRT`, UPSI switch forms) previously fell into
  the SPECIAL-NAMES paragraph's generic unknown-clause fallback and was
  discarded with no trace. Detected via one-token lookahead (`name IS
  ...`) and collected into `special_names["mnemonic_definitions"]`.
  Pinned by `tests/unit/test_special_names.py` and
  `tests/unit/test_write_advancing.py`. Updated `parser.md`,
  `ast-models.md`, and `CHANGELOG.md` (Unreleased).

## 2026-07-20 (PERFORM THRU gaps: numeric procedure names + range reachability)

* **All-digit procedure names** (`PERFORM 1000 THRU 1999` numbering):
  `procedure_boundaries.py` recognizes numeric paragraph headers
  (`_is_procedure_name_token`), and `perform_parser.py` no longer consumes
  a numeric token as a speculative TIMES count — TIMES is checked by
  lookahead first, and all-digit tokens are accepted as the PERFORM target
  and the THRU end. Updated `parser.md`.
* **THRU range members reachable**: `program_flow/graph.py`
  `find_unreachable_nodes` treats every `FlowEdge.range_members` entry as a
  neighbor of the edge source, ending false `unreachable_nodes` for range
  intermediates whose fall-through edge was suppressed. Updated
  `analysis.md`.
* Pinned by `tests/unit/test_perform_thru_numeric.py` and
  `tests/unit/analysis/test_program_flow_thru_reachability.py`.

## 2026-07-20 (multi-line REDEFINES clause fix)

A `REDEFINES` keyword separated from its target data-name by a line break
lost the target (NEWLINE token between keyword and identifier). Fixed in
both the pure-Python clause loop (`data_clauses.py`, via `_skip_newlines`)
and the Cython fast path (`_data_fast.pyx`, inline newline-skip loop;
`_data_fast.c` regenerated with Cython 3.2.4). New multi-line REDEFINES
cases in `tests/unit/test_data_division_branches.py::TestRedefinesClause`,
including a forced pure-Python-loop variant. Updated `parser.md`
(multi-line clause gotcha) and `CHANGELOG.md` (Unreleased → Bug Fixes).

## 2026-07-20 (WRITE BEFORE/AFTER without ADVANCING keyword)

* **`WRITE ... AFTER 1` (no `ADVANCING`) no longer drops the clause**
  (`parsers/statements/write_parser.py`): the `ADVANCING` keyword is
  optional in the standard `BEFORE|AFTER [ADVANCING] [n] [LINES|LINE|PAGE]`
  phrase, but the parser required it — `AFTER 1`, `AFTER 1 LINE`, and
  `BEFORE PAGE` consumed the `BEFORE`/`AFTER` token and then recorded
  nothing, with a trailing `LINE`/`LINES` surfacing as an "Unparsed
  tokens" content-drop warning. The count/unit parsing now runs whether
  or not `ADVANCING` is present. Pinned by
  `tests/unit/test_write_advancing.py`. Updated `parser.md` and
  `CHANGELOG.md` (Unreleased).

## 2026-07-20 (open-findings M6/M10/M11/M12/M13/M15 batch fix)

The six MEDIUM findings previously deferred as subsystem rewrites are
fixed, each pinned by its own
`tests/regression/test_open_findings_m<N>_regression.py`:

* **M13** — `apply_replacing_clauses` is a context-aware line scanner
  (comment lines and string literals protected); `:ABC:` pseudo-text
  delimiters stripped by `CopyStatementLexer._read_operand` so colon
  operands substitute. Updated `preprocessing.md`.
* **M10** — `preprocess_conditional_compilation` evaluates real `>>IF`
  conditions (comparisons, `AND`/`OR`/`NOT`, `DEFINED`) against valued
  symbols (`dict` accepted; pre-existing CLI `--define NAME=VALUE` values
  now take effect), and implements
  `>>EVALUATE`/`>>WHEN`/`>>WHEN OTHER`/`>>END-EVALUATE`. Obsolete pins
  in `test_tier4_audit_remediations.py` updated. Updated
  `preprocessing.md`.
* **M11** — `ExecCicsStatement.options` dict, `ExecImsStatement` DLI
  function + positional args, tokenizer-based `parse_exec_sql`
  (`select_columns`, `where_present`, `:VAR:IND`). Additive only.
  Updated `parser.md`.
* **M12** — `ComputeStatement.expression_tree` (precedence-parsed) and
  `CobolExpression.condition_tree` for PERFORM UNTIL / IF-fallback
  conditions, via new shared `parsers/statements/_conditions.py`. Raw
  strings and dict output for pre-existing shapes unchanged. Updated
  `parser.md`, `ast-models.md`.
* **M15** — `detect_encoding` plausibility scoring over a 64 KiB prefix;
  `encoding_errors` (`"replace"`/`"strict"`) on `CopybookSearchPath` /
  `expand_copybooks`. Updated `preprocessing.md`.
* **M6** — `tokenize_cobol()`/CLI `tokenize` unified onto
  `normalize_fixed_format` + free-form lexing with COMMENT tokens
  re-emitted at original line numbers (`_tokenize_source`). No Cython
  mirror touched. Updated `lexer.md`.

`reports/open-findings.md` and `CHANGELOG.md` (Unreleased) updated in the
same batch. Remaining open: M17 (coverage debt) and LOW findings.

## 2026-07-17 (VALUE ALL literal clause support)

* **`VALUE ALL <literal>` parsed instead of dropped**
  (`divisions/data_clauses.py`, `parse_value_clause`): `ALL` lexes as a
  `FIGURATIVE_CONSTANT`, so the previous literal branch consumed it as a
  complete value and the repeated literal (`'='`) fell through to the
  unknown-clause loop as an "Unparsed token" content-drop warning —
  which made mockymock refuse the program (PARSE_WARNING, fail-closed).
  Surfaced by the legacy-application corpus re-sweep on `EODPROC.cbl`'s
  report-separator idiom `05 FILLER PIC X(133) VALUE ALL '='.`. New
  handling: `ALL` + string literal → `value_clause='ALL "="'`; `ALL` +
  figurative constant → `'ALL ZEROS'`; bare `ALL` keeps the old
  figurative-constant result. The literal may sit on a continuation line
  (newlines skipped after `ALL`, same as after `VALUE`/`IS`). The Cython
  `_data_fast` path is unaffected — it delegates VALUE parsing back to
  this Python method. Regression suite:
  `tests/regression/test_value_all_clause.py` (6 tests, includes a
  no-warnings assertion). Updated `parser.md` (VALUE ALL note) and
  `CHANGELOG.md` (Unreleased).

## 2026-07-15 (PR #89 review fixes: Area A comment-entry termination, COPY warning wording, REPLACE scanner rewind)

Three small fixes out of the PR #89 self-review:

* **Comment-entry termination completed** (`divisions/identification.py`):
  per COBOL-74, *any* entry starting in Area A ends a comment-entry — not
  just recognized clause keywords. The clause-value loop now stops at a
  line-starting Area A token (tracked via each consumed token's line, so
  same-line values after `AUTHOR.` are unaffected), and the main loop's
  unknown-clause recovery closes `in_comment_entry` on an Area A token.
  Two new tests in `tests/regression/test_comment_entry_area_b.py`
  (unknown Area A word closes the entry; an Area B `AUTHOR` keyword does
  not open one).
* **Un-expanded COPY warning is path-neutral**
  (`preprocess/replace_statement.py`): now `COPY <member> was not
  expanded; ...` — the old "(no copybook path configured)" was wrong when
  expansion ran but couldn't resolve the member. mocky-mock's adapter
  matches on `COPY ` + `not expanded`, unaffected.
* **REPLACE scanner rewind** (`preprocess/replace_statement.py`): a failed
  `_parse_replace_at` now rewinds to just past the matched keyword
  (captured after `_match_word`), not `keyword_start + 7`, which could
  land mid-word when separators preceded the keyword.

Full suite: 6797 passed / 18 skipped / 1 xfailed; ruff/black/mypy clean.

## 2026-07-14 (Area B–aware comment-entry termination; NIST KNOWN_ISSUES emptied)

Made the IDENTIFICATION DIVISION parser's boundary checks comment-entry
aware (`parsers/divisions/identification.py`,
`_at_comment_entry_aware_boundary`): COBOL-74 comment-entries end only at
the next **Area A** entry, and `normalize_fixed_format` preserves Area A/B
as leading indentation. The parser now tracks an `in_comment_entry` state —
opened when an AUTHOR/INSTALLATION/DATE-WRITTEN/DATE-COMPILED/REMARKS/
SECURITY entry itself starts in Area A (at or left of the division's own
header column, stashed by `BaseDivisionParser.parse` as
`_division_header_column`), closed by PROGRAM-ID or an Area A division
header — and **only while that state is active** does an Area B
division-header-shaped sequence count as comment text instead of a
boundary. Fixes NIST `OBNC1M`, whose SECURITY comment-entry embeds an
entire phony program in Area B — previously the phony `ENVIRONMENT
DIVISION.` ended the division early and the phony `IDENTIFICATION
DIVISION.` spawned a bogus program unit failing "PROGRAM-ID is mandatory".
The state-gating matters: suppressing on column geometry alone broke 31
tests whose loosely indented sources put every real division deeper than
the IDENTIFICATION header — outside a comment-entry the column is
deliberately ignored and those keep terminating the division exactly as
before. Pinned by `tests/regression/test_comment_entry_area_b.py`.

Also moved `SM101A` from `KNOWN_ISSUES` to a new
`REQUIRES_COPYBOOK_EXPANSION` set in
`tests/integration/test_nist_cobol85_support.py`: its COPY members are
statement fragments by design, so the strict parametrized test now parses it
through the copybook-expansion pipeline (as a compiler must) and requires
zero errors — a stronger guarantee than the previous strict-xfail.

**`KNOWN_ISSUES` is now empty: all 459 NIST COBOL-85 programs parse
error-free** (517 passed / 0 xfailed in the NIST support suite).

## 2026-07-14 (REPLACE statement + un-expanded COPY pseudo-text substitution)

Implemented COBOL source-text pseudo-text substitution as a preprocessing pass
run before lexing, in a new module `cobolparser/preprocess/replace_statement.py`,
wired into `CobolParser._parse_core` just before `CobolLexer`. Two NIST
COBOL-85 programs (`SM206A`, `SM208A`) now parse error-free and were removed
from `KNOWN_ISSUES` in `tests/integration/test_nist_cobol85_support.py`.

* **`apply_replace_statements`** — the `REPLACE ==a== BY ==b== [ ... ] .`
  compiler-directing statement (one or more operand pairs) with `REPLACE OFF.`
  cancelling the active set. Matching is on a COBOL **text-word** stream via a
  new `_tokenize_text_words`: space/comma/semicolon separators are equivalent
  (not text words), a separator period IS its own text word (so `MOVE WS-A TO
  WS-B.` matches a find of `MOVE WS-A TO WS-B` and keeps the sentence period),
  literals are single words compared case-sensitively, other words compare
  case-insensitively. A single left-to-right scan per segment applies the
  active pairs (first match wins); the REPLACE statements themselves are
  blanked. Fixes `SM208A` (30x `REPLACE`; `MOVE "*" AO ...`, `==MOVE "FAIL"
  TO==`, giant 160-quote literals, multi-line pseudo-text, `,`/`;` separators,
  empty `====` deletion).
* **`strip_unexpanded_copy_statements`** — blanks `COPY` statements the
  standalone (`parse_cobol`) pipeline will not expand, reusing the existing
  pseudo-text-aware `CopyStatementLexer` (single COPY parser, not a divergent
  one). This removes the whole statement — including a `REPLACING
  ==pseudo-text==` operand that legally contains statement keywords/periods —
  so nothing leaks into the token stream. Fixes `SM206A`, whose `COPY KP004
  REPLACING ... BY MOVE ==DELETE== ...` leaked a bare `MOVE` as a MOVE with no
  TO. In the copybook-expansion pipeline COPY is already inlined before this
  point, so the strip is a no-op there (verified: `SM206A` still parses clean
  with expansion, `SM101A`/`SM207A` expansion tests unaffected).

Both passes preserve their input's physical line count (every newline in a
removed/replaced span is re-emitted) so downstream error line numbers stay
aligned. Both are cheap no-ops when the source contains no `REPLACE`/`COPY`
keyword. Full suite stays green (6791 passed / 18 skipped / 3 xfailed; +24 new
tests, and `SM206A`/`SM208A` flipped from strict-xfail to pass). Pinned by
`tests/regression/test_replace_and_copy_pseudo_text.py`.

## 2026-07-14 (H9 refinement: clause-continuation keywords + SQL special registers)

Refined `looks_like_paragraph_boundary()` (`parsers/statements/_utils.py`) so
the H9 missing-period recovery no longer misclassifies two real-world shapes
surfaced by the mockymock legacy-application corpus sweep:

* Added `CLAUSE_CONTINUATION_KEYWORDS` (`DELIMITED`, `TALLYING`, `POINTER`,
  `GIVING`, `ROUNDED`, ...) and `SQL_SPECIAL_REGISTERS` (`SQLCODE`,
  `SQLSTATE`) frozensets, excluded alongside `STATEMENT_KEYWORDS`. These are
  reserved words / precompiler-provided registers that lex as plain
  `IDENTIFIER` but can never legally be a paragraph name, so a multi-source
  `STRING` with each `DELIMITED BY SIZE` clause on its own continuation line,
  or a period-less `DISPLAY` before a bare `SQLCODE`, no longer truncates the
  AST.
* The "next token must be a period or `SECTION`" lookahead is **kept**.
  Dropping it (as the abandoned PR #87 branch did) looked attractive for
  catching unknown-verb shapes, but is a proven real-world regression: a
  continuation-line operand named by an *unexpanded* COPY member is not in
  `known_data_names`, so without the shape check it is misread as a
  boundary and the statement truncated — mocky-mock's copybook fixtures
  (`COMPUTE X =` / newline / `ORD-AMOUNT ...` with `COPY ORDREC.`
  unresolved) caught exactly this.

Pinned by `tests/regression/test_clause_continuation_boundary.py`.

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

## 2026-07-09 (CobolCheck test generation removed — superseded by mockymock)

Removed the CobolCheck test-generation feature end to end: the
`cobol-parser generate-tests` CLI subcommand, the `generate_cobolcheck_tests()`
Python API, and the `CoverageAnalyzer` / `TestPlanGenerator` /
`CobolCheckGenerator` classes (`cobolparser/analysis/coverage_analyzer.py`,
`cobolparser/analysis/test_plan.py`, `cobolparser/generators/cobolcheck.py`,
all deleted), plus their ~180 dedicated tests across 6 test files. Confirmed
via `interface-contract.md` that the backend adapter never called into this
feature, so no cross-repo consumer was affected. The vendored copy in
`backend/_vendor/cobol-parser/` was re-synced afterward. Full suite still
passes (6,638 passed / 13 skipped / 5 xfailed) at 92.44% coverage, above the
81% floor.

* **Updated** [cli.md](cli.md): removed the "Generate-Tests" subcommand
  section and the CobolCheck mention in Output Identification.
* **Updated** [analysis.md](analysis.md): removed the "CoverageAnalyzer +
  TestPlanGenerator + CobolCheckGenerator" section, its Public API imports,
  and its two Module File Map rows; module count 15 → 13.
* **Updated** [tests.md](tests.md): refreshed pass count and the
  `generators/` directory description (flowchart tests only now).

## 2026-07-09 (ENVIRONMENT/DATA division sections stamped with the wrong line — user-reported)

A user testing the parser noticed that `ENVIRONMENT DIVISION`'s
`CobolDivision` node and its `INPUT-OUTPUT SECTION` `CobolSection` reported
the exact same `line`/`column` in the AST's `to_dict()` output. Confirmed as
a real, consistent bug (not specific to that one division): every
`CobolSection`/`CobolParagraph` built by `environment.py`'s and `data.py`'s
`_create_ast_node()` reused the division's own `start_location` instead of
its own header token's location — `procedure.py` already tracked per-section
locations correctly, so only these two division parsers needed the fix.
Both now capture each section's (and the FILE-CONTROL paragraph's) own
keyword-token location during parsing and thread it through to
`_create_ast_node`. Pinned by new file
`tests/regression/test_section_location_tracking.py` (TDD: written first,
confirmed failing against the old behavior, then fixed).

* **Updated** [parser.md](parser.md): new "Section/Paragraph Location
  Tracking" section describing the root cause and fix.

## 2026-07-09 (H10 fixed: out-of-line `PERFORM ... VARYING ...` dropped, `perform_type` mistagged)

A user reported, and personally verified before reporting, that the
out-of-line form of `PERFORM procedure-name VARYING ...` was not parsed
at all: the clause was silently dropped and `PerformStatement.perform_type`
stayed the default `"SIMPLE"`, indistinguishable from a genuine plain
`PERFORM`. The user's own diagnosis was precise: what actually prevented
this from being a live problem today was an unrelated mechanism — the
generic dropped-clause parse warning tripping an unrelated downstream
refusal gate (in a consuming service, outside this repo) before any
terminator logic there ran — a real but accidental safety net that would
go silent again if the out-of-line VARYING shape were ever parsed without
also fixing the tagging.

Filed as H10 in `reports/open-findings.md` (a new finding, not from this
document's own prior audit passes) and fixed same-day. Root cause:
`perform_type` only became `"VARYING"` as a side effect of
`set_varying_clause()`, which requires a fully-parsed `until_condition` —
confirmed to be a strictly worse, fully silent instance of the *same* bug
already present on the *inline* PERFORM VARYING form (no accidental
warning to mask it there). Fixed via a new `PerformStatement.
mark_varying()`, called the instant the `VARYING` keyword is consumed,
before `FROM`/`BY`/`UNTIL` are attempted — plus a missing out-of-line
`VARYING` dispatch in `perform_parser.py`, and an explicit warning on any
VARYING clause that doesn't fully parse. Pinned by
`TestPerformVaryingOutOfLine` in `tests/regression/test_perform_backward_compat.py`
and a strengthened assertion in `TestPerformVaryingMissingUntil`
(`tests/unit/test_perform_edge_cases.py`) for the inline-form case.

* **Updated** [parser.md](parser.md): H10 added to the "open-findings.md
  HIGH-severity fixes" section (now "H1-H10"), full write-up alongside the
  existing H1-H9 entries.

## 2026-07-09 (open-findings.md MEDIUM-severity remediation: M1, M2, M3, M4, M5, M7, M8, M9, M14, M16 fixed)

Follow-up to the same-day H1-H9 pass above: implemented fixes for 10 of
the 17 MEDIUM findings in `reports/open-findings.md`, chosen (per user
decision) as the ones contained enough to fix with real TDD in one pass;
M6, M10, M11, M12, M13, M15 (each close to its own subsystem rewrite)
deferred to separate plans, and M17 (branch-coverage debt, not a bug) not
attempted. Each pinned by a dedicated test class in new file
`tests/regression/test_open_findings_medium_regressions.py` (30 tests
total, including a Cython/pure-Python parity check). Full per-finding
writeup: `CHANGELOG.md` (Unreleased → Fixed). `reports/open-findings.md`
updated in place — all 10 marked `FIXED 2026-07-09` (left visible for
traceability, per the file's own convention), M3 and M7 marked partial
with residual write-ups appended in place.

M3 (screen positioning / extended ACCEPT clauses) was scoped by grepping
`examples/cobol/shamrice/*.cbl` — the corpus the finding's original hit
counts came from — rather than guessing IBM grammar the finding text
didn't fully specify: `AT` positioning turned out to be 100%
combined-numeric (`AT 0330`) in real usage with zero `AT LINE n COLUMN m`
hits, and `SECURE`/`NO-ECHO` turned out to be semantically distinct
(`SECURE` masks with `*`, `NO-ECHO` shows nothing) per the corpus file's
own comment — both facts the finding text alone didn't establish.

* **Updated** [parser.md](parser.md): new "open-findings.md
  MEDIUM-severity fixes (2026-07-09)" section (mirrors the H1-H9 section
  above it), covering M1 (`DISPLAY` figurative constants —
  `TokenType.FIGURATIVE_CONSTANT` missing from the display-item accepted
  set), M2 (`DISPLAY WITH NO ADVANCING` — `WITH`/`NO`/`ADVANCING` lex as
  dedicated `TokenType`s the item loop didn't handle;
  `DisplayStatement.with_no_advancing` added), M3 (`AT` positioning on
  `DISPLAY`/`ACCEPT` plus `ACCEPT`'s `SECURE`/`NO-ECHO`/`TIMEOUT`/
  `AUTO-SKIP`/`UPPER` — corpus-scoped as above; `IOAcceptStatement`
  gained `secure`/`timeout_value`/`auto_skip`/`upper`, its pre-existing
  `at_line`/`at_column`/`with_no_echo` scaffolding finally wired up), M9
  (`try_parse_nested_statement`'s bare `except Exception` now surfaces a
  warning unless the exception is already `_already_recorded` by
  `report_or_raise` — distinct call site from H4's 5 bare excepts in
  `perform_parser.py`), and M16 (`_PICTURE_SYMBOL_TOKEN_TYPES` used
  `TokenType.DIVIDE`/`MULTIPLY`, the *statement keyword* tokens, instead
  of `TokenType.DIVIDE_OP`/`MULTIPLY_OP`, so `/`- and `*`-edited pictures
  like `PIC 99/99/99` truncated at the first edit symbol and the
  remainder was misparsed as phantom level-99 data items).
* **Updated** [lexer.md](lexer.md): "Warnings" section gained a second
  producer — `read_prefixed_literal_from_text` now validates hex content
  for `X'..'`/`NX'..'` typed literals (odd digit count or non-hex
  characters both now warn; `G'..'`/`N'..'` untouched) — finding M7,
  fixed partially (validation only, not decoding).
* **Updated** [preprocessing.md](preprocessing.md): `normalize_fixed_format`
  gained a `debug_lines_as_comments` keyword (default `True` — `D`/`d` in
  column 7 now treated as a comment, matching
  `copy_statement_parser.is_comment_line()`, closing the M4 two-pipelines-
  disagree gap) and tab-expands each line (`str.expandtabs(8)`) before
  any column-sensitive slicing (M8). Trailing blanks on a line are now
  preserved when a literal remains open at end of line, only stripped
  once confirmed closed (M5) — both the opening-line and
  literal-continuation branches, pure-Python and Cython. Copybook
  Expansion section gained a note on M14: cache hits in
  `_expand_source_recursive` now count toward `context.total_bytes` the
  same as a miss does (previously only misses did, so diamond-dependency
  copybooks under-counted against `max_total_size`).
* **Updated** [tests.md](tests.md): test count refreshed to 6,789 passed
  / 13 skipped / 5 xfailed, 92.65% coverage.
* Cython extension rebuilt (`python setup.py build_ext --inplace`) for
  the M4/M5/M8 `_preprocess_fast.pyx` changes; regenerated `.c` committed
  alongside. Verified both `_lexer_fast`/`_preprocess_fast` report as
  active post-rebuild (`tests/unit/test_fast_import.py`) and a dedicated
  parity test confirms the Cython and pure-Python paths agree on all
  three new behaviors.
* Full suite (6,789 tests) and `ruff`/`black`/`mypy` all pass after the
  batch; the real `examples/cobol/shamrice/accept.cbl`,
  `accept-secure.cbl`, and `mouse_example.cbl` files (the M3 motivating
  corpus) now parse with zero `AT`/`SECURE`/`NO-ECHO`/`TIMEOUT`/
  `AUTO-SKIP`/`UPPER`-related warnings.

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
