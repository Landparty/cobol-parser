---
type: Reference
title: Tests
description: Test layout, pytest markers, coverage floor (81%), and shared fixtures for the cobolparser test suite.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-08-13T00:00:00Z
---

# Overview

2026-08-13: +5 in `tests/unit/analysis/test_unused_variables.py`'s new
`TestQualifiedAndFunctionOperands` — Copilot PR review on the
`UnusedVariableAnalyzer` PR caught that a qualified name (`WS-A OF
WS-GRP`), an intrinsic function call (`FUNCTION UPPER-CASE(WS-X)`), a
special register (`LENGTH OF WS-X`), and a subscripted reference
(`WS-ENTRY(WS-IDX)`) were each added to the referenced-names set as one
opaque joined string instead of split into their underlying data-names,
so none of the real names ever matched and were falsely reported unused.
See [analysis.md](analysis.md)'s `_extract_identifiers` note.

2026-08-13: New `tests/unit/analysis/test_unused_variables.py` (25 tests) for
the new `UnusedVariableAnalyzer` (see [analysis.md](analysis.md)) — basic
used/unused detection, FILLER/`ANONYMOUS-*` exclusion, group-item
used-if-any-descendant-used, level-88 usage marking its parent used,
IF/PERFORM UNTIL condition operands (exercising the expression-tree walk,
not `.operands`), REDEFINES propagation, OCCURS DEPENDING ON, LINKAGE/FILE
SECTION coverage, `copybook_item_names`/`include_copybook_variables`
filtering, `TestExtrasLookupIsMroAware` (pins that the
`_STR_ATTR_EXTRAS`/`_DICT_LIST_EXTRAS` lookup walks `type(stmt).__mro__`,
not exact type), `to_dict()` serialization, top-level package export, and a
`collect_declared_items()` unit test.

2026-08-13: +23 in new `tests/regression/test_screen_report_communication_sections.py`
— pins the DATA DIVISION parser's new SCREEN/REPORT/COMMUNICATION SECTION
header recognition (previously unrecognized headers let their content
corrupt WORKING-STORAGE), including end-to-end assertions against
`tests/samples/screen_section_io.cbl`, `report_writer.cbl`, and
`communication_module.cbl`, plus a dedicated collision check against
`examples/cobol/shamrice/report_test.cbl`'s `REPORT IS report-name.` FD
clause (`REPORT` as an ordinary clause word, not a section header). See
[parser.md](parser.md).

2026-08-13: `test_statement_text.py` reformatted to match the CI-pinned
`black==26.3.0` (whitespace-only, no test logic change) — pre-existing
drift from a newer local black, discovered while unblocking this PR's CI.

2026-08-13: +13 in `tests/unit/analysis/test_dead_code.py` — 3 in new
`TestSectionPropagationDoesNotResurrectSiblings` pinning the
`_propagate_section_references` sibling-resurrection fix, plus 10 in new
`TestDefensiveEdgeCases` closing every remaining coverage gap in
`dead_code.py` (95.77% → 100% line + 100% branch): inline PERFORM with no
target, MERGE without an output procedure / without THRU, a THRU range
with a falsy start, a blank SECTION name, invalid `"."` paragraph names
inside a section, a duplicate top-level paragraph name, an orphan ENTRY
statement, and a malformed ALTER target. See [analysis.md](analysis.md).

2026-08-12: Test-infrastructure audit — `contract`/`integration`/`io`
markers are now applied structurally by per-directory `conftest.py`
collection hooks (see "Per-directory marker enforcement" below); the 12
"Implementation pending - Phase 6/7" placeholder skips in the copybook
expansion unit/integration/contract files were replaced with real tests
(the phases shipped long ago); and the assert-free/tautological tests in
`test_comprehensive_real_world.py`, `test_parser_capabilities.py`, and
`test_basic_real_world_parsing.py` now assert `result.success` and AST
content. See [log.md](log.md).

2026-08-11: +1 in `test_dead_code.py`
(`test_terminator_earlier_in_paragraph_still_cuts_off_fall_through`) and +2
in `test_program_flow.py`
(`test_terminator_earlier_in_paragraph_still_suppresses_fall_through`,
`test_conditional_stop_run_inside_if_does_not_suppress_fall_through`) --
Copilot review on PR #135 caught that the just-added fall-through
termination checks were last-statement-only (missing an earlier top-level
terminator) and that `has_stop_run`/`has_goback`/`has_exit_program` were
nesting-blind (set for a conditional terminator too). See
[analysis.md](analysis.md).

2026-08-11: +11 in `tests/unit/analysis/test_dead_code.py`'s new
`TestFallThroughReferences` class (the fall-through concept added to
`DeadCodeAnalyzer`, audit finding #1) and +3 in
`tests/unit/analysis/test_program_flow.py`'s `TestProgramFlowFallThrough`
(the conditional-GO TO fall-through-suppression fix, audit finding #5,
including a rewrite of `test_fall_through_when_goto_and_perform_both_present`
to assert the corrected behavior). 21 pre-existing tests in
`test_dead_code.py` also needed their fixtures updated: they used
`CONTINUE`/bare `DISPLAY` as filler paragraph bodies with no terminator,
which the new fall-through pass now (correctly) credits as reaching the
next paragraph — added `STOP RUN` where a fixture's paragraph needed to
stay an isolated dead-code island. See [analysis.md](analysis.md).

2026-08-11: +6 across `test_dead_code.py` and `test_program_flow.py` —
three regression tests each pinning the `dead-code-section-550f0e`
paragraphs-before-first-SECTION fix: the mixed-order reordering itself, a
name reused top-level and inside a section (dedup guard on the paragraph
branch), and a name reused as a top-level paragraph then later as a SECTION
header (dedup guard on the SECTION-registration branch, added in a Copilot
review follow-up on the same PR). See [analysis.md](analysis.md).

2026-08-11: +3 in `tests/unit/analysis/test_dead_code.py`'s
`TestEntryReferences` (whitespace-only, empty-after-quote-stripping, and
`None` ENTRY literals) plus 2 more in `tests/unit/analysis/test_program_flow.py`.
A Copilot review on the ENTRY-reachability fix (see [analysis.md](analysis.md)'s
`DeadCodeAnalyzer`/`ProgramFlowAnalyzer` sections) caught that
`dead_code.py`'s new `_collect_entry_refs` didn't apply the same
blank/whitespace-literal filter `program_flow/scanner.py`'s
`collect_entry_points` already did — fixed to match.

2026-08-11: +4 in `tests/unit/analysis/test_program_flow.py` — new
`TestScannerDeepNestingRegression` class, pinning the explicit-work-stack
rewrite of `ProcedureScanner._scan_paragraph_statements`
(`cobolparser/analysis/program_flow/scanner.py`): three tests drive
`ProcedureScanner` directly (bypassing `ProgramFlowAnalyzer.analyze()`,
which hits a separate, unrelated `RecursionError` in `CobolProgram.
get_all_statements()` at these depths) at 2,000-5,000 levels of nested
IF/PERFORM to confirm no `RecursionError`, plus one pinning the EVALUATE
`WHEN`-clause thunk-deferral ordering invariant the rewrite depends on; see
[analysis.md](analysis.md).

2026-08-07: +7 — `tests/regression/test_inline_comment_stripping.py`, pinning
the lexer's new `*>` free-form inline-comment stripping, including a
pure/Cython parity check; see [lexer.md](lexer.md). Also removed the now-stale
`unstring.cbl` entry from `_EXPECTED_UNRESOLVED` in
`test_boundary_inventory_corpus.py` — the phantom `IOStartStatement` that
entry documented no longer occurs. Also 2026-08-07: +5 in
`tests/regression/test_parser_completeness.py` —
`TestExternalGlobalClauses.test_leading_is_does_not_warn` plus the new
`TestSynchronizedJustifiedIsClause` class, covering a data-item clause
dispatch fix: the leading `IS` of `[IS] EXTERNAL`/`[IS] GLOBAL`, and the
missing `IS` before `SYNCHRONIZED`/`JUSTIFIED`'s `LEFT`/`RIGHT` direction,
were dropped as spurious "Unparsed token" warnings even on fully standard
syntax — see [parser.md](parser.md). 2026-08-05: +44 net across two fixes
— `test_dead_keyword_removal.py` (+16: seven dead `lexer.KEYWORDS` entries
that never matched real syntax, see [lexer.md](lexer.md)) and
`test_invoke_allocate_free_statements.py` (+15, plus new
`TestInvokeAllocateFreeNoLongerSwallowed` classes in
`test_tier5_silent_drip_audit.py` and `test_tier7_unsupported_verb_boundary.py`,
and a swapped-in `TRANSFORM` case replacing the now-supported `INVOKE` in
`test_tier3_silent_drop_fixes.py`/`test_tier5_silent_drip_audit.py`: `INVOKE`/
`ALLOCATE`/`FREE` now have registered statement parsers, see
[parser.md](parser.md)). A Copilot review on the same PR (#113) added
required-operand validation to all three parsers (missing object
identifier/method name for INVOKE, missing size-expr/data-item for ALLOCATE,
zero pointer names for FREE all now report a parse error instead of
silently succeeding) plus an operand-recording fix for INVOKE's literal
method names — 5 of the 15 tests above cover these. 2026-08-04: +454 tests across Phases
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

2026-08-12: +17 in `tests/unit/analysis/test_statement_text.py` (new —
`summarize_statement`/`summarize_arm`, real-parse fixtures per statement
type, truncation, never-raises guard) and +20 in
`test_flowchart_generator.py` (`TestMermaidLabelFidelity`/
`TestDotLabelFidelity`/`TestLabelFidelityEndToEnd`: ASCII-only output,
`#lt;`/`#gt;` label escaping, `"`→`'` substitution — `#quot;` renders as
literal `&quot;` on the SVG-text path — arm statement summaries with
`+N more` markers, empty-IF-arm dropping), plus `test_program_flow.py`'s
`test_branch_arm_to_dict_fields` extended for the optional
`BranchArm.summary` key. See [generators.md](generators.md)'s "Label
fidelity" section.

2026-08-11: +2 in `test_flowchart_generator.py`
(`test_loop_label_with_parens_is_quoted`, `test_call_dynamic_edge_label_with_parens_is_quoted`)
plus 6 existing `-->|label|` assertions updated to the now-quoted form —
`MermaidFlowchartGenerator` started wrapping edge labels in quotes so an
unquoted `(`/`[` inside one (a loop annotation, `CALL (dynamic)`, a
`[THRU n]` badge) can't be misread by Mermaid's flowchart lexer as a node
shape token. See [generators.md](generators.md)'s "Flowcharts" section.

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
                               #   test_screen_report_communication_sections.py:
                               #   SCREEN/REPORT/COMMUNICATION SECTION header
                               #   recognition (2026-08-13) -- see parser.md
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

## Per-directory marker enforcement (2026-08-12)

The `contract`, `integration`, and `io` markers are applied **structurally**
by per-directory `conftest.py` files (a `pytest_collection_modifyitems` hook
that adds the marker to every item collected under that directory), so new
test files can never drift out of `-m` selection:

| conftest.py location | Marker applied |
|----------------------|----------------|
| `tests/contracts/` | `contract` |
| `tests/integration/` | `integration` |
| `tests/unit/io_statements/` | `io` |
| `tests/integration/io_statements/` | `io` (plus `integration` from parent) |
| `tests/integration/io/` | `io` (plus `integration` from parent) |
| `tests/contracts/io_statements/` | `io` (plus `contract` from parent) |

In-file `pytestmark = pytest.mark.<x>` lines still exist in many files;
they are harmless duplicates and are no longer required. A file *outside*
these directories can still opt in with an explicit `pytestmark` (e.g. the
`integration` marker is carried by a few files elsewhere).

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
3. **build** — `pip install -e ".[dev,fast]"` + `python setup.py build_ext --inplace` on matrix: Python 3.11, 3.12, 3.13 (install + Cython extension build only, no tests)

The full `pytest tests/ -v` suite (~8,075 tests) is **not** run automatically —
too slow for every push/PR. It's wired as a `test` job gated to
`if: github.event_name == 'workflow_dispatch'`, so it only runs when manually
triggered from the Actions tab. Run the full suite locally during development
(see commands above).

# See Also

* [cli.md](cli.md) — `tests/unit/cli/` covers CLI subcommands
* [generators.md](generators.md) — flowchart, copybook → CSV, program layout
  index, and program fixture bundle generator tests
* [analysis.md](analysis.md) — `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) — `tests/integration/` covers end-to-end parsing
