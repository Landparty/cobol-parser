---
type: Reference
title: Tests
description: Test suite layout (tests/ directories, corpora, conftest fixtures), pytest markers and their per-directory enforcement, the 90% coverage floor and why it is measured on pure Python, the CI jobs in .github/workflows/ci.yml (currently disabled), and the conventions a new test must follow.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-10-16T00:00:00Z
---

# Tests

The suite lives under `tests/` and runs with plain pytest: **~13,970 tests
collected from 483 `test_*.py` files** (`python -m pytest tests --collect-only
-q --no-cov`, 2026-10-16). Configuration is `[tool.pytest.ini_options]` in
`pyproject.toml` (`testpaths = ["tests"]`, `--strict-markers`, coverage on by
default with a **90% floor**, branch coverage enabled). Two shared fixtures
(`parser`, `samples_dir`) come from `tests/conftest.py`; four markers
(`integration`, `slow`, `contract`, `io`), three of them applied structurally
by per-directory `conftest.py` files.

Getting started: `pip install -e ".[dev]"`, then `python -m pytest
tests/unit/test_lexer.py --no-cov` for a single file (`--no-cov`, because a
subset always fails the 90% floor), or `python -m pytest tests/ -n auto` for
the whole suite with coverage (`pytest-xdist` is in `[dev]`). The default
backend is **pure Python**: the Cython accelerators are only built and only
used under `COBOLPARSER_ACCEL=1` (`cobolparser/_accel.py`), so a default run
measures coverage correctly even with `*.so` files present. To exercise the
fast paths, build and run with the variable set and `--no-cov` (see
[Coverage](#coverage-requirement-detail)).

Where to put a new test: `tests/unit/` (one component; analyzers under
`unit/analysis/`, CLI under `unit/cli/`, record encoding/decoding under
`unit/generators/data/`), `tests/regression/` (a pinned bug fix, usually
named for the issue or finding), `tests/integration/` (end-to-end over a
corpus), `tests/contracts/` (public API shapes other repos depend on). Before
writing one, read [Writing tests](#writing-tests): fixed-format fixtures have
a column-72 trap, and several registries are pinned by self-maintaining tests.

## Contents

- [Directory Layout](#directory-layout)
- [pytest Markers](#pytest-markers) (incl. per-directory enforcement)
- [Shared Fixtures](#shared-fixtures-testsconftestpy)
- [Running Tests](#running-tests)
- [Example Corpora](#example-corpora)
- [Enterprise program-type corpus](#enterprise-program-type-corpus)
- [Writing tests](#writing-tests) -- conventions and traps
- [Where behaviour is pinned](#where-behaviour-is-pinned) -- notable test files by area
- [Coverage Requirement Detail](#coverage-requirement-detail)
- [CI/CD](#cicd)
- [OKF guards](#okf-guards)
- [See also](#see-also)

## Directory Layout

File counts are `test_*.py` files, recursive, as of 2026-10-15.

```
tests/
  conftest.py                  # shared fixtures: parser(), samples_dir()
  test_all_samples.py          # smoke-tests every tests/samples/*.cbl program
  test_okf_staleness_map.py    # OKF_MAP guard (see "OKF guards")
  test_okf_claims.py           # OKF content guard: the docs' claims vs the code
  unit/                        # 295 files: individual components (200 directly in unit/)
    test_copybook_data_generator.py  # copybook -> CSV: flattening, categories, value constraints, options, dataset surface, TestFloatValueClauses (#551)
    test_program_layout_index.py     # ProgramLayoutIndex: FD/record resolution, FD-vs-SD tagging, FileFacts, name resolution, qualified level-88 names (resolve/condition_values/gen-fixtures arms, #272), record_named(), multi-program units, from_file errors (see generators.md)
    test_program_fixtures.py         # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON round trip, one directory per scenario, distinct CSVs on a forced name collision); TestScenarioModes (witness pinning incl. compound SEARCH WHEN #348, empty-input, boundary min-max, scenario_coverage); TestTier1CallCountExpectations / TestTier2FieldEqualsExpectations; TestTargetedArmsAreVerified (#244); TestFailurePathExpectations (#318); TestCallCountFollowsControlFlow (#363); TestMultipleRecordsUnderOneFd (#364); TestArmsOnTwoRecordsOfOneFd; TestFillerOwningConditionName; TestCallFixtureSameNamedFields (#365); TestKeyedReadReturnsTheKeyAskedFor (#322); TestFloatFieldArms (#551) (see generators.md)
    test_scenario_planner.py         # ScenarioPlanner: THEN/ELSE targeting, disjoint-field merging, unsatisfiable arms, fixed families (empty-input/error-status/boundary-values), exact coverage accounting, TestScenarioNamesAreUnique (#267) (see generators.md)
    test_extended_verb_parsers.py    # 2026-09-02 statement-coverage audit: every Report Writer / Communication / legacy / COBOL 2002 verb -> node, operands, no warnings; UNSUPPORTED_VERBS == {EXECUTE, GOTO, RECOVER}; every STATEMENT_KEYWORDS verb dispatches (see parser.md)
    test_fast_import.py              # Cython import guard: extensions load when compiled (importorskip otherwise), pure Python is the default even when compiled, swapped in only under COBOLPARSER_ACCEL=1, accelerators_enabled() spellings
    analysis/                  # 48 files: every analyzer
      test_boundary_inventory.py  # BoundaryInventoryAnalyzer: per-category key/layout/direction, nested-body reachability, CALL argument-direction ladder, structure-qualified SQL host variables, ACCEPT filtering, IOLogger cross-check
      test_constraints.py      # ConstraintExtractor: relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan, EVALUATE TRUE + 88s, WHEN OTHER, SEARCH WHEN (#348), PERFORM-UNTIL SequenceConstraint
      test_domains.py          # domains.solve(): numeric/text/enum domains, witness-satisfies-constraint property, Unsatisfiable never returns a value, level-88 pick re-checked against gt/ge/lt/le (#244), TestFloatDomain: COMP-1/COMP-2 signed fractional domain (#551)
      test_dclgen_check.py     # DclgenChecker: column <-> host-variable pairing, every violation kind/severity, both null-indicator syntaxes, what it declines to check, "DCLGEN's own output is always clean" table
      test_const_fold.py       # ConstantFolder: MOVE/arithmetic/COMPUTE folding, GIVING, loop/branch poisoning, DIVIDE poison, PERFORM chaining, GO TO/STOP RUN, observation points; TestStorageAliasing (#245), TestValueAtObservationPoint (#246), TestWalkBudget, TestInspectAndExecWrites (#317), TestReadKeys (#322)
      test_invocation_counts.py  # count_invocations (#363): status-check exemption (success-arm evaluation, #590), unknown-count bodies, EXIT PARAGRAPH, literal TIMES, fall-through + PERFORM, GO TO following
    cli/                       # 26 files: CLI subcommands
      test_decode_cli.py       # decode: CSV/JSON/hex, --view / --list-views, gen-data -> decode round trip, paging, trailing bytes, --strict; dclgen-check subcommand and lint rule
      test_gen_fixtures_cli.py # gen-fixtures: flags, --list-boundaries, --format json|csv-dir, --strict exit codes
    test_flowchart_generator.py      # Mermaid/DOT flowcharts: label fidelity, quoting, escaping (see generators.md)
    generators/                # 14 files (3 here: bug-hunt r11, row witnesses, scenario verification; + data/)
      data/                    # 11 files: compare, decoding, editing, encoding, layout, layout_offsets, program_layout_conditions, storage, values, variable_length, views
        test_views.py          # build_record_views(): running offsets vs real encoded bytes, REDEFINES overlays (every occurrence inside OCCURS, FILLER padding, nested overlays #296), short-name lookup, ODO ambiguity, contiguity property
        test_decoding.py       # RecordDecoder: decode(encode(row)) == row for every storage class and both charsets, ODO under every RecordFormat, RDW framing, overlay switching, sign conventions read but never written, bad bytes reported per field, paging, hex pane
    io_statements/             # 7 files: IO parser unit tests (`io` marker)
  integration/                 # 32 files: end-to-end over corpora (`integration` marker)
    test_shamrice_examples.py  # all examples/cobol/shamrice/*.cbl parse error-free
    test_nist_cobol85_support.py  # all 459 NIST *.CBL parse error-free (strict-xfail KNOWN_ISSUES ratchet, empty); copybook validation
    test_enterprise_program_types.py  # tests/samples/enterprise/ (see below)
    test_copybook_csv_generation.py   # sample + NIST *.CPY: gen-data never crashes; no-layout copybooks raise CopybookLayoutError; every cell fits its field
    test_data_item_layout_corpus.py   # compute_program_data_items() over fixtures and shamrice
    test_program_layout_corpus.py, test_boundary_inventory_corpus.py, test_gen_fixtures_corpus.py,
    test_constraint_extractor_corpus.py, test_scenario_planner_corpus.py, test_const_fold_corpus.py
                               # gen-fixtures phases 1-7 parametrised over shamrice: no raise, no unexpected unresolved, layout-valid values, exact coverage accounting
    io/                        # 1 file: IO coverage reporting integration (`io` too)
    io_statements/             # 2 files: IO statement parsing, VSAM (`io` too)
  contracts/                   # 21 files: API contract tests (`contract` marker)
    test_fixture_bundle_contract.py  # FixtureBundle: exported names, bundle_version, generator signatures, to_dict() key sets, reproducibility, scenario-mode contract (see docs/fixture-bundle-schema.md)
    io_statements/             # 1 file (`io` too)
  regression/                  # 137 files: pinned bug fixes, typically named for the issue/finding, e.g.
                               #   test_swallow_sweep.py: one period-less snippet per registered statement
                               #     parser x a DISPLAY 'MARKER'. sentinel; fails if a new parser is
                               #     registered without a fixture (see parser.md)
                               #   test_statement_coverage_audit_2026_09_02.py: EXEC CICS/DLI in
                               #     get_all_statements(), handler boundaries, NIST no-drop-warning guard
                               #   test_open_findings_high_regressions.py / ..._medium_regressions.py:
                               #     reports/open-findings.md H1-H8 / M-series
                               #   test_nist_edge_case_fixes.py: minimal repros of NIST edge cases
  performance/                 # test_factory_performance.py (`slow`; absolute floors skipped under a tracer)
                               # + bench_cython_vs_pure.py (a script, not collected)
  samples/                     # shared COBOL fixtures: 48 *.cbl at top level
    copybook_programs/         # programs with COPY statements
    copybooks/                 # .CPY files
    enterprise/                # 22 programs, one per IBM Enterprise COBOL program type, + copybooks/
    io/positive/, io/negative/ # valid / invalid IO patterns
    jcl/                       # invupdt.jcl, payproc.jcl
    lineage/                   # WRITER/SUBPGM/READER/MISC .cbl + FEEJOB.jcl (field-lineage chain)
```

## pytest Markers

Declared in `pyproject.toml` (`--strict-markers`, so an undeclared marker is
a collection error):

| Marker | Meaning |
|--------|---------|
| `integration` | Integration tests |
| `slow` | Slow-running tests (only `tests/performance/test_factory_performance.py` today) |
| `contract` | API contract tests |
| `io` | IO statement tests (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK) |

```bash
python -m pytest -m "integration"    # integration tests only
python -m pytest -m "slow"           # slow tests only
python -m pytest -m "contract"       # API contract tests only
python -m pytest -m "io"             # IO statement tests only
```

### Per-directory marker enforcement

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

In-file `pytestmark = pytest.mark.<x>` lines in these directories are
harmless duplicates, not required. A file *outside* these directories can
still opt in explicitly (e.g. `tests/unit/test_ims_segment_analyzer.py`,
`tests/regression/test_nist_edge_case_fixes.py`).

## Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns |
|---------|---------|
| `parser()` | Fresh `CobolParser` instance |
| `samples_dir()` | `Path` to `tests/samples/` |

## Running Tests

```bash
# All tests with coverage (90% min); -n auto (pytest-xdist) is optional
python -m pytest tests/ -v

# Single file / single test (--no-cov: a subset always misses the floor)
python -m pytest tests/unit/test_lexer.py -v --no-cov
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs --no-cov

# By directory (no dedicated marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/contracts/ -v
python -m pytest tests/performance/ -v

# The suite against the Cython accelerators (opt-in; never trust its coverage)
COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace
COBOLPARSER_ACCEL=1 python -m pytest tests/ -q --no-cov
```

Running only a subset of tests with coverage on will trigger a coverage
failure -- that is expected.

## Example Corpora

| Path | Contents |
|------|----------|
| `tests/samples/` | 48 COBOL programs covering all statement types, smoke-tested by `test_all_samples.py` |
| `tests/samples/enterprise/` | 22 programs, one per IBM Enterprise COBOL program type (see next section) |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + 51 .CPY copybooks); **all 459** parse error-free, pinned by `test_nist_cobol85_support.py`. Its strict-xfail `KNOWN_ISSUES` ratchet is empty (a new entry must be a known, tracked failure); SM101A is parsed through copybook expansion (`REQUIRES_COPYBOOK_EXPANSION`) since its COPY members are statement fragments. Minimal repros for NIST edge cases live in `tests/regression/test_nist_edge_case_fixes.py` |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs from shamrice/COBOL-Examples; all parse cleanly under FAIL_FAST; the gen-fixtures corpus tests sweep it |

## Enterprise program-type corpus

`tests/samples/enterprise/` holds one program per IBM Enterprise COBOL
program type (22 programs + `copybooks/`; the matrix with every
distinguishing construct is `docs/enterprise-program-types.md`).
`tests/integration/test_enterprise_program_types.py` (`integration`
marker) asserts, per program: a FAIL_FAST parse with no errors and no
warnings other than the informational "Compilation unit contains N
program units"; a JSON round trip; every analyzer over every unit without
raising and `LintReport.failed_rules == []`; `gen-fixtures --scenarios
all` and `scan` accepting it; and per-type traits (the CICS commands,
DL/I function codes, MQ calls, OO unit tree, declarative sections, flow
edges, 6.x data attributes ... that make the program its kind).
`TestCorpusShape` fails when the directory and `PROGRAM_TYPES` disagree, so
a new type has to be added to both. The corpus is parsed with
`debug_lines=True` (COMPDIR declares `WITH DEBUGGING MODE`; it is the only
program with D lines), so COMPDIR's D-line DISPLAYs are in its AST and it
stays warning-free; `tests/unit/test_debugging_mode_lines.py` pins the
default (dropped + warning), the option on every surface (API, CLI,
cobol.yml, scan, tokenize, batch, the copybook expansion -- with a real
COPY, since a program without one passes through the expander untouched --
and every subcommand that parses COBOL) and `debug_line_numbers` (#334).
`test_all_samples.py` covers the corpus too, since it lives under
`tests/samples/`. The same 22 files are copied into
`mocky-mock/tests/fixtures/enterprise/`, where
`mocky-mock/tests/unit/test_enterprise_corpus.py` pins `mockymock generate`'s
outcome per program (that path is in the *sibling* repo, not this one).

`tests/unit/test_enterprise_syntax.py` pins each construct the corpus
surfaced in isolation: PROGRAM-ID attributes, OO units, DECLARATIVES,
`USE BEFORE REPORTING`, the 6.x data clauses, `OCCURS UNBOUNDED`, JSON
`CONVERTING`, `RETURNING`, `SET ADDRESS OF`, conditional compilation by
default, and REPLACE partial words. Tests elsewhere rely on three behaviours
the corpus required: a missing period after the `PROGRAM-ID` keyword is
tolerated (IBM), the mandatory-PROGRAM-ID message names CLASS-ID /
METHOD-ID too, and an unknown `>>` directive is blanked rather than passed
through.

## Writing tests

Conventions and traps that have each cost real debugging time:

* **Column 72 in fixed-format fixtures.** `normalize_fixed_format` drops
  columns 73+ exactly as a compiler does, silently. A test template that
  appends a clause to a deep-indented line (an FD's `RECORD` clause, an
  `OCCURS ... DEPENDING ON <var>`) loses it with no error; put the clause on
  its own line. `test_all_samples.py::TestSampleCorpus` fails any
  `tests/samples/*.cbl` with **non-whitespace** past column 72 (trailing
  spaces are allowed: dropping them changes nothing) and requires every
  sample to parse error-free except the two in `EXPECTED_PARSE_ERRORS`
  (`error_recovery_tests.cbl`, purpose-built malformed input;
  `special_names_config.cbl`, a non-ASCII `¥` currency symbol the lexer
  rejects). Sample programs feed thousands of other tests, so a truncated
  sample silently changes what they assert against.
* **Self-maintaining registries.** Registering a statement parser means
  adding a `FIXTURES` entry to `tests/regression/test_swallow_sweep.py` and
  an `EXPECTED_ORDER` position plus a `DISPATCH_CASES` case to
  `tests/unit/test_procedure_registry_dispatch_order.py`; both fail when a
  parser has no fixture. A new enterprise program type goes in both the
  directory and `PROGRAM_TYPES`. A new `cobolparser/` file needs an
  `OKF_MAP` entry ([OKF guards](#okf-guards)).
* **Contract key sets and goldens.** An additive key on a public shape is
  pinned in the matching `tests/contracts/` key set (e.g.
  `test_copybook_data_generator_contract.py`'s `_FIELD_SPEC_KEYS`), and
  `tests/regression/test_fixturedemo_golden.py`'s golden bundle is
  regenerated when its serialized shape changes (check no generated value
  moved).
* **Record-image fixtures come from the encoder.** Decode / compare tests
  build their inputs with `encode_record`, not hand-built decode results, so
  a round trip is what is tested. Encoding values were checked against
  GnuCOBOL; a new expected byte string should be too.
* **Positive controls for negative assertions.** An "X is not reported"
  test should also declare something that *is* reported (an unused
  `WS-DEAD`), so a parser regression that drops the declarations cannot make
  it pass vacuously.
* **Pure/Cython parity.** Behaviour mirrored in `_preprocess_fast.pyx` /
  `_lexer_fast.pyx` / `_data_fast.pyx` (column-72 quote rule, continuation
  across a comment line, `*>` stripping, V-line comments) needs its
  regression file run once with the extensions built and
  `COBOLPARSER_ACCEL=1`. Accelerator-specific tests `importorskip` the
  extension. `test_data_fast_signature_drift.py` counts the
  `parse_data_item` call's arguments with `ast` because
  `_DATA_FAST_ARG_COUNT` is a third copy of that arity; a stale extension
  must be reported through `logger`, not `warnings.warn` (a `-W error`
  subprocess test pins that `import cobolparser` survives).
* **Process pools under coverage.** `field-impact` CLI tests pass
  `--workers 1`: scan's process pool under pytest-cov fails to pickle its
  work items. `jcl-parser` is in `[dev]`, but jcl end-to-end tests still
  `importorskip("jclparser")`.
* **Patching file reads.** The expander opens files itself, so patching
  `Path.read_text` affects only helpers that use it (e.g. lint's column
  re-read) -- useful, but check which reader a test actually patches.
* **Changing a pinned behaviour.** When a fix inverts what a test pinned,
  replace the old test (and name the new behaviour in it) rather than
  deleting it; the archive in [history](history/tests.md) records which
  tests changed meaning and why.

## Where behaviour is pinned

Notable test files by area, beyond those in the layout above. Most
regression files are named for their issue (`test_issue_NNN_*.py`) or audit
(`test_audit_<date>*.py`, `test_bug_hunt_*.py`); grep
[history](history/tests.md) for a file name to find what it pins and why.

| Area | Test files |
|------|-----------|
| Preprocessing / COPY / REPLACE | `regression/test_audit_2026_09_17_preprocessing.py` (record-only line splitting, EBCDIC NL, REPLACING text words), `test_copy_member_case_folding.py`, `test_copy_replacing_identifier_operand.py`, `test_copy_replacing_literal_operand.py`, `test_comment_entry_copy_replace_scan.py`, `test_replace_before_identification_division.py`, `test_tagged_sequence_area_detection.py`, `test_expansion_width_and_tags.py`, `test_version_tag_line_handling.py`, `test_normalize_column_overflow_warning.py`, `test_fixed_format_word_boundary_overflow.py`, `test_conditional_compilation_literals.py`, `test_expansion_source_map_and_comments.py`; `unit/test_preprocess_init_coverage.py::TestValidateCopybookContent` |
| Lexer / literals | `regression/test_inline_comment_stripping.py`, `test_literal_concatenation.py`, `test_doubled_quote_literal_values.py`, `test_dead_keyword_removal.py` |
| Parser statements | `regression/test_swallow_sweep.py`, `test_keyword_line_breaks.py` (#385), `test_condition_expression_separators.py` (#386), `test_optional_keyword_forms.py` / `_402.py`, `test_evaluate_*` (stacked / figurative / word-operator WHEN), `test_arithmetic_qualifier_chain.py`, `test_move_qualifier_chain.py`, `test_tier8_arithmetic_scope_terminator.py`, `test_special_register_paragraph_boundary.py`, `test_go_depending_without_on.py`, `test_issue_258_same_named_items.py`, `test_implicit_paragraph_trailing_period.py` (#503); `unit/test_perform_until_newline.py`, `test_call_using_mode_without_by.py`, `test_compute_bare_size_error.py`, `test_report_section.py`, `test_xml_json_structured_clauses.py` (incl. `CONVERTING x [FROM or TO] JSON BOOLEAN` before ON EXCEPTION, #574), `test_extended_verb_parsers.py` |
| EXEC SQL | `unit/test_exec_sql_fetch_orientation.py`, `_host_variable_lists.py`, `_literals_comments.py`, `_merge_cte.py`, `_qualified_tables.py` |
| Dead code / program flow | `unit/analysis/test_dead_code.py` (`TestTransitiveDeadCode`, `TestSectionExitGoTo`, `TestFallThroughReferences`, `TestFallThroughEdges`), `test_program_flow.py`, `test_exit_section_and_alterable_goto.py`, `test_cics_terminators.py`, `test_sql_whenever_references.py` |
| Other analyzers | `regression/test_report_writer_file_output_issue_499.py` (Report Writer INITIATE/GENERATE/TERMINATE in CRUD, IOLogger, io-sequence, boundaries, lineage, #499), `unit/analysis/test_unused_variables.py`, `test_io_sequence*.py`, `test_move_type_checker.py`, `test_xref.py` (incl. level-88s under a FILLER and level-66 RENAMES, #485, also pinned in `test_field_lineage.py` and the MCP `explain_symbol` tests), `test_business_rules.py`, `test_redundancy.py`, `test_technical_debt.py`, `test_codebase.py`, `test_ast_diff.py`, `test_sql_cics_lint.py`, `test_ims_ssa_segment_resolution.py`, `test_linkage_checker.py`, `test_lint.py`; `unit/test_ims_segment_analyzer.py`, `test_value_tracker.py`, `test_issue_564_dynamic_call_incomplete.py` (dynamic CALL targets: LINKAGE / READ / SQL / CICS receivers, MOVE fixpoint) |
| Field lineage | `unit/analysis/test_field_lineage.py` (incl. a RENAMES item traced through its THRU range, and the caveat when it cannot be placed, #485; the MCP `explain_symbol` tests pin its byte range too), `test_lineage_graph.py`, `test_lineage_jcl.py`, `test_sql_flow.py`; `unit/cli/test_lineage_cli.py`; `regression/test_same_record_area_issue_497.py` (SAME RECORD AREA aliasing, lineage + constant folding); samples in `tests/samples/lineage/` |
| Record data | `unit/generators/data/test_encoding.py` (`TestHexLiteralBytes`, `TestFiller`, `TestDbcsCaveat`), `test_editing.py`, `test_variable_length.py`, `test_layout_offsets.py`, `test_compare.py`, `test_views.py`, `test_decoding.py`; `regression/test_fd_lrecl_framing_issue_362.py`; gen-fixtures scenario planning: `regression/test_issue_509_unmodeled_arms.py` (an unmodeled WHEN OTHER / SEARCH AT END is missed, `--strict` exits 2; a WHEN OTHER after not-boundary-fed WHENs is missed for their reason, `--strict` exits 0) |
| CLI | `unit/cli/test_output_identification.py`, `test_source_format_flag.py`, `test_profile_output_flags.py`, `test_analyzer_cli_gaps.py`, `test_new_subcommands.py`, `test_lint_subcommand.py`, `test_expand_source_map_cli.py`, `test_gen_data_cli.py`, `test_compare_cli.py`, `test_record_layout_copy_expansion.py`, `test_jcl_cli.py`, `test_project_config_cli.py`; `unit/test_config_yaml.py`, `test_project_config.py` |
| Program units / models | `regression/test_nested_program_units.py`, `unit/test_models.py` (`from_json` lossy warning, `TestNodeEquality`) |
| Accelerators | `unit/test_fast_import.py`, `regression/test_data_fast_signature_drift.py` |
| MCP server | `unit/mcp_server/test_mcp_tools.py` (no SDK: guard, cache incl. a copybook added after a miss, caveats incl. one missing member among several, `cobol.yml` re-read on edit, `TestConfigCannotWidenTheGuard` (#544: `copybook_path: [/]` reads nothing outside, a parent-dir `cobol.yml` ignored, an outside copybook dir serves `FOO.cpy` / an extensionless member but not `secret.txt` or dotfiles, `..` and symlinks out refused, home / its ancestors / root ancestors / hidden / system dirs refused, `--config` under the same rules, the refused-directory caveat), each tool, copybook fields linted as info like the CLI, special registers), `program_brief` / `callers_of` / `record_layout` (every cited line checked against the file; PERFORM THRU, FILLER, a failing analyzer, reachability agreeing with dead-code after a PERFORMed paragraph or THRU range, #486), `test_mcp_codebase.py` (the root-wide indexes: what counts as a program, built once and kept out of the parse cache, rebuilt on an added or edited program; symlinks out of the root skipped, progress while indexing;
program-level `callers_of` incl. dynamic CALLs, a dynamic CICS LINK and a duplicate PROGRAM-ID; copybook impact with COPY lines; field lineage across a CALL and a JCL job, with and without jcl-parser, and through an expanded copybook; `codebase_overview` incl. clones across programs), `test_mcp_server.py` (in-memory client session, a slow tool not blocking the loop, progress notifications, `cobol-parser mcp` incl. the refused-directory stderr warning). The directory is not `unit/mcp/`: a test package named `mcp` shadows the SDK |

## Coverage Requirement Detail

From `pyproject.toml`:

```toml
addopts = [
    "--strict-markers",
    "--cov=cobolparser",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=90",
]
```

Branch coverage is also enabled (`[tool.coverage.run] branch = true`,
`source = ["cobolparser"]`). No coverage baselines are stored in the repo
(there is no `baselines/` directory); the floor above is the only gate.

**Measure coverage on the pure-Python backend.** coverage.py cannot see into
a compiled Cython extension, so with the accelerators in use the pure-Python
bodies they shadow read as unexecuted: same suite, same commit, measured
2026-09-07, **54.32%** with the extensions in use vs **91.76%** without.
Pure Python is the default -- a built `*.so` is ignored unless
`COBOLPARSER_ACCEL=1` is set at import time -- so a plain `python -m
pytest tests/` measures correctly. Run the accelerated suite separately with
`COBOLPARSER_ACCEL=1 ... --no-cov`. Accelerator-specific tests
(`tests/unit/test_fast_import.py`,
`tests/regression/test_data_fast_signature_drift.py`, the parity checks)
`importorskip` the extension and set the variable themselves where needed.

**Timing assertions and coverage.** `tests/performance/test_factory_performance.py`
guards its two absolute nodes/sec floors (100,000) with `requires_untraced`
(`skipif("sys.gettrace() is not None")`). Under coverage.py's tracer the
suite took 950 s instead of 94 s, and `test_factory_throughput` measured
64,243 nodes/sec against its 100,000 floor on a CI runner that clears it
comfortably uninstrumented -- the number describes the tracer, not the
factory. Any `--no-cov` run (e.g. CI's `build` job) enforces the floors;
only a coverage run skips them. The ratio-based overhead assertion is
unaffected.

## CI/CD

> **Currently disabled.** Every line of `.github/workflows/ci.yml` is
> commented out (commit `315d474`, "refactor(ci): comment out CI
> configuration"). No lint, typecheck, test or coverage job runs on push or
> PR; run them locally. The job definitions below are what the file
> describes and what runs once it is uncommented. `release-please.yml` is
> still active.

Triggers (as written): push/PR to `main`, a nightly `schedule`
(`17 4 * * *`) and manual `workflow_dispatch`. Push and PR triggers carry
`paths-ignore` for `docs/**`, `.okf/**`, `reports/**` and `**/*.md`, so a
docs-only change runs no CI. A new push to a PR cancels the run in flight
(`concurrency`); runs on `main` are never cancelled.

1. **lint** -- `ruff check .` + `black --check .` (Python 3.13, `ruff==0.15.0`
   / `black==26.3.0`, pinned to match `.pre-commit-config.yaml`)
2. **typecheck** -- `mypy cobolparser/` (Python 3.13, `mypy==1.20.0`)
3. **build** -- `pip install -e ".[dev,fast]"` +
   `COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace` +
   `COBOLPARSER_ACCEL=1 python -m pytest <targets> -q -p no:randomly -n auto --no-cov`
   on matrix Python 3.11, 3.12, 3.13, on every trigger. Its job is to run the
   suite *through the Cython extensions* (hence the variable at both ends,
   and `--no-cov`). The full `tests/` suite runs on all three for a push to
   `main`, the nightly run and a dispatch; on a **PR** only 3.13 runs the
   full suite, and 3.11/3.12 run a smoke subset (`tests/unit/test_lexer.py
   tests/test_all_samples.py tests/unit/test_program_fixtures.py`). The
   nightly full matrix is what catches a 3.11/3.12-only break that slipped
   through a PR.
4. **coverage** -- `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"` +
   `python -m pytest tests/ -q -p no:randomly -n auto` on Python 3.13
   (`if: github.event_name != 'push'`: PRs, nightly and dispatch). This is
   where the 90% floor (from `addopts`) is enforced, on a pure-Python
   install, for the reason in [Coverage](#coverage-requirement-detail).
   (`COBOLPARSER_SKIP_EXT=1` is belt and braces: without
   `COBOLPARSER_ACCEL=1` nothing is compiled anyway.)

`-n auto` keeps each test job near two minutes; `-p no:randomly` keeps a
failure reproducible from the log (pytest-randomly is not a declared
dependency; the flag is a no-op without it). The `build`/`coverage` split
exists because a single job cannot both exercise the extensions and measure
coverage; with CI disabled, nothing enforces the floor unless it is run
locally.

Release builds are a separate workflow,
`.github/workflows/release-please.yml`: release-please cuts the release from
Conventional Commits, then `cibuildwheel` builds wheels (manylinux x86_64,
macOS arm64, Windows AMD64 x CPython 3.11-3.13, with
`environment = { COBOLPARSER_ACCEL = "1" }` so the three Cython accelerators
are compiled; every other module ships as `.py`) and a `build-sdist` job
builds the sdist; both are published to PyPI as `cobol-parser` via Trusted
Publishing. `[tool.cibuildwheel]`'s `test-command` imports the three
extensions, sets `COBOLPARSER_ACCEL=1` and asserts the fast lexer is swapped
in, then runs `tests/unit/test_lexer.py tests/test_all_samples.py
tests/unit/test_program_fixtures.py --no-cov` against the installed wheel.
There is no closed-source release mode; the package is AGPL-3.0-or-later.

## OKF guards

`tests/test_okf_staleness_map.py` pins `scripts/okf_staleness_check.py`'s
`OKF_MAP`: every tracked `.py`/`.pyx` under `cobolparser/` must map to at
least one OKF file, every mapped OKF file must exist, and every prefix that
names a directory must end with `/`. (`tests/` itself maps to this file.)

A file missing from that map is a file whose documentation can rot
silently, because the pre-commit hook never asks for an update when it
changes. The directory-slash assertion matters both ways: a prefix such as
`cobolparser/parsers/` never matches `cobolparser/parser.py` (so that file
needs its own entry), and dropping the slash would make
`cobolparser/parsers` swallow `cobolparser/parser.py` instead.

`tests/test_okf_claims.py` runs `scripts/okf_check.py` over every OKF file
and CLAUDE.md, one test per file: imports written in the docs must run,
backticked names/paths must exist, links and anchors must resolve, the CLI
table in `cli.md` must match argparse, and every `<!-- okf:gen NAME -->`
span must equal its generator's output. A failure after a code change is
either a doc that needs a real edit or a generated span to refresh with
`python scripts/okf_check.py --write`. Its `TestCheckerCatchesDrift` class
pins that each check still flags the drift it exists for.

## See also

* [cli.md](cli.md) -- `tests/unit/cli/` covers CLI subcommands
* [generators.md](generators.md) -- flowchart, copybook -> CSV, record
  encoding/decoding, program layout index, and fixture bundle tests
* [analysis.md](analysis.md) -- `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) -- `tests/integration/` covers end-to-end parsing
* [lexer.md](lexer.md) -- the `COBOLPARSER_ACCEL` switch and pure/Cython parity
* `tests/unit/cli/test_gen_data_cli.py::TestRecordImageFormats` -- the
  `gen-data --format record|hex` flags, that CSV output is unchanged by any
  of them, and (counting `encode_record` calls) that `--output` encodes the
  dataset exactly once. `::TestRecordFormatFlag` covers `--record-format`
  alongside it
* `tests/unit/cli/test_record_layout_copy_expansion.py` (#592) -- a COPY
  nested in a copybook or under an FD is expanded by `gen-data` / `decode` /
  `compare` from `--copybook-path` or `cobol.yml`, and one left unexpanded
  is a stderr warning and a caveat, never a silently short record
* `tests/unit/generators/data/test_variable_length.py` -- fixed vs variable
  record length: ODO layout linking, per-row trimming, counter bounds, RDW
  framing, and the length reporting built on them.
  `TestFdRangeWithoutDependingOn` (#320) pins that an FD range with no
  DEPENDING ON writes every record at its own 01's full length, never cut
* [history](history/tests.md) -- the archived dated change log: per test
  file, what it pins and why
